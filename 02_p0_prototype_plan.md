# Prototype P0 Plan
## Test Whether CoI-Agent + Science Hierarchography Can Recover a Semantic Academic Genealogy

### Status

This is a **feasibility prototype**, not a production architecture.

The purpose of P0 is to answer one question:

> Can we reuse existing code from CoI-Agent and Science Hierarchography, add only a thin integration layer, and already recover a useful approximation of the desired research-evolution tree/DAG?

If the answer is no, P0 must tell us **which layer fails** so that the next implementation can replace only the necessary components instead of rewriting everything blindly.

---

# 1. Upstream Repositories

Use the following upstream repositories:

```text
CoI-Agent
https://github.com/DAMO-NLP-SG/CoI-Agent

Science Hierarchography
https://github.com/JHU-CLSP/science-hierarchography
```

Pin the exact upstream commit used by the experiment in a lock file:

```text
upstream.lock
```

Example:

```yaml
coi_agent:
  repo: https://github.com/DAMO-NLP-SG/CoI-Agent
  commit: <resolved commit hash>

science_hierarchography:
  repo: https://github.com/JHU-CLSP/science-hierarchography
  commit: <resolved commit hash>
```

Do not develop directly inside either upstream repository.

Recommended layout:

```text
academic-genealogy-prototype/
├── upstream/
│   ├── CoI-Agent/
│   └── science-hierarchography/
│
├── src/
│   ├── schema.py
│   ├── corpus_builder.py
│   ├── semantic_adapter.py
│   ├── hierarchy_runner.py
│   ├── citation_overlay.py
│   ├── branch_inference.py
│   ├── evaluation.py
│   └── render.py
│
├── scripts/
│   ├── 00_check_upstreams.py
│   ├── 01_build_corpus.py
│   ├── 02_extract_profiles.py
│   ├── 03_run_hierarchy.py
│   ├── 04_overlay_citations.py
│   ├── 05_infer_tree.py
│   ├── 06_evaluate_gold.py
│   └── run_p0.sh
│
├── configs/
│   └── lsm_gold.yaml
│
├── data/
│   ├── raw/
│   ├── papers/
│   ├── semantic_profiles/
│   ├── hierarchy/
│   └── output/
│
├── reports/
│   └── p0_feasibility_report.md
│
└── upstream.lock
```

---

# 2. Important Architectural Decision: Do NOT Merge the Two Codebases

Treat the repositories as two upstream components with a file-based adapter between them.

Reasons:

1. Their dependency stacks are different.
2. CoI-Agent uses SciPDF Parser/GROBID and Semantic Scholar-oriented retrieval.
3. Science Hierarchography has its own embedding and clustering stack.
4. We want to determine independently which upstream component is useful.
5. A direct source-code merge would make failure attribution difficult.

For P0, prefer:

```text
CoI environment
    |
    | JSON
    v
our adapter
    |
    | JSON / embedding pickle
    v
Science Hierarchography environment
    |
    | hierarchy JSON
    v
our graph overlay + evaluation
```

Use separate environments if necessary.

Do not spend time forcing all dependencies into one environment.

---

# 3. What We Can Actually Reuse from CoI-Agent

CoI-Agent's final objective is different from ours. Its main `DeepResearchAgent` tries to construct a **linear chain of ideas** and then generate new research ideas.

We should therefore **not reuse the whole agent as our graph algorithm**.

The useful pieces are lower-level.

---

## 3.1 Reuse: Semantic Scholar retrieval

Relevant code:

```text
CoI-Agent/searcher/sementic_search.py
```

Useful functions include the Semantic Scholar Graph API search and related-paper traversal.

The repository already queries:

```text
https://api.semanticscholar.org/graph/v1/paper/search
```

and requests fields including:

```text
title
paperId
abstract
year
publicationDate
citationCount
citations
references
openAccessPdf
```

Reuse this layer to obtain:

- seed-paper metadata;
- citation lists;
- reference lists;
- publication year;
- abstracts;
- open-access PDF links.

### P0 modification rule

Do not rewrite the search client initially.

Wrap it.

Create:

```python
class CoIRetrievalAdapter:
    def resolve_paper(title_or_id) -> PaperRecord:
        ...

    def get_references(paper) -> list[PaperRecord]:
        ...

    def get_citations(paper) -> list[PaperRecord]:
        ...

    def topic_search(query, limit) -> list[PaperRecord]:
        ...
```

Our own `PaperRecord` must preserve `paperId`. Do not rely on title as the graph identifier.

---

## 3.2 Reuse: citation/reference neighbourhood discovery

Relevant code:

```text
SementicSearcher.search_related_paper_async(...)
```

This code already knows how to inspect citation/reference candidates and retrieve related papers.

However, **do not use its final single-paper selection behavior as the genealogy algorithm**.

For our use case, we want the candidate set.

P0 should use the underlying citation/reference metadata to build a local citation DAG.

Recommended corpus expansion:

```text
seed papers
   |
   +-- direct references
   |
   +-- direct citations
   |
   +-- topic search results
```

For the LSM-tree gold case, initially cap the corpus at approximately:

```text
50–150 papers
```

Do not start with thousands of papers.

P0 is evaluating structure quality, not corpus-scale performance.

---

## 3.3 Reuse: PDF parsing and text extraction

CoI-Agent already integrates:

```text
SciPDF Parser
GROBID
```

and contains methods that read article text together with references.

Reuse this path for papers whose full text is available.

However, P0 should **not require full-text parsing for every candidate paper**.

Recommended policy:

```text
Tier 1: gold / hub / high-priority papers
    -> full text

Tier 2: likely branch representatives
    -> full text if available

Tier 3: peripheral candidate papers
    -> title + abstract initially
```

This prevents PDF parsing from becoming the bottleneck of the feasibility experiment.

---

## 3.4 Reuse: structured contribution extraction prompt

Relevant file:

```text
CoI-Agent/prompts/deep_research_agent_prompts.py
```

Relevant function:

```text
get_deep_reference_prompt(...)
```

The existing prompt extracts:

```text
Background
Novelty
Contribution
Methods
Detail reason
Limitation
Experiment
Entities
Three relevant references
```

This is useful because our problem needs semantic paper representations rather than raw embeddings of the entire PDF.

### P0 direct-reuse baseline

For the first experiment, do **not immediately redesign the prompt**.

Run the existing extraction and save:

```yaml
coi_profile:
  background:
  novelty:
  contribution:
  methods:
  detail_reason:
  limitation:
  experiment:
  entities:
  selected_references:
```

This gives us a literal answer to:

> Is CoI-Agent's existing semantic representation already sufficient?

If not, that failure is useful evidence.

---

## 3.5 Optional reuse: progression explanation

Relevant function:

```text
get_deep_trend_idea_chains_prompt(...)
```

It asks an LLM to explain the historical progression among papers ordered from early to late.

Use this only as a **diagnostic summarizer for a branch that we have already inferred**.

Do not let it decide the topology.

For example:

```text
Monkey -> Dostoevsky -> LSM-Bush
```

can be passed to the prompt after the graph builder has selected that path.

Then compare its explanation with the human gold explanation.

---

## 3.6 Do NOT reuse as core logic

Do not use the following CoI behavior as the final genealogy algorithm:

```text
DeepResearchAgent.deep_research_paper_with_chain(...)
```

Reasons:

- it produces a chain rather than a DAG;
- it repeatedly chooses one next citation/reference paper;
- it has explicit `max_chain_length`;
- it is designed to obtain a useful idea-development chain, not recover all major branches;
- branch points and sibling branches are therefore structurally lost.

Also skip for P0:

```text
idea generation
novelty scoring
review agent
experiment generation
future-direction generation
Elo-style idea selection
```

They are unrelated to our objective.

---

# 4. What We Can Reuse from Science Hierarchography

For P0, focus on:

```text
science-hierarchography/SCYCHIC/
```

Do not begin with `fLMSci`.

`fLMSci` may be tested later as an alternative taxonomy generator, but it adds another LLM-heavy pipeline before we know whether the basic hierarchy signal is useful.

---

## 4.1 Reuse: structured semantic axes

Relevant file:

```text
SCYCHIC/generate.py
```

The repository defines embeddings over separate paper attributes.

Current keys include:

```text
problem.overarching problem domain
problem.challenges/difficulties
problem.research question/goal
problem.novelty of the problem
problem.knowns or prior work

solution.overarching solution domain
solution.knowns or prior work
solution.solution approach
solution.novelty of the solution

results.findings/results
results.potential impact of the results
```

This is one of the most useful parts of the project for our use case.

It means that we do not have to treat a paper as one undifferentiated embedding.

---

## 4.2 Reuse: key-specific embeddings

`SCYCHIC/generate.py` already generates embeddings independently for semantic subkeys.

Use this functionality directly.

We want to compare at least these hierarchy variants:

```text
H_problem
H_solution
H_all
```

If feasible, also test:

```text
problem.research question/goal
problem.challenges/difficulties
solution.solution approach
solution.novelty of the solution
```

The purpose is not to pick the prettiest hierarchy.

The purpose is to test:

> Which semantic axis best recovers expert-recognized research branches?

---

## 4.3 Reuse: pre-generated embedding interface

Relevant pipeline:

```text
SCYCHIC/pipeline/pipeline.py
```

The processor supports:

```text
embedding_type = subkey | key | all
embedding_key
pre_generated_embeddings_file
```

This is important because it gives us a clean extension path.

For the literal P0 baseline, use SCYCHIC's existing embedding format.

Later, if the built-in semantic keys are insufficient, we can create our own embeddings for:

```text
assumption
scope
optimization paradigm
workload model
target component
```

and feed them into the hierarchy builder without replacing the entire clustering pipeline.

---

## 4.4 Reuse: hierarchical clustering

Relevant API:

```text
process_hierarchical_clustering(...)
```

It supports multi-level clustering and clustering directions including:

```text
top_down
bottom_up
bidirectional
```

For P0:

1. begin with `top_down`;
2. use a small number of hierarchy levels;
3. do not aggressively tune cluster sizes to match the gold answer.

Recommended initial sweeps for a 50–150 paper corpus:

```text
2 levels:
    coarse branches -> sub-branches

3 levels:
    field -> branch -> local paper family
```

The exact cluster-size settings should be recorded in every run.

---

## 4.5 Reuse: cluster summaries

Use SCYCHIC's summarization mechanism to label clusters.

The cluster label should help us answer:

```text
What do the papers in this branch have in common?
```

Store both:

```yaml
cluster:
  id:
  paper_ids:
  summary:
  parent_cluster:
  level:
```

We will later compare these summaries against the expert-defined branch meanings.

---

# 5. Bridge the Two Repositories with a Canonical Schema

The two repositories do not share a data model.

Create our own minimal canonical schema.

```python
@dataclass
class PaperRecord:
    paper_id: str
    title: str
    year: int | None
    venue: str | None
    abstract: str | None
    pdf_url: str | None

    references: list[str]
    citations: list[str]

    coi_profile: dict | None
    scychic_profile: dict | None

    cluster_paths: dict[str, list[str]]
```

Persist each paper as JSON.

Example:

```yaml
paper_id: S2:<id>
title: "..."
year: 2024

references:
  - S2:...
citations:
  - S2:...

coi_profile:
  background: "..."
  novelty: "..."
  contribution: "..."
  methods: "..."
  limitation: "..."

scychic_profile:
  problem:
    overarching problem domain: "..."
    challenges/difficulties: "..."
    research question/goal: "..."
    novelty of the problem: "..."
    knowns or prior work: "..."

  solution:
    overarching solution domain: "..."
    knowns or prior work: "..."
    solution approach: "..."
    novelty of the solution: "..."

  results:
    findings/results: "..."
    potential impact of the results: "..."
```

---

# 6. Direct-Composition Baseline

This is the most important P0 experiment.

Do not add a sophisticated new semantic-relation model yet.

We first want to know how far the two repositories get us almost by themselves.

Pipeline:

```text
Step 1
CoI retrieval
    ->
candidate paper corpus + citation/reference graph

Step 2
CoI semantic extraction
    ->
Background / Novelty / Contribution / Methods / Limitation

Step 3
minimal field adapter
    ->
SCYCHIC-compatible semantic JSON

Step 4
SCYCHIC
    ->
semantic hierarchy

Step 5
our thin overlay
    ->
citation edges + publication time on top of hierarchy

Step 6
simple deterministic branch inference
    ->
candidate semantic evolution tree

Step 7
compare with human gold case
```

---

# 7. Minimal CoI -> SCYCHIC Field Adapter

For the literal baseline, do not call another LLM solely to rewrite the profile.

Map fields mechanically.

Initial mapping:

```text
CoI.background
    ->
problem.knowns or prior work

CoI.limitation
    ->
problem.challenges/difficulties

CoI.contribution
    ->
problem.research question/goal
    + results.potential impact of the results

CoI.methods
    ->
solution.solution approach

CoI.novelty
    ->
solution.novelty of the solution

CoI.detail_reason
    ->
solution.overarching solution domain

CoI.experiment
    ->
results.findings/results
```

Some mappings are imperfect.

That is intentional.

P0 needs to reveal whether a small amount of glue is enough.

Record missing fields instead of hallucinating values.

---

# 8. Citation Overlay

SCYCHIC produces a semantic hierarchy, not a research-evolution graph.

Add a thin overlay.

For every paper:

```text
paper
 -> semantic cluster path
 -> year
 -> citations/references inside corpus
```

Then construct a local DAG containing only citation edges between corpus papers where:

```text
source.year <= target.year
```

Normalize direction as:

```text
earlier paper -> later paper
```

even if the source API represents the citation in the reverse direction.

Do not show all edges in the final visualization.

Keep the full graph in JSON.

---

# 9. P0 Branch-Point Heuristic

We need a minimal bridge from:

```text
hierarchy + citations
```

to:

```text
evolution tree
```

Implement only a simple deterministic heuristic.

For every internal semantic cluster:

1. identify its child clusters;
2. find papers published before or near the earliest papers of those children;
3. find papers cited by papers from two or more child clusters;
4. rank those candidate predecessors.

Suggested P0 hub score:

```text
hub_score =
    descendant_branch_coverage
    * log(1 + in_corpus_descendant_citations)
```

where:

```text
descendant_branch_coverage
=
number of sibling semantic branches containing later papers that cite or descend from this paper
```

Do not use global citation count as the primary score.

A paper with high citations but no branch-forming role should not automatically become a hub.

---

# 10. P0 Parent Selection Within a Branch

For a paper `P`:

1. consider only earlier papers that `P` directly cites;
2. prioritize candidates in the same semantic branch;
3. among them, prefer the most recent meaningful predecessor;
4. if no same-branch predecessor exists, allow a parent from the parent semantic cluster.

Baseline parent score:

```text
parent_score =
    semantic_cluster_match
    + temporal_proximity
    + local_citation_support
```

This produces one dominant parent for visualization.

Keep all citation relations separately so the underlying representation remains a DAG.

---

# 11. P0 Split Explanation

Do not build a general semantic edge classifier yet.

For each detected split, generate a simple contrast report from the two child-cluster summaries:

```yaml
split:
  hub:
  branch_a:
  branch_b:

  contrast:
    problem:
    method:
    scope:
    stated_limitation:
```

For P0, this contrast may be generated by a single LLM call over:

- parent/hub profile;
- branch A summary + representative papers;
- branch B summary + representative papers.

This is the only new semantic prompt that P0 should add.

The prompt must be constrained to answer:

```text
What changed?
```

not:

```text
Invent a narrative connecting these papers.
```

Require evidence paper titles in the result.

---

# 12. LSM-Tree Gold Case: Corrected Baseline

This benchmark must not encode the previously incorrect chain.

The earlier shorthand:

```text
Monkey -> Rusty -> Camel -> ...
```

must be removed.

Correct names:

```text
RusKey
CAMAL
ArceKV
```

not:

```text
Rusty
Camel
RKV
```

---

## 12.1 Core papers to seed or force-include

Use at least the following papers.

### Foundational root

```text
The Log-Structured Merge-Tree (LSM-tree)
Patrick O'Neil, Edward Cheng, Dieter Gawlick, Elizabeth O'Neil
1996
```

### Classical analytical / structural line

```text
Monkey: Optimal Navigable Key-Value Store
Niv Dayan, Manos Athanassoulis, Stratos Idreos
SIGMOD 2017
```

