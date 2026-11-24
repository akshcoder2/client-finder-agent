from __future__ import annotations

import re
from typing import Any

import requests
from bs4 import BeautifulSoup

from .db import DB
from .sources import domain_of

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
JUNK_WORDS = ("noreply", "no-reply", "donotreply", "postmaster", "example.com", "sentry", "wixsite")
GENERIC_LOCALPARTS = {"info", "hello", "contact", "enquiry", "inquiry", "sales", "team", "admin", "support"}


def _clean_emails(raw: str, domain: str | None) -> list[str]:
    found = []
    for match in EMAIL_RE.findall(raw or ""):
        email = match.lower().strip(".,;:")
        if any(junk in email for junk in JUNK_WORDS):
            continue
        if email.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")):
            continue
        if domain and not email.endswith("@" + domain):
            # Keep it, but rank domain-matching addresses first below.
            pass
        if email not in found:
            found.append(email)
    if domain:
        found.sort(key=lambda e: (not e.endswith("@" + domain), e in ("",)))
    return found


def discover_email(website: str | None, contact_name: str | None = None,
                   allow_generic: bool = False, allow_guessed: bool = False,
                   fetch: bool = True) -> tuple[str | None, str | None, str | None]:
    """Find an email on a company website. Returns (email, confidence, source).

    Pattern-guessed addresses are returned only when explicitly allowed, and are
    always labelled 'guessed' so they can never be auto-approved by mistake.
    """
    domain = domain_of(website)
    if not domain:
        return None, None, None

    page = ""
    if fetch:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; ClientFinderAgent/0.1; +research)"}
        for url in [website, website.rstrip("/") + "/contact", website.rstrip("/") + "/contact-us"]:
            try:
                resp = requests.get(url, headers=headers, timeout=8, allow_redirects=True)
                if resp.status_code == 200:
                    page += resp.text[:400_000]
            except requests.RequestException:
                continue
            if EMAIL_RE.search(page) and "mailto:" in page:
                break

    soup = BeautifulSoup(page, "html.parser") if page else None
    raw = page or ""
    if soup:
        for tag in soup.find_all("a", href=True):
            if tag["href"].lower().startswith("mailto:"):
                raw += " " + tag["href"][7:]

    emails = _clean_emails(raw, domain)
    personal = []
    generic = []
    for email in emails:
        local = email.split("@")[0]
        (generic if local in GENERIC_LOCALPARTS else personal).append(email)

    if personal:
        return personal[0], "high", "website"
    if generic and allow_generic:
        return generic[0], "medium", "website_generic"
    if generic:
        return generic[0], "medium", "found_not_sendable"

    if allow_guessed and contact_name:
        parts = re.sub(r"[^a-z ]", "", contact_name.lower()).split()
        if len(parts) >= 2:
            candidates = [f"{parts[0]}.{parts[-1]}@{domain}", f"{parts[0]}@{domain}"]
        elif parts:
            candidates = [f"{parts[0]}@{domain}"]
        else:
            candidates = []
        for candidate in candidates:
            if candidate not in JUNK_WORDS:
                return candidate, "guessed", "pattern_guess"
    return None, None, None


def score_lead(lead: dict[str, Any]) -> int:
    score = 0
    if lead.get("email"):
        score += 35
        if lead.get("email_confidence") == "high":
            score += 15
    if lead.get("contact_name"):
        score += 15
    if lead.get("website"):
        score += 10
    if lead.get("rating"):
        try:
            score += min(15, int(float(lead["rating"]) * 3))
        except (TypeError, ValueError):
            pass
    if lead.get("headline"):
        score += 5
    if lead.get("source") == "linkedin":
        score += 5
    return min(100, score)


def enrich_all(db: DB, cfg, fetch: bool = True) -> tuple[int, int]:
    """Discover emails for leads that need one. Returns (checked, enriched)."""
    sourcing = cfg["sourcing"]
    leads = db.leads("email IS NULL OR email_confidence IN ('guessed','found_not_sendable')")
    checked = enriched = 0
    for lead in leads:
        if lead.get("email") and lead.get("email_confidence") == "found_not_sendable" and not sourcing["allow_generic_email"]:
            # Already inspected; keep as-is unless policy changes.
            continue
        checked += 1
        email, confidence, source = discover_email(
            lead.get("website"),
            lead.get("contact_name"),
            allow_generic=bool(sourcing["allow_generic_email"]),
            allow_guessed=bool(sourcing["allow_guessed_email"]),
            fetch=fetch,
        )
        if email:
            enriched += 1
            db.update_lead(lead["id"], email=email, email_confidence=confidence, email_source=source)
        db.update_lead(lead["id"], score=score_lead({**lead, "email": email, "email_confidence": confidence}))
    # Refresh scores for leads that already have emails.
    for lead in db.leads("email IS NOT NULL"):
        if lead["id"] not in {l["id"] for l in leads}:
            db.update_lead(lead["id"], score=score_lead(lead))
    return checked, enriched
