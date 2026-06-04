import threading
import time
from datetime import datetime, timezone
from utils.db import get_connection
import json
import random
import uuid
from datetime import datetime, timezone, timedelta
from utils.helpers import schedule_retry,mark_delivered,mark_failed

import requests

REQUEST_TIMEOUT_SECONDS = 10
POLL_INTERVAL_SECONDS = 2


def claim_one_delivery():
    """Grab one due 'pending' ticket and flip it to 'in_progress' — atomically."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT * FROM deliveries
            WHERE status = 'pending' AND next_attempt_at <= ?
            ORDER BY next_attempt_at
            LIMIT 1
            """,
            (now,),
        ).fetchone()

        if row is None:
            return None

        cur = conn.execute(
            "UPDATE deliveries SET status = 'in_progress', updated_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (now, row["id"]),
        )
        conn.commit()

        if cur.rowcount == 0:
            return None        # someone else claimed it first — let it go
        return row
    finally:
        conn.close()
        
def deliver(delivery):
    conn = get_connection()
    try:
        sub = conn.execute(
            "SELECT target_url FROM subscriptions WHERE id = ?",
            (delivery["subscription_id"],),
        ).fetchone()
        event = conn.execute(
            "SELECT type, payload FROM events WHERE id = ?",
            (delivery["event_id"],),
        ).fetchone()
    finally:
        conn.close()

    if sub is None:
        mark_failed(delivery, None, "subscription no longer exists")
        return

    body = {
        "event_id": delivery["event_id"],     # the dedup stamp for the subscriber
        "type": event["type"],
        "payload": json.loads(event["payload"]),
    }

    try:
        resp = requests.post(
            sub["target_url"], json=body, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        schedule_retry(delivery, status_code=None, error=str(exc))   # network error/timeout
        return

    if 200 <= resp.status_code < 300:
        mark_delivered(delivery, resp.status_code)
    elif resp.status_code in (408, 429) or 500 <= resp.status_code < 600:
        schedule_retry(delivery, status_code=resp.status_code, error=None)
    else:
        mark_failed(delivery, resp.status_code, "non-retryable status")
        
def run_worker(stop_event: threading.Event):
    """The kitchen loop: claim a ticket, deliver it, repeat. Naps when idle."""
    while not stop_event.is_set():
        delivery = claim_one_delivery()
        if delivery is None:
            time.sleep(POLL_INTERVAL_SECONDS)   # board empty — take a short nap
            continue
        deliver(delivery)