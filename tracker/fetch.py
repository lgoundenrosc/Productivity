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
