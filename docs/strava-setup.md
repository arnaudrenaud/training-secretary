# Strava API Setup

## 1. Create a Strava App

1. Go to [Strava API Settings](https://www.strava.com/settings/api)
2. Fill in the application details:
   - **Application Name**: e.g., "Training Secretary"
   - **Category**: e.g., "Training"
   - **Website**: any URL (e.g., `http://localhost`)
   - **Authorization Callback Domain**: `localhost`
3. Click **Create**

## 2. Get Client Credentials

From your app settings page, copy:

- **Client ID** → `STRAVA_CLIENT_ID`
- **Client Secret** → `STRAVA_CLIENT_SECRET`

## 3. Get a Refresh Token

### Step 1: Authorize Your App

Open this URL in your browser (replace `YOUR_CLIENT_ID`):

```
https://www.strava.com/oauth/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http://localhost&scope=read,activity:read_all,activity:write
```

### Step 2: Approve Access

Click **Authorize** to grant access.

### Step 3: Get the Authorization Code

You'll be redirected to a URL like:

```
http://localhost/?state=&code=AUTHORIZATION_CODE&scope=read,activity:read_all,activity:write
```

Copy the `AUTHORIZATION_CODE` from the URL.

### Step 4: Exchange for Tokens

Run this command (replace placeholders):

```bash
curl -X POST https://www.strava.com/oauth/token \
  -d client_id=YOUR_CLIENT_ID \
  -d client_secret=YOUR_CLIENT_SECRET \
  -d code=AUTHORIZATION_CODE \
  -d grant_type=authorization_code
```

### Step 5: Copy the Refresh Token

From the JSON response, copy the `refresh_token` value → `STRAVA_REFRESH_TOKEN`
