# Google Sheets Setup

## 1. Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **Select a project** → **New Project**
3. Enter a project name and click **Create**

## 2. Enable APIs

1. Go to **APIs & Services** → **Library**
2. Search for and enable:
   - **Google Sheets API**
   - **Google Drive API**

## 3. Create a Service Account

1. Go to **IAM & Admin** → **Service Accounts**
2. Click **Create Service Account**
3. Enter a name (e.g., "training-secretary") and click **Create and Continue**
4. Skip the optional steps and click **Done**

## 4. Create a JSON Key

1. Click on your new service account
2. Go to the **Keys** tab
3. Click **Add Key** → **Create new key**
4. Select **JSON** and click **Create**
5. Save the downloaded file as `service-account.json`

## 5. Get Environment Variables

### `GOOGLE_SERVICE_ACCOUNT_JSON`

Copy the contents of `service-account.json`.

### `GOOGLE_SHEET_ID`

From your spreadsheet URL:

```
https://docs.google.com/spreadsheets/d/SHEET_ID_HERE/edit
```

Copy the `SHEET_ID_HERE` part.

## 6. Share Your Sheet

1. Open your Google Sheet
2. Click **Share**
3. Add the service account email (found in the JSON file as `client_email`)
4. Give it **Editor** access
