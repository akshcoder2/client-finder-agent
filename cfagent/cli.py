from __future__ import annotations

import shutil
from pathlib import Path

import click

from . import drafting, enrich, reports, sources
from .config import ROOT, Config
from .db import DB


def _open(cfg: Config) -> DB:
    cfg.ensure_dirs()
    return DB(cfg.path_for("db"))


@click.group()
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.pass_context
def cli(ctx: click.Context, config_path: str | None) -> None:
    """Find clients and send personalised outreach — carefully."""
    ctx.obj = Config.load(config_path) if config_path else Config.load()


@cli.command()
@click.pass_obj
def init(cfg: Config) -> None:
    """Create config.yaml, .env and folders (safe to re-run)."""
    cfg.ensure_dirs()
    for src, dest in [
        ("config.example.yaml", "config.yaml"),
        (".env.example", ".env"),
    ]:
        source, target = ROOT / src, cfg.root / dest
        if not target.exists() and source.exists():
            shutil.copy(source, target)
            click.echo(f"created {target}")
    click.echo("Now edit config.yaml and .env, then run: demo | find | run")


@cli.command()
@click.pass_obj
def demo(cfg: Config) -> None:
    """Seed offline sample leads, draft emails and export a preview (no network, no sending)."""
    db = _open(cfg)
    for lead in sources.demo_leads():
        db.upsert_lead(lead)
    made, skipped = drafting.draft_all(db, cfg)
    out = cfg.path_for("output_dir")
    csv_path = reports.export_csv(db, out / "leads.csv")
    html_path = reports.export_preview_html(db, out / "outreach-preview.html", cfg["profile"])
    click.echo(f"Seeded 6 sample leads · {made} drafts · {skipped} skipped")
    click.echo(f"CSV: {csv_path}\nPreview: {html_path}")
    click.echo("This is demo data. Nothing was sent.")


@cli.command("find")
@click.option("--query", required=True, help="e.g. 'dentist' or 'web design agency'")
@click.option("--location", required=True, help="e.g. 'Indore, India'")
@click.option("--limit", default=20, show_default=True)
@click.pass_obj
def find(cfg: Config, query: str, location: str, limit: int) -> None:
    """Find local businesses through the official Google Places API."""
    try:
        leads = sources.find_maps(query, location, limit)
    except (RuntimeError, Exception) as exc:  # noqa: BLE001
        raise click.ClickException(str(exc)) from exc
    db = _open(cfg)
    created = 0
    for lead in leads:
        _, was_created = db.upsert_lead(lead)
        created += int(was_created)
    for lead in db.leads("source='maps'"):
        db.update_lead(lead["id"], score=enrich.score_lead(lead))
    click.echo(f"Found {len(leads)} places, {created} new. Use 'enrich' next.")


@cli.command("import")
@click.option("--file", "path", required=True, help="CSV exported from LinkedIn / Sales Navigator")
@click.pass_obj
def import_csv(cfg: Config, path: str) -> None:
    """Import a LinkedIn/Sales Navigator CSV export (no scraping)."""
    try:
        leads = sources.import_linkedin_csv(path)
    except (FileNotFoundError, Exception) as exc:  # noqa: BLE001
        raise click.ClickException(str(exc)) from exc
    db = _open(cfg)
    created = sum(int(db.upsert_lead(lead)[1]) for lead in leads)
    for lead in db.leads("source='linkedin'"):
        db.update_lead(lead["id"], score=enrich.score_lead(lead))
    click.echo(f"Imported {len(leads)} rows, {created} new.")


@cli.command()
@click.option("--offline", is_flag=True, help="Skip website requests (use cached/instant scoring)")
@click.pass_obj
def enrich_cmd(cfg: Config, offline: bool) -> None:
    """Discover contact emails on prospect websites and score leads."""
    db = _open(cfg)
    checked, found = enrich.enrich_all(db, cfg, fetch=not offline)
    click.echo(f"Checked {checked} leads · email found for {found}.")


@cli.command()
@click.pass_obj
def draft(cfg: Config) -> None:
    """Write personalised emails for leads with a sendable email."""
    db = _open(cfg)
    made, skipped = drafting.draft_all(db, cfg)
    click.echo(f"Created {made} drafts · skipped {skipped} (no sendable email / already drafted).")
    click.echo("Review with 'review'; nothing is sent automatically.")


@cli.command()
@click.pass_obj
def review(cfg: Config) -> None:
    """Print every draft for review."""
    db = _open(cfg)
    rows = db.emails(with_lead=True)
    if not rows:
        click.echo("No drafts yet.")
        return
    for row in rows:
        click.echo("-" * 70)
        click.echo(f"[{row['id']}] {row['company']} <{row['email']}> "
                   f"({row['email_confidence']}) — {row['status']}")
        click.echo(f"Subject: {row['subject']}")
        click.echo(row["body"])


