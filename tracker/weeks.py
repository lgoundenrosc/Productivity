"""City-wide event weeks: Boston Built Week, Tough Tech Week, London Tech Week
and the like. Each runs a calendar of dozens of partner events that no single
host's events page lists.

A `fetch: weeks` source does three things on each run:
  1. a search agent looks for event weeks overlapping the digest window and
     finds each one's calendar page;
  2. new weeks are added to a JSON file next to seen.json, so a week found
     once is read on every later run until it ends, even if a later search
     misses it;
  3. every live week, plus the `known` weeks listed in sources.yaml, becomes
     an ordinary page source, so its calendar goes through the same
     extraction and scoring as any other events page.
"""
import json
import re
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FOCUS = """Look for city-wide event weeks and festivals in {area}: weeks such as
Boston Built Week, Tough Tech Week, Boston Tech Week, Boston AI Week, Startup
Boston Week, Boston Fintech Week, Climate Week, Founders Week, Demo Week or
London Tech Week, where one organizer runs a calendar of partner events hosted
across the city by many companies, funds and universities. Include weeks run
by industry groups (construction, robotics, climate, life sciences, defense,
fintech, AI) as well as general startup weeks. For each week give its name,
organizer, first and last day, and the URL of the page that lists its full
calendar of partner events (a schedule page or Luma calendar, not just a
homepage, when one exists). Only list weeks whose dates you confirmed on a
real page."""

WEEK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["weeks"],
    "properties": {"weeks": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "organizer", "start", "end", "url"],
        "properties": {
            "name": {"type": "string"},
            "organizer": {"type": "string"},
            "start": {"type": "string", "description": "YYYY-MM-DD"},
            "end": {"type": "string", "description": "YYYY-MM-DD, the last day"},
            "url": {"type": "string", "description": "the page listing the week's events"},
        },
    }}},
}


def norm_url(url):
    """Compares URLs without scheme, www or trailing slash."""
    return re.sub(r"^https?://(www\.)?", "", url.strip()).rstrip("/").lower()


def load(path):
    try:
        return json.loads((ROOT / path).read_text())
    except FileNotFoundError:
        return []


def save(weeks, path):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(weeks, indent=1, sort_keys=True) + "\n")


def _valid(w):
    try:
        start, end = date.fromisoformat(w["start"]), date.fromisoformat(w["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return start <= end <= start + timedelta(days=31) and w.get("url", "").startswith("http")


def merge(stored, found, today):
    """Adds newly found weeks, refreshes dates for ones already known, and
    drops weeks that ended more than a week ago."""
    by_url = {norm_url(w["url"]): w for w in stored}
    for w in found:
        if _valid(w):
            by_url[norm_url(w["url"])] = {**by_url.get(norm_url(w["url"]), {}), **w}
    cutoff = (today - timedelta(days=7)).isoformat()
    return sorted((w for w in by_url.values() if w["end"] >= cutoff),
                  key=lambda w: (w["start"], w["name"]))


def discover(area, today, until, extra_focus=""):
    from . import llm
    focus = FOCUS.format(area=area) + ("\n" + extra_focus.strip() if extra_focus else "")
    text = llm.search_text(focus, today, until, area)
    prompt = f"""Below is a research note about event weeks in {area}, written on {today}.
List each event week it confirms that overlaps {today} to {until}. Use the
calendar or schedule page as `url`. Skip anything without confirmed dates.

<note>
{text}
</note>"""
    return llm._json_call(prompt, WEEK_SCHEMA)["weeks"]


def page_source(w, prefix="wk"):
    url = w["url"]
    return {
        "id": f"{prefix}_{re.sub(r'[^a-z0-9]+', '_', norm_url(url))[:40]}",
        "name": w["name"],
        "url": url,
        "fetch": w.get("fetch") or ("luma" if "luma.com/" in url or "lu.ma/" in url else "auto"),
    }


def sources(src, area, today, until, search=True, failures=None):
    """Page sources for every event week worth reading this run."""
    path = src["store"]
    stored = load(path)
    if search:
        try:
            stored = merge(stored, discover(area, today, until, src.get("focus", "")), today)
        except Exception as exc:
            if failures is not None:
                failures.append((src["name"], f"{type(exc).__name__}: {exc}"[:200]))
        save(stored, path)
    out, seen = [], set()
    for w in src.get("known", []):
        out.append(page_source(w))
        seen.add(norm_url(w["url"]))
    for w in stored:
        live = w["start"] <= until.isoformat() and w["end"] >= today.isoformat()
        if live and norm_url(w["url"]) not in seen:
            out.append(page_source(w))
            seen.add(norm_url(w["url"]))
    return out
