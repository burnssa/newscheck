#!/usr/bin/env python3
"""
Batch article assessment script.

Fetches articles, extracts claims, and assesses each claim with models
selected from the superjective database (same models used in production).

Usage:
    python scripts/assess_articles.py                    # uses URLS list below
    python scripts/assess_articles.py urls.txt           # one URL per line
    python scripts/assess_articles.py <single-url>       # single article

API keys and DATABASE_URL loaded from superjective/.env
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Add parent to path so we can import newscheck
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from newscheck import fetch_article, extract_claims

# ---------- Configuration ----------

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Load API keys from superjective .env
ENV_PATH = Path(__file__).resolve().parent.parent.parent / "superjective" / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    print(f"WARNING: .env not found at {ENV_PATH}")

# Provider name → env var for API key
PROVIDER_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
}

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

ASSESSMENT_PROMPT_GROUNDED = """You are a fact-checker verifying a claim from a news article. Assess whether the claim is supported by the web sources provided below.

IMPORTANT GUIDELINES:
1. Base your assessment PRIMARILY on the web search results. You may use general knowledge only to interpret the sources.
2. A claim is "supported" if the core factual assertion is confirmed by sources, even if minor details differ (e.g., a source says "80-85%" and the claim says "85%" — that is supported, not partially supported).
3. These claims come from articles published at a specific point in time. If sources confirm the figure was accurate at any recent point, treat it as "supported" — do NOT mark a claim as unsupported just because a newer figure exists.
4. "partially_supported" means part of the claim is confirmed but another substantive part is contradicted or unverifiable. Minor rounding differences or date ranges do NOT qualify.
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
- "note": optional string — include ONLY if there is a factual caveat the reader should know (e.g., sources contradict each other, claim mixes two different statistics, search results were irrelevant). Omit this field if there is no such caveat."""

ASSESSMENT_PROMPT_UNGROUNDED = """Assess whether the following factual claim is supported by publicly available data sources.

Base your assessment ONLY on:
- Official government statistics and reports
- Published peer-reviewed research
- Well-documented reporting from established institutions
- Public records and filings

Important: Your training data has a knowledge cutoff. If this claim refers to very recent events that may have occurred after your training data, you MUST say so honestly. Use verdict "partially_supported" with a note explaining the recency limitation rather than marking a recent event "not_supported" simply because you lack data on it. Do not fabricate source references for events you cannot verify.

If you cannot assess the claim with reasonable confidence from public sources, say so.

Claim to assess:
{claim_text}

Claim category: {category}

