# Garmin Heart Rate to Google Sheets Sync

Daily automated sync of resting heart rate from Garmin Connect to Google Sheets.

## Setup

### 1. Google Cloud Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Enable the **Google Sheets API** and **Google Drive API**
4. Go to **IAM & Admin > Service Accounts**
5. Create a new service account
6. Create a JSON key for the service account
7. Share your Google Sheet with the service account email (with Editor access)

### 2. GitHub Repository Secrets

Go to your repository **Settings > Secrets and variables > Actions** and add:

| Secret                        | Description                             |
| ----------------------------- | --------------------------------------- |
| `GARMIN_EMAIL`                | Your Garmin Connect email               |
| `GARMIN_PASSWORD`             | Your Garmin Connect password            |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Base64-encoded service account JSON key |
| `GOOGLE_SHEET_ID`             | The spreadsheet ID from the URL         |

To base64 encode your service account JSON:

```bash
base64 -i service-account.json | tr -d '\n'
```

The Google Sheet ID is in the URL: `https://docs.google.com/spreadsheets/d/SHEET_ID_HERE/edit`

### 3. Google Sheet Format

The script expects:

- **Column A**: Dates in French locale format (e.g., "mar. 20 janv. 2026")
- **Column B**: Where the resting heart rate will be written

## Usage

### Automatic

The GitHub Action runs daily at 3:00 AM UTC.

### Manual Trigger

Go to **Actions > Daily Garmin to Google Sheets Sync > Run workflow**

### Local Testing

```bash
export GARMIN_EMAIL="your-email@example.com"
export GARMIN_PASSWORD="your-password"
export GOOGLE_SERVICE_ACCOUNT_JSON='{"type": "service_account", ...}'
export GOOGLE_SHEET_ID="your-sheet-id"

pip install -r requirements.txt
python sync.py
```
