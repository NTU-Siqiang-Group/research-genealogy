import unittest

from src.evidence_extraction import (
    EntityOrigin,
    FullTextDocument,
    FullTextSection,
    relation_edges_from_documents,
    parse_bibliography,
    split_sections,
)
from src.schema import PaperRecord


class EvidenceExtractionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.origin = PaperRecord("P:old", "Dostoevsky", 2018)
        self.target = PaperRecord("P:new", "RusKey", 2024)
        self.entity = EntityOrigin(
            entity="Fluid LSM-tree",
            paper_id=self.origin.paper_id,
            evidence_text="We introduce Fluid LSM-tree as a generalized design space.",
            section="1 Introduction",
        )

    def test_related_work_alone_stays_weak(self) -> None:
        document = FullTextDocument(
            paper_id=self.target.paper_id,
            sections=[
                FullTextSection(
                    "7 Related Work",
                    "related_work",
                    "Dostoevsky proposes adaptive merging [17].",
                )
            ],
            reference_ids={17: self.origin.paper_id},
        )
        edge = relation_edges_from_documents(
            [self.origin, self.target], [document], entity_origins=[self.entity]
        )[0]
        self.assertEqual(edge.association_level, "weak")
        self.assertFalse(edge.parent_eligible)

    def test_introduction_discussion_is_medium(self) -> None:
        document = FullTextDocument(
            paper_id=self.target.paper_id,
            sections=[
                FullTextSection(
                    "1.1 Prior Work",
                    "introduction",
                    "Dostoevsky requires a workload known a priori [17], which remains a limitation for dynamic workloads.",
                )
            ],
            reference_ids={17: self.origin.paper_id},
        )
        edge = relation_edges_from_documents(
            [self.origin, self.target], [document], entity_origins=[self.entity]
        )[0]
        self.assertEqual(edge.association_level, "medium")
        self.assertIn("ADDRESSES_LIMITATION", edge.relation_types)
        self.assertFalse(edge.dominant)

    def test_directly_named_method_in_large_intro_citation_list_is_medium(self) -> None:
        self.origin.abstract = (
            "We propose a cache merging approach, called KVMerger, for long contexts."
        )
        document = FullTextDocument(
            paper_id=self.target.paper_id,
            sections=[
                FullTextSection(
                    "1 Introduction",
                    "introduction",
                    "Merging methods such as KVMerger [14], WeightedKV [17], "
                    "D2O [13], and LOOK-M [12] preserve evicted tokens. "
                    "We address two limitations of these uniform merging methods.",
                )
            ],
            reference_ids={14: self.origin.paper_id},
        )
        edge = relation_edges_from_documents([self.origin, self.target], [document])[0]
        self.assertEqual(edge.association_level, "medium")
        self.assertEqual(edge.relation, "ADDRESSES_LIMITATION")
        self.assertIn("DIRECT_DISCUSSION", edge.relation_types)
        self.assertEqual(edge.evidence_details[0].role, "DIRECT_DISCUSSION")

    def test_generic_large_intro_citation_list_stays_weak(self) -> None:
        document = FullTextDocument(
            paper_id=self.target.paper_id,
            sections=[
                FullTextSection(
                    "1 Introduction",
                    "introduction",
                    "Several merging approaches [14, 17, 13, 12] reduce memory use.",
                )
            ],
            reference_ids={14: self.origin.paper_id},
        )
        edge = relation_edges_from_documents([self.origin, self.target], [document])[0]
        self.assertEqual(edge.association_level, "weak")

    def test_author_year_bibliography_and_citation_are_resolved(self) -> None:
        origin = PaperRecord(
            "P:flexgen",
            "FlexGen: High-Throughput Generative Inference of Large Language Models",
            2023,
            metadata={"authors": ["Ying Sheng"]},
        )
        target = PaperRecord("P:next", "A Follow-up System", 2024)
        raw = (
            "1 INTRODUCTION\n"
            "FlexGen offloads model state between CPU and GPU (Sheng et al., 2023), "
            "but this mechanism is limited by transfer bandwidth.\n"
            "REFERENCES\n"
            "Ying Sheng, Lianmin Zheng, and Ion Stoica. FlexGen: High-Throughput "
            "Generative Inference of Large Language Models, 2023.\n"
            "OpenAI. GPT-4 technical report, 2023.\n"
        )
        references = parse_bibliography(raw)
        self.assertEqual(len(references), 2)
        document = FullTextDocument(
            paper_id=target.paper_id,
            sections=split_sections(raw)[0],
            references=references,
        )
        edge = relation_edges_from_documents([origin, target], [document])[0]
        self.assertEqual(edge.source, origin.paper_id)
        self.assertEqual(edge.association_level, "medium")
        self.assertIn("DIRECT_DISCUSSION", edge.relation_types)
        self.assertIn("Sheng et al., 2023", edge.evidence_details[0].citation_marker)

    def test_artifact_baseline_recovers_strong_genealogy(self) -> None:
        document = FullTextDocument(
            paper_id=self.target.paper_id,
            sections=[
                FullTextSection(
                    "6.1 Experimental Setup",
                    "evaluation",
                    "Baselines. We compare RusKey with policy settings in Fluid LSM-tree [17].",
                )
            ],
            reference_ids={17: self.origin.paper_id},
        )
        edge = relation_edges_from_documents(
            [self.origin, self.target], [document], entity_origins=[self.entity]
        )[0]
        self.assertEqual(edge.association_level, "strong")
        self.assertIn("IMPLICIT_BASELINE", edge.relation_types)
        self.assertIn("USES_CONCEPT_FROM", edge.relation_types)
        self.assertTrue(edge.parent_eligible)
        self.assertTrue(edge.dominant)
        self.assertEqual(
            {atom.role for atom in edge.evidence_details},
            {"IMPLICIT_BASELINE", "ENTITY_ORIGIN"},
        )

    def test_entity_provenance_works_without_nearby_citation_marker(self) -> None:
        document = FullTextDocument(
            paper_id=self.target.paper_id,
            sections=[
                FullTextSection(
                    "6 Evaluation",
                    "evaluation",
                    "Our baseline is the Fluid LSM-tree policy under a static workload.",
                )
            ],
        )
        edge = relation_edges_from_documents(
            [self.origin, self.target], [document], entity_origins=[self.entity]
        )[0]
        self.assertFalse(edge.citation_exists)
        self.assertTrue(edge.parent_eligible)

    def test_pdf_style_split_number_and_heading_on_separate_lines(self) -> None:
        sections, bibliography = split_sections(
            "1\n\nINTRODUCTION\nWe design a system.\n"
            "5\n\nEVALUATION\nBaselines. We compare with X [2].\n"
            "6\n\nRELATED WORK\nPrior studies [3].\n"
            "REFERENCES\n[2] X paper.\n[3] Y paper.\n"
        )
        self.assertEqual(
            [(section.heading, section.section_type) for section in sections],
            [
                ("1 INTRODUCTION", "introduction"),
                ("5 EVALUATION", "evaluation"),
                ("6 RELATED WORK", "related_work"),
            ],
        )
        self.assertIn("[2] X paper", bibliography)

    def test_false_self_reference_from_pdf_header_is_ignored(self) -> None:
        document = FullTextDocument(
            paper_id=self.target.paper_id,
            sections=[
                FullTextSection(
                    "6 Evaluation",
                    "evaluation",
                    "We compare against prior compaction schemes [96].",
                )
            ],
            # Simulates a bibliography entry contaminated by a running header
            # containing the target paper's own title.
            reference_ids={96: self.target.paper_id},
        )
        self.assertEqual(
            relation_edges_from_documents([self.origin, self.target], [document]),
            [],
        )

    def test_explicit_baseline_plus_intro_limitation_is_parent_candidate(self) -> None:
        document = FullTextDocument(
            paper_id=self.target.paper_id,
            sections=[
                FullTextSection(
                    "1 Introduction",
                    "introduction",
                    "Dostoevsky is limited by slow transitions [17].",
                ),
                FullTextSection(
                    "6 Evaluation",
                    "evaluation",
                    "Baselines. We compare RusKey against Dostoevsky [17].",
                ),
            ],
            reference_ids={17: self.origin.paper_id},
        )
        edge = relation_edges_from_documents(
            [self.origin, self.target], [document]
        )[0]
        self.assertEqual(edge.association_level, "strong")
        self.assertIn("ADDRESSES_LIMITATION", edge.relation_types)
        self.assertTrue(edge.parent_eligible)

    def test_explicit_baseline_without_intro_lineage_stays_cross_link(self) -> None:
        document = FullTextDocument(
            paper_id=self.target.paper_id,
            sections=[
                FullTextSection(
                    "6 Evaluation",
                    "evaluation",
                    "Baselines. We compare RusKey against Dostoevsky [17].",
                )
            ],
            reference_ids={17: self.origin.paper_id},
        )
        edge = relation_edges_from_documents(
            [self.origin, self.target], [document]
        )[0]
        self.assertEqual(edge.association_level, "strong")
        self.assertFalse(edge.parent_eligible)

    def test_comparative_evaluation_is_an_explicit_baseline(self) -> None:
        document = FullTextDocument(
            paper_id=self.target.paper_id,
            sections=[
                FullTextSection(
                    "4 Evaluation",
                    "evaluation",
                    "We make a comparative evaluation against Dostoevsky [17] using identical workload parameters.",
                )
            ],
            reference_ids={17: self.origin.paper_id},
        )
        edge = relation_edges_from_documents(
            [self.origin, self.target], [document]
        )[0]
        self.assertEqual(edge.association_level, "strong")
        self.assertIn("EXPLICIT_BASELINE", edge.relation_types)
        self.assertEqual(edge.evidence_details[0].role, "EXPLICIT_BASELINE")


if __name__ == "__main__":
    unittest.main()
