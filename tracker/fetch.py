"""Download event pages and reduce them to compact text for extraction."""
import os
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
DROP_TAGS = ["script", "style", "noscript", "svg", "nav", "form", "iframe",
             "button", "select"]


def get_html(url, browser=False):
    if browser:
        return _get_html_browser(url)
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    if r.encoding and r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding  # server sent no charset
    return r.text


def _get_html_browser(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        try:
            page = b.new_page()  # a spoofed UA gets blocked; keep Chromium's own
            resp = page.goto(url, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            if resp and resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status} from {url}")
            return page.content()
        finally:
            b.close()


def page_text(html, base_url):
    """Visible text with links kept inline as `text <url>` so Claude can
    return registration links."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(DROP_TAGS):
        tag.decompose()
    # Drop the site banner and footer, but keep <header> elements inside event
    # cards, which some sites (SpaceNews) use for the event title.
    for tag in soup.find_all(["header", "footer"]):
        if not tag.find_parent(["article", "main", "section", "li"]):
            tag.decompose()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        label = a.get_text(" ", strip=True)
        if label and href.startswith("http"):
            a.replace_with(f"{label} <{href}>")
    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{2,}", "\n", text)


def source_text(src, recent_days=30):
    """Text for one source, by its `fetch` type: http (default), browser,
    luma (a Luma calendar or city page) or rss (a newsletter feed)."""
    kind = src.get("fetch", "http")
    if kind == "luma":
        return luma_text(src["url"])
    if kind == "rss":
        return rss_text(src["url"], recent_days)
    return page_text(get_html(src["url"], browser=kind == "browser"), src["url"])


def luma_text(url):
    """Luma renders dates client-side, so read the event data embedded in
    the page instead of its visible text."""
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    html = get_html(url)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("Luma page has no embedded event data")
    lines, seen = [], set()

    def walk(o):
        if isinstance(o, dict):
            ev = o.get("event") if isinstance(o.get("event"), dict) else None
            if ev and ev.get("start_at") and ev.get("api_id") not in seen:
                seen.add(ev.get("api_id"))
                start = datetime.fromisoformat(ev["start_at"].replace("Z", "+00:00"))
                geo = ev.get("geo_address_info") or {}
                where = geo.get("full_address") or geo.get("city_state") or (
                    "Online" if ev.get("location_type") == "online" else "")
                hosts = ", ".join(h.get("name", "") for h in o.get("hosts") or [] if isinstance(h, dict))
                lines.append(" | ".join(filter(None, [
                    ev.get("name", ""),
                    start.astimezone(ZoneInfo("America/New_York")).strftime("%A %B %d %Y, %I:%M %p ET"),
                    where, f"Hosts: {hosts}" if hosts else "",
                    f"<https://luma.com/{ev.get('url', '')}>"])))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(json.loads(m.group(1)))
    return "\n".join(lines)


def rss_text(url, recent_days):
    """Recent newsletter posts, which often announce happy hours."""
    from datetime import datetime, timedelta, timezone
    from email.utils import parsedate_to_datetime
    soup = BeautifulSoup(get_html(url), "xml")
    cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
    posts = []
    for item in soup.find_all("item"):
        try:
            posted = parsedate_to_datetime(item.pubDate.text)
        except Exception:
            continue
        if posted < cutoff:
            continue
        body = item.find("content:encoded") or item.description
        text = page_text(body.text if body else "", item.link.text if item.link else url)
        posts.append(f"## {item.title.text} (posted {posted:%B %d %Y}) <{item.link.text}>\n{text}")
    return "\n\n".join(posts)
