# coding: utf-8
# -------------------------------------------------------------------
# aaPanel Agent — PanelDocsLookup tool
# Official docs lookup: route topic keyword -> fetch -> markdown
# -------------------------------------------------------------------
import re
import requests

from . import register_tool
from .base import _xml_response
from .webfetch import simple_html_to_markdown

_DOCS_BASE = "https://www.aapanel.com/docs"
_DEFAULT_TIMEOUT = 30
_MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5MB
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html;q=1.0, application/xhtml+xml;q=0.9, */*;q=0.1",
}

# keyword (lowercase, EN) -> docs page URL. extend here only, prompt stays unchanged
_DOCS_URL_MAP = {
    # panel basics / FAQ
    "faq": f"{_DOCS_BASE}/faq/Panel_Related.html",
    "panel": f"{_DOCS_BASE}/faq/Panel_Related.html",
    "login": f"{_DOCS_BASE}/faq/Panel_Related.html",
    "password": f"{_DOCS_BASE}/faq/Panel_Related.html",
    "port": f"{_DOCS_BASE}/faq/Panel_Related.html",
    "install": f"{_DOCS_BASE}/guide/quickstart.html",
    # website
    "website": f"{_DOCS_BASE}/Function/Website.html",
    # domains / dns / ssl
    "domain": f"{_DOCS_BASE}/Function/Domains.html",
    "ssl": f"{_DOCS_BASE}/Function/Domains.html",
    "certificate": f"{_DOCS_BASE}/Function/Domains.html",
    "dns": f"{_DOCS_BASE}/Function/Domains.html",
    # cron / backup
    "cron": f"{_DOCS_BASE}/Function/Cron.html",
    "backup": f"{_DOCS_BASE}/Function/Cron.html",
    # mail
    "mail": f"{_DOCS_BASE}/Function/MailServer.html",
    "email": f"{_DOCS_BASE}/Function/MailServer.html",
    # app store / plugins
    "appstore": f"{_DOCS_BASE}/Function/AppStore.html",
    "plugin": f"{_DOCS_BASE}/Function/AppStore.html",
    # home / dashboard
    "home": f"{_DOCS_BASE}/Function/Home.html",
    "dashboard": f"{_DOCS_BASE}/Function/Home.html",
}
_INDEX_FALLBACK = f"{_DOCS_BASE}/Function/Tutorial/Tutorial-list.html"


def _route(topic: str, module: str = "") -> str:
    """topic keyword -> docs URL. module bypasses routing."""
    if module:
        return f"{_DOCS_BASE}/Function/{module}.html"
    t = topic.strip().lower()
    if t in _DOCS_URL_MAP:
        return _DOCS_URL_MAP[t]
    # when topic contains a keyword, prefer the longest (more specific) match
    for key in sorted(_DOCS_URL_MAP.keys(), key=len, reverse=True):
        if key and key in t:
            return _DOCS_URL_MAP[key]
    return _INDEX_FALLBACK


def _fetch_docs(url: str) -> str:
    """fetch a docs page and return markdown. reuses webfetch.simple_html_to_markdown."""
    resp = requests.get(url, headers=_HEADERS, timeout=_DEFAULT_TIMEOUT, stream=True)
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code} from {url}")

    content_length = resp.headers.get("content-length")
    if content_length and int(content_length) > _MAX_RESPONSE_SIZE:
        raise RuntimeError("Response too large (exceeds 5MB limit)")

    raw = b""
    for chunk in resp.iter_content(chunk_size=8192):
        if chunk:
            raw += chunk
            if len(raw) > _MAX_RESPONSE_SIZE:
                raise RuntimeError("Response too large (exceeds 5MB limit)")

    # encoding: content-type charset -> meta charset -> utf-8; fallback gb18030
    encoding = resp.encoding
    content_type = resp.headers.get("content-type", "").lower()
    if "charset=" in content_type:
        encoding = content_type.split("charset=")[-1].split(";")[0].strip() or encoding
    if not encoding or encoding.lower() == "iso-8859-1":
        meta = re.search(rb'<meta[^>]*charset=["\']?\s*([a-zA-Z0-9_-]+)', raw, re.I)
        encoding = meta.group(1).decode("ascii", errors="ignore") if meta else "utf-8"
    try:
        html = raw.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        try:
            html = raw.decode("gb18030")
        except UnicodeDecodeError:
            html = raw.decode("utf-8", errors="replace")
    return simple_html_to_markdown(html)


def _inject_keyword_doc(func):
    """把 _DOCS_URL_MAP 的 key 注入工具 docstring, 自动同步."""
    keywords = ", ".join(sorted(_DOCS_URL_MAP.keys()))
    func.__doc__ = (func.__doc__ or "") + (
        "\n\n    Supported topic keywords (exact or substring match): " + keywords + "."
    )
    return func


@register_tool(category="Docs", name_cn="Panel Docs Lookup", risk_level="low")
@_inject_keyword_doc
def PanelDocsLookup(topic: str = "", module: str = "") -> str:
    """
    Look up aaPanel's official documentation for a feature and return it as markdown.

    When to use:
    - The user asks HOW TO USE or CONFIGURE an aaPanel feature (e.g. "how to set up SSL",
      "where is cron", "what does the WAF do", "how to add a website").
    - You need accurate panel instructions instead of answering from memory.

    Stay within the docs: this tool only reads official documentation — not live
    diagnostics, running commands, or the user's specific server state (use SiteList /
    RunCommand etc. for those). Answer strictly from the fetched page, and do not chain
    into follow-up actions after a lookup unless the user explicitly asks.

     The tool routes `topic` via an internal English keyword map. Pass a keyword close to
    what the user asks about — it must match one of the map's English keys (exact or as
    a substring), otherwise routing falls back to a tutorial index. If unsure of the
    keyword, pass the exact docs module name as `module` (PascalCase, e.g. "Website") to
    fetch that page directly.

    Args:
        topic: Feature keyword matching the user's question; must hit an English key in
               the route map, e.g. "ssl", "cron backup", "dns", "certificate".
        module: Optional exact docs module name (PascalCase) to fetch directly,
                e.g. "Website", "Cron", "Domains". Skips keyword routing.
    """
    if not topic and not module:
        return _xml_response(
            "PanelDocsLookup", "error",
            "Provide a feature `topic` (e.g. 'ssl') or a `module` name (e.g. 'Website').",
        )
    try:
        url = _route(topic, module)
        content = _fetch_docs(url)
        if not content.strip():
            return _xml_response("PanelDocsLookup", "error", f"Empty docs from {url}")
        return _xml_response("PanelDocsLookup", "done", content)
    except requests.Timeout:
        return _xml_response("PanelDocsLookup", "error", "Request timed out")
    except requests.RequestException as e:
        return _xml_response("PanelDocsLookup", "error", f"Request failed: {e}")
    except Exception as e:
        return _xml_response("PanelDocsLookup", "error", str(e))