```text
Dostoevsky: Better Space-Time Trade-Offs for LSM-Tree Based
Key-Value Stores via Adaptive Removal of Superfluous Merging
Niv Dayan, Stratos Idreos
SIGMOD 2018
```

```text
The Log-Structured Merge-Bush & the Wacky Continuum
Niv Dayan, Stratos Idreos
SIGMOD 2019
```

### Compaction-granularity direction

```text
Spooky: Granulating LSM-Tree Compactions Correctly
Niv Dayan et al.
PVLDB 2022
```

Do **not** force Spooky to be a direct child of Dostoevsky or LSM-Bush.
Its relationship should be recovered from evidence.

### Dynamic / learned structural adaptation

```text
Learning to Optimize LSM-trees:
Towards A Reinforcement Learning based Key-Value Store
for Dynamic Workloads

System: RusKey
Dingheng Mo, Fanchao Chen, Siqiang Luo, Caihua Shan
PACMMOD 2023
```

RusKey:

- targets dynamically changing workloads;
- uses reinforcement learning to guide structural transformations;
- introduces FLSM-tree for efficient transitions between compaction policies.

It should **not** be renamed Rusty.

### Expanded structural-design space

```text
Structural Designs Meet Optimality:
Exploring Optimized LSM-tree Structures in a Colossal Configuration Space

System: Moose
Junfeng Liu, Fan Wang, Dingheng Mo, Siqiang Luo
PACMMOD 2024
```

This is useful because ArceKV later uses Moose as an important workload-aware structural baseline.

### Active-learning instance optimization

```text
CAMAL: Optimizing LSM-trees via Active Learning
Weiping Yu, Siqiang Luo, Zihao Yu, Gao Cong
PACMMOD 2024
```

CAMAL:

- uses active learning;
- couples learning with analytical cost models;
- performs instance-level LSM parameter tuning;
- supports a dynamic mode.

Important gold constraint:

```text
RusKey -> CAMAL
```

must **not** be hard-coded as a parent-child lineage.

CAMAL explicitly recognizes RusKey as prior ML/RL work, but it defines a different optimization approach: active-learning-based instance optimization rather than RL-guided structural transition.

A good genealogy system may place them under a broader learned/adaptive optimization family while keeping them as distinct sub-branches.

### Growth / structural evolution line

```text
How to Grow an LSM-tree?
Towards Bridging the Gap Between Theory and Practice

Dingheng Mo, Siqiang Luo, Stratos Idreos
PACMMOD / SIGMOD 2025
```

Include this paper in the benchmark corpus, but do not hard-code where it belongs.
Let the prototype decide whether it aligns more strongly with the analytical structural line, the local lab line, or both.

### Dynamic compaction / continuous transition optimization

```text
ArceKV:
Towards Workload-driven LSM-compactions for Key-Value Store
Under Dynamic Workloads

Junfeng Liu, Haoxuan Xie, Siqiang Luo
2025 technical report; PVLDB 2026
```

ArceKV is especially important for the gold case.

Its problem framing explicitly analyzes transition limitations of:

```text
Dostoevsky
RusKey
```

and argues for shifting the optimization target from:

```text
reaching a precomputed target LSM structure
```

to:

```text
continuously optimizing performance during workload transitions
```

It introduces:

```text
ElasticLSM
Arce
```

This provides a much stronger candidate lineage relation:

```text
RusKey -> ArceKV
```

with semantic label approximately:

```text
ADDRESSES_LIMITATION /
CHANGES_TRANSITION_MODEL
```

than any forced:

```text
CAMAL -> ArceKV
```

edge.

CAMAL appears in ArceKV's references, but P0 should not assume it is ArceKV's direct intellectual parent.

---

# 13. Preliminary Gold Structure

Do **not** treat this drawing as an immutable truth.
It is a benchmark hypothesis to be refined manually after inspecting the papers.

A more defensible starting graph is:

```text
O'Neil LSM-tree
       |
     Monkey
       |
       +-----------------------------+
       |                             |
       v                             v
 Dostoevsky                     CAMAL
       |                   active-learning /
       |                   hybrid model tuning
       |
       +------> LSM-Bush
       |
       +------> RusKey
                  |
                  | dynamic structural transition
                  v
                ArceKV
```

