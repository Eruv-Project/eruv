# Eruv Fiber Monitoring System

Monitors a city eruv line through an optical fiber that runs along it. An OTDR in the control cabinet at pole 1 tests the fiber every 60 seconds. When the fiber is cut, maintainers get a push alert naming the two poles the break lies between, with a Waze link to the spot.

The design, requirements and decisions are in [docs/plans/2026-09-30-1248-feat-eruv-fiber-monitoring-system-plan.md](docs/plans/2026-09-30-1248-feat-eruv-fiber-monitoring-system-plan.md).

## Components

| Folder | What it is | Runs on |
|---|---|---|
| [`pi-agent/`](pi-agent/) | Python service that drives the OTDR and reports to the server | Raspberry Pi 5 in the cabinet, one per city |
| [`server/`](server/) | FastAPI + PostgreSQL: ingest, break detection, pole mapping, auth, push, WebSocket | One AWS EC2 instance (Docker Compose) |
| [`app/`](app/) | Expo / React Native app for maintainers and admins (Hebrew, RTL) | iOS and Android |
| [`contracts/`](contracts/) | The Pi ↔ server API contract and JSON Schemas both sides test against | — |
| [`docs/reference/`](docs/reference/) | OTDR module manual and launch box datasheet | — |

## Where to put the server address

The server's address is `https://eruv-monitor.duckdns.org`, a free DuckDNS name whose DNS record must point at the server's public IP. It is set in exactly these places:

| Component | File | Key |
|---|---|---|
| Pi agent | `pi-agent/config/agent.example.yaml`, installed on the device as `/etc/eruv-agent/agent.yaml` | `server.base_url` |
| App | `app/.env` (copy of `app/.env.example`) | `EXPO_PUBLIC_API_URL` |
| Server | `server/.env` (copy of `server/.env.example`); `server/Caddyfile` reads it from there | `PUBLIC_BASE_URL` |

To move to another domain later, change these values and rebuild the app: the address is compiled into it. The server needs a domain name with HTTPS: iOS blocks plain HTTP, and device keys must not travel unencrypted.

## Setup and operations

See [`docs/runbook.md`](docs/runbook.md) for deployment, adding a city, installing a Pi, importing poles, setting the reference and the go-live checks.
