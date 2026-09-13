"""
SSE endpoint for progressive article claim checking.

Events emitted in order:
  1. article_ready    — article text, metadata, classification
  2. extraction_ready — claims extracted with density stats
  3. claim_assessed   — one per claim, streamed as each completes
  4. done             — final summary stats
"""

import json
import os
import re
import time
from datetime import datetime

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from .fetch import fetch_article, classify_article

# ---------- Config ----------

# Reads a .env from the working directory if one exists. Real environment variables win.
load_dotenv()

PROVIDER_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
}
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# Used when DATABASE_URL is not set. These are the four models the batch results in
# output/ were produced with. Entries whose provider key is missing from the
# environment are skipped, so set only the keys you have.
DEFAULT_MODELS = [
    {"name": "gpt-5-chat-latest", "provider": "openai", "adapter": "OpenAIAdapter",
     "endpoint": "https://api.openai.com/v1/chat/completions"},
    {"name": "claude-opus-4-5-20251101", "provider": "anthropic", "adapter": "AnthropicAdapter",
     "endpoint": "https://api.anthropic.com/v1/messages"},
    {"name": "claude-sonnet-4-5-20250929", "provider": "anthropic", "adapter": "AnthropicAdapter",
     "endpoint": "https://api.anthropic.com/v1/messages"},
    {"name": "grok-4-fast-non-reasoning", "provider": "xai", "adapter": "XAIAdapter",
     "endpoint": "https://api.x.ai/v1/chat/completions"},
]