Return ONLY valid JSON with these fields:
- "verdict": one of "supported", "partially_supported", "not_supported"
- "reasoning": 2-3 sentences explaining your assessment, citing specific data sources. If the claim may refer to events after your knowledge cutoff, state this clearly.
- "sources": array of specific public data source names that inform your assessment
- "note": optional string — include ONLY if there is a factual caveat about methodology changes, definitional ambiguity, knowledge cutoff limitations, or causal attribution that the data cannot establish. Omit this field entirely if there is no such caveat. Do not editorialize."""


# ---------- Web search via Tavily ----------

_CREDENTIAL_PARAM = re.compile(r'([?&](?:key|api_key|apikey|token|access_token)=)[^&\s\'"]+', re.IGNORECASE)


def _redact_error(err) -> str:
    """Error text that is safe to store or print.

    Some providers echo the full request URL in error messages, and Google's API
    carries the key as a query parameter, so raw exception text can leak credentials.
    """
    return _CREDENTIAL_PARAM.sub(r'\1REDACTED', str(err))


def search_claim(claim_text: str, max_results: int = 5) -> list[dict] | None:
    """Search the web for evidence about a claim using Tavily API.

    Returns list of {title, url, content, score} or None if no API key.
    """
    if not TAVILY_API_KEY:
        return None

    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": claim_text,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_answer": False,
            },
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:600],  # truncate long snippets
                "score": r.get("score", 0),
            }
            for r in results
        ]
    except Exception as e:
        print(f"    Tavily search failed: {e}")
        return None


def _format_search_results(results: list[dict]) -> str:
    """Format Tavily results into a numbered list for the prompt."""
    parts = []
    for i, r in enumerate(results, 1):
        parts.append(
            f"[Source {i}] {r['title']}\n"
            f"URL: {r['url']}\n"
            f"Content: {r['content']}\n"
        )
    return "\n".join(parts)


# ---------- DB model loading ----------

def load_models_from_db():
    """Load active models from the superjective database."""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    # SQLAlchemy needs postgresql:// not postgres://
    db_url = db_url.replace("postgres://", "postgresql://")
    engine = create_engine(db_url)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, name, provider, adapter_class, api_config
            FROM language_models
            WHERE is_active = true
            ORDER BY provider, name
        """)).fetchall()

    models = []
    for r in rows:
        api_key = os.getenv(PROVIDER_KEY_MAP.get(r.provider.lower(), ""), "")
        if not api_key:
            print(f"  Skipping {r.provider}/{r.name} — no API key")
            continue

        endpoint = (r.api_config or {}).get("api_endpoint", "")
        if "{model_name}" in endpoint:
            endpoint = endpoint.replace("{model_name}", r.name)

        models.append({
            "id": r.id,
            "name": r.name,
            "provider": r.provider,
            "adapter": r.adapter_class,
            "endpoint": endpoint,
            "api_key": api_key,
            "auth_type": (r.api_config or {}).get("auth_type", "bearer"),
        })

    return models


# ---------- API callers by adapter type ----------

