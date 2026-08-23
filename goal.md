# Academic Research Genealogy Mapping
## Motivation, Problem Definition, and Target Output

### 1. Motivation

Background research is often presented as a flat collection of related papers, a chronological reading list, or a citation graph. These representations are useful for discovering papers, but they do not directly answer the questions that matter most when trying to understand a mature research area:

- Where did the major research lines originate?
- Which papers acted as turning points or intellectual hubs?
- At what point did one line split into multiple branches?
- What exactly caused the split?
- Are two branches competing approaches to the same problem, or are they orthogonal because they make different assumptions or address different scopes?
- Which later papers truly inherit a technical idea, and which papers merely cite or compare against it?
- Which papers are representative landmarks of a branch, rather than simply highly cited papers?
- How did branches evolve, merge, disappear, or become active frontiers?

The desired system should reconstruct the **intellectual genealogy of a research topic** rather than only retrieve relevant literature.

The central intuition is that research development has structure. A new paper normally does not appear in isolation. It inherits some combination of:

- a problem definition,
- a set of assumptions,
- a scope,
- a system or algorithmic model,
- a methodology,
- an optimization objective,
- an evaluation setting,
- and limitations exposed by earlier work.

A meaningful literature map should recover these relationships explicitly.

---

## 2. Core Goal

Given a research topic and optionally a small number of seed papers, automatically reconstruct a **semantic research-evolution graph** that explains how the topic developed over time.

The output should be understandable as a tree when the structure is simple, but the internal representation should be a **directed acyclic graph (DAG)** because a paper may inherit ideas from more than one research line.

The system should identify:

1. **Foundational papers**
   - Papers that define the problem, architecture, model, or design space from which later work develops.

2. **Major hubs**
   - Papers that substantially redirect later work or become a common predecessor for multiple important descendants.

3. **Research branches**
   - Groups of papers that share a coherent technical direction.

4. **Branch points**
   - The paper or conceptual point at which later work diverges into meaningfully different directions.

5. **Split reasons**
   - A concise technical explanation of *why* two branches diverge.

6. **Lineage within each branch**
   - Which work extends, relaxes, generalizes, replaces, or criticizes which predecessor.

7. **Cross-branch relationships**
   - Cases where two lines are orthogonal, complementary, competing, or later recombined.

8. **Current frontiers**
   - Recent papers or active sub-branches that represent the latest development of each line.

The final result should answer not only **“what papers are related?”** but also:

> **“How did the technical ideas in this field evolve, and why did the field split into the branches that exist today?”**

---

## 3. Desired Representation

### 3.1 Internal representation: semantic evolution DAG

Each paper is a node.

Each directed edge means that the later paper has a meaningful intellectual relationship to the earlier paper. Citation is useful evidence, but citation alone is not sufficient to create an edge.

A paper may have multiple parents.

Example:

```text
                           Paper A
                              |
                         Paper B
                        /       \
                       /         \
                  Paper C       Paper D
                     |            |
                  Paper E      Paper F
                       \         /
                         Paper G
```

Paper G may legitimately inherit ideas from both branches. The representation must preserve this rather than forcing every paper to have exactly one parent.

### 3.2 Human-facing representation: simplified research tree

For visualization, the DAG may be projected into a cleaner dominant-lineage tree:

```text
Foundational idea
       |
   Key hub
   /     \
Branch A  Branch B
  |          |
 A1         B1
  |          |
 A2         B2
```

Secondary relationships can be shown as lighter cross-links.

The visual hierarchy should prioritize interpretability over displaying every citation.

---

## 4. What Constitutes a Research Branch?

A branch must be defined by a **technical distinction**, not merely by paper similarity.

Possible branch axes include:

- different problem formulations;
- different assumptions;
- static vs. dynamic settings;
- exact vs. approximate solutions;
- centralized vs. distributed architectures;
- analytical optimization vs. learning-based optimization;
- online vs. offline optimization;
- different data models;
- different hardware assumptions;
- different workload assumptions;
- different optimization objectives;
- different system scopes;
- different components being optimized;
- different guarantees;
- different evaluation regimes.

Two branches may be highly related at the topic level while remaining largely orthogonal technically.

For every detected branch, the system should therefore produce both:

```text
Branch label: <short technical description>
Branch definition: <the property that makes papers belong to this branch>
```

For every split:

```text
Split point: <paper or conceptual predecessor>

Branch A:
    <technical direction>

Branch B:
    <technical direction>

Split reason:
    <specific assumption / scope / methodology / objective that differs>
```

---

## 5. Paper-Level Semantic Profile

A citation graph alone cannot recover the desired structure. Each important paper should therefore be represented using a structured semantic profile.

Minimum fields:

```yaml
paper:
  title:
  year:
  venue:

problem:
  problem_statement:
  prior_limitation:
  research_goal:

scope:
  target_system_or_component:
  workload_or_setting:
  included_cases:
  excluded_cases:

assumptions:
  - assumption_1
  - assumption_2

method:
  paradigm:
  core_technique:
  main_design_choices:

objective:
  optimization_target:
  constraints:

contribution:
  key_insight:
  claimed_novelty:
  main_result:

relation_to_prior_work:
  claimed_predecessors:
  important_baselines:
  limitations_of_predecessors:
```

