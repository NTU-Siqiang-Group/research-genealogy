import tempfile
import unittest
from pathlib import Path

from src.app_server import SearchManager
from src.result_store import ResultStore


class FakePipeline:
    def __init__(self, store):
        self.store = store

    def run(self, result_id):
        self.store.update_status(
            result_id,
            state="completed",
            stage="completed",
            progress=100,
            message="ready",
        )


class SearchManagerTest(unittest.TestCase):
    def test_completed_identical_request_is_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ResultStore(Path(temporary) / "searches")
            manager = SearchManager(store, lambda: FakePipeline(store))
            request = {"seeds": ["A paper"], "fulltext_limit": 0}
            first, reused = manager.submit(request)
            self.assertFalse(reused)
            manager.executor.shutdown(wait=True)
            second_manager = SearchManager(store, lambda: FakePipeline(store))
            second, reused = second_manager.submit(request)
            self.assertTrue(reused)
            self.assertEqual(first["result_id"], second["result_id"])
            second_manager.close()


if __name__ == "__main__":
    unittest.main()
