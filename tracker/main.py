"""Weekly events digest for one city (config/<city>/).

    python -m tracker.main --dry-run               # build out/digest.html, send nothing
    python -m tracker.main --fetch-only            # check every source loads, no Claude calls
    python -m tracker.main                         # full run: email the DC digest, update seen events
    python -m tracker.main --city boston --test    # email a test Boston digest, record nothing
"""
import argparse
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import digest, fetch, gov, llm, store

ROOT = Path(__file__).resolve().parent.parent
ET = ZoneInfo("America/New_York")
GOV_WORKERS = ("hill", "industry")
# Event types kept up to travel_lookahead_days out instead of lookahead_days.
LONG_LEAD_TYPES = ("conference", "industry_day", "speaking_call")


def scrape_group(sources, profile, today, until, fetch_only, networking=False):
    """One worker: each page gets its own extraction call."""
    events, failures = [], []
    for src in sources:
        try:
            if fetch_only and src.get("fetch") == "search":
                print(f"  {src['name']}: search agent (needs ANTHROPIC_API_KEY; skipped)")
                continue
            text = fetch.source_text(src, today, until, profile["city"]["area"])
            if fetch_only:
                print(f"  {src['name']}: {len(text):,} chars of text")
                continue
            found = llm.extract_events(src["name"], text, today, until, profile,
                                       src.get("local_only", False), networking)
            if not found:
                failures.append((src["name"], "page loaded but no upcoming events were found"))
            for e in found:
                if e.get("date") and today.isoformat() <= e["date"] <= until.isoformat():
                    events.append({**e, "kind": "event", "source": src["name"]})
        except Exception as exc:
            failures.append((src["name"], f"{type(exc).__name__}: {exc}"[:200]))
    return events, failures


def gov_worker(kind, cfg, today, until, fetch_only):
    try:
        if kind == "hill":
            if not os.environ.get("CONGRESS_API_KEY"):
                return [], [("Congress.gov", "CONGRESS_API_KEY not set")]
            evs = gov.hearings(today, today + timedelta(days=21), cfg["hill_committees"])
        else:
            if not os.environ.get("SAM_API_KEY"):
                return [], [("SAM.gov", "SAM_API_KEY not set")]
            evs = gov.industry_days(today, cfg["sam_phrases"])
        if fetch_only:
            print(f"  {kind}: {len(evs)} items")
            return [], []
        return evs, []
    except Exception as exc:
        name = "Congress.gov" if kind == "hill" else "SAM.gov"
        return [], [(name, f"{type(exc).__name__}: {exc}"[:200])]


def run_worker(name, cfg, profile, today, until, fetch_only):
    if name in GOV_WORKERS:
        events, failures = gov_worker(name, cfg, today, until, fetch_only)
    else:
        events, failures = scrape_group(cfg[name], profile, today, until, fetch_only,
                                        networking=name in cfg.get("networking_workers", []))
    if events and not fetch_only:
        try:
            llm.score_events(events, profile)
        except Exception as exc:
            failures.append((f"Scoring ({name})", f"{type(exc).__name__}: {exc}"[:200]))
    return events, failures


def place(e, today, local_until, bonus):
    """Applies the local bonus and decides whether an event stays in the digest.
    Local events are kept for three weeks; conferences, industry days and calls
    for speakers, and anything out of town, only if they are worth planning or
    traveling for."""
    if e["kind"] != "event":
        return True
    fmt, local = e.get("format", "unknown"), e.get("local", True)
    if e.get("networking_source") or e.get("event_type") == "networking":
        if not local and fmt != "virtual":
            return False  # an out-of-town happy hour; online ones stay, ranked lower
    long_lead = e.get("event_type") in LONG_LEAD_TYPES
    if not local and fmt != "virtual" and not long_lead:
        return False  # an out-of-town talk or happy hour
    if date.fromisoformat(e["date"]) > local_until and not long_lead:
        return False
    if fmt == "virtual":
        delta = bonus.get("online_only", 0)
    elif local and fmt == "in-person":
        delta = bonus.get("local_in_person", 0)
    elif local and fmt == "hybrid":
        delta = bonus.get("local_hybrid", 0)
    else:
        delta = 0
    if "score" in e:
        e["score"] = max(1, min(10, e["score"] + delta))
    return True


