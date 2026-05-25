# Keyword & Skill Extraction Findings

JDs audited: 12 (from `backend/data/calibration_corpus/jds/`)
Resumes used for fuzzy/ngram sample: 8

## Token funnel (per-JD averages)

- Raw tokens: avg 282
- After stopword filter: avg 208
- After BLOCKED_GENERIC filter: avg 194
- Unique normalized: avg 152
- Dropped by NER (entities): avg 0
- Dropped by min_freq=2: avg 127
- Final top_jd tokens (k=50): avg 26

## N-gram phrase coverage

- Total phrases in `_NGRAM_SKILLS`: **25**
- Dead in JD corpus (never hit): **3/25** (12%)
- Dead in resume corpus: **15/25**
- Dead in both (truly unused): **0**

Top dead-in-JD phrases:
```
data analysis
microservices architecture
reinforcement learning
```

## extract_skills vs SKILL_DOMAIN vs _top_jd_tokens

Average disagreement (symmetric difference share) between `nlp_utils.extract_skills` and `_top_jd_tokens`: **0.93**

`SKILL_DOMAIN` has 90 entries; `nlp_utils._TECH_SKILLS` is a separate ~46-entry hardcoded set in `nlp_utils.py` and is not synced with `SKILL_DOMAIN`. Coverage gaps drive disagreement.

## Fuzzy-match sample

Surfaced 22 pairs (jd_token, resume_token) with rapidfuzz ratio in [85,100). See `fuzzy_match_log.csv` — `false_positive` column is empty for human annotation.
