#!/usr/bin/env python3
"""
Multi-model extraction + assessment comparison (v2).

Changes from v1:
- Claims constrained to single sentences with sentence_index
- LLM-generated search queries targeting primary/authoritative sources
- Sentence-level verdict aggregation
- Tightened partially_supported criteria

Usage:
    python scripts/compare_models.py scripts/urls_v2.txt
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from newscheck import fetch_article

# ---------- Configuration ----------

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

ENV_PATH = Path(__file__).resolve().parent.parent.parent / "superjective" / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

PROVIDER_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
}

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")


# ---------- Prompts ----------

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
4. "partially_supported" is a NARROW category. Use it ONLY when part of the claim is confirmed BUT another SUBSTANTIVE part is actively contradicted or genuinely unverifiable. Example: "Company X laid off 500 workers and closed 3 factories" where sources confirm 500 layoffs but say 2 factories closed. Do NOT use partially_supported when: the core claim is confirmed but a minor detail differs, sources use slightly different wording, or numbers differ by small rounding amounts.
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

def load_models_from_db():
    db_url = os.getenv("DATABASE_URL", "").replace("postgres://", "postgresql://")
    if not db_url:
        print("ERROR: DATABASE_URL not set"); sys.exit(1)
    engine = create_engine(db_url)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, name, provider, adapter_class, api_config
            FROM language_models WHERE is_active = true ORDER BY provider, name
        """)).fetchall()
    models = []
    for r in rows:
        api_key = os.getenv(PROVIDER_KEY_MAP.get(r.provider.lower(), ""), "")
        if not api_key: continue
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


def call_model(model, prompt):
    caller = CALLERS.get(model["adapter"])
    if not caller: raise ValueError(f"Unknown adapter: {model['adapter']}")
    return caller(model, prompt)


# ---------- Sentence splitting ----------

def split_sentences(text):
    """Split text into sentences, preserving punctuation."""
    parts = re.split(r'(?<=[.!?])[\s\n]+', text)
    return [p.strip() for p in parts if p.strip()]


def format_numbered_sentences(sentences):
    """Format sentences with 0-based indices for the extraction prompt."""
    return "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences))


# ---------- Tavily + LLM query generation ----------

def search_tavily(query, max_results=5):
    """Run a single Tavily search."""
    if not TAVILY_API_KEY: return []
    try:
        resp = httpx.post("https://api.tavily.com/search", json={
            "api_key": TAVILY_API_KEY, "query": query,
            "search_depth": "advanced", "max_results": max_results, "include_answer": False,
        }, timeout=15)
        resp.raise_for_status()
        return [{"title": r.get("title", ""), "url": r.get("url", ""),
                 "content": r.get("content", "")[:1500], "score": r.get("score", 0)}
                for r in resp.json().get("results", [])]
    except Exception as e:
        print(f"      Tavily error: {e}")
        return []


def generate_search_queries(model, claim_text, category, article_url="", article_date="", source_hint=""):
    """Use an LLM to generate targeted search queries for a claim."""
    prompt = QUERY_GEN_PROMPT.format(claim_text=claim_text, category=category,
                                     article_url=article_url, article_date=article_date,
                                     source_hint=source_hint or "none")
    try:
        raw = call_model(model, prompt)
        # Try direct parse
        try:
            queries = json.loads(raw)
            if isinstance(queries, list):
                return [q for q in queries if isinstance(q, str)][:2]
        except json.JSONDecodeError:
            pass
        # Try markdown block
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
        if match:
            queries = json.loads(match.group(1))
            if isinstance(queries, list):
                return [q for q in queries if isinstance(q, str)][:2]
    except Exception:
        pass
    # Fallback: use claim text directly
    return [claim_text]


def search_with_smart_queries(query_model, claim_text, category, article_url="", article_date="", source_hint=""):
    """Generate LLM-crafted queries, search Tavily, merge and deduplicate."""
    queries = generate_search_queries(query_model, claim_text, category,
                                      article_url=article_url, article_date=article_date,
                                      source_hint=source_hint)
    all_results = []
    seen_urls = set()
    for query in queries:
        results = search_tavily(query, max_results=4)
        for r in results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                all_results.append(r)
    # Sort by score descending, take top 5
    all_results.sort(key=lambda r: r["score"], reverse=True)
    return all_results[:5], queries