@cli.command()
@click.option("--id", "email_id", type=int, help="Email ID from 'review'")
@click.option("--email", "address", help="Prospect email address")
@click.option("--all", "approve_all", is_flag=True, help="Approve all drafts (use with care)")
@click.option("--high-confidence", is_flag=True, help="Approve only website-verified emails")
@click.pass_obj
def approve(cfg: Config, email_id: int | None, address: str | None,
            approve_all: bool, high_confidence: bool) -> None:
    """Approve drafts for sending."""
    db = _open(cfg)
    if high_confidence:
        n = db.approve_all_high_confidence()
    elif email_id:
        db.approve_email(email_id)
        n = 1
    elif address:
        lead = db.lead_by_email(address)
        if not lead:
            raise click.ClickException(f"No lead with email {address}")
        match = next((e for e in db.emails("draft") if e["lead_id"] == lead["id"]), None)
        if not match:
            raise click.ClickException("No draft for that lead")
        db.approve_email(match["id"])
        n = 1
    elif approve_all:
        n = 0
        for row in db.emails("draft"):
            db.approve_email(row["id"])
            n += 1
    else:
        raise click.ClickException("Pass --id, --email, --all or --high-confidence")
    click.echo(f"Approved {n} draft(s). Send with: send --live")


@cli.command()
@click.option("--email", required=True)
@click.option("--reason", default="manual opt-out")
@click.pass_obj
def suppress(cfg: Config, email: str, reason: str) -> None:
    """Add an address to the permanent do-not-contact list."""
    db = _open(cfg)
    db.suppress(email, reason)
    click.echo(f"Suppressed {email.lower()}")


@cli.command("check-replies")
@click.option("--days", default=14, show_default=True)
@click.pass_obj
def check_replies(cfg: Config, days: int) -> None:
    """Scan inbox replies for opt-outs and add them to the suppression list."""
    from .google_client import build_services, find_opt_outs

    db = _open(cfg)
    gmail, _ = build_services(cfg)
    sent = [r["email"] for r in db.emails("sent", with_lead=True) if r.get("email")]
    flagged = find_opt_outs(gmail, sent, days)
    for email in flagged:
        db.suppress(email, "reply opt-out")
    click.echo(f"Checked {len(sent)} sent contacts · {len(flagged)} opt-outs suppressed.")


@cli.command()
@click.option("--live", is_flag=True, help="Actually send. Without this, it's a dry run.")
@click.option("--limit", default=None, type=int, help="Max sends this run")
@click.option("--auto-approve", is_flag=True, help="Approve verified drafts first (only if enabled in config)")
@click.option("--ignore-window", is_flag=True, help="Send outside configured business hours")
@click.pass_obj
def send(cfg: Config, live: bool, limit: int | None, auto_approve: bool, ignore_window: bool) -> None:
    """Send approved drafts through Gmail with a hard daily cap."""
    from .google_client import build_services, in_send_window, respect_delay, send_one

    db = _open(cfg)
    if auto_approve:
        if not cfg["limits"].get("auto_approve_high_confidence"):
            raise click.ClickException("Set limits.auto_approve_high_confidence: true in config.yaml first")
        click.echo(f"Auto-approved {db.approve_all_high_confidence()} verified draft(s).")

    approved = [e for e in db.emails("approved", with_lead=True) if e.get("email")]
    remaining = max(0, int(cfg["limits"]["daily_send_cap"]) - db.sent_in_last_hours(24))
    queue = [e for e in approved if not db.is_suppressed(e["email"])][: remaining if limit is None else min(limit, remaining)]
    if not live:
        click.echo(f"DRY RUN — {len(queue)} email(s) ready, cap remaining today: {remaining}. Nothing sent.")
        for item in queue[:5]:
            click.echo(f"  → {item['email']} | {item['subject']}")
        click.echo("Use 'send --live' to actually send.")
        return
    if not in_send_window(cfg) and not ignore_window:
        raise click.ClickException("Outside your configured send window. Use --ignore-window to override.")
    if not queue:
        click.echo("Nothing to send (approve drafts first, or daily cap reached).")
        return

    gmail, _ = build_services(cfg)
    click.echo(f"Sending {len(queue)} email(s) through Gmail...")
    for index, item in enumerate(queue, 1):
        try:
            message_id = send_one(gmail, cfg, item["email"], item["subject"], item["body"])
            db.mark_sent(item["id"], message_id)
            click.echo(f"  [{index}/{len(queue)}] sent → {item['email']}")
        except Exception as exc:  # noqa: BLE001
            db.mark_failed(item["id"], str(exc))
            click.echo(f"  [{index}/{len(queue)}] FAILED → {item['email']}: {exc}")
            break
        if index < len(queue):
            respect_delay(int(cfg["limits"]["min_delay_seconds"]))