app = FastAPI(title="Newscheck", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------- Prompts (imported from compare_models logic) ----------

EXTRACTION_PROMPT = """You are a research analyst identifying verifiable factual claims in a news article.

Each claim MUST correspond to exactly one sentence from the numbered list below. A sentence may contain zero, one, or multiple verifiable claims. If a sentence contains multiple distinct verifiable facts, extract each as a separate claim referencing the same sentence number.

A verifiable claim is a SPECIFIC, QUANTIFIED assertion that a researcher could confirm or refute by consulting a named public data source (official statistics, government records, published research, regulatory filings).

STRICT INCLUSION CRITERIA — every extracted claim MUST satisfy ALL of these:
1. Contains at least one specific quantity: a number, percentage, dollar amount, date, ratio, or named measurement
2. Can be checked against a specific, identifiable primary source (e.g., BLS data, SEC filings, Census data, court records, published studies)
3. Is non-trivial — it asserts something substantive, not a routine fact about reporting or publication

DO extract:
- Statistics with specific figures ("unemployment fell to 3.4%", "shed 92,000 jobs")
- Comparisons with concrete numbers ("up from 3.1% a year earlier", "the lowest rate since 1969")
- Named quantities tied to documented events ("the strike affected 31,000 workers")
- Specific financial or economic figures ("wage growth was 0.4% monthly", "gas averaged $3.31/gallon")
- Factual data points within fact-check articles, even when near attributed quotes

DO NOT extract:
- Direction-only claims without magnitude ("the number fell", "jobs declined", "scores dropped")
- Trivial meta-claims about reporting ("BLS released data on Friday", "the report was published")
- Subjective characterizations, even if loosely checkable ("weakest in history", "most industries lost jobs", "a sharp setback")
- Vague causal claims ("the war sent gas prices higher", "tariffs hurt manufacturing")
- Opinions, predictions, or aspirational statements
- Attributed quotes (what someone said, believed, or intended)
- Rhetorical framing, figurative language, or editorial judgment
- Claims where the only "verification" would be finding another article that says the same thing

The test: Does this claim state a specific number or measurement AND point to a concrete primary data source a researcher could consult? If either answer is no, do not extract it.

For each claim, return:
- "sentence_index": the sentence number (0-based) from the numbered list below
- "claim": a standalone factual assertion. Strip the reporting publication (e.g., do NOT include "CBS reported" or "according to the article"). But PRESERVE any named reference data source (e.g., "according to ADP data", "a Tax Foundation analysis found", "the CME FedWatch tool shows") so a researcher knows where to verify the underlying fact.
- "category": one of "statistical", "comparative", "historical", "procedural"
- "source_hint": (optional) if the sentence names the organization or dataset the fact comes from, include the organization AND the type of data or report referenced. Examples: "ADP turnover report", "Tax Foundation tax analysis", "JOLTS job openings data", "Census Bureau poverty data", "CME FedWatch tool". Be specific about both the source and the metric. Omit if no specific source is named.

Return ONLY a valid JSON array. No markdown, no explanation.

Numbered sentences:
{numbered_sentences}"""

QUERY_GEN_PROMPT = """Given a factual claim from a news article, generate 1-2 search queries designed to find the PRIMARY authoritative source that would confirm or deny this claim.

Target official and primary sources: government databases (BLS, Census, SEC), academic research, official organizational reports, press releases from the originating institution, regulatory filings.

CRITICAL: If a source_hint is provided, it tells you exactly which organization or dataset produced the data. Target that source FIRST. For example, if the source_hint is "ADP", search for ADP research reports — do NOT default to BLS. If the source_hint is "Tax Foundation", search Tax Foundation — do NOT default to IRS.

When constructing queries, focus on the SPECIFIC METRIC in the claim, not just the organization name. Many organizations publish multiple reports — match the metric. For example:
- "ADP" + "turnover rate" → search "ADP Research turnover" or "ADP workforce vitality", NOT "ADP National Employment Report" (which covers job creation, not turnover)
- "BLS" + "job openings" → search "JOLTS", not "Employment Situation"
- "Census" + "poverty rate" → search "Census poverty", not "Census population"

Avoid queries that would just return other news articles repeating the same claim. Think about WHERE the underlying data originates and how to reach that source directly.

IMPORTANT: This claim comes from an article published around {article_date} at {article_url}. Use this temporal context when constructing queries — if the claim says "in February" without a year, it means February relative to the article's publication date.

Claim: {claim_text}
Category: {category}
Source hint: {source_hint}

Return ONLY a JSON array of 1-2 search query strings. Example:
["BLS employment situation report February 2026 nonfarm payrolls", "bureau labor statistics unemployment rate data 2026"]"""

ASSESSMENT_PROMPT = """You are a fact-checker verifying a claim from a news article. Assess whether the claim is supported by the web sources provided below.

IMPORTANT GUIDELINES:
1. Base your assessment PRIMARILY on the web search results. You may use general knowledge only to interpret the sources.
2. A claim is "supported" if the core factual assertion is confirmed by sources, even if minor details differ (e.g., a source says "80-85%" and the claim says "85%" — that is supported, not partially supported).
3. These claims come from articles published at a specific point in time. If sources confirm the figure was accurate at any recent point, treat it as "supported" — do NOT mark a claim as unsupported just because a newer figure exists.
4. "partially_supported" is a NARROW category. Use it ONLY when part of the claim is confirmed BUT another SUBSTANTIVE part is actively contradicted or genuinely unverifiable.
5. "not_supported" means the sources actively contradict the claim OR the sources contain no relevant information about the claim at all.
6. If the web search results are clearly irrelevant to the claim (wrong topic entirely), say so and use "not_supported" with a note that search results were not relevant.

For each piece of evidence you cite, reference the specific source number (e.g., [Source 1], [Source 2]).

Claim to assess:
{claim_text}

Claim category: {category}

Web search results:
{search_results}

Return ONLY valid JSON with these fields:
- "verdict": one of "supported", "partially_supported", "not_supported"
- "reasoning": 2-3 sentences explaining your assessment, citing specific source numbers from the search results above.
- "sources": array of URLs from the search results that inform your assessment
- "note": optional string — include ONLY if there is a factual caveat the reader should know. Omit if none."""


# ---------- DB + API callers ----------

def _default_models():
    """Static model list for running without a database."""
    models = []
    for i, m in enumerate(DEFAULT_MODELS, start=1):
        api_key = os.getenv(PROVIDER_KEY_MAP.get(m["provider"], ""), "")
        if not api_key:
            continue
        models.append({"id": i, **m, "api_key": api_key, "auth_type": "bearer"})
    return models


def _load_models():
    """Models from a language_models table when DATABASE_URL is set; otherwise DEFAULT_MODELS."""
    db_url = os.getenv("DATABASE_URL", "").replace("postgres://", "postgresql://")
    if not db_url:
        return _default_models()
    from sqlalchemy import create_engine, text  # only needed with a database

    engine = create_engine(db_url)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, name, provider, adapter_class, api_config
            FROM language_models WHERE is_active = true ORDER BY provider, name
        """)).fetchall()
    models = []
    for r in rows:
        api_key = os.getenv(PROVIDER_KEY_MAP.get(r.provider.lower(), ""), "")
        if not api_key:
            continue
        endpoint = (r.api_config or {}).get("api_endpoint", "")
        if "{model_name}" in endpoint:
            endpoint = endpoint.replace("{model_name}", r.name)
        models.append({
            "id": r.id, "name": r.name, "provider": r.provider,
            "adapter": r.adapter_class, "endpoint": endpoint,
            "api_key": api_key,
            "auth_type": (r.api_config or {}).get("auth_type", "bearer"),
        })
    return models


def _call_openai(model, prompt):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {model['api_key']}"}
    payload = {"model": model["name"], "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
    resp = httpx.post(model["endpoint"], json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_anthropic(model, prompt):
    headers = {"Content-Type": "application/json", "x-api-key": model["api_key"], "anthropic-version": "2023-06-01"}
    payload = {"model": model["name"], "max_tokens": 4096, "temperature": 0.1, "messages": [{"role": "user", "content": prompt}]}
    resp = httpx.post(model["endpoint"], json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _call_google(model, prompt):
    url = f"{model['endpoint']}?key={model['api_key']}"
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1}}
    resp = httpx.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=60)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


CALLERS = {"OpenAIAdapter": _call_openai, "XAIAdapter": _call_openai, "AnthropicAdapter": _call_anthropic, "GoogleAdapter": _call_google}


def _call_model(model, prompt):
    caller = CALLERS.get(model["adapter"])
    if not caller:
        raise ValueError(f"Unknown adapter: {model['adapter']}")
    return caller(model, prompt)


_CREDENTIAL_PARAM = re.compile(r'([?&](?:key|api_key|apikey|token|access_token)=)[^&\s\'"]+', re.IGNORECASE)


def _redact_error(err) -> str:
    """Error text that is safe to store or print.

    Some providers echo the full request URL in error messages, and Google's API
    carries the key as a query parameter, so raw exception text can leak credentials.
    """
    return _CREDENTIAL_PARAM.sub(r'\1REDACTED', str(err))


# ---------- Helpers ----------

def _split_sentences(text):
    parts = re.split(r'(?<=[.!?])[\s\n]+', text)
    return [p.strip() for p in parts if p.strip()]


def _format_numbered(sentences):
    return "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences))


def _parse_claims_json(raw):
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "claims" in data:
            return data["claims"]
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return []


def _parse_assessment(raw, model):
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
        if match:
            try:
                parsed = json.loads(match.group(1))
            except json.JSONDecodeError:
                parsed = {}
        else:
            parsed = {}
    valid = {"supported", "partially_supported", "not_supported"}
    verdict = parsed.get("verdict", "error")
    if verdict not in valid:
        verdict = "error"
    return {
        "model": model["name"],
        "verdict": verdict,
        "reasoning": parsed.get("reasoning", ""),
        "sources": parsed.get("sources", []),
        "note": parsed.get("note"),
    }


def _short_name(name):
    if "opus" in name: return "opus"
    if "sonnet" in name: return "sonnet"
    if "gpt" in name: return "gpt5"
    if "grok" in name: return "grok"
    if "gemini" in name: return "gemini"
    return name[:10]


def _search_tavily(query, max_results=5):
    if not TAVILY_API_KEY:
        return []
    resp = httpx.post("https://api.tavily.com/search", json={
        "api_key": TAVILY_API_KEY, "query": query,
        "search_depth": "advanced", "max_results": max_results, "include_answer": False,
    }, timeout=15)
    resp.raise_for_status()
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "content": r.get("content", "")[:1500], "score": r.get("score", 0)}
            for r in resp.json().get("results", [])]


def _generate_queries(model, claim_text, category, article_url, article_date, source_hint):
    prompt = QUERY_GEN_PROMPT.format(
        claim_text=claim_text, category=category,
        article_url=article_url, article_date=article_date,
        source_hint=source_hint or "none",
    )
    raw = _call_model(model, prompt)
    try:
        queries = json.loads(raw)
        if isinstance(queries, list):
            return [q for q in queries if isinstance(q, str)][:2]
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
    if match:
        try:
            queries = json.loads(match.group(1))
            if isinstance(queries, list):
                return [q for q in queries if isinstance(q, str)][:2]
        except json.JSONDecodeError:
            pass
    return [claim_text]


def _search_for_claim(query_model, claim_text, category, article_url, article_date, source_hint):
    queries = _generate_queries(query_model, claim_text, category, article_url, article_date, source_hint)
    all_results = []
    seen_urls = set()
    for query in queries:
        try:
            results = _search_tavily(query, max_results=4)
        except Exception:
            continue
        for r in results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                all_results.append(r)
    all_results.sort(key=lambda r: r["score"], reverse=True)
    return all_results[:5], queries


def _format_search(results):
    return "\n".join(
        f"[Source {i}] {r['title']}\nURL: {r['url']}\nContent: {r['content']}\n"
        for i, r in enumerate(results, 1)
    )


# ---------- Model selection ----------

_cached_models = None


def _get_working_models(exclude_gemini=True):
    """Load and probe models, caching the result."""
    global _cached_models
    if _cached_models is not None:
        return _cached_models

    all_models = _load_models()
    working = []
    for model in all_models:
        if exclude_gemini and "gemini" in model["name"].lower():
            continue
        try:
            _call_model(model, "Say OK")
            working.append(model)
        except Exception:
            continue
    _cached_models = working
    return working


def _pick_query_model(models):
    """Pick the query generation model (prefer GPT-5)."""
    for m in models:
        if "gpt" in m["name"].lower():
            return m
    return models[0] if models else None


# ---------- SSE endpoint ----------

@app.get("/check")
async def check_article(url: str = Query(..., description="Article URL to check")):
    """
    SSE endpoint that progressively checks an article.

    Event stream:
      article_ready    → article text + metadata
      extraction_ready → claims list with density stats
      claim_assessed   → one event per claim with verdicts
      done             → summary stats
    """
    import asyncio

    async def _async_wrapper():
        """Wrap the sync generator to run blocking calls in a thread."""
        loop = asyncio.get_event_loop()
        gen = _check_stream(url)
        while True:
            try:
                event = await loop.run_in_executor(None, next, gen)
                yield event
            except StopIteration:
                break

    return EventSourceResponse(
        _async_wrapper(),
        media_type="text/event-stream",
    )


def _sse_event(event_type: str, data: dict) -> dict:
    return {"event": event_type, "data": json.dumps(data, default=str)}


def _check_stream(url: str):
    """Generator that yields SSE events as the pipeline progresses."""

    # --- Stage 1: Fetch article ---
    try:
        article = fetch_article(url)
    except Exception as e:
        yield _sse_event("error", {"message": f"Failed to fetch article: {e}"})
        return

    sentences = _split_sentences(article.text)

    date_match = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', url)
    article_date = (
        f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
        if date_match else datetime.now().strftime("%Y-%m-%d")
    )

    yield _sse_event("article_ready", {
        "url": article.url,
        "title": article.title,
        "author": article.author,
        "domain": article.domain,
        "article_type": article.article_type,
        "type_confidence": article.type_confidence,
        "word_count": article.word_count,
        "sentence_count": len(sentences),
        "article_date": article_date,
        "sentences": sentences,
    })

    # --- Stage 2: Extract claims ---
    models = _get_working_models()
    if not models:
        yield _sse_event("error", {"message": "No working models available"})
        return

    query_model = _pick_query_model(models)

    # Use baseline model for extraction (the one that tends to extract the most)
    extractions = {}
    for model in models:
        try:
            numbered = _format_numbered(sentences)
            claims, elapsed = _extract_claims(model, numbered)
            extractions[model["name"]] = claims
        except Exception:
            extractions[model["name"]] = []

    # Pick baseline (model with most claims)
    baseline = max(extractions, key=lambda k: len(extractions[k]))
    baseline_claims = extractions[baseline]

    if not baseline_claims:
        yield _sse_event("extraction_ready", {
            "claims_count": 0,
            "sentences_with_claims": 0,
            "claims_density": 0,
            "extraction_model": baseline,
            "claims": [],
        })
        yield _sse_event("done", {"message": "No verifiable claims found"})
        return

    # Group claims by sentence
    sentence_claims = {}
    for claim in baseline_claims:
        si = claim.get("sentence_index", -1)
        if 0 <= si < len(sentences):
            sentence_claims.setdefault(si, []).append(claim)

    total_claims = sum(len(v) for v in sentence_claims.values())
    sentences_with_claims = len(sentence_claims)

    # Build flat claims list for the extraction event
    claims_preview = []
    for si in sorted(sentence_claims.keys()):
        for claim in sentence_claims[si]:
            claims_preview.append({
                "sentence_index": si,
                "sentence_text": sentences[si],
                "claim": claim.get("claim", ""),
                "category": claim.get("category", "unknown"),
                "source_hint": claim.get("source_hint"),
            })

    yield _sse_event("extraction_ready", {
        "claims_count": total_claims,
        "sentences_with_claims": sentences_with_claims,
        "total_sentences": len(sentences),
        "claims_density": round(total_claims / len(sentences), 3) if sentences else 0,
        "extraction_model": _short_name(baseline),
        "model_counts": {_short_name(k): len(v) for k, v in extractions.items()},
        "claims": claims_preview,
    })

    # --- Stage 3: Assess each claim ---
    use_web = bool(TAVILY_API_KEY)
    claim_index = 0

    for si in sorted(sentence_claims.keys()):
        for claim in sentence_claims[si]:
            claim_text = claim.get("claim", "")
            category = claim.get("category", "unknown")
            source_hint = claim.get("source_hint", "")

            # Search
            web_results = []
            search_queries = []
            if use_web and query_model:
                try:
                    web_results, search_queries = _search_for_claim(
                        query_model, claim_text, category,
                        article_url=url, article_date=article_date,
                        source_hint=source_hint,
                    )
                except Exception:
                    pass

            # Build assessment prompt
            if web_results:
                formatted = _format_search(web_results)
                prompt = ASSESSMENT_PROMPT.format(
                    claim_text=claim_text, category=category, search_results=formatted,
                )
            else:
                prompt = (
                    f"Assess this claim: {claim_text}\n"
                    f"Category: {category}\n"
                    f"Return JSON with verdict, reasoning, sources."
                )

            # Assess with each model
            assessments = []
            for model in models:
                try:
                    t0 = time.time()
                    raw = _call_model(model, prompt)
                    elapsed = time.time() - t0
                    assessment = _parse_assessment(raw, model)
                    assessment["elapsed"] = round(elapsed, 1)
                    assessments.append(assessment)
                except Exception as e:
                    assessments.append({
                        "model": model["name"],
                        "verdict": "error",
                        "reasoning": _redact_error(e),
                        "sources": [],
                    })

            # Compute consensus
            verdicts = [a["verdict"] for a in assessments if a["verdict"] != "error"]
            if verdicts:
                from collections import Counter
                counts = Counter(verdicts)
                consensus = counts.most_common(1)[0][0]
                agreement = counts[consensus] / len(verdicts)
            else:
                consensus = "error"
                agreement = 0

            yield _sse_event("claim_assessed", {
                "claim_index": claim_index,
                "sentence_index": si,
                "sentence_text": sentences[si],
                "claim": claim_text,
                "category": category,
                "source_hint": source_hint,
                "consensus_verdict": consensus,
                "agreement": round(agreement, 2),
                "assessments": [
                    {"model": _short_name(a["model"]), "verdict": a["verdict"],
                     "reasoning": a.get("reasoning", "")}
                    for a in assessments
                ],
                "search_queries": search_queries,
                "source_count": len(web_results),
            })
            claim_index += 1

    # --- Stage 4: Done ---
    all_verdicts = []
    # Reconstruct from what we yielded
    yield _sse_event("done", {
        "total_claims": total_claims,
        "models_used": [_short_name(m["name"]) for m in models],
        "article_type": article.article_type,
    })


def _extract_claims(model, numbered_sentences):
    """Have a model extract sentence-level claims."""
    prompt = EXTRACTION_PROMPT.format(numbered_sentences=numbered_sentences)
    t0 = time.time()
    raw = _call_model(model, prompt)
    elapsed = time.time() - t0
    claims = _parse_claims_json(raw)
    return claims, elapsed
