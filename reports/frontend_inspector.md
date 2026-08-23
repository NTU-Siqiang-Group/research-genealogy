# Interactive genealogy inspector

Run date: 2026-08-23.

## Outcome

The evidence-first LSM-tree run now has a dependency-free browser interface at
`web/index.html`. It is driven by a generated payload rather than a manually
maintained visualization. Gold labels and development evaluation results are
not inputs to, or bundled with, the interface.

Current payload:

- 150 papers;
- 1,315 relations: 1,171 weak, 135 medium, and 9 strong;
- 19 papers and 23 logical medium/strong relations in the default technical
  genealogy;
- 4 dominant, parent-eligible genealogy edges, reduced to 3 default display
  spine edges while retaining the redundant direct edge for evidence
  inspection;
- 527 full-text and authorship evidence atoms;
- 1 automatically discovered `Monkey → ArceKV` lineage path;
- CAMAL and ArceKV full-text provenance and PDF links.

## Alignment with the project goal

| Goal requirement | Inspector behavior |
| --- | --- |
| DAG, not forced single-parent tree | The default view includes all logical medium/strong links and emphasizes a transitively reduced dominant spine. |
| Avoid citation hairball | Pure citations and pure authorship overlap stay out of the default technical genealogy. Weak citations are opt-in. |
| Clear default genealogy | Nodes are layered by DAG generation; virtual routing nodes steer long edges through open lanes instead of through paper cards. |
| Time-aware evolution | A separate timeline layout places publication years on the x-axis and retains at least six vertical lanes. |
| Cluster-free layout | Weighted barycentric sweeps reorder real and routing nodes to reduce crossings; dominant edges receive the highest layout weight. |
| Semantic relation levels | Strong, medium, and weak layers have separate filters and visual encodings. |
| Research-group context | Standalone key-author-overlap links use a thinner dotted treatment and a separate layer that is off by default. Logical evidence remains the primary relation when both kinds exist. |
| Inspectable relationships | Clicking an edge exposes relation types, confidence, parent eligibility, section, role, citation marker, entity, PDF, and verbatim passage. |
| Branch inspection | Lineage components and branch cones are discovered automatically from the reduced primary DAG and may overlap after merges. |
| Honest path semantics | Automatic paths are navigation aids inferred from the primary DAG and may overlap after a later merge. |

## Verification

- `node --check web/app.js` passes.
- 45 Python unit/integration tests pass, including authorship fallback, DAG
  reduction, automatic branch discovery, payload,
  and UI-contract tests.
- Headless Chrome loaded the production page successfully. The default
  topology layout renders 19 labeled papers across 5 DAG generations, with
  long relations routed through intermediate open lanes.
- The optional timeline was also inspected at 1600×1000 and preserves six
  vertical slots instead of collapsing the evidence graph to two rows.

Screenshots:

- `reports/genealogy_inspector.png`
- `reports/genealogy_inspector_edge.png`
- `reports/genealogy_inspector_camal.png` (logical relation plus supplemental
  research-group evidence)
- `reports/genealogy_inspector_auto_dag.png` (current cluster-free,
  topology-first primary view)
- `reports/genealogy_inspector_timeline.png` (optional publication-year view
  with expanded vertical lanes)

## Run

```bash
.venv-coi/bin/python scripts/07_build_inspector_data.py
.venv-coi/bin/python -m http.server 4174 --bind 127.0.0.1
```

Open <http://127.0.0.1:4174/web/>.