@cli.command()
@click.pass_obj
def queue(cfg: Config) -> None:
    """Export approved drafts to output/send-queue.csv for sending via the connected Gmail app."""
    import csv

    db = _open(cfg)
    rows = [e for e in db.emails("approved", with_lead=True) if e.get("email") and not db.is_suppressed(e["email"])]
    out = cfg.path_for("output_dir") / "send-queue.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["email_id", "to", "subject", "body", "company"])
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "email_id": row["id"],
                "to": row["email"],
                "subject": row["subject"],
                "body": row["body"],
                "company": row["company"],
            })
    click.echo(f"Wrote {len(rows)} approved email(s) to {out}")
    click.echo("You can ask the agent in chat to send these via the connected Gmail account.")


@cli.command("mark-sent")
@click.option("--email", required=True, help="Prospect email address")
@click.option("--message-id", default="connector", help="Gmail message ID for the audit trail")
@click.pass_obj
def mark_sent(cfg: Config, email: str, message_id: str) -> None:
    """Record that an approved draft was sent through the connected Gmail app."""
    db = _open(cfg)
    lead = db.lead_by_email(email)
    if not lead:
        raise click.ClickException(f"No lead with email {email}")
    match = next((e for e in db.emails("approved") if e["lead_id"] == lead["id"]), None)
    if not match:
        raise click.ClickException("No approved draft for that lead")
    db.mark_sent(match["id"], message_id)
    click.echo(f"Marked {email} as sent.")


@cli.command()
@click.option("--drive", is_flag=True, help="Upload the CSV and preview to Google Drive")
@click.option("--sheet", is_flag=True, help="Convert the uploaded CSV into a Google Sheet")
@click.pass_obj
def report(cfg: Config, drive: bool, sheet: bool) -> None:
    """Export leads.csv and outreach-preview.html."""
    db = _open(cfg)
    out = cfg.path_for("output_dir")
    csv_path = reports.export_csv(db, out / "leads.csv")
    html_path = reports.export_preview_html(db, out / "outreach-preview.html", cfg["profile"])
    click.echo(f"Wrote {csv_path}\nWrote {html_path}")
    if drive:
        from .google_client import build_services, upload_to_drive

        _, service = build_services(cfg)
        folder = __import__("os").getenv("DRIVE_FOLDER_ID", "").strip() or None
        for path in (csv_path, html_path):
            result = upload_to_drive(service, path, folder_id=folder,
                                     to_sheet=sheet and path.suffix == ".csv")
            click.echo(f"Uploaded {result.get('name')}: {result.get('webViewLink')}")


@cli.command()
@click.pass_obj
def run(cfg: Config) -> None:
    """Full discovery pipeline: find/import → enrich → draft → report. Never sends."""
    db = _open(cfg)
    targets = cfg.get("targets", [])
    if not targets:
        click.echo("No targets in config.yaml. Add some, or run 'demo' to try it out.")
    for target in targets:
        source = target.get("source")
        try:
            if source == "maps":
                leads = sources.find_maps(target.get("query", ""), target.get("location", ""),
                                          int(target.get("limit", 20)))
            elif source in ("linkedin_csv", "linkedin"):
                leads = sources.import_linkedin_csv(target.get("path", "input/linkedin.csv"))
            else:
                click.echo(f"! Unknown source: {source}")
                continue
            created = sum(int(db.upsert_lead(lead)[1]) for lead in leads)
            click.echo(f"{source}: {len(leads)} found, {created} new")
        except Exception as exc:  # noqa: BLE001
            click.echo(f"! {source} failed: {exc}")
    for lead in db.leads():
        db.update_lead(lead["id"], score=enrich.score_lead(lead))
    checked, found = enrich.enrich_all(db, cfg)
    made, _ = drafting.draft_all(db, cfg)
    out = cfg.path_for("output_dir")
    reports.export_csv(db, out / "leads.csv")
    reports.export_preview_html(db, out / "outreach-preview.html", cfg["profile"])
    click.echo(f"Done · {checked} checked · {found} emails found · {made} drafts · report in {out}")
    click.echo("Review the drafts, then: approve --high-confidence → send --live")


@cli.command()
@click.pass_obj
def stats(cfg: Config) -> None:
    """Show pipeline counters."""
    for key, value in _open(cfg).stats().items():
        click.echo(f"{key:>12}: {value}")


def main() -> None:
    cli()
