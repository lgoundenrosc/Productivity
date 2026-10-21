"""Builds the Monday email."""
import html
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

e_ = html.escape


def calendar_link(ev):
    """Google Calendar 'add event' link. Opening it shows the event prefilled,
    and clicking Save is the approval."""
    d = date.fromisoformat(ev["date"])
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m", ev.get("start_time", ""), re.I)
    if m:
        h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
        start = datetime(d.year, d.month, d.day, h, int(m.group(2) or 0))
        end = start + timedelta(minutes=90)
        dates = f"{start:%Y%m%dT%H%M%S}/{end:%Y%m%dT%H%M%S}"
    else:
        dates = f"{d:%Y%m%d}/{d + timedelta(days=1):%Y%m%d}"
    details = "\n".join(filter(None, [ev.get("url", ""), f"Via {ev['source']}"]))
    return "https://calendar.google.com/calendar/render?" + urlencode({
        "action": "TEMPLATE", "text": ev["title"], "dates": dates,
        "ctz": "America/New_York", "details": details,
        "location": ev.get("location", ""),
    })


def _minutes(ev):
    """Start time as minutes after midnight, so 8:30 AM sorts before 6:00 PM.
    Events with no listed time go first."""
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m", ev.get("start_time", ""), re.I)
    if not m:
        return -1
    return (int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)) * 60 + int(m.group(2) or 0)


def _when(ev):
    d = date.fromisoformat(ev["date"])
    return f"{d:%a %b} {d.day}" + (f", {ev['start_time']}" if ev.get("start_time") else "")


FORMAT_BADGES = {
    "in-person": ("IN PERSON", "#e8f0fe", "#1a3d6d"),
    "hybrid": ("HYBRID: IN PERSON OR ONLINE", "#fef7e0", "#7a4f01"),
    "virtual": ("ONLINE ONLY", "#f1f3f4", "#5f6368"),
    "unknown": ("FORMAT NOT LISTED", "#f1f3f4", "#5f6368"),
}
FORMAT_ORDER = {"in-person": 0, "hybrid": 1, "unknown": 2, "virtual": 3}


def _badge(fmt):
    label, bg, fg = FORMAT_BADGES.get(fmt, FORMAT_BADGES["unknown"])
    return (f'<span style="background:{bg};color:{fg};font-size:12px;font-weight:600;'
            f'padding:1px 6px;border-radius:8px;margin-right:6px">{label}</span>')


def _card(ev, local_label="", show_calendar=True):
    pill = '<span style="background:{};color:{};font-size:12px;font-weight:600;padding:1px 6px;border-radius:8px;margin-left:6px">{}</span>'
    new = "".join([
        pill.format("#fce8e6", "#a50e0e", "THIS WEEK") if ev.get("this_week") else "",
        pill.format("#fff4e5", "#7a4f01", "TOP PICK") if ev.get("top_pick") else "",
        pill.format("#e6f4ea", "#137333", "NEW") if ev.get("is_new") else "",
    ])
    title = f'<a href="{e_(ev["url"])}" style="color:#1a3d6d;text-decoration:none">{e_(ev["title"])}</a>' if ev.get("url") else e_(ev["title"])
    badge = _badge(ev.get("format") or "unknown") if ev["kind"] != "industry_day" else ""
    where = e_(ev.get("location", "")) or (e_(local_label) if ev.get("local") else "")
    if ev.get("local") is False and ev.get("format") != "virtual":
        where = f"<b>Travel:</b> {where}"
    meta = badge + " · ".join(filter(None, [_when(ev), e_(ev["source"]), where]))
    speakers = f'<div style="color:#555;font-size:15px">Speakers: {e_(", ".join(ev["speakers"][:6]))}</div>' if ev.get("speakers") else ""
    cal = f' &nbsp;<a href="{e_(calendar_link(ev))}" style="font-size:13px">Add to calendar</a>' if show_calendar else ""
    return f"""<div style="margin:0 0 14px 0">
<div style="font-weight:600">{title}{new}</div>
<div style="color:#444;font-size:15px">{meta}</div>{speakers}
<div style="font-size:15px"><b>{ev.get('score', '')}/10</b> {e_(ev.get('reason', ''))}{cal}</div>
</div>"""


