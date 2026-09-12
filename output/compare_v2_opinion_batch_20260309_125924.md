# Newscheck Batch Summary

**Date:** 2026-03-09 12:59
**Version:** v2 (sentence-level, primary-source queries)
**Articles processed:** 8
**Models:** opus, sonnet, gpt5, grok
**Query generation model:** gpt5

## Extraction Summary

Claims per model with (sentences containing claims) in parentheses.

| Article | Sentences | opus | sonnet | gpt5 | grok |
|---------|-----------|------|--------|------|------|
| www.foxnews.com | 62 | 17 (13) | 14 (12) | 13 (12) | 22 (14) |
| www.washingtonexaminer.com | 37 | 8 (5) | 8 (5) | 8 (5) | 14 (7) |
| www.aljazeera.com | 42 | 10 (6) | 9 (6) | 13 (9) | 16 (11) |
| www.aljazeera.com | 56 | 10 (8) | 9 (8) | 14 (10) | 12 (9) |
| thehill.com | 24 | 8 (7) | 8 (7) | 8 (7) | 9 (8) |
| thehill.com | 46 | 1 (1) | 1 (1) | 1 (1) | 1 (1) |
| thehill.com | 36 | 6 (6) | 6 (6) | 6 (6) | 8 (8) |
| thehill.com | 42 | 5 (3) | 5 (3) | 5 (3) | 5 (3) |
| **TOTAL** | **345** | **65** (49) | **60** (48) | **68** (53) | **87** (61) |

## Sentence Overlap (avg Jaccard)

| Model Pair | Avg Overlap |
|------------|-------------|
| gemini vs gpt5 | 0% |
| gemini vs grok | 0% |
| gpt5 vs grok | 86% |
| opus vs gemini | 0% |
| opus vs gpt5 | 89% |
| opus vs grok | 82% |
| opus vs sonnet | 99% |
| sonnet vs gemini | 0% |
| sonnet vs gpt5 | 90% |
| sonnet vs grok | 83% |

## Verdict Distribution

### Sentence-Level (62 sentences assessed)

| Model | Supported | Partial | Not Supported | Error | Sup% | Not% |
|-------|-----------|---------|---------------|-------|------|------|
| opus | 17 | 13 | 32 | 0 | 27% | 52% |
| sonnet | 32 | 0 | 30 | 0 | 52% | 48% |
| gpt5 | 36 | 1 | 25 | 0 | 58% | 40% |
| grok | 31 | 2 | 29 | 0 | 50% | 47% |

### Claim-Level (89 claims assessed)

| Model | Supported | Partial | Not Supported | Error | Sup% | Not% |
|-------|-----------|---------|---------------|-------|------|------|
| opus | 37 | 16 | 36 | 0 | 42% | 40% |
| sonnet | 55 | 0 | 34 | 0 | 62% | 38% |
| gpt5 | 59 | 1 | 29 | 0 | 66% | 33% |
| grok | 53 | 2 | 34 | 0 | 60% | 38% |

## Agreement

- **Sentence agreement:** 48.4% (30/62)
- **Claim agreement:** 58.4% (52/89)

## Per-Article Results

### www.foxnews.com

- **URL:** https://www.foxnews.com/opinion/not-coming-america-60-year-immigration-bubble-finally-bursts
- **Type:** opinion (high) | **Words:** 1011 | **Sentences:** 62 | **Date:** 2026-03-09
- **Claims assessed:** 22 across 14 sentences (baseline: grok)

