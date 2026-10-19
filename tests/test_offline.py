"""Offline checks: no network, no Claude calls."""
from datetime import date
from unittest import mock
from urllib.parse import parse_qs, urlparse

import yaml

from tracker import digest, gov, main, store

PROFILE = yaml.safe_load(open("config/profile.yaml"))


def ev(**kw):
    base = dict(kind="event", source="CSIS", title="Drones and the industrial base",
                date="2026-10-22", start_time="2:00 PM ET", location="CSIS, 1616 Rhode Island Ave NW",
                format="in-person", speakers=["Jane Doe (DIU)"], summary="Panel.", url="https://csis.org/x",
                category="robotics", score=8, reason="DIU speaker.", is_new=True)
    base.update(kw)
    return base


def test_calendar_link_timed():
    q = parse_qs(urlparse(digest.calendar_link(ev())).query)
    assert q["dates"] == ["20261022T140000/20261022T153000"]
    assert q["ctz"] == ["America/New_York"]
    assert q["text"] == ["Drones and the industrial base"]


def test_calendar_link_all_day():
    q = parse_qs(urlparse(digest.calendar_link(ev(start_time=""))).query)
    assert q["dates"] == ["20261022/20261023"]


def test_digest_groups_and_filters():
    events = [ev(), ev(title="Low", score=3), ev(title="Bio", category="aibio", score=6),
              ev(kind="hearing", title="HASC posture hearing", category="defense", score=7),
              ev(kind="industry_day", title="Army Industry Day", category="defense", score=6)]
    html = digest.build(events, PROFILE, date(2026, 10, 19), [("SpaceNews", "HTTP 403")])
    assert "Top picks" in html and "AI x bio and WMD risk" in html
    assert "Congressional hearings" in html and "Army Industry Day" in html
    assert "Low" not in html and "SpaceNews" in html


def test_event_id_ignores_punctuation():
    assert store.event_id(ev(title="AI & Bio: Risks")) == store.event_id(ev(title="ai bio risks"))


def test_hearings_filter(monkeypatch):
    monkeypatch.setenv("CONGRESS_API_KEY", "x")
    listing = {"committeeMeetings": [{"url": "u1"}, {"url": "u2"}, {"url": "u3"}], "pagination": {}}
    meetings = {
        "u1": {"eventId": "1", "date": "2026-10-21T14:00:00Z", "title": "Posture of the Army",
               "type": "Hearing", "meetingStatus": "Scheduled",
               "committees": [{"name": "House Armed Services"}], "location": {"building": "Rayburn", "room": "2118"}},
        "u2": {"eventId": "2", "date": "2026-10-21T14:00:00Z", "title": "Farm bill",
               "committees": [{"name": "House Agriculture"}], "meetingStatus": "Scheduled"},
        "u3": {"eventId": "3", "date": "2025-01-01T14:00:00Z", "title": "Old",
               "committees": [{"name": "Senate Armed Services"}], "meetingStatus": "Scheduled"},
    }

    def fake_get(url, params=None, timeout=None):
        r = mock.Mock(status_code=200)
        r.json.return_value = listing if "committee-meeting/119" in url else {"committeeMeeting": meetings[url]}
        return r

    with mock.patch.object(gov.requests, "get", fake_get):
        out = gov.hearings(date(2026, 10, 19), date(2026, 11, 30), ["Armed Services"])
    titles = [e["title"] for e in out]
    assert titles == ["Posture of the Army", "Posture of the Army"]  # once per chamber listing
    assert out[0]["start_time"] == "10:00 AM ET"


def test_schedule_guard(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_SCHEDULE", "50 10 * * 1")
    edt = main.intended_slot_ok.__globals__["datetime"]
    with mock.patch.object(main, "datetime") as dt:
        dt.now.return_value = edt(2026, 10, 19, 11, 5, tzinfo=main.timezone.utc)  # EDT: slot is 6:50
        assert main.intended_slot_ok()
        dt.now.return_value = edt(2026, 12, 7, 11, 5, tzinfo=main.timezone.utc)   # EST: slot is 5:50
        assert not main.intended_slot_ok()