The schema should remain extensible because different academic fields may require different dimensions.

---

## 6. Semantic Edge Types

The target graph should distinguish different kinds of intellectual inheritance.

Candidate edge types:

```text
EXTENDS
GENERALIZES
SPECIALIZES
RELAXES_ASSUMPTION
CHANGES_ASSUMPTION
CHANGES_SCOPE
CHANGES_METHOD
CHANGES_OBJECTIVE
REPLACES_COMPONENT
ADDRESSES_LIMITATION
COMBINES
APPLIES_TO_NEW_DOMAIN
CONTRADICTS
REINTERPRETS
PARALLEL_TO
```

An edge should contain evidence:

```yaml
edge:
  source:
  target:
  relation:
  explanation:
  evidence:
    - paper_section_or_citation_context
  confidence:
```

The system should explicitly separate:

```text
A cites B
```

from:

```text
A technically extends B
```

The first is bibliographic evidence. The second is the relationship we ultimately want to infer.

---

## 7. Hub and Branch-Point Semantics

A highly cited paper is not automatically a hub.

A paper is an important **intellectual hub** when later papers inherit a substantial technical idea from it and multiple meaningful lines can be traced back to it.

Signals may include:

- many later papers directly building on its formulation;
- descendants appearing in multiple semantic branches;
- later papers repeatedly describing it as a predecessor or baseline;
- introduction of a reusable abstraction, design space, or methodology;
- a clear change in the vocabulary or assumptions used by later work.

A **branch point** may be:

1. a specific paper;
2. a pair or small set of contemporaneous papers;
3. a conceptual transition that cannot be attributed to one paper alone.

The system must allow all three cases.

---

## 8. Desired User Experience

### Input

At minimum:

```yaml
topic: "<research topic>"
```

Optionally:

```yaml
seed_papers:
  - "<paper 1>"
  - "<paper 2>"

time_range:
  start:
  end:

scope_notes:
  - "<optional researcher constraints>"
```

### Output A: Overview

A concise explanation of:

- the origin of the field;
- the main trunk;
- major branch points;
- the current major schools/directions;
- the most important papers within each branch.

### Output B: Evolution graph

A visual tree/DAG containing:

- paper title or short name;
- year;
- branch membership;
- hub markers;
- semantic edge type;
- branch labels;
- split reasons.

### Output C: Branch cards

For every major branch:

```yaml
branch:
  name:
  origin:
  core_assumption:
  scope:
  methodology:
  key_papers:
  internal_lineage:
  relationship_to_other_branches:
  current_frontier:
```

### Output D: Evidence

Every inferred relationship should be inspectable.

The user should be able to ask:

> Why did the system connect Paper A to Paper B?

and receive the supporting evidence from the papers.

---

## 9. What the System Is NOT Trying to Build

This project is not primarily:

- a general paper search engine;
- a recommendation system;
- a citation-count dashboard;
- a generic paper similarity graph;
- a bibliography manager;
- a flat topic taxonomy;
- a chronological list of publications;
- a visualization of all citations.

Those can be useful intermediate components, but they are not the target.

A taxonomy answers:

> “Which papers belong to similar categories?”

A citation graph answers:

> “Who cites whom?”

The target system answers:

> **“How did one technical idea evolve into different research lines, and what conceptual change caused each split?”**

---

## 10. Evaluation Philosophy

The system should initially be evaluated on research areas for which an expert can manually construct a reliable reference genealogy.

For each benchmark topic, create a human-curated gold graph containing:

- must-find papers;
- known hubs;
- known major branches;
- expected branch definitions;
- important predecessor relationships;
- relationships that must **not** be inferred;
- expected split explanations.

Evaluation should measure at least five dimensions.

### 10.1 Paper coverage

Did the system recover the important papers?

### 10.2 Branch quality

Do papers grouped into a branch actually share the intended technical property?

### 10.3 Hub and split accuracy

Did the system identify the correct intellectual hubs and branch points?

### 10.4 Lineage accuracy

Are important predecessor/descendant relationships correct?

### 10.5 Explanation accuracy

Does the generated split reason match an expert's explanation of the difference in assumptions, scope, or methodology?

A beautiful visualization is not useful if these five properties are wrong.

---

## 11. Success Criteria for an Initial System

A first useful system does not need to perfectly reconstruct an entire research field.

It is successful if, for a carefully scoped topic, it can:

1. recover most expert-identified landmark papers;
2. organize them into the major technical branches;
3. identify the most important branch points;
4. recover the dominant within-branch evolution;
5. explain branch differences using technically meaningful language;
6. provide evidence for the inferred relationships;
7. avoid turning the visualization into a dense citation hairball.

The primary milestone is **semantic correctness**, not UI polish.

---

## 12. Long-Term Vision

The long-term target is a research background-analysis system in which a researcher can provide a topic and obtain a navigable intellectual map such as:

```text
                         Foundational idea
                               |
                           Key framework
                          /             \
                         /               \
                Branch A                 Branch B
           assumption/model X      assumption/model Y
                  |                       |
              Paper A1                Paper B1
                  |                       |
              Paper A2                Paper B2
                   \                     /
                    \------ Paper C ----/
```

Each edge and branch should answer:

- what was inherited;
- what was changed;
- why the change mattered;
- and what new research line resulted.

That is the core product goal.
