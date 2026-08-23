# Evidence-first genealogy prototype

Run date: 2026-08-23.

## Architectural change

The genealogy decision layer no longer selects one cited predecessor by
semantic-cluster similarity and temporal proximity. OpenAlex citations enter
as weak candidates. Section-aware full-text evidence can promote an edge to
medium or strong. Key-author overlap can independently promote an association
to medium, but never makes it parent-eligible. Strong edges enter the primary genealogy only when their
typed relations establish inheritance; clustering remains downstream for
branch grouping and visual layout.

The new edge contract contains:

```text
association_level: weak | medium | strong
relation_types: CITES | ADDRESSES_LIMITATION | EXTENDS |
                USES_CONCEPT_FROM | METHOD_DEPENDENCY |
                EXPLICIT_BASELINE | IMPLICIT_BASELINE |
                KEY_AUTHOR_OVERLAP | SAME_RESEARCH_GROUP
parent_eligible: boolean
evidence_details: section, section type, passage, citation marker,
                  entity, source PDF, confidence
```

## Real PDF run

Inputs:

- Dostoevsky PDF;
- RusKey PDF;
- CAMAL PDF, recovered from arXiv and title-validated;
- ArceKV PDF, recovered from the Siqiang Luo group publication page after its
  OpenAlex record provided no PDF URL;
- the existing 150-paper OpenAlex corpus and 1,233-edge citation overlay.

The fallback resolver discovered the official PVLDB PDF from the publication
page's JavaScript data. It validated the first-page title at 1.0, stored the
file locally, and recorded the final URL, source page, failed candidates,
timestamp, and SHA-256 digest in the retrieval index.

The local PDF path parsed 53 Dostoevsky, 68 RusKey, 91 CAMAL, and 110 ArceKV
bibliography entries and resolved 14, 30, 35, and 40 of them, respectively, to
papers inside the bounded corpus. Unresolved entries remain unresolved; they
are not guessed.

The extractor produced 109 full-text evidence-backed paper pairs:

- 86 weak;
- 14 medium;
- 9 strong.

All 150 papers now have ordered OpenAlex authorships. First-page parsing
recovered Siqiang Luo as corresponding author for both RusKey and CAMAL after
OpenAlex omitted both flags. Key-author comparison produced 125 supplemental
research-group associations.

After merging all evidence with the OpenAlex overlay, the 1,315-edge graph contains:

- 1,171 weak edges;
- 135 medium edges;
- 9 strong associations, of which 4 are parent-eligible primary genealogy
  edges;
- zero chronology violations;
- zero forbidden forced edges.

## RusKey acceptance case

The system recovered:

```text
Dostoevsky -> RusKey
association_level: strong
parent_eligible: true
relation_types:
  ADDRESSES_LIMITATION
  CITES
  EXTENDS
  IMPLICIT_BASELINE
  METHOD_DEPENDENCY
  USES_CONCEPT_FROM
```

The evidence chain includes:

1. RusKey's Introduction discussion of Dostoevsky's static-workload and
   transition limitations;
2. its Background attribution of the compaction policy to Dostoevsky;
3. its Evaluation comparison against Fluid LSM-tree policy settings and
   Lazy-Leveling;
4. the Dostoevsky passages establishing Fluid LSM-tree and Lazy Leveling as
   originating entities.

A second gold strong edge is `Monkey -> Dostoevsky`, supported by Dostoevsky's
Introduction, the method passage that generalizes Monkey's Bloom-filter
allocation to the Fluid LSM-tree design space, and the explicit evaluation
baseline. Multiple parents are retained; the pipeline does not collapse them
to one similarity-selected predecessor.

## CAMAL association case

The system now recovers:

```text
RusKey -> CAMAL
association_level: medium
relation: ADDRESSES_LIMITATION
parent_eligible: false
relation_types:
  ADDRESSES_LIMITATION
  CITES
  EXTENDS
  KEY_AUTHOR_OVERLAP
  SAME_RESEARCH_GROUP
```

CAMAL's Background discusses RusKey's level-based compaction parameters and
their sampling-cost limitation. That logical evidence remains the primary
relation at confidence 0.72. The verified shared corresponding author is shown
as supplemental research-group evidence at confidence 0.60; it does not force
the pair into the primary genealogy.

## ArceKV acceptance case

The recovered full text promotes:

```text
RusKey -> ArceKV
association_level: strong
parent_eligible: true
relation_types:
  ADDRESSES_LIMITATION
  CITES
  EXPLICIT_BASELINE
  EXTENDS
```

The auditable chain combines ArceKV's Introduction discussion of FLSM/RusKey's
dependence on sufficient updates and its resulting responsiveness limitation
with ArceKV's Evaluation section, which explicitly includes RusKey as an
artifact-backed state-of-the-art baseline. CAMAL is also correctly retained as
a strong experimental comparison, but it is not parent-eligible because the
Introduction/Preliminaries inheritance condition is absent.

All three configured gold lineage pairs now have full-text evidence and are
strong, parent-eligible, dominant edges. Expected-edge, strong-association,
full-text-evidence, and parent-eligible recall are all 1.0. The graph still has
zero forbidden forced edges and zero chronology violations.
