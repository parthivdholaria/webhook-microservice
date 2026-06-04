import random
from datetime import datetime, timezone, timedelta
from db import get_connection

MAX_ATTEMPTS = 5

def mark_delivered(delivery, status_code):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE deliveries SET status='delivered', last_status_code=?, "
            "last_error=NULL, updated_at=? WHERE id=?",
            (status_code, now, delivery["id"]),
        )
        conn.commit()
    finally:
        conn.close()


def mark_failed(delivery, status_code, error):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE deliveries SET status='failed', last_status_code=?, "
            "last_error=?, updated_at=? WHERE id=?",
            (status_code, error, now, delivery["id"]),
        )
        conn.commit()
    finally:
        conn.close()
        
        
def backoff_seconds(attempts):
    base = min(2 ** attempts, 60)            # 2, 4, 8, 16, 32 … capped at 60s
    jitter = random.uniform(0, base * 0.5)   # up to +50%, randomized
    return base + jitter


def schedule_retry(delivery, status_code, error):
    attempts = delivery["attempts"] + 1
    if attempts >= MAX_ATTEMPTS:
        mark_failed(delivery, status_code, error or "max attempts reached")
        return

    delay = backoff_seconds(attempts)
    next_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE deliveries SET status='pending', attempts=?, next_attempt_at=?, "
            "last_status_code=?, last_error=?, updated_at=? WHERE id=?",
            (attempts, next_at, status_code, error, now, delivery["id"]),
        )
        conn.commit()
    finally:
        conn.close()
        
def recover_stuck_deliveries():
    """On boot, any ticket left 'in_progress' is leftover from a crash
    mid-delivery — reset it to 'pending' so it gets tried again."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE deliveries SET status='pending', next_attempt_at=?, updated_at=? "
            "WHERE status='in_progress'",
            (now, now),
        )
        conn.commit()
    finally:
        conn.close()