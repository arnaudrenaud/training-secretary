#!/usr/bin/env python3
"""
Tag Strava outdoor cycling activities as commutes.

Finds outdoor cycling activities from yesterday recorded on Garmin Forerunner 165
and sets them as commutes with the specified bike. Indoor/trainer rides are skipped.
"""

import os
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

DEVICE_NAME = "Garmin Forerunner 165"
BIKE_NAME = "Peugeot Professionnel 500"
BIKE_ID = "b6207119"  # From https://www.strava.com/bikes/6207119


def get_strava_access_token() -> str | None:
    """Get a fresh Strava access token using the refresh token."""
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    refresh_token = os.environ.get("STRAVA_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError("STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, and STRAVA_REFRESH_TOKEN required")

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


def get_activities_from_device(access_token: str, target_date, device_name: str) -> list:
    """Get cycling activities from a specific device for a specific date."""
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

    # Filter for cycling activities - need to get detailed activity for device info
    matching_activities = []
    for activity in activities:
        # Only process outdoor rides (not virtual rides or trainer rides)
        if activity.get("type") != "Ride" or activity.get("trainer"):
            continue

        # Get detailed activity to check device
        detail_response = requests.get(
            f"https://www.strava.com/api/v3/activities/{activity['id']}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        detail_response.raise_for_status()
        detail = detail_response.json()

        device = detail.get("device_name", "")
        if device == device_name:
            matching_activities.append(detail)

    return matching_activities


def update_activity(access_token: str, activity_id: int, gear_id: str) -> bool:
    """Update an activity to be a commute with the specified bike."""
    response = requests.put(
        f"https://www.strava.com/api/v3/activities/{activity_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        data={
            "commute": True,
            "gear_id": gear_id,
        },
    )
    return response.status_code == 200


def tag_commutes_for_date(access_token: str, target_date) -> None:
    """Tag commutes for a specific date."""
    print(f"\n{'='*50}")
    print(f"Looking for cycling activities on {target_date} from {DEVICE_NAME}...")

    # Get activities from the device
    activities = get_activities_from_device(access_token, target_date, DEVICE_NAME)

    if not activities:
        print(f"No cycling activities found from {DEVICE_NAME}.")
        return

    print(f"Found {len(activities)} cycling activity/ies from {DEVICE_NAME}:")

    for activity in activities:
        activity_id = activity["id"]
        name = activity.get("name", "Unnamed")
        already_commute = activity.get("commute", False)
        current_gear = activity.get("gear_id")

        if already_commute and current_gear == BIKE_ID:
            print(f"  - {name}: already tagged as commute with correct bike, skipping")
            continue

        if update_activity(access_token, activity_id, BIKE_ID):
            print(f"  - {name}: tagged as commute with {BIKE_NAME}")
        else:
            print(f"  - {name}: failed to update")


def main():
    """Main function to tag commutes."""
    access_token = get_strava_access_token()
    print(f"Using bike: {BIKE_NAME} ({BIKE_ID})")

    # Process yesterday and the day before yesterday
    target_dates = [
        (datetime.now(timezone.utc) - timedelta(days=2)).date(),  # Day before yesterday
        (datetime.now(timezone.utc) - timedelta(days=1)).date(),  # Yesterday
    ]

    for target_date in target_dates:
        tag_commutes_for_date(access_token, target_date)

    print("\nDone!")


if __name__ == "__main__":
    main()
