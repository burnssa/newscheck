import re
from urllib.parse import urlparse

import trafilatura

from .types import Article

MAX_CHARS = 60000


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

    return Article(
        url=url,
        title=title,
        author=author,
        domain=domain,
        text=text,
        sentence_count=sentence_count,
        word_count=word_count,
        truncated=truncated,
    )
