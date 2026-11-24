from __future__ import annotations

import csv
import html
import os
from datetime import datetime
from pathlib import Path

from .db import DB

FIELDS = [
    "id", "source", "company", "contact_name", "email", "email_confidence",
    "website", "phone", "rating", "city", "linkedin_url", "score", "status",
    "subject", "body", "email_status",
]


def export_csv(db: DB, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = db.export_rows()
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in FIELDS})
    return path


def export_preview_html(db: DB, path: str | Path, profile: dict | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = profile or {}
    rows = [e for e in db.emails(with_lead=True)]
    cards = []
    for row in rows:
        badge = {
            "draft": "#f59e0b", "approved": "#22c55e", "sent": "#3b82f6", "failed": "#ef4444"
        }.get(row["status"], "#94a3b8")
        cards.append(
            f"""<article class="card">
              <div class="meta"><span class="dot" style="background:{badge}"></span>
              <strong>{html.escape(str(row.get('company') or ''))}</strong>
              <span class="pill">{html.escape(str(row.get('status')))}</span></div>
              <div class="to">To: {html.escape(str(row.get('email') or 'no email'))}
              &nbsp;·&nbsp; {html.escape(str(row.get('email_confidence') or '—'))} confidence</div>
              <h3>{html.escape(str(row.get('subject') or ''))}</h3>
              <pre>{html.escape(str(row.get('body') or ''))}</pre>
            </article>"""
        )
    if not cards:
        cards.append('<div class="empty">No drafts yet. Run <code>draft</code> first.</div>')
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Outreach preview — {html.escape(str(profile.get('company', 'Client Finder Agent')))}</title>
    <style>
      body{{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;background:#f6f7fb;color:#101828;margin:0;padding:32px}}
      main{{max-width:820px;margin:auto}} h1{{font-size:26px;margin:0 0 6px}}
      .sub{{color:#667085;margin-bottom:28px;font-size:14px}}
      .card{{background:#fff;border:1px solid #e4e7ec;border-radius:14px;padding:20px 22px;margin-bottom:16px;box-shadow:0 1px 3px #1018280d}}
      .meta{{display:flex;align-items:center;gap:8px;font-size:15px}}
      .dot{{width:9px;height:9px;border-radius:50%;display:inline-block}}
      .pill{{margin-left:auto;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#667085;border:1px solid #e4e7ec;border-radius:99px;padding:3px 9px}}
      .to{{color:#667085;font-size:12px;margin:8px 0 14px}}
      h3{{font-size:16px;margin:0 0 10px}}
      pre{{white-space:pre-wrap;word-wrap:break-word;font:13px/1.65 ui-sans-serif,system-ui,sans-serif;color:#344054;margin:0}}
      .empty{{background:#fff;border:1px dashed #d0d5dd;border-radius:14px;padding:40px;text-align:center;color:#667085}}
    </style></head><body><main>
    <h1>Outreach preview</h1>
    <div class="sub">Generated {html.escape(datetime.now().strftime('%d %b %Y, %H:%M'))} · {len(rows)} drafted emails · Review before sending</div>
    {''.join(cards)}
    </main></body></html>"""
    path.write_text(doc, encoding="utf-8")
    return path