Additional cross-cutting nodes:

```text
Spooky
    -> compaction granularity axis

Moose
    -> expanded structural configuration/design-space axis
    -> important predecessor/baseline for ArceKV

How to Grow an LSM-tree?
    -> should be discovered rather than manually attached
```

The important property of this benchmark is that the correct result is **not a clean tree**.

For example, RusKey is simultaneously related to:

- structural/compaction-policy work;
- dynamic workload adaptation;
- machine-learning-based optimization.

This is exactly why the internal representation should be a DAG.

---

# 14. Gold Constraints

Create:

```text
configs/lsm_gold.yaml
```

with three kinds of annotations.

## 14.1 Must-find papers

```yaml
must_find:
  - LSM-tree
  - Monkey
  - Dostoevsky
  - LSM-Bush
  - Spooky
  - RusKey
  - Moose
  - CAMAL
  - How to Grow an LSM-tree?
  - ArceKV
```

## 14.2 Expected strong relationships

Initial examples:

```yaml
expected_edges:
  - source: Monkey
    target: Dostoevsky
    relation_family:
      - EXTENDS
      - CHANGES_COMPACTION_DESIGN

  - source: Dostoevsky
    target: RusKey
    relation_family:
      - EXTENDS_DYNAMIC_ADAPTATION
      - CHANGES_TRANSITION_METHOD

  - source: RusKey
    target: ArceKV
    relation_family:
      - ADDRESSES_LIMITATION
      - CHANGES_TRANSITION_MODEL
```

These labels are deliberately broad for P0.

## 14.3 Forbidden hard-coded relationships

```yaml
must_not_force:
  - source: RusKey
    target: CAMAL
    reason: >
      Related ML/adaptive work, but not a simple parent-child technical lineage.

  - source: CAMAL
    target: ArceKV
    reason: >
      Do not infer a direct lineage merely because both are from a related lab/topic.

  - source: Dostoevsky
    target: Spooky
    reason: >
      Do not force a direct parent relation without semantic/citation evidence.
```

The benchmark should test whether the system distinguishes:

```text
related
```

from:

```text
inherits from
```

---

# 15. Run Matrix

P0 should run multiple controlled variants.

## Run A: citation-only baseline

Input:

```text
CoI corpus + citation graph
```

No SCYCHIC clustering.

Purpose:

> How much does citation topology alone recover?

---

## Run B: SCYCHIC problem hierarchy

```text
embedding_key = problem
```

Overlay citations afterward.

Purpose:

> Do problem formulations recover meaningful schools?

---

## Run C: SCYCHIC solution hierarchy

```text
embedding_key = solution
```

Purpose:

> Do methodological differences recover the branches better?

---

## Run D: SCYCHIC all-fields hierarchy

```text
embedding_type = all
```

Purpose:

> Is the complete semantic profile better or does it blur orthogonal branch axes?

---

## Run E: direct CoI-profile mapping

Use the mechanical CoI -> SCYCHIC mapping defined earlier.

Purpose:

> Can the existing CoI extraction be reused without a new paper-analysis schema?

---

# 16. Evaluation Metrics

P0 does not need a sophisticated benchmark framework.

Produce a table for every run.

```text
Metric                          Score / Notes
---------------------------------------------------------
Must-find paper recall
Major branch purity
Major branch coverage
Correct hub recovery
Expected edge recall
Forbidden-edge count
Within-branch ordering quality
Split-explanation quality
Manual expert rating
```

Suggested manual scores:

```text
0 = wrong
1 = partially useful
2 = mostly correct
3 = expert-quality
```

Evaluate separately:

```text
Topology
Branch semantics
Paper coverage
Split explanation
```

Do not collapse everything into one scalar score initially.

---

# 17. Required Output Files

Every run should produce:

```text
data/output/<run_id>/
├── papers.json
├── citation_graph.json
├── hierarchy.json
├── evolution_dag.json
├── dominant_tree.json
├── tree.dot
├── tree.svg
└── evaluation.json
```

Use Graphviz for P0 visualization.

Do not build a web UI yet.

Optional Mermaid output:

```text
tree.mmd
```

