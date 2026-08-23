# Research Genealogy Inspector

This is a dependency-free static UI over the evidence-first output contract.
It intentionally starts from the primary genealogy instead of rendering all
citations.

Regenerate `data/inspector.json` whenever the DAG or evidence changes:

```bash
.venv-coi/bin/python scripts/07_build_inspector_data.py
```

The generated payload combines these authoritative artifacts:

- `data/output/evidence_first/evolution_dag.json`
- `data/output/evidence_first/evaluation.json`
- `data/raw/fulltext/retrieval_index.json`
- `configs/lsm_gold.yaml`

Run the UI from the repository root:

```bash
.venv-coi/bin/python -m http.server 4173 --bind 127.0.0.1
```

Open <http://127.0.0.1:4173/web/>.
