import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import threading
from webhook_service.worker import run_worker
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel
from utils.matching import filter_matches
from utils.db import init_db, get_connection
from utils.helpers import recover_stuck_deliveries

class EventIn(BaseModel):
    type: str
    payload: dict   
    
class SubscriptionIn(BaseModel):
    target_url: str
    event_filter: str
    secret: Optional[str] = None
    
    
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    recover_stuck_deliveries()
    stop_event = threading.Event()
    worker_thread = threading.Thread(target=run_worker, args=(stop_event,), daemon=True)
    worker_thread.start()
    yield                          # the app runs (and the worker hums along)
    stop_event.set()               # on shutdown, ask the worker to stop
    worker_thread.join(timeout=5)  # give its current pass a moment to finish

app = FastAPI(lifespan=lifespan)

@app.post("/events")
def ingest_event(event: EventIn):
    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    try:
        # 1. save the event
        conn.execute(
            "INSERT INTO events (id, type, payload, received_at) VALUES (?, ?, ?, ?)",
            (event_id, event.type, json.dumps(event.payload), now),
        )

        # 2. find matching subscribers and pin one 'pending' ticket each
        subs = conn.execute("SELECT id, event_filter FROM subscriptions").fetchall()
        tickets = 0
        for sub in subs:
            if filter_matches(event.type, sub["event_filter"]):
                conn.execute(
                    """
                    INSERT INTO deliveries
                        (id, event_id, subscription_id, status, attempts, next_attempt_at, updated_at)
                    VALUES (?, ?, ?, 'pending', 0, ?, ?)
                    """,
                    (str(uuid.uuid4()), event_id, sub["id"], now, now),
                )
                tickets += 1

        conn.commit()   # 3. event + all its tickets saved together, atomically
    finally:
        conn.close()

    return {"status": "accepted", "event_id": event_id, "tickets_created": tickets}


@app.post("/subscriptions")
def create_subscription(sub: SubscriptionIn):
    sub_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO subscriptions (id, target_url, secret, event_filter, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (sub_id, sub.target_url, sub.secret, sub.event_filter, created_at),
    )
    conn.commit()
    conn.close()

    return {"status": "created", "subscription_id": sub_id}
