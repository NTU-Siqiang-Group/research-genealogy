import unittest

from src.branch_discovery import discover_auto_branches, transitive_reduction_edges
from src.schema import EvolutionEdge, PaperRecord


def primary(source, target, confidence=0.9):
    return EvolutionEdge(
        source,
        target,
        citation_exists=True,
        relation="EXTENDS",
        relation_types=["EXTENDS"],
        association_level="strong",
        confidence=confidence,
        dominant=True,
        parent_eligible=True,
    )


class BranchDiscoveryTest(unittest.TestCase):
    def test_transitive_reduction_hides_redundant_display_edge(self) -> None:
        edges = [primary("A", "B"), primary("B", "C"), primary("A", "C")]
        kept, redundant = transitive_reduction_edges(edges)
        self.assertEqual({(edge.source, edge.target) for edge in kept}, {("A", "B"), ("B", "C")})
        self.assertEqual([(edge.source, edge.target) for edge in redundant], [("A", "C")])

    def test_split_creates_automatic_overlapping_branch_cones(self) -> None:
        papers = [
            PaperRecord("A", "Origin", 2000),
            PaperRecord("B", "Branch One", 2001),
            PaperRecord("C", "Branch Two", 2001),
            PaperRecord("D", "Merge", 2002),
        ]
        result = discover_auto_branches(
            papers,
            [primary("A", "B"), primary("A", "C"), primary("B", "D"), primary("C", "D")],
        )
        self.assertEqual(len(result["branches"]), 2)
        self.assertTrue(all(branch["split_paper_id"] == "A" for branch in result["branches"]))
        self.assertTrue(all("D" in branch["paper_ids"] for branch in result["branches"]))
        self.assertTrue(all(branch["kind"] == "branch_cone" for branch in result["branches"]))

    def test_single_path_becomes_lineage_component(self) -> None:
        papers = [
            PaperRecord("A", "Origin", 2000),
            PaperRecord("B", "Middle", 2001),
            PaperRecord("C", "Latest", 2002),
        ]
        result = discover_auto_branches(
            papers, [primary("A", "B"), primary("B", "C")]
        )
        branch = result["branches"][0]
        self.assertEqual(branch["kind"], "lineage_component")
        self.assertEqual(branch["paper_ids"], ["A", "B", "C"])
        self.assertEqual(branch["label"], "Origin → Latest")


if __name__ == "__main__":
    unittest.main()
