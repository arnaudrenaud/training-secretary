#!/usr/bin/env python3
"""
Sync Garmin resting heart rate to Google Sheets.

Fetches yesterday's resting heart rate from Garmin Connect and writes it
to the corresponding row in Google Sheets (matching by date).
"""

import base64
import json
import os
import sys
from datetime import date, timedelta

import dateparser
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
    """Main function to sync Garmin HR to Google Sheets."""
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID environment variable required")

    # Default to yesterday's date
    target_date = date.today() - timedelta(days=1)

    print(f"Fetching resting heart rate for {target_date.isoformat()}...")

    # Get resting heart rate from Garmin
    resting_hr = get_garmin_resting_hr(target_date)

    if resting_hr is None:
        print("No resting heart rate data available for this date.")
        sys.exit(1)

    print(f"Resting heart rate: {resting_hr} bpm")

    # Connect to Google Sheets
    print("Connecting to Google Sheets...")
    sheet = get_google_sheet(sheet_id)

    # Find the row for the target date
    row_num = find_row_by_date(sheet, target_date)

    if row_num is None:
        print(f"No row found for date {target_date.isoformat()}")
        sys.exit(1)

    print(f"Found date at row {row_num}")

    # Write heart rate to column B
    sheet.update_cell(row_num, 2, resting_hr)
    print(f"Successfully wrote {resting_hr} to row {row_num}, column B")


if __name__ == "__main__":
    main()
