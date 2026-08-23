import json
from pathlib import Path
import tempfile
import unittest

from src.schema import (
    Branch,
    CitationEdge,
    EvidenceAtom,
    EvolutionDAG,
    EvolutionEdge,
    HierarchyCluster,
    PaperRecord,
    SemanticProfile,
)


class SchemaRoundTripTest(unittest.TestCase):
    def test_paper_round_trip_preserves_semantic_identity(self) -> None:
        paper = PaperRecord(
            paper_id="S2:abc123",
            title="A Semantic Paper",
            year=2024,
            references=["S2:root"],
            citations=["S2:child"],
            semantic_profile=SemanticProfile(
                coi={"methods": "adaptive compaction"},
                scychic={"solution": {"solution approach": "adaptive compaction"}},
            ),
            cluster_paths={"solution": ["root", "adaptive"]},
        )
        self.assertEqual(PaperRecord.from_json(paper.to_json()), paper)

    def test_dag_file_round_trip(self) -> None:
        dag = EvolutionDAG(
            nodes=[
                PaperRecord("S2:root", "Root", 1996),
                PaperRecord("S2:child", "Child", 2017),
            ],
            edges=[
                EvolutionEdge(
                    "S2:root",
                    "S2:child",
                    citation_exists=True,
                    relation="EXTENDS",
                    confidence=0.8,
                    dominant=True,
                    association_level="strong",
                    relation_types=["EXTENDS"],
                    parent_eligible=True,
                    evidence_details=[
                        EvidenceAtom(
                            paper_id="S2:child",
                            cited_paper_id="S2:root",
                            section="1 Introduction",
                            section_type="introduction",
                            text="We extend Root [1].",
                            role="DIRECT_DISCUSSION",
                            confidence=0.8,
                        )
                    ],
                )
            ],
            branches=[Branch("structural", "Structural optimization")],
            run_metadata={"axis": "solution"},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dag.json"
            dag.dump(path)
            self.assertEqual(EvolutionDAG.load(path), dag)
            self.assertTrue(json.loads(path.read_text())["edges"][0]["dominant"])

    def test_supporting_models_round_trip(self) -> None:
        citation = CitationEdge("S2:a", "S2:b", ["b references a"])
        cluster = HierarchyCluster("c1", ["S2:a"], "Analytical", level=1)
        self.assertEqual(CitationEdge.from_dict(citation.to_dict()), citation)
        self.assertEqual(HierarchyCluster.from_dict(cluster.to_dict()), cluster)

    def test_rejects_invalid_edges_and_confidence(self) -> None:
        with self.assertRaises(ValueError):
            CitationEdge("same", "same")
        with self.assertRaises(ValueError):
            EvolutionEdge("a", "b", True, confidence=1.1)


if __name__ == "__main__":
    unittest.main()
