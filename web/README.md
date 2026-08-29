# Research Genealogy Inspector

This is a dependency-free browser UI over the evidence-first output contract.
It intentionally starts from the primary genealogy instead of rendering all
citations. English is the default; append `?lang=zh` for Chinese. Language,
view, layout, paper, and edge selections remain shareable in the URL.

Regenerate `data/inspector.json` whenever the DAG or evidence changes:

```bash
python scripts/07_build_inspector_data.py \
  --topic "LSM-tree structural and workload-adaptive optimization"
```

The generated payload combines the DAG and retrieval artifacts, then derives
the full technical genealogy and display backbone from the evidence DAG:

- `data/output/evidence_first/evolution_dag.json`
- `data/raw/fulltext/retrieval_index.json`

The UI deliberately does not expose expert benchmarks, legacy solution
clusters, or automatic-path controls. Content is selected only through three
fixed modes: narrative lineage, evidence map, and full citation graph. The one
optional research-group overlay only connects papers already present in the
current mode; it cannot expand or reposition the node set. The default layout
is a cluster-free DAG-generation view with explicit long-edge routing. A
second layout places publication years on the x-axis while retaining expanded
vertical lanes. Long relations use stable horizontal tracks selected to avoid
paper cards in every intermediate layer. The initial viewport keeps labeled
cards at a readable size; use `Fit` for a compressed whole-graph overview.

Run the homepage, result API, and inspector from the repository root:

```bash
python scripts/09_serve_app.py --port 4174
```

Open <http://127.0.0.1:4174/>. Persistent result pages use
`/web/?result=<result-id>`; `/web/` without a result continues to load the
checked-in development payload.
