import json
import logging
from typing import Optional

from openai import OpenAI

from .prompts import CLAIM_EXTRACTION_PROMPT
from .types import Article, ExtractedClaim, ExtractionResult

logger = logging.getLogger(__name__)


def _find_quote_position(article_text: str, quote: str) -> tuple[int, int]:
    """Find the start and end position of a quote in the article text."""
    idx = article_text.find(quote)
    if idx >= 0:
        return idx, idx + len(quote)

    # Try case-insensitive search
    lower_text = article_text.lower()
    lower_quote = quote.lower()
    idx = lower_text.find(lower_quote)
    if idx >= 0:
        return idx, idx + len(quote)

    # Try matching a substring (first 60 chars of the quote)
    if len(quote) > 60:
        short = quote[:60]
        idx = article_text.find(short)
        if idx >= 0:
            return idx, idx + len(quote)

    # Could not locate — return -1, -1
    return -1, -1


def extract_claims(
    article: Article,
    api_key: str,
    model: str = "gpt-4o-mini",
    base_url: Optional[str] = None,
) -> ExtractionResult:
    """
    Extract verifiable claims from article text using an LLM.

    Uses OpenAI-compatible API so it works with any provider.
    The caller provides their own API key and model choice.
    """
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    client = OpenAI(**client_kwargs)

    prompt = CLAIM_EXTRACTION_PROMPT.format(article_text=article.text)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        content = response.choices[0].message.content
        parsed = json.loads(content)

        # Handle both {"claims": [...]} and bare [...] responses
        if isinstance(parsed, dict):
            raw_claims = parsed.get("claims", parsed.get("results", []))
        elif isinstance(parsed, list):
            raw_claims = parsed
        else:
            logger.warning(f"Unexpected response format: {type(parsed)}")
            raw_claims = []

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        raw_claims = []
    except Exception as e:
        logger.error(f"LLM API call failed: {e}")
        raise

    claims = []
    for raw in raw_claims:
        try:
            quote = raw.get("quote", "")
            normalized = raw.get("normalized", "")
            category = raw.get("category", "procedural")

            if not quote or not normalized:
                continue

            valid_categories = {"statistical", "causal", "comparative", "historical", "procedural"}
            if category not in valid_categories:
                category = "procedural"

            char_start, char_end = _find_quote_position(article.text, quote)

            claims.append(
                ExtractedClaim(
                    quote=quote,
                    normalized=normalized,
                    category=category,
                    char_start=char_start,
                    char_end=char_end,
                )
            )
        except Exception as e:
            logger.warning(f"Skipping malformed claim: {e}")
            continue

    density = len(claims) / article.sentence_count if article.sentence_count > 0 else 0.0

    return ExtractionResult(
        article=article,
        claims=claims,
        claims_density=density,
        extraction_model=model,
    )
