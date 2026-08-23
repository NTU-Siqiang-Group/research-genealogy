import unittest

from src.authorship_enrichment import (
    corresponding_authors_from_front_matter,
)


AUTHORSHIPS = [
    {"display_name": "Dingheng Mo"},
    {"display_name": "Fanchao Chen"},
    {"display_name": "Siqiang Luo"},
    {"display_name": "Caihua Shan"},
]


class AuthorshipEnrichmentTest(unittest.TestCase):
    def test_explicit_corresponding_author_statement(self) -> None:
        text = """
        DINGHENG MO, University A
        SIQIANG LUO†, University A
        † Siqiang Luo is the corresponding author.
        """
        matches = corresponding_authors_from_front_matter(text, AUTHORSHIPS)
        self.assertEqual([match.display_name for match in matches], ["Siqiang Luo"])
        self.assertEqual(matches[0].method, "explicit_statement")

    def test_footnote_marker_and_legend(self) -> None:
        text = """
        WEIPING YU, University A
        SIQIANG LUO†, University A
        ZIHAO YU, University A
        † Corresponding Author
        """
        matches = corresponding_authors_from_front_matter(text, AUTHORSHIPS)
        self.assertEqual([match.display_name for match in matches], ["Siqiang Luo"])
        self.assertEqual(matches[0].method, "matched_footnote_marker")

    def test_ordinary_contact_list_is_not_guessed_as_correspondence(self) -> None:
        text = "Authors' Contact Information: Siqiang Luo, siqiang@example.edu"
        self.assertEqual(
            corresponding_authors_from_front_matter(text, AUTHORSHIPS), []
        )


if __name__ == "__main__":
    unittest.main()