def _format_search(results):
    return "\n".join(f"[Source {i}] {r['title']}\nURL: {r['url']}\nContent: {r['content']}\n"
                     for i, r in enumerate(results, 1))


# ---------- Parsing ----------

def _parse_claims_json(raw):
    """Parse LLM response into list of claim dicts."""
    try:
        data = json.loads(raw)
        if isinstance(data, list): return data
        if isinstance(data, dict) and "claims" in data: return data["claims"]
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, list): return data
            if isinstance(data, dict) and "claims" in data: return data["claims"]
        except json.JSONDecodeError:
            pass
    return []


def _parse_assessment(raw, model):
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
        if match:
            try: parsed = json.loads(match.group(1))
            except: parsed = {}
        else:
            parsed = {}
    valid = {"supported", "partially_supported", "not_supported"}
    verdict = parsed.get("verdict", "error")
    if verdict not in valid: verdict = "error"
    result = {"model_id": model["id"], "model_name": model["name"], "provider": model["provider"],
              "verdict": verdict, "reasoning": parsed.get("reasoning", raw[:500] if not parsed else ""),
              "sources": parsed.get("sources", [])}
    if parsed.get("note"): result["note"] = parsed["note"]
    return result


def _short_name(name):
    if "opus" in name: return "opus"
    if "sonnet" in name: return "sonnet"
    if "gpt" in name: return "gpt5"
    if "grok" in name: return "grok"
    if "gemini" in name: return "gemini"
    return name[:10]


# ---------- Extraction ----------

def extract_with_model(model, numbered_sentences):
    """Have a model extract sentence-level claims."""
    prompt = EXTRACTION_PROMPT.format(numbered_sentences=numbered_sentences)
    t0 = time.time()
    raw = call_model(model, prompt)
    elapsed = time.time() - t0
    claims = _parse_claims_json(raw)
    return claims, elapsed


def compute_sentence_overlap(extractions, num_sentences):
    """Compute sentence-level overlap: which sentences each model flagged."""
    model_names = list(extractions.keys())
    if len(model_names) < 2:
        return {}, {}

    model_sentences = {}
    for name, claims in extractions.items():
        flagged = set()
        for c in claims:
            si = c.get("sentence_index")
            if si is not None and 0 <= si < num_sentences:
                flagged.add(si)
        model_sentences[name] = flagged

    overlap = {}
    for i, m1 in enumerate(model_names):
        for m2 in model_names[i + 1:]:
            s1 = model_sentences[m1]
            s2 = model_sentences[m2]
            union = s1 | s2
            intersection = s1 & s2
            rate = len(intersection) / len(union) if union else 1.0
            overlap[f"{m1} vs {m2}"] = {
                "intersection": len(intersection),
                "union": len(union),
                "rate": rate,
            }

    return overlap, model_sentences


# ---------- Main pipeline ----------

