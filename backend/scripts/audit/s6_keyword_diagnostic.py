"""s6 — Keyword and skill extraction diagnostic.

For every JD in backend/data/calibration_corpus/jds/, instrument
keyword_utils to capture intermediate token counts (post-stopword,
post-blocked, post-NER, final top-k) and compare against
nlp_utils.extract_skills and skill_taxonomy.SKILL_DOMAIN.

Quantifies: dead n-gram phrases, NER over-drop rate, taxonomy gaps,
fuzzy-match false-positive sample.

Outputs under backend/docs/audit/keywords/:
    jd_token_audit.csv
    skill_set_coverage.csv
    ngram_phrase_hits.csv
    fuzzy_match_log.csv
    extraction_findings.md
"""
from __future__ import annotations

import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.keyword_utils import (  # noqa: E402
    _BLOCKED_GENERIC,
    _NGRAM_SKILLS,
    _STOPWORDS,
    _jd_entity_tokens,
    _normalize_token,
    _significant_tokens,
    _tokenize_raw,
)
from app.api.match_logic.nlp_utils import extract_skills  # noqa: E402
from app.core.skill_taxonomy import SKILL_DOMAIN  # noqa: E402

_CORPUS = _BACKEND_ROOT / "data" / "calibration_corpus" / "jds"
_RESUME_CORPUS = _BACKEND_ROOT / "data" / "calibration_corpus" / "resumes"
_OUT = _BACKEND_ROOT / "docs" / "audit" / "keywords"


def _instrument_jd(text: str, k: int = 50, min_freq: int = 2) -> dict:
    """Walk _top_jd_tokens manually and return counts at each filter stage."""
    raw_tokens = _tokenize_raw(text)
    n_raw = len(raw_tokens)

    after_stop = [t for t in raw_tokens if t not in _STOPWORDS]
    after_blocked = [t for t in after_stop if t not in _BLOCKED_GENERIC]

    counts: Counter = Counter()
    for raw in raw_tokens:
        if raw in _STOPWORDS or raw in _BLOCKED_GENERIC:
            continue
        norm = _normalize_token(raw)
        if not norm or norm in _STOPWORDS or norm in _BLOCKED_GENERIC:
            continue
        counts[norm] += 1

    entities = _jd_entity_tokens(text)
    above_min = [(t, c) for t, c in counts.items() if c >= min_freq]
    above_min_after_ner = [(t, c) for t, c in above_min if t not in entities]
    # Mirror fallback behavior: if NER drops too aggressively, allow min_freq=1
    final = above_min_after_ner if above_min_after_ner else [
        (t, c) for t, c in counts.items() if t not in entities
    ]
    final.sort(key=lambda x: (-x[1], x[0]))
    kept = [t for t, _ in final[:k]]

    dropped_to_blocked = [t for t in raw_tokens if t in _BLOCKED_GENERIC]
    dropped_to_stop = [t for t in raw_tokens if t in _STOPWORDS]
    dropped_to_ner = [t for t in counts if t in entities]
    dropped_to_min_freq = [t for t, c in counts.items() if c < min_freq and t not in entities]

    def _top_unique(items, n=5):
        c = Counter(items)
        return [t for t, _ in c.most_common(n)]

    return {
        "n_raw": n_raw,
        "n_after_stopwords": len(after_stop),
        "n_after_blocked": len(after_blocked),
        "n_unique_normalized": len(counts),
        "n_above_min_freq": len(above_min),
        "n_entities_dropped": len(dropped_to_ner),
        "n_dropped_min_freq": len(dropped_to_min_freq),
        "n_final": len(kept),
        "top5_kept": kept[:5],
        "top5_dropped_blocked": _top_unique(dropped_to_blocked, 5),
        "top5_dropped_stop": _top_unique(dropped_to_stop, 5),
        "top5_dropped_ner": dropped_to_ner[:5],
        "top5_dropped_min_freq": dropped_to_min_freq[:5],
        "final_set": set(kept),
    }


def _extract_resume_text(path: Path) -> str:
    """Best-effort plain-text extraction from PDF resume. Falls back to empty."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        return "\n".join(page.get_text() for page in doc)
    except Exception:
        return ""


def main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)

    jd_files = sorted(_CORPUS.glob("*.txt"))
    if not jd_files:
        print("s6: no JD corpus files; abort")
        return 1

    # --- jd_token_audit.csv ---
    audit_rows = []
    audit_details = {}
    for jd_path in jd_files:
        text = jd_path.read_text(encoding="utf-8", errors="ignore")
        d = _instrument_jd(text)
        audit_details[jd_path.name] = d
        audit_rows.append({
            "jd_file": jd_path.name,
            "n_raw_tokens": d["n_raw"],
            "n_after_stopwords": d["n_after_stopwords"],
            "n_after_blocked": d["n_after_blocked"],
            "n_unique_normalized": d["n_unique_normalized"],
            "n_entities_dropped": d["n_entities_dropped"],
            "n_dropped_min_freq": d["n_dropped_min_freq"],
            "n_final_top_jd": d["n_final"],
            "top5_kept": "|".join(d["top5_kept"]),
            "top5_dropped_ner": "|".join(d["top5_dropped_ner"]),
            "top5_dropped_blocked": "|".join(d["top5_dropped_blocked"]),
            "top5_dropped_min_freq": "|".join(d["top5_dropped_min_freq"]),
        })
    with (_OUT / "jd_token_audit.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(audit_rows[0].keys()))
        wr.writeheader()
        wr.writerows(audit_rows)

    # --- skill_set_coverage.csv ---
    cov_rows = []
    for jd_path in jd_files:
        text = jd_path.read_text(encoding="utf-8", errors="ignore")
        d = audit_details[jd_path.name]
        top_jd = d["final_set"]
        skills_nlp = extract_skills(text)
        skills_taxonomy = {tok for tok in (top_jd | skills_nlp)
                           if tok in SKILL_DOMAIN}
        all_three_union = top_jd | skills_nlp | skills_taxonomy
        only_nlp = skills_nlp - top_jd
        only_top = top_jd - skills_nlp
        only_taxonomy = skills_taxonomy - top_jd
        # Disagreement metric: symmetric difference between top_jd and nlp_skills
        sym_diff = (top_jd ^ skills_nlp)
        disagree_share = len(sym_diff) / max(len(top_jd | skills_nlp), 1)
        cov_rows.append({
            "jd_file": jd_path.name,
            "n_top_jd_tokens": len(top_jd),
            "n_nlp_extract_skills": len(skills_nlp),
            "n_in_taxonomy_SKILL_DOMAIN": len(skills_taxonomy),
            "union_all": len(all_three_union),
            "in_top_jd_not_in_nlp": len(only_top),
            "in_nlp_not_in_top_jd": len(only_nlp),
            "in_taxonomy_not_in_top_jd": len(only_taxonomy),
            "disagreement_share": round(disagree_share, 3),
            "skills_nlp_sample": "|".join(sorted(skills_nlp)[:10]),
            "skills_taxonomy_sample": "|".join(sorted(skills_taxonomy)[:10]),
        })
    with (_OUT / "skill_set_coverage.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(cov_rows[0].keys()))
        wr.writeheader()
        wr.writerows(cov_rows)

    # --- ngram_phrase_hits.csv ---
    jd_hit_counter: Counter = Counter()
    resume_hit_counter: Counter = Counter()
    for jd_path in jd_files:
        text = jd_path.read_text(encoding="utf-8", errors="ignore").lower()
        for phrase in _NGRAM_SKILLS:
            if phrase in text:
                jd_hit_counter[phrase] += 1
    resume_files = sorted(_RESUME_CORPUS.glob("*.pdf"))
    for rp in resume_files:
        text = _extract_resume_text(rp).lower()
        if not text:
            continue
        for phrase in _NGRAM_SKILLS:
            if phrase in text:
                resume_hit_counter[phrase] += 1

    ngram_rows = []
    for phrase in sorted(_NGRAM_SKILLS):
        ngram_rows.append({
            "phrase": phrase,
            "jd_hits": jd_hit_counter.get(phrase, 0),
            "resume_hits": resume_hit_counter.get(phrase, 0),
            "dead_in_jd": jd_hit_counter.get(phrase, 0) == 0,
            "dead_in_resume": resume_hit_counter.get(phrase, 0) == 0,
        })
    with (_OUT / "ngram_phrase_hits.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(ngram_rows[0].keys()))
        wr.writeheader()
        wr.writerows(ngram_rows)

    # --- fuzzy_match_log.csv ---
    # Try to pair each JD with a real resume from corpus to surface fuzzy matches.
    try:
        from rapidfuzz import fuzz
    except ImportError:
        fuzz = None

    fuzzy_rows = []
    if fuzz is not None:
        rng = random.Random(0)
        for jd_path in jd_files:
            jd_text = jd_path.read_text(encoding="utf-8", errors="ignore")
            top_jd = audit_details[jd_path.name]["final_set"]
            for rp in resume_files[: min(3, len(resume_files))]:
                resume_text = _extract_resume_text(rp)
                if not resume_text:
                    continue
                resume_tokens = _significant_tokens(resume_text)
                exact = top_jd & resume_tokens
                leftover = top_jd - exact
                for jd_tok in list(leftover):
                    for r_tok in resume_tokens:
                        ratio = fuzz.ratio(jd_tok, r_tok)
                        if 85 <= ratio < 100 and jd_tok != r_tok:
                            fuzzy_rows.append({
                                "jd_file": jd_path.name,
                                "resume_file": rp.name,
                                "jd_token": jd_tok,
                                "resume_token": r_tok,
                                "ratio": ratio,
                                "false_positive": "",  # human-fill
                            })
                            break
        if len(fuzzy_rows) > 100:
            fuzzy_rows = rng.sample(fuzzy_rows, 100)
    with (_OUT / "fuzzy_match_log.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["jd_file", "resume_file", "jd_token",
                                           "resume_token", "ratio", "false_positive"])
        wr.writeheader()
        wr.writerows(fuzzy_rows)

    # --- extraction_findings.md ---
    dead_in_jd = [r["phrase"] for r in ngram_rows if r["dead_in_jd"]]
    dead_in_resume = [r["phrase"] for r in ngram_rows if r["dead_in_resume"]]
    dead_in_both = [r["phrase"] for r in ngram_rows
                    if r["dead_in_jd"] and r["dead_in_resume"]]
    total_ngrams = len(_NGRAM_SKILLS)

    avg_ner_drop = sum(r["n_entities_dropped"] for r in audit_rows) / max(len(audit_rows), 1)
    avg_minfreq_drop = sum(r["n_dropped_min_freq"] for r in audit_rows) / max(len(audit_rows), 1)
    avg_final = sum(r["n_final_top_jd"] for r in audit_rows) / max(len(audit_rows), 1)

    avg_disagreement = sum(r["disagreement_share"] for r in cov_rows) / max(len(cov_rows), 1)

    findings = [
        "# Keyword & Skill Extraction Findings",
        "",
        f"JDs audited: {len(jd_files)} (from `backend/data/calibration_corpus/jds/`)",
        f"Resumes used for fuzzy/ngram sample: {len(resume_files)}",
        "",
        "## Token funnel (per-JD averages)",
        "",
        f"- Raw tokens: avg {sum(r['n_raw_tokens'] for r in audit_rows)/max(len(audit_rows),1):.0f}",
        f"- After stopword filter: avg {sum(r['n_after_stopwords'] for r in audit_rows)/max(len(audit_rows),1):.0f}",
        f"- After BLOCKED_GENERIC filter: avg {sum(r['n_after_blocked'] for r in audit_rows)/max(len(audit_rows),1):.0f}",
        f"- Unique normalized: avg {sum(r['n_unique_normalized'] for r in audit_rows)/max(len(audit_rows),1):.0f}",
        f"- Dropped by NER (entities): avg {avg_ner_drop:.0f}",
        f"- Dropped by min_freq=2: avg {avg_minfreq_drop:.0f}",
        f"- Final top_jd tokens (k=50): avg {avg_final:.0f}",
        "",
        "## N-gram phrase coverage",
        "",
        f"- Total phrases in `_NGRAM_SKILLS`: **{total_ngrams}**",
        f"- Dead in JD corpus (never hit): **{len(dead_in_jd)}/{total_ngrams}** ({len(dead_in_jd)*100//total_ngrams}%)",
        f"- Dead in resume corpus: **{len(dead_in_resume)}/{total_ngrams}**",
        f"- Dead in both (truly unused): **{len(dead_in_both)}**",
        "",
        "Top dead-in-JD phrases:",
        "```",
        "\n".join(dead_in_jd[:20]),
        "```",
        "",
        "## extract_skills vs SKILL_DOMAIN vs _top_jd_tokens",
        "",
        f"Average disagreement (symmetric difference share) between `nlp_utils.extract_skills` "
        f"and `_top_jd_tokens`: **{avg_disagreement:.2f}**",
        "",
        f"`SKILL_DOMAIN` has {len(SKILL_DOMAIN)} entries; "
        f"`nlp_utils._TECH_SKILLS` is a separate ~46-entry hardcoded set in `nlp_utils.py` "
        f"and is not synced with `SKILL_DOMAIN`. Coverage gaps drive disagreement.",
        "",
        f"## Fuzzy-match sample",
        "",
        f"Surfaced {len(fuzzy_rows)} pairs (jd_token, resume_token) with rapidfuzz ratio in [85,100). "
        f"See `fuzzy_match_log.csv` — `false_positive` column is empty for human annotation.",
        "",
    ]
    (_OUT / "extraction_findings.md").write_text("\n".join(findings), encoding="utf-8")

    print(f"s6 done. jds={len(jd_files)} dead_ngrams={len(dead_in_both)}/{total_ngrams}, "
          f"avg_ner_drop={avg_ner_drop:.0f}, avg_disagreement={avg_disagreement:.2f}, "
          f"fuzzy_pairs={len(fuzzy_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
