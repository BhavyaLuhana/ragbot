# Evaluation

## 1. Metrics (RAGAS)
| Metric             | What it measures                     | Target |
|--------------------|--------------------------------------|--------|
| Faithfulness       | Answer grounded in retrieved context | ≥ 0.90 |
| Answer Relevancy   | Answer addresses the question        | ≥ 0.85 |
| Context Recall     | Retrieved context covers ground truth| ≥ 0.85 |
| Context Precision  | Signal-to-noise of retrieved chunks  | ≥ 0.80 |

## 2. Eval Set
- **Source:** Synthetic, GPT-4o-mini via RAGAS `TestsetGenerator`
- **Size:** 25 pairs (20 answerable + 5 unanswerable)
- **Categories:**
  - 10 × single-chunk factual lookup
  - 10 × multi-chunk / multi-hop
  - 5 × unanswerable (negative control — measures hallucination)
- **Storage:** `data/eval/qa_set.json` (committed)

## 3. Execution Model
`evaluate.py` is an HTTP client of the retrieval service — it calls
`POST /retrieve/sync` (non-streaming) and collects
`{answer, contexts, citations}` per query. RAGAS runs on the results.
Evaluation is implementation-agnostic: swap retrieval internals, re-run
`make eval`, get fresh scores.

## 4. Ablation Matrix (interview centerpiece)

| Config                 | Faithfulness | Relevancy | Recall | Precision |
|------------------------|--------------|-----------|--------|-----------|
| Dense only             |              |           |        |           |
| + BM25 + RRF           |              |           |        |           |
| + Cross-encoder rerank |              |           |        |           |
| + HyDE (full pipeline) |              |           |        |           |

Controlled via env vars:
- `RETRIEVAL_DENSE_ONLY=true`
- `RETRIEVAL_HYBRID=true`
- `RETRIEVAL_RERANK=true`
- `HYDE_ENABLED=true`

`make ablation` runs all four and writes `data/eval/ablation.csv`.

## 5. Test Queries (manual seeds)
Populated in `data/eval/manual_queries.json`:
- Factual: "What is <topic>?" → single-chunk retrieval expected
- Multi-hop: "How does X relate to Y?" → 2+ chunks expected
- Unanswerable: "What does the document say about <off-topic>?" → refusal expected

## 6. Reporting
- `make eval` → RAGAS table + `data/eval/results.json` (gitignored)
- `make ablation` → `data/eval/ablation.csv` (gitignored)
- Committed artifacts: `qa_set.json`, `manual_queries.json` only.
  Results are regenerated on demand; README will show a screenshot of
  the ablation table so reviewers see numbers without running the pipeline.
- Rationale for gitignoring results: they depend on the LLM's
  non-determinism and cost money to reproduce; the eval *harness* is
  what matters, not the frozen numbers.

## 7. Known Limitations
- Synthetic questions may be biased toward source-chunk language
  (mitigated by manual negative-control + multi-hop additions)
- RAGAS LLM-as-judge uses GPT-4o-mini → cheap, not ground truth
- Single-PDF corpus limits statistical significance of ablation deltas