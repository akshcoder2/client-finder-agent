from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .db import make_id

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = (
    "places.id,places.displayName,places.formattedAddress,places.websiteUri,"
    "places.nationalPhoneNumber,places.internationalPhoneNumber,places.rating,"
    "places.userRatingCount,places.businessStatus,places.googleMapsUri,nextPageToken"
)


def find_maps(query: str, location: str, limit: int = 20) -> list[dict]:
    """Find local businesses with the official Google Places API (New)."""
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not set. Add it to .env (Places API (New)).")

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELDS,
    }
    leads: list[dict] = []
    token = None
    while len(leads) < limit:
        body: dict[str, Any] = {
            "textQuery": f"{query} in {location}".strip(),
            "pageSize": min(20, limit - len(leads)),
            "languageCode": "en",
        }
        if token:
            body["pageToken"] = token
        resp = requests.post(PLACES_URL, headers=headers, json=body, timeout=25)
        resp.raise_for_status()
        data = resp.json()
        for place in data.get("places", []):
            name = (place.get("displayName") or {}).get("text", "")
            if not name:
                continue
            leads.append(
                {
                    "source": "maps",
                    "external_id": str(place.get("id") or make_id("maps", name, place.get("websiteUri"))),
                    "company": name,
                    "contact_name": None,
                    "email": None,
                    "email_confidence": None,
                    "email_source": None,
                    "website": place.get("websiteUri"),
                    "phone": place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber"),
                    "rating": place.get("rating"),
                    "address": place.get("formattedAddress"),
                    "city": location,
                    "linkedin_url": place.get("googleMapsUri"),
                    "headline": f"{query} · {place.get('userRatingCount', 0)} Google reviews",
                    "notes": f"Google Maps: {place.get('businessStatus', 'OPERATIONAL')}",
                }
            )
        token = data.get("nextPageToken")
        if not token:
            break
    return leads[:limit]


HEADER_ALIASES = {
    "contact_name": ["contact name", "full name", "recipient name", "prospect name", "name"],
    "first_name": ["first name"],
    "last_name": ["last name", "surname"],
    "company": ["company", "company name", "current company", "organization", "account"],
    "email": ["email", "email address", "e-mail", "work email"],
    "website": ["website", "company website", "domain", "company domain"],
    "linkedin_url": ["profile url", "linkedin profile url", "linkedin url", "url", "sales navigator url"],
    "headline": ["headline", "title", "job title", "position", "current position"],
    "location": ["location", "city", "geography"],
    "phone": ["phone", "phone number", "mobile"],
}


def _normalise_header(value: str) -> str:
    return value.strip().lower().replace("_", " ").replace("-", " ")


def import_linkedin_csv(path: str | Path) -> list[dict]:
    """Import a manually exported LinkedIn / Sales Navigator CSV.

    This deliberately does NOT log in to LinkedIn or scrape search results —
    that breaks LinkedIn's terms. Export the list from the UI, then import it.
    """
    p = Path(path)
    if not p.is_absolute():
        p = Path.cwd() / p
    if not p.exists():
        raise FileNotFoundError(f"LinkedIn CSV not found: {p}")

    with p.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        headers = {_normalise_header(h or ""): h for h in (reader.fieldnames or [])}
        col = {
            key: next((headers[a] for a in aliases if a in headers), None)
            for key, aliases in HEADER_ALIASES.items()
        }
        leads = []
        for row in reader:
            def get(key: str) -> str:
                value = row.get(col[key]) if col[key] else ""
                return str(value or "").strip()

            first, last = get("first_name"), get("last_name")
            contact = get("contact_name") or " ".join(x for x in (first, last) if x)
            company = get("company")
            email = get("email")
            linkedin = get("linkedin_url")
            website = get("website")
            if not (company or contact or email):
                continue
            if not website and email and "@" in email and "linkedin.com" not in email:
                website = "https://" + email.split("@")[-1]
            leads.append(
                {
                    "source": "linkedin",
                    "external_id": str(make_id("linkedin", linkedin or email or company, contact)),
                    "company": company or contact,
                    "contact_name": contact or None,
                    "email": email.lower() or None,
                    "email_confidence": "high" if email else None,
                    "email_source": "linkedin_export" if email else None,
                    "website": website or None,
                    "phone": get("phone") or None,
                    "rating": None,
                    "address": get("location") or None,
                    "city": get("location") or None,
                    "linkedin_url": linkedin or None,
                    "headline": get("headline") or None,
                    "notes": "Imported from LinkedIn/Sales Navigator CSV export",
                }
            )
    return leads


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host or None


def demo_leads() -> list[dict]:
    """Offline sample leads so the whole pipeline can be tried without API keys."""
    samples = [
        ("Smile Dental Clinic", "Dr. Neha Sharma", "smiledental-indore.com", "hello@smiledental-indore.com", 4.6, "dentist"),
        ("Urban Nest Interiors", "Rohit Malhotra", "urbannestindore.in", "contact@urbannestindore.in", 4.8, "interior designer"),
        ("Pulse Physiotherapy", "Dr. Anjali Verma", "pulsephysioindore.com", "info@pulsephysioindore.com", 4.5, "physiotherapy"),
        ("The Bake House", "Meera Joshi", "thebakehouseindore.com", "meera@thebakehouseindore.com", 4.7, "bakery"),
        ("Clearview Opticians", "Vikram Sethi", "clearviewindore.in", None, 4.4, "optician"),
        ("GrowthCurve Consulting", "Sameer Rao", "growthcurve.example", "sameer@growthcurve.example", None, "consultant"),
    ]
    leads = []
    for i, (company, contact, domain, email, rating, niche) in enumerate(samples):
        leads.append(
            {
                "source": "demo" if i < 5 else "linkedin",
                "external_id": f"demo-{i}",
                "company": company,
                "contact_name": contact,
                "email": email,
                "email_confidence": "high" if email else None,
                "email_source": "demo_sample" if email else None,
                "website": f"https://{domain}",
                "phone": f"+91 9{i}123 4567{i}",
                "rating": rating,
                "address": f"{i + 12}, MG Road, Indore, Madhya Pradesh",
                "city": "Indore, India",
                "linkedin_url": f"https://www.linkedin.com/in/sample-{i}" if i >= 5 else None,
                "headline": f"{niche.title()} · Indore",
                "notes": "Sample data — no real emails were contacted",
            }
        )
    return leads