def _call_openai_compatible(model: dict, prompt: str) -> str:
    """Call OpenAI-compatible API (OpenAI, xAI)."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {model['api_key']}",
    }
    payload = {
        "model": model["name"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    resp = httpx.post(model["endpoint"], json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_anthropic(model: dict, prompt: str) -> str:
    """Call Anthropic Messages API."""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": model["api_key"],
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": model["name"],
        "max_tokens": 1024,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = httpx.post(model["endpoint"], json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _call_google(model: dict, prompt: str) -> str:
    """Call Google Gemini API."""
    # Google uses API key as query param, not header
    url = f"{model['endpoint']}?key={model['api_key']}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }
    resp = httpx.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


ADAPTER_CALLERS = {
    "OpenAIAdapter": _call_openai_compatible,
    "XAIAdapter": _call_openai_compatible,
    "AnthropicAdapter": _call_anthropic,
    "GoogleAdapter": _call_google,
}


def call_model(model: dict, prompt: str) -> str:
    """Route to the correct API caller based on adapter type."""
    caller = ADAPTER_CALLERS.get(model["adapter"])
    if not caller:
        raise ValueError(f"Unknown adapter: {model['adapter']}")
    return caller(model, prompt)


# ---------- Assessment logic ----------

def _parse_assessment(raw: str, model: dict) -> dict:
    """Parse LLM response into structured assessment."""
    import re

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

    result = {
        "model_id": model["id"],
        "model_name": model["name"],
        "provider": model["provider"],
        "verdict": verdict,
        "reasoning": parsed.get("reasoning", raw[:500] if not parsed else ""),
        "sources": parsed.get("sources", []),
    }
    if parsed.get("note"):
        result["note"] = parsed["note"]

    return result


def assess_article(url: str, models: list) -> dict | None:
    """Full pipeline for one article: fetch → extract → assess → return JSON."""
    print(f"\n{'='*70}")
    print(f"URL: {url}")

    # Fetch
    try:
        article = fetch_article(url)
        print(f"  Fetched: {article.word_count} words, domain={article.domain}")
    except Exception as e:
        print(f"  FETCH FAILED: {e}")
        return None

    # Extract claims
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        print("  ERROR: OPENAI_API_KEY needed for extraction")
        return None

    try:
        extraction = extract_claims(article, api_key=openai_key, model="gpt-4o-mini")
        print(f"  Extracted {len(extraction.claims)} claims (density: {extraction.claims_density:.1%})")
    except Exception as e:
        print(f"  EXTRACTION FAILED: {e}")
        return None

    if not extraction.claims:
        print("  No claims found")
        return None

    # Assess each claim with each model
    use_web_search = bool(TAVILY_API_KEY)
    if use_web_search:
        print(f"  Web search: ENABLED (Tavily)")
    else:
        print(f"  Web search: DISABLED (set TAVILY_API_KEY to enable)")

    claims_data = []
    for i, claim in enumerate(extraction.claims):
        print(f"  Claim {i+1}/{len(extraction.claims)}: {claim.normalized[:80]}...")

        # Search the web for evidence about this claim
        web_results = None
        if use_web_search:
            web_results = search_claim(claim.normalized)
            if web_results:
                print(f"    Found {len(web_results)} web sources")
            else:
                print(f"    No web results — falling back to ungrounded")

        # Build prompt: grounded if we have search results, ungrounded otherwise
        if web_results:
            formatted = _format_search_results(web_results)
            prompt = ASSESSMENT_PROMPT_GROUNDED.format(
                claim_text=claim.normalized,
                category=claim.category,
                search_results=formatted,
            )
        else:
            prompt = ASSESSMENT_PROMPT_UNGROUNDED.format(
                claim_text=claim.normalized,
                category=claim.category,
            )

        assessments = []
        for model in models:
            try:
                t0 = time.time()
                raw = call_model(model, prompt)
                elapsed = time.time() - t0
                assessment = _parse_assessment(raw, model)
                print(f"    {model['name']}: {assessment['verdict']} ({elapsed:.1f}s)")
                assessments.append(assessment)
            except Exception as e:
                print(f"    {model['name']}: ERROR — {_redact_error(e)}")
                assessments.append({
                    "model_id": model["id"],
                    "model_name": model["name"],
                    "provider": model["provider"],
                    "verdict": "error",
                    "reasoning": _redact_error(e),
                    "sources": [],
                })

        claim_entry = {
            "quote": claim.quote,
            "normalized": claim.normalized,
            "category": claim.category,
            "char_start": claim.char_start,
            "char_end": claim.char_end,
            "assessments": assessments,
        }
        if web_results:
            claim_entry["web_sources"] = web_results
        claims_data.append(claim_entry)

    result = {
        "url": article.url,
        "title": article.title,
        "author": article.author,
        "domain": article.domain,
        "word_count": article.word_count,
        "sentence_count": article.sentence_count,
        "truncated": article.truncated,
        "extraction_model": extraction.extraction_model,
        "claims_density": extraction.claims_density,
        "web_search_enabled": use_web_search,
        "claims_count": len(claims_data),
        "assessment_models": [
            {"id": m["id"], "name": m["name"], "provider": m["provider"]}
            for m in models
        ],
        "assessed_at": datetime.now().isoformat(),
        "claims": claims_data,
    }

    # Summary stats
    for model in models:
        verdicts = []
        for c in claims_data:
            for a in c["assessments"]:
                if a["model_id"] == model["id"]:
                    verdicts.append(a["verdict"])
        supported = verdicts.count("supported")
        partial = verdicts.count("partially_supported")
        not_sup = verdicts.count("not_supported")
        errors = verdicts.count("error")
        print(f"  {model['name']}: {supported} supported, {partial} partial, {not_sup} not supported, {errors} errors")

    return result


def _model_verdicts(article: dict, model_id: int) -> list:
    """Extract verdicts for a specific model from an article result."""
    verdicts = []
    for c in article["claims"]:
        for a in c["assessments"]:
            if a["model_id"] == model_id:
                verdicts.append(a["verdict"])
    return verdicts


def _build_batch_summary(results: list, models: list) -> dict:
    """Build batch output with per-article and aggregate statistics."""
    model_ids = [m["id"] for m in models]
    model_names = {m["id"]: m["name"] for m in models}

    # Per-article summaries
    article_summaries = []
    for r in results:
        per_model = {}
        for mid in model_ids:
            verdicts = _model_verdicts(r, mid)
            non_error = [v for v in verdicts if v != "error"]
            per_model[model_names.get(mid, str(mid))] = {
                "supported": verdicts.count("supported"),
                "partially_supported": verdicts.count("partially_supported"),
                "not_supported": verdicts.count("not_supported"),
                "error": verdicts.count("error"),
                "supported_pct": verdicts.count("supported") / len(non_error) if non_error else None,
            }

        article_summaries.append({
            "url": r["url"],
            "domain": r["domain"],
            "title": r.get("title"),
            "word_count": r["word_count"],
            "sentence_count": r["sentence_count"],
            "claims_count": r["claims_count"],
            "claims_density": r["claims_density"],
            "per_model": per_model,
        })

    # Aggregate stats across all articles
    total_claims = sum(r["claims_count"] for r in results)
    total_words = sum(r["word_count"] for r in results)
    total_sentences = sum(r["sentence_count"] for r in results)
    avg_density = sum(r["claims_density"] for r in results) / len(results) if results else 0

    aggregate_per_model = {}
    for mid in model_ids:
        all_verdicts = []
        for r in results:
            all_verdicts.extend(_model_verdicts(r, mid))
        non_error = [v for v in all_verdicts if v != "error"]
        name = model_names.get(mid, str(mid))
        aggregate_per_model[name] = {
            "total_assessments": len(all_verdicts),
            "supported": all_verdicts.count("supported"),
            "partially_supported": all_verdicts.count("partially_supported"),
            "not_supported": all_verdicts.count("not_supported"),
            "error": all_verdicts.count("error"),
            "supported_pct": all_verdicts.count("supported") / len(non_error) if non_error else None,
            "not_supported_pct": all_verdicts.count("not_supported") / len(non_error) if non_error else None,
        }

    # Model agreement: how often do working models agree on verdict?
    agreement_count = 0
    comparison_count = 0
    for r in results:
        for c in r["claims"]:
            working = [a["verdict"] for a in c["assessments"] if a["verdict"] != "error"]
            if len(working) >= 2:
                comparison_count += 1
                if len(set(working)) == 1:
                    agreement_count += 1

    return {
        "batch_metadata": {
            "assessed_at": datetime.now().isoformat(),
            "articles_processed": len(results),
            "total_claims": total_claims,
            "total_words": total_words,
            "total_sentences": total_sentences,
            "avg_claims_density": avg_density,
            "avg_claims_per_article": total_claims / len(results) if results else 0,
            "model_agreement_rate": agreement_count / comparison_count if comparison_count else None,
            "agreement_comparisons": comparison_count,
        },
        "aggregate_by_model": aggregate_per_model,
        "article_summaries": article_summaries,
        "articles": results,
    }


def _print_summary(batch: dict):
    """Print a readable summary table to stdout."""
    meta = batch["batch_metadata"]
    print(f"\n{'='*80}")
    print(f"BATCH SUMMARY")
    print(f"{'='*80}")
    print(f"Articles: {meta['articles_processed']}  |  Total claims: {meta['total_claims']}  |  Total words: {meta['total_words']}")
    print(f"Avg claims/article: {meta['avg_claims_per_article']:.1f}  |  Avg density: {meta['avg_claims_density']:.1%}")
    if meta['model_agreement_rate'] is not None:
        print(f"Model agreement rate: {meta['model_agreement_rate']:.1%} ({meta['agreement_comparisons']} comparisons)")

    print(f"\n--- Aggregate by Model ---")
    print(f"{'Model':<35} {'OK':>4} {'Sup':>4} {'Part':>4} {'Not':>4} {'Err':>4} {'Sup%':>6} {'Not%':>6}")
    for name, stats in batch["aggregate_by_model"].items():
        ok = stats["total_assessments"] - stats["error"]
        sup_pct = f"{stats['supported_pct']:.0%}" if stats["supported_pct"] is not None else "N/A"
        not_pct = f"{stats['not_supported_pct']:.0%}" if stats["not_supported_pct"] is not None else "N/A"
        print(f"{name:<35} {ok:>4} {stats['supported']:>4} {stats['partially_supported']:>4} {stats['not_supported']:>4} {stats['error']:>4} {sup_pct:>6} {not_pct:>6}")

    print(f"\n--- Per Article ---")
    print(f"{'Domain':<25} {'Words':>5} {'Sent':>4} {'Claims':>6} {'Density':>8}")
    for a in batch["article_summaries"]:
        print(f"{a['domain']:<25} {a['word_count']:>5} {a['sentence_count']:>4} {a['claims_count']:>6} {a['claims_density']:>7.1%}")


def main():
    # Load models from DB
    print("Loading models from database...")
    all_models = load_models_from_db()

    if not all_models:
        print("ERROR: No models available (check API keys)")
        sys.exit(1)

    print(f"Available models: {', '.join(m['name'] for m in all_models)}")

    # Determine URLs
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg.startswith("http"):
            urls = [arg]
        elif Path(arg).exists():
            urls = [
                line.strip()
                for line in Path(arg).read_text().splitlines()
                if line.strip() and not line.startswith("#")
            ]
        else:
            print(f"Not a URL or file: {arg}")
            sys.exit(1)
    else:
        # Default list — edit these with real working URLs
        urls = [
            "https://rollcall.com/2026/03/04/trumps-big-bet-on-operation-epic-fury/",
            # Add more URLs here, one per line:
        ]

    # Probe Tavily
    if TAVILY_API_KEY:
        try:
            test = search_claim("test query", max_results=1)
            if test is not None:
                print(f"Tavily web search: OK ({len(test)} result)")
            else:
                print("Tavily web search: FAILED (no results)")
        except Exception as e:
            print(f"Tavily web search: FAILED — {e}")
    else:
        print("Tavily web search: DISABLED (set TAVILY_API_KEY in .env)")

    # Test each model with a quick probe to filter out broken keys
    working_models = []
    print("\nProbing models...")
    test_prompt = "Return only this JSON: {\"verdict\": \"supported\", \"reasoning\": \"test\", \"sources\": []}"
    for model in all_models:
        try:
            call_model(model, test_prompt)
            print(f"  {model['name']}: OK")
            working_models.append(model)
        except Exception as e:
            print(f"  {model['name']}: FAILED — {e}")

    if not working_models:
        print("ERROR: No models responded successfully")
        sys.exit(1)

    print(f"\nProcessing {len(urls)} article(s) with {len(working_models)} working models: {', '.join(m['name'] for m in working_models)}")

    results = []
    for url in urls:
        result = assess_article(url, working_models)
        if result:
            slug = result["domain"].replace(".", "_")
            filename = f"newscheck_{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = OUTPUT_DIR / filename
            with open(filepath, "w") as f:
                json.dump(result, f, indent=2)
            print(f"  Saved: {filepath}")
            results.append(result)

    if results:
        # Build batch output with summary statistics
        batch = _build_batch_summary(results, all_models)
        summary_path = OUTPUT_DIR / f"newscheck_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(summary_path, "w") as f:
            json.dump(batch, f, indent=2)
        print(f"\nBatch summary: {summary_path}")
        print(f"Processed {len(results)}/{len(urls)} articles successfully")

        # Print readable summary table
        _print_summary(batch)


if __name__ == "__main__":
    main()
