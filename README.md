# NEXA Messenger — self-hosted MVP

A responsive web messenger with account registration/sign-in, username lookup, direct chats, groups, persistent message history, and live message delivery over WebSocket. It uses only Node.js built-in modules (no npm dependencies).

## Requirements
- Node.js 18+ (tested with Node.js 22)
- A server/computer where Node can remain running

## Run locally
```bash
node server.js
```
Open `http://localhost:3000`. For testing real-time chat, create two accounts in two browser profiles/devices and start a conversation using the other account's username. For a phone on the same Wi-Fi, open `http://YOUR_COMPUTER_LAN_IP:3000`.

## Run as a service
Use a process manager such as systemd or PM2 in production. Keep `data/db.json` backed up and restricted to the service account. `PORT` and `HOST` environment variables are supported.

## Public internet deployment checklist
1. Provision a host/VPS and a domain; neither is included in this source package.
2. Put the app behind a trusted HTTPS reverse proxy (Caddy/Nginx) and proxy WebSocket upgrades to the Node port. Use HTTPS/WSS publicly; do not expose plain HTTP login traffic to the internet.
3. Set firewall rules so the Node port is reachable only from the reverse proxy. Add server monitoring, backups, log rotation, and a database strategy suitable for your expected scale.
4. Review security and privacy requirements before inviting real users. The included JSON file store is for a small MVP, not high-concurrency production scale.

## What works in this package
- Register and sign in; password hashes use Node `scrypt` with random per-user salts.
- Session tokens, logout, username validation, basic per-IP rate limiting.
- Find registered users; filter chats by direct/group; start direct chats; create named groups with existing usernames.
- Store messages on disk and fetch recent history.
- Deliver new messages to connected members using WebSocket.
- Responsive dark UI for phones and desktop.
- Basic validation, output escaping, security response headers.

## Limitations (important)
- This is a self-hosted MVP, not an already-hosted public service. No domain, VPS, DNS, or TLS certificate is provisioned by this project.
- No end-to-end encryption. Messages are stored as readable text in the server's JSON database. Do not use for sensitive or confidential messages.
- JSON storage is not a production database; concurrent writes, high load, multi-process deployment, and recovery need stronger infrastructure.
- No file/photo/voice uploads, calls, push notifications, password reset, email/phone verification, read receipts, typing indicators, message editing/deletion, moderation/reporting, or multi-device session management.
- WebSocket authentication uses the session token in the URL query string; use HTTPS/WSS and review proxy/access logs so query strings are not retained. A production implementation should use a more robust WebSocket auth handshake.
- The built-in rate limiter is per-process and memory-only. There is no automated security audit or independent penetration test.

## Smoke test
Run:
```bash
node --check server.js
node --check public/app.js
node server.js
```
In another terminal:
```bash
curl -s http://127.0.0.1:3000/api/health
```
Expected response includes `"ok":true`.

## Data and privacy
Persistent data is written to `data/db.json`. Protect that file, backups, and server access. Deleting the file removes local accounts, sessions, chats, and messages. This project does not transmit data to a third-party service by itself.

## Optional Docker + HTTPS reverse proxy
1. Install Docker Engine and Docker Compose on your server.
2. Copy `.env.example` to `.env` and set `DOMAIN` to your real domain. Point that domain's DNS records to your server and allow inbound ports 80/443.
3. Run `docker compose up -d --build`.
4. Caddy will attempt to obtain and renew a public TLS certificate automatically. Check `docker compose logs -f caddy app` if it fails.
5. Keep `.env` private. Back up the Docker volume `nexa_data`.

This deployment recipe is supplied but has not been run against a real domain or external server in this environment.

## One-click deployment (Render)

This repository includes `render.yaml` as a Render Blueprint. It creates a Docker web service in Singapore and mounts a 1 GB persistent disk at `/app/data` so user accounts/messages survive redeploys. **A persistent disk requires a paid Render service; review the current price in Render before confirming deployment.** No hosting account, billing authorization, domain, or live URL is included with this source package.

1. Push the complete `nexa-messenger-final` directory to a GitHub repository (repository root must contain `render.yaml` and `Dockerfile`).
2. Sign in to Render, choose **New → Blueprint**, connect that repository, review the plan/disk costs, and confirm deployment.
3. Wait for the deployment to finish. Open `https://YOUR-SERVICE.onrender.com/api/health`; the response should contain `"ok":true`.
4. The web app is available at `https://YOUR-SERVICE.onrender.com`. HTTPS and WebSocket TLS are provided by Render.

The blueprint uses a persistent disk because the included JSON file store is not safe to run on ephemeral storage. This remains a small-MVP data store, not a production-grade database.

## Build an installable Android APK with GitHub Actions

The `.github/workflows/build-android.yml` workflow uses GitHub-hosted Linux runners with Java 21 and Node 22, then creates a Capacitor Android wrapper and builds a debug APK. The APK packages the web UI locally and connects to the deployed HTTPS backend.

1. Push this project to a GitHub repository.
2. After Render is live, open the GitHub repository's **Settings → Secrets and variables → Actions → Variables** and create a repository variable named `NEXA_PUBLIC_URL` with the full HTTPS URL, for example `https://nexa-messenger.onrender.com` (use your actual URL).
3. Open **Actions → Build NEXA Android APK → Run workflow**. Wait for the workflow to finish.
4. Download the `nexa-messenger-android-debug` artifact from the completed run, extract it, and install `app-debug.apk` on your Android phone. Android may ask you to allow installing apps from that source.

The workflow produces a **debug APK**, suitable for testing and direct installation. It is not a signed Play Store release. A production release requires a securely managed Android signing key and a separate signed-release workflow. The APK requires an internet connection and the Render backend to be running. Do not publish credentials or signing keys in the repository.

## Native API routing

`public/native-config.js` is empty for ordinary same-origin web deployment. The Android workflow replaces it in the build workspace with the configured backend URL. The API allows the Capacitor Android origins `https://localhost` and `capacitor://localhost`; extend `ALLOWED_ORIGINS` deliberately if adding another native origin. Never add broad wildcard CORS for authenticated endpoints.
