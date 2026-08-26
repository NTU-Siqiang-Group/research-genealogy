import unittest

from scripts._import_support import rewrite_path_prefixes


class ImportSupportTest(unittest.TestCase):
    def test_nested_paths_are_rewritten(self):
        value = {"a": ["data/raw/pdfs/a.pdf", "https://example.test/a.pdf"]}
        rewritten = rewrite_path_prefixes(
            value, {"data/raw/pdfs/": "data/searches/run/raw/pdfs/"}
        )
        self.assertEqual(rewritten["a"][0], "data/searches/run/raw/pdfs/a.pdf")
        self.assertEqual(rewritten["a"][1], "https://example.test/a.pdf")


if __name__ == "__main__":
    unittest.main()
