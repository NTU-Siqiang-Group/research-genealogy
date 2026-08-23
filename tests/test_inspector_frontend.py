import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InspectorFrontendTest(unittest.TestCase):
    def test_builder_packages_current_evidence_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "inspector.json"
            subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "scripts/07_build_inspector_data.py"),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["summary"]["paper_count"], 150)
        self.assertEqual(payload["summary"]["edge_count"], 1315)
        self.assertEqual(payload["summary"]["evidence_atom_count"], 527)
        self.assertEqual(len(payload["landmarks"]), 10)
        self.assertEqual(len(payload["benchmark_branches"]), 4)
        self.assertIn("OPENALEX:W7160292552", payload["fulltext"])

        ruskey_arce = next(
            edge
            for edge in payload["dag"]["edges"]
            if edge["source"] == "OPENALEX:W4388620464"
            and edge["target"] == "OPENALEX:W7160292552"
        )
        self.assertEqual(ruskey_arce["association_level"], "strong")
        self.assertTrue(ruskey_arce["parent_eligible"])
        self.assertTrue(ruskey_arce["dominant"])
        self.assertEqual(len(ruskey_arce["evidence_details"]), 8)

        ruskey_camal = next(
            edge
            for edge in payload["dag"]["edges"]
            if edge["source"] == "OPENALEX:W4388620464"
            and edge["target"] == "OPENALEX:W4402969669"
        )
        self.assertEqual(ruskey_camal["relation"], "ADDRESSES_LIMITATION")
        self.assertEqual(ruskey_camal["association_level"], "medium")
        self.assertIn("SAME_RESEARCH_GROUP", ruskey_camal["relation_types"])
        self.assertIn("KEY_AUTHOR_OVERLAP", ruskey_camal["relation_types"])
        self.assertFalse(ruskey_camal["parent_eligible"])

    def test_frontend_exposes_inspection_controls(self) -> None:
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        script = (ROOT / "web/app.js").read_text(encoding="utf-8")
        for required_id in (
            'id="paper-search"',
            'id="group-layer"',
            'id="graph-svg"',
            'id="inspector-content"',
            'data-mode="lineage"',
            'data-mode="evidence"',
            'data-mode="corpus"',
        ):
            self.assertIn(required_id, html)
        for behavior in (
            "renderEdgeInspector",
            "renderEvidenceAtom",
            "renderSearchResults",
            "fitView",
            "parent_eligible",
            "showGroupEdges",
        ):
            self.assertIn(behavior, script)


if __name__ == "__main__":
    unittest.main()
