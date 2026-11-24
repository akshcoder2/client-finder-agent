from __future__ import annotations

import json
import os
import random
from typing import Any

import requests

from .db import DB

SENDABLE_CONFIDENCE = {"high", "medium", "verified"}


HONORIFICS = {"dr.", "dr", "mr.", "mr", "mrs.", "mrs", "ms.", "ms", "prof.", "prof", "shri", "smt."}


def first_name(lead: dict[str, Any]) -> str:
    parts = (lead.get("contact_name") or "").strip().split()
    if not parts:
        return "there"
    if parts[0].lower() in HONORIFICS:
        return f"{parts[0]} {parts[-1]}" if len(parts) > 1 else parts[0]
    return parts[0]


def is_sendable(lead: dict[str, Any]) -> bool:
    return bool(lead.get("email")) and (lead.get("email_confidence") in SENDABLE_CONFIDENCE)


def template_draft(lead: dict[str, Any], profile: dict[str, Any]) -> tuple[str, str]:
    company = lead.get("company") or "your company"
    who = first_name(lead)
    offer = profile.get("offer", "we help businesses grow")
    context = ""
    headline = (lead.get("headline") or "").strip()
    if headline:
        context = f" I noticed your profile mentions {headline.lower()}." if len(headline) < 90 else ""
    if lead.get("source") == "maps" and lead.get("rating"):
        context = f" I saw your {lead['rating']}★ rating on Google Maps and thought I'd reach out."

    subject = random.choice(
        [
            f"Quick idea for {company}",
            f"{company} + {profile.get('company', 'us')}",
            f"A thought about {company}",
        ]
    )
    body = (
        f"Hi {who},\n\n"
        f"I came across {company}.{context} I'm {profile.get('name', 'reach out from')} from "
        f"{profile.get('company', 'my company')}, and {offer}.\n\n"
        "Would you be open to a quick 10-minute call this week? I can share a couple of "
        "specific ideas — no pitch deck, no pressure.\n\n"
        f"{profile.get('signature', 'Best regards')}\n\n"
        "P.S. If you'd rather not hear from me, just reply \"no thanks\" and I won't follow up.\n"
        f"{profile.get('physical_address', '')}"
    ).rstrip()
    return subject, body


def llm_draft(lead: dict[str, Any], profile: dict[str, Any], llm: dict[str, Any]) -> tuple[str, str]:
    api_key = os.getenv(llm.get("api_key_env", "LLM_API_KEY"), "").strip()
    if not api_key:
        raise RuntimeError("LLM enabled but API key is empty")
    base_url = os.getenv("LLM_BASE_URL", llm.get("base_url", "https://api.openai.com/v1")).rstrip("/")
    prompt = f"""Write ONE short, genuinely personal cold email (max 110 words) to a potential client.
Use only the facts below. Do not invent details, numbers, or claims.
Tone: warm, concise, specific, no hype, no "I hope this email finds you well".
Ask for a 10-minute call. Include the exact signature and physical address at the end.

Prospect:
{json.dumps({k: lead.get(k) for k in ('company','contact_name','headline','city','rating','source','website')}, ensure_ascii=False)}

Sender profile:
{json.dumps(profile, ensure_ascii=False)}

Reply with strict JSON: {{"subject": "...", "body": "..."}}"""
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": llm.get("model", "gpt-4o-mini"),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": int(llm.get("max_tokens", 350)),
            "temperature": 0.6,
        },
        timeout=40,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()
    data = json.loads(content)
    subject = str(data["subject"]).strip()
    body = str(data["body"]).strip()
    if not subject or not body:
        raise ValueError("LLM returned an empty subject or body")
    return subject, body


def draft_all(db: DB, cfg) -> tuple[int, int]:
    """Create drafts for sendable leads that have no email yet."""
    profile = cfg["profile"]
    llm_cfg = cfg["llm"]
    created = skipped = 0
    for lead in db.leads("status NOT IN ('sent','opted_out')"):
        existing = db.emails()
        if any(e["lead_id"] == lead["id"] for e in existing):
            continue
        if not is_sendable(lead):
            skipped += 1
            continue
        if db.is_suppressed(lead["email"]):
            skipped += 1
            continue
        subject, body = template_draft(lead, profile)
        if llm_cfg.get("enabled"):
            try:
                subject, body = llm_draft(lead, profile, llm_cfg)
            except Exception as exc:  # noqa: BLE001 - fall back to the free template
                print(f"  ! LLM failed for {lead['company']}: {exc}; using template")
        db.put_email(lead["id"], subject, body, "draft")
        db.update_lead(lead["id"], status="drafted")
        created += 1
    return created, skipped
