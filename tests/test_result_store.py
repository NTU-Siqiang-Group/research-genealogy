import json
from pathlib import Path
import tempfile
import unittest

from src.result_store import ResultStore, normalize_search_request, request_fingerprint


class ResultStoreTest(unittest.TestCase):
    def test_single_and_multi_seed_requests_are_normalized(self) -> None:
        single = normalize_search_request({"seeds": "A Paper\n"})
        multi = normalize_search_request({"seeds": ["A Paper", "B Paper", "A Paper"]})
        self.assertEqual(single["seeds"], ["A Paper"])
        self.assertEqual(multi["seeds"], ["A Paper", "B Paper"])
        self.assertEqual(single["topic"], "A Paper")

    def test_result_bundle_is_listable_and_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResultStore(Path(directory) / "searches")
            request = store.create({"seeds": ["Seed Paper"]}, result_id="seed-paper")
            result_dir = store.result_dir("seed-paper")
            (result_dir / "inspector.json").write_text(
                json.dumps({"summary": {"paper_count": 12}}), encoding="utf-8"
            )
            store.update_status("seed-paper", state="completed", stage="completed")

            record = store.get("seed-paper")
            reused = store.find_completed(request_fingerprint(request))

        self.assertEqual(record["summary"]["paper_count"], 12)
        self.assertEqual(record["open_url"], "/web/?result=seed-paper")
        self.assertEqual(reused["result_id"], "seed-paper")

    def test_manifest_hashes_every_saved_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            store = ResultStore(workspace / "searches")
            store.create({"seeds": ["Seed"]}, result_id="seed")
            (store.result_dir("seed") / "outputs" / "dag.json").write_text(
                "{}\n", encoding="utf-8"
            )
            manifest = store.write_artifact_manifest("seed", workspace=workspace)

        paths = {item["path"] for item in manifest["artifacts"]}
        self.assertIn("request.json", paths)
        self.assertIn("status.json", paths)
        self.assertIn("outputs/dag.json", paths)


if __name__ == "__main__":
    unittest.main()
