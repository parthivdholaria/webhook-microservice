# Webhook Microservice

A webhook delivery system with retry logic, HMAC signature verification, and a live dashboard. Built with FastAPI + SQLite.

---

## Architecture

```
┌──────────────────────────┐     ┌──────────────────────────────────┐
│  Docker Compose network  │     │  Exposed on localhost             │
│                          │     │                                   │
│  webhook  :8000          │     │  :8000  API + Dashboard           │
│  benign   :8001  ◀──POST─┤     │  :8001  benign subscriber         │
│  tempdown :8002  ◀──POST─┤     │  :8002  tempdown subscriber       │
│  alwaysdown:8003 ◀──POST─┘     │  :8003  alwaysdown subscriber     │
└──────────────────────────┘     └──────────────────────────────────┘
```

All four services start from one `docker compose up --build`. The worker thread inside the `webhook` container reaches the subscriber containers by Docker service name (`http://benign:8001/hook`, etc.).

### Subscriber behaviours

| Service | Port | Behaviour |
|---|---|---|
| `benign` | 8001 | Always accepts (HTTP 200). Simulates a healthy client. |
| `tempdown` | 8002 | Fails the first 2 attempts with 500, then accepts on attempt 3. |
| `alwaysdown` | 8003 | Always returns 500. Triggers full retry exhaustion. |

Each subscriber verifies the HMAC-SHA256 `X-Webhook-Signature` header on every request and rejects tampered payloads with 401.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (running)
- `curl` (for terminal-based testing — optional if using the dashboard)

---

## Quickstart

```bash
# From the project root
mkdir -p data          # pre-create volume dir to avoid root-ownership issues
docker compose up --build
```

| URL | What it is |
|---|---|
| http://localhost:8000/dashboard | Events list |
| http://localhost:8000/dashboard/subscriptions | Subscriptions + registration form |

No extra terminals needed — all subscribers are already running inside Docker.

---

## Using the Dashboard

The dashboard lets you do everything without curl.

**Register a subscription** — go to `/dashboard/subscriptions` and either:
- Click a **preset pill** (Benign / Temp Down / Always Down / Wildcard) to auto-fill the form, then click **Register Subscription**
- Or type in a custom Target URL, Event Filter, and optional Secret

**Fire an event** — go to `/dashboard` (Events page) and either:
- Click a **preset pill** to auto-fill the event type and sample payload, then click **Fire Event**
- Or fill in a custom event type and JSON payload

After firing, you land directly on the event detail page and can watch delivery attempts update in real time. Failed deliveries have a **Retry** button that resets them to `pending`.

---

## Terminal-based testing (curl)

### Register subscriptions

```bash
# Benign (always up)
curl -s -X POST http://localhost:8000/subscriptions \
  -H "Content-Type: application/json" \
  -d '{"target_url":"http://benign:8001/hook","event_filter":"benign","secret":"benign-client-secret"}' \
  | python3 -m json.tool

# Temp down (fails 2x, recovers on attempt 3)
curl -s -X POST http://localhost:8000/subscriptions \
  -H "Content-Type: application/json" \
  -d '{"target_url":"http://tempdown:8002/hook","event_filter":"tempdown","secret":"temp-client-down-secret"}' \
  | python3 -m json.tool

# Always down (exhausts all retries)
curl -s -X POST http://localhost:8000/subscriptions \
  -H "Content-Type: application/json" \
  -d '{"target_url":"http://alwaysdown:8003/hook","event_filter":"alwaysdown","secret":"always-down-client-secret"}' \
  | python3 -m json.tool
```

> **Note:** Use Docker service names (`http://benign:8001/hook`) as the target URL — not `localhost` or `host.docker.internal` — so the worker inside Docker can reach them.

---

## Test Scenarios

### Scenario 1 — Happy path (immediate delivery)
> Tests: event ingest → subscriber match → first-attempt delivery

```bash
curl -s -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{"type":"benign","payload":{"order_id":"ord_001","amount":99.99}}' \
  | python3 -m json.tool
```

**Expected** — `docker compose logs benign`:
```
OK verified + delivered <event_id> on attempt 1
```
Dashboard: status `delivered`, attempts `1`, HTTP `200`.

---

### Scenario 2 — Retry with exponential backoff
> Tests: 500 responses trigger retries with `2^n ± 50% jitter` delay; subscriber recovers on attempt 3

```bash
curl -s -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{"type":"tempdown","payload":{"order_id":"ord_002"}}' \
  | python3 -m json.tool
```

**Expected** — `docker compose logs tempdown`:
```
FAIL (pretending to be down): attempt 1 for <event_id>
FAIL (pretending to be down): attempt 2 for <event_id>
OK verified + delivered <event_id> on attempt 3
```
Dashboard: status `delivered`, attempts `3`, last HTTP `200`. (Wait ~10–20 s for retries.)

---

### Scenario 3 — Full retry exhaustion
> Tests: after `MAX_ATTEMPTS` (5) all fail, delivery moves to `failed`

```bash
curl -s -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{"type":"alwaysdown","payload":{"order_id":"ord_003"}}' \
  | python3 -m json.tool
```

**Expected** — `docker compose logs alwaysdown`:
```
FAIL (Always Down subscriber): attempt 1 for <event_id>
...
FAIL (Always Down subscriber): attempt 5 for <event_id>
```
Dashboard: status `failed`, attempts `5`, last HTTP `500`. (Takes ~2–5 min due to backoff.)

---

### Scenario 4 — Manual retry from dashboard
> Tests: operator can force-reset a failed delivery to `pending`

1. Complete Scenario 3 and wait for status `failed`.
2. Open the event detail page → click **Retry** next to the delivery.
3. Delivery resets to `attempts=0`, `status=pending`; worker picks it up again.

