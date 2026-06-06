import sqlite3
from pathlib import Path

import os
DB_PATH = Path(os.environ.get("DB_PATH", "webhooks.db"))

# DB_PATH = Path(__file__).parent / "webhooks.db"   # use this when testing using uvicorn app

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row           
    conn.execute("PRAGMA journal_mode=WAL")  
    conn.execute("PRAGMA foreign_keys=ON") 
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id           TEXT PRIMARY KEY,
            type         TEXT NOT NULL,
            payload      TEXT NOT NULL,
            received_at  TEXT NOT NULL
        )
        """
    )
    
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            id            TEXT PRIMARY KEY,
            target_url    TEXT NOT NULL,
            secret        TEXT,
            event_filter  TEXT NOT NULL,
            created_at    TEXT NOT NULL
        )
        """
    )
    
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS deliveries (
            id                TEXT PRIMARY KEY,
            event_id          TEXT NOT NULL,
            subscription_id   TEXT NOT NULL,
            status            TEXT NOT NULL DEFAULT 'pending',
            attempts          INTEGER NOT NULL DEFAULT 0,
            next_attempt_at   TEXT NOT NULL,
            last_status_code  INTEGER,
            last_error        TEXT,
            updated_at        TEXT NOT NULL,
            FOREIGN KEY (event_id)        REFERENCES events(id),
            FOREIGN KEY (subscription_id) REFERENCES subscriptions(id)
        )
        """
    )

    conn.commit()
    conn.close()