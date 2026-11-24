from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

LEAD_COLUMNS = (
    "source", "external_id", "company", "contact_name", "email",
    "email_confidence", "email_source", "website", "phone", "rating",
    "address", "city", "linkedin_url", "headline", "score", "status",
    "notes", "created_at",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  company TEXT NOT NULL,
  contact_name TEXT,
  email TEXT,
  email_confidence TEXT,
  email_source TEXT,
  website TEXT,
  phone TEXT,
  rating REAL,
  address TEXT,
  city TEXT,
  linkedin_url TEXT,
  headline TEXT,
  score INTEGER DEFAULT 0,
  status TEXT DEFAULT 'new',
  notes TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);

CREATE TABLE IF NOT EXISTS emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT DEFAULT 'draft',
  created_at TEXT NOT NULL,
  sent_at TEXT,
  message_id TEXT,
  UNIQUE(lead_id)
);

CREATE TABLE IF NOT EXISTS sends (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER NOT NULL,
  email_id INTEGER NOT NULL,
  sent_at TEXT NOT NULL,
  message_id TEXT,
  status TEXT NOT NULL,
  error TEXT
);

CREATE TABLE IF NOT EXISTS suppression (
  email TEXT PRIMARY KEY,
  reason TEXT,
  created_at TEXT NOT NULL
);
"""

EMAIL_STATUSES = {"draft", "approved", "sent", "failed"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_id(*parts: Any) -> str:
    raw = "|".join(str(p or "") for p in parts).lower().strip()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class DB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "DB":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ---------- leads ----------

    def upsert_lead(self, lead: dict) -> tuple[int, bool]:
        """Insert or merge a lead. Returns (id, created)."""
        source = lead.get("source") or "import"
        external_id = str(
            lead.get("external_id")
            or make_id(lead.get("company"), lead.get("email"), lead.get("linkedin_url"), lead.get("website"))
        )
        row = self.conn.execute(
            "SELECT id FROM leads WHERE source=? AND external_id=?", (source, external_id)
        ).fetchone()
        clean = {k: lead.get(k) for k in LEAD_COLUMNS}
        clean["source"] = source
        clean["external_id"] = external_id
        clean["status"] = clean.get("status") or "new"
        clean["score"] = int(clean.get("score") or 0)
        if not clean.get("created_at"):
            clean["created_at"] = now_iso()
        # Never overwrite a send/status with stale source data.
        if row:
            self.conn.execute(
                "UPDATE leads SET " + ", ".join(f"{k}=?" for k in LEAD_COLUMNS) + " WHERE id=?",
                [clean[k] for k in LEAD_COLUMNS] + [row["id"]],
            )
            self.conn.commit()
            return int(row["id"]), False
        cur = self.conn.execute(
            "INSERT INTO leads (" + ", ".join(LEAD_COLUMNS) + ") VALUES (" + ", ".join("?" for _ in LEAD_COLUMNS) + ")",
            [clean[k] for k in LEAD_COLUMNS],
        )
        self.conn.commit()
        return int(cur.lastrowid), True

    def update_lead(self, lead_id: int, **fields: Any) -> None:
        bad = [k for k in fields if k not in LEAD_COLUMNS]
        if bad:
            raise ValueError(f"Unknown lead fields: {bad}")
        if not fields:
            return
        self.conn.execute(
            "UPDATE leads SET " + ", ".join(f"{k}=?" for k in fields) + " WHERE id=?",
            list(fields.values()) + [lead_id],
        )
        self.conn.commit()

    def get_lead(self, lead_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        return dict(row) if row else None

    def leads(self, where: str = "1=1", params: Iterable[Any] = ()) -> list[dict]:
        rows = self.conn.execute(f"SELECT * FROM leads WHERE {where} ORDER BY score DESC, id", tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def lead_by_email(self, email: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM leads WHERE lower(email)=lower(?)", (email,)).fetchone()
        return dict(row) if row else None

    # ---------- emails ----------

    def put_email(self, lead_id: int, subject: str, body: str, status: str = "draft") -> int:
        if status not in EMAIL_STATUSES:
            raise ValueError(f"Bad email status: {status}")
        existing = self.conn.execute("SELECT id, status FROM emails WHERE lead_id=?", (lead_id,)).fetchone()
        if existing:
            new_status = existing["status"] if existing["status"] == "sent" else status
            self.conn.execute(
                "UPDATE emails SET subject=?, body=?, status=?, created_at=? WHERE lead_id=?",
                (subject, body, new_status, now_iso(), lead_id),
            )
            self.conn.commit()
            return int(existing["id"])
        cur = self.conn.execute(
            "INSERT INTO emails (lead_id, subject, body, status, created_at) VALUES (?,?,?,?,?)",
            (lead_id, subject, body, status, now_iso()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def emails(self, status: str | None = None, with_lead: bool = False) -> list[dict]:
        if with_lead:
            sql = """SELECT e.*, l.company, l.contact_name, l.email, l.email_confidence,
                            l.website, l.source, l.status AS lead_status
                     FROM emails e JOIN leads l ON l.id=e.lead_id"""
            if status:
                sql += " WHERE e.status=?"
            sql += " ORDER BY e.id"
        else:
            sql = "SELECT * FROM emails"
            if status:
                sql += " WHERE status=?"
            sql += " ORDER BY id"
        rows = self.conn.execute(sql, (status,) if status else ()).fetchall()
        return [dict(r) for r in rows]

    def approve_email(self, email_id: int) -> None:
        self.conn.execute("UPDATE emails SET status='approved' WHERE id=? AND status='draft'", (email_id,))
        self.conn.commit()

    def approve_all_high_confidence(self) -> int:
        cur = self.conn.execute(
            """UPDATE emails SET status='approved'
               WHERE status='draft' AND lead_id IN (
                 SELECT id FROM leads WHERE email_confidence='high' AND email IS NOT NULL AND status!='opted_out'
               )"""
        )
        self.conn.commit()
        return cur.rowcount

    def mark_sent(self, email_id: int, message_id: str) -> None:
        ts = now_iso()
        self.conn.execute(
            "UPDATE emails SET status='sent', sent_at=?, message_id=? WHERE id=?", (ts, message_id, email_id)
        )
        row = self.conn.execute("SELECT lead_id FROM emails WHERE id=?", (email_id,)).fetchone()
        if row:
            self.conn.execute("UPDATE leads SET status='sent' WHERE id=?", (row["lead_id"],))
            self.conn.execute(
                "INSERT INTO sends (lead_id,email_id,sent_at,message_id,status) VALUES (?,?,?,?,'sent')",
                (row["lead_id"], email_id, ts, message_id),
            )
        self.conn.commit()

    def mark_failed(self, email_id: int, error: str) -> None:
        self.conn.execute("UPDATE emails SET status='failed' WHERE id=?", (email_id,))
        row = self.conn.execute("SELECT lead_id FROM emails WHERE id=?", (email_id,)).fetchone()
        if row:
            self.conn.execute(
                "INSERT INTO sends (lead_id,email_id,sent_at,status,error) VALUES (?,?,?, 'failed', ?)",
                (row["lead_id"], email_id, now_iso(), error[:500]),
            )
        self.conn.commit()

    def sent_in_last_hours(self, hours: int = 24) -> int:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        return int(self.conn.execute("SELECT count(*) FROM sends WHERE status='sent' AND sent_at>=?", (since,)).fetchone()[0])

    # ---------- suppression ----------

    def suppress(self, email: str, reason: str = "opt-out") -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO suppression (email, reason, created_at) VALUES (?,?,?)",
            (email.lower().strip(), reason, now_iso()),
        )
        self.conn.execute("UPDATE leads SET status='opted_out' WHERE lower(email)=lower(?)", (email,))
        self.conn.execute(
            "UPDATE emails SET status='draft' WHERE status IN ('approved','draft') AND lead_id IN "
            "(SELECT id FROM leads WHERE lower(email)=lower(?))",
            (email,),
        )
        self.conn.commit()

    def is_suppressed(self, email: str) -> bool:
        if not email:
            return False
        return self.conn.execute("SELECT 1 FROM suppression WHERE email=?", (email.lower().strip(),)).fetchone() is not None

    def stats(self) -> dict:
        def count(sql: str) -> int:
            return int(self.conn.execute(sql).fetchone()[0])

        return {
            "leads": count("SELECT count(*) FROM leads"),
            "with_email": count("SELECT count(*) FROM leads WHERE email IS NOT NULL"),
            "drafts": count("SELECT count(*) FROM emails WHERE status='draft'"),
            "approved": count("SELECT count(*) FROM emails WHERE status='approved'"),
            "sent_total": count("SELECT count(*) FROM sends WHERE status='sent'"),
            "sent_24h": self.sent_in_last_hours(24),
            "suppressed": count("SELECT count(*) FROM suppression"),
        }

    def export_rows(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT l.id, l.source, l.company, l.contact_name, l.email, l.email_confidence,
                      l.website, l.phone, l.rating, l.address, l.city, l.linkedin_url,
                      l.score, l.status, e.subject, e.body, e.status AS email_status
               FROM leads l LEFT JOIN emails e ON e.lead_id=l.id
               ORDER BY l.score DESC, l.id"""
        ).fetchall()
        return [dict(r) for r in rows]
