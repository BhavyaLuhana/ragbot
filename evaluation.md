# Evaluation

## 1. Metrics (RAGAS)
| Metric             | What it measures                              | Target |
|--------------------|-----------------------------------------------|--------|
| Faithfulness       | Answer grounded in retrieved context          | ≥ 0.90 |
| Answer Relevancy   | Answer addresses the question                 | ≥ 0.85 |
| Context Recall     | Retrieved context covers ground truth         | ≥ 0.85 |
| Context Precision  | Signal-to-noise of retrieved chunks           | ≥ 0.80 |

## 2. Eval Set
- **Source:** Synthetic, generated with GPT-4o-mini via RAGAS `TestsetGenerator`
- **Size:** 25 pairs (20 answerable + 5 unanswerable as negative control)
- **Categories:**
  - 10 × single-chunk factual lookup
  - 10 × multi-chunk / multi-hop
  - 5 × unanswerable (measures hallucination under empty context)
- **Storage:** `data/eval/qa_set.json` (committed)

## 3. Execution Model
`evaluate.py` is an HTTP client of the retrieval service — it calls
`POST /retrieve/sync` (non-streaming variant) and collects
`{answer, contexts, citations}` per query. RAGAS runs on the collected
results. This keeps evaluation **implementation-agnostic**: swap the
retrieval internals, re-run `make eval`, get a fresh score.

## 4. Ablation Matrix (interview centerpiece)
Run the same eval set against 4 retrieval configs, via env flags:

| Config                       | Faithfulness | Relevancy | Recall | Precision |
|------------------------------|--------------|-----------|--------|-----------|
| Dense only                   |              |           |        |           |
| + BM25 + RRF                 |              |           |        |           |
| + Cross-encoder rerank       |              |           |        |           |
| + HyDE (full pipeline)       |              |           |        |           |

Controlled via env vars:
- `RETRIEVAL_DENSE_ONLY=true`
- `RETRIEVAL_HYBRID=true`
- `RETRIEVAL_RERANK=true`
- `HYDE_ENABLED=true`

`make ablation` runs all four and writes `data/eval/ablation.csv`.

## 5. Test Queries (seeded, human-written — filled once corpus is known)
To be populated in `data/eval/manual_queries.json`:
- Factual: "What is <topic>?"  → expected: single-chunk retrieval
- Multi-hop: "How does X relate to Y?" → expected: 2+ chunks in context
- Unanswerable: "What does the document say about <off-topic>?" → expected: refusal

## 6. Reporting
- `make eval` → runs RAGAS, prints table, writes `data/eval/results.json`
- `make ablation` → writes `data/eval/ablation.csv`
- Both metrics and ablation CSV are committed for the portfolio narrative.

## 7. Known Limitations
- Synthetic questions may be biased toward language in the source chunks
  (mitigated by manual negative-control + multi-hop additions)
- RAGAS LLM-as-judge uses GPT-4o-mini → cheap but not ground truth
- Single-PDF corpus limits statistical significance of ablation deltas