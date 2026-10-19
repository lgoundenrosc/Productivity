"""Claude calls: pull events out of page text, then score them."""
import json
import os

import anthropic

MODEL = os.environ.get("TRACKER_MODEL", "claude-opus-5-5")
_client = None


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _json_call(prompt, schema, effort="low"):
    # `fallbacks: "default"` reroutes a safety decline (e.g. the bio
    # classifier on an AI x biosecurity panel) instead of dropping the batch.
    resp = client().beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": effort,
                       "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined the request")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("Claude's reply was cut off at max_tokens")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def _obj(props):
    return {"type": "object", "properties": props,
            "required": list(props), "additionalProperties": False}


S = {"type": "string"}
EVENT_SCHEMA = _obj({"events": {"type": "array", "items": _obj({
    "title": S,
    "date": {"type": "string", "description": "YYYY-MM-DD"},
    "start_time": {"type": "string", "description": "e.g. 10:00 AM ET, or empty"},
    "location": S,
    "format": {"type": "string", "enum": ["in-person", "virtual", "hybrid", "unknown"]},
    "speakers": {"type": "array", "items": S},
    "summary": {"type": "string", "description": "One or two sentences"},
    "url": S,
})}})


def extract_events(source_name, text, today, until, dc_only=False):
    where = ("Keep only events held in the Washington, DC area or online; "
             "drop events in other cities. " if dc_only else "")
    prompt = f"""Below is the text of the events page of {source_name}, captured on {today}.
Links appear inline as `label <url>`.

List every event dated from {today} to {until} inclusive. {where}Skip past events,
recordings of past events, and navigation links. If the year is missing, infer it
from today's date. Use the event's own page as `url` when one is linked, otherwise
the registration link, otherwise an empty string. Use empty strings and empty lists
for anything the page does not say. Do not invent speakers or details.

<page>
{text}
</page>"""
    return _json_call(prompt, EVENT_SCHEMA)["events"]


def score_events(events, profile):
    """Adds category, score (1-10) and reason to each event, in place."""
    cats = profile["categories"]
    schema = _obj({"scores": {"type": "array", "items": _obj({
        "idx": {"type": "integer"},
        "category": {"type": "string", "enum": [c["id"] for c in cats]},
        "score": {"type": "integer", "description": "1 to 10"},
        "reason": {"type": "string", "description": "One short sentence"},
    })}})
    cat_lines = "\n".join(f"- {c['id']}: {c['name']}" for c in cats)
    for start in range(0, len(events), 40):
        batch = events[start:start + 40]
        listing = "\n\n".join(
            f"[{i}] {e['source']} | {e['date']} {e.get('start_time', '')} | "
            f"{e.get('format', '')} | {e.get('location', '')}\n{e['title']}\n"
            f"Speakers: {', '.join(e.get('speakers') or []) or 'not listed'}\n"
            f"{e.get('summary', '')}"
            for i, e in enumerate(batch))
        prompt = f"""You are choosing which Washington events a reader should attend.

Reader: {profile['reader']}
Interests: {profile['interests']}
Score higher for: {profile['boost']}
Score lower for: {profile['penalize']}

For each event give one category from this list:
{cat_lines}

and a score from 1 (skip) to 10 (must attend) for this reader, with a one-sentence
reason naming the specific draw (a speaker, a topic, a buyer in the room).
Return one entry per event, using its [idx].

{listing}"""
        for s in _json_call(prompt, schema, effort="medium")["scores"]:
            if 0 <= s["idx"] < len(batch):
                batch[s["idx"]].update(category=s["category"],
                                       score=s["score"], reason=s["reason"])
    return events
