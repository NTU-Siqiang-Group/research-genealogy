import json
from pathlib import Path
import tempfile
import unittest

from src.schema import PaperRecord
from src.semantic_adapter import adapt_paper, map_coi_to_scychic, write_scychic_input


class SemanticAdapterTest(unittest.TestCase):
    def test_literal_mapping_leaves_unavailable_fields_empty(self) -> None:
        result = map_coi_to_scychic(
            {
                "Background": "prior systems",
                "Limitation": "static workloads",
                "Contribution": "dynamic optimization",
                "Methods": "reinforcement learning",
                "Novelty": "online transition",
                "Detail reason": "LSM compaction",
                "Experiment": "lower latency",
            }
        )
        self.assertEqual(result["problem"]["knowns or prior work"], "prior systems")
        self.assertEqual(result["solution"]["solution approach"], "reinforcement learning")
        self.assertEqual(result["problem"]["novelty of the problem"], "")
        self.assertEqual(
            result["results"]["potential impact of the results"],
            "dynamic optimization",
        )

    def test_scychic_file_shape(self) -> None:
        paper = adapt_paper(
            PaperRecord("S2:ruskey", "RusKey", 2023),
            {"Methods": "RL", "Contribution": "adaptation"},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = write_scychic_input(paper, directory)
            value = json.loads(Path(path).read_text())
            self.assertEqual(value["paper_id"], "S2:ruskey")
            self.assertEqual(value["solution"]["solution approach"], "RL")


if __name__ == "__main__":
    unittest.main()

