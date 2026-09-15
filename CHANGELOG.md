# Changelog

All notable changes to this project are documented in this file. The project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-09-15

### Added

- Persistent seed-driven searches with bounded OpenAlex corpus expansion.
- Title-validated full-text retrieval with deterministic and optional
  author-homepage fallbacks.
- Section-aware weak, medium, and strong relationship evidence, including
  numbered and author-year citations.
- Explicit and implicit baseline detection plus subordinate author-affinity
  evidence.
- Sparse lineage, complete evidence, and corpus views with bilingual UI.
- Reopenable local result bundles with provenance, logs, and artifact hashes.

### Changed

- Resolved seed papers remain visible even when no medium or strong relation is
  detected.
- Introduction and Preliminary direct method discussions can contribute medium
  evidence.

[Unreleased]: https://github.com/NTU-Siqiang-Group/research-genealogy/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/NTU-Siqiang-Group/research-genealogy/releases/tag/v0.2.0
