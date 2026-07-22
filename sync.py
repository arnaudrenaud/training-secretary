#!/usr/bin/env python3
"""
Sync training data to Google Sheets.

Fetches:
- Resting heart rate from Garmin Connect
- Commute cycling workload (kJ) from Strava

Writes values to the corresponding row in Google Sheets (matching by date).
"""

import json
import os
import tempfile
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

import dateparser
import garth
import requests
from dotenv import load_dotenv

load_dotenv()
import gspread
from google.oauth2.service_account import Credentials


def _write_garmin_tokens() -> None:
    """Write current Garmin OAuth tokens for the workflow to persist as secrets."""
    if garth.client.oauth1_token:
        with open("/tmp/garmin_oauth1_token.json", "w") as f:
            json.dump(asdict(garth.client.oauth1_token), f)
    if garth.client.oauth2_token:
        with open("/tmp/garmin_oauth2_token.json", "w") as f:
            json.dump(asdict(garth.client.oauth2_token), f)


def garmin_login() -> bool:
    """Authenticate with Garmin once.

    Garmin frequently rate-limits OAuth refresh/login in CI. Treat Garmin auth
    failures as a missing data source rather than failing the entire sync; Strava
    workload and Google Sheets updates can still succeed.
    """
    oauth1 = os.environ.get("GARMIN_OAUTH1_TOKEN")
    oauth2 = os.environ.get("GARMIN_OAUTH2_TOKEN")

    if oauth1 and oauth2:
        try:
            token_dir = tempfile.mkdtemp()
            with open(os.path.join(token_dir, "oauth1_token.json"), "w") as f:
                f.write(oauth1)
            with open(os.path.join(token_dir, "oauth2_token.json"), "w") as f:
                f.write(oauth2)
            garth.resume(token_dir)

            # Pre-exchange the OAuth2 token if expired so subsequent connectapi()
            # calls share the same fresh token. If Garmin rate-limits this, skip
            # HR for this run instead of falling back to another rate-limited login.
            if garth.client.oauth2_token is None or garth.client.oauth2_token.expired:
                garth.client.refresh_oauth2()
                _write_garmin_tokens()
                print("Garmin OAuth2 token refreshed and saved.")
            return True
        except Exception as e:
            print(f"Warning: Garmin token authentication failed ({e}); skipping Garmin HR.")
            return False

    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")

    if not email or not password:
        print("Garmin credentials not configured, skipping resting heart rate.")
        return False

    try:
        garth.login(email, password)
        _write_garmin_tokens()
        return True
    except Exception as e:
        print(f"Warning: Garmin password login failed ({e}); skipping Garmin HR.")
        return False


def get_garmin_resting_hr(target_date: date) -> int | None:
    """Fetch resting heart rate for a specific date from Garmin Connect."""
    date_str = target_date.isoformat()
    try:
        hr_data = garth.connectapi(f"/usersummary-service/usersummary/daily?calendarDate={date_str}")
        return hr_data.get("restingHeartRate")
    except Exception as e:
        print(f"Warning: error fetching Garmin heart rate data ({e}); skipping Garmin HR for {date_str}.")
        return None


def get_strava_access_token() -> str | None:
    """Get a fresh Strava access token using the refresh token."""
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    refresh_token = os.environ.get("STRAVA_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        return None

    response = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )

    if response.status_code == 403:
        print(
            "Strava refused the token refresh (HTTP 403). "
            "The STRAVA_REFRESH_TOKEN GitHub secret is likely expired or revoked; "
            "generate a new token with activity:read_all and activity:write scopes. "
            "Skipping Strava work for this run."
        )
        return None

    response.raise_for_status()
    return response.json()["access_token"]


