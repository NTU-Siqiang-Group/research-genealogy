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
        self.assertEqual(payload["summary"]["edge_count"], 1318)
        self.assertEqual(payload["summary"]["evidence_atom_count"], 583)
        self.assertNotIn("landmarks", payload)
        self.assertNotIn("benchmark_branches", payload)
        self.assertNotIn("evaluation", payload)
        self.assertNotIn("branches", payload["dag"])
        self.assertNotIn("cluster_paths", payload["dag"]["nodes"][0])
        self.assertNotIn("gold", payload["source_artifacts"])
        self.assertEqual(payload["summary"]["display_primary_count"], 4)
        self.assertEqual(payload["summary"]["redundant_primary_count"], 1)
        self.assertEqual(payload["summary"]["technical_lineage_paper_count"], 20)
        self.assertEqual(payload["summary"]["technical_lineage_edge_count"], 27)
        self.assertEqual(payload["summary"]["narrative_lineage_paper_count"], 10)
        self.assertEqual(payload["summary"]["narrative_lineage_edge_count"], 11)
        self.assertEqual(
            len(payload["auto_branch_discovery"]["narrative_edge_keys"]),
            11,
        )
        self.assertEqual(len(payload["auto_branches"]), 2)
        self.assertEqual(
            {branch["label"] for branch in payload["auto_branches"]},
            {
                "After Dostoevsky: Learning to Optimize LSM-trees",
                "After Dostoevsky: Structural Designs Meet Optimality",
            },
        )
        self.assertIn("OPENALEX:W7160292552", payload["fulltext"])
        self.assertIn("OPENALEX:W4399175309", payload["fulltext"])

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

        dostoevsky_moose = next(
            edge
            for edge in payload["dag"]["edges"]
            if edge["source"] == "OPENALEX:W2798441769"
            and edge["target"] == "OPENALEX:W4399175309"
        )
        self.assertEqual(dostoevsky_moose["association_level"], "strong")
        self.assertEqual(dostoevsky_moose["relation"], "EXPLICIT_BASELINE")
        self.assertIn("EXPLICIT_BASELINE", dostoevsky_moose["relation_types"])
        self.assertIn("IMPLICIT_BASELINE", dostoevsky_moose["relation_types"])
        self.assertTrue(dostoevsky_moose["parent_eligible"])
        self.assertTrue(dostoevsky_moose["dominant"])

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
            'data-layout="topology"',
            'data-layout="timeline"',
            "EDGE SEMANTICS",
            "OPTIONAL OVERLAY",
            "只叠加当前视图内的研究组关系，不增加论文",
            "全引图",
            "显式 baseline",
            "隐式 baseline",
        ):
            self.assertIn(required_id, html)
        for behavior in (
            "renderEdgeInspector",
            "renderEvidenceAtom",
            "renderSearchResults",
            "fitView",
            "toggleSelection",
            "parent_eligible",
            "showGroupEdges",
            "narrativeEdgeKeys",
            "baseNodeIds",
            "layoutEdges: baseEdges",
            "groupEdgeCount",
            "group-affiliation-overlay",
            "edgeSemanticClass",
            "showEdgeTooltip",
            "minimizeLayerCrossings",
            "buildTopologyLayout",
            "buildTimelineLayout",
            "assignRouteLanes",
            "balanced_temporal_topological_dag_with_obstacle_routes",
        ):
            self.assertIn(behavior, script)
        for hidden_control in (
            "RELATION LAYERS",
            'data-level="strong"',
            'data-level="medium"',
            'data-level="weak"',
            "AUTO-DISCOVERED PATHS",
            'id="branch-list"',
        ):
            self.assertNotIn(hidden_control, html)
        for removed_behavior in ("state.levels", "branchFocus", "renderBranchList"):
            self.assertNotIn(removed_behavior, script)
        self.assertNotIn("`GEN ${index + 1}`", script)
        self.assertNotIn("edge-label-bg", script)
        self.assertIn('markerUnits="userSpaceOnUse"', html)

    def test_group_overlay_never_expands_a_mode_paper_set(self) -> None:
        payload = json.loads((ROOT / "web/data/inspector.json").read_text(encoding="utf-8"))
        nodes = payload["dag"]["nodes"]
        edges = payload["dag"]["edges"]
        technical = set(payload["auto_branch_discovery"]["technical_edge_keys"])
        narrative = set(payload["auto_branch_discovery"]["narrative_edge_keys"])

        def key(edge):
            return f"{edge['source']}→{edge['target']}"

        def is_group(edge):
            relation_types = set(edge.get("relation_types", []))
            return edge.get("relation") == "SAME_RESEARCH_GROUP" or bool(
                {"SAME_RESEARCH_GROUP", "KEY_AUTHOR_OVERLAP"} & relation_types
            )

        expected = {
            "lineage": (10, 11, 5),
            "evidence": (20, 27, 13),
            "corpus": (150, 1318, 125),
        }
        for mode, (paper_count, base_edge_count, group_count) in expected.items():
            if mode == "lineage":
                base_edges = [edge for edge in edges if key(edge) in narrative]
            elif mode == "evidence":
                base_edges = [edge for edge in edges if key(edge) in technical]
            else:
                base_edges = list(edges)
            base_ids = {node["paper_id"] for node in nodes} if mode == "corpus" else {
                endpoint
                for edge in base_edges
                for endpoint in (edge["source"], edge["target"])
            }
            group_edges = [
                edge
                for edge in edges
                if is_group(edge)
                and edge["source"] in base_ids
                and edge["target"] in base_ids
            ]
            self.assertEqual(len(base_ids), paper_count)
            self.assertEqual(len(base_edges), base_edge_count)
            self.assertEqual(len(group_edges), group_count)
            # Enabling the overlay only adds edges whose two endpoints are
            # already members of the mode's immutable base node set.
            enabled_ids = set(base_ids)
            for edge in group_edges:
                enabled_ids.update((edge["source"], edge["target"]))
            self.assertEqual(enabled_ids, base_ids)


if __name__ == "__main__":
    unittest.main()