Or via curl (get `<delivery_id>` from the dashboard URL):
```bash
curl -s -X POST http://localhost:8000/dashboard/deliveries/<delivery_id>/retry
```

---

### Scenario 5 — Event type filtering
> Tests: a `benign` event does NOT trigger `tempdown` or `alwaysdown` subscribers

```bash
curl -s -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{"type":"benign","payload":{"test":"filtering"}}' \
  | python3 -m json.tool
```

**Expected:** only the `benign` container logs a delivery. Dashboard: 1 ticket created.

---

### Scenario 6 — Wildcard subscriber (receives all event types)
> Tests: `event_filter="*"` matches every event type

```bash
# Register wildcard subscription
curl -s -X POST http://localhost:8000/subscriptions \
  -H "Content-Type: application/json" \
  -d '{"target_url":"http://benign:8001/hook","event_filter":"*","secret":"benign-client-secret"}' \
  | python3 -m json.tool

# Fire any event type
curl -s -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{"type":"completely-new-type","payload":{"test":"wildcard"}}' \
  | python3 -m json.tool
```

**Expected:** `benign` container receives it even though no explicit `completely-new-type` subscription exists. Dashboard: `tickets_created` includes the wildcard subscription.

---

### Scenario 7 — HMAC signature verification
> Tests: wrong secret → subscriber rejects with 401 → delivery marked `failed` (non-retryable)

```bash
# Register with WRONG secret (subscriber expects "benign-client-secret")
curl -s -X POST http://localhost:8000/subscriptions \
  -H "Content-Type: application/json" \
  -d '{"target_url":"http://benign:8001/hook","event_filter":"sig-test","secret":"WRONG-SECRET"}' \
  | python3 -m json.tool

curl -s -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{"type":"sig-test","payload":{"test":"bad-sig"}}' \
  | python3 -m json.tool
```

**Expected** — `docker compose logs benign`:
```
REJECTED: bad signature
```
Dashboard: status `failed`, last HTTP `401`. No retries (401 is non-retryable).

---

### Scenario 8 — No matching subscribers
> Tests: event with no matching subscribers ingests cleanly with `tickets_created=0`

```bash
curl -s -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{"type":"orphan-event","payload":{"test":"no-sub"}}' \
  | python3 -m json.tool
```

**Expected response:** `{"status":"accepted","tickets_created":0}`. Event appears in the dashboard list but has no delivery rows.

---

### Scenario 9 — Fanout (multiple subscribers, same event type)
> Tests: one event creates one delivery ticket per matching subscriber

```bash
# Register a second subscriber also on "benign"
curl -s -X POST http://localhost:8000/subscriptions \
  -H "Content-Type: application/json" \
  -d '{"target_url":"http://tempdown:8002/hook","event_filter":"benign","secret":"temp-client-down-secret"}' \
  | python3 -m json.tool

# Fire — both subscribers should receive it
curl -s -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{"type":"benign","payload":{"test":"fanout"}}' \
  | python3 -m json.tool
```

**Expected:** `tickets_created: 2`. `benign` delivers immediately; `tempdown` fails twice then delivers.

---

### Scenario 10 — Subscription without a secret
> Tests: when `secret` is omitted, the worker sends no `X-Webhook-Signature` header

```bash
curl -s -X POST http://localhost:8000/subscriptions \
  -H "Content-Type: application/json" \
  -d '{"target_url":"http://benign:8001/hook","event_filter":"nosig"}' \
  | python3 -m json.tool
```

> Note: the bundled `benign` subscriber always verifies a signature and will reject this with 401. To observe the unsigned path cleanly, point to a plain HTTP echo server on a custom port.

---

### Scenario 11 — Crash recovery
> Tests: `in_progress` tickets are re-queued automatically on restart

1. Fire an `alwaysdown` event and let a delivery reach `in_progress` in the DB:
   ```bash
   sqlite3 data/webhooks.db "SELECT id, status FROM deliveries LIMIT 5;"
   ```
2. Kill the stack: `docker compose down`
3. Restart: `docker compose up`
4. The lifespan handler calls `recover_stuck_deliveries()` which resets any `in_progress` rows to `pending`.

**Expected:** delivery resumes from where it left off.

---

## Edge Cases

### A — Rapid-fire / concurrent events
```bash
for i in $(seq 1 10); do
  curl -s -X POST http://localhost:8000/events \
    -H "Content-Type: application/json" \
    -d "{\"type\":\"benign\",\"payload\":{\"i\":$i}}" &
done; wait
```
Verify all 10 events reach `delivered` with no dropped tickets.

### B — Unreachable subscriber URL
```bash
curl -s -X POST http://localhost:8000/subscriptions \
  -H "Content-Type: application/json" \
  -d '{"target_url":"http://host.docker.internal:9999/hook","event_filter":"dead-url"}' \
  | python3 -m json.tool

curl -s -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{"type":"dead-url","payload":{"test":"unreachable"}}' \
  | python3 -m json.tool
```
**Expected:** worker catches `RequestException`, schedules retries, delivery eventually reaches `failed` with `last_error` set.

### C — Replay attack protection
Capture a valid signed request, wait >5 minutes, replay it.  
**Expected:** subscriber returns 401 — the `X-Webhook-Timestamp` is older than the 300-second window.

### D — Malformed payload
```bash
curl -s -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{"type":"bad","payload":"this-is-a-string-not-a-dict"}' \
  | python3 -m json.tool
```
**Expected:** HTTP 422 from FastAPI — no event row is created.

### E — Duplicate subscription registration
Register the same `target_url` + `event_filter` twice. Both rows are stored and each event creates two delivery tickets (no dedup at registration time).

---

## Tear down

```bash
docker compose down

# Also wipe the database for a clean slate
rm -rf ./data
```