def _section(name, cards):
    if not cards:
        return ""
    return f'<h2 style="font-size:19px;border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:28px">{e_(name)}</h2>' + "".join(cards)


def build(events, profile, today, failures):
    """Each event appears once, in the first section that claims it:
    this week, happy hours and networking (unless the profile turns that
    section off), a topic, or big events ahead."""
    city = profile["city"]
    card = lambda e, **kw: _card(e, city["local_label"], **kw)
    week_end = today + timedelta(days=6 - today.weekday())  # through Sunday; next week starts Monday
    local_until = today + timedelta(days=profile["lookahead_days"])
    top = profile["top_pick_score"]
    keep = [e for e in events if e.get("score", 0) >= profile["min_score"]]
    for e in keep:
        e["this_week"] = date.fromisoformat(e["date"]) <= week_end
        e["top_pick"] = e.get("score", 0) >= top

    by_date = lambda e: (e["date"], _minutes(e))
    in_person_first = lambda e: (FORMAT_ORDER.get(e.get("format"), 2), e["date"], _minutes(e))
    regular = [e for e in keep if e["kind"] == "event"]
    hearings = sorted((e for e in keep if e["kind"] == "hearing"), key=by_date)
    notices = sorted((e for e in keep if e["kind"] == "industry_day"), key=lambda e: -e["score"])

    def is_travel(e):
        return e.get("event_type") in ("conference", "industry_day") and (
            not e.get("local", True) or date.fromisoformat(e["date"]) > local_until)

    travel = sorted((e for e in regular if is_travel(e)), key=by_date)
    rest = [e for e in regular if not is_travel(e)]
    this_week = sorted((e for e in rest if e["this_week"]), key=by_date)
    rest = [e for e in rest if not e["this_week"]]
    networking = []
    if profile.get("networking_section", True):
        networking = sorted((e for e in rest if e.get("event_type") == "networking"
                             or e.get("networking_source")), key=by_date)
    rest = [e for e in rest if e not in networking]
    happy_hours = f"{len(networking)} happy hours and meetups, " if networking else ""

    parts = ['<div style="font-family:Georgia,serif;font-size:16px;max-width:680px;color:#111">',
             f'<h1 style="font-size:24px">{e_(city["name"])} events: week of {today:%B} {today.day}</h1>',
             f'<p style="color:#555;font-size:15px">{len(this_week)} event{"" if len(this_week) == 1 else "s"} this week, '
             f'{happy_hours}{len(rest)} more over the next three weeks '
             f'and {len(travel)} bigger events further out. {e_(city["name"])} events you can attend '
             'in person rank first. NEW marks events not in an earlier digest.</p>']
    parts.append(_section(f"This week ({today:%b} {today.day} to {week_end:%b} {week_end.day})",
                          [card(e) for e in this_week]))
    parts.append(_section("Happy hours, meetups and networking", [card(e) for e in networking]))
    for cat in profile["categories"]:
        evs = sorted((e for e in rest if e.get("category") == cat["id"]), key=in_person_first)
        parts.append(_section(cat["name"], [card(e) for e in evs]))
    parts.append(_section("Conferences and big events ahead (worth planning or traveling for)",
                          [card(e) for e in travel]))
    parts.append(_section("Congressional hearings", [card(e) for e in hearings]))
    parts.append(_section("Industry days and proposers days (SAM.gov, posted in the last two weeks)",
                          [card(e, show_calendar=False) for e in notices]))
    if failures:
        items = "".join(f"<li>{e_(name)}: {e_(msg)}</li>" for name, msg in failures)
        parts.append(f'<h2 style="font-size:17px;margin-top:28px;color:#a50e0e">Sources that failed this week</h2>'
                     f'<ul style="font-size:15px;color:#555">{items}</ul>')
    parts.append("</div>")
    return "".join(parts)
