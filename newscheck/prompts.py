CLAIM_EXTRACTION_PROMPT = """You are a research analyst identifying verifiable factual claims in a news article.

A verifiable claim is a specific, falsifiable assertion about the world where public data sources (official statistics, government records, published research, documented reporting) could confirm or contradict it.

DO extract:
- Statistics and numerical claims ("unemployment fell to 3.4%")
- Historical assertions ("the lowest since 1969")
- Comparative claims ("more than 80% of the world's solar panels")
- Causal claims ("since the new policy, jobs increased by 800,000")
- Procedural claims about documented processes

DO NOT extract:
- Opinions, predictions, or subjective characterizations
- Attributed quotes (what someone said — these are claims about what was said, not about the world)
- Vague assertions without specific, checkable details ("the economy is struggling")
- Rhetorical framing

For each claim found, return:
- "quote": the exact verbatim text from the article containing the claim
- "normalized": a standalone, source-stripped restatement of just the factual assertion. Remove any reference to the publication, author, or framing. State only the checkable fact.
- "category": one of "statistical", "causal", "comparative", "historical", "procedural"

Extract ALL verifiable claims. Do not limit the number.

Return ONLY valid JSON array. No markdown, no explanation.

Article text:
{article_text}"""