def intended_slot_ok():
    """The workflow fires at 10:50 and 11:50 UTC on Mondays. Only the run
    scheduled for 6:50 ET goes ahead, so the email lands near 7:00 in both
    EDT and EST, even when GitHub starts the job late."""
    cron = os.environ.get("GITHUB_EVENT_SCHEDULE")
    if not cron:
        return True
    minute, hour = (int(x) for x in cron.split()[:2])
    now = datetime.now(timezone.utc)
    slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if slot > now:
        slot -= timedelta(days=1)
    return slot.astimezone(ET).hour == 6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="write out/digest.html instead of emailing")
    ap.add_argument("--fetch-only", action="store_true", help="load sources without calling Claude")
    ap.add_argument("--only", help="comma-separated worker names, e.g. hill,other_orgs")
    ap.add_argument("--city", default="dc", help="config folder under config/, e.g. dc or boston")
    ap.add_argument("--test", action="store_true",
                    help="email the digest marked as a test and leave the seen-events record alone")
    args = ap.parse_args()

    if not intended_slot_ok():
        print("Not the 7am ET slot this week (daylight saving offset); exiting.")
        return 0

    needed = [] if args.fetch_only else ["ANTHROPIC_API_KEY"]
    if not (args.fetch_only or args.dry_run):
        needed += ["GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"]
    missing = [k for k in needed if not os.environ.get(k)]
    if missing:
        print(f"Missing {', '.join(missing)}. Add them as repository secrets "
              "(Settings > Secrets and variables > Actions); see the README.")
        return 1

    cfg = yaml.safe_load((ROOT / "config" / args.city / "sources.yaml").read_text())
    profile = yaml.safe_load((ROOT / "config" / args.city / "profile.yaml").read_text())
    city = profile["city"]
    today = datetime.now(ET).date()
    local_until = today + timedelta(days=profile["lookahead_days"])
    until = today + timedelta(days=profile["travel_lookahead_days"])

    workers = cfg["workers"]
    covered = sorted({src["name"] for g in workers if g not in GOV_WORKERS
                      for src in cfg.get(g, []) if src.get("fetch") != "search"})
    for src in cfg.get("general_search", []):
        src["focus"] = src["focus"].replace("{covered}", ", ".join(covered))

    if args.only:
        workers = [w for w in workers if w in args.only.split(",")]
    with ThreadPoolExecutor(len(workers)) as pool:
        results = list(pool.map(
            lambda w: run_worker(w, cfg, profile, today, until, args.fetch_only), workers))
    if args.fetch_only:
        for _, fails in results:
            for name, msg in fails:
                print(f"  FAILED {name}: {msg}")
        return 0

    seen = store.load(city["seen_file"])
    events, failures, ids = [], [], set()
    for (evs, fails), worker in zip(results, workers):
        failures += fails
        for e in evs:
            e["worker"] = worker
            e["networking_source"] = worker in cfg.get("networking_workers", [])
            eid = store.event_id(e)
            if eid in ids:
                continue  # co-hosted event listed by two sources
            ids.add(eid)
            e["is_new"] = eid not in seen
            events.append(e)

    bonus = profile.get("location_bonus", {})
    events = [e for e in events if place(e, today, local_until, bonus)]

    body = digest.build(events, profile, today, failures)
    if args.dry_run:
        out = ROOT / "out" / "digest.html"
        out.parent.mkdir(exist_ok=True)
        out.write_text(body)
        print(f"Wrote {out} ({len(events)} events, {len(failures)} failures)")
        return 0

    from . import mailer
    subject = f"{city['name']} events: week of {today:%b} {today.day}"
    mailer.send(f"Test: {subject}" if args.test else subject, body)
    if args.test:
        print(f"Sent test digest with {len(events)} events; {len(failures)} failures")
        return 0
    for e in events:
        seen.setdefault(store.event_id(e), today.isoformat())
    store.save(seen, today, city["seen_file"])
    print(f"Sent digest with {len(events)} events; {len(failures)} failures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
