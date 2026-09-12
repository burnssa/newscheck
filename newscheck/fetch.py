import re
from configparser import ConfigParser
from typing import Optional
from urllib.parse import urlparse

import trafilatura
from trafilatura.settings import DEFAULT_CONFIG

from .types import Article

MAX_CHARS = 60000

# ---------- Article type classification ----------

# Tier 1: URL path segments that indicate opinion content
_OPINION_URL_SEGMENTS = [
    "/opinion/", "/opinions/", "/editorial/", "/editorials/",
    "/commentary/", "/commentisfree/", "/op-ed/", "/oped/",
    "/perspective/", "/perspectives/",
    "/views/", "/contributors/", "/columnists/", "/op-eds/",
]

# Tier 2: HTML metadata keywords (case-insensitive matching)
_OPINION_KEYWORDS = {
    "opinion", "editorial", "commentary", "op-ed", "oped",
    "perspective", "columnist", "column", "letter to the editor",
    "OpinionNewsArticle",
}


def _classify_by_url(url: str) -> Optional[tuple[str, str]]:
    """Tier 1: Check URL path for opinion signals. Returns (article_type, detail) or None."""
    path = urlparse(url).path.lower()
    for segment in _OPINION_URL_SEGMENTS:
        if segment in path:
            return "opinion", segment.strip("/")
    return None


def _classify_by_html(html: str) -> Optional[tuple[str, str]]:
    """Tier 2: Check HTML metadata for opinion signals. Returns (article_type, detail) or None."""
    checks = [
        (r'"articleSection"\s*:\s*"([^"]+)"', "schema:articleSection"),
        (r'property="article:section"\s+content="([^"]+)"', "meta:article:section"),
        (r'"genre"\s*:\s*"([^"]+)"', "schema:genre"),
        (r'<meta[^>]*name="category"[^>]*content="([^"]+)"', "meta:category"),
        (r'<meta[^>]*name="content-type"[^>]*content="([^"]+)"', "meta:content-type"),
    ]
    for pattern, source in checks:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for match in matches:
            if any(kw in match.lower() for kw in _OPINION_KEYWORDS):
                return "opinion", f"{source}={match}"

    # Check CSS classes for category-opinion, category-editorial patterns
    class_pattern = r'class="([^"]*(?:category-opinion|category-editorial|category-commentary|category-op-ed)[^"]*)"'
    if re.search(class_pattern, html, re.IGNORECASE):
        return "opinion", "css:category-class"

    return None


def classify_article(url: str, html: Optional[str] = None) -> tuple[str, str, str]:
    """
    Classify an article as opinion/news/etc using a tiered approach.

    Returns (article_type, confidence, source_tier).
    """
    # Tier 1: URL path
    result = _classify_by_url(url)
    if result:
        return result[0], "high", f"url:{result[1]}"

    # Tier 2: HTML metadata (only if html provided)
    if html:
        result = _classify_by_html(html)
        if result:
            return result[0], "high", f"html:{result[1]}"

    # Tier 2b: Check title for editorial/opinion keywords
    # Some outlets embed "Editorial:" or "Opinion:" in the title
    if html:
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        if title_match:
            title_lower = title_match.group(1).lower()
            for kw in ["editorial:", "opinion:", "op-ed:", "commentary:"]:
                if kw in title_lower:
                    return "opinion", "medium", f"title:{kw.strip(':')}"

    # No opinion signals found — default to news
    return "news", "medium", "default"

# Use a browser-like User-Agent to avoid 403 rejections from news sites
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _get_config() -> ConfigParser:
    """Return a trafilatura config with a browser-like User-Agent."""
    config = ConfigParser()
    config.read_dict({"DEFAULT": dict(DEFAULT_CONFIG["DEFAULT"])})
    config.set("DEFAULT", "USER_AGENTS", _BROWSER_UA)
    return config


def _count_sentences(text: str) -> int:
    """Count sentences by splitting on sentence-ending punctuation followed by whitespace."""
    parts = re.split(r'[.!?][\s\n]+', text)
    # Filter out empty strings from the split
    return len([p for p in parts if p.strip()])


def _truncate_at_sentence_boundary(text: str, max_chars: int) -> str:
    """Truncate text at the last sentence boundary before max_chars."""
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    # Find the last sentence-ending punctuation
    last_sentence_end = max(
        truncated.rfind('. '),
        truncated.rfind('! '),
        truncated.rfind('? '),
        truncated.rfind('.\n'),
        truncated.rfind('!\n'),
        truncated.rfind('?\n'),
    )

    if last_sentence_end > 0:
        return truncated[:last_sentence_end + 1]

    # Fallback: truncate at last whitespace
    last_space = truncated.rfind(' ')
    if last_space > 0:
        return truncated[:last_space]

    return truncated


def fetch_article(url: str) -> Article:
    """
    Fetch and extract clean article text from a URL.

    Uses trafilatura for content extraction.
    Truncates at MAX_CHARS with a flag if exceeded.
    """
    config = _get_config()
    downloaded = trafilatura.fetch_url(url, config=config)
    if not downloaded:
        # Some sites block browser-like UAs; retry with trafilatura defaults
        downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise ValueError(f"Failed to download article from {url}")

    text = trafilatura.extract(
        downloaded,
        output_format="txt",
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )

    if not text:
        raise ValueError(f"Failed to extract article text from {url}")

    # Extract metadata (title, author)
    # trafilatura 2.0+ returns a Document object from bare_extraction
    title = None
    author = None
    try:
        metadata_obj = trafilatura.bare_extraction(downloaded)
        if metadata_obj:
            title = getattr(metadata_obj, "title", None) or (metadata_obj.get("title") if isinstance(metadata_obj, dict) else None)
            author = getattr(metadata_obj, "author", None) or (metadata_obj.get("author") if isinstance(metadata_obj, dict) else None)
    except Exception:
        pass

    domain = urlparse(url).netloc

    truncated = len(text) > MAX_CHARS
    if truncated:
        text = _truncate_at_sentence_boundary(text, MAX_CHARS)

    sentence_count = _count_sentences(text)
    word_count = len(text.split())

    # Classify article type
    article_type, type_confidence, type_source = classify_article(url, html=downloaded)

    return Article(
        url=url,
        title=title,
        author=author,
        domain=domain,
        text=text,
        sentence_count=sentence_count,
        word_count=word_count,
        truncated=truncated,
        article_type=article_type,
        type_confidence=type_confidence,
        type_source=type_source,
    )
