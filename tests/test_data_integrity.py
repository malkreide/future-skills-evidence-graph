from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from jsonschema import Draft202012Validator  # noqa: E402

from cluster_claims import cluster_candidate_skills  # noqa: E402
from common import (  # noqa: E402
    RELEVANCE_MODEL_PATH,
    RELEVANCE_THRESHOLD,
    append_candidate_sources,
    decide_relevance,
    fetch_or_warn,
    filter_new_claims,
    filter_new_sources,
    filter_relevant_sources,
    is_off_scope,
    load_json,
    load_records,
    load_relevance_model,
    normalize_title,
    relevance_classifier_mode,
    score_relevance,
    write_json,
)
from extract_claims import (  # noqa: E402
    AGE_RANGE_PLACEHOLDER,
    CONTEXT_PLACEHOLDER_SUFFIX,
    OUTCOME_PLACEHOLDER,
    best_claim_sentence,
    claim_from_source,
    sentence_tier,
)
from promote_candidate import claim_review_errors, skill_activation_errors  # noqa: E402
from score_evidence import reviewed_claim_scores, skill_score  # noqa: E402
from validate_data import validate_repository  # noqa: E402


class DataIntegrityTests(unittest.TestCase):
    def test_repository_validates(self) -> None:
        self.assertEqual(validate_repository(), [])

    def test_active_skills_have_reviewed_evidence_path(self) -> None:
        claims = {claim["id"]: claim for claim in load_records("claims")}
        sources = {source["id"]: source for source in load_records("sources")}
        for skill in load_records("skills"):
            if skill["status"] != "active":
                continue
            self.assertGreater(len(skill["supporting_claim_ids"]), 0, skill["id"])
            referenced = skill["supporting_claim_ids"] + skill.get("contradicting_claim_ids", [])
            for claim_id in referenced:
                claim = claims[claim_id]
                self.assertEqual(claim["status"], "reviewed", claim_id)
                for source_id in claim["source_ids"]:
                    self.assertIn(source_id, sources)
                    self.assertEqual(sources[source_id]["status"], "reviewed", source_id)

    def test_skill_score_rewards_breadth_and_penalizes_contradictions(self) -> None:
        claim_scores = {"c1": 0.8, "c2": 0.8, "c3": 0.6}
        narrow = {"supporting_claim_ids": ["c1"]}
        broad = {"supporting_claim_ids": ["c1", "c2"]}
        contradicted = {"supporting_claim_ids": ["c1"], "contradicting_claim_ids": ["c3"]}
        unsupported = {"supporting_claim_ids": []}
        self.assertGreater(skill_score(broad, claim_scores), skill_score(narrow, claim_scores))
        self.assertGreater(skill_score(narrow, claim_scores), skill_score(contradicted, claim_scores))
        self.assertEqual(skill_score(unsupported, claim_scores), 0.0)
        self.assertEqual(skill_score(broad, claim_scores), skill_score(broad, claim_scores))

    def test_scoring_excludes_unreviewed_claims(self) -> None:
        sources = {"src-1": {"id": "src-1", "source_type": "systematic_review"}}
        claims = [
            {"id": "c-reviewed", "status": "reviewed", "evidence_strength": "strong", "source_ids": ["src-1"]},
            {"id": "c-candidate", "status": "candidate", "evidence_strength": "strong", "source_ids": ["src-1"]},
            {"id": "c-rejected", "status": "rejected", "evidence_strength": "strong", "source_ids": ["src-1"]},
        ]
        scores = reviewed_claim_scores(claims, sources)
        self.assertEqual(set(scores), {"c-reviewed"})

        clean = {"supporting_claim_ids": ["c-reviewed"]}
        inflated = {"supporting_claim_ids": ["c-reviewed", "c-candidate", "c-rejected"]}
        self.assertEqual(skill_score(inflated, scores), skill_score(clean, scores))

        contradicted = {
            "supporting_claim_ids": ["c-reviewed"],
            "contradicting_claim_ids": ["c-candidate"],
        }
        self.assertEqual(skill_score(contradicted, scores), skill_score(clean, scores))

    def test_relevance_scoring_separates_scope_from_noise(self) -> None:
        relevant = {
            "title": "AI literacy and critical thinking for children in primary school",
            "abstract": "We study how students develop competence with artificial intelligence.",
        }
        irrelevant = {
            "title": "Lattice simulations of quantum chromodynamics",
            "abstract": "We present improved gauge field configurations.",
        }
        relevant_score, relevant_topics = score_relevance(relevant)
        irrelevant_score, irrelevant_topics = score_relevance(irrelevant)
        self.assertGreaterEqual(relevant_score, 0.3)
        self.assertIn("ai literacy", relevant_topics)
        self.assertIn("critical thinking", relevant_topics)
        self.assertLess(irrelevant_score, 0.3)
        self.assertEqual(irrelevant_topics, [])

        kept = filter_relevant_sources([dict(relevant), dict(irrelevant)])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["title"], relevant["title"])
        self.assertEqual(kept[0]["relevance_score"], relevant_score)
        self.assertEqual(kept[0]["topics"], relevant_topics)

    def test_filter_new_sources_avoids_id_collisions(self) -> None:
        existing_id = load_records("sources")[0]["id"]
        candidates = [
            {
                "id": existing_id,
                "title": "A unique candidate title alpha",
                "url": "https://example.test/alpha",
                "year": 2026,
            },
            {
                "id": existing_id,
                "title": "A unique candidate title beta",
                "url": "https://example.test/beta",
                "year": 2026,
            },
        ]
        kept = filter_new_sources(candidates)
        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[0]["id"], f"{existing_id}-2")
        self.assertEqual(kept[1]["id"], f"{existing_id}-3")

    def test_append_candidate_sources_preserves_earlier_batches(self) -> None:
        week_one = [
            {
                "id": "src-alpha",
                "title": "A unique candidate title alpha",
                "url": "https://example.test/alpha",
                "year": 2026,
            },
            {
                "id": "src-beta",
                "title": "A unique candidate title beta",
                "url": "https://example.test/beta",
                "year": 2026,
            },
        ]
        week_two = [
            # Duplicate of an existing record: must not be appended again.
            {
                "id": "src-alpha-dup",
                "title": "A unique candidate title alpha",
                "url": "https://example.test/alpha",
                "year": 2026,
            },
            # Id collision with an existing record: must get a suffix.
            {
                "id": "src-beta",
                "title": "A unique candidate title gamma",
                "url": "https://example.test/gamma",
                "year": 2026,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates-test.json"
            write_json(path, week_one)
            appended = append_candidate_sources(path, week_two)
            self.assertEqual(len(appended), 1)
            self.assertEqual(appended[0]["id"], "src-beta-2")
            stored = load_json(path)
            self.assertEqual(
                [record["id"] for record in stored],
                ["src-alpha", "src-beta", "src-beta-2"],
            )

    def test_append_candidate_sources_skips_empty_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "candidates-empty.json"
            self.assertEqual(append_candidate_sources(missing, []), [])
            self.assertFalse(missing.exists())

            existing = Path(tmp) / "candidates-existing.json"
            records = [
                {
                    "id": "src-alpha",
                    "title": "A unique candidate title alpha",
                    "url": "https://example.test/alpha",
                    "year": 2026,
                }
            ]
            write_json(existing, records)
            before = existing.stat().st_mtime_ns
            self.assertEqual(append_candidate_sources(existing, []), [])
            self.assertEqual(existing.stat().st_mtime_ns, before)
            self.assertEqual(load_json(existing), records)

    def test_claim_extraction_uses_verbatim_text_anchor(self) -> None:
        source = {
            "id": "src-test-ai-literacy",
            "source_type": "systematic_review",
            "status": "candidate",
            "abstract": (
                "Background remarks describing the structure of this paper come first. "
                "We find that AI literacy instruction improves critical thinking among "
                "primary school students. Short note."
            ),
        }
        claim = claim_from_source(source)
        self.assertIsNotNone(claim)
        self.assertEqual(
            claim["statement"],
            "We find that AI literacy instruction improves critical thinking among "
            "primary school students.",
        )
        self.assertIn('sentence 2: "We find that AI literacy', claim["text_anchor"])
        self.assertEqual(claim["source_ids"], ["src-test-ai-literacy"])
        self.assertEqual(claim["evidence_type"], "systematic_review")
        self.assertEqual(claim["evidence_strength"], "low")
        self.assertEqual(claim["status"], "candidate")
        schema = load_json(ROOT / "schemas" / "claim.schema.json")
        Draft202012Validator(schema).validate(claim)

        self.assertIsNone(claim_from_source({"id": "src-x", "abstract": None}))
        self.assertIsNone(
            claim_from_source(
                {
                    "id": "src-x",
                    "abstract": "Lattice quantum chromodynamics simulations with improved gauge actions.",
                }
            )
        )

    def test_arxiv_convert_maps_atom_entry_to_source(self) -> None:
        from xml.etree import ElementTree

        import ingest_arxiv

        entry_xml = (
            '<entry xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:arxiv="http://arxiv.org/schemas/atom">'
            "<id>http://arxiv.org/abs/2510.12345v1</id>"
            "<title>AI literacy for school children</title>"
            "<summary>We study AI literacy education for students.</summary>"
            "<published>2025-10-26T22:56:08Z</published>"
            '<link href="https://arxiv.org/abs/2510.12345v1" rel="alternate" type="text/html"/>'
            "<author><name>Jane Doe</name></author>"
            "<author><name>John Roe</name></author>"
            "</entry>"
        )
        record = ingest_arxiv.convert(ElementTree.fromstring(entry_xml))
        self.assertEqual(record["title"], "AI literacy for school children")
        self.assertEqual(record["year"], 2025)
        self.assertEqual(record["authors"], ["Jane Doe", "John Roe"])
        self.assertEqual(record["url"], "https://arxiv.org/abs/2510.12345v1")
        self.assertEqual(record["source_type"], "working_paper")
        self.assertTrue(record["abstract"])
        Draft202012Validator(load_json(ROOT / "schemas" / "source.schema.json")).validate(record)

    def test_eric_convert_and_source_type(self) -> None:
        import ingest_eric

        journal = {
            "id": "EJ1476161",
            "title": "Developing a Holistic AI Literacy Framework for Children",
            "author": ["A. Author", "B. Author"],
            "description": "A framework for AI literacy among children.",
            "publicationdateyear": 2025,
            "url": "http://dx.doi.org/10.1000/example",
            "peerreviewed": "T",
            "publicationtype": ["Journal Articles", "Reports - Research"],
            "source": "Journal of AI Education",
        }
        record = ingest_eric.convert(journal)
        self.assertEqual(record["eric_id"], "EJ1476161")
        self.assertEqual(record["year"], 2025)
        self.assertEqual(record["source_type"], "peer_reviewed_article")
        self.assertEqual(record["publisher"], "Journal of AI Education")
        Draft202012Validator(load_json(ROOT / "schemas" / "source.schema.json")).validate(record)

        # Document-type precedence: a standalone report is a policy report,
        # books are books, journal articles win over the "report" descriptor.
        self.assertEqual(ingest_eric._source_type({"publicationtype": ["Reports - Descriptive"]}), "policy_report")
        self.assertEqual(ingest_eric._source_type({"publicationtype": ["Books", "Reports - Research"]}), "book")
        self.assertEqual(
            ingest_eric._source_type({"publicationtype": ["Journal Articles", "Reports - Research"]}),
            "peer_reviewed_article",
        )
        # A record with no URL falls back to a stable ERIC link.
        no_url = ingest_eric.convert({"id": "ED678840", "title": "AI Literacy for the Workforce"})
        self.assertEqual(no_url["url"], "https://eric.ed.gov/?id=ED678840")

    def test_sentence_tier_separates_findings_from_methods(self) -> None:
        self.assertEqual(sentence_tier("Findings show that students improved their critical thinking."), 1)
        self.assertEqual(sentence_tier("We used semi-structured interviews with thirty participants."), -1)
        self.assertEqual(sentence_tier("This paper introduces a six-step pedagogical design framework."), -1)
        self.assertEqual(sentence_tier("AI literacy is increasingly important for school children."), 0)

    def test_extraction_prefers_findings_over_methodology(self) -> None:
        # A finding sentence is chosen over a topic-matching methodology sentence.
        abstract = (
            "We used semi-structured interviews to study AI literacy in schools. "
            "Findings show that AI literacy instruction improves critical thinking among students."
        )
        picked = best_claim_sentence(abstract)
        self.assertIsNotNone(picked)
        self.assertTrue(picked[1].startswith("Findings show that AI literacy"))

    def test_extraction_skips_methodology_only_sources(self) -> None:
        # When the only topic-matching sentence is methodology/structure, no
        # claim is emitted rather than a "we used interviews" pseudo-claim.
        abstract = "We used semi-structured interviews to explore AI literacy among students in schools."
        self.assertIsNone(best_claim_sentence(abstract))

    def test_filter_new_claims_drops_known_statements(self) -> None:
        existing = load_records("claims")[0]
        duplicate = {
            "id": "claim-duplicate-statement",
            "statement": existing["statement"],
        }
        colliding = {
            "id": existing["id"],
            "statement": "A genuinely new candidate claim statement about creativity.",
        }
        kept = filter_new_claims([duplicate, colliding])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["id"], f"{existing['id']}-2")

    def test_clustering_proposes_skills_only_for_uncovered_topics(self) -> None:
        claims = [
            {
                "id": "claim-a",
                "status": "candidate",
                "statement": "Creativity training fosters creative thinking in students.",
            },
            {
                "id": "claim-b",
                "status": "candidate",
                "statement": "Creative problem solving practice benefits pupils in classrooms.",
            },
            {
                "id": "claim-c",
                "status": "reviewed",
                "statement": "Creativity also appears in reviewed claims about schools.",
            },
        ]
        proposals, hints = cluster_candidate_skills(claims, [], min_claims=2)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["id"], "skill-creativity")
        self.assertEqual(proposals[0]["status"], "candidate")
        self.assertEqual(proposals[0]["evidence_score"], 0.0)
        self.assertEqual(proposals[0]["supporting_claim_ids"], ["claim-a", "claim-b"])
        schema = load_json(ROOT / "schemas" / "skill.schema.json")
        Draft202012Validator(schema).validate(proposals[0])
        self.assertEqual(hints, [])

        existing_skill = {"id": "skill-creative-problem-solving", "topics": ["creativity"]}
        proposals, hints = cluster_candidate_skills(claims, [existing_skill], min_claims=2)
        self.assertEqual(proposals, [])
        self.assertEqual(
            hints,
            [("creativity", "skill-creative-problem-solving", ["claim-a", "claim-b"])],
        )

    def test_claim_review_gate_blocks_placeholders_and_dangling_refs(self) -> None:
        extracted = claim_from_source(
            {
                "id": "src-gate",
                "source_type": "empirical_study",
                "status": "candidate",
                "abstract": "AI literacy instruction improves critical thinking for primary school students here.",
            }
        )
        # As extracted: placeholders for context/age/outcome, no skill link.
        errors = claim_review_errors(extracted, skill_ids=set(), source_ids={"src-gate"})
        joined = " | ".join(errors)
        self.assertIn("context", joined)
        self.assertIn("age_range", joined)
        self.assertIn("outcome", joined)
        self.assertIn("link at least one skill", joined)

        # Reviewer fills the fields but points at a skill and source that do not exist.
        extracted.update(
            context="K-12 classroom study",
            age_range="6-12",
            outcome="Learners critique AI outputs",
            supports_skill_ids=["skill-missing"],
        )
        errors = claim_review_errors(extracted, skill_ids=set(), source_ids=set())
        self.assertEqual(
            sorted(errors),
            ["references missing skill skill-missing", "references missing source src-gate"],
        )

        # Everything resolvable -> no errors.
        self.assertEqual(
            claim_review_errors(extracted, skill_ids={"skill-missing"}, source_ids={"src-gate"}),
            [],
        )

    def test_skill_activation_gate_requires_definition_and_reviewed_claims(self) -> None:
        candidate = {
            "definition": "Candidate skill clustered from 2 candidate claims about ethics. "
            "Definition requires human review.",
            "supporting_claim_ids": ["claim-x"],
            "contradicting_claim_ids": [],
        }
        claims = {"claim-x": {"id": "claim-x", "status": "candidate"}}
        errors = skill_activation_errors(candidate, claims)
        joined = " | ".join(errors)
        self.assertIn("definition still holds a placeholder", joined)
        self.assertIn("claim-x is candidate", joined)

        candidate["definition"] = "Ability to reason about the ethics of technology use."
        claims["claim-x"]["status"] = "reviewed"
        self.assertEqual(skill_activation_errors(candidate, claims), [])

        # An empty supporting set is rejected even with a real definition.
        self.assertIn(
            "needs at least one supporting claim",
            " | ".join(skill_activation_errors({"definition": "Real definition text here.",
                                                 "supporting_claim_ids": []}, claims)),
        )

    def test_extracted_claim_fields_are_recognized_as_placeholders(self) -> None:
        # Guards against the generators and the review gate drifting apart.
        claim = claim_from_source(
            {
                "id": "src-drift",
                "source_type": "systematic_review",
                "status": "candidate",
                "abstract": "Digital literacy education supports media literacy for adolescent learners in schools.",
            }
        )
        self.assertTrue(claim["context"].endswith(CONTEXT_PLACEHOLDER_SUFFIX))
        self.assertEqual(claim["age_range"], AGE_RANGE_PLACEHOLDER)
        self.assertEqual(claim["outcome"], OUTCOME_PLACEHOLDER)
        errors = claim_review_errors(claim, skill_ids=set(), source_ids={"src-drift"})
        self.assertTrue(any("context" in error for error in errors))
        self.assertTrue(any("age_range" in error for error in errors))
        self.assertTrue(any("outcome" in error for error in errors))

    def test_fetch_or_warn_degrades_gracefully_on_source_outage(self) -> None:
        import urllib.error

        def rate_limited() -> list[dict[str, object]]:
            raise urllib.error.HTTPError("https://api.test", 429, "Too Many Requests", {}, None)

        def malformed() -> list[dict[str, object]]:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

        # A failing source returns no records instead of raising, so the
        # pipeline keeps running on the other sources.
        self.assertEqual(fetch_or_warn("Test", rate_limited), [])
        self.assertEqual(fetch_or_warn("Test", malformed), [])
        self.assertEqual(
            fetch_or_warn("Test", lambda: [{"id": "src-ok"}]),
            [{"id": "src-ok"}],
        )

    def test_relevance_requires_a_topic_match(self) -> None:
        # Audience terms alone must not qualify a source: a paper that only
        # mentions "school" or "students" but matches no topic is dropped.
        audience_only = {
            "title": "Menstrual hygiene practices among primary school girls",
            "abstract": "A public health study of hygiene management for school students.",
        }
        topic_match = {
            "title": "AI literacy for school students",
            "abstract": "Building artificial intelligence competence among pupils.",
        }
        kept = filter_relevant_sources([dict(audience_only), dict(topic_match)])
        self.assertEqual([source["title"] for source in kept], [topic_match["title"]])

    def test_off_scope_drops_incidental_matches_keeps_anchored(self) -> None:
        # An off-scope term plus only an incidental abstract topic match is
        # discarded, but the same off-scope term is tolerated when the future
        # skill is named in the title (a genuine topic anchor).
        incidental = {
            "title": "The Relationship between Student Health and Academic Performance",
            "abstract": "We examine the complexity of nutrition, fitness and obesity in pupils.",
        }
        anchored = {
            "title": "AI literacy and nutrition: teaching pupils about data",
            "abstract": "An artificial intelligence literacy unit that also covers nutrition.",
        }
        clean = {
            "title": "Computational thinking in primary computing education",
            "abstract": "A systems thinking curriculum for school children.",
        }
        self.assertTrue(is_off_scope(incidental))
        self.assertFalse(is_off_scope(anchored))
        self.assertFalse(is_off_scope(clean))
        kept = filter_relevant_sources([dict(incidental), dict(anchored), dict(clean)])
        self.assertEqual(
            [source["title"] for source in kept], [anchored["title"], clean["title"]]
        )

    def test_relevance_heuristic_meets_measured_floor(self) -> None:
        # Guards the keyword classifier against regressions using the labeled
        # eval set. The off-scope filter raised measured precision from 0.78 to
        # 1.00 at recall 1.00; floors sit below that with margin.
        import eval_relevance

        examples = eval_relevance.load_examples()
        metrics = eval_relevance.evaluate(examples, RELEVANCE_THRESHOLD)
        self.assertGreaterEqual(metrics.precision, 0.90, "relevance precision regressed")
        self.assertGreaterEqual(metrics.recall, 0.90, "relevance recall regressed")

    def test_reject_missing_record_reports_error(self) -> None:
        from argparse import Namespace

        from promote_candidate import reject_record

        errors = reject_record(Namespace(id="claim-does-not-exist-xyz"))
        self.assertTrue(errors)
        self.assertIn("not found", errors[0])

    def test_reject_source_missing_reports_error(self) -> None:
        from argparse import Namespace

        from promote_candidate import reject_source

        errors = reject_source(Namespace(id="src-does-not-exist-xyz"))
        self.assertTrue(errors)
        self.assertIn("not found", errors[0])

    def test_harvest_dedup_and_provenance(self) -> None:
        # A positive label carries its provenance; a later decision for the same
        # normalized title is ignored (append-only, first decision wins).
        import promote_candidate as pc

        with tempfile.TemporaryDirectory() as tmp:
            original = pc.HARVEST_PATH
            pc.HARVEST_PATH = Path(tmp) / "relevance_harvested.json"
            try:
                positive = pc._harvest_example(
                    {"id": "src-x", "title": "AI Literacy: For Pupils!", "abstract": "abc"},
                    True,
                    "promote_claim",
                    claim_id="claim-x",
                )
                self.assertEqual(pc.record_relevance_labels([positive]), 1)
                # Same title, different punctuation/case and opposite decision.
                duplicate = pc._harvest_example(
                    {"id": "src-y", "title": "ai literacy for pupils", "abstract": "z"},
                    False,
                    "reject_source",
                )
                self.assertEqual(pc.record_relevance_labels([duplicate]), 0)
                # An empty batch is a no-op.
                self.assertEqual(pc.record_relevance_labels([]), 0)

                payload = load_json(pc.HARVEST_PATH)
                self.assertEqual(len(payload["examples"]), 1)
                example = payload["examples"][0]
                self.assertTrue(example["relevant"])
                self.assertEqual(example["origin"], "harvested")
                self.assertEqual(example["decision"], "promote_claim")
                self.assertEqual(example["source_id"], "src-x")
                self.assertEqual(example["claim_id"], "claim-x")
                self.assertIn("harvested_at", example)
                self.assertIn("title", example)
                self.assertIn("abstract", example)
                # The bias / do-not-replace note travels with the harvested file.
                self.assertIn("SELECTION BIAS", payload["_README"])
            finally:
                pc.HARVEST_PATH = original

    def test_promoted_claim_harvests_positive_per_source(self) -> None:
        # promote_claim's success maps the claim to a positive label for each of
        # its sources; rejected claims never reach this path (no naive negatives).
        import promote_candidate as pc

        sources = {
            "src-a": {"id": "src-a", "title": "Critical thinking in schools", "abstract": "x"},
            "src-b": {"id": "src-b", "title": "Data literacy for teens", "abstract": "y"},
        }
        original_find = pc.find_record
        original_path = pc.HARVEST_PATH
        pc.find_record = lambda kind, rid: (None, None, sources[rid]) if rid in sources else None
        with tempfile.TemporaryDirectory() as tmp:
            pc.HARVEST_PATH = Path(tmp) / "relevance_harvested.json"
            try:
                claim = {"id": "claim-z", "source_ids": ["src-a", "src-b", "src-missing"]}
                added = pc._harvest_promoted_claim(claim)
                self.assertEqual(added, 2)
                labels = load_json(pc.HARVEST_PATH)["examples"]
                self.assertTrue(all(label["relevant"] for label in labels))
                self.assertTrue(all(label["decision"] == "promote_claim" for label in labels))
                self.assertEqual({label["source_id"] for label in labels}, {"src-a", "src-b"})
            finally:
                pc.find_record = original_find
                pc.HARVEST_PATH = original_path

    def test_eval_combine_examples_prefers_curated(self) -> None:
        # The harvested set supplements the curated set without overriding it,
        # and is deduped by normalized title; the curated file stays separate.
        import eval_relevance

        curated = [{"title": "Shared Title", "abstract": "c", "relevant": True}]
        harvested = [
            {"title": "shared title", "abstract": "h", "relevant": False, "origin": "harvested"},
            {"title": "Fresh Harvested", "abstract": "h2", "relevant": True, "origin": "harvested"},
        ]
        combined = eval_relevance.combine_examples(curated, harvested)
        self.assertEqual(len(combined), 2)
        shared = next(ex for ex in combined if ex["title"] == "Shared Title")
        self.assertEqual(shared["abstract"], "c")  # curated wins
        self.assertNotEqual(eval_relevance.EVAL_PATH, eval_relevance.HARVESTED_PATH)

    def test_normalize_title_is_deduplication_friendly(self) -> None:
        self.assertEqual(
            normalize_title("AI Literacy: Future-Skills in Education!"),
            normalize_title("ai literacy future skills in education"),
        )

    def test_lehrplan21_mappings_have_coverage_metadata(self) -> None:
        all_skills = load_records("skills")
        skills = {skill["id"] for skill in all_skills}
        active_skills = {skill["id"] for skill in all_skills if skill["status"] == "active"}
        mappings = [
            mapping
            for mapping in load_records("frameworks")
            if mapping.get("framework_group") == "Lehrplan 21"
        ]
        mapped_skills = {mapping["skill_id"] for mapping in mappings}
        self.assertLessEqual(
            active_skills,
            mapped_skills,
            f"active skills without Lehrplan 21 mapping: {sorted(active_skills - mapped_skills)}",
        )
        for mapping in mappings:
            self.assertIn(mapping["skill_id"], skills)
            self.assertGreaterEqual(mapping["coverage_score"], 0)
            self.assertLessEqual(mapping["coverage_score"], 3)
            self.assertIn(mapping["coverage_label"], {"gut abgedeckt", "teilweise", "Zukunftsluecke"})
            self.assertTrue(mapping["cycles"])
            self.assertTrue(mapping["evidence_path"])

    def test_relevance_decision_defaults_to_heuristic(self) -> None:
        # The default decision (no env flag) must be the deterministic heuristic,
        # byte-for-byte the same keep/score/topics it always produced.
        import os
        from unittest import mock

        relevant = {
            "title": "AI literacy and critical thinking for school students",
            "abstract": "A classroom study with pupils.",
        }
        off_scope = {
            "title": "Soil nutrition in wastewater refinery effluent",
            "abstract": "An agriculture and salary study.",
        }
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RELEVANCE_CLASSIFIER", None)
            self.assertEqual(relevance_classifier_mode(), "heuristic")
            keep, score, topics = decide_relevance(relevant)
            expected_score, expected_topics = score_relevance(relevant)
            self.assertTrue(keep)
            self.assertEqual(score, expected_score)
            self.assertEqual(topics, expected_topics)
            self.assertFalse(decide_relevance(off_scope)[0])

    def test_model_mode_falls_back_to_heuristic_when_artifact_missing(self) -> None:
        # Opting into the model but with no artifact must not break the pipeline:
        # it falls back to the heuristic decision rather than raising.
        import os
        from unittest import mock

        import common

        relevant = {
            "title": "Data literacy and collaboration in K-12 education",
            "abstract": "A study of learners.",
        }
        heuristic = decide_relevance(relevant)  # env unset here
        with mock.patch.dict(os.environ, {"RELEVANCE_CLASSIFIER": "model"}), mock.patch.object(
            common, "RELEVANCE_MODEL_PATH", Path(tempfile.gettempdir()) / "no_such_model.json"
        ), mock.patch.object(common, "_model_fallback_warned", False):
            self.assertEqual(relevance_classifier_mode(), "model")
            self.assertIsNone(load_relevance_model())
            self.assertEqual(decide_relevance(relevant), heuristic)

    def test_model_mode_keeps_keyword_topics_as_companion_signal(self) -> None:
        # With the model active the data model is unchanged: relevance_score holds
        # the model probability, but topics stay the explainable keyword signal.
        import os
        from unittest import mock

        artifact = load_relevance_model()
        self.assertIsNotNone(artifact, "committed model artifact should load")
        source = {
            "title": "AI literacy and critical thinking in classrooms",
            "abstract": "A study with students.",
        }
        _, keyword_topics = score_relevance(source)
        with mock.patch.dict(os.environ, {"RELEVANCE_CLASSIFIER": "model"}):
            keep, score, topics = decide_relevance(source)
        self.assertEqual(topics, keyword_topics)
        self.assertTrue(0.0 <= score <= 1.0)
        self.assertIsInstance(keep, bool)

    def test_model_artifact_is_versioned_and_reproducible(self) -> None:
        # The committed artifact must carry the provenance needed to reproduce it.
        artifact = load_relevance_model()
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact["model_type"], "tfidf+logreg")
        training = artifact["training"]
        self.assertEqual(training["seed"], 42)
        self.assertIn("sklearn_version", training)
        self.assertEqual(len(artifact["classifier"]["coef"]), training["n_features"])
        self.assertEqual(len(artifact["vectorizer"]["idf"]), training["n_features"])
        self.assertEqual(len(artifact["vectorizer"]["vocabulary"]), training["n_features"])

    def test_stdlib_scorer_reproduces_sklearn(self) -> None:
        # The stdlib inference must reproduce scikit-learn's predict_proba so the
        # importers can stay dependency-free. Skipped when sklearn is absent.
        try:
            import train_relevance
        except ImportError:
            self.skipTest("scikit-learn not installed")
        texts, labels, _ = train_relevance.load_examples(include_harvested=False)
        vectorizer, classifier = train_relevance.fit_model(texts, labels)
        artifact = train_relevance.build_artifact(vectorizer, classifier, texts, labels, ["test"])
        max_diff = train_relevance.self_check(artifact, vectorizer, classifier, texts)
        self.assertLess(max_diff, 1e-9)


if __name__ == "__main__":
    unittest.main()
