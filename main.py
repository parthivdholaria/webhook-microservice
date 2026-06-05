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
from utils.db import init_db, get_connection
from utils.helpers import recover_stuck_deliveries
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

templates = Jinja2Templates(directory="templates")

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
    yield           
    stop_event.set()              
    worker_thread.join(timeout=5)  

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
            if sub["event_filter"] == event.type or sub["event_filter"] == "*":
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


# FrontEnd APIs
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_events(request: Request):
    conn = get_connection()
    try:
        events = [dict(r) for r in conn.execute(
            "SELECT id, type, received_at FROM events ORDER BY received_at DESC LIMIT 50"
        ).fetchall()]
    finally:
        conn.close()
    return templates.TemplateResponse(
        request=request, name="events.html", context={"events": events}
    )
    
@app.get("/dashboard/events/{event_id}", response_class=HTMLResponse)
def dashboard_event_detail(request: Request, event_id: str):
    conn = get_connection()
    try:
        event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        deliveries = [dict(r) for r in conn.execute(
            """
            SELECT d.id, d.status, d.attempts, d.last_status_code, d.last_error,
                   s.target_url
            FROM deliveries d
            JOIN subscriptions s ON s.id = d.subscription_id
            WHERE d.event_id = ?
            ORDER BY d.updated_at
            """,
            (event_id,),
        ).fetchall()]
    finally:
        conn.close()

    if event is None:
        raise HTTPException(status_code=404, detail="event not found")

    return templates.TemplateResponse(
        request=request, name="event_detail.html",
        context={"event": dict(event), "deliveries": deliveries},
    )
    
@app.get("/dashboard/subscriptions", response_class=HTMLResponse)
def dashboard_subscriptions(request: Request):
    conn = get_connection()
    try:
        subs = [dict(r) for r in conn.execute(
            "SELECT * FROM subscriptions ORDER BY created_at DESC"
        ).fetchall()]
    finally:
        conn.close()
    return templates.TemplateResponse(
        request=request, name="subscriptions.html", context={"subscriptions": subs}
    )

@app.post("/dashboard/deliveries/{delivery_id}/retry")
def retry_delivery(delivery_id: str):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT event_id, status FROM deliveries WHERE id = ?",
            (delivery_id,),
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="delivery not found")

        # only a failed ticket can be hand-retried
        if row["status"] == "failed":
            conn.execute(
                "UPDATE deliveries SET status='pending', attempts=0, "
                "next_attempt_at=?, last_error=NULL, updated_at=? WHERE id=?",
                (now, now, delivery_id),
            )
            conn.commit()

        event_id = row["event_id"]
    finally:
        conn.close()

    return RedirectResponse(url=f"/dashboard/events/{event_id}", status_code=303)
