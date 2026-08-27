# Academic Genealogy P0

This workspace implements an evidence-first academic genealogy prototype.
OpenAlex supplies the corpus and the weak citation-candidate graph. Local full
text supplies section-aware direct-discussion, baseline, method-dependency, and
entity-provenance evidence. Those evidence records determine genealogy edges.
SCYCHIC clustering is retained only for optional branch grouping and display;
it no longer chooses paper parents.

The two upstream repositories are pinned in `upstream.lock` and are not patched.

## Search application and persistent results

Start the local application server:

```bash
.venv-coi/bin/python scripts/09_serve_app.py --port 4174
```

Open <http://127.0.0.1:4174/>. The homepage accepts one paper title, DOI, or
OpenAlex ID in the usual case; put one seed per line for a curated multi-seed
case. Search work runs in the background and the homepage shows its current
stage. An identical completed request is reused unless a forced rerun is
requested through the CLI or API.

Every search is an independent, reopenable bundle under
`data/searches/<result-id>/`:

```text
request.json                 normalized query and stable fingerprint
status.json                  progress, warnings, counts, and final state
inputs/                      exact configuration and full-text selection
raw/openalex/                cached provider responses
raw/pdfs/                    title-validated source PDFs
raw/fulltext/                retrieval attempts, URLs, and checksums
corpus.json                  bounded paper corpus
citation_graph.json          normalized weak citation candidates
evidence.json                section-aware extracted evidence
outputs/                     inferred DAG, dominant tree, DOT, and SVG
inspector.json               self-contained browser payload
logs/                        commands, stdout/stderr, and traceback on failure
artifact_manifest.json       byte size and SHA-256 for every saved artifact
```

Opening a saved result reads `inspector.json`; it does not call OpenAlex, the
full-text fallback chain, or an LLM again. The homepage history is derived from
these directories, so it does not depend on a separate database. Search data
and credentials remain local and are ignored by Git.

The same workflow is available without the browser:

```bash
.venv-coi/bin/python scripts/08_run_search.py \
  --seed "CAMAL: Optimizing LSM-trees via Active Learning"
```

The current manually audited LSM-tree result can be imported once into this
store with `.venv-coi/bin/python scripts/10_import_gold_result.py`. This copies
its raw provider cache, PDFs, evidence, derived artifacts, and retained legacy
inputs so the historical run is auditable as well as viewable.

## Verified local smoke suite

```bash
bash scripts/run_p0.sh
```

This runs unit tests, a real two-level SCYCHIC clustering smoke fixture, and an
explicitly non-evaluative offline LSM contract fixture. Generated files are
under `data/output/offline_smoke/`.

## Live pipeline entry points

```bash
.venv-coi/bin/python scripts/01_build_corpus.py \
  --provider openalex \
  --output data/papers/openalex_lsm_corpus.json
.venv-coi/bin/python scripts/02_extract_profiles.py \
  --corpus data/papers/openalex_lsm_corpus.json \
  --output-dir data/semantic_profiles/run_b
.venv-coi/bin/python scripts/02_adapt_profiles.py \
  --corpus data/papers/openalex_lsm_corpus.json \
  --profile-dir data/semantic_profiles/run_b \
  --output-dir data/hierarchy/run_b/input

.venv-scychic/bin/python scripts/03_run_hierarchy.py \
  --input-folder data/hierarchy/scychic_input \
  --embeddings-file data/hierarchy/embeddings.pkl \
  --axis solution \
  --cluster-sizes 12 4 \
  --output data/hierarchy/solution/hierarchy.json
```

The root `.env` is loaded by the live retrieval and extraction scripts. The
current provider-neutral variables are `OPENALEX_API_KEY`, `DEEPSEEK_API_KEY`,
`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_THINKING`. The older
Semantic Scholar and OpenAI/Azure paths remain optional compatibility routes.

## Reproducing Run A/B

Run A uses only title, abstract, citations, local TF-IDF, and SCYCHIC:

```bash
.venv-scychic/bin/python scripts/02_prepare_local_embeddings.py \
  --mode abstract \
  --corpus data/papers/openalex_lsm_corpus.json \
  --input-dir data/hierarchy/run_a/input \
  --embeddings-file data/hierarchy/run_a/embeddings.pkl

.venv-scychic/bin/python scripts/03_run_hierarchy.py \
  --input-folder data/hierarchy/run_a/input \
  --embeddings-file data/hierarchy/run_a/embeddings.pkl \
  --axis all --cluster-sizes 12 4 \
  --output data/output/run_a/hierarchy.json
```

Run B first caches provider-generated CoI profiles, then uses the same local
embedding and SCYCHIC boundary:

```bash
.venv-coi/bin/python scripts/02_extract_profiles.py \
  --corpus data/papers/openalex_lsm_corpus.json \
  --output-dir data/semantic_profiles/run_b \
  --max-concurrency 8

.venv-coi/bin/python scripts/02_adapt_profiles.py \
  --corpus data/papers/openalex_lsm_corpus.json \
  --profile-dir data/semantic_profiles/run_b \
  --output-dir data/hierarchy/run_b/input

.venv-scychic/bin/python scripts/02_prepare_local_embeddings.py \
  --mode semantic \
  --input-dir data/hierarchy/run_b/input \
  --embeddings-file data/hierarchy/run_b/embeddings.pkl
```

Measured results and the keep/rewrite decision are in
`reports/run_ab_results.md`.

After a live hierarchy exists:

```bash
.venv-coi/bin/python scripts/04_overlay_citations.py \
  --corpus data/papers/openalex_lsm_corpus.json \
  --hierarchy data/hierarchy/solution/hierarchy.json \
  --axis solution \
  --output data/output/solution/citation_graph.json

.venv-coi/bin/python scripts/05_infer_tree.py \
  --overlay data/output/solution/citation_graph.json \
  --axis solution \
  --output-dir data/output/solution

.venv-coi/bin/python scripts/06_evaluate_gold.py \
  --dag data/output/solution/evolution_dag.json \
  --output data/output/solution/evaluation.json
```

Current evidence and blockers are recorded in `reports/p0_feasibility_report.md`.

## Evidence-first genealogy

Before overlaying citations, hydrate ordered OpenAlex authorships. The same
step checks the first two pages of locally verified PDFs for explicit
corresponding-author statements or matched footnote markers. This fallback is
needed because OpenAlex may retain the byline while omitting correspondence
roles.

```bash
.venv-coi/bin/python scripts/01_enrich_authorships.py \
  --corpus data/papers/openalex_lsm_corpus.json \
  --manifest configs/lsm_fulltext.yaml \
  --retrieval-index data/raw/fulltext/retrieval_index.json
```

The first real full-text set contains Dostoevsky, RusKey, CAMAL, and ArceKV. It uses
the system `pdftotext` executable; no GROBID server or embedding API is required
for this prototype path.

When OpenAlex has no usable PDF, retrieve and title-validate a local copy first:

```bash
.venv-coi/bin/python scripts/03_retrieve_fulltext.py \
  --corpus data/papers/openalex_lsm_corpus.json \
  --paper-id OPENALEX:W7160292552 \
  --output-dir data/raw/pdfs \
  --index data/raw/fulltext/retrieval_index.json
```

For a bounded batch of corpus records whose OpenAlex `pdf_url` is empty:

```bash
.venv-coi/bin/python scripts/03_retrieve_fulltext.py \
  --corpus data/papers/openalex_lsm_corpus.json \
  --missing-only --limit 20 \
  --output-dir data/raw/pdfs \
  --index data/raw/fulltext/retrieval_index.json
```

Retrieval is staged and stops at the first valid PDF: OpenAlex PDF/location,
configured author or research-group publication pages (including JavaScript
sites), explicit project override, DOI landing page, arXiv title search, then
DBLP. A PDF is accepted only if it has a PDF signature and the first two pages
match the requested title. `retrieval_index.json` records the source page,
resolved URL, provider, failed attempts, retrieval time, title score, local
path, and SHA-256 digest. Add further lab/author publication pages in
`configs/fulltext_retrieval.yaml`; the DOI/arXiv/DBLP stages work without a
page-specific entry.

