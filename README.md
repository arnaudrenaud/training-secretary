# training-secretary

## Scripts

- `tag_commutes.py` — Tag yesterday's Garmin Forerunner 165 cycling activities on Strava as commutes with Peugeot Professionnel 500
- `sync.py` — Sync yesterday's resting heart rate (Garmin Connect) and cycling workload (Strava, both commute and non-commute) to Google Sheets

## Setup

### Environment

Copy the `.env.example` file to `.env` and fill in the values.

#### Garmin

| Variable          | How to get                   |
| ----------------- | ---------------------------- |
| `GARMIN_EMAIL`    | Your Garmin Connect email    |
| `GARMIN_PASSWORD` | Your Garmin Connect password |

#### Strava

| Variable               | How to get                               |
| ---------------------- | ---------------------------------------- |
| `STRAVA_CLIENT_ID`     | See [Strava setup](docs/strava-setup.md) |
| `STRAVA_CLIENT_SECRET` | See [Strava setup](docs/strava-setup.md) |
| `STRAVA_REFRESH_TOKEN` | See [Strava setup](docs/strava-setup.md) |

#### Google Sheets

| Variable                      | How to get                               |
| ----------------------------- | ---------------------------------------- |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | See [Google setup](docs/google-setup.md) |
| `GOOGLE_SHEET_ID`             | See [Google setup](docs/google-setup.md) |

#### Dependencies

```bash
pip install -r requirements.txt
```

## Run

```bash
python tag_commutes.py
python sync.py
```
