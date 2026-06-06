# Design Decisions

## Overview

There are two workers: one consuming events (the subscriber) and one whose job is to notify the correct subscriber about an event that just happened.

To test edge cases, three test subscribers are included:
- **Benign client** — always reachable, always succeeds
- **Temp-down subscriber** — intentionally stays down for 2 retries, then succeeds on the third
- **Always-down client** — always reachable but never succeeds, created to test max retry capping on failure

---

## Storage

Three tables persist data across crashes: `Events`, `Deliveries`, `Subscriptions`.

SQLite was chosen because it requires no separate server process and is lightweight — easy to deploy for this kind of assignment. MongoDB and PostgreSQL would be overkill here.

---

## Concurrency

A single thread handles all pending delivery tickets. This keeps the `requests` library easy to reason about and debug, with no locks or race conditions to manage. To increase throughput, additional worker threads could be spawned to handle more subscribers in parallel.

The worker thread polls the database every 2 seconds, filters `deliveries` records with `status = 'pending'`, flips them to `in_progress`, and POSTs to the appropriate subscriber. On success the status becomes `delivered`; on failure it either moves to `failed` or is rescheduled for a retry.

---

## Retry Policy

- Maximum **5 attempts** before permanently marking a delivery as `failed`
- Retry delay: exponential backoff with random jitter — `next_retry = now + (2 ** attempts)`, capped at 60 seconds, plus up to 50% random jitter

---

## Payload Signing

The worker stamps each webhook with a short-lived HMAC-SHA256 fingerprint. The subscriber recomputes it on receipt and rejects anything older than 5 minutes or with a mismatched signature. Signing is opt-in — subscribers that registered without a secret receive unsigned webhooks.

---

## Dashboard

Server-rendered HTML with plain tables. The dashboard allows you to:
1. Register the three test subscribers for events of a chosen type
2. Trigger events via the Events tab
3. View delivery status in the Deliveries tab (refresh manually to poll for updates)

---

## Known Trade-offs

**Client wakes after max retries exceeded** — the event is never delivered. Not handled currently. To fix this, a background thread could poll `failed` deliveries periodically and immediately re-attempt once the subscriber is reachable again.

**Worker crashes after a successful POST but before recording it** — the event gets delivered twice. This is an accepted at-least-once trade-off. Each delivery is stamped with an `event_id` so subscribers can deduplicate on their side.
