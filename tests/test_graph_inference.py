import unittest

from src.branch_inference import dominant_tree, infer_evolution_dag
from src.citation_overlay import overlay_citations
from src.schema import PaperRecord
from src.schema import EvidenceAtom, EvolutionEdge


class GraphInferenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = PaperRecord(
            "S2:root", "Root", 2000, citations=["S2:a", "S2:b"], cluster_paths={"solution": ["0"]}
        )
        self.a = PaperRecord(
            "S2:a", "A", 2010, references=["S2:root"], cluster_paths={"solution": ["0", "a"]}
        )
        self.b = PaperRecord(
            "S2:b", "B", 2011, references=["S2:root"], cluster_paths={"solution": ["0", "b"]}
        )
        self.c = PaperRecord(
            "S2:c",
            "C",
            2015,
            references=["S2:root", "S2:a"],
            cluster_paths={"solution": ["0", "a"]},
        )

    def test_overlay_normalizes_and_deduplicates(self) -> None:
        papers, edges = overlay_citations([self.root, self.a, self.b, self.c], axis="solution")
        pairs = [(edge.source, edge.target) for edge in edges]
        self.assertEqual(pairs.count(("S2:root", "S2:a")), 1)
        self.assertIn(("S2:a", "S2:c"), pairs)
        self.assertEqual(len(papers), 4)

    def test_citation_only_does_not_force_parent_from_cluster(self) -> None:
        papers, edges = overlay_citations([self.root, self.a, self.b, self.c], axis="solution")
        dag = infer_evolution_dag(papers, edges, axis="solution")
        tree_pairs = {(edge.source, edge.target) for edge in dominant_tree(dag).edges}
        self.assertEqual(tree_pairs, set())
        self.assertTrue(all(edge.association_level == "weak" for edge in dag.edges))
        self.assertFalse(next(p for p in dag.nodes if p.paper_id == "S2:root").metadata["is_hub"])

    def test_strong_inheritance_evidence_selects_parent_without_cluster_score(self) -> None:
        papers, edges = overlay_citations([self.root, self.a, self.b, self.c], axis="solution")
        evidence = EvolutionEdge(
            "S2:root",
            "S2:c",
            citation_exists=True,
            relation="USES_CONCEPT_FROM",
            relation_types=["CITES", "USES_CONCEPT_FROM", "IMPLICIT_BASELINE"],
            association_level="strong",
            parent_eligible=True,
            evidence_details=[
                EvidenceAtom(
                    paper_id="S2:c",
                    cited_paper_id="S2:root",
                    section="6 Evaluation",
                    section_type="evaluation",
                    text="We compare against the artifact introduced in Root [1].",
                    role="IMPLICIT_BASELINE",
                    confidence=0.9,
                )
            ],
            confidence=0.9,
        )
        dag = infer_evolution_dag(
            papers, edges, evidence_edges=[evidence], axis="solution"
        )
        tree_pairs = {(edge.source, edge.target) for edge in dominant_tree(dag).edges}
        self.assertEqual(tree_pairs, {("S2:root", "S2:c")})

    def test_author_overlap_upgrades_citation_but_never_becomes_parent(self) -> None:
        root = PaperRecord(
            "P:old",
            "Old",
            2023,
            metadata={"authors": ["Shared Author", "Another Person"]},
        )
        child = PaperRecord(
            "P:new",
            "New",
            2024,
            references=["P:old"],
            metadata={"authors": ["Shared Author", "Different Person"]},
        )
        papers, citations = overlay_citations([root, child])
        dag = infer_evolution_dag(papers, citations)
        edge = dag.edges[0]
        self.assertEqual(edge.association_level, "medium")
        self.assertEqual(edge.relation, "SAME_RESEARCH_GROUP")
        self.assertIn("CITES", edge.relation_types)
        self.assertFalse(edge.parent_eligible)
        self.assertEqual(dominant_tree(dag).edges, [])

    def test_logical_relation_remains_primary_when_author_overlap_is_supplemental(self) -> None:
        root = PaperRecord(
            "P:old",
            "Old",
            2023,
            metadata={"authors": ["Shared Author", "Another Person"]},
        )
        child = PaperRecord(
            "P:new",
            "New",
            2024,
            references=["P:old"],
            metadata={"authors": ["Shared Author", "Different Person"]},
        )
        papers, citations = overlay_citations([root, child])
        logical = EvolutionEdge(
            "P:old",
            "P:new",
            citation_exists=True,
            relation="EXTENDS",
            relation_types=["CITES", "EXTENDS"],
            association_level="medium",
            confidence=0.72,
        )
        dag = infer_evolution_dag(papers, citations, evidence_edges=[logical])
        edge = dag.edges[0]
        self.assertEqual(edge.relation, "EXTENDS")
        self.assertEqual(edge.confidence, 0.72)
        self.assertIn("SAME_RESEARCH_GROUP", edge.relation_types)
        self.assertIn("Supplemental research-group evidence", edge.explanation)


if __name__ == "__main__":
    unittest.main()
