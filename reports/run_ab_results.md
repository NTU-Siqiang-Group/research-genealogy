# OpenAlex Run A/B results

Run date: 2026-08-21.

## Experimental contract

Both runs use the same real OpenAlex corpus and citation overlay:

- 150 deduplicated papers;
- all 10 must-find LSM papers resolved;
- 139 papers with abstracts;
- 134 papers with bibliography fields;
- 1,233 normalized in-corpus citation edges;
- SCYCHIC top-down KMeans with 12 fine clusters and 4 coarse clusters;
- local 384-feature TF-IDF embeddings, so neither run uses a hosted embedding API.

Run A embeds title plus abstract and does not call an LLM. Run B calls
DeepSeek V4 Flash with CoI-Agent's literal deep-reference prompt, maps the
parsed fields mechanically into SCYCHIC, and evaluates the `problem`,
`solution`, `results`, and `all` axes separately.

## Results

| run | expected citation recall | expected dominant-lineage recall | forbidden dominant edges | mean gold-branch coherence | largest coarse cluster |
|---|---:|---:|---:|---:|---:|
| A — title + abstract | 1.00 | 0.00 | 0 | 0.625 | 0.333 |
| B — problem | 1.00 | 0.00 | 0 | 0.917 | 0.393 |
| B — solution | 1.00 | 0.33 | 0 | 0.792 | 0.687 |
| B — results | 1.00 | 0.00 | 0 | 0.792 | 0.540 |
| B — all | 1.00 | 0.00 | 0 | 0.917 | 0.833 |

`expected citation recall` only confirms that the gold pairs cite one another.
It is not genealogy recovery. The added `expected dominant-lineage recall`
shows that Run A recovered none of the three expected parent links. Among Run B
variants, only the solution axis made `Monkey -> Dostoevsky` dominant; neither
`Dostoevsky -> RusKey` nor `RusKey -> ArceKV` was selected by any run.

The problem axis is the best clustering variant in this controlled comparison:
it improves mean gold-branch coherence without the severe collapse seen in the
solution and all-field embeddings. This is provisional evidence from ten gold
papers, not a claim that its generated semantic fields are factually correct.

## Semantic extraction quality failure

DeepSeek connectivity and formatting were reliable: 150/150 calls completed,
and all responses were cached with raw output and a prompt hash. Content
grounding was not reliable.

- The 1996 LSM-tree paper was described as proposing a workload-adaptive
  RocksDB framework with online reconfiguration and YCSB-style experiments,
  none of which is supported by its supplied title/abstract.
- Ten corpus papers have no abstract. Six nevertheless received non-empty
  Background, Novelty, Contribution, Methods, Detail Reason, and Limitation
  fields.
- Across the 150 profiles, terms absent from each paper's supplied source were
  injected into the six core fields for `workload` in 61 papers, `adaptive` in
  59 papers, and `dynamic` in 62 papers.
- Only 108/150 profiles contained a parsed Methods field, although 146 had
  Novelty, Contribution, Detail Reason, and Limitation fields.

This is consistent with CoI's prompt behaving as research-idea generation
rather than evidence-bounded paper profiling. Its output can move clusters—the
problem-axis dominant-parent set has only 0.195 Jaccard overlap with Run A—but
that movement is not trustworthy genealogy evidence.

## P0 decision

Keep:

- OpenAlex retrieval, caching, canonical IDs, and duplicate-version collapse;
- local file contracts and resumable profile cache;
- SCYCHIC's pre-generated embedding and hierarchy boundary;
- citation overlay, chronology checks, and explicit DAG/tree outputs.

Rewrite before a quality claim:

- replace the literal CoI idea-generation prompt with an evidence-bounded
  extractor that permits `unknown` and quotes source spans;
- exclude or separately label title-only papers instead of fabricating full
  semantic profiles;
- score lineage using typed semantic change plus citation context, not merely
  same-cluster membership and temporal proximity;
- evaluate expected dominant lineage separately from citation existence;
- replace deterministic token-frequency cluster labels with grounded labels
  generated from representative source passages.

## Artifacts

- Run A: `data/output/run_a/`
- Run B problem axis: `data/output/run_b/problem/`
- Run B solution axis: `data/output/run_b/solution/`
- Run B results axis: `data/output/run_b/results/`
- Run B all-fields axis: `data/output/run_b/all/`
- Cached DeepSeek profiles: `data/semantic_profiles/run_b/`
- Shared OpenAlex corpus: `data/papers/openalex_lsm_corpus.json`
