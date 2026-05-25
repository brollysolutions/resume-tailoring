# Data Quality Report

Joined rows: **136** of 136 labels (lost to missing log: 0)
Unique pairs in log: 137; log events: 607 (avg 4.4 events/pair)

## Label cluster skew

- Dominant resume_id: `5eac9e08-bbe2-4f14-8faf-75a3bf99a261` -> **28** joined rows (20.6% of joined)
- Label mix in cluster: {'bad': 28}
- Active-weights Spearman over all joined rows: **0.3431**
- Active-weights Spearman with cluster removed: **0.2231**
- Delta (cluster contribution): 0.12

## Top 10 resumes by label count

| resume_id | n_labels | good | ok | bad | llm | implicit |
|-----------|----------|------|----|-----|-----|----------|
| `5eac9e08-bbe...` | 28 | 0 | 0 | 28 | 24 | 4 |
| `dad72dba-ce3...` | 18 | 2 | 0 | 16 | 14 | 4 |
| `67b3024e-e71...` | 14 | 8 | 1 | 5 | 13 | 1 |
| `8f01e655-adb...` | 13 | 3 | 0 | 10 | 13 | 0 |
| `7688bc4a-9a5...` | 12 | 0 | 0 | 12 | 12 | 0 |
| `408202a3-049...` | 12 | 0 | 0 | 12 | 10 | 2 |
| `48bcd3c3-7f6...` | 12 | 2 | 1 | 9 | 10 | 2 |
| `16cf5a23-425...` | 12 | 2 | 0 | 10 | 8 | 4 |
| `6a4359f9-5b9...` | 2 | 0 | 0 | 2 | 0 | 2 |
| `42a66357-7f3...` | 1 | 1 | 0 | 0 | 0 | 1 |

## Duplication

Pairs rescored more than once: **38**
Largest range: pair `(, 325092716aaab940)` -> 27 events, span 37.0 points
