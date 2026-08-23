# P0 upstream check

Checked on 2026-08-20 in `/Users/dinghengmo/works/academic_evolution_tree`.

## Pinned revisions

| Component | Revision | Revision date | Working tree |
|---|---|---|---|
| CoI-Agent | `ac94317ff2d1997f362747edc2c9e5f0fdc9c450` | 2025-01-15 | clean |
| Science Hierarchography | `d67aa6d5f2ba230fe856cef1477c2e9b6c2e0608` | 2026-08-05 | clean |

The repositories remain separate under `upstream/`; project code does not patch
either repository. Exact revisions are recorded in `upstream.lock`.

## CoI-Agent

- All 11 Python files pass a Python AST syntax check.
- The smallest documented CLI check (`python main.py --help`) does not start in
  the clean host environment because `requests` is absent.
- The retrieval module imports `scipdf` at module import time, so even metadata-
  only Semantic Scholar use currently requires the PDF stack to be importable.
- The README requires a separately installed SciPDF Parser and a running GROBID
  service for full-text extraction. These are not declared in
  `requirements.txt`.
- Semantic Scholar metadata access can run without a key in the code, but a key
  is expected for reliable/rate-limited use. LLM extraction additionally needs
  OpenAI or Azure OpenAI credentials and model names.
- The search layer preserves `paperId` in search results, but
  `search_related_paper_async` returns only one selected downloaded paper and
  discards IDs in its final `Result`. P0 must wrap the lower-level API response,
  not use this final selection method as graph inference.

Required configuration:

- `SEMENTIC_SEARCH_API_KEY` (recommended for reliable corpus construction)
- `OPENAI_API_KEY` + `OPENAI_BASE_URL`, or Azure OpenAI equivalents
- `MAIN_LLM_MODEL`, `CHEAP_LLM_MODEL`
- optional separate embedding endpoint/key/model
- SciPDF Parser, GROBID, and Java for full-text parsing

License: Apache-2.0 (`LICENSE` exists at repository root).

The P0 wrapper has an explicit metadata-only compatibility mode: if `scipdf` is
the sole missing module, it supplies a fail-closed stub so CoI's unchanged
Semantic Scholar client can run. Any attempt to parse a PDF through that stub
raises an error. Installing SciPDF from its Git repository was attempted but the
Git fetch stalled and was stopped; full-text extraction remains pending.

## Science Hierarchography / SCYCHIC

- All 17 Python files across SCYCHIC and fLMSci pass a Python AST syntax check.
- `SCYCHIC/main.py --help` stops on missing `pandas`; `generate.py --help` stops
  on missing `torch` in the clean host environment.
- The README refers to a root `requirements.txt`, but the pinned revision has no
  such file. Its environment therefore cannot be reproduced literally from the
  repository.
- The README specifies Python 3.8, while the host default is Python 3.14.3.
  SCYCHIC must use a separate compatible environment.
- `SCYCHIC/run.sh` is an SLURM script with author-specific absolute paths, GPU
  assumptions, and cluster configuration; it is not a portable sanity example.
- The main entry imports `evaluator.evaluate`, but the checked-out directory is
  named `eval`. After dependencies are installed this import path must be
  rechecked before treating the upstream CLI as runnable.
- The code supports pre-generated per-subkey embeddings plus `subkey`, `key`,
  and `all` aggregation, and supports top-down, bottom-up, and bidirectional
  clustering. This remains the intended P0 integration seam.

Likely dependencies inferred from imports include NumPy, pandas, PyTorch,
sentence-transformers, scikit-learn, transformers, tqdm, OpenAI, and
python-dotenv. Model downloads and the summarization path need network access;
the default embedding model is a 7B Qwen model and is not a small CPU sanity
fixture.

Required configuration/resources:

- a compatible isolated Python environment
- embedding model weights or a compatible pre-generated embedding pickle
- local Hugging Face summarizer weights, or OpenAI configuration depending on
  selected generator
- GPU for the documented/default large-model route

License: no root license file or explicit software-license statement was found
at the pinned revision. Keep it as a separately invoked local upstream and do
not vendor or redistribute its source until licensing is clarified.

## Phase 0A result

Both upstreams are pinned and their reusable seams are present, but neither
documented end-to-end entry point is currently runnable in the clean host
environment. CoI has undeclared full-text dependencies; SCYCHIC lacks a locked
dependency specification and a portable example. The next checks should use
separate environments and tiny fixtures. This is an upstream integration risk,
not a blocker for the dependency-free canonical schema and gold benchmark.

## Follow-up isolated-environment checks

- CoI's declared requirements installed under Python 3.12. Its search class now
  loads through the metadata-only wrapper, but a real Monkey lookup repeatedly
  received HTTP 429 without `SEMENTIC_SEARCH_API_KEY`; the wrapper's 20-second
  bound stopped the upstream recursive retry.
- A compatible SCYCHIC environment was reconstructed and pinned locally in
  `requirements/scychic-p0.txt`. NumPy 2.x first failed against the available
  PyTorch build; NumPy 1.26 then required matching older SciPy/scikit-learn.
- `SCYCHIC/generate.py --help` succeeds in that environment.
- `SCYCHIC/main.py --help` reaches the repository bug
  `ModuleNotFoundError: evaluator`; the checkout contains `eval`, not
  `evaluator`.
- Direct invocation of the unchanged `PaperProcessor` completed a two-level
  top-down KMeans smoke run over six pre-generated embeddings. The adapter had
  to convert NumPy scalar IDs and restore canonical paper IDs that SCYCHIC
  otherwise replaces with row indexes.
