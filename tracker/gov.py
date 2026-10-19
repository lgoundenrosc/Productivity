"""Structured government feeds: Congress.gov hearings and SAM.gov notices."""
import os
from datetime import date, datetime, timedelta, timezone

import requests

CONGRESS_API = "https://api.congress.gov/v3"
SAM_API = "https://api.sam.gov/opportunities/v2/search"


def _congress_number(d):
    return (d.year - 1789) // 2 + 1


def hearings(today, until, committee_terms):
    """Committee meetings scheduled between today and until whose committee
    names match committee_terms. The list endpoint filters on update time,
    so we pull everything updated in the last 45 days and filter by date."""
    key = os.environ["CONGRESS_API_KEY"]
    congress = _congress_number(today)
    since = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for chamber in ("house", "senate"):
        url = f"{CONGRESS_API}/committee-meeting/{congress}/{chamber}"
        params = {"format": "json", "limit": 250, "fromDateTime": since, "api_key": key}
        while url:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            for ref in data.get("committeeMeetings", []):
                m = _meeting(ref["url"], key)
                if m is None:
                    continue
                when = datetime.fromisoformat(m["date"].replace("Z", "+00:00"))
                if not today <= when.date() <= until:
                    continue
                names = [c.get("name", "") for c in m.get("committees", [])]
                if not any(t.lower() in n.lower() for n in names for t in committee_terms):
                    continue
                loc = m.get("location") or {}
                out.append({
                    "kind": "hearing",
                    "source": "; ".join(names),
                    "title": m.get("title", "").strip(),
                    "date": when.date().isoformat(),
                    "start_time": _et_time(when),
                    "location": " ".join(filter(None, [loc.get("building"), loc.get("room")])),
                    "format": "in-person",
                    "speakers": [w.get("name", "") for w in m.get("witnesses", [])],
                    "summary": f"{m.get('type', 'Meeting')}, {m.get('meetingStatus', '')}".strip(", "),
                    "url": f"https://www.congress.gov/event/{congress}th-Congress/{chamber}-event/{m['eventId']}",
                })
            url = data.get("pagination", {}).get("next")
            params = {"api_key": key}  # `next` already carries the other params
    return out


def _meeting(url, key):
    r = requests.get(url, params={"api_key": key}, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    m = r.json().get("committeeMeeting")
    if not m or not m.get("date") or m.get("meetingStatus") in ("Canceled", "Cancelled", "Postponed"):
        return None
    return m


def _et_time(dt_utc):
    try:
        from zoneinfo import ZoneInfo
        return dt_utc.astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p ET")
    except Exception:
        return ""


def industry_days(today, phrases, days_back=14):
    """Special notices posted in the last `days_back` days with an
    industry-day style title, across all federal agencies."""
    key = os.environ["SAM_API_KEY"]
    fmt = "%m/%d/%Y"
    seen, out = set(), []
    for phrase in phrases:
        r = requests.get(SAM_API, timeout=60, params={
            "api_key": key, "ptype": "s", "title": phrase, "limit": 100,
            "postedFrom": (today - timedelta(days=days_back)).strftime(fmt),
            "postedTo": today.strftime(fmt),
        })
        r.raise_for_status()
        for o in r.json().get("opportunitiesData", []):
            if o.get("noticeId") in seen:
                continue
            seen.add(o.get("noticeId"))
            out.append({
                "kind": "industry_day",
                "source": o.get("fullParentPathName", "").replace(".", " / "),
                "title": o.get("title", "").strip(),
                "date": (o.get("postedDate") or today.isoformat())[:10],
                "start_time": "",
                "location": "",
                "format": "unknown",
                "speakers": [],
                "summary": "Posted on SAM.gov" + (
                    f"; responses due {o['responseDeadLine'][:10]}" if o.get("responseDeadLine") else ""),
                "url": o.get("uiLink", ""),
            })
    return out
