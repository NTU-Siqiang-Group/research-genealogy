# P0 feasibility report — Run A/B complete; evidence-first prototype running

Status date: 2026-08-23.

This report deliberately separates actual upstream checks from fixture-only
contract checks. No score from `offline_smoke` is evidence about real genealogy
quality.

## What has run

1. Both upstream repositories were cloned and pinned; neither was modified.
2. CoI-Agent's declared dependencies were installed in an isolated Python 3.12
   environment. Its unchanged Semantic Scholar search client loads through the
   P0 adapter.
3. A real query for Monkey reached Semantic Scholar but received repeated HTTP
   429 responses without an API key. The adapter bounded CoI's otherwise
   unbounded recursive retry at 20 seconds.
4. SciPDF installation was attempted separately; its Git fetch stalled. P0 now
   has a fail-closed metadata-only compatibility boundary. Full-text calls still
   require real SciPDF + GROBID.
5. SCYCHIC had no requirements file. A compatible environment was reconstructed
   after reproducing NumPy/PyTorch/Transformers conflicts. `generate.py --help`
   runs; `main.py --help` still fails because it imports nonexistent package
   `evaluator` while the checkout contains `eval`.
6. SCYCHIC's `PaperProcessor.process_hierarchical_clustering` was invoked
   directly, unchanged, on a six-paper pre-generated-embedding fixture. Its
   two-level top-down KMeans path completed and preserved canonical IDs through
   the wrapper.
7. Canonical schema, CoI adapter/cache, mechanical CoI-to-SCYCHIC mapping,
   citation overlay, deterministic lineage heuristic, DOT/SVG rendering, and
   gold-constraint evaluation have executable tests.
8. An OpenAlex adapter resolved all 10 must-find LSM papers, deduplicated
   preprint/venue versions, and built a 150-paper corpus with 1,233 in-corpus
   citation edges.
9. Run A completed with local title/abstract TF-IDF embeddings and no LLM.
10. DeepSeek V4 Flash completed 150/150 cached CoI-prompt profiles with no API
    failures. Run B completed on problem, solution, results, and all-field axes.
11. The evaluator now distinguishes citation existence from dominant-lineage
    recovery. Citation recall was 3/3 for all variants, but dominant-lineage
    recall was 0/3 for Run A and at most 1/3 for Run B.
12. The literal CoI prompt was found unsuitable for factual profiling: it
    fabricated workload-adaptive methods for the 1996 LSM-tree paper and filled
    complete semantic profiles for title-only records.
13. The parent-selection layer was replaced with section-aware full-text
    evidence. Citation-only edges are weak and no longer receive a forced
    parent based on cluster similarity.
14. A real Dostoevsky/RusKey PDF run recovered `Dostoevsky -> RusKey` as a
    strong, parent-eligible implicit baseline through Fluid LSM-tree and Lazy
    Leveling provenance. The run has zero chronology violations and zero
    forbidden forced edges.
15. The full-text set now includes CAMAL and ArceKV. CAMAL's Background yields
    a medium logical `RusKey -> CAMAL` cross-link, while shared verified
    correspondence by Siqiang Luo is retained only as supplemental
    research-group evidence.
16. Ordered authorships are hydrated for all 150 papers. Explicit PDF
    front-matter statements and matched correspondence footnotes provide a
    fallback when OpenAlex omits corresponding-author flags.

## Current answers to the P0 questions

| Question | Current evidence |
|---|---|
| Did citation-only work? | It recovered all three gold citations but none as the dominant lineage parent. Citation existence is necessary evidence but not sufficient genealogy. |
| Did SCYCHIC recover meaningful branches? | Partially. Run A mean gold-branch coherence was 0.625. Run B problem-axis coherence rose to 0.917 with a tolerable 39.3% largest-cluster share, but this sparse gold metric does not establish semantic correctness. |
| Which semantic axis worked best? | `problem` was the best clustering compromise. `all` matched its 0.917 coherence but collapsed 83.3% of papers into one coarse cluster; `solution` recovered one dominant gold edge but collapsed 68.7% into one cluster. |
| Is CoI extraction sufficient? | No. API/format reliability was high, but the literal prompt generated unsupported methods and topic-biased profiles. It must be replaced by evidence-bounded extraction. |
| Were hubs/branch points recovered? | The citation-descendant heuristic marked all three expected hubs, but lineage-parent recovery remained 0/3 to 1/3. This is not yet a reliable branch-point result. |
| Were forbidden edges inferred? | No. `RusKey -> CAMAL` is retained as a medium, non-parent cross-link; the evaluation still reports zero forbidden forced edges. |
| Can split reasons be explained? | Only a deterministic cluster-path contrast is currently emitted. Evidence-grounded semantic wording remains pending. |

## Preliminary keep/rewrite decision

Keep:

- OpenAlex retrieval, cache, stable IDs, and duplicate collapse;
- SCYCHIC's pre-generated embedding contract and KMeans hierarchy processor;
- separate environments and file-based integration.

Rewrite or harden:

- the literal CoI idea-generation prompt, replacing it with evidence-bounded
  semantic extraction;
- SCYCHIC packaging, CLI import path, dependency lock, NumPy scalar output, and
  loss of canonical IDs;
- semantic predecessor inference (the fixture false edge shows why);
- evidence-grounded branch-point and split-reason logic.

## Next quality blockers

- evidence-grounded full text or section-level source passages for landmark
  papers;
- an extractor that returns `unknown` rather than inventing unsupported fields;
- citation-context and typed-change evidence for lineage edge scoring;
- broader human gold labels for branches and dominant parents;
- grounded cluster labels and split explanations.

Detailed measurements and artifact paths are in `reports/run_ab_results.md`.