| # | Sentence (truncated) | Claim | opus | sonnet | gpt5 | grok |
|---|---------------------|-------|---|---|---|---|
| 9 | A speculative market frenzy in tech stocks caused the tech-h... | The Nasdaq Composite Index rose from under 1,000 in 1995 to ... | sup | sup | sup | not |
| 10 | By October 2002, the Nasdaq had fallen to just over 1,000 ag... | By October 2002, the Nasdaq Composite Index had fallen to ju... | par | not | sup | not |
| 14 | Annual appreciation rates reached 15–17% in 2004 and 2005. | Annual housing appreciation rates reached 15–17% in 2004 and... | not | not | sup | not |
| 15 | Meanwhile, the Federal Reserve lowered interest rates from 6... | The Federal Reserve lowered interest rates from 6.5% in 2000... | sup | sup | sup | sup |
| 27 | government has annually granted lawful permanent resident st... | The U.S. government has annually granted lawful permanent re... | par | sup | sup | not |
|  |  | Approximately 75% of lawful permanent resident statuses gran... | not | not | not | not |
|  |  | Approximately 20% of lawful permanent resident statuses gran... | not | not | not | not |
| 30 | Border Patrol apprehended over 201,000 illegal aliens along ... | The U.S. Border Patrol apprehended over 201,000 illegal alie... | not | not | not | not |
| 31 | That number consistently rose each year, first reaching over... | U.S. Border Patrol apprehensions first reached over 1 millio... | not | not | not | not |
|  |  | U.S. Border Patrol apprehensions consistently exceeded 1 mil... | not | sup | sup | sup |
| 32 | The annual number of encounters ranged from over 300,000 to ... | The annual number of U.S. Border Patrol encounters ranged fr... | sup | sup | sup | sup |
|  |  | There were over 7 million U.S. Border Patrol encounters in f... | sup | sup | sup | not |
| 41 | The Biden administration annually paid tens of billions in f... | The Biden administration annually paid tens of billions in f... | par | not | not | sup |
| 48 | Census Bureau just released its new population estimates, wh... | The U.S. Census Bureau released new population estimates. | sup | sup | sup | sup |
| 49 | It reports that NIM peaked at 2.7 million in 2024, declined ... | Net international migration to the U.S. peaked at 2.7 millio... | par | sup | sup | par |
|  |  | Net international migration to the U.S. declined to 1.3 mill... | sup | sup | sup | sup |
|  |  | Net international migration to the U.S. is projected to furt... | not | sup | not | sup |
| 50 | Brookings estimates net migration in 2025 ranged from negati... | Brookings estimates net migration in 2025 ranged from negati... | par | sup | sup | sup |
|  |  | Net migration to the U.S. has been negative for the first ti... | sup | sup | sup | sup |
| 52 | Pew Research reported that 53.3 million aliens lived in the ... | Pew Research reported that 53.3 million aliens lived in the ... | par | not | sup | sup |
| 54 | By June, that number decreased to 51.9 million, the first de... | The number of aliens living in the U.S. decreased to 51.9 mi... | not | not | not | not |
|  |  | The number of aliens living in the U.S. first declined since... | sup | sup | sup | sup |

### www.washingtonexaminer.com

- **URL:** https://www.washingtonexaminer.com/opinion/4480367/when-7oh-fears-drive-policy-by-anecdote-kratom/
- **Type:** opinion (high) | **Words:** 753 | **Sentences:** 37 | **Date:** 2026-03-09
- **Claims assessed:** 14 across 7 sentences (baseline: grok)

| # | Sentence (truncated) | Claim | opus | sonnet | gpt5 | grok |
|---|---------------------|-------|---|---|---|---|
| 7 | announced plans to urge the Drug Enforcement Administration ... | Drug Enforcement Administration plans to place 7-OH in Sched... | par | not | sup | sup |
| 12 | Roughly two-thirds of decedents had fentanyl in their system... | Roughly two-thirds of decedents had fentanyl in their system... | not | sup | not | sup |
| 13 | About one-third had heroin present, and just under one-fifth... | About one-third had heroin present. | not | sup | sup | sup |
|  |  | Just under one-fifth had prescription opioids or cocaine. | sup | sup | sup | sup |
| 14 | Around 80% had documented histories of substance misuse, and... | Around 80% had documented histories of substance misuse. | sup | sup | sup | sup |
|  |  | About 90% were not receiving clinical care for pain. | not | not | not | not |
| 21 | Tennessee’s Matthew Davenport’s Law “establishes criminal pe... | Tennessee’s Matthew Davenport’s Law establishes criminal pen... | sup | sup | sup | sup |
| 22 | Jared Polis (D-CO) signed the Daniel Bregger Act, which bans... | Colorado Gov. Jared Polis signed the Daniel Bregger Act on M... | not | not | not | not |
|  |  | Daniel Bregger Act bans the sale or marketing of kratom prod... | sup | sup | sup | sup |
|  |  | Daniel Bregger Act prohibits kratom products that exceed spe... | sup | sup | sup | sup |
|  |  | Daniel Bregger Act prohibits kratom products intended for va... | sup | sup | sup | sup |
|  |  | Daniel Bregger Act prohibits kratom products that contain mo... | sup | sup | sup | sup |
| 26 | Although Michigan’s House Bill 4969 — which aims to ban 7-OH... | Dakota Herrera was aged 27. | not | not | not | not |
|  |  | Michigan’s House Bill 4969 aims to ban 7-OH. | par | not | not | sup |

### www.aljazeera.com

- **URL:** https://www.aljazeera.com/opinions/2026/2/24/three-myths-about-the-russia-economic-war
- **Type:** opinion (high) | **Words:** 1112 | **Sentences:** 42 | **Date:** 2026-02-24
- **Claims assessed:** 16 across 11 sentences (baseline: grok)

