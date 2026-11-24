from __future__ import annotations

import base64
import os
import random
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.file",
]
OPT_OUT_WORDS = ("unsubscribe", "opt out", "opt-out", "no thanks", "stop emailing", "remove me", "don't email")


def _path_from_env(env_name: str, default: str, root: Path) -> Path:
    raw = os.getenv(env_name, default)
    p = Path(os.path.expandvars(raw))
    return p if p.is_absolute() else root / p


def build_services(cfg) -> tuple[Any, Any]:
    """OAuth handshake (first run opens a browser) -> (gmail, drive) services."""
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds_path = _path_from_env("GMAIL_CREDENTIALS_FILE", "credentials.json", cfg.root)
    token_path = _path_from_env("GMAIL_TOKEN_FILE", "token.json", cfg.root)
    if not creds_path.exists():
        raise RuntimeError(
            f"Missing {creds_path}. Download an OAuth client JSON from Google Cloud "
            "and save it as credentials.json (see README)."
        )

    creds = None
    if token_path.exists():
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        os.chmod(token_path, 0o600)
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    return gmail, drive


def sender_email(cfg) -> str:
    return (
        os.getenv("GMAIL_SENDER_EMAIL", "")
        or cfg["profile"].get("sender_email", "")
        or "me"
    )


def make_raw_message(to: str, subject: str, body: str, from_addr: str) -> str:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg["List-Unsubscribe"] = f"<mailto:{from_addr}?subject=unsubscribe>"
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def send_one(gmail, cfg, to: str, subject: str, body: str) -> str:
    raw = make_raw_message(to, subject, body, sender_email(cfg))
    sent = gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
    return str(sent.get("id", ""))


def respect_delay(seconds: int, jitter: float = 0.35) -> None:
    if seconds <= 0:
        return
    delay = seconds * (1 + random.uniform(-jitter, jitter))
    time.sleep(max(1.0, delay))


def in_send_window(cfg) -> bool:
    """Check local business-hours window. Returns True if config has no window."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    window = (cfg["limits"].get("send_window") or "").strip()
    if not window or window.lower() == "any":
        return True
    try:
        start_s, end_s = window.split("-")
        start = datetime.strptime(start_s.strip(), "%H:%M").time()
        end = datetime.strptime(end_s.strip(), "%H:%M").time()
        tz = ZoneInfo(cfg["limits"].get("timezone", "UTC"))
        current = datetime.now(tz).time()
        return start <= current <= end
    except (ValueError, KeyError):
        return True


def find_opt_outs(gmail, sent_emails: list[str], days: int = 14) -> list[str]:
    """Inspect replies to recent sends for opt-out language."""
    flagged = []
    for email in sent_emails:
        query = f"in:inbox newer_than:{days}d from:({email})"
        try:
            result = gmail.users().messages().list(userId="me", q=query, maxResults=10).execute()
        except Exception:  # noqa: BLE001
            continue
        for item in result.get("messages", []):
            try:
                msg = gmail.users().messages().get(userId="me", id=item["id"], format="metadata",
                                                   metadataHeaders=["From"]).execute()
            except Exception:  # noqa: BLE001
                continue
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            if email.lower() not in headers.get("from", "").lower():
                continue
            snippet = (msg.get("snippet") or "").lower()
            if any(word in snippet for word in OPT_OUT_WORDS):
                flagged.append(email)
                break
    return flagged


def upload_to_drive(drive, file_path: Path, name: str | None = None,
                    folder_id: str | None = None, to_sheet: bool = False) -> dict:
    from googleapiclient.http import MediaFileUpload

    file_path = Path(file_path)
    mime = "text/csv" if file_path.suffix.lower() == ".csv" else "text/html"
    media = MediaFileUpload(str(file_path), mimetype=mime, resumable=False)
    metadata: dict[str, Any] = {"name": name or file_path.name}
    if folder_id:
        metadata["parents"] = [folder_id]
    if to_sheet:
        metadata["mimeType"] = "application/vnd.google-apps.spreadsheet"
    return drive.files().create(body=metadata, media_body=media, fields="id,name,webViewLink").execute()
