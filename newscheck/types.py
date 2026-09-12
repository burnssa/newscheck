from pydantic import BaseModel
from typing import Optional


class Article(BaseModel):
    url: str
    title: Optional[str] = None
    author: Optional[str] = None
    domain: str
    text: str
    sentence_count: int
    word_count: int
    truncated: bool = False
    article_type: str = "unknown"  # opinion, news, analysis, fact-check, research, unknown
    type_confidence: str = "none"  # high, medium, low, none
    type_source: Optional[str] = None  # which tier classified it: url, html_metadata, llm


class ExtractedClaim(BaseModel):
    quote: str
    normalized: str
    category: str  # "statistical", "causal", "comparative", "historical", "procedural"
    char_start: int
    char_end: int


class ExtractionResult(BaseModel):
    article: Article
    claims: list[ExtractedClaim]
    claims_density: float
    extraction_model: str
