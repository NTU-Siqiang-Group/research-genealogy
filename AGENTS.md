# Project Agent Instructions

## Canonical repository

- GitHub repository: https://github.com/NTU-Siqiang-Group/research-genealogy
- Git remote URL: `git@github.com:NTU-Siqiang-Group/research-genealogy.git`
- Default branch: `main`
- Visibility: private. Do not make the repository public without explicit user approval.
- Treat the organization repository above as the only canonical remote. Do not
  create or push this project to a personal fork unless the user explicitly asks.

If the execution environment prevents writing `.git/config`, push directly to
the canonical remote URL instead of falling back to another repository.

## Sensitive and generated files

- Never commit `.env`, API keys, retrieved PDFs, or generated search bundles.
- Keep `data/raw/` and `data/searches/` local and ignored.
