"""Remembers which events earlier digests already showed."""
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def event_id(e):
    title = re.sub(r"\W+", " ", e["title"].lower()).strip()
    return hashlib.sha1(f"{e['date']}|{title}".encode()).hexdigest()[:16]


def load(seen_file):
    try:
        return json.loads((ROOT / seen_file).read_text())
    except FileNotFoundError:
        return {}


def save(seen, today, seen_file):
    cutoff = (today - timedelta(days=180)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    path = ROOT / seen_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, indent=0, sort_keys=True) + "\n")
