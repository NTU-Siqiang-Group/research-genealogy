import unittest

from src.authorship_affinity import key_author_overlap_edges
from src.schema import PaperRecord


def authorship(author_id, name, index, *, corresponding=False):
    return {
        "author_id": author_id,
        "display_name": name,
        "byline_index": index,
        "author_position": "first" if index == 0 else "middle",
        "is_corresponding": corresponding,
    }


class AuthorshipAffinityTest(unittest.TestCase):
    def test_key_author_overlap_is_supplemental_medium(self) -> None:
        older = PaperRecord(
            "P:old",
            "Older",
            2023,
            metadata={
                "authorships": [
                    authorship("OPENALEX:A1", "First Old", 0),
                    authorship("OPENALEX:A2", "Shared Person", 1),
                ]
            },
        )
        newer = PaperRecord(
            "P:new",
            "Newer",
            2024,
            metadata={
                "authorships": [
                    authorship("OPENALEX:A3", "First New", 0),
                    authorship(
                        "OPENALEX:A2", "Shared Person", 2, corresponding=True
                    ),
                ]
            },
        )

        edge = key_author_overlap_edges([newer, older])[0]
        self.assertEqual((edge.source, edge.target), ("P:old", "P:new"))
        self.assertEqual(edge.association_level, "medium")
        self.assertEqual(edge.relation, "SAME_RESEARCH_GROUP")
        self.assertIn("KEY_AUTHOR_OVERLAP", edge.relation_types)
        self.assertFalse(edge.citation_exists)
        self.assertFalse(edge.parent_eligible)
        self.assertFalse(edge.dominant)
        self.assertLess(edge.confidence, 0.72)
        self.assertEqual(edge.evidence_details[0].role, "KEY_AUTHOR_OVERLAP")

    def test_non_key_coauthor_overlap_does_not_create_edge(self) -> None:
        left = PaperRecord(
            "P:left",
            "Left",
            2023,
            metadata={
                "authorships": [
                    authorship("OPENALEX:A1", "First Left", 0),
                    authorship("OPENALEX:A2", "Second Left", 1),
                    authorship("OPENALEX:A9", "Shared Middle", 2),
                ]
            },
        )
        right = PaperRecord(
            "P:right",
            "Right",
            2024,
            metadata={
                "authorships": [
                    authorship("OPENALEX:A3", "First Right", 0),
                    authorship("OPENALEX:A4", "Second Right", 1),
                    authorship("OPENALEX:A9", "Shared Middle", 3),
                ]
            },
        )
        self.assertEqual(key_author_overlap_edges([left, right]), [])

    def test_legacy_ordered_names_support_first_two_authors(self) -> None:
        left = PaperRecord(
            "P:left",
            "Left",
            2023,
            metadata={"authors": ["Alice Smith", "Bob Jones"]},
        )
        right = PaperRecord(
            "P:right",
            "Right",
            2024,
            metadata={"authors": ["Carol Lee", "Bob Jones"]},
        )
        edge = key_author_overlap_edges([left, right])[0]
        self.assertEqual(edge.association_level, "medium")
        self.assertEqual(edge.evidence_details[0].entity, "Bob Jones")


if __name__ == "__main__":
    unittest.main()