is useful for quick inspection in Markdown.

---

# 18. Evolution DAG Schema

Use a stable output contract even if P0 inference is crude.

```yaml
nodes:
  - id:
    title:
    year:
    branch_path:
    semantic_profile:
    hub_score:
    is_hub:

edges:
  - source:
    target:
    citation_exists:
    relation:
    explanation:
    evidence:
    confidence:

branches:
  - id:
    parent_branch:
    label:
    summary:
    representative_papers:
    split_hub:
    split_reason:
```

This lets us replace individual algorithms later without changing the downstream UI.

---

# 19. Execution Order for Codex

Codex should execute the project in this order.

### Phase 0A — Verify upstream repositories

1. Clone both repositories.
2. Record commit hashes.
3. Inspect their current README and dependency files.
4. Run their smallest available sanity checks/examples independently.
5. Do not patch upstream code yet.

Deliver:

```text
reports/upstream_check.md
```

containing:

- commit hashes;
- setup status;
- failures;
- required API keys;
- environment conflicts.

---

### Phase 0B — Implement canonical schema

Create:

```text
src/schema.py
```

with serializable models for:

```text
PaperRecord
SemanticProfile
CitationEdge
HierarchyCluster
EvolutionEdge
Branch
```

Add round-trip JSON tests.

---

### Phase 0C — Implement CoI retrieval adapter

Create:

```text
src/corpus_builder.py
```

Reuse CoI's Semantic Scholar search layer.

Requirements:

- resolve every seed paper;
- preserve Semantic Scholar paper ID;
- retrieve references and citations;
- filter by topic relevance;
- cache raw API responses;
- never repeatedly download the same PDF;
- export canonical JSON.

Do not implement genealogy inference here.

---

### Phase 0D — Build LSM corpus

Use `configs/lsm_gold.yaml`.

Start with all must-find papers as seeds.

Expand one citation hop plus topic-search candidates.

Cap the corpus.

Produce:

```text
data/papers/lsm_corpus.json
```

Before continuing, report any must-find paper that failed resolution.

---

### Phase 0E — Extract CoI semantic profiles

For high-priority papers:

1. obtain full text where available;
2. call the existing CoI extraction prompt;
3. save its output without rewriting the semantics;
4. store exact raw LLM response for debugging.

Produce:

```text
data/semantic_profiles/coi/
```

---

### Phase 0F — Convert to SCYCHIC input

Create:

```text
src/semantic_adapter.py
```

Implement the mechanical mapping defined in Section 7.

No second semantic LLM transformation in the direct baseline.

Produce one SCYCHIC-compatible JSON file per paper.

---

### Phase 0G — Run SCYCHIC

Run the hierarchy pipeline for:

```text
problem
solution
all
```

and relevant subkeys.

Store every configuration.

Do not manually tune until the gold graph appears.

Use a small sweep with fixed random seeds.

---

### Phase 0H — Overlay citation graph

Create:

```text
src/citation_overlay.py
```

Combine:

```text
SCYCHIC cluster path
publication year
in-corpus citation edges
```

Export the full DAG.

---

### Phase 0I — Infer dominant lineage

Create:

```text
src/branch_inference.py
```

Implement only the simple heuristics in Sections 9 and 10.

No learned model.

No general semantic relation classifier.

---

### Phase 0J — Render

Create:

```text
src/render.py
```

Output Graphviz DOT + SVG.

Requirements:

- x-axis or rank should broadly respect publication time;
- cluster/branch labels visible;
- hub papers visually marked;
- dominant lineage edges emphasized;
- cross-links retained but visually secondary;
- avoid showing every citation edge.

---

### Phase 0K — Evaluate

Create:

```text
src/evaluation.py
```

Compare the result with `lsm_gold.yaml`.

Produce:

```text
reports/p0_feasibility_report.md
```

The report must answer:

1. Did citation-only work?
2. Did SCYCHIC recover meaningful branches?
3. Which semantic axis worked best?
4. Did CoI extraction provide enough information?
5. Were hubs recovered?
6. Were branch points recovered?
7. Were forbidden parent-child relationships incorrectly inferred?
8. Can the split reason be explained correctly?
9. Which upstream components should be kept?
10. Which components need to be rewritten?

