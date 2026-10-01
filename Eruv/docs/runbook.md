# Eruv Monitoring System: Operations and Field Runbook

<div dir="rtl">

**מבוא.** מסמך זה מיועד למפעילים ולמתקינים. הוא מתאר, צעד אחר צעד, איך מעלים את השרת ב-AWS, איך יוצרים מנהל ראשון, ואיך מתקינים עיר חדשה מקצה לקצה: יצירת עיר ומכשיר, התקנת ה-Pi בארון, ייבוא עמודים, קביעת ייחוס, ובדיקות השטח לפני עלייה לאוויר. הפקודות והשמות הטכניים כתובים באנגלית. בצעו את הסעיפים לפי הסדר; סעיף "Go-live checks" בסוף הוא התנאי לעלייה לאוויר של כל עיר.

</div>

Sections:

1. [Set the server address](#1-set-the-server-address)
2. [Deploy the server on AWS](#2-deploy-the-server-on-aws)
3. [Set up the uptime monitor](#3-set-up-the-uptime-monitor)
4. [Create the first admin](#4-create-the-first-admin)
5. [Add a city and its device; rotate a device key](#5-add-a-city-and-its-device-rotate-a-device-key)
6. [Install the Pi agent](#6-install-the-pi-agent)
7. [Cabinet notes](#7-cabinet-notes)
8. [Import the poles](#8-import-the-poles)
9. [Set the reference](#9-set-the-reference)
10. [Power-cycle test](#10-power-cycle-test)
11. [Detection check (spare spool)](#11-detection-check-spare-spool)
12. [Mapping check (live eruv fiber)](#12-mapping-check-live-eruv-fiber)
13. [Go-live checks](#13-go-live-checks)
14. [App distribution: iOS (Apple Business Manager) and Android](#14-app-distribution-ios-apple-business-manager-and-android)
15. [Backups and restore](#15-backups-and-restore)
16. [Troubleshooting](#16-troubleshooting)

Conventions: `$SERVER` is the server's public origin, for example `https://eruv.example.org`. `$TOKEN` is an admin access token (section 4). Server commands run on the EC2 instance from the `server/` folder of the repository checkout.

---

## 1. Set the server address

The repository ships with a placeholder documentation IP instead of the real server address. Replace it in exactly the places listed in the table in [README.md, "Where to put the AWS address"](../README.md#where-to-put-the-aws-address):

| Component | File | Key |
|---|---|---|
| Pi agent | `pi-agent/config/agent.example.yaml`, installed on the device as `/etc/eruv-agent/agent.yaml` | `server.base_url` |
| App | `app/.env` (copy of `app/.env.example`) | `EXPO_PUBLIC_API_URL` |
| Server | `server/.env` (copy of `server/.env.example`) and `server/Caddyfile` | `PUBLIC_BASE_URL`, site address |

All four values must name the same origin. Use a **domain name** for production (for example `eruv.example.org`, with a DNS `A` record pointing at the instance's Elastic IP):

- iOS release builds refuse plain HTTP and untrusted certificates.
- The Pi agent refuses anything but HTTPS with a trusted certificate, and the device key must not travel unencrypted.
- A public certificate authority normally does not issue a certificate for a bare IP address.

The production domain is an open "Resolve Before Release" item in the plan. Get it before the iOS release build.

### Development on a bare IP

Until the domain exists, the server can run on the bare Elastic IP:

- **Default (`tls internal`):** the shipped `Caddyfile` serves HTTPS with a certificate from Caddy's own local CA. The API works from a browser or `curl -k`, but phones, the Pi agent and external uptime monitors do not trust that CA.
- **Plain HTTP (dev only):** change the Caddyfile site address to `http://<ip>` and delete the `tls internal` line; set `PUBLIC_BASE_URL=http://<ip>`. The Pi needs `server.allow_insecure_dev: true` in its config, and the app needs a development build with a dev-only plain-HTTP exception. Never use this for a city that is live.

---

## 2. Deploy the server on AWS

### 2.1 Instance

1. Launch one EC2 instance: Ubuntu LTS, `t3.small` or larger, 20 GB gp3 disk.
2. Attach an Elastic IP, so the address never changes.
3. Security group inbound: TCP 22 (SSH, from your own IP only), TCP 80 and TCP 443 (from anywhere), UDP 443 (optional, HTTP/3). Nothing else. PostgreSQL and the API port are never exposed.
4. Point the production domain's DNS `A` record at the Elastic IP.
5. Install Docker Engine with the Compose plugin (Docker's official instructions for Ubuntu). Compose v2.17 or newer is required (the build uses `additional_contexts`); check with `docker compose version`.

### 2.2 Configure

```sh
git clone <repository-url> eruv && cd eruv/server
cp .env.example .env
chmod 600 .env
```

Edit `server/.env`:

| Key | Value |
|---|---|
| `PUBLIC_BASE_URL` | `https://<your domain>` |
| `POSTGRES_PASSWORD` | a new random URL-safe password: `python3 -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `DATABASE_URL` | `postgresql+psycopg://eruv:<the same password>@db:5432/eruv` |
| `JWT_SECRET` | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |

Edit `server/Caddyfile`: replace the placeholder site address with the domain, and delete the `tls internal` line (see the comment at the top of the file).

### 2.3 Start

```sh
docker compose up -d --build
docker compose ps          # api should become "healthy" within about 30 s
docker compose logs -f api # migrations run first, then uvicorn starts
curl -i https://<your domain>/health
```

`/health` answers `200 {"status":"ok",...}` while the server's watchdog loop runs, and `503` otherwise.

What runs (`server/docker-compose.yml`):

| Service | Role |
|---|---|
| `api` | FastAPI server. Runs `alembic upgrade head`, then uvicorn with **exactly one worker**: the event bus and watchdog are in-process. Never add `--workers` or scale this service. |
| `db` | PostgreSQL 16, data in the named volume `pgdata`. |
| `backup` | Nightly `pg_dump` at 01:00 UTC into `server/backups/` (section 15). |
| `caddy` | HTTPS on ports 80/443, certificates stored in the `caddy_data` volume, reverse proxy to `api:8000` including the `/ws` WebSocket. |

### 2.4 Upgrade

```sh
cd eruv && git pull
cd server && docker compose up -d --build
```

Migrations run automatically when `api` starts. Take a manual backup first (section 15) when the release notes mention a migration.

---

## 3. Set up the uptime monitor

The server is one EC2 instance. If it or its watchdog stops, nobody gets break alerts, so an outside service must watch it (KTD12).

1. Create a free account with an external uptime service, for example **UptimeRobot** or **Better Stack Uptime**. Install its mobile app on the admin's phone and enable push notifications (add SMS or a phone call if the plan offers them).
2. Add an **HTTP(S)** monitor:
   - URL: `https://<your domain>/health`
   - Interval: 1 minute (5 minutes is the most you should accept).
   - Alert when: the status code is not 200. If the service offers a keyword check, also require the keyword `"ok"`.
   - Request timeout: 10 to 30 s.
3. Alert contacts: the admin's phone (app push, plus SMS where available), and a second admin if there is one.
4. Enable the SSL-certificate-expiry alert if the service offers one.
5. Prove it works: see go-live check G4 (section 13).

An external monitor cannot reach a server that uses `tls internal` or plain HTTP on a bare IP unless the check ignores certificate errors. Set up the real monitor once the domain exists.

---

## 4. Create the first admin

Admins are normally created by another admin approving them, so the first admin comes from the command line on the server:

```sh
docker compose exec api python -m app.cli create-admin \
    --email admin@example.org --name "Admin Name" --phone 050-0000000
```

The command prompts for the password twice (at least 8 characters). For scripting, pass it in `ERUV_ADMIN_PASSWORD` instead (`docker compose exec -e ERUV_ADMIN_PASSWORD=... api python -m app.cli create-admin ...`); keep it out of shell history. The command refuses an email that already exists.

The admin can now log in to the app. Later admins register in the app and are approved and promoted from the app's Admin tab.

To get an access token for the API calls below:

```sh
SERVER=https://<your domain>
TOKEN=$(curl -s -X POST "$SERVER/api/auth/login" -H 'Content-Type: application/json' \
    -d '{"email":"admin@example.org","password":"<password>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
```

The access token lasts 15 minutes; log in again when calls return `401`.

---

## 5. Add a city and its device; rotate a device key

Use the app's Admin tab, or the API:

```sh
# Create the city (launch box offset and break tolerance in metres; defaults 1000 and 50)
curl -s -X POST "$SERVER/api/admin/cities" -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' -d '{"name":"באר שבע","launch_offset_m":1000,"break_tolerance_m":50}'
# -> {"id": 1, ...}

# Create the city's device and get its API key
curl -s -X POST "$SERVER/api/admin/cities/1/device-key" -H "Authorization: Bearer $TOKEN"
# -> {"device_id": 1, "city_id": 1, "api_key": "<shown only once>"}
```

- The `api_key` is shown **once**. Copy it straight into the Pi config (section 6). Do not email it or store it anywhere else.
- `launch_offset_m` is the length of fiber inside the launch box before pole 1; take it from the launch box datasheet (`docs/reference/`).

**Rotate a key** (a leaked key, a replaced Pi, a lost SD card): call the same `POST /api/admin/cities/{id}/device-key` again, or use the Admin tab. The old key stops working immediately, so the city shows as disconnected until the new key is on the Pi. Then on the Pi:

```sh
sudo nano /etc/eruv-agent/agent.yaml        # set server.device_key to the new key
sudo systemctl restart eruv-agent
```

**Approve maintainers:** users register in the app and pick their city. Approve them from the Admin tab, or with `GET /api/admin/users?approval_state=pending` and `POST /api/admin/users/{id}/approve` (also `reject` and `disable`).

---

## 6. Install the Pi agent

On the Raspberry Pi 5 (Raspberry Pi OS, network working, clock synced by NTP):

```sh
sudo apt-get install -y git python3-venv
git clone <repository-url> eruv
sudo sh eruv/pi-agent/deploy/install.sh
```

The installer creates `/opt/eruv-agent/venv`, installs the agent, creates `/etc/eruv-agent/agent.yaml` (owner root, mode `0600`), creates the spool folder `/var/lib/eruv-agent`, and enables the `eruv-agent` systemd service (starts on boot, restarts after any crash, R8).

Edit the config:

```sh
sudo nano /etc/eruv-agent/agent.yaml
```

| Key | Value |
|---|---|
| `server.base_url` | `https://<your domain>` (same as `PUBLIC_BASE_URL`) |
| `server.device_key` | the key from section 5 |
| `server.allow_insecure_dev` | `false` (always, on a real city) |
| `otdr.host`, `otdr.port` | the OTDR module's Ethernet address (default `192.168.1.249:5000`) |

Leave the `test` and `schedule` values as shipped unless the plan says otherwise (one test every 60 s, heartbeat every 10 s).

Start it and watch the log:

```sh
sudo systemctl start eruv-agent
journalctl -u eruv-agent -f
```

Within about 2 minutes the log shows the OTDR connection, a completed test and successful uploads. The app shows the city as connected (it stays "awaiting reference" until section 9). Manual run for debugging (stop the service first):

```sh
sudo systemctl stop eruv-agent
sudo /opt/eruv-agent/venv/bin/python -m eruv_agent --config /etc/eruv-agent/agent.yaml
```

Upgrading the agent: `cd eruv && git pull && sudo sh pi-agent/deploy/install.sh` (the existing config is kept).

---

## 7. Cabinet notes

- **Cooling:** the OTDR tests every 60 s, around the clock. Its manual requires **forced-air cooling** for continuous use: fit a fan that blows air through the cabinet past the OTDR. The Pi reports its CPU temperature with every result; a rising trend means the cooling is not enough.
- **Key file:** `/etc/eruv-agent/agent.yaml` holds the device key and must stay `root:root`, mode `0600` (`sudo ls -l /etc/eruv-agent/`). Anyone with physical access to the cabinet can still read the SD card: lock the cabinet, and rotate the key (section 5) if a Pi or SD card goes missing.
- **Power:** the Pi and OTDR must come back by themselves after a power cut (section 10). A small UPS is optional; without it the Pi's spool keeps results only while the Pi has power.
- **Network:** the Pi only makes outgoing HTTPS connections, so it works behind cellular NAT. No inbound port is needed.
- **Labels:** label the Pi, the OTDR port and the launch box with the city name.

---

## 8. Import the poles

Pole import is built in U9 (the app's Admin tab). Planned API: `POST /api/admin/cities/{id}/poles/preview` and `POST /api/admin/cities/{id}/poles` (added in U9).

1. Prepare the file:
   - **CSV** with the header `pole_number,lat,lon`, one row per pole, decimal degrees (WGS84), or
   - **KML** with one placemark per pole.
   - Pole 1 is the pole with the cabinet. Numbers must be unique and consecutive from 1, **in the order the fiber runs**: the ring is walked 1 → 2 → … → N → 1.
2. In the app: Admin tab → the city → Import poles → choose the file.
3. Check the preview on the map: every pole in the right place, the ring outline following the eruv, no crossing lines (a crossing usually means two poles are numbered in the wrong order). Fix the file and preview again until it is right.
4. Save.

---

## 9. Set the reference

The reference is the intact fiber length that later results are compared with. Set it once the Pi reports and the line is known to be intact. Planned API: `POST /api/admin/cities/{id}/reference` (added in U9).

1. Walk or check the line, and confirm the latest results are recent (the app's log shows a result every 60 s).
2. Admin tab → the city → Set reference (from the latest intact result).
3. The server refuses while the city is in a suspected or confirmed break.
4. If the measured fiber length is more than 5% shorter than the pole ring's perimeter, the app asks for explicit confirmation. Stop and find out why first: a wrong launch offset, a pole file that does not match the route, or a real break close to the far end.
5. The banner turns green ("העירוב תקין").

Set the reference again after any repair that changes the fiber length (a new splice or a re-routed span).

---

## 10. Power-cycle test

Proves unattended recovery (R8; success criterion: results resume within 3 minutes of power returning).

1. Note the time of the last result in the app's log.
2. Switch the whole cabinet off at the supply (Pi and OTDR together). Leave it off for at least 1 minute.
3. Switch it back on and start a stopwatch.
4. Pass: a new result appears in the app's log, and the city shows its normal state (not disconnected), **within 3 minutes**. On the Pi, `journalctl -u eruv-agent -b` shows the agent started by itself.

---

## 11. Detection check (spare spool)

Proves that a cut is detected as a break and pushed to phones within 4 minutes. Do this **before** connecting the live eruv fiber, or with the live fiber temporarily swapped for a spare spool.

1. Connect a spare fiber spool (a few km) to the launch box instead of the eruv fiber. Import a temporary test pole file for the city that matches the spool length, or use a separate test city with its own device key.
2. Wait for results, then set the reference (section 9). The banner is green.
3. Make sure at least one approved maintainer phone has the app installed, is logged in, and has notifications enabled.
4. Cut the spool fiber cleanly at a known distance and start a stopwatch.
5. Pass: the city goes to `BREAK` (red banner) **and** the phone receives the push **within 3 minutes** (typical case; a cut during a running measurement can take one more 60 s cycle, about 3.5 minutes worst case).
6. Note the break distance in the app and compare it with the known cut distance.
7. Splice or replace the spool. Pass: a recovery push arrives and the banner returns to green.
8. Put the real eruv fiber back, restore the real pole file, and set the reference again.

If the city never reaches `BREAK`, the OTDR may report a cut differently than expected (for example a large reflective event before the end). Keep the Pi log and the result (`journalctl -u eruv-agent`) and adjust the break criterion before go-live.

---

## 12. Mapping check (live eruv fiber)

Proves that OTDR distances map to the right pole pair on the real eruv fiber. This is the check that decides whether the pure geographic-distance model is good enough.

1. Choose **at least 3 known-location features** on the live fiber, spread around the ring, at least one far from pole 1:
   - existing splice closures at known poles, or
   - a temporary macrobend (a tight loop, about 2 cm across, held for a few test cycles) at a named pole. Do not bend so hard that the line looks broken, and remove it afterwards.
2. Wait for 1 to 2 test cycles with the feature present.
3. On the server, print the events of the city's latest result and the pole pair each one maps to (replace `CITY_ID`):

   ```sh
   docker compose exec -T api python - <<'EOF'
   CITY_ID = 1
   from sqlalchemy import select
   from app.config import get_settings
   from app.db import make_engine, make_session_factory
   from app.mapping import PolePoint, map_break
   from app.models import City, Pole, Result, ResultKind
   with make_session_factory(make_engine(get_settings().database_url))() as s:
       city = s.get(City, CITY_ID)
       poles = [PolePoint(p.number, p.lat, p.lon) for p in s.scalars(select(Pole).where(Pole.city_id == CITY_ID).order_by(Pole.number))]
       r = s.scalars(select(Result).where(Result.city_id == CITY_ID, Result.kind == ResultKind.RESULT).order_by(Result.received_at.desc())).first()
       print("result seq", r.seq, "measured", r.measured_at, "fiber length", r.fiber_length_m)
       for e in r.events or []:
           print(f'{e["distance_m"]:>10.1f} m  {e["type"]:<15}', map_break(e["distance_m"], city.launch_offset_m, poles))
   EOF
   ```

4. For each feature, find its event by distance and compare the mapped pole pair with the pole where the feature really is.
5. Pass: **every** feature maps between the correct pole pair (the feature's pole is `pole_a` or `pole_b`, or the mapping falls on the segment next to it).
6. Record the results (feature, real pole, OTDR distance, mapped pair, error in metres) in the city's install notes.

If a feature maps to the wrong pair, and the error grows with distance from pole 1, that is fiber slack or overlength. Do **not** go live for that city: raise it with the team to revisit the geographic-distance decision (calibration from the measured fiber length is the planned follow-up). Check the launch offset and the pole order first.

---

## 13. Go-live checks

A city goes live only when all four checks pass. Record the date, the result and who ran each one.

| # | Check | How | Pass |
|---|---|---|---|
| G1 | Power-cycle recovery | Section 10 | Results resume **≤ 3 min** after power returns |
| G2 | Break detection and alert | Section 11 (spare-spool cut) | City goes to `BREAK` and a push arrives **within 4 min** |
| G3 | Break mapping | Section 12 | Each of **≥ 3** known-location features on the live fiber maps between the correct pole pair |
| G4 | Uptime monitor | On the server: `docker compose stop api`; wait; then `docker compose start api` | The admin's phone gets the uptime monitor's "down" alert, then "up" after the restart |

G4 needs doing once per server, not per city. Also confirm, after the city is live, that the app shows the city as green and connected, and that every maintainer of the city is approved and has received a test alert (G2) or a recovery push.

---

## 14. App distribution: iOS (Apple Business Manager) and Android

The app is installable only by invitation (R21).

### Prerequisites (start early)

- An **Apple Developer Program organization account**. It needs a **D-U-N-S number** for the organization, which can take weeks. Start this before anything else.
- An **Apple Business Manager** account for the same organization (business.apple.com), also verified with the D-U-N-S number.
- An Expo account and EAS set up for the app (`eas init`; the project ID goes in `app/.env` as `EAS_PROJECT_ID`).
- `app/.env` with `EXPO_PUBLIC_API_URL=https://<your domain>` (section 1).

### Publish a new iOS version (Apple Business Manager custom app)

Production iOS distribution is an Apple Business Manager **custom app**. Its builds do not expire, unlike TestFlight builds, so alerting never lapses silently. TestFlight is used only for pre-release testing.

1. Raise the version (`version` and the iOS build number) in the app config.
2. Build: `cd app && eas build --platform ios --profile production`.
3. Upload: `eas submit --platform ios` (to App Store Connect).
4. Optional: test the build on TestFlight with one or two testers.
5. The first time only, in App Store Connect → the app → **Pricing and Availability**: choose **Private distribution for business** and add the organization's Apple Business Manager Organization ID.
6. Fill in the version's details and **submit it for review**. Custom apps go through App Review like public apps.
7. After approval, the first time only: in Apple Business Manager → **Apps and Books**, find the custom app, get licenses, and hand out redeem codes (or assign it through an MDM, if the organization has one).
8. Later versions reach installed phones as normal App Store updates. Ask maintainers to keep automatic updates on.

### Android

Either of:

- **Google Play closed testing track** (recommended: automatic updates). Build with `eas build --platform android --profile production`, upload the `.aab` to Play Console → Testing → Closed testing, and add the maintainers' Google account emails to the tester list. They join through the opt-in link.
- **Direct APK**: build an APK profile (`buildType: "apk"`), and send the file to maintainers privately. They must allow installation from that source. There are no automatic updates: every new version must be sent again.

After installing, each maintainer registers in the app, picks their city, and waits for admin approval (section 5).

---

## 15. Backups and restore

- The `backup` service writes `server/backups/eruv-YYYY-MM-DD.dump` every night at 01:00 UTC; a new dump the same day overwrites. Check with `ls -l server/backups/` and `docker compose logs backup`.
- **Copy backups off the instance** (for example a nightly `aws s3 sync server/backups s3://<bucket>/eruv-backups/` from the host's crontab). A backup that only lives on the instance is lost with it.
- Dumps are not deleted automatically. They are small; remove old ones by hand once in a while (for example keep the last 30).
- Manual backup: `docker compose exec backup sh -c 'pg_dump -Fc -f /backups/eruv-manual-$(date -u +%F-%H%M).dump'`.
- Restore (stops alerting while it runs):

  ```sh
  docker compose stop api
  docker compose exec -T backup pg_restore --clean --if-exists -d eruv < backups/eruv-YYYY-MM-DD.dump
  docker compose start api
  ```

- Changing the database password after first start: `POSTGRES_PASSWORD` is read only when the volume is first created. Run `docker compose exec db psql -U eruv -c "ALTER USER eruv PASSWORD '<new>'"`, then update both `POSTGRES_PASSWORD` and `DATABASE_URL` in `.env` and run `docker compose up -d`.

---

## 16. Troubleshooting

| Symptom | Check |
|---|---|
| `/health` returns 503 | The watchdog stopped: `docker compose logs api`. Restart with `docker compose restart api`. |
| Caddy cannot get a certificate | DNS `A` record points at the Elastic IP; ports 80 and 443 open; the domain in `Caddyfile` is right. `docker compose logs caddy`. |
| City shows disconnected | On the Pi: `journalctl -u eruv-agent -f`. `401` in the log means a wrong or rotated key (section 5). TLS errors mean the certificate is not trusted (section 1). |
| City shows OTDR fault (orange) | The OTDR does not answer: power, Ethernet cable, `otdr.host` in the config, cabinet temperature (section 7). |
| Login fails with 429 | Too many attempts from one address or for one account; wait 15 minutes. |
| No push alerts | The phone has notifications enabled for the app and the user is approved for the city. `docker compose logs api` shows push errors. |
| A second break after a repair | Only the break nearest pole 1 is visible. After a repair, the next test reveals any further break automatically. |
