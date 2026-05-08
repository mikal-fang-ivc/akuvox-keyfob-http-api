# Akuvox Simple Web (FastAPI)

Internal web app for viewing/editing user rows in `keyfobs.csv`(akuvox local user export file), toggling `Schedule-SRelay`, and syncing user updates to an Akuvox device.

## Features

- FastAPI backend + single-page table UI
- Session login
  - `AUTH_MODE=dev` local login
  - `AUTH_MODE=google` Google OAuth OIDC
  - `AUTH_MODE=both` enables local and Google login together
  - role-based authorization from `managers.json`
    - `full` access: everything + manage manager accounts
    - `limited` access: rename and toggle keyfob status
- User operations on CSV `UserData` section
  - Edit `Name`
  - Toggle `Schedule-SRelay` between `1001-2;` (Always) and `1002-2;` (Never)
- CSV safety behavior
  - Writes only modified user row
  - Atomic replace write
  - Timestamped backup per write
  - Lock file to prevent concurrent overwrite
- Akuvox HTTP API integration
  - Read path: `GET /api/user/get`
  - Update path: `POST /api/user/set`

## Quick Start

1. Create env file and local config:

```bash
cp .env.example .env
cp app/example.config.py app/config.py
```

2. Install deps (inside your venv):

```bash
pip install -r requirements.txt
```

3. Run app:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 43127 --reload
```

## External Auth Broker

This application supports using an external Google OAuth connector for authentication. To use one:

- Set `BROKER_URL` in your `.env` to point to the URL of your Google-OAuth connector.
- The app will redirect to the broker for authentication and validate the returned tokens.

---

## API Routes

- `GET /api/me`
- `GET /api/users`
- `POST /api/users/{id}/name`
- `POST /api/users/{id}/toggle-srelay`
- `POST /api/users/{id}/sync-akuvox`

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
