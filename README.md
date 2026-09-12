# newscheck

Open-source claim extraction for news articles and opinion pieces.

Newscheck was built to support automated, multi-model validation of the factual claims in news and opinion writing. This package is the first stage of that pipeline: fetch an article, classify it as news or opinion, and extract every verifiable claim as structured data. The second stage, in which several LLMs independently assessed each claim, ran inside [Superjective](https://superjective.ai) and is not part of this package.

The approach follows [GPT as a Measurement Tool](https://cdn.openai.com/pdf/7517a586-5bfa-4b87-bd3d-6ea0e9e844c7/GPT-as-a-measurement-tool.pdf) (Asirvatham, Mokski, and Shleifer, NBER Working Paper 34834, 2026) and OpenAI's companion [GABRIEL](https://github.com/openai/GABRIEL) toolkit: treat an LLM as a measurement instrument for quantitative social science. Here the attribute being measured is whether a sentence makes a claim that a named public source could confirm or refute.

## What it does

- `fetch_article(url)` downloads and cleans the article text with trafilatura, keeps title and author, and truncates long pieces at a sentence boundary.
- `classify_article(url, html)` labels a piece as opinion or news from URL patterns and HTML metadata, returning a confidence and the tier that decided it.
- `extract_claims(article, api_key, model=...)` asks an OpenAI-compatible model for every verifiable claim and returns the verbatim quote, a source-stripped restatement, a category (statistical, causal, comparative, historical, procedural), and the claim's position in the text. Opinions, predictions, attributed quotes, and slogans are excluded by design. The prompt is in `newscheck/prompts.py`.

## Usage

```python
from newscheck import fetch_article, extract_claims

article = fetch_article("https://example.com/some-article")
result = extract_claims(article, api_key="sk-...", model="gpt-4o-mini")

print(article.article_type, article.type_confidence)
for claim in result.claims:
    print(claim.category, "|", claim.normalized)
```

Any OpenAI-compatible endpoint works. Pass `base_url` to `extract_claims` to use another provider.

## Install

```
pip install git+https://github.com/burnssa/newscheck.git
```

Requires Python 3.10 or later.

## Run the server

The streaming checker in `newscheck/api.py` fetches an article, extracts claims, assesses each one against web search results with several models, and streams the results as server-sent events.

```
pip install "newscheck[server] @ git+https://github.com/burnssa/newscheck.git"
export OPENAI_API_KEY=... ANTHROPIC_API_KEY=... XAI_API_KEY=... TAVILY_API_KEY=...
uvicorn newscheck.api:app
curl -N "http://127.0.0.1:8000/check?url=https://example.com/some-article"
```

Only providers whose key is set are used. A `.env` file in the working directory is read automatically. The Tavily key is needed for the web search step. Setting `DATABASE_URL` to a Postgres database with a `language_models` table swaps the built-in model list for that table.

## Status

The hosted Newscheck page and its multi-model assessment layer were retired in September 2026 along with Superjective. This package works on its own and is not under active development.

## License

MIT
