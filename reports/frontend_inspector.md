# Interactive genealogy inspector

Run date: 2026-08-23.

## Outcome

The evidence-first LSM-tree run now has a dependency-free browser interface at
`web/index.html`. It is driven by a generated payload rather than a manually
maintained visualization.

Current payload:

- 150 papers;
- 1,315 relations: 1,171 weak, 135 medium, and 9 strong;
- 4 dominant, parent-eligible genealogy edges;
- 527 full-text and authorship evidence atoms;
- 10 benchmark landmarks and 4 benchmark branch hypotheses;
- CAMAL and ArceKV full-text provenance and PDF links.

## Alignment with the project goal

| Goal requirement | Inspector behavior |
| --- | --- |
| DAG, not forced single-parent tree | All four dominant edges are shown, including both Dostoevsky→ArceKV and RusKey→ArceKV. |
| Avoid citation hairball | The default view shows only dominant edges and landmarks. Weak citations are opt-in. |
| Time-aware evolution | Nodes are ordered by real publication year; long empty periods are compressed for readability. |
| Hubs and landmarks | Hubs have a gold star marker; benchmark landmarks are visually distinct. |
| Semantic relation levels | Strong, medium, and weak layers have separate filters and visual encodings. |
| Research-group context | Standalone key-author-overlap links use a thinner dotted treatment and a separate layer that is off by default. Logical evidence remains the primary relation when both kinds exist. |
| Inspectable relationships | Clicking an edge exposes relation types, confidence, parent eligibility, section, role, citation marker, entity, PDF, and verbatim passage. |
| Branch inspection | Human benchmark branches are a separate focus lens from numeric model clusters; disagreement and coarse coherence remain visible. |
| Current limitations visible | Missing validated technical split explanations are shown as an evidence gap instead of being hidden or invented. |

## Verification

- `node --check web/app.js` passes.
- 41 Python unit/integration tests pass, including authorship fallback, payload,
  and UI-contract tests.
- Headless Chrome loaded the production page and reported
  `data-ready=true`, `data-mode=evidence`, 17 visible nodes, and 15 visible
  evidence relations.
- The main view and the RusKey→ArceKV evidence view were visually inspected at
  1600×1000.

Screenshots:

- `reports/genealogy_inspector.png`
- `reports/genealogy_inspector_edge.png`
- `reports/genealogy_inspector_camal.png` (logical relation plus supplemental
  research-group evidence)

## Run

```bash
.venv-coi/bin/python scripts/07_build_inspector_data.py
.venv-coi/bin/python -m http.server 4173 --bind 127.0.0.1
```

Open <http://127.0.0.1:4173/web/>.