def process_article(url, models, query_model):
    """Fetch, split sentences, multi-model extract, LLM-guided search, assess, aggregate."""
    print(f"\n{'=' * 70}")
    print(f"URL: {url}")

    # Fetch
    try:
        article = fetch_article(url)
        print(f"  Fetched: {article.word_count} words, {article.sentence_count} sentences, domain={article.domain}")
        print(f"  Type: {article.article_type} (confidence={article.type_confidence}, source={article.type_source})")
    except Exception as e:
        print(f"  FETCH FAILED: {e}")
        return None

    # Split into numbered sentences
    sentences = split_sentences(article.text)
    numbered = format_numbered_sentences(sentences)
    print(f"  Split into {len(sentences)} sentences")

    # Phase 1: Each model extracts claims independently
    print(f"\n  --- EXTRACTION COMPARISON ---")
    extractions = {}
    for model in models:
        short = model["name"]
        try:
            claims, elapsed = extract_with_model(model, numbered)
            extractions[short] = claims
            flagged = set()
            categories = {}
            for c in claims:
                si = c.get("sentence_index")
                if si is not None and 0 <= si < len(sentences):
                    flagged.add(si)
                cat = c.get("category", "unknown")
                categories[cat] = categories.get(cat, 0) + 1
            cat_str = ", ".join(f"{k}:{v}" for k, v in sorted(categories.items()))
            print(f"  {_short_name(short):<10} {len(claims):>3} claims in {len(flagged):>3}/{len(sentences)} sentences  ({elapsed:.1f}s)  [{cat_str}]")
        except Exception as e:
            print(f"  {_short_name(short):<10} ERROR: {e}")
            extractions[short] = []

    # Sentence-level overlap
    overlap, model_sentences = compute_sentence_overlap(extractions, len(sentences))
    if overlap:
        print(f"\n  --- SENTENCE OVERLAP (Jaccard) ---")
        for pair, stats in overlap.items():
            short_pair = " vs ".join(_short_name(p) for p in pair.split(" vs "))
            print(f"  {short_pair}: {stats['intersection']}/{stats['union']} = {stats['rate']:.0%}")

    # Phase 2: Build union claim set grouped by sentence
    baseline_model = max(extractions, key=lambda k: len(extractions[k])) if extractions else None
    if not baseline_model or not extractions[baseline_model]:
        print("  No claims extracted by any model")
        return None

    baseline_claims = extractions[baseline_model]

    # Group by sentence_index
    sentence_claims = {}
    for claim in baseline_claims:
        si = claim.get("sentence_index", -1)
        if si < 0 or si >= len(sentences):
            continue
        if si not in sentence_claims:
            sentence_claims[si] = []
        sentence_claims[si].append(claim)

    total_claims = sum(len(v) for v in sentence_claims.values())
    print(f"\n  Using {_short_name(baseline_model)} extraction ({total_claims} claims in {len(sentence_claims)} sentences) as assessment baseline")

    # Derive approximate article date from URL (look for date patterns)
    date_match = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', url)
    article_date = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}" if date_match else datetime.now().strftime("%Y-%m-%d")

    # Phase 3: Assess each claim with LLM-guided search
    print(f"\n  --- ASSESSMENT ---")
    use_web = bool(TAVILY_API_KEY)
    sentences_data = []
    claim_counter = 0

    for si in sorted(sentence_claims.keys()):
        claims_in_sentence = sentence_claims[si]
        sentence_text = sentences[si]
        print(f"\n  Sentence [{si}]: {sentence_text[:90]}{'...' if len(sentence_text) > 90 else ''}")

        sentence_result = {
            "sentence_index": si,
            "sentence_text": sentence_text,
            "claims": [],
        }

        for ci, claim in enumerate(claims_in_sentence):
            claim_counter += 1
            claim_text = claim.get("claim", claim.get("normalized", ""))
            category = claim.get("category", "unknown")
            source_hint = claim.get("source_hint", "")
            print(f"    Claim {claim_counter}: {claim_text[:75]}{'...' if len(claim_text) > 75 else ''}")
            if source_hint:
                print(f"      Source hint: {source_hint}")

            web_results = None
            search_queries = None
            if use_web:
                web_results, search_queries = search_with_smart_queries(query_model, claim_text, category,
                                                                       article_url=url, article_date=article_date,
                                                                       source_hint=source_hint)
                if web_results:
                    print(f"      Queries: {search_queries}")
                    scores = ", ".join(f"{r['score']:.2f}" for r in web_results)
                    print(f"      {len(web_results)} sources (scores: {scores})")

            if web_results:
                formatted = _format_search(web_results)
                prompt = ASSESSMENT_PROMPT.format(claim_text=claim_text, category=category, search_results=formatted)
            else:
                prompt = f"Assess this claim: {claim_text}\nCategory: {category}\nReturn JSON with verdict, reasoning, sources."

            assessments = []
            for model in models:
                try:
                    t0 = time.time()
                    raw = call_model(model, prompt)
                    elapsed = time.time() - t0
                    assessment = _parse_assessment(raw, model)
                    print(f"      {_short_name(model['name']):<8} {assessment['verdict']:<22} ({elapsed:.1f}s)")
                    assessments.append(assessment)
                except Exception as e:
                    print(f"      {model['name']}: ERROR — {e}")
                    assessments.append({"model_id": model["id"], "model_name": model["name"],
                                        "provider": model["provider"], "verdict": "error",
                                        "reasoning": str(e), "sources": []})

            claim_entry = {"claim": claim_text, "category": category, "assessments": assessments}
            if source_hint:
                claim_entry["source_hint"] = source_hint
            if web_results:
                claim_entry["web_sources"] = web_results
            if search_queries:
                claim_entry["search_queries"] = search_queries
            sentence_result["claims"].append(claim_entry)

        # Sentence-level verdict per model (worst-case across claims)
        sentence_verdicts = {}
        for model in models:
            verdicts_for_model = []
            for ce in sentence_result["claims"]:
                for a in ce["assessments"]:
                    if a["model_name"] == model["name"]:
                        verdicts_for_model.append(a["verdict"])
            if "not_supported" in verdicts_for_model:
                sentence_verdicts[model["name"]] = "not_supported"
            elif "partially_supported" in verdicts_for_model:
                sentence_verdicts[model["name"]] = "partially_supported"
            elif "supported" in verdicts_for_model:
                sentence_verdicts[model["name"]] = "supported"
            else:
                sentence_verdicts[model["name"]] = "error"

        sentence_result["sentence_verdicts"] = sentence_verdicts
        vstr = "  ".join(f"{_short_name(mn)}:{v[:3]}" for mn, v in sentence_verdicts.items())
        print(f"    → Sentence: {vstr}")

        sentences_data.append(sentence_result)

    # Build extraction summary
    extraction_summary = {}
    for name, claims in extractions.items():
        cats = {}
        flagged = set()
        for c in claims:
            cat = c.get("category", "unknown")
            cats[cat] = cats.get(cat, 0) + 1
            si = c.get("sentence_index")
            if si is not None and 0 <= si < len(sentences):
                flagged.add(si)
        extraction_summary[name] = {
            "claim_count": len(claims),
            "sentence_count": len(flagged),
            "categories": cats,
        }

    result = {
        "url": article.url, "title": article.title, "author": article.author,
        "domain": article.domain, "word_count": article.word_count,
        "article_type": article.article_type,
        "type_confidence": article.type_confidence,
        "type_source": article.type_source,
        "article_date": article_date,
        "total_sentences": len(sentences),
        "truncated": article.truncated,
        "extraction_comparison": extraction_summary,
        "sentence_overlap": overlap,
        "extraction_baseline": baseline_model,
        "assessed_sentences": len(sentences_data),
        "assessed_claims": total_claims,
        "claims_per_sentence": total_claims / len(sentences_data) if sentences_data else 0,
        "web_search_enabled": use_web,
        "query_model": query_model["name"],
        "assessment_models": [{"id": m["id"], "name": m["name"], "provider": m["provider"]} for m in models],
        "assessed_at": datetime.now().isoformat(),
        "sentences": sentences_data,
    }

    return result


