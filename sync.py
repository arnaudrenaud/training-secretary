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
from datetime import date, datetime, timedelta, timezone

import dateparser
import requests
from dotenv import load_dotenv

load_dotenv()
import garth
import gspread
from google.oauth2.service_account import Credentials


def get_garmin_resting_hr(target_date: date) -> int | None:
    """Fetch resting heart rate for a specific date from Garmin Connect."""
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")

    if not email or not password:
        raise ValueError("GARMIN_EMAIL and GARMIN_PASSWORD environment variables required")

    # Authenticate with Garmin
    garth.login(email, password)

    # Fetch heart rate data for the target date
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
            kj = activity.get("kilojoules") or activity.get("calories") or 0
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


def main():
    """Main function to sync training data to Google Sheets."""
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID environment variable required")

    # Default to yesterday's date
    target_date = date.today() - timedelta(days=1)

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

    # Connect to Google Sheets
    print("\n--- Writing to Google Sheets ---")
    sheet = get_google_sheet(sheet_id)

    # Find the row for the target date
    row_num = find_row_by_date(sheet, target_date)

    if row_num is None:
        print(f"No row found for date {target_date.isoformat()}")
        sys.exit(1)

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
        sys.exit(1)

    print("\nSync complete!")


if __name__ == "__main__":
    main()
