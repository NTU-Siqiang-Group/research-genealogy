"""Stable, dependency-free data contracts for the P0 pipeline.

The upstream projects exchange files through these models.  Keeping the
contract here prevents retrieval, clustering, and graph inference details from
leaking into one another.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping, TypeVar


JsonDict = dict[str, Any]
T = TypeVar("T", bound="JsonModel")


class JsonModel:
    """Small JSON serialization mixin for top-level P0 records."""

    def to_dict(self) -> JsonDict:
        return asdict(self)  # type: ignore[arg-type]

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def dump(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.to_json() + "\n", encoding="utf-8")

    @classmethod
    def from_json(cls: type[T], payload: str) -> T:
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValueError(f"{cls.__name__} JSON must be an object")
        return cls.from_dict(value)

    @classmethod
    def load(cls: type[T], path: str | Path) -> T:
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"expected a list, got {type(value).__name__}")
    return value


EVIDENCE_LEVELS = {"weak", "medium", "strong"}


@dataclass(slots=True)
class SemanticProfile(JsonModel):
    """Both the literal CoI output and its mechanical SCYCHIC projection."""

    coi: JsonDict = field(default_factory=dict)
    scychic: JsonDict = field(default_factory=dict)
    raw_response_path: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SemanticProfile":
        return cls(
            coi=dict(value.get("coi") or {}),
            scychic=dict(value.get("scychic") or {}),
            raw_response_path=value.get("raw_response_path"),
        )


@dataclass(slots=True)
class PaperRecord(JsonModel):
    paper_id: str
    title: str
    year: int | None = None
    venue: str | None = None
    abstract: str | None = None
    pdf_url: str | None = None
    references: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    semantic_profile: SemanticProfile | None = None
    cluster_paths: dict[str, list[str]] = field(default_factory=dict)
    metadata: JsonDict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.paper_id.strip():
            raise ValueError("paper_id must not be empty")
        if not self.title.strip():
            raise ValueError("title must not be empty")
        if self.year is not None and not 1000 <= self.year <= 3000:
            raise ValueError(f"implausible publication year: {self.year}")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PaperRecord":
        profile = value.get("semantic_profile")
        paths = value.get("cluster_paths") or {}
        if not isinstance(paths, dict):
            raise ValueError("cluster_paths must be an object")
        return cls(
            paper_id=str(value["paper_id"]),
            title=str(value["title"]),
            year=value.get("year"),
            venue=value.get("venue"),
            abstract=value.get("abstract"),
            pdf_url=value.get("pdf_url"),
            references=[str(item) for item in _list(value.get("references"))],
            citations=[str(item) for item in _list(value.get("citations"))],
            semantic_profile=(
                SemanticProfile.from_dict(profile)
                if isinstance(profile, Mapping)
                else None
            ),
            cluster_paths={
                str(key): [str(item) for item in _list(path)]
                for key, path in paths.items()
            },
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass(slots=True)
class CitationEdge(JsonModel):
    """A normalized, earlier-to-later in-corpus citation edge."""

    source: str
    target: str
    evidence: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.source == self.target:
            raise ValueError("citation edge cannot be a self-loop")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CitationEdge":
        return cls(
            source=str(value["source"]),
            target=str(value["target"]),
            evidence=[str(item) for item in _list(value.get("evidence"))],
        )


@dataclass(slots=True)
class EvidenceAtom(JsonModel):
    """One auditable full-text passage supporting a paper-to-paper relation.

    ``paper_id`` is the paper in which the passage occurs.  For ordinary
    citation contexts this is normally the later/target paper; entity-origin
    atoms may instead occur in the predecessor/source paper.
    """

    paper_id: str
    section: str
    section_type: str
    text: str
    role: str
    cited_paper_id: str | None = None
    citation_marker: str | None = None
    entity: str | None = None
    source_path: str | None = None
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if not self.paper_id.strip():
            raise ValueError("evidence paper_id must not be empty")
        if not self.text.strip():
            raise ValueError("evidence text must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("evidence confidence must be in [0, 1]")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceAtom":
        return cls(
            paper_id=str(value["paper_id"]),
            section=str(value.get("section") or "unknown"),
            section_type=str(value.get("section_type") or "unknown"),
            text=str(value.get("text") or ""),
            role=str(value.get("role") or "CITATION"),
            cited_paper_id=(
                str(value["cited_paper_id"])
                if value.get("cited_paper_id") is not None
                else None
            ),
            citation_marker=value.get("citation_marker"),
            entity=value.get("entity"),
            source_path=value.get("source_path"),
            confidence=float(value.get("confidence", 0.0)),
        )


@dataclass(slots=True)
class HierarchyCluster(JsonModel):
    cluster_id: str
    paper_ids: list[str] = field(default_factory=list)
    summary: str = ""
    parent_cluster: str | None = None
    level: int = 0
    axis: str = "all"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HierarchyCluster":
        return cls(
            cluster_id=str(value["cluster_id"]),
            paper_ids=[str(item) for item in _list(value.get("paper_ids"))],
            summary=str(value.get("summary") or ""),
            parent_cluster=value.get("parent_cluster"),
            level=int(value.get("level", 0)),
            axis=str(value.get("axis") or "all"),
        )


@dataclass(slots=True)
class EvolutionEdge(JsonModel):
    source: str
    target: str
    citation_exists: bool
    relation: str = "RELATED_PREDECESSOR"
    explanation: str = ""
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.0
    dominant: bool = False
    association_level: str = "weak"
    relation_types: list[str] = field(default_factory=list)
    parent_eligible: bool = False
    evidence_details: list[EvidenceAtom] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.source == self.target:
            raise ValueError("evolution edge cannot be a self-loop")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.association_level not in EVIDENCE_LEVELS:
            raise ValueError(
                f"association_level must be one of {sorted(EVIDENCE_LEVELS)}"
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvolutionEdge":
        return cls(
            source=str(value["source"]),
            target=str(value["target"]),
            citation_exists=bool(value.get("citation_exists", False)),
            relation=str(value.get("relation") or "RELATED_PREDECESSOR"),
            explanation=str(value.get("explanation") or ""),
            evidence=[str(item) for item in _list(value.get("evidence"))],
            confidence=float(value.get("confidence", 0.0)),
            dominant=bool(value.get("dominant", False)),
            association_level=str(value.get("association_level") or "weak"),
            relation_types=[
                str(item) for item in _list(value.get("relation_types"))
            ],
            parent_eligible=bool(value.get("parent_eligible", False)),
            evidence_details=[
                EvidenceAtom.from_dict(item)
                for item in _list(value.get("evidence_details"))
                if isinstance(item, Mapping)
            ],
        )


@dataclass(slots=True)
class Branch(JsonModel):
    branch_id: str
    label: str
    summary: str = ""
    parent_branch: str | None = None
    representative_papers: list[str] = field(default_factory=list)
    split_hub: str | None = None
    split_reason: str = ""

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Branch":
        return cls(
            branch_id=str(value["branch_id"]),
            label=str(value["label"]),
            summary=str(value.get("summary") or ""),
            parent_branch=value.get("parent_branch"),
            representative_papers=[
                str(item) for item in _list(value.get("representative_papers"))
            ],
            split_hub=value.get("split_hub"),
            split_reason=str(value.get("split_reason") or ""),
        )


@dataclass(slots=True)
class EvolutionDAG(JsonModel):
    nodes: list[PaperRecord] = field(default_factory=list)
    edges: list[EvolutionEdge] = field(default_factory=list)
    branches: list[Branch] = field(default_factory=list)
    run_metadata: JsonDict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvolutionDAG":
        return cls(
            nodes=[PaperRecord.from_dict(item) for item in _list(value.get("nodes"))],
            edges=[EvolutionEdge.from_dict(item) for item in _list(value.get("edges"))],
            branches=[Branch.from_dict(item) for item in _list(value.get("branches"))],
            run_metadata=dict(value.get("run_metadata") or {}),
        )