| # | Sentence (truncated) | Claim | opus | sonnet | gpt5 | grok |
|---|---------------------|-------|---|---|---|---|
| 1 | This is a cost borne mostly by Ukraine: The World Bank now e... | The World Bank estimates the cost of reconstruction in Ukrai... | par | sup | sup | sup |
|  |  | The $588bn reconstruction cost is nearly three times Ukraine... | sup | sup | sup | sup |
| 11 | Before the war, Russia sold roughly 150 billion cubic metres... | Before the war, Russia sold roughly 150 billion cubic metres... | sup | sup | sup | not |
|  |  | Russia’s gas sales to the EU are down to 38 bcm annually. | not | not | not | not |
| 12 | Based on the recent prices for European gas futures, every b... | Every billion cubic metres of European gas is worth more tha... | not | not | not | not |
|  |  | Russia is losing out on as much as 34 billion euros ($40bn) ... | not | not | not | not |
| 13 | That sum will increase next year when EU countries will phas... | EU countries will phase out completely Russian gas imports n... | not | not | not | not |
| 14 | Approximately $335bn in Russian sovereign assets remain froz... | Approximately $335bn in Russian sovereign assets remain froz... | not | sup | sup | sup |
| 21 | Since Washington imposed sweeping sanctions on Russia’s two ... | Washington imposed sweeping sanctions on Russia’s two larges... | sup | sup | sup | not |
| 27 | Therefore, even as the geopolitical risk premium driven by T... | The benchmark Brent oil price has reached more than $70 per ... | sup | sup | sup | sup |
|  |  | Russia has had to offer discounts of as much as $30 per barr... | sup | sup | sup | sup |
| 31 | In the latter case, the country’s second-largest refinery, V... | Vadinar, India’s second-largest refinery, which is part-owne... | par | sup | sup | sup |
| 32 | Europe is currently preparing its 20th sanctions package and... | Europe is currently preparing its 20th sanctions package. | not | not | not | sup |
| 33 | That process, however, as well as the crucial 90-billion-eur... | Brussels agreed to provide Kyiv a 90-billion-euro ($106bn) l... | par | sup | sup | not |
|  |  | Hungary extended its veto on the eve of the invasion’s anniv... | sup | sup | sup | sup |
| 36 | In fact, the 90-billion-euro loan plan was itself thrown tog... | The 90-billion-euro loan plan was thrown together at the las... | not | sup | sup | sup |

### www.aljazeera.com

- **URL:** https://www.aljazeera.com/opinions/2026/3/4/the-iran-strikes-could-become-a-midterm-reckoning-for-trump-and-israel
- **Type:** opinion (high) | **Words:** 1303 | **Sentences:** 56 | **Date:** 2026-03-04
- **Claims assessed:** 14 across 10 sentences (baseline: gpt5)

| # | Sentence (truncated) | Claim | opus | sonnet | gpt5 | grok |
|---|---------------------|-------|---|---|---|---|
| 6 | The stakes for Republicans are high: All 435 seats in the US... | All 435 seats in the US House of Representatives will be on ... | sup | sup | sup | sup |
|  |  | 35 of 100 Senate seats will be on the ballot in the 2026 mid... | not | not | sup | sup |
|  |  | Republicans currently control both chambers of Congress. | sup | sup | sup | sup |
| 31 | A Reuters news agency poll conducted after the start of mili... | A Reuters poll conducted after the start of military operati... | sup | sup | sup | sup |
| 32 | More concerning for Trump, perhaps, is that only 55 percent ... | 55 percent of Republicans approve of Trump's decision to go ... | par | sup | sup | sup |
| 33 | This is a remarkably low figure, especially in comparison wi... | George W. Bush had more than 90 percent Republican support f... | sup | sup | not | sup |
| 35 | All members of the House face voters every two years, and th... | All members of the US House of Representatives face voters e... | sup | sup | sup | sup |
|  |  | The president’s party almost always loses seats in midterm c... | sup | sup | sup | sup |
| 36 | Trump, whose approval rating has hovered between 36 percent ... | Trump’s approval rating has hovered between 36 percent and 3... | sup | sup | sup | sup |
|  |  | Trump is the first president ever with a sub-50 percent appr... | not | sup | sup | not |
| 38 | In 2025, Democratic candidates racked up a series of victori... | In 2025, Democratic candidates swept gubernatorial races and... | par | not | par | par |
| 40 | For decades, Americans have sympathised much more with Israe... | Between 2001 and 2018, Israelis held a 43 percent advantage ... | sup | sup | sup | sup |
| 41 | Last week, however, a Gallup poll suggested – for the first ... | A Gallup poll conducted last week found that American sympat... | sup | not | sup | sup |
| 43 | Since 2024, support for Israel has declined by 10 percent am... | Since 2024, support for Israel has declined by 10 percent am... | sup | sup | sup | sup |

### thehill.com

- **URL:** https://thehill.com/opinion/lindseys-lens/5732057-trump-immigration-crackdown-data/
- **Type:** opinion (high) | **Words:** 473 | **Sentences:** 24 | **Date:** 2026-03-09
- **Claims assessed:** 9 across 8 sentences (baseline: grok)

