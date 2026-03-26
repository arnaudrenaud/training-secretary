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
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

import dateparser
import requests
from dotenv import load_dotenv

load_dotenv()
import garth
import gspread
from google.oauth2.service_account import Credentials


def _write_garmin_tokens():
    from dataclasses import asdict
    with open("/tmp/garmin_oauth1_token.json", "w") as f:
        json.dump(asdict(garth.client.oauth1_token), f)
    with open("/tmp/garmin_oauth2_token.json", "w") as f:
        json.dump(asdict(garth.client.oauth2_token), f)


def garmin_login():
    """Authenticate with Garmin once.

    Prefers token-based auth (GARMIN_OAUTH1_TOKEN + GARMIN_OAUTH2_TOKEN env vars)
    to avoid 429 rate limiting from repeated password logins in CI.
    Falls back to password login if tokens are not set.
    """
    oauth1 = os.environ.get("GARMIN_OAUTH1_TOKEN")
    oauth2 = os.environ.get("GARMIN_OAUTH2_TOKEN")

    if oauth1 and oauth2:
        token_dir = tempfile.mkdtemp()
        with open(os.path.join(token_dir, "oauth1_token.json"), "w") as f:
            f.write(oauth1)
        with open(os.path.join(token_dir, "oauth2_token.json"), "w") as f:
            f.write(oauth2)
        garth.resume(token_dir)
        # Pre-exchange the OAuth2 token if expired so all subsequent connectapi()
        # calls share the same fresh token (avoids each call triggering its own
        # exchange and hitting Garmin's rate limit on /oauth-service/oauth/exchange).
        if garth.client.oauth2_token is None or garth.client.oauth2_token.expired:
            try:
                garth.client.refresh_oauth2()
                # Write refreshed tokens so the CI workflow can persist them back
                # to secrets, ensuring the next run starts with a valid token.
                _write_garmin_tokens()
                print("Garmin OAuth2 token refreshed and saved.")
            except Exception as e:
                print(f"Warning: could not pre-exchange Garmin OAuth2 token: {e}")
        return

    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")

    if not email or not password:
        raise ValueError(
            "Either GARMIN_OAUTH1_TOKEN+GARMIN_OAUTH2_TOKEN or GARMIN_EMAIL+GARMIN_PASSWORD are required"
        )

    garth.login(email, password)
    _write_garmin_tokens()


def get_garmin_resting_hr(target_date: date) -> int | None:
    """Fetch resting heart rate for a specific date from Garmin Connect."""
    date_str = target_date.isoformat()
    try:
        hr_data = garth.connectapi(f"/usersummary-service/usersummary/daily?calendarDate={date_str}")
        resting_hr = hr_data.get("restingHeartRate")
        return resting_hr
    except Exception as e:
        print(f"Error fetching heart rate data: {e}")
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


def sync_date(target_date: date, sheet) -> bool:
    """Sync data for a specific date. Returns True if any data was written."""
    print(f"\n{'='*50}")
    print(f"Fetching data for {target_date.isoformat()}...")

    # Get resting heart rate from Garmin
    print("\n--- Garmin Resting Heart Rate ---")
    resting_hr = get_garmin_resting_hr(target_date)
    if resting_hr:
        print(f"Resting heart rate: {resting_hr} bpm")
    else:
        print("No resting heart rate data available.")

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

    # Write data to sheet
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

    # Connect to Google Sheets once
    sheet = get_google_sheet(sheet_id)

    # Authenticate with Garmin once (avoid 429 rate limiting from multiple logins)
    garmin_login()

    # Process yesterday and the day before yesterday
    target_dates = [
        date.today() - timedelta(days=2),  # Day before yesterday
        date.today() - timedelta(days=1),  # Yesterday
    ]

    any_data_written = False
    for target_date in target_dates:
        if sync_date(target_date, sheet):
            any_data_written = True

    if not any_data_written:
        print("\nNo data written for any date.")
        sys.exit(1)

    print("\nSync complete!")


if __name__ == "__main__":
    main()
