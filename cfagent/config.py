from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)

DEFAULTS: dict[str, Any] = {
    "profile": {
        "name": "Your Name",
        "company": "Your Company",
        "offer": "we help businesses grow",
        "website": "https://example.com",
        "location": "Indore, India",
        "signature": "Best,\nYour Name",
        "physical_address": "Indore, Madhya Pradesh, India",
    },
    "targets": [],
    "limits": {
        "daily_send_cap": 25,
        "min_delay_seconds": 120,
        "send_window": "09:00-18:00",
        "timezone": "Asia/Kolkata",
        "auto_approve_high_confidence": False,
    },
    "sourcing": {
        "allow_generic_email": False,
        "allow_guessed_email": False,
    },
    "llm": {
        "enabled": False,
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key_env": "LLM_API_KEY",
        "max_tokens": 350,
    },
    "storage": {
        "db": "data/leads.db",
        "output_dir": "output",
        "input_dir": "input",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


class Config:
    """Config object with dict-style and attribute-style access."""

    def __init__(self, data: dict, path: Path | None = None):
        self.data = _deep_merge(DEFAULTS, data or {})
        self.path = path

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        path = Path(path) if path else ROOT / "config.yaml"
        data: dict = {}
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        return cls(data, path)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def root(self) -> Path:
        return self.path.parent if self.path else ROOT

    def path_for(self, key: str) -> Path:
        raw = str(self["storage"][key])
        p = Path(os.path.expandvars(raw))
        return p if p.is_absolute() else self.root / p

    def ensure_dirs(self) -> None:
        for key in ("db", "output_dir", "input_dir"):
            p = self.path_for(key)
            target = p if key != "db" else p.parent
            target.mkdir(parents=True, exist_ok=True)
