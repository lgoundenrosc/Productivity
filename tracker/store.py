"""Remembers which events earlier digests already showed."""
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "seen.json"


def event_id(e):
    title = re.sub(r"\W+", " ", e["title"].lower()).strip()
    return hashlib.sha1(f"{e['date']}|{title}".encode()).hexdigest()[:16]


def load():
    try:
        return json.loads(PATH.read_text())
    except FileNotFoundError:
        return {}


def save(seen, today):
    cutoff = (today - timedelta(days=180)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(seen, indent=0, sort_keys=True) + "\n")