def get_strava_cycling_workloads(target_date: date) -> tuple[int | None, int | None]:
    """
    Fetch cycling workloads from Strava for a specific date.

    Returns:
        tuple: (non_commute_kj, commute_kj) - workload for training rides and commutes
    """
    access_token = get_strava_access_token()
    if not access_token:
        print("Strava credentials not configured, skipping cycling workload.")
        return None, None

    # Get activities for the target date
    start_of_day = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    end_of_day = start_of_day + timedelta(days=1)

    response = requests.get(
        "https://www.strava.com/api/v3/athlete/activities",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "after": int(start_of_day.timestamp()),
            "before": int(end_of_day.timestamp()),
        },
    )
    response.raise_for_status()
    activities = response.json()

    # Separate cycling activities into commute and non-commute
    commute_kj = 0
    non_commute_kj = 0
    commute_count = 0
    non_commute_count = 0

    for activity in activities:
        activity_type = activity.get("type")
        sport_type = activity.get("sport_type")
        # Include all cycling activities (outdoor, virtual, and indoor)
        if activity_type in ("Ride", "VirtualRide") or sport_type == "IndoorCycling":
            kj = activity.get("kilojoules")
            # Fetch detailed activity to get calories if kilojoules not available
            if not kj:
                detail_response = requests.get(
                    f"https://www.strava.com/api/v3/activities/{activity['id']}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                detail_response.raise_for_status()
                detail = detail_response.json()
                kj = detail.get("kilojoules") or detail.get("calories") or 0
            kj = kj or 0
            if activity.get("commute"):
                commute_kj += kj
                commute_count += 1
                print(f"  Commute: {activity.get('name')} - {kj:.0f} kJ")
            else:
                non_commute_kj += kj
                non_commute_count += 1
                print(f"  Training: {activity.get('name')} - {kj:.0f} kJ")

    if commute_count == 0 and non_commute_count == 0:
        print("No cycling activities found for this date.")
        return None, None

    return (
        int(non_commute_kj) if non_commute_count > 0 else None,
        int(commute_kj) if commute_count > 0 else None,
    )


def get_google_sheet(sheet_id: str):
    """Authenticate and return the Google Sheet."""
    service_account_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

    if not service_account_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable required")

    credentials_dict = json.loads(service_account_json)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
    client = gspread.authorize(credentials)

    return client.open_by_key(sheet_id).sheet1


def find_row_by_date(sheet, target_date: date) -> int | None:
    """
    Find the row number matching the target date.

    Handles French locale date format (e.g., "mar. 20 janv. 2026").
    """
    date_column = sheet.col_values(1)  # Column A

    for row_num, cell_value in enumerate(date_column, start=1):
        if not cell_value:
            continue

        # Parse the date using dateparser (handles French locale)
        parsed_date = dateparser.parse(cell_value, languages=["fr"])

        if parsed_date and parsed_date.date() == target_date:
            return row_num

    return None


def sync_date(target_date: date, sheet, garmin_available: bool) -> bool:
    """Sync data for a specific date. Returns True if any data was written."""
    print(f"\n{'='*50}")
    print(f"Fetching data for {target_date.isoformat()}...")

    # Get resting heart rate from Garmin
    resting_hr = None
    if garmin_available:
        print("\n--- Garmin Resting Heart Rate ---")
        resting_hr = get_garmin_resting_hr(target_date)
        if resting_hr:
            print(f"Resting heart rate: {resting_hr} bpm")
        else:
            print("No resting heart rate data available.")
    else:
        print("\n--- Garmin Resting Heart Rate ---")
        print("Garmin unavailable, skipping resting heart rate.")

    # Get cycling workloads from Strava
    print("\n--- Strava Cycling Workload ---")
    training_kj, commute_kj = get_strava_cycling_workloads(target_date)
    if training_kj:
        print(f"Total training workload: {training_kj} kJ")
    if commute_kj:
        print(f"Total commute workload: {commute_kj} kJ")

    # Find the row for the target date
    print("\n--- Writing to Google Sheets ---")
    row_num = find_row_by_date(sheet, target_date)

    if row_num is None:
        print(f"No row found for date {target_date.isoformat()}")
        return False

    print(f"Found date at row {row_num}")

    if resting_hr:
        sheet.update_cell(row_num, 2, resting_hr)  # Column B
        print(f"Wrote resting HR ({resting_hr}) to column B")

    if training_kj:
        sheet.update_cell(row_num, 9, training_kj)  # Column I
        print(f"Wrote training workload ({training_kj} kJ) to column I")

    if commute_kj:
        sheet.update_cell(row_num, 10, commute_kj)  # Column J
        print(f"Wrote commute workload ({commute_kj} kJ) to column J")

    if not resting_hr and not training_kj and not commute_kj:
        print("No data to write.")
        return False

    return True


def main():
    """Main function to sync training data to Google Sheets."""
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID environment variable required")

    sheet = get_google_sheet(sheet_id)
    garmin_available = garmin_login()

    # Process yesterday and the day before yesterday
    target_dates = [
        date.today() - timedelta(days=2),  # Day before yesterday
        date.today() - timedelta(days=1),  # Yesterday
    ]

    any_data_written = False
    for target_date in target_dates:
        if sync_date(target_date, sheet, garmin_available):
            any_data_written = True

    if not any_data_written:
        print("\nNo data to write for any date.")

    print("\nSync complete!")


if __name__ == "__main__":
    main()
