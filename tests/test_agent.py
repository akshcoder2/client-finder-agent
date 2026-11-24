from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from cfagent import drafting, enrich, reports, sources
from cfagent.cli import cli
from cfagent.config import Config
from cfagent.db import DB


def make_config(tmp_path: Path, **overrides) -> Config:
    data = {
        "profile": {"name": "Test", "company": "Test Co", "offer": "we build websites",
                    "signature": "Best,\nTest", "physical_address": "Indore, India"},
        "limits": {"daily_send_cap": 2, "min_delay_seconds": 0, "send_window": "any"},
        "storage": {"db": "data/leads.db", "output_dir": "output", "input_dir": "input"},
    }
    data.update(overrides)
    path = tmp_path / "config.yaml"
    import yaml
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    cfg = Config.load(path)
    cfg.ensure_dirs()
    return cfg


def demo_lead(email="hello@acme.in", **kw):
    lead = {
        "source": "maps", "external_id": "p1", "company": "Acme Clinic",
        "contact_name": "Dr. Neha Sharma", "email": email,
        "email_confidence": "high", "website": "https://acme.in",
        "headline": "dentist · Indore", "rating": 4.6,
    }
    lead.update(kw)
    return lead


def test_upsert_dedupe_defaults_and_stats(tmp_path):
    db = DB(tmp_path / "leads.db")
    id1, created1 = db.upsert_lead(demo_lead())
    id2, created2 = db.upsert_lead(demo_lead(rating=4.9))
    assert (created1, created2) == (True, False)
    assert id1 == id2
    row = db.get_lead(id1)
    assert row["status"] == "new"
    assert row["rating"] == 4.9
    assert db.stats()["leads"] == 1


def test_linkedin_csv_import_aliases(tmp_path):
    p = tmp_path / "linkedin.csv"
    with p.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["First Name", "Last Name", "Company Name",
                                           "Email Address", "Profile URL", "Title"])
        w.writeheader()
        w.writerow({"First Name": "Riya", "Last Name": "Verma", "Company Name": "Bright Co",
                    "Email Address": "Riya@Bright.co", "Profile URL": "https://linkedin.com/in/riya",
                    "Title": "Founder"})
    leads = sources.import_linkedin_csv(p)
    assert len(leads) == 1
    assert leads[0]["contact_name"] == "Riya Verma"
    assert leads[0]["email"] == "riya@bright.co"
    assert leads[0]["source"] == "linkedin"


def test_template_draft_is_personal_and_has_optout(tmp_path):
    cfg = make_config(tmp_path)
    db = DB(cfg.path_for("db"))
    lid, _ = db.upsert_lead(demo_lead())
    made, skipped = drafting.draft_all(db, cfg)
    assert (made, skipped) == (1, 0)
    email = db.emails()[0]
    assert "Hi Dr. Sharma" in email["body"]
    assert "Acme Clinic" in email["subject"]
    assert "no thanks" in email["body"]
    assert "Indore, India" in email["body"]
    # A second run must not duplicate the draft.
    assert drafting.draft_all(db, cfg) == (0, 0)


def test_no_draft_without_sendable_email(tmp_path):
    cfg = make_config(tmp_path)
    db = DB(cfg.path_for("db"))
    db.upsert_lead(demo_lead(email="info@acme.in", email_confidence="found_not_sendable"))
    assert drafting.draft_all(db, cfg) == (0, 1)


def test_suppression_blocks_approval_and_sending(tmp_path):
    cfg = make_config(tmp_path)
    db = DB(cfg.path_for("db"))
    lid, _ = db.upsert_lead(demo_lead())
    drafting.draft_all(db, cfg)
    db.suppress("hello@acme.in", "test opt-out")
    assert db.is_suppressed("HELLO@ACME.IN")
    assert db.get_lead(lid)["status"] == "opted_out"
    assert db.approve_all_high_confidence() == 0


def test_daily_cap_and_send_flow(tmp_path, monkeypatch):
    import cfagent.google_client as google

    cfg = make_config(tmp_path)
    db = DB(cfg.path_for("db"))
    for i in range(3):
        db.upsert_lead(demo_lead(email=f"p{i}@acme.in", external_id=f"p{i}"))
    drafting.draft_all(db, cfg)
    assert db.approve_all_high_confidence() == 3

    sent = []
    monkeypatch.setattr(google, "build_services", lambda cfg: (object(), object()))
    monkeypatch.setattr(google, "in_send_window", lambda cfg: True)
    monkeypatch.setattr(google, "respect_delay", lambda *a, **k: None)
    monkeypatch.setattr(google, "send_one", lambda gmail, cfg, to, subject, body: sent.append(to) or "mid-1")

    runner = CliRunner()
    cfg_path = str(tmp_path / "config.yaml")
    assert "DRY RUN" in runner.invoke(cli, ["--config", cfg_path, "send"]).output
    assert sent == []

    result = runner.invoke(cli, ["--config", cfg_path, "send", "--live"])
    assert result.exit_code == 0, result.output
    assert len(sent) == 2  # hard daily cap = 2
    assert db.stats()["sent_24h"] == 2
    assert db.stats()["approved"] == 1


def test_queue_and_mark_sent_via_connector(tmp_path):
    cfg_path = str(tmp_path / "config.yaml")
    cfg = make_config(tmp_path)
    db = DB(cfg.path_for("db"))
    db.upsert_lead(demo_lead())
    drafting.draft_all(db, cfg)
    runner = CliRunner()
    runner.invoke(cli, ["--config", cfg_path, "approve", "--high-confidence"])
    result = runner.invoke(cli, ["--config", cfg_path, "queue"])
    assert result.exit_code == 0, result.output
    queue_file = tmp_path / "output" / "send-queue.csv"
    assert "hello@acme.in" in queue_file.read_text(encoding="utf-8")
    result = runner.invoke(cli, ["--config", cfg_path, "mark-sent", "--email", "hello@acme.in"])
    assert result.exit_code == 0, result.output
    assert db.stats()["sent_total"] == 1


def test_reports_and_scoring(tmp_path):
    cfg = make_config(tmp_path)
    db = DB(cfg.path_for("db"))
    lead = demo_lead()
    db.upsert_lead(lead)
    assert enrich.score_lead(lead) >= 75
    drafting.draft_all(db, cfg)
    csv_path = reports.export_csv(db, tmp_path / "out" / "leads.csv")
    html_path = reports.export_preview_html(db, tmp_path / "out" / "preview.html", cfg["profile"])
    assert "Acme Clinic" in csv_path.read_text(encoding="utf-8")
    assert "Acme Clinic" in html_path.read_text(encoding="utf-8")
    assert "no thanks" in html_path.read_text(encoding="utf-8")


def test_demo_cli_never_sends(tmp_path):
    cfg_path = str(tmp_path / "config.yaml")
    make_config(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["--config", cfg_path, "demo"])
    assert result.exit_code == 0, result.output
    assert "Nothing was sent" in result.output
    assert runner.invoke(cli, ["--config", cfg_path, "stats"]).output.count("leads:") >= 1
