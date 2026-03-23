# Admin User Setup

## Problem
The app was always asking to create the first admin user even when one already existed. This happened because on Streamlit Cloud, the file system is ephemeral and gets reset on app restarts/deployments.

## Solution
The app now supports two ways to ensure the admin user persists:

### Option 1: Streamlit Secrets (Recommended for Streamlit Cloud)

1. Go to your Streamlit Cloud dashboard
2. Navigate to your app → Settings → Secrets
3. Add the following configuration:

```toml
[admin]
email = "your-admin@email.com"
password = "your-secure-password"
```

4. Save and restart the app

The admin user will be automatically created from these credentials on app startup if no users exist yet. This ensures the admin always exists, even after app restarts.

### Option 2: Local File Storage (For Local Development)

When running locally, the app stores users in `data/users.json`. This file persists between runs on your local machine but not on Streamlit Cloud.

## How It Works

1. On app startup, `require_login()` checks if admin credentials exist in Streamlit Secrets
2. If secrets are configured and no users exist, it auto-creates the admin user
3. If secrets are not configured, it shows the setup screen to manually create the admin
4. Once created (either way), subsequent logins go directly to the login screen

## Testing

To test locally without secrets:
1. Delete `data/users.json`
2. Run the app
3. Create an admin user
4. Restart the app
5. Verify it goes to login screen (not setup screen)

To test with secrets:
1. Create `.streamlit/secrets.toml` with admin credentials (see `.streamlit/secrets.toml.example`)
2. Delete `data/users.json`
3. Run the app
4. Verify admin is auto-created and login screen is shown

## Security Notes

- Never commit `secrets.toml` to version control
- Use strong passwords for admin accounts
- On Streamlit Cloud, secrets are encrypted and secure
- The `data/` directory is excluded from git via `.gitignore`

---

# Upstash Redis Cache (Optional)

The app supports **Upstash Redis** as a cloud cache backend (replaces the local SQLite `kv_cache`).
This improves performance on Streamlit Cloud by persisting cache across reruns and app restarts.

If Upstash is **not** configured the app continues to use the local SQLite cache with no changes.

## Setup (Streamlit Cloud — Recommended)

1. Create a free database at [console.upstash.com](https://console.upstash.com).
2. Copy the **REST URL** and **REST Token** from the database details page.
3. In your Streamlit Cloud app → **Settings → Secrets**, add:

```toml
[upstash]
rest_url   = "https://<your-endpoint>.upstash.io"
rest_token = "<your-token>"
```

4. Save and restart the app. Cache operations will now use Redis automatically.

## Setup (Local Development)

Create or edit `.streamlit/secrets.toml`:

```toml
[upstash]
rest_url   = "https://<your-endpoint>.upstash.io"
rest_token = "<your-token>"
```

Or set environment variables:

```bash
export UPSTASH_REDIS_REST_URL="https://<your-endpoint>.upstash.io"
export UPSTASH_REDIS_REST_TOKEN="<your-token>"
```

## Fallback Behavior

| Scenario | Cache backend used |
|---|---|
| Upstash configured, reachable | Redis (Upstash) |
| Upstash configured, network error | SQLite (automatic fallback) |
| Upstash not configured | SQLite |

## Notes

- Never commit tokens to version control.
- The free Upstash plan supports up to 10,000 requests/day and 256 MB storage — sufficient for typical usage.
- TTL is handled natively by Redis (`EX` option on `SET`); keys without TTL never expire.