# ---------- Batch summary ----------

def print_batch_summary(results, models):
    print(f"\n{'=' * 90}")
    print(f"BATCH COMPARISON SUMMARY (v2 — sentence-level)")
    print(f"{'=' * 90}")
    print(f"Articles processed: {len(results)}")

    model_names = [m["name"] for m in models]
    short_names = [_short_name(n) for n in model_names]

    # Extraction: claims and sentences per model per article
    print(f"\n--- EXTRACTION: Claims (Sentences) per Model per Article ---")
    header = f"{'Article':<25} {'Total':>5} " + " ".join(f"{s:>12}" for s in short_names)
    print(header)
    print("-" * len(header))

    for r in results:
        domain = r["domain"][:23]
        total_s = str(r["total_sentences"])
        cells = []
        for mn in model_names:
            ec = r["extraction_comparison"].get(mn, {})
            cc = ec.get("claim_count", 0)
            sc = ec.get("sentence_count", 0)
            cells.append(f"{cc}({sc})")
        print(f"{domain:<25} {total_s:>5} " + " ".join(f"{c:>12}" for c in cells))

    # Totals
    totals_claims = {mn: 0 for mn in model_names}
    totals_sents = {mn: 0 for mn in model_names}
    total_article_sents = 0
    for r in results:
        total_article_sents += r["total_sentences"]
        for mn in model_names:
            ec = r["extraction_comparison"].get(mn, {})
            totals_claims[mn] += ec.get("claim_count", 0)
            totals_sents[mn] += ec.get("sentence_count", 0)
    print("-" * len(header))
    cells = [f"{totals_claims[mn]}({totals_sents[mn]})" for mn in model_names]
    print(f"{'TOTAL':<25} {total_article_sents:>5} " + " ".join(f"{c:>12}" for c in cells))

    # Sentence overlap averages
    all_overlaps = {}
    for r in results:
        for pair, stats in r.get("sentence_overlap", {}).items():
            short_pair = " vs ".join(_short_name(p) for p in pair.split(" vs "))
            if short_pair not in all_overlaps:
                all_overlaps[short_pair] = []
            all_overlaps[short_pair].append(stats["rate"])
    if all_overlaps:
        print(f"\n--- SENTENCE OVERLAP (avg Jaccard across articles) ---")
        for pair, rates in sorted(all_overlaps.items()):
            avg = sum(rates) / len(rates)
            print(f"  {pair}: {avg:.0%}")

    # Sentence-level verdict distribution
    print(f"\n--- SENTENCE-LEVEL VERDICT DISTRIBUTION ---")
    model_sent_verdicts = {mn: {"supported": 0, "partially_supported": 0, "not_supported": 0, "error": 0} for mn in model_names}
    total_assessed_sentences = 0
    for r in results:
        for s in r["sentences"]:
            total_assessed_sentences += 1
            for mn in model_names:
                v = s.get("sentence_verdicts", {}).get(mn, "error")
                model_sent_verdicts[mn][v] = model_sent_verdicts[mn].get(v, 0) + 1

    print(f"Total sentences assessed: {total_assessed_sentences}")
    print(f"\n{'Model':<10} {'Sup':>4} {'Part':>4} {'Not':>4} {'Err':>4} {'Sup%':>6} {'Not%':>6}")
    for mn in model_names:
        v = model_sent_verdicts[mn]
        ok = v["supported"] + v["partially_supported"] + v["not_supported"]
        sup_pct = f"{v['supported'] / ok:.0%}" if ok else "N/A"
        not_pct = f"{v['not_supported'] / ok:.0%}" if ok else "N/A"
        print(f"{_short_name(mn):<10} {v['supported']:>4} {v['partially_supported']:>4} {v['not_supported']:>4} {v['error']:>4} {sup_pct:>6} {not_pct:>6}")

    # Claim-level verdict distribution
    print(f"\n--- CLAIM-LEVEL VERDICT DISTRIBUTION ---")
    model_claim_verdicts = {mn: {"supported": 0, "partially_supported": 0, "not_supported": 0, "error": 0} for mn in model_names}
    total_assessed_claims = 0
    for r in results:
        for s in r["sentences"]:
            for c in s["claims"]:
                total_assessed_claims += 1
                for a in c["assessments"]:
                    if a["model_name"] in model_claim_verdicts:
                        v = a["verdict"]
                        model_claim_verdicts[a["model_name"]][v] = model_claim_verdicts[a["model_name"]].get(v, 0) + 1

    print(f"Total claims assessed: {total_assessed_claims}")
    print(f"\n{'Model':<10} {'Sup':>4} {'Part':>4} {'Not':>4} {'Err':>4} {'Sup%':>6} {'Not%':>6}")
    for mn in model_names:
        v = model_claim_verdicts[mn]
        ok = v["supported"] + v["partially_supported"] + v["not_supported"]
        sup_pct = f"{v['supported'] / ok:.0%}" if ok else "N/A"
        not_pct = f"{v['not_supported'] / ok:.0%}" if ok else "N/A"
        print(f"{_short_name(mn):<10} {v['supported']:>4} {v['partially_supported']:>4} {v['not_supported']:>4} {v['error']:>4} {sup_pct:>6} {not_pct:>6}")

    # Sentence-level agreement rate
    sent_agreement = sent_comparisons = 0
    for r in results:
        for s in r["sentences"]:
            working = [v for v in s.get("sentence_verdicts", {}).values() if v != "error"]
            if len(working) >= 2:
                sent_comparisons += 1
                if len(set(working)) == 1:
                    sent_agreement += 1
    if sent_comparisons:
        print(f"\nSentence agreement rate: {sent_agreement / sent_comparisons:.1%} ({sent_agreement}/{sent_comparisons})")

    # Claim-level agreement rate
    claim_agreement = claim_comparisons = 0
    for r in results:
        for s in r["sentences"]:
            for c in s["claims"]:
                working = [a["verdict"] for a in c["assessments"] if a["verdict"] != "error"]
                if len(working) >= 2:
                    claim_comparisons += 1
                    if len(set(working)) == 1:
                        claim_agreement += 1
    if claim_comparisons:
        print(f"Claim agreement rate: {claim_agreement / claim_comparisons:.1%} ({claim_agreement}/{claim_comparisons})")


