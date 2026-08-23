# Research Genealogy Inspector

This is a dependency-free static UI over the evidence-first output contract.
It intentionally starts from the primary genealogy instead of rendering all
citations.

Regenerate `data/inspector.json` whenever the DAG or evidence changes:

```bash
.venv-coi/bin/python scripts/07_build_inspector_data.py \
  --topic "LSM-tree structural and workload-adaptive optimization"
```

The generated payload combines the DAG and retrieval artifacts, then derives
the full technical genealogy, a display backbone, and automatic path lenses
from the evidence DAG:

- `data/output/evidence_first/evolution_dag.json`
- `data/raw/fulltext/retrieval_index.json`

The UI deliberately does not expose expert benchmarks or legacy solution
clusters, and neither is included in its generated payload. Its default layout
is a cluster-free DAG-generation view with explicit long-edge routing. A
second layout places publication years on the x-axis while retaining expanded
vertical lanes. The initial viewport keeps labeled cards at a readable size;
use `Fit` for a compressed whole-graph overview.

Run the UI from the repository root:

```bash
.venv-coi/bin/python -m http.server 4174 --bind 127.0.0.1
```

Open <http://127.0.0.1:4174/web/>.