| # | Sentence (truncated) | Claim | opus | sonnet | gpt5 | grok |
|---|---------------------|-------|---|---|---|---|
| 2 | ICE made roughly 393,000 arrests between Jan. | ICE made roughly 393,000 arrests between Jan. 21, 2025, and ... | not | not | not | not |
| 4 | That’s more than triple the number of administrative arrests... | The number of administrative arrests in fiscal 2024 was less... | not | sup | sup | sup |
| 6 | But here’s the part that stood out to me: less than 14 perce... | Less than 14 percent of those arrested had charges or convic... | not | sup | sup | sup |
| 7 | Take a listen to a bit of the reporting:
“The president, for... | 2 percent of the people arrested by ICE have been charged or... | not | not | not | not |
|  |  | 2 percent of the people arrested by ICE were identified as g... | not | not | not | not |
| 8 | The numbers really illustrate that the Trump administrations... | Nearly 40 percent of those arrested had no criminal record a... | not | not | not | not |
| 13 | A CBS News poll found support for Trump’s deportation effort... | A CBS News poll found support for Trump’s deportation effort... | not | not | not | not |
| 14 | More than 60 percent of Americans surveyed said immigration ... | More than 60 percent of Americans surveyed said immigration ... | sup | sup | sup | sup |
| 18 | If nearly 40 percent of those arrested have no criminal reco... | Nearly 40 percent of those arrested have no criminal record. | not | sup | sup | sup |

### thehill.com

- **URL:** https://thehill.com/opinion/finance/5768708-trump-trade-policy-agenda-2026/
- **Type:** opinion (high) | **Words:** 651 | **Sentences:** 46 | **Date:** 2026-03-09
- **Claims assessed:** 1 across 1 sentences (baseline: opus)

| # | Sentence (truncated) | Claim | opus | sonnet | gpt5 | grok |
|---|---------------------|-------|---|---|---|---|
| 11 | While the document acknowledges that the overall current acc... | The overall current account deficit has hovered between 3.4 ... | sup | sup | sup | sup |

### thehill.com

- **URL:** https://thehill.com/opinion/healthcare/5669986-america-sick-health-care/
- **Type:** opinion (high) | **Words:** 877 | **Sentences:** 36 | **Date:** 2026-03-09
- **Claims assessed:** 8 across 8 sentences (baseline: grok)

| # | Sentence (truncated) | Claim | opus | sonnet | gpt5 | grok |
|---|---------------------|-------|---|---|---|---|
| 8 | Ever since President Richard Nixon privatized American healt... | President Richard Nixon privatized American health insurance... | not | not | not | not |
| 11 | Consider the state of our system: Two-thirds of all bankrupt... | Two-thirds of all bankruptcies are medical | par | sup | sup | not |
| 15 | After the murder of UnitedHealthcare’s CEO Brian Thompson a ... | UnitedHealthcare’s CEO Brian Thompson was murdered a year ag... | not | not | sup | not |
| 16 | Thanks to the effects of the One Big Beautiful Bill Act, Aff... | Affordable Care Act health plan premiums are expected to ris... | not | not | not | not |
| 17 | As a result, one in four Americans enrolled in ObamaCare rec... | One in four Americans enrolled in ObamaCare said they’d go w... | sup | sup | not | sup |
| 20 | We’ve arrived at the hospital for surgery only to be handed ... | $500 bottle of medicine | not | not | not | not |
| 23 | Since founding Stupid Cancer for young adults with cancer 20... | Stupid Cancer was founded for young adults with cancer 20 ye... | par | sup | sup | not |
| 25 | What we need now is a well-funded and powerful lobby — a vot... | America has 19 million cancer patients | not | not | not | not |

### thehill.com

- **URL:** https://thehill.com/opinion/education/5659983-college-decline-public-confidence/
- **Type:** opinion (high) | **Words:** 794 | **Sentences:** 42 | **Date:** 2026-03-09
- **Claims assessed:** 5 across 3 sentences (baseline: opus)

| # | Sentence (truncated) | Claim | opus | sonnet | gpt5 | grok |
|---|---------------------|-------|---|---|---|---|
| 6 | Recent polling shows nearly two-thirds of registered voters ... | Nearly two-thirds of registered voters say a four-year colle... | sup | sup | sup | sup |
|  |  | The percentage of registered voters who believe a four-year ... | par | not | sup | sup |
| 7 | Other polling, from the Pew Research Center, indicates 70 pe... | 70 percent of Americans believe higher education is 'going i... | sup | sup | sup | sup |
|  |  | The percentage of Americans who believe higher education is ... | sup | sup | sup | sup |
| 11 | Surely some students need special academic services, but dat... | The number of students qualifying for academic accommodation... | not | not | not | not |
