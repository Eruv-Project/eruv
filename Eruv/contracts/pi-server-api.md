# Pi ↔ Server Device API

This file is the contract between the Pi agent (`pi-agent/`) and the server (`server/`). Both test suites validate against the JSON Schemas in this folder. Do not copy the schemas into either project.

## Transport and authentication

- Base URL: the server's public origin, for example `https://eruv.example.org`. On the Pi it is `server.base_url` in `/etc/eruv-agent/agent.yaml`.
- All device endpoints are under `/api/device/v1/`.
- Every request carries the header `X-Device-Key: <device api key>`. The server stores only a hash of the key. An unknown or rotated key gets `401`.
- Request and response bodies are JSON (`Content-Type: application/json`), UTF-8.
- The Pi always initiates. The server never connects to the Pi.

## Endpoints

| Method and path | Body schema | Success | Other responses |
|---|---|---|---|
| `POST /api/device/v1/heartbeat` | `heartbeat.schema.json` | `200` with `{"server_time": "<ISO-8601 UTC>"}` | `401`, `422` |
| `POST /api/device/v1/results` | `result.schema.json` | `201` | `401`, `409`, `422` |
| `POST /api/device/v1/faults` | `fault.schema.json` | `201` | `401`, `409`, `422` |

- `422` means the body failed schema validation. The Pi logs it and drops the message, because retrying an invalid message cannot succeed.
- `5xx` or a network error means "not delivered". The Pi keeps the message in its spool and retries.

## Sequence numbers (`seq`)

- Results and faults share one per-device counter, `seq`. It is an integer ≥ 1 and strictly increasing.
- The Pi keeps the counter in its own table in the spool database. It never derives it from a rowid, so it survives an empty spool, a crash and a power cut.
- The server deduplicates on `(device, seq)`:
  - Same `seq` and identical payload → `409`. The Pi treats `409` as delivered and removes the message from its spool.
  - A `seq` lower than the highest seen, with a different payload → accepted (`201`) and logged as a **device reset** (for example after a reinstall that wiped the spool). The server then continues from the new sequence.
- The server orders messages by `seq` and by its own receive time, never by the Pi's wall clock. A Pi 5 without an RTC battery boots with a wrong clock until NTP syncs.

## Backlog detection (`queued_s`)

Every result and fault carries `queued_s`: how many seconds the message waited in the Pi's spool before this delivery attempt, measured with a monotonic clock. It is correct even when the wall clock is wrong.

The server treats a message with `queued_s > 120` (2 cadence periods) as **backlog**. Backlog messages drive the status engine and are logged, but their transitions are marked `replayed` and are not pushed individually. When the backlog drains, the server sends at most one push with the current state, if it differs from the state last pushed.

## Distances

- Every distance is in metres along the fiber, measured from the OTDR port. It includes the launch box (default 1000 m).
- Event distances are computed on the Pi from the sample index: `x = m · c / (2 · n · Fs)`, with `c = 299792458`, `n` the group refractive index and `Fs` the sample rate the OTDR reported.
- `end_event_distance_m` is the distance of the last event of type `end` (type code 3). It is `null` when the OTDR reported no end event.
- The OTDR's reserved "not computed" float `8192.0` is sent as `null`.

## Message semantics

- **Heartbeat** — every 10 s, independent of tests. Heartbeats are not spooled: a missed heartbeat is the signal the server uses to mark a device `DISCONNECTED`.
- **Result** — one per completed OTDR averaging test (every 60 s). v1 never sends `curve_b64`. The field is reserved for a future curve viewer.
- **Fault** — the OTDR did not answer, returned an error status, or the socket failed. The Pi spools faults like results.
