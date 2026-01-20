#!/usr/bin/env python3
"""
Sync training data to Google Sheets.

Fetches:
- Resting heart rate from Garmin Connect
- Commute cycling workload (kJ) from Strava

Writes values to the corresponding row in Google Sheets (matching by date).
"""

import base64
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


def get_strava_commute_workload(target_date: date) -> int | None:
    """Fetch total workload (kJ) from Strava cycling commutes for a specific date."""
    access_token = get_strava_access_token()
    if not access_token:
        print("Strava credentials not configured, skipping commute workload.")
        return None

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

    # Filter for cycling commutes and sum kilojoules
    total_kj = 0
    commute_count = 0
    for activity in activities:
        if activity.get("type") == "Ride" and activity.get("commute"):
            kj = activity.get("kilojoules", 0) or 0
            total_kj += kj
            commute_count += 1
            print(f"  Commute: {activity.get('name')} - {kj:.0f} kJ")

    if commute_count == 0:
        print("No cycling commutes found for this date.")
        return None

    return int(total_kj)


def get_google_sheet(sheet_id: str):
    """Authenticate and return the Google Sheet."""
    service_account_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

    if not service_account_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable required")

    # Decode base64 service account credentials
    try:
        credentials_dict = json.loads(base64.b64decode(service_account_json))
    except Exception:
        # Try as plain JSON (for local testing)
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

    # Get commute workload from Strava
    print("\n--- Strava Commute Workload ---")
    commute_kj = get_strava_commute_workload(target_date)
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

    if commute_kj:
        sheet.update_cell(row_num, 10, commute_kj)  # Column J
        print(f"Wrote commute workload ({commute_kj} kJ) to column J")

    if not resting_hr and not commute_kj:
        print("No data to write.")
        sys.exit(1)

    print("\nSync complete!")


if __name__ == "__main__":
    main()