```bash
.venv-coi/bin/python scripts/04_extract_relation_evidence.py \
  --corpus data/papers/openalex_lsm_corpus.json \
  --manifest configs/lsm_fulltext.yaml \
  --retrieval-index data/raw/fulltext/retrieval_index.json \
  --output data/evidence/lsm_fulltext_evidence.json

.venv-coi/bin/python scripts/05_infer_tree.py \
  --overlay data/output/run_b/solution/citation_graph.json \
  --evidence data/evidence/lsm_fulltext_evidence.json \
  --axis solution \
  --output-dir data/output/evidence_first

.venv-coi/bin/python scripts/06_evaluate_gold.py \
  --dag data/output/evidence_first/evolution_dag.json \
  --output data/output/evidence_first/evaluation.json
```

Every edge now carries independent fields for `association_level`, typed
`relation_types`, `parent_eligible`, and verbatim `evidence_details`. The
default policy is:

- bibliography-only and Related Work mentions are weak;
- substantive Introduction, Preliminaries, and Background discussions are
  medium;
- overlapping first, second, or verified corresponding authors are a medium,
  supplemental `SAME_RESEARCH_GROUP` association: stronger than citation but
  lower-priority than logical evidence, and never parent-eligible on its own;
- experimental baselines and method dependencies are strong;
- an explicit experimental baseline is strong; it becomes parent-eligible when
  Introduction/Preliminaries evidence also frames it as the limitation being
  addressed;
- an artifact-level implicit baseline or direct method dependency can establish
  parent eligibility on its own when entity provenance is available;
- no paper is forced to have exactly one parent.

`configs/lsm_fulltext.yaml` also records artifact origins and aliases. This
allows an experimental mention of `Fluid LSM-tree` or `Lazy-Leveling` to be
traced to Dostoevsky even when the baseline name is not the paper title.

## Interactive genealogy inspector

Build the browser payload from the current evidence-first DAG and full-text
retrieval provenance. Gold labels and development evaluation files are not
inputs to this product view:

```bash
.venv-coi/bin/python scripts/07_build_inspector_data.py \
  --topic "LSM-tree structural and workload-adaptive optimization"
```

Serve the application so the inspector can also open locally retrieved PDFs
and select persistent results:

```bash
.venv-coi/bin/python scripts/09_serve_app.py --port 4174
```

Then open <http://127.0.0.1:4174/>. The inspector provides:

- three fixed-content modes: a sparse narrative genealogy, the complete
  medium/strong evidence network, and the full in-corpus citation graph;
- one optional same-research-group overlay. It only draws key-author-overlap
  relations whose two endpoints already belong to the selected mode, so it
  never adds papers or changes their layout;
- no weak/medium/strong filter burden and no product-facing automatic-path
  controls; edge types remain distinguishable through the passive legend;
- title/OpenAlex search, pan, zoom, and fit controls;
- paper metadata, local/official PDF links, and strongest incident relations;
- edge-level inspection of relation types, parent eligibility, confidence,
  sections, roles, citation markers, entities, and verbatim evidence passages;
- two cluster-free layouts: the default topology view uses DAG generations,
  weighted barycentric crossing reduction, and invisible routing nodes for
  long edges; the optional timeline view uses publication years on the x-axis;
- both layouts reserve multiple vertical lanes even when a year or generation
  contains only one or two papers, keeping edges from collapsing behind cards;
- long edges receive stable obstacle-aware lanes: routing checks every
  intermediate layer for paper-card collisions and penalizes already crowded
  tracks, avoiding the false visual impression of an A→B→C chain;
- readable initial navigation for larger graphs: compact labeled cards stay at
  a useful scale and the viewport starts around the primary spine; `Fit` is an
  explicit overview action rather than the default;
- shareable `?paper=...`, `?edge=source,target`, `?mode=evidence`, and
  `?group=1` URLs.

Legacy Run-B solution clusters and automatically derived branch artifacts
remain available for offline analysis, but neither controls the graph layout
or appears as a product-facing navigation choice.
