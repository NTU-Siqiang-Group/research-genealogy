# Academic Genealogy P0

This workspace implements an evidence-first academic genealogy prototype.
OpenAlex supplies the corpus and the weak citation-candidate graph. Local full
text supplies section-aware direct-discussion, baseline, method-dependency, and
entity-provenance evidence. Those evidence records determine genealogy edges.
SCYCHIC clustering is retained only for optional branch grouping and display;
it no longer chooses paper parents.

The two upstream repositories are pinned in `upstream.lock` and are not patched.

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

Serve the repository root so the inspector can also open locally retrieved
PDFs:

```bash
.venv-coi/bin/python -m http.server 4174 --bind 127.0.0.1
```

Then open <http://127.0.0.1:4174/web/>. The inspector provides:

- a default 19-paper technical genealogy containing logical medium and strong
  relations, with the transitively reduced dominant DAG emphasized as its
  primary spine;
- automatically discovered lineage components and branch cones derived only
  from strong, parent-eligible evidence edges;
- separate evidence-map and all-corpus modes;
- weak/medium/strong relation layers, with weak citations disabled by default;
- standalone same-research-group links are a separate, disabled-by-default
  layer; logical medium relations remain visible and retain priority when both
  evidence types occur on the same paper pair;
- title/OpenAlex search, automatic-path focus, pan, zoom, and fit controls;
- paper metadata, automatic-path membership, local/official PDF links, and
  strongest incident relations;
- edge-level inspection of relation types, parent eligibility, confidence,
  sections, roles, citation markers, entities, and verbatim evidence passages;
- a cluster-free weighted layered layout: chronology defines horizontal
  layers, while repeated weighted barycentric sweeps order nodes to reduce
  crossings, giving primary edges much more influence than supplemental ones;
- readable initial navigation for larger graphs: compact labeled cards stay at
  a useful scale and the viewport starts around the primary spine; `Fit` is an
  explicit overview action rather than the default;
- shareable `?paper=...`, `?edge=source,target`, and `?mode=evidence` URLs.

Legacy Run-B solution clusters remain in archived experiment artifacts but no
longer control the graph layout or appear in the product UI. Automatic paths
are navigation aids, not benchmarks or hard partitions; papers may belong to
multiple branch cones after a later merge.
