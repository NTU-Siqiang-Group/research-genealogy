from pathlib import Path
import tempfile
import unittest

from src.branch_inference import infer_evolution_dag
from src.evaluation import evaluate_gold
from src.render import render
from src.schema import CitationEdge, EvolutionEdge, PaperRecord


class EvaluationRenderTest(unittest.TestCase):
    def test_gold_constraints_and_render_outputs(self) -> None:
        root = PaperRecord(
            "S2:monkey",
            "Monkey: Optimal Navigable Key-Value Store",
            2017,
            cluster_paths={"solution": ["0"]},
            metadata={"gold_key": "monkey"},
        )
        child = PaperRecord(
            "S2:dostoevsky",
            "Dostoevsky: Better Space-Time Trade-Offs",
            2018,
            cluster_paths={"solution": ["0"]},
            metadata={"gold_key": "dostoevsky"},
        )
        dag = infer_evolution_dag(
            [root, child],
            [CitationEdge(root.paper_id, child.paper_id)],
            evidence_edges=[
                EvolutionEdge(
                    root.paper_id,
                    child.paper_id,
                    citation_exists=True,
                    relation="EXTENDS",
                    relation_types=["CITES", "EXTENDS"],
                    association_level="strong",
                    parent_eligible=True,
                    confidence=0.9,
                )
            ],
            axis="solution",
        )
        gold = {
            "must_find": [
                {"key": "monkey", "title": root.title},
                {"key": "dostoevsky", "title": child.title},
            ],
            "expected_edges": [{"source": "monkey", "target": "dostoevsky"}],
            "must_not_force": [{"source": "dostoevsky", "target": "monkey"}],
        }
        result = evaluate_gold(dag, gold)
        self.assertEqual(result["metrics"]["must_find_recall"], 1.0)
        self.assertEqual(result["metrics"]["expected_edge_recall"], 1.0)
        self.assertEqual(result["metrics"]["expected_dominant_edge_recall"], 1.0)
        self.assertEqual(result["metrics"]["expected_strong_association_recall"], 1.0)
        self.assertEqual(result["metrics"]["expected_parent_eligible_recall"], 1.0)
        self.assertEqual(result["metrics"]["forbidden_edge_count"], 0)
        with tempfile.TemporaryDirectory() as directory:
            dot = Path(directory) / "tree.dot"
            svg = Path(directory) / "tree.svg"
            render(dag, dot, svg)
            self.assertIn("digraph academic_genealogy", dot.read_text())
            self.assertIn("<svg", svg.read_text())


if __name__ == "__main__":
    unittest.main()
