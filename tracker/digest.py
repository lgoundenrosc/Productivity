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
    details = "\n".join(filter(None, [
        ev.get("summary", ""),
        "Speakers: " + ", ".join(ev["speakers"]) if ev.get("speakers") else "",
        ev.get("url", ""),
        f"Found by the DC events tracker ({ev['source']})",
    ]))
    return "https://calendar.google.com/calendar/render?" + urlencode({
        "action": "TEMPLATE", "text": ev["title"], "dates": dates,
        "ctz": "America/New_York", "details": details,
        "location": ev.get("location", ""),
    })


def _when(ev):
    d = date.fromisoformat(ev["date"])
    return f"{d:%a %b} {d.day}" + (f", {ev['start_time']}" if ev.get("start_time") else "")


def _card(ev, show_calendar=True):
    new = ' <span style="background:#e6f4ea;color:#137333;font-size:11px;padding:1px 6px;border-radius:8px">NEW</span>' if ev.get("is_new") else ""
    title = f'<a href="{e_(ev["url"])}" style="color:#1a3d6d;text-decoration:none">{e_(ev["title"])}</a>' if ev.get("url") else e_(ev["title"])
    meta = " · ".join(filter(None, [_when(ev), e_(ev["source"]), e_(ev.get("format", "")) if ev.get("format") not in ("", "unknown") else ""]))
    speakers = f'<div style="color:#555;font-size:13px">Speakers: {e_(", ".join(ev["speakers"][:6]))}</div>' if ev.get("speakers") else ""
    cal = f' &nbsp;<a href="{e_(calendar_link(ev))}" style="font-size:12px">Add to calendar</a>' if show_calendar else ""
    return f"""<div style="margin:0 0 14px 0">
<div style="font-weight:600">{title}{new}</div>
<div style="color:#444;font-size:13px">{meta}</div>{speakers}
<div style="font-size:13px"><b>{ev.get('score', '')}/10</b> {e_(ev.get('reason', ''))}{cal}</div>
</div>"""


def _section(name, cards):
    if not cards:
        return ""
    return f'<h2 style="font-size:17px;border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:28px">{e_(name)}</h2>' + "".join(cards)


def build(events, profile, today, failures):
    by_date = lambda e: (e["date"], e.get("start_time", ""))
    keep = [e for e in events if e.get("score", 0) >= profile["min_score"]]
    regular = [e for e in keep if e["kind"] == "event"]
    hearings = sorted((e for e in keep if e["kind"] == "hearing"), key=by_date)
    notices = sorted((e for e in keep if e["kind"] == "industry_day"), key=lambda e: -e["score"])

    parts = [f'<div style="font-family:Georgia,serif;max-width:680px;color:#111">',
             f'<h1 style="font-size:22px">DC events: week of {today:%B} {today.day}</h1>',
             f'<p style="color:#555;font-size:13px">{len(regular)} events, {len(hearings)} hearings and '
             f'{len(notices)} industry-day notices scored {profile["min_score"]}+ out of {len(events)} found. '
             'NEW marks events not in an earlier digest.</p>']
    top = sorted((e for e in regular if e["score"] >= profile["top_pick_score"]),
                 key=lambda e: (-e["score"], e["date"]))[:6]
    parts.append(_section("Top picks", [_card(e) for e in top]))
    for cat in profile["categories"]:
        evs = sorted((e for e in regular if e.get("category") == cat["id"]), key=by_date)
        parts.append(_section(cat["name"], [_card(e) for e in evs]))
    parts.append(_section("Congressional hearings", [_card(e) for e in hearings]))
    parts.append(_section("Industry days and proposers days (SAM.gov, posted in the last two weeks)",
                          [_card(e, show_calendar=False) for e in notices]))
    if failures:
        items = "".join(f"<li>{e_(name)}: {e_(msg)}</li>" for name, msg in failures)
        parts.append(f'<h2 style="font-size:15px;margin-top:28px;color:#a50e0e">Sources that failed this week</h2>'
                     f'<ul style="font-size:13px;color:#555">{items}</ul>')
    parts.append("</div>")
    return "".join(parts)