---

# 20. Decision Rules After P0

The prototype should end with an explicit architecture decision.

## Case A — Hierarchy is good, lineage is bad

Symptoms:

- SCYCHIC clusters match expert branches;
- branch summaries are meaningful;
- citation overlay does not recover parent/child relationships.

Decision:

```text
KEEP:
    SCYCHIC semantic representation
    SCYCHIC clustering

REWRITE:
    branch-point detection
    semantic edge inference
    evolution-DAG construction
```

This is a likely outcome.

---

## Case B — CoI retrieval works, CoI semantic extraction is too weak

Symptoms:

- corpus quality is good;
- citations/references are useful;
- extracted Background/Novelty/Methods fields fail to distinguish assumption/scope.

Decision:

```text
KEEP:
    CoI Semantic Scholar adapter
    CoI PDF parsing

REWRITE:
    paper semantic schema
    extraction prompts
```

Add explicit fields such as:

```text
assumptions
scope
workload
optimization objective
target component
technical predecessor
claimed limitation of predecessor
```

---

## Case C — SCYCHIC taxonomy itself is unstable

Symptoms:

- small cluster-size changes radically change branches;
- branches mostly reflect vocabulary rather than technical schools;
- expert branches are mixed even using solution/problem-specific embeddings.

Decision:

```text
REPLACE:
    taxonomy construction

WITH:
    custom multi-aspect clustering
    or LLM-guided branch induction
```

Keep the semantic profile data if it is still useful.

---

## Case D — CoI retrieval stack is cumbersome

Symptoms:

- GROBID/PDF dependencies dominate setup;
- Semantic Scholar wrapper is brittle;
- corpus expansion misses obvious papers;
- title-based resolution causes identity problems.

Decision:

```text
REPLACE:
    CoI retrieval layer

KEEP IF USEFUL:
    its prompt patterns only
```

Write a small first-party academic-graph client instead.

---

## Case E — Direct composition works surprisingly well

If the prototype recovers:

- correct major branches;
- correct hubs;
- most expected predecessor relations;
- no major false parent-child edges;
- technically meaningful split explanations;

then keep the two upstream components and focus the next iteration on:

```text
semantic edge classification
DAG cleanup
interactive visualization
larger-domain evaluation
```

---

# 21. Expected Outcome

The working hypothesis for P0 should be:

> **The two repositories are likely sufficient for corpus construction + paper semantics + taxonomy, but insufficient for the core semantic evolution DAG.**

More specifically:

CoI-Agent is likely useful for:

```text
retrieval
citation/reference traversal
PDF parsing
paper-level contribution extraction
```

Science Hierarchography is likely useful for:

```text
multi-aspect semantic representation
embedding generation
hierarchical clustering
cluster summarization
```

The likely missing first-party components are:

```text
semantic predecessor inference
branch-point detection
typed evolution edges
split-reason extraction
DAG simplification
```

P0 exists to verify this hypothesis with evidence rather than assume it.

---

# 22. Licensing / Reuse Precaution

CoI-Agent currently declares an Apache-2.0 license in its repository.

For Science Hierarchography, the repository root should be checked again at implementation time for an explicit software license before copying or redistributing its source.

Until that is confirmed:

- clone it as a separate upstream dependency;
- invoke it from our wrapper;
- do not vendor its source into our project;
- do not redistribute modified copies.

This does not block a local feasibility experiment.

---

# 23. Definition of Done

P0 is complete only when Codex produces all of the following:

```text
[ ] both upstream repositories run independently
[ ] exact upstream commits are pinned
[ ] LSM gold corpus is built
[ ] must-find paper resolution is reported
[ ] CoI semantic extraction is cached
[ ] SCYCHIC runs for multiple semantic axes
[ ] citation graph is overlaid on hierarchy
[ ] a candidate evolution DAG is generated
[ ] a simplified tree/SVG is rendered
[ ] gold constraints are evaluated
[ ] false edges are explicitly reported
[ ] a written keep/rewrite decision is produced
```

The objective is **not** to prove that the two repositories can be combined.

The objective is to obtain a rigorous answer to:

> **Which parts can be reused, and where must we build our own academic-genealogy logic?**
