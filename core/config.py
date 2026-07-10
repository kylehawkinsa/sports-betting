"""Load config.yaml and .env. API keys live only in environment variables
(.env is git-ignored; .env.example documents the names)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader — KEY=VALUE lines, no dependency."""
    p = path or ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def load_config(path: Path | None = None) -> dict:
    load_dotenv()
    p = path or ROOT / "config.yaml"
    with open(p) as f:
        cfg = yaml.safe_load(f)
    return cfg


def get_api_key(env_name: str) -> str | None:
    val = os.environ.get(env_name, "").strip()
    return val or None
