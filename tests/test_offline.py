"""Offline checks: no network, no Claude calls."""
from datetime import date
from unittest import mock
from urllib.parse import parse_qs, urlparse

import yaml

from tracker import digest, gov, main, store

PROFILE = yaml.safe_load(open("config/dc/profile.yaml"))
BOSTON = yaml.safe_load(open("config/boston/profile.yaml"))


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
    events = [ev(date="2026-10-28"), ev(title="Low", score=3), ev(title="Bio", category="aibio", score=6, date="2026-10-29"),
              ev(kind="hearing", title="HASC posture hearing", category="defense", score=7),
              ev(kind="industry_day", title="Army Industry Day", category="defense", score=6)]
    html = digest.build(events, PROFILE, date(2026, 10, 19), [("SpaceNews", "HTTP 403")])
    assert "TOP PICK" in html and "AI x bio and WMD risk" in html
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


def test_format_badges_and_in_person_first():
    events = [ev(title="Webinar on drones", format="virtual", date="2026-10-27"),
              ev(title="Drone panel at CSIS", format="in-person", date="2026-10-30")]
    html = digest.build(events, PROFILE, date(2026, 10, 19), [])
    section = html.split("Robotics, autonomy and drones")[1]
    assert section.index("Drone panel at CSIS") < section.index("Webinar on drones")
    assert "IN PERSON" in html and "ONLINE ONLY" in html


def test_this_week_networking_and_travel_sections():
    events = [ev(title="CSIS panel tomorrow", date="2026-10-20"),
              ev(title="Defense Tech DC happy hour", date="2026-10-27", event_type="networking", category="venture"),
              ev(title="Spark Tank in Chicago", date="2026-11-02", event_type="industry_day", local=False,
                 location="Chicago, IL"),
              ev(title="Later DC panel", date="2026-11-05")]
    html = digest.build(events, PROFILE, date(2026, 10, 19), [])
    sections = html.split("<h2")
    find = lambda t: next(i for i, sec in enumerate(sections) if t in sec)
    assert "This week" in sections[find("CSIS panel tomorrow")]
    assert "Happy hours" in sections[find("Defense Tech DC happy hour")]
    assert "Conferences and big events ahead" in sections[find("Spark Tank in Chicago")]
    assert "Travel:" in html and html.count("CSIS panel tomorrow") == 1


def test_place_rules():
    b = PROFILE["location_bonus"]
    today, local_until = date(2026, 10, 19), date(2026, 11, 9)
    dc = ev(score=6)
    assert main.place(dc, today, local_until, b) and dc["score"] == 8
    away_talk = ev(local=False, event_type="talk")
    assert not main.place(away_talk, today, local_until, b)
    away_conf = ev(local=False, event_type="conference", date="2027-01-15", score=6)
    assert main.place(away_conf, today, local_until, b) and away_conf["score"] == 6
    far_talk = ev(date="2026-12-15", event_type="talk")
    assert not main.place(far_talk, today, local_until, b)
    webinar = ev(format="virtual", score=6)
    assert main.place(webinar, today, local_until, b) and webinar["score"] == 5


def test_networking_is_dc_or_online():
    b, today, until = PROFILE["location_bonus"], date(2026, 10, 19), date(2026, 11, 9)
    assert main.place(ev(event_type="networking", networking_source=True), today, until, b)
    online = ev(event_type="networking", format="virtual", score=6)
    assert main.place(online, today, until, b) and online["score"] == 5
    assert not main.place(ev(event_type="networking", local=False), today, until, b)
    assert not main.place(ev(networking_source=True, event_type="industry_day", local=False), today, until, b)


def test_localist_keyword_filter(monkeypatch):
    from tracker import fetch
    page = {"events": [
        {"event": {"title": "Defense-Tech Innovation Exchange", "description_text": "", "location_name": "National Landing",
                   "experience": "inperson", "localist_url": "https://cal/x",
                   "event_instances": [{"event_instance": {"start": "2026-10-22T17:00:00-04:00"}}]}},
        {"event": {"title": "Men's Soccer", "description_text": "", "localist_url": "https://cal/y",
                   "event_instances": [{"event_instance": {"start": "2026-10-31T14:00:00-04:00"}}]}}],
        "page": {"total": 1}}
    resp = mock.Mock(); resp.json.return_value = page
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: resp)
    out = fetch.localist_text("https://cal", "defen[cs]e|startup", date(2026, 10, 19), date(2026, 11, 9))
    assert "Innovation Exchange" in out and "Soccer" not in out


def test_search_agent_resumes_after_pause(monkeypatch):
    from tracker import llm
    text = mock.Mock(type="text", text="Event A | Oct 22")
    paused = mock.Mock(stop_reason="pause_turn", content=[])
    done = mock.Mock(stop_reason="end_turn", content=[text])
    fake = mock.Mock(); fake.beta.messages.create.side_effect = [paused, done]
    monkeypatch.setattr(llm, "client", lambda: fake)
    assert llm.search_text("focus", date(2026, 10, 19), date(2026, 11, 9), "Greater Boston") == "Event A | Oct 22"
    second_call = fake.beta.messages.create.call_args_list[1].kwargs
    assert second_call["messages"][-1]["role"] == "assistant"


def test_city_configs_are_complete():
    for city in ("dc", "boston"):
        cfg = yaml.safe_load(open(f"config/{city}/sources.yaml"))
        profile = yaml.safe_load(open(f"config/{city}/profile.yaml"))
        assert {"name", "long_name", "area", "local_label", "seen_file"} <= set(profile["city"])
        for w in cfg["workers"]:
            assert w in main.GOV_WORKERS or cfg[w], f"{city}: worker {w} has no sources"
    assert "aibio" not in {c["id"] for c in BOSTON["categories"]}
    assert BOSTON["categories"][0]["id"] == "lp"


def test_boston_digest_puts_receptions_under_topics():
    events = [ev(title="Family office dinner", date="2026-10-29", event_type="networking", category="lp",
                 networking_source=True, location="Boston, MA"),
              ev(title="Judges wanted for MIT $100K", date="2026-12-01", event_type="speaking_call",
                 category="speaking")]
    html = digest.build(events, BOSTON, date(2026, 10, 19), [])
    assert "Boston events: week of" in html and "Happy hours" not in html
    lp = html.split("LP access")[1]
    assert "Family office dinner" in lp
    b, today, until = BOSTON["location_bonus"], date(2026, 10, 19), date(2026, 11, 9)
    assert main.place(events[1], today, until, b)  # a speaker call due after three weeks stays


def test_same_day_events_sort_by_clock_time():
    events = [ev(title="Evening dinner", start_time="6:00 PM ET"), ev(title="Morning summit", start_time="8:30 AM ET")]
    html = digest.build(events, PROFILE, date(2026, 10, 19), [])
    assert html.index("Morning summit") < html.index("Evening dinner")


def test_this_week_ends_on_sunday():
    events = [ev(title="Saturday demo day", date="2026-10-24"), ev(title="Monday summit", date="2026-10-26")]
    html = digest.build(events, BOSTON, date(2026, 10, 22), [])  # a Thursday
    this_week = html.split("<h2")[1]
    assert "Oct 22 to Oct 25" in this_week
    assert "Saturday demo day" in this_week and "Monday summit" not in this_week