# ---------- Markdown summary ----------

def write_batch_markdown(results, models, md_path):
    """Write a human-readable markdown batch summary."""
    model_names = [m["name"] for m in models]
    short_names = [_short_name(n) for n in model_names]
    lines = []
    w = lines.append

    w(f"# Newscheck Batch Summary")
    w(f"")
    w(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    w(f"**Version:** v2 (sentence-level, primary-source queries)")
    w(f"**Articles processed:** {len(results)}")
    w(f"**Models:** {', '.join(short_names)}")
    query_model = results[0].get("query_model", "unknown") if results else "unknown"
    w(f"**Query generation model:** {_short_name(query_model)}")
    w("")

    # --- Extraction summary table ---
    w("## Extraction Summary")
    w("")
    w("Claims per model with (sentences containing claims) in parentheses.")
    w("")
    header = f"| Article | Sentences | " + " | ".join(short_names) + " |"
    sep = f"|---------|-----------|" + "|".join("-" * (len(s) + 2) for s in short_names) + "|"
    w(header)
    w(sep)

    total_sents = 0
    total_claims = {mn: 0 for mn in model_names}
    total_flagged = {mn: 0 for mn in model_names}
    for r in results:
        domain = r["domain"]
        total_s = r["total_sentences"]
        total_sents += total_s
        cells = []
        for mn in model_names:
            ec = r["extraction_comparison"].get(mn, {})
            cc = ec.get("claim_count", 0)
            sc = ec.get("sentence_count", 0)
            total_claims[mn] += cc
            total_flagged[mn] += sc
            cells.append(f"{cc} ({sc})")
        w(f"| {domain} | {total_s} | " + " | ".join(cells) + " |")

    totals = [f"**{total_claims[mn]}** ({total_flagged[mn]})" for mn in model_names]
    w(f"| **TOTAL** | **{total_sents}** | " + " | ".join(totals) + " |")
    w("")

    # --- Sentence overlap ---
    all_overlaps = {}
    for r in results:
        for pair, stats in r.get("sentence_overlap", {}).items():
            short_pair = " vs ".join(_short_name(p) for p in pair.split(" vs "))
            if short_pair not in all_overlaps:
                all_overlaps[short_pair] = []
            all_overlaps[short_pair].append(stats["rate"])
    if all_overlaps:
        w("## Sentence Overlap (avg Jaccard)")
        w("")
        w("| Model Pair | Avg Overlap |")
        w("|------------|-------------|")
        for pair, rates in sorted(all_overlaps.items()):
            avg = sum(rates) / len(rates)
            w(f"| {pair} | {avg:.0%} |")
        w("")

    # --- Verdict distribution ---
    model_sent_verdicts = {mn: {"supported": 0, "partially_supported": 0, "not_supported": 0, "error": 0} for mn in model_names}
    model_claim_verdicts = {mn: {"supported": 0, "partially_supported": 0, "not_supported": 0, "error": 0} for mn in model_names}
    total_assessed_sentences = 0
    total_assessed_claims = 0

    for r in results:
        for s in r["sentences"]:
            total_assessed_sentences += 1
            for mn in model_names:
                v = s.get("sentence_verdicts", {}).get(mn, "error")
                model_sent_verdicts[mn][v] = model_sent_verdicts[mn].get(v, 0) + 1
            for c in s["claims"]:
                total_assessed_claims += 1
                for a in c["assessments"]:
                    if a["model_name"] in model_claim_verdicts:
                        v = a["verdict"]
                        model_claim_verdicts[a["model_name"]][v] = model_claim_verdicts[a["model_name"]].get(v, 0) + 1

    w("## Verdict Distribution")
    w("")
    w(f"### Sentence-Level ({total_assessed_sentences} sentences assessed)")
    w("")
    w("| Model | Supported | Partial | Not Supported | Error | Sup% | Not% |")
    w("|-------|-----------|---------|---------------|-------|------|------|")
    for mn in model_names:
        v = model_sent_verdicts[mn]
        ok = v["supported"] + v["partially_supported"] + v["not_supported"]
        sup_pct = f"{v['supported'] / ok:.0%}" if ok else "N/A"
        not_pct = f"{v['not_supported'] / ok:.0%}" if ok else "N/A"
        w(f"| {_short_name(mn)} | {v['supported']} | {v['partially_supported']} | {v['not_supported']} | {v['error']} | {sup_pct} | {not_pct} |")
    w("")

    w(f"### Claim-Level ({total_assessed_claims} claims assessed)")
    w("")
    w("| Model | Supported | Partial | Not Supported | Error | Sup% | Not% |")
    w("|-------|-----------|---------|---------------|-------|------|------|")
    for mn in model_names:
        v = model_claim_verdicts[mn]
        ok = v["supported"] + v["partially_supported"] + v["not_supported"]
        sup_pct = f"{v['supported'] / ok:.0%}" if ok else "N/A"
        not_pct = f"{v['not_supported'] / ok:.0%}" if ok else "N/A"
        w(f"| {_short_name(mn)} | {v['supported']} | {v['partially_supported']} | {v['not_supported']} | {v['error']} | {sup_pct} | {not_pct} |")
    w("")

    # --- Agreement ---
    sent_agreement = sent_comparisons = 0
    claim_agreement = claim_comparisons = 0
    for r in results:
        for s in r["sentences"]:
            working = [v for v in s.get("sentence_verdicts", {}).values() if v != "error"]
            if len(working) >= 2:
                sent_comparisons += 1
                if len(set(working)) == 1:
                    sent_agreement += 1
            for c in s["claims"]:
                cw = [a["verdict"] for a in c["assessments"] if a["verdict"] != "error"]
                if len(cw) >= 2:
                    claim_comparisons += 1
                    if len(set(cw)) == 1:
                        claim_agreement += 1

    w("## Agreement")
    w("")
    if sent_comparisons:
        w(f"- **Sentence agreement:** {sent_agreement / sent_comparisons:.1%} ({sent_agreement}/{sent_comparisons})")
    if claim_comparisons:
        w(f"- **Claim agreement:** {claim_agreement / claim_comparisons:.1%} ({claim_agreement}/{claim_comparisons})")
    w("")

    # --- Per-article detail ---
    w("## Per-Article Results")
    w("")
    for r in results:
        w(f"### {r['domain']}")
        w("")
        w(f"- **URL:** {r['url']}")
        article_type = r.get('article_type', 'unknown')
        type_conf = r.get('type_confidence', '')
        w(f"- **Type:** {article_type} ({type_conf}) | **Words:** {r['word_count']} | **Sentences:** {r['total_sentences']} | **Date:** {r.get('article_date', 'unknown')}")
        assessed = r.get("assessed_claims", 0)
        assessed_s = r.get("assessed_sentences", 0)
        w(f"- **Claims assessed:** {assessed} across {assessed_s} sentences (baseline: {_short_name(r.get('extraction_baseline', 'unknown'))})")
        w("")

        if r["sentences"]:
            w("| # | Sentence (truncated) | Claim | " + " | ".join(short_names) + " |")
            w("|---|---------------------|-------|" + "|".join("---" for _ in short_names) + "|")
            for s in r["sentences"]:
                si = s["sentence_index"]
                sent_short = s["sentence_text"][:60].replace("|", "\\|") + ("..." if len(s["sentence_text"]) > 60 else "")
                for ci, c in enumerate(s["claims"]):
                    claim_short = c["claim"][:60].replace("|", "\\|") + ("..." if len(c["claim"]) > 60 else "")
                    verdicts = []
                    for mn in model_names:
                        v = next((a["verdict"] for a in c["assessments"] if a["model_name"] == mn), "—")
                        symbol = {"supported": "sup", "partially_supported": "par", "not_supported": "not", "error": "err"}.get(v, "—")
                        verdicts.append(symbol)
                    sent_col = sent_short if ci == 0 else ""
                    si_col = str(si) if ci == 0 else ""
                    w(f"| {si_col} | {sent_col} | {claim_short} | " + " | ".join(verdicts) + " |")
            w("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Markdown summary: {md_path}")


# ---------- Main ----------

def main():
    print("Loading models from database...")
    all_models = load_models_from_db()
    if not all_models:
        print("ERROR: No models available"); sys.exit(1)
    print(f"Available: {', '.join(m['name'] for m in all_models)}")

    # URLs
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg.startswith("http"):
            urls = [arg]
        elif Path(arg).exists():
            urls = [l.strip() for l in Path(arg).read_text().splitlines() if l.strip() and not l.startswith("#")]
        else:
            print(f"Not a URL or file: {arg}"); sys.exit(1)
    else:
        print("Usage: python compare_models.py <urls.txt or URL>"); sys.exit(1)

    # Probe Tavily
    if TAVILY_API_KEY:
        try:
            test = search_tavily("test query", max_results=1)
            print(f"Tavily: OK" if test else "Tavily: no results")
        except Exception as e:
            print(f"Tavily: FAILED — {e}")
    else:
        print("Tavily: DISABLED")

    # Probe models
    working = []
    print("\nProbing models...")
    for model in all_models:
        try:
            call_model(model, 'Return only: {"verdict":"supported","reasoning":"test","sources":[]}')
            print(f"  {model['name']}: OK")
            working.append(model)
        except Exception as e:
            print(f"  {model['name']}: FAILED — {e}")

    if not working:
        print("ERROR: No models available"); sys.exit(1)

    # Pick the fastest model for query generation (prefer GPT-5 > Grok > Sonnet > Opus)
    query_model = working[0]
    for m in working:
        if "gpt" in m["name"]:
            query_model = m
            break
    print(f"\nQuery generation model: {query_model['name']}")
    print(f"Processing {len(urls)} articles with {len(working)} models")

    results = []
    for url in urls:
        result = process_article(url, working, query_model)
        if result:
            slug = result["domain"].replace(".", "_")
            filename = f"compare_v2_{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = OUTPUT_DIR / filename
            with open(filepath, "w") as f:
                json.dump(result, f, indent=2)
            print(f"  Saved: {filepath}")
            results.append(result)

    if results:
        batch = {"batch_metadata": {"assessed_at": datetime.now().isoformat(),
                                     "version": "v2_sentence_level",
                                     "articles": len(results),
                                     "models": [m["name"] for m in working],
                                     "query_model": query_model["name"]},
                 "articles": results}
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        summary_path = OUTPUT_DIR / f"compare_v2_batch_{ts}.json"
        with open(summary_path, "w") as f:
            json.dump(batch, f, indent=2)
        print(f"\nBatch: {summary_path}")
        md_path = OUTPUT_DIR / f"compare_v2_batch_{ts}.md"
        write_batch_markdown(results, working, md_path)
        print_batch_summary(results, working)


if __name__ == "__main__":
    main()
