from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from jsonschema import Draft202012Validator  # noqa: E402

from cluster_claims import (  # noqa: E402
    EMBEDDING_CLUSTER_THRESHOLD,
    cluster_candidate_skills,
    cluster_candidate_skills_embedding,
    cluster_method,
    cluster_skills,
)
from common import source_is_valid_candidate  # noqa: E402
from common import (  # noqa: E402
    DEFAULT_RESEARCH_QUERIES,
    RELEVANCE_MODEL_PATH,
    RELEVANCE_THRESHOLD,
    append_candidate_sources,
    classify_audience,
    decide_relevance,
    dedupe_queries,
    fetch_or_warn,
    filter_new_claims,
    filter_new_sources,
    filter_relevant_sources,
    heuristic_keep,
    is_adult_audience,
    is_educator_audience,
    is_off_scope,
    is_title_duplicate,
    load_json,
    load_records,
    load_research_queries,
    load_relevance_anchors,
    load_relevance_model,
    normalize_title,
    relevance_classifier_mode,
    score_relevance,
    title_similarity,
    write_json,
)
from extract_claims import (  # noqa: E402
    AGE_RANGE_PLACEHOLDER,
    CONTEXT_PLACEHOLDER_SUFFIX,
    OUTCOME_PLACEHOLDER,
    PREFILL_OUTPUT_SCHEMA,
    PREFILL_PROMPT_VERSION,
    best_claim_sentence,
    claim_from_source,
    prefill_prompt,
    sentence_tier,
    suggest_claim_fields,
)
from extract_pdf_text import clean_extracted_text  # noqa: E402
import ingest_reports  # noqa: E402
from ingest_reports import (  # noqa: E402
    MIN_PASSAGE_LENGTH,
    truncate_report_text,
    REPORT_OUTPUT_SCHEMA,
    REPORT_PROMPT_VERSION,
    build_claims,
    build_source,
    import_job,
    load_jobs,
    normalize_for_match,
    propose_report,
    report_candidates,
    report_prompt,
    verbatim_passage,
)
from promote_candidate import (  # noqa: E402
    apply_claim_suggestions,
    claim_review_errors,
    claim_suggestions,
    format_claim_suggestions,
    skill_activation_errors,
)
from score_evidence import reviewed_claim_scores, skill_score  # noqa: E402
from triage_candidates import build_worksheet  # noqa: E402
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

    def test_skill_score_resolves_rounding_boundary_reproducibly(self) -> None:
        # Ten claim scores summing to exactly 7.75 put the mean (0.775) on a
        # rounding boundary. The builtin sum accumulates float error to
        # 7.749999... on Python < 3.12 (rounds to 0.77) but is exact on 3.12
        # (rounds to 0.78); math.fsum is exact on every version. The score must
        # be 0.78 regardless of interpreter, or the stored evidence_score is not
        # reproducible across environments (it was the skill-ai-literacy case).
        boundary = {f"c{i}": v for i, v in enumerate(
            [0.895, 0.76, 0.82, 0.7, 0.7, 0.835, 0.76, 0.76, 0.76, 0.76]
        )}
        skill = {"supporting_claim_ids": list(boundary)}
        self.assertEqual(skill_score(skill, boundary), 0.78)

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

    def test_off_scope_covers_pe_and_language_pedagogy(self) -> None:
        # Physical education and foreign-language pedagogy are out of the topic
        # scope; with no topic anchor in the title they are dropped.
        pe = {
            "title": "Integrating technology into physical education classes",
            "abstract": "We study collaboration in school physical activity programs.",
        }
        efl = {
            "title": "Speech recognition technology for EFL learning",
            "abstract": "We examine AI literacy gains among English language learners.",
        }
        self.assertTrue(is_off_scope(pe))
        self.assertTrue(is_off_scope(efl))
        self.assertEqual(filter_relevant_sources([dict(pe), dict(efl)]), [])

    def test_audience_gate_excludes_adult_only_sources(self) -> None:
        # Adult / post-secondary audience with no school-age signal is dropped,
        # even though "AI literacy" is named in the title.
        adult = {"title": "AI Literacy for the Workforce", "abstract": "Upskilling employees."}
        higher_ed = {"title": "AI literacy courses in higher education", "abstract": "For undergraduates."}
        self.assertTrue(is_adult_audience(adult))
        self.assertTrue(is_adult_audience(higher_ed))
        self.assertEqual(filter_relevant_sources([dict(adult), dict(higher_ed)]), [])

        # A paper naming both an adult and a school-age audience is kept.
        both = {"title": "AI literacy for secondary students preparing for university", "abstract": ""}
        self.assertFalse(is_adult_audience(both))

        # A school-age source is kept and survives the filter.
        school = {"title": "AI literacy in primary schools", "abstract": "for children"}
        self.assertFalse(is_adult_audience(school))
        self.assertEqual(len(filter_relevant_sources([dict(school)])), 1)

    def test_educator_lane_recovers_teacher_competence_evidence(self) -> None:
        # The educator lane keeps in-scope educator-competence evidence the
        # adult-audience gate would otherwise drop, and tags it audience="educator".
        pd = {
            "title": "Professional Development for In-Service Teachers in AI Literacy",
            "abstract": "Building in-service teachers' competence and readiness to teach AI literacy.",
        }
        teacher_ed = {
            "title": "Integrating AI literacy into teacher education: a critical perspective",
            "abstract": "",
        }
        # The PD paper names in-service teachers and no school-age audience, so the
        # adult-audience gate would drop it on the learner lane -- the educator
        # lane is what rescues it.
        self.assertTrue(is_adult_audience(pd), "premise: the learner gate would drop it")
        for source in (pd, teacher_ed):
            self.assertTrue(is_educator_audience(source))
            kept = filter_relevant_sources([dict(source)])
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0]["audience"], "educator")

    def test_educator_lane_guards_reject_out_of_scope(self) -> None:
        # Higher-education faculty (not a school educator) and pure teacher
        # productivity tool-use must NOT ride the educator lane.
        faculty = {
            "title": "Faculty Development for Generative AI Literacy in University Teaching",
            "abstract": "Preparing university lecturers and college faculty for undergraduate teaching.",
        }
        productivity = {
            "title": "An AI Grading Assistant to Reduce Secondary Teachers' Marking Workload",
            "abstract": "Teachers adopt a tool that automates marking and administrative communication.",
        }
        for source in (faculty, productivity):
            self.assertFalse(is_educator_audience(source))
            self.assertEqual(filter_relevant_sources([dict(source)]), [])

    def test_learner_source_is_tagged_learner(self) -> None:
        # A plain school-age future-skills source rides the learner lane: it is
        # kept (as before) and tagged audience="learner" (absence-equivalent).
        learner = {
            "title": "AI literacy and critical thinking for children in primary school",
            "abstract": "How students build competence with artificial intelligence.",
        }
        self.assertEqual(classify_audience(learner), "learner")
        kept = filter_relevant_sources([dict(learner)])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["audience"], "learner")

    def test_educator_lane_measured_on_labeled_set(self) -> None:
        # The dedicated educator-lane set is recovered cleanly: every labeled
        # positive is rescued and tagged educator, and no off-scope negative leaks
        # onto the lane. Mirrors the learner heuristic's measured floor.
        import eval_relevance

        examples = eval_relevance.load_educator_examples()
        # A meaningful floor needs a set that is not trivially memorizable: the
        # original 7-example set with a 0.99 assertion was effectively "all 7
        # correct" — memorization, not measurement.
        self.assertGreaterEqual(len(examples), 25, "educator-lane set too small to measure")
        lane = eval_relevance.educator_lane_report(examples, RELEVANCE_THRESHOLD)
        self.assertEqual(lane["leaked"], [], "off-scope example leaked onto the educator lane")
        # Measured 1.00/1.00 on the 26-example set; the floor sits below with
        # margin so future examples may dip without breaking the build (the
        # measured value lives in OPERATIONS.md, the floor guards regressions).
        self.assertGreaterEqual(lane["precision"], 0.85)
        self.assertGreaterEqual(lane["recall"], 0.85)

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

    def test_is_title_duplicate_matches_preprint_and_publication(self) -> None:
        # Same work, different DOI, lightly reworded title, publication a year
        # later than the preprint: the exact identity/title-year keys miss it,
        # the fuzzy title + year window catches it.
        preprint = {
            "title": "Deep Learning for AI Literacy in Primary Schools",
            "doi": "10.1000/preprint",
            "year": 2022,
        }
        publication = {
            "title": "Deep Learning for AI Literacy in Primary Schools: A Study",
            "doi": "10.1000/published",
            "year": 2023,
        }
        self.assertTrue(is_title_duplicate(preprint, publication))

    def test_is_title_duplicate_respects_year_window(self) -> None:
        # An identical title years apart is treated as a distinct work, not a
        # duplicate, so a re-issue outside the window is kept for review.
        first = {"title": "AI literacy for children", "year": 2015}
        much_later = {"title": "AI literacy for children", "year": 2024}
        self.assertFalse(is_title_duplicate(first, much_later))

    def test_is_title_duplicate_keeps_distinct_similar_titles(self) -> None:
        # Superficially similar but genuinely different works stay separate.
        computational = {"title": "Computational thinking in early education", "year": 2023}
        critical = {"title": "Critical thinking in early education", "year": 2023}
        self.assertLess(
            title_similarity(computational["title"], critical["title"]), 0.92
        )
        self.assertFalse(is_title_duplicate(computational, critical))

    def test_filter_new_sources_drops_fuzzy_title_duplicate(self) -> None:
        # A candidate whose title closely matches an already-stored source (within
        # the year window) is dropped even though its url/doi are new.
        first = load_records("sources")[0]
        candidates = [
            {
                "id": "src-fuzzy-dup",
                "title": f"{first['title']} (v2)",
                "url": "https://example.test/fuzzy-dup",
                "year": first.get("year", 2024),
            }
        ]
        self.assertEqual(filter_new_sources(candidates), [])

    def test_append_candidate_sources_drops_fuzzy_title_duplicate(self) -> None:
        week_one = [
            {
                "id": "src-preprint",
                "title": "Generative AI tutoring for secondary school students in mathematics",
                "url": "https://example.test/preprint",
                "year": 2023,
            }
        ]
        week_two = [
            # Same work, published version: different url, reworded title, +1 year.
            {
                "id": "src-published",
                "title": "Generative AI tutoring for secondary school students in mathematics revised",
                "url": "https://example.test/published",
                "year": 2024,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates-fuzzy.json"
            write_json(path, week_one)
            appended = append_candidate_sources(path, week_two)
            self.assertEqual(appended, [])
            self.assertEqual([r["id"] for r in load_json(path)], ["src-preprint"])

    def test_dedupe_queries_trims_blanks_and_duplicates(self) -> None:
        self.assertEqual(
            dedupe_queries(["  AI  literacy ", "AI literacy", "", "  ", "robotics"]),
            ["AI literacy", "robotics"],
        )

    def test_load_research_queries_env_override(self) -> None:
        import os

        import common

        # Newline- and comma-separated, with a blank and a duplicate to clean.
        with mock.patch.dict(
            os.environ, {"RESEARCH_QUERIES": "first query\nsecond query, first query\n"}
        ):
            self.assertEqual(
                common.load_research_queries(), ["first query", "second query"]
            )

    def test_load_research_queries_reads_config_file(self) -> None:
        import os

        import common

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "research_queries.json"
            write_json(path, ["alpha topic", "beta topic", "alpha topic"])
            with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(
                common, "RESEARCH_QUERIES_PATH", path
            ):
                os.environ.pop("RESEARCH_QUERIES", None)
                self.assertEqual(
                    common.load_research_queries(), ["alpha topic", "beta topic"]
                )

    def test_load_research_queries_falls_back_to_default(self) -> None:
        import os

        import common

        missing = Path(tempfile.gettempdir()) / "no_such_research_queries.json"
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(
            common, "RESEARCH_QUERIES_PATH", missing
        ):
            os.environ.pop("RESEARCH_QUERIES", None)
            self.assertEqual(common.load_research_queries(), DEFAULT_RESEARCH_QUERIES)

    def test_configured_research_queries_are_valid(self) -> None:
        # The versioned config file must be a non-empty list of non-blank strings,
        # so the weekly importers always have at least one usable query.
        import common

        payload = load_json(common.RESEARCH_QUERIES_PATH)
        self.assertIsInstance(payload, list)
        self.assertTrue(payload)
        self.assertTrue(all(isinstance(q, str) and q.strip() for q in payload))

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

    def test_dashboard_index_ships_without_bulk_fields(self) -> None:
        # The client downloads and parses the WHOLE index on every visit;
        # abstracts and assist blocks are never rendered and dominated the
        # payload. They must stay out of the shipped index — while everything
        # the dashboard actually reads stays in.
        from build_site import build_index

        index = build_index()
        for source in index["sources"]:
            self.assertNotIn("abstract", source)
            self.assertNotIn("assist", source)
            for needed in ("id", "title", "url", "publisher", "source_type"):
                self.assertIn(needed, source)
        for claim in index["claims"]:
            self.assertNotIn("assist", claim)
            for needed in ("id", "statement", "evidence_strength", "evidence_type", "text_anchor"):
                self.assertIn(needed, claim)
        # The canonical records keep every field — only the transport slims.
        self.assertTrue(any(src.get("abstract") for src in load_records("sources")))

    def test_run_importer_pipeline_end_to_end(self) -> None:
        # The five importers now share one main() (common.run_importer). Wire a
        # fake fetch/convert through it: an in-scope record must land in the
        # output file, an off-scope record must be filtered, fetch_kwargs and
        # configure_parser must reach fetch, and a second run must not
        # duplicate the record.
        import io
        from contextlib import redirect_stdout

        from common import run_importer

        nonce = "runimporter-e2e"
        raw_items = [
            {"kind": "keep"},
            {"kind": "drop"},
        ]
        seen_kwargs: list[dict] = []

        def fake_fetch(query, limit, flavor=None):
            seen_kwargs.append({"query": query, "limit": limit, "flavor": flavor})
            return raw_items

        def fake_convert(item):
            keep = item["kind"] == "keep"
            return {
                "id": f"src-{nonce}-{item['kind']}",
                "title": (
                    f"AI literacy for primary school pupils {nonce}"
                    if keep
                    else f"Quarterly refinery throughput report {nonce}"
                ),
                "authors": [],
                "year": 2024,
                "doi": None,
                "url": f"https://example.org/{nonce}/{item['kind']}",
                "openalex_id": None,
                "semantic_scholar_id": None,
                "eric_id": None,
                "publisher": "Test",
                "source_type": "peer_reviewed_article",
                "license": None,
                "abstract": "Pupils in primary school build AI literacy." if keep else "Refinery data.",
                "topics": ["education"],
                "status": "candidate",
                "created_at": "2026-01-01",
                "reviewed_at": None,
            }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "candidates-fake.json"
            argv = ["--query", "test query", "--limit", "7",
                    "--output", str(output), "--flavor", "vanilla"]
            for _ in range(2):  # second run must dedupe, not duplicate
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    code = run_importer(
                        "FakeSource",
                        fake_fetch,
                        fake_convert,
                        "unused-default.json",
                        configure_parser=lambda p: p.add_argument("--flavor", default=None),
                        fetch_kwargs=lambda args: {"flavor": args.flavor},
                        argv=argv,
                    )
                self.assertEqual(code, 0)
                self.assertIn("FakeSource", buffer.getvalue())
            written = load_json(output)
            self.assertEqual(len(written), 1, "keep-record once, drop-record never")
            self.assertIn(nonce, written[0]["title"])
            self.assertIn("primary school", written[0]["title"])
            self.assertEqual(
                seen_kwargs[0], {"query": "test query", "limit": 7, "flavor": "vanilla"}
            )

    def test_ingester_converts_survive_broken_api_payloads(self) -> None:
        # The importers' only outage guard is fetch_or_warn's except clause; an
        # AttributeError inside convert() (live APIs DO send explicit nulls for
        # nested fields) aborted the whole pipeline run. Every convert must
        # tolerate an empty record and null-riddled nested fields.
        import ingest_crossref
        import ingest_eric
        import ingest_openalex
        import ingest_semantic_scholar

        broken_by_module = {
            ingest_openalex: [
                {},
                {"authorships": [None, {"author": None}], "primary_location": None, "doi": None},
            ],
            ingest_semantic_scholar: [
                {},
                {"authors": [None, {"name": None}], "externalIds": None, "publicationTypes": None},
            ],
            ingest_crossref: [
                {},
                {"title": [], "author": [None, {"given": None, "family": None}], "issued": None},
            ],
            ingest_eric: [
                {},
                {"author": None, "description": None, "publicationdateyear": None},
            ],
        }
        for module, payloads in broken_by_module.items():
            for payload in payloads:
                record = module.convert(payload)
                self.assertTrue(record["title"], f"{module.__name__} lost the title fallback")
                self.assertIsInstance(record["authors"], list)
                year = record["year"]
                self.assertTrue(year is None or isinstance(year, int))

    def test_sentence_split_survives_abbreviations(self) -> None:
        # "e.g." must not end a sentence: before the abbreviation-safe split the
        # anchor's sentence number pointed at the wrong sentence.
        from extract_claims import split_sentences

        text = (
            "AI literacy is taught in schools (e.g. primary schools) across Europe. "
            "Results show significant gains in critical thinking among pupils."
        )
        sentences = split_sentences(text)
        self.assertEqual(len(sentences), 2)
        self.assertIn("(e.g. primary schools)", sentences[0])
        self.assertTrue(sentences[1].startswith("Results show"))
        # German abbreviations from the bilingual sources.
        german = (
            "Die Studie untersucht KI-Kompetenz in Schulen, z. B. in der Primarstufe. "
            "Die Ergebnisse zeigen deutliche Zuwächse bei Schülerinnen und Schülern."
        )
        self.assertEqual(len(split_sentences(german)), 2)
        # A genuine sentence end after a word merely ENDING in an abbreviation
        # ("develop." contains "p.") must still split.
        tricky = (
            "The programme helped every pupil develop. "
            "Results show gains in AI literacy across all classrooms observed."
        )
        self.assertEqual(len(split_sentences(tricky)), 2)

    def test_multiple_findings_yield_multiple_claims(self) -> None:
        # An abstract with several finding sentences yields several claims (the
        # skill score rewards breadth), each verbatim with its own anchor and a
        # distinct id; methodology sentences still never become claims.
        from extract_claims import MAX_CLAIMS_PER_SOURCE, claims_from_source

        source = {
            "id": "src-multi",
            "source_type": "peer_reviewed_article",
            "abstract": (
                "We conducted a survey with a sample of 300 pupils about AI literacy. "
                "Results show that AI literacy instruction improves critical thinking among pupils. "
                "Findings suggest that collaboration in the classroom enhances digital competence. "
                "The study finds that self-regulation training promotes lifelong learning in schools."
            ),
        }
        claims = claims_from_source(source)
        self.assertEqual(len(claims), MAX_CLAIMS_PER_SOURCE)
        statements = [claim["statement"] for claim in claims]
        self.assertEqual(len(set(statements)), len(statements))
        self.assertEqual(len({claim["id"] for claim in claims}), len(claims))
        for claim in claims:
            self.assertIn(claim["statement"], source["abstract"])
            self.assertIn(claim["statement"], claim["text_anchor"])
            self.assertNotIn("sample of", claim["statement"])
        # The single-best wrapper stays consistent with the ranked head.
        self.assertEqual(claim_from_source(source)["statement"], statements[0])

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

    def test_off_scope_title_is_decisive_abstract_is_exempted(self) -> None:
        # An off-scope term only in the ABSTRACT is tolerated when the future
        # skill is named in the title (a genuine topic anchor). The same term in
        # the TITLE is decisive: the paper is about that off-domain subject, so a
        # co-occurring skill word does not rescue it -- this is the fix for the
        # disaster/health false-positive class (a school audience plus a skill
        # word in the title of a hygiene/nutrition/disaster paper).
        incidental = {  # off-scope in abstract, no title topic -> off scope
            "title": "The Relationship between Student Health and Academic Performance",
            "abstract": "We examine the complexity of nutrition, fitness and obesity in pupils.",
        }
        abstract_anchored = {  # off-scope only in abstract, topic in title -> kept
            "title": "AI literacy for school pupils: teaching about data",
            "abstract": "An artificial intelligence literacy unit that also mentions nutrition.",
        }
        title_offscope = {  # off-scope in title, even with a skill word -> off scope
            "title": "Nutrition, hygiene and self-regulation among primary school pupils",
            "abstract": "A school health promotion program.",
        }
        clean = {
            "title": "Computational thinking in primary computing education",
            "abstract": "A systems thinking curriculum for school children.",
        }
        self.assertTrue(is_off_scope(incidental))
        self.assertFalse(is_off_scope(abstract_anchored))
        self.assertTrue(is_off_scope(title_offscope))
        self.assertFalse(is_off_scope(clean))
        kept = filter_relevant_sources(
            [dict(incidental), dict(abstract_anchored), dict(title_offscope), dict(clean)]
        )
        self.assertEqual(
            [source["title"] for source in kept],
            [abstract_anchored["title"], clean["title"]],
        )

    def test_relevance_heuristic_meets_measured_floor(self) -> None:
        # Guards the keyword classifier against regressions using the labeled
        # eval set, which includes the previously-residual hard false-positive
        # classes (teacher tool-use, disaster/health papers that carry a
        # school-age word plus a topic in the title). Those are now handled
        # (is_teacher_tooluse and the title-decisive off-scope rule), so at
        # threshold 0.3 the heuristic measures precision 1.00 / recall 1.00; the
        # floors sit below those with margin so added examples can dip a little.
        import eval_relevance

        examples = eval_relevance.load_examples()
        metrics = eval_relevance.evaluate(examples, RELEVANCE_THRESHOLD)
        self.assertGreaterEqual(metrics.precision, 0.90, "relevance precision regressed")
        self.assertGreaterEqual(metrics.recall, 0.95, "relevance recall regressed")

    def test_hard_false_positive_classes_are_dropped(self) -> None:
        # Regression guard for the two hard FP classes fixed under issue #63:
        # every labeled hard_case (all off-scope) must be dropped by the heuristic.
        import eval_relevance

        examples = eval_relevance.load_examples()
        hard = [e for e in examples if e.get("origin") == "hard_case"]
        self.assertTrue(hard, "no hard_case examples present to guard")
        for example in hard:
            self.assertFalse(example["relevant"], f"hard_case should be off-scope: {example['title']}")
            score, topics = score_relevance(example)
            self.assertFalse(
                heuristic_keep(example, score, topics),
                f"hard false positive kept: {example['title']}",
            )

    def test_german_sources_pass_the_bilingual_filter(self) -> None:
        # Regression guard for the German blind spot: the project is anchored to
        # Lehrplan 21, yet before the bilingual keyword layer a German EDK/KMK/
        # PH-style abstract scored 0.0 and was silently dropped. The labeled set
        # now carries German examples (notes tagged "[de]"); every one of them
        # must be classified correctly — positives kept (incl. the educator lane
        # and Sek-II vocational learners), negatives dropped (German higher-ed,
        # workplace, health, teacher tool-use).
        import eval_relevance

        examples = eval_relevance.load_examples()
        german = [e for e in examples if str(e.get("note", "")).startswith("[de]")]
        self.assertGreaterEqual(len(german), 20, "German eval examples missing")
        self.assertTrue(any(e["relevant"] for e in german))
        self.assertTrue(any(not e["relevant"] for e in german))
        for example in german:
            score, topics = score_relevance(example)
            kept = heuristic_keep(example, score, topics)
            self.assertEqual(
                kept,
                example["relevant"],
                f"German example misclassified: {example['title']}",
            )

    def test_french_italian_sources_pass_the_multilingual_filter(self) -> None:
        # The other two Swiss school languages: Plan d'études romand (FR) and
        # Piano di studio (IT) sources must classify exactly like the German
        # ones — positives kept (incl. educator lane), negatives dropped
        # (higher-ed étudiants/studenti universitari, economics, school PE).
        import eval_relevance

        examples = eval_relevance.load_examples()
        tagged = [
            e for e in examples
            if str(e.get("note", "")).startswith(("[fr]", "[it]"))
        ]
        self.assertGreaterEqual(len(tagged), 12, "French/Italian eval examples missing")
        self.assertTrue(any(e["relevant"] for e in tagged))
        self.assertTrue(any(not e["relevant"] for e in tagged))
        for example in tagged:
            score, topics = score_relevance(example)
            kept = heuristic_keep(example, score, topics)
            self.assertEqual(
                kept,
                example["relevant"],
                f"French/Italian example misclassified: {example['title']}",
            )

    def test_normalize_title_folds_german_diacritics(self) -> None:
        # Umlauts must map to their base letters (not vanish), and ß to ss, so
        # German keywords and titles normalize consistently on both sides.
        self.assertEqual(
            normalize_title("Förderung der KI-Kompetenz bei Schülerinnen"),
            "forderung der ki kompetenz bei schulerinnen",
        )
        self.assertEqual(normalize_title("Straße"), "strasse")
        # The gender star splits the token; the stem keyword still matches.
        self.assertEqual(normalize_title("Schüler*innen"), "schuler innen")

    def test_attach_claim_validates_targets(self) -> None:
        from argparse import Namespace

        from promote_candidate import attach_claim

        # Missing skill is rejected before any write.
        self.assertTrue(
            attach_claim(Namespace(id="skill-does-not-exist", claim="claim-x", contradicting=False))
        )
        # Existing skill but missing claim is rejected too.
        skill_id = load_records("skills")[0]["id"]
        errors = attach_claim(Namespace(id=skill_id, claim="claim-does-not-exist-xyz", contradicting=False))
        self.assertTrue(any("not found" in error for error in errors))

    def test_recall_probe_rejection_reason(self) -> None:
        from recall_probe import rejection_reason

        # In scope -> the filter keeps it (no rejection reason).
        self.assertIsNone(
            rejection_reason(
                {"title": "AI literacy for primary school children", "abstract": "pupils learn AI"}
            )
        )
        # No topic vocabulary match at all.
        self.assertEqual(
            rejection_reason({"title": "Quantum chromodynamics lattice", "abstract": "gauge fields"}),
            "no_topic",
        )
        # Topic only in the abstract, no audience -> below threshold.
        self.assertEqual(
            rejection_reason({"title": "A study of pedagogy", "abstract": "mentions critical thinking once"}),
            "below_threshold",
        )
        # Adult audience with a title topic but no school-age signal.
        self.assertEqual(
            rejection_reason({"title": "AI literacy for the workforce", "abstract": "employees upskilling"}),
            "adult_audience",
        )
        # Off-scope domain term with no title topic anchor.
        self.assertEqual(
            rejection_reason(
                {"title": "School wellbeing", "abstract": "collaboration and nutrition in pupils"}
            ),
            "off_scope",
        )

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

    def test_reopen_missing_record_reports_error(self) -> None:
        from argparse import Namespace

        from promote_candidate import reopen_record

        errors = reopen_record(Namespace(id="claim-does-not-exist-xyz"))
        self.assertTrue(errors)
        self.assertIn("not found", errors[0])

    def test_reopen_refuses_non_rejected_record(self) -> None:
        # Re-opening only applies to a rejected (or deprecated) record; a reviewed
        # source is left untouched with a clear message and no write.
        from argparse import Namespace

        from promote_candidate import reopen_record

        reviewed = next(s for s in load_records("sources") if s.get("status") == "reviewed")
        errors = reopen_record(Namespace(id=reviewed["id"]))
        self.assertTrue(errors)
        self.assertIn("nothing to re-open", errors[0])

    def test_remove_harvested_label_by_title(self) -> None:
        # Re-opening a source drops its stale harvested label, matched by
        # normalized title (case/punctuation-insensitive); a second call no-ops.
        import promote_candidate as pc

        with tempfile.TemporaryDirectory() as tmp:
            original = pc.HARVEST_PATH
            pc.HARVEST_PATH = Path(tmp) / "relevance_harvested.json"
            try:
                negative = pc._harvest_example(
                    {"id": "src-x", "title": "Preservice Teachers and AI", "abstract": "a"},
                    False,
                    "reject_source",
                )
                pc.record_relevance_labels([negative])
                self.assertEqual(len(load_json(pc.HARVEST_PATH)["examples"]), 1)
                self.assertEqual(pc.remove_harvested_label({"title": "preservice teachers and ai!"}), 1)
                self.assertEqual(load_json(pc.HARVEST_PATH)["examples"], [])
                self.assertEqual(pc.remove_harvested_label({"title": "preservice teachers and ai"}), 0)
            finally:
                pc.HARVEST_PATH = original

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

    def test_active_skills_carry_german_display_fields(self) -> None:
        # The dashboard's audience is German-speaking (Lehrplan-21 anchoring);
        # every ACTIVE skill ships a German display name and definition
        # (name_de/definition_de, EN stays the canonical reviewed text).
        # Candidates may stay English until promotion.
        for skill in load_records("skills"):
            if skill.get("status") != "active":
                continue
            self.assertTrue(
                str(skill.get("name_de", "")).strip(),
                f"active skill {skill['id']} lacks name_de",
            )
            self.assertTrue(
                str(skill.get("definition_de", "")).strip(),
                f"active skill {skill['id']} lacks definition_de",
            )

    def test_refilter_flags_stale_candidates_against_current_vocabulary(self) -> None:
        # The filter only runs at ingest time; refilter_candidates re-checks the
        # OPEN backlog after a vocabulary change. The MENA-immigrant case is the
        # documented stale candidate: ingested under an older vocabulary, dropped
        # by today's off-scope terms.
        import refilter_candidates as rc

        stale = {
            "id": "src-stale",
            "status": "candidate",
            "title": "Immigration Trauma and Resilience Among Immigrant College Students",
            "abstract": "Acculturative stress among immigrant students in higher education.",
        }
        fresh = {
            "id": "src-fresh",
            "status": "candidate",
            "title": "AI literacy in primary school classrooms",
            "abstract": "Pupils develop critical thinking about AI systems.",
        }
        reviewed = {
            "id": "src-reviewed",
            "status": "reviewed",
            "title": "Immigration Trauma and Posttraumatic Growth",
        }
        with mock.patch.object(rc, "load_records", return_value=[stale, fresh, reviewed]):
            worksheet = rc.build_worksheet()
        self.assertEqual(worksheet["open_candidate_sources"], 2, "reviewed must be ignored")
        flagged = worksheet["flagged"]
        self.assertEqual([row["source_id"] for row in flagged], ["src-stale"])
        self.assertEqual(flagged[0]["reason"], "off_scope")
        self.assertIn("reject-source src-stale", flagged[0]["command"])

    def test_refilter_drop_reason_mirrors_heuristic_keep(self) -> None:
        # Every source must agree between the live decision (heuristic_keep) and
        # the refilter's explanation: reason None <=> kept. Exercise one source
        # per rule branch, including the educator-lane rescue.
        import refilter_candidates as rc

        cases = [
            {"title": "Quarterly refinery throughput report", "abstract": ""},
            {"title": "AI literacy for the workforce", "abstract": "Employees upskill."},
            {
                "title": "Teacher professional development for AI literacy instruction",
                "abstract": "In-service teachers build competence to teach AI literacy.",
            },
            {
                "title": "Critical thinking in primary school",
                "abstract": "Pupils practice reasoning about misinformation.",
            },
        ]
        for source in cases:
            score, topics = score_relevance(source)
            kept = heuristic_keep(source, score, topics)
            reason = rc.drop_reason(source)
            self.assertEqual(
                reason is None,
                kept,
                f"drop_reason and heuristic_keep disagree for: {source['title']} ({reason})",
            )

    def test_candidate_without_year_is_kept_not_silently_dropped(self) -> None:
        # An otherwise-valid source whose API record has no publication year
        # used to arrive as year=0 and vanish in source_is_valid_candidate.
        # year=None is now a legal CANDIDATE state.
        base = {"title": "AI literacy in primary school", "url": "https://x.org/p"}
        self.assertTrue(source_is_valid_candidate({**base, "year": None}))
        self.assertTrue(source_is_valid_candidate({**base, "year": 2024}))
        # 0 (and anything outside 1900-2100) stays invalid — the old sentinel
        # must not sneak back in as a "real" year.
        self.assertFalse(source_is_valid_candidate({**base, "year": 0}))
        self.assertFalse(source_is_valid_candidate({**base, "year": 1500}))

    def test_promote_source_requires_a_year(self) -> None:
        # A reviewed source is part of the evidence path: promotion must refuse
        # a year-less candidate unless the reviewer supplies --year.
        from argparse import Namespace

        import promote_candidate as pc

        source = {
            "id": "src-no-year",
            "title": "AI literacy in primary school",
            "year": None,
            "source_type": "peer_reviewed_article",
            "publisher": "Test",
            "url": "https://x.org/p",
            "topics": ["ai literacy"],
            "status": "candidate",
            "created_at": "2026-01-01",
        }
        written: list = []
        with mock.patch.object(
            pc, "find_record", return_value=(Path("unused.json"), [source], source)
        ), mock.patch.object(pc, "write_json", lambda path, records: written.append(records)), \
                mock.patch.object(pc, "record_relevance_labels", lambda batch: len(batch)):
            errors = pc.promote_source(Namespace(id="src-no-year", year=None))
            self.assertTrue(any("no publication year" in e for e in errors))
            self.assertEqual(source["status"], "candidate", "must not review without a year")
            self.assertEqual(written, [])

            errors = pc.promote_source(Namespace(id="src-no-year", year=2023))
            self.assertEqual(errors, [])
            self.assertEqual(source["year"], 2023)
            self.assertEqual(source["status"], "reviewed")
            self.assertEqual(len(written), 1)

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
        # Lehrplan 21 is a learner curriculum, so only learner-audience active
        # skills must carry an LP21 mapping; educator-audience skills are anchored
        # to an educator framework (UNESCO AI Competency Framework for Teachers).
        active_skills = {
            skill["id"]
            for skill in all_skills
            if skill["status"] == "active" and skill.get("audience", "learner") == "learner"
        }
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

    def test_skill_audience_dimension(self) -> None:
        # The optional audience axis separates learner future-skills from the
        # educator competencies that enable them. Absence means learner.
        validator = Draft202012Validator(load_json(ROOT / "schemas" / "skill.schema.json"))
        base = next(s for s in load_records("skills") if s["status"] == "active")
        for value in ("learner", "educator"):
            self.assertEqual(list(validator.iter_errors({**base, "audience": value})), [])
        self.assertTrue(list(validator.iter_errors({**base, "audience": "teacher"})))
        # Every shipped skill is explicitly tagged with a valid audience.
        skills = load_records("skills")
        self.assertTrue(all("audience" in s for s in skills))
        self.assertTrue(all(s.get("audience", "learner") in {"learner", "educator"} for s in skills))

    def test_educator_skills_map_to_unesco_teacher_framework(self) -> None:
        # Parallel to the Lehrplan 21 invariant: every active educator-audience
        # skill must carry a UNESCO AI Competency Framework for Teachers mapping,
        # the educator-side anchor (educators are out of scope for LP21).
        all_skills = load_records("skills")
        skill_ids = {skill["id"] for skill in all_skills}
        active_educators = {
            skill["id"]
            for skill in all_skills
            if skill["status"] == "active" and skill.get("audience") == "educator"
        }
        mapped = {
            mapping["skill_id"]
            for mapping in load_records("frameworks")
            if mapping.get("framework_group") == "UNESCO AI Competency Framework for Teachers"
        }
        self.assertLessEqual(
            active_educators,
            mapped,
            f"active educator skills without a UNESCO-for-Teachers mapping: {sorted(active_educators - mapped)}",
        )
        for mapping in load_records("frameworks"):
            if mapping.get("framework_group") == "UNESCO AI Competency Framework for Teachers":
                self.assertIn(mapping["skill_id"], skill_ids)
                self.assertTrue(mapping["competency"])
                self.assertTrue(mapping["rationale"])

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

    def test_embedding_mode_falls_back_to_heuristic_when_artifact_missing(self) -> None:
        # Opting into the embedding anchors but with no artifact must not break
        # the pipeline: it degrades to the exact heuristic decision, not raise.
        import os

        import common

        relevant = {
            "title": "AI literacy and collaboration in K-12 education",
            "abstract": "A study of school learners.",
        }
        heuristic = decide_relevance(relevant)  # env unset here
        with mock.patch.dict(
            os.environ, {"RELEVANCE_CLASSIFIER": "embedding", "EMBEDDING_PROVIDER": "local"}
        ), mock.patch.object(
            common, "RELEVANCE_ANCHORS_PATH", Path(tempfile.gettempdir()) / "no_such_anchors.json"
        ), mock.patch.object(common, "_embedding_fallback_warned", False):
            self.assertEqual(relevance_classifier_mode(), "embedding")
            self.assertIsNone(load_relevance_anchors())
            self.assertEqual(decide_relevance(relevant), heuristic)

    def test_embedding_mode_falls_back_when_no_embedding_provider(self) -> None:
        # The artifact is present but no EMBEDDING_PROVIDER is configured (embed
        # returns None): the decision must match the heuristic exactly.
        import os

        import common

        relevant = {
            "title": "Data literacy and critical thinking for school students",
            "abstract": "A classroom study with pupils.",
        }
        heuristic = decide_relevance(relevant)  # env unset here
        self.assertIsNotNone(load_relevance_anchors(), "committed anchors should load")
        with mock.patch.dict(os.environ, {"RELEVANCE_CLASSIFIER": "embedding"}), mock.patch.object(
            common, "_embedding_fallback_warned", False
        ):
            os.environ.pop("EMBEDDING_PROVIDER", None)
            self.assertEqual(decide_relevance(relevant), heuristic)

    def test_embedding_mode_is_deterministic_from_fixtures(self) -> None:
        # With the committed (st) anchors active and the fixture-backed semantic
        # embedding, the decision is reproducible and offline (the source text has
        # a committed embedding fixture); topics stay the explainable keyword
        # signal and the stored relevance_score stays schema-valid in [0, 1].
        import os

        source = {
            "title": "AI literacy and critical thinking in classrooms",
            "abstract": "A study with students.",
        }
        _, keyword_topics = score_relevance(source)
        with mock.patch.dict(
            os.environ, {"RELEVANCE_CLASSIFIER": "embedding", "EMBEDDING_PROVIDER": "st"}
        ):
            first = decide_relevance(source)
            second = decide_relevance(source)
        self.assertEqual(first, second)  # deterministic, network-free
        keep, score, topics = first
        self.assertIsInstance(keep, bool)
        self.assertEqual(topics, keyword_topics)
        self.assertTrue(0.0 <= score <= 1.0)

    def test_embedding_anchors_artifact_is_versioned_and_reproducible(self) -> None:
        # The committed anchors must carry the provenance needed to reproduce them,
        # including the embedding model name and version (P3: real semantic st).
        artifact = load_relevance_anchors()
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact["model_type"], "embedding-anchors")
        self.assertIn("positive", artifact["anchors"])
        self.assertIn("negative", artifact["anchors"])
        self.assertEqual(len(artifact["anchors"]["positive"]), artifact["embedding_dim"])
        self.assertEqual(len(artifact["anchors"]["negative"]), artifact["embedding_dim"])
        provenance = artifact["provenance"]
        self.assertIn("embedding_provider", provenance)
        self.assertTrue(provenance["model_name"])
        self.assertTrue(provenance["model_version"])
        self.assertIn("built_at", provenance)
        self.assertIn("input_hashes", provenance)
        self.assertEqual(
            provenance["n_examples"], provenance["n_relevant"] + provenance["n_irrelevant"]
        )

    def test_embedding_anchors_rebuild_is_reproducible(self) -> None:
        # Rebuilding the anchors from the same labeled set reproduces the committed
        # artifact's anchors. The committed artifact uses the semantic st provider,
        # served offline from the embedding fixtures (every labeled text has a
        # committed vector), so the rebuild is network-free. The comparison is
        # tolerance-based, not bit-exact: the centroid sums are floating point, so
        # they reproduce to well within any decision-relevant precision but can
        # differ at the ULP level across Python builds.
        import os

        import build_relevance_anchors as bra

        examples = load_json(bra.EVAL_PATH)["examples"]
        positives, negatives = bra.split_texts(examples)
        with mock.patch.dict(os.environ, {"EMBEDDING_PROVIDER": "st"}):
            rebuilt = bra.build_artifact(positives, negatives, "st", bra.DEFAULT_DECISION_THRESHOLD)
        committed = load_relevance_anchors()
        for sign in ("positive", "negative"):
            rebuilt_vec = rebuilt["anchors"][sign]
            committed_vec = committed["anchors"][sign]
            self.assertEqual(len(rebuilt_vec), len(committed_vec))
            for got, expected in zip(rebuilt_vec, committed_vec):
                self.assertAlmostEqual(got, expected, places=9)


class EmbeddingClusteringTests(unittest.TestCase):
    # Three candidate claims: alpha/beta embed near each other (they cluster),
    # gamma is orthogonal (it stays a singleton and is dropped). The reviewed
    # claim is ignored. Vectors are a fixture so the test never touches a real
    # embedding provider or the network.
    CLAIMS = [
        {"id": "claim-a", "status": "candidate", "statement": "alpha statement"},
        {"id": "claim-b", "status": "candidate", "statement": "beta statement"},
        {"id": "claim-c", "status": "candidate", "statement": "gamma statement"},
        {"id": "claim-d", "status": "reviewed", "statement": "delta reviewed"},
    ]
    VECTORS = {
        "alpha statement": [1.0, 0.0, 0.0, 0.0],
        "beta statement": [0.9, 0.2, 0.0, 0.0],
        "gamma statement": [0.0, 0.0, 1.0, 0.0],
    }

    def _embedder(self, extra=None):
        mapping = dict(self.VECTORS)
        if extra:
            mapping.update(extra)
        return lambda texts: [mapping.get(text, [0.0, 0.0, 0.0, 0.0]) for text in texts]

    def test_vocabulary_is_the_default_method(self) -> None:
        import os

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLUSTER_METHOD", None)
            self.assertEqual(cluster_method(), "vocabulary")

    def test_embedding_clustering_is_deterministic_and_schema_valid(self) -> None:
        embedder = self._embedder()
        first = cluster_candidate_skills_embedding(
            self.CLAIMS, [], min_claims=2, embedder=embedder, provider="local"
        )
        second = cluster_candidate_skills_embedding(
            self.CLAIMS, [], min_claims=2, embedder=embedder, provider="local"
        )
        self.assertEqual(first, second)  # reproducible for the same input
        proposals, hints = first
        self.assertEqual(hints, [])
        self.assertEqual(len(proposals), 1)  # gamma singleton is dropped at min_claims=2
        proposal = proposals[0]
        self.assertEqual(proposal["supporting_claim_ids"], ["claim-a", "claim-b"])
        self.assertEqual(proposal["status"], "candidate")
        self.assertEqual(proposal["evidence_score"], 0.0)
        # Provenance is recorded in the change_log (the schema admits no extra field).
        self.assertIn("embedding", proposal["change_log"][0]["change"])
        # Output satisfies skill.schema.json and the definition keeps the review gate.
        schema = load_json(ROOT / "schemas" / "skill.schema.json")
        Draft202012Validator(schema).validate(proposal)
        self.assertTrue(proposal["definition"].endswith("Definition requires human review."))

    def test_embedding_clustering_is_order_independent(self) -> None:
        embedder = self._embedder()
        forward, _ = cluster_candidate_skills_embedding(
            self.CLAIMS, [], min_claims=2, embedder=embedder, provider="local"
        )
        reversed_claims = list(reversed(self.CLAIMS))
        backward, _ = cluster_candidate_skills_embedding(
            reversed_claims, [], min_claims=2, embedder=embedder, provider="local"
        )
        self.assertEqual(forward, backward)

    def test_existing_skill_is_only_a_hint_not_a_suppressor(self) -> None:
        existing = {
            "id": "skill-creativity",
            "name": "Creativity",
            "definition": "Creative thinking skills here.",
        }
        skill_text = "Creativity Creative thinking skills here."
        embedder = self._embedder({skill_text: [0.95, 0.1, 0.0, 0.0]})
        proposals, hints = cluster_candidate_skills_embedding(
            self.CLAIMS, [existing], min_claims=2, embedder=embedder, provider="local"
        )
        # The proposal is still made: existing skills never suppress, only hint.
        self.assertEqual(len(proposals), 1)
        self.assertEqual(
            hints, [("claim-a", "skill-creativity", ["claim-a", "claim-b"])]
        )

    def test_embedding_returns_none_without_a_provider(self) -> None:
        # No embedding provider: the embedder yields nothing, the function signals
        # None, and the dispatcher falls back to the vocabulary method.
        none_embedder = lambda texts: None
        self.assertIsNone(
            cluster_candidate_skills_embedding(
                self.CLAIMS, [], min_claims=2, embedder=none_embedder, provider="none"
            )
        )

    def test_dispatcher_falls_back_to_vocabulary_when_embedding_unavailable(self) -> None:
        import os

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
        ]
        vocab = cluster_candidate_skills(claims, [], min_claims=2)
        with mock.patch.dict(
            os.environ, {"CLUSTER_METHOD": "embedding"}, clear=False
        ):
            os.environ.pop("EMBEDDING_PROVIDER", None)
            dispatched = cluster_skills(claims, [], min_claims=2)
        self.assertEqual(dispatched, vocab)

    def test_threshold_constant_is_a_fixed_cosine(self) -> None:
        self.assertTrue(0.0 < EMBEDDING_CLUSTER_THRESHOLD <= 1.0)


class OptionalAiFoundationTests(unittest.TestCase):
    def test_provider_none_is_default_and_inert(self) -> None:
        # AI_PROVIDER=none (the default) must behave exactly as before: no AI,
        # no network, no SDK import — complete/embed simply return None.
        import os
        from unittest import mock

        import ai_provider

        with mock.patch.dict(os.environ, {}, clear=False):
            for var in ("AI_PROVIDER", "AI_MODEL", "EMBEDDING_PROVIDER"):
                os.environ.pop(var, None)
            self.assertEqual(ai_provider.ai_provider(), "none")
            self.assertEqual(ai_provider.ai_model(), "claude-opus-4-8")
            self.assertEqual(ai_provider.embedding_provider(), "none")
            self.assertIsNone(ai_provider.complete("hello", schema={"type": "object"}))
            self.assertIsNone(ai_provider.embed(["hello", "world"]))

    def test_provenance_has_model_prompt_version_and_created_at(self) -> None:
        import ai_provider

        provenance = ai_provider.ai_provenance("claim-assist-v1")
        self.assertEqual(set(provenance), {"model", "prompt_version", "created_at"})
        self.assertEqual(provenance["prompt_version"], "claim-assist-v1")
        self.assertTrue(provenance["model"])
        self.assertTrue(provenance["created_at"])

    def test_cache_provider_is_deterministic_and_miss_is_detectable(self) -> None:
        # The cache provider replays committed fixtures deterministically; a miss
        # returns None so that in CI (cache mode) it surfaces as a failure rather
        # than a silent network fall-through.
        import os
        from unittest import mock

        import ai_provider

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            ai_provider, "CACHE_DIR", Path(tmp)
        ), mock.patch.dict(os.environ, {"AI_PROVIDER": "cache", "AI_MODEL": "claude-opus-4-8"}):
            prompt = "Summarize this claim."
            schema = {"type": "object"}
            payload = {
                "kind": "complete",
                "model": "claude-opus-4-8",
                "prompt": prompt,
                "schema": schema,
            }
            stored = {"suggestions": [{"field": "context", "value": "K-12 classroom"}]}
            ai_provider.cache_write(payload, stored)

            first = ai_provider.complete(prompt, schema=schema)
            second = ai_provider.complete(prompt, schema=schema)
            self.assertEqual(first, stored)
            self.assertEqual(first, second)  # deterministic replay

            # A miss has no offline answer -> None (a failure in CI cache mode).
            self.assertIsNone(ai_provider.complete("an uncached prompt", schema=schema))

    def test_local_embedding_is_deterministic_and_normalized(self) -> None:
        import os
        from unittest import mock

        import ai_provider

        with mock.patch.dict(os.environ, {"EMBEDDING_PROVIDER": "local"}):
            vectors = ai_provider.embed(["AI literacy", "AI literacy"])
            self.assertIsNotNone(vectors)
            self.assertEqual(len(vectors), 2)
            self.assertEqual(vectors[0], vectors[1])  # deterministic, network-free
            self.assertEqual(len(vectors[0]), ai_provider.EMBED_DIM)
            self.assertAlmostEqual(math.sqrt(sum(v * v for v in vectors[0])), 1.0, places=6)

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EMBEDDING_PROVIDER", None)
            self.assertIsNone(ai_provider.embed(["x"]))

    def test_st_embedding_is_fixture_backed_and_offline(self) -> None:
        # EMBEDDING_PROVIDER=st replays a committed sentence-transformers vector
        # from tests/fixtures/embeddings/ without importing the heavy package or
        # touching the network: the fixture is a cache hit, so a sentinel that
        # would explode on import is never reached. A miss with no package (and no
        # fixture) returns None so callers fall back to the heuristic.
        import os
        from unittest import mock

        import ai_provider

        cached_text = "AI literacy for school children fixture probe"
        self.assertIsNotNone(
            ai_provider.embed_cache_read(ai_provider.ST_DEFAULT_MODEL, cached_text),
            "expected a committed st fixture for the probe text",
        )

        def explode(_model: str):  # the model must never load on a cache hit
            raise AssertionError("st model loaded despite a fixture cache hit")

        with mock.patch.dict(os.environ, {"EMBEDDING_PROVIDER": "st"}), mock.patch.object(
            ai_provider, "_load_st_model", explode
        ):
            vectors = ai_provider.embed([cached_text, cached_text])
        self.assertIsNotNone(vectors)
        self.assertEqual(vectors[0], vectors[1])  # deterministic replay
        self.assertEqual(len(vectors[0]), 384)  # all-MiniLM-L6-v2 dimensionality
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in vectors[0])), 1.0, places=5)

        # A genuine miss with no usable provider degrades to None, not a crash.
        with mock.patch.dict(os.environ, {"EMBEDDING_PROVIDER": "st"}), mock.patch.object(
            ai_provider, "_load_st_model", lambda model: (_ for _ in ()).throw(ImportError("no st"))
        ):
            self.assertIsNone(ai_provider.embed(["a text with no committed fixture at all"]))

    def test_schema_accepts_records_with_and_without_assist(self) -> None:
        import ai_provider

        claim_validator = Draft202012Validator(load_json(ROOT / "schemas" / "claim.schema.json"))
        source_validator = Draft202012Validator(load_json(ROOT / "schemas" / "source.schema.json"))

        base_claim = {
            "id": "claim-assist-example",
            "statement": "A sample claim statement long enough to validate.",
            "source_ids": ["src-x"],
            "text_anchor": 'sentence 1: "..."',
            "context": "K-12 classroom",
            "age_range": "6-12",
            "outcome": "Learners critique AI outputs",
            "evidence_type": "empirical_study",
            "evidence_strength": "low",
            "supports_skill_ids": ["skill-x"],
            "status": "candidate",
            "created_at": "2026-06-20",
        }
        base_source = {
            "id": "src-assist-example",
            "title": "A sample source title",
            "year": 2026,
            "source_type": "peer_reviewed_article",
            "publisher": "Example Publisher",
            "url": "https://example.test/x",
            "topics": ["ai literacy"],
            "status": "candidate",
            "created_at": "2026-06-20",
        }

        assist = {
            "suggestions": [{"field": "outcome", "value": "Learners critique AI outputs"}],
            "provenance": ai_provider.ai_provenance("assist-v1"),
        }

        # Without "assist" (the existing, unchanged shape) and with it both validate.
        claim_validator.validate(base_claim)
        claim_validator.validate({**base_claim, "assist": assist})
        source_validator.validate(base_source)
        source_validator.validate({**base_source, "assist": assist})

        # "assist" is never required: removing it leaves a valid record.
        self.assertNotIn("assist", base_claim)
        self.assertNotIn("assist", base_source)


class ClaimPrefillAssistTests(unittest.TestCase):
    """P1: the LLM claim pre-fill only ever proposes -- never decides."""

    SOURCE = {
        "id": "src-prefill-test",
        "source_type": "systematic_review",
        "status": "candidate",
        "abstract": (
            "Background remarks describing the structure of this paper come first. "
            "We find that AI literacy instruction improves critical thinking among "
            "primary school students. Short note."
        ),
    }

    EXPECTED_STATEMENT = (
        "We find that AI literacy instruction improves critical thinking among "
        "primary school students."
    )

    def _write_suggestion_fixture(self, cache_dir: Path, suggestion: dict) -> None:
        """Record a model suggestion for SOURCE's extracted sentence into the cache."""
        import ai_provider

        picked = best_claim_sentence(self.SOURCE["abstract"])
        assert picked is not None
        _, sentence, topics = picked
        prompt = prefill_prompt(self.SOURCE["abstract"], sentence, topics)
        payload = {
            "kind": "complete",
            "model": ai_provider.ai_model(),
            "prompt": prompt,
            "schema": PREFILL_OUTPUT_SCHEMA,
        }
        with mock.patch.object(ai_provider, "CACHE_DIR", cache_dir):
            ai_provider.cache_write(payload, suggestion)

    def test_provider_none_adds_no_assist(self) -> None:
        # With AI off (the default), claim_from_source must behave exactly as
        # before: no "assist" key, suggestion path inert.
        import os

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_PROVIDER", None)
            self.assertIsNone(suggest_claim_fields("abstract", "statement", ["ai literacy"]))
            claim = claim_from_source(self.SOURCE)
        self.assertIsNotNone(claim)
        self.assertNotIn("assist", claim)
        self.assertEqual(claim["age_range"], AGE_RANGE_PLACEHOLDER)
        self.assertEqual(claim["outcome"], OUTCOME_PLACEHOLDER)

    def test_suggestion_lands_only_under_assist(self) -> None:
        # With a cached suggestion, claim_from_source attaches it under "assist"
        # while statement/text_anchor stay verbatim and the REAL fields keep
        # their placeholders -- the suggestion never touches them.
        import os

        import ai_provider

        suggestion = {
            "age_range": "6-12",
            "outcome": "AI literacy instruction improves critical thinking.",
            "context": "Systematic review in primary school classrooms.",
            "evidence_strength": "moderate",
        }
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            self._write_suggestion_fixture(cache_dir, suggestion)
            with mock.patch.object(ai_provider, "CACHE_DIR", cache_dir), mock.patch.dict(
                os.environ, {"AI_PROVIDER": "cache", "AI_MODEL": "claude-opus-4-8"}
            ):
                claim = claim_from_source(self.SOURCE)

        # statement / text_anchor remain the deterministic verbatim evidence.
        self.assertEqual(claim["statement"], self.EXPECTED_STATEMENT)
        self.assertIn('sentence 2: "We find that AI literacy', claim["text_anchor"])
        # The real review fields are untouched placeholders.
        self.assertEqual(claim["age_range"], AGE_RANGE_PLACEHOLDER)
        self.assertEqual(claim["outcome"], OUTCOME_PLACEHOLDER)
        self.assertTrue(claim["context"].endswith(CONTEXT_PLACEHOLDER_SUFFIX))
        # The suggestion lives ONLY under assist, with provenance.
        self.assertEqual(claim["assist"]["suggestions"], [suggestion])
        self.assertEqual(
            claim["assist"]["provenance"]["prompt_version"], PREFILL_PROMPT_VERSION
        )
        # And the record still validates against the schema.
        schema = load_json(ROOT / "schemas" / "claim.schema.json")
        Draft202012Validator(schema).validate(claim)

    def test_promotion_gate_stays_sharp_with_suggestions(self) -> None:
        # A suggestion sitting under assist must NOT satisfy the review gate; only
        # explicit adoption (--accept-suggestions / reviewer args) fills the real
        # fields, and even then a skill link is still required.
        suggestion = {
            "age_range": "6-12",
            "outcome": "AI literacy instruction improves critical thinking.",
            "context": "Systematic review in primary school classrooms.",
            "evidence_strength": "high",
        }
        claim = {
            "id": "claim-prefill-gate",
            "context": f"Auto-extracted candidate. {CONTEXT_PLACEHOLDER_SUFFIX}",
            "age_range": AGE_RANGE_PLACEHOLDER,
            "outcome": OUTCOME_PLACEHOLDER,
            "evidence_strength": "low",
            "supports_skill_ids": [],
            "contradicts_skill_ids": [],
            "source_ids": ["src-x"],
            "assist": {
                "suggestions": [suggestion],
                "provenance": {"prompt_version": PREFILL_PROMPT_VERSION},
            },
        }
        skill_ids, source_ids = {"skill-x"}, {"src-x"}

        # Gate is sharp: placeholders remain -> errors, despite the suggestion.
        errors = claim_review_errors(claim, skill_ids, source_ids)
        self.assertTrue(any("context" in e for e in errors))
        self.assertTrue(any("age_range" in e for e in errors))
        self.assertTrue(any("outcome" in e for e in errors))
        # Helpers expose the suggestion for display without changing the record.
        self.assertEqual(claim_suggestions(claim), suggestion)
        self.assertTrue(format_claim_suggestions(claim))
        self.assertEqual(claim["age_range"], AGE_RANGE_PLACEHOLDER)  # unchanged

        # Adopt the suggestions as starting values (the --accept-suggestions path).
        adopted = apply_claim_suggestions(claim)
        self.assertEqual(set(adopted), {"age_range", "outcome", "context", "evidence_strength"})
        self.assertEqual(claim["age_range"], "6-12")
        self.assertEqual(claim["evidence_strength"], "strong")  # high -> strong mapping

        # Adoption alone is not enough: a reviewed claim still needs a skill link.
        errors = claim_review_errors(claim, skill_ids, source_ids)
        self.assertEqual(errors, ["a reviewed claim must link at least one skill; pass --supports or --contradicts"])

        # With the reviewer-supplied skill link the gate finally clears.
        claim["supports_skill_ids"] = ["skill-x"]
        self.assertEqual(claim_review_errors(claim, skill_ids, source_ids), [])


class ReportTruncationTests(unittest.TestCase):
    """The LLM prompt is cost-capped: a submitter-controlled 25 MB PDF must not
    reach the paid API in full. Only the prompt is cut — the verbatim guard
    keeps checking statements against the complete text."""

    def test_text_at_or_under_limit_is_unchanged(self) -> None:
        text = "One finding. Another finding."
        self.assertEqual(truncate_report_text(text, limit=100), text)
        self.assertEqual(truncate_report_text(text, limit=len(text)), text)

    def test_over_limit_cuts_on_a_sentence_boundary(self) -> None:
        text = "First sentence stands alone. Second sentence follows here. Tail"
        capped = truncate_report_text(text, limit=40)
        self.assertEqual(capped, "First sentence stands alone.")
        # Never a half sentence the model could quote from mid-air.
        self.assertTrue(capped.endswith("."))

    def test_over_limit_without_boundary_hard_cuts(self) -> None:
        text = "x" * 500
        self.assertEqual(truncate_report_text(text, limit=100), "x" * 100)

    def test_prompt_is_capped_but_guard_sees_full_text(self) -> None:
        # A finding sentence placed BEYOND the cap: the prompt must not contain
        # it, yet the verbatim guard (which gets the full text) still accepts it.
        beyond = (
            "Learners in primary school gain measurable digital competence "
            "from sustained classroom practice."
        )
        text = ("Filler sentence for padding. " * 50) + beyond
        with mock.patch.object(ingest_reports, "MAX_REPORT_CHARS", 200):
            capped = truncate_report_text(text, limit=200)
            self.assertNotIn(beyond, capped)
            captured: dict[str, str] = {}

            def fake_complete(prompt: str, *, schema: object = None) -> None:
                captured["prompt"] = prompt
                return None

            with mock.patch.object(
                ingest_reports.ai_provider, "ai_provider", return_value="anthropic"
            ), mock.patch.object(
                ingest_reports.ai_provider, "complete", side_effect=fake_complete
            ):
                propose_report(text, "https://example.org/report.pdf")
            self.assertNotIn(beyond, captured["prompt"])
        # The guard verifies against the FULL text, so the passage stays valid.
        self.assertEqual(verbatim_passage(beyond, text), beyond)


class ReportImportTests(unittest.TestCase):
    """P2: the LLM report importer proposes candidates but never decides, and
    every claim statement must be a verbatim quote from the report text."""

    REPORT = (ROOT / "tests" / "fixtures" / "reports" / "sample-report.txt").read_text(
        encoding="utf-8"
    )
    URL = "https://www.oecd.org/education/2030-project/report.pdf"

    # A verbatim finding, given to the importer WITH the report's original line
    # wraps to prove matching is whitespace-agnostic.
    VERBATIM_WRAPPED = (
        "Schools that embed AI literacy across the curriculum report stronger\n"
        "critical thinking among primary school students than schools that teach\n"
        "it as a stand-alone unit."
    )
    VERBATIM_COLLAPSED = (
        "Schools that embed AI literacy across the curriculum report stronger "
        "critical thinking among primary school students than schools that teach "
        "it as a stand-alone unit."
    )
    FABRICATED = "AI literacy doubles student test scores within one academic year."

    def _proposal(self) -> dict:
        return {
            "title": "OECD Future of Education and Skills 2030: AI Literacy in Schools",
            "year": 2023,
            "source_type": "policy_report",
            "authors": ["OECD"],
            "summary": (
                "The report examines how compulsory education prepares learners aged "
                "6 to 18 for artificial intelligence across member states."
            ),
            "findings": [
                {
                    "statement": self.VERBATIM_WRAPPED,
                    "outcome": "Embedding AI literacy is linked to stronger critical thinking.",
                    "context": "OECD country survey across member states.",
                    "age_range": "6-12",
                    "evidence_strength": "moderate",
                },
                {
                    "statement": self.FABRICATED,
                    "outcome": None,
                    "context": None,
                    "age_range": None,
                    "evidence_strength": None,
                },
            ],
        }

    def test_verbatim_guard_keeps_quotes_and_drops_inventions(self) -> None:
        # A real quote survives (whitespace-collapsed), an invented one and a
        # too-short fragment are rejected.
        self.assertEqual(
            verbatim_passage(self.VERBATIM_WRAPPED, self.REPORT), self.VERBATIM_COLLAPSED
        )
        self.assertIsNone(verbatim_passage(self.FABRICATED, self.REPORT))
        self.assertIsNone(verbatim_passage("AI", self.REPORT))
        # A paraphrase that is not literally present is rejected.
        self.assertIsNone(
            verbatim_passage(
                "Schools embedding AI literacy see much better critical thinking.",
                self.REPORT,
            )
        )
        self.assertGreater(MIN_PASSAGE_LENGTH, len("AI"))

    def test_provider_none_is_a_no_op(self) -> None:
        # With AI off (the default) nothing is proposed and no candidates are built.
        import os

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_PROVIDER", None)
            self.assertIsNone(propose_report(self.REPORT, self.URL))
        self.assertEqual(report_candidates(None, self.REPORT, self.URL, "OECD", None), ([], []))

    def test_proposal_yields_schema_valid_candidates(self) -> None:
        # A proposal becomes exactly one candidate source and one candidate claim
        # (the fabricated finding is dropped); both validate against the schemas.
        sources, claims = report_candidates(
            self._proposal(), self.REPORT, self.URL, "OECD", 2023
        )
        self.assertEqual(len(sources), 1)
        relevant = filter_relevant_sources(sources)
        self.assertEqual(len(relevant), 1, "the report source should be in scope")
        source = relevant[0]
        self.assertEqual(source["status"], "candidate")
        self.assertEqual(source["source_type"], "policy_report")
        self.assertEqual(source["url"], self.URL)
        self.assertEqual(source["reviewed_at"], None)
        Draft202012Validator(load_json(ROOT / "schemas" / "source.schema.json")).validate(source)

        # Only the verbatim finding becomes a claim; the invention is discarded.
        self.assertEqual(len(claims), 1)
        claim = claims[0]
        self.assertEqual(claim["statement"], self.VERBATIM_COLLAPSED)
        self.assertIn(self.VERBATIM_COLLAPSED, claim["text_anchor"])
        self.assertEqual(claim["source_ids"], [source["id"]])
        self.assertEqual(claim["status"], "candidate")
        self.assertEqual(claim["evidence_strength"], "low")
        self.assertEqual(claim["evidence_type"], "policy_synthesis")
        self.assertEqual(claim["reviewed_at"], None)
        Draft202012Validator(load_json(ROOT / "schemas" / "claim.schema.json")).validate(claim)

        # The model's richer guesses live ONLY under the non-binding assist block;
        # the real review fields keep their placeholders.
        self.assertEqual(claim["age_range"], AGE_RANGE_PLACEHOLDER)
        self.assertEqual(claim["outcome"], OUTCOME_PLACEHOLDER)
        self.assertTrue(claim["context"].endswith(CONTEXT_PLACEHOLDER_SUFFIX))
        self.assertEqual(claim["assist"]["suggestions"][0]["age_range"], "6-12")
        self.assertEqual(
            claim["assist"]["provenance"]["prompt_version"], REPORT_PROMPT_VERSION
        )

    def test_irrelevant_report_yields_no_claims(self) -> None:
        # An out-of-scope report is dropped by the relevance filter; even a
        # verbatim finding produces no candidate because its source is gone.
        proposal = {
            "title": "Soil nutrition in wastewater refinery effluent",
            "year": 2022,
            "source_type": "policy_report",
            "authors": ["ACME"],
            "summary": "An agriculture and salary study of refinery soil.",
            "findings": [],
        }
        sources, _ = report_candidates(proposal, self.REPORT, self.URL, "ACME", 2022)
        self.assertEqual(filter_relevant_sources(sources), [])

    def test_unusable_proposal_builds_no_source(self) -> None:
        # No title, or no schema-valid year, is something the importer refuses to
        # invent, so it builds no source at all.
        self.assertIsNone(build_source({"title": "", "year": 2023}, self.URL, "OECD", None))
        self.assertIsNone(
            build_source({"title": "A report", "year": None}, self.URL, "OECD", None)
        )
        self.assertIsNotNone(
            build_source({"title": "A report", "year": None}, self.URL, "OECD", 2023)
        )

    def test_cache_mode_replays_proposal_deterministically(self) -> None:
        # The provider integration: a committed fixture is replayed under
        # AI_PROVIDER=cache, with the same request hash the importer computes.
        import os

        import ai_provider

        proposal = self._proposal()
        prompt = report_prompt(self.REPORT, self.URL)
        payload = {
            "kind": "complete",
            "model": "claude-opus-4-8",
            "prompt": prompt,
            "schema": REPORT_OUTPUT_SCHEMA,
        }
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            with mock.patch.object(ai_provider, "CACHE_DIR", cache_dir):
                ai_provider.cache_write(payload, proposal)
                with mock.patch.dict(
                    os.environ, {"AI_PROVIDER": "cache", "AI_MODEL": "claude-opus-4-8"}
                ):
                    replayed = propose_report(self.REPORT, self.URL)
        self.assertEqual(replayed, proposal)
        _, claims = report_candidates(replayed, self.REPORT, self.URL, "OECD", 2023)
        self.assertEqual([claim["statement"] for claim in claims], [self.VERBATIM_COLLAPSED])

    def test_verbatim_match_tolerates_pdf_typography(self) -> None:
        # PDF artifacts (curly quotes, dashes, ligatures, hyphenated line breaks,
        # non-breaking spaces) must not defeat a genuine verbatim quote.
        curly = 'The report calls the “skill” gap real and growing across school systems.'
        straight = 'The report calls the "skill" gap real and growing across school systems.'
        self.assertEqual(verbatim_passage(straight, curly), normalize_for_match(straight))

        hyphenated = "Schools build curricu-\nlum competence in critical thinking for pupils."
        joined = "Schools build curriculum competence in critical thinking for pupils."
        self.assertEqual(verbatim_passage(joined, hyphenated), normalize_for_match(joined))

        ligature = "A key ﬁnding about AI literacy for school children is reported here."
        plain = "A key finding about AI literacy for school children is reported here."
        self.assertEqual(verbatim_passage(plain, ligature), plain)

        nbsp = "Digital competence matters for every school learner today."
        spaced = "Digital competence matters for every school learner today."
        self.assertEqual(verbatim_passage(spaced, nbsp), spaced)

        # A genuine paraphrase (different words) is still rejected: only typography
        # is neutralized, never wording.
        self.assertIsNone(
            verbatim_passage("The skill gap is enormous and growing fast in schools.", curly)
        )

    # --- Adversarial hallucination-guard suite -------------------------------
    # A finding that occurs verbatim in the report (across its original line
    # wraps). It is the positive control every forgery below is measured against.
    GENUINE_PASSAGE = (
        "Sustained collaboration between teachers and learners improves the "
        "uptake of digital competence in lower-secondary classrooms."
    )

    def test_adversarial_forgeries_are_rejected(self) -> None:
        # Each forgery is comfortably longer than the length floor, so its
        # rejection proves the *verbatim* guard fired, not the MIN_PASSAGE_LENGTH
        # cutoff. They span the four ways an LLM can drift from the text:
        # invention, paraphrase, truncation, and typographic forgery.
        cyrillic_a = "а"  # looks identical to Latin "a", different codepoint

        fabricated = (
            "AI literacy doubles student test scores within a single academic year."
        )
        # The hard paraphrase: every word of the genuine passage is present, only
        # "teachers and learners" is swapped to "learners and teachers". Maximum
        # lexical overlap, yet not a literal quote -> rejected. This is the key
        # negative proof: shared vocabulary is not shared provenance.
        reordered_paraphrase = (
            "Sustained collaboration between learners and teachers improves the "
            "uptake of digital competence in lower-secondary classrooms."
        )
        # A looser paraphrase: same claim, different words.
        loose_paraphrase = (
            "Working together, teachers and pupils raise digital competence in "
            "the lower-secondary grades over time."
        )
        # Shortened: the interior words "the uptake of" are removed, so the result
        # is no longer a contiguous passage of the report.
        shortened = (
            "Sustained collaboration between teachers and learners improves "
            "digital competence in lower-secondary classrooms."
        )
        # Typographic forgery: a single Latin "a" swapped for its Cyrillic
        # homoglyph. It looks identical, but it is a different codepoint and NFKC
        # does not fold across scripts, so the guard -- which compares codepoints,
        # not glyphs -- rejects it instead of silently accepting a lookalike.
        homoglyph_forgery = self.GENUINE_PASSAGE.replace("a", cyrillic_a, 1)
        # Single-word substitution: "lower-secondary" -> "upper-secondary". One
        # word changed, meaning altered, no longer verbatim.
        altered_word = self.GENUINE_PASSAGE.replace("lower-secondary", "upper-secondary")

        forgeries = {
            "fabricated": fabricated,
            "reordered_paraphrase": reordered_paraphrase,
            "loose_paraphrase": loose_paraphrase,
            "shortened": shortened,
            "homoglyph_forgery": homoglyph_forgery,
            "altered_word": altered_word,
        }
        for label, forgery in forgeries.items():
            self.assertGreaterEqual(
                len(normalize_for_match(forgery)), MIN_PASSAGE_LENGTH, label
            )
            self.assertIsNone(verbatim_passage(forgery, self.REPORT), label)

        # The positive control: the genuine passage IS accepted, so the rejections
        # above are about wording/provenance, not an over-eager guard.
        self.assertEqual(
            verbatim_passage(self.GENUINE_PASSAGE, self.REPORT), self.GENUINE_PASSAGE
        )

    def test_genuine_passages_survive_pdf_noise(self) -> None:
        # Genuine quotes carrying real PDF artefacts -- a folded ligature and an
        # intra-word hyphenation across a line break -- still match, while a
        # homoglyph forgery of the very same sentence does not.
        report_text = (
            "A key ﬁnding is that sustained collabora-\n"
            "tion between teachers improves critical thinking for school pupils."
        )
        genuine = (
            "A key finding is that sustained collaboration between teachers "
            "improves critical thinking for school pupils."
        )
        self.assertEqual(
            verbatim_passage(genuine, report_text), normalize_for_match(genuine)
        )
        forged = genuine.replace("a", "а", 1)  # Cyrillic homoglyph
        self.assertIsNone(verbatim_passage(forged, report_text))

    def test_adversarial_proposal_keeps_only_the_verbatim_finding(self) -> None:
        # End-to-end: a proposal whose findings are mostly forgeries (an invention
        # and a high-overlap paraphrase) plus one genuine quote yields exactly one
        # claim -- only the verbatim finding survives the guard into a candidate.
        proposal = {
            "title": "OECD Future of Education and Skills 2030: AI Literacy in Schools",
            "year": 2023,
            "source_type": "policy_report",
            "authors": ["OECD"],
            "summary": (
                "The report examines how compulsory education prepares learners "
                "aged 6 to 18 for artificial intelligence across member states."
            ),
            "findings": [
                {"statement": self.FABRICATED},
                {
                    "statement": (
                        "Sustained collaboration between learners and teachers "
                        "improves the uptake of digital competence in "
                        "lower-secondary classrooms."
                    )
                },
                {"statement": self.VERBATIM_WRAPPED},
            ],
        }
        _, claims = report_candidates(proposal, self.REPORT, self.URL, "OECD", 2023)
        self.assertEqual(
            [claim["statement"] for claim in claims], [self.VERBATIM_COLLAPSED]
        )

    def test_load_jobs_single_and_manifest(self) -> None:
        from argparse import Namespace

        rel = "tests/fixtures/reports/sample-report.txt"
        single = load_jobs(
            Namespace(manifest=None, report=rel, url=self.URL, publisher="OECD", year=2023)
        )
        self.assertEqual(len(single), 1)
        self.assertEqual(single[0]["url"], self.URL)
        self.assertEqual(single[0]["year"], 2023)
        self.assertTrue(single[0]["text"])

        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            write_json(
                manifest,
                [
                    {"report": rel, "url": "https://oecd.org/a", "publisher": "OECD", "year": 2023},
                    {"report": rel, "url": "https://wef.org/b"},
                ],
            )
            jobs = load_jobs(
                Namespace(manifest=str(manifest), report=None, url=None, publisher=None, year=None)
            )
        self.assertEqual([job["url"] for job in jobs], ["https://oecd.org/a", "https://wef.org/b"])
        self.assertEqual(jobs[1]["year"], None)

        # A malformed request is rejected rather than silently importing nothing.
        with self.assertRaises(ValueError):
            load_jobs(Namespace(manifest=None, report=None, url=None, publisher=None, year=None))
        with self.assertRaises(ValueError):
            load_jobs(Namespace(
                manifest=None, report="tests/fixtures/reports/missing.txt",
                url=self.URL, publisher=None, year=None,
            ))

    def test_batch_import_dedupes_across_jobs(self) -> None:
        # Two identical jobs in one run: the first writes a source + claim, the
        # second is fully deduplicated against the first via the output files.
        import os

        import ai_provider

        prompt = report_prompt(self.REPORT, self.URL)
        payload = {
            "kind": "complete",
            "model": "claude-opus-4-8",
            "prompt": prompt,
            "schema": REPORT_OUTPUT_SCHEMA,
        }
        job = {"text": self.REPORT, "url": self.URL, "publisher": "OECD", "year": 2023}
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "ai"
            sources_path = Path(tmp) / "candidates-reports-sources.json"
            claims_path = Path(tmp) / "candidates-reports-claims.json"
            with mock.patch.object(ai_provider, "CACHE_DIR", cache_dir), mock.patch.dict(
                os.environ, {"AI_PROVIDER": "cache", "AI_MODEL": "claude-opus-4-8"}
            ):
                ai_provider.cache_write(payload, self._proposal())
                first = import_job(dict(job), sources_path, claims_path)
                second = import_job(dict(job), sources_path, claims_path)
            stored_sources = load_json(sources_path)
            stored_claims = load_json(claims_path)
        self.assertEqual(first, (1, 1, 0))
        self.assertEqual(second, (0, 0, 0))
        self.assertEqual(len(stored_sources), 1)
        self.assertEqual(len(stored_claims), 1)
        self.assertEqual(stored_sources[0]["status"], "candidate")
        self.assertEqual(stored_claims[0]["evidence_strength"], "low")


class PdfTextExtractionTests(unittest.TestCase):
    """The optional PDF->plaintext helper's pure cleaner (no pypdf needed)."""

    def test_clean_extracted_text_repairs_extraction_noise(self) -> None:
        raw = (
            "AI lite­racy and curricu-\nlum design\n\n\n\n"
            "improve  critical   thinking.\nThe ﬁnal section follows. \n"
        )
        cleaned = clean_extracted_text(raw)
        # Soft hyphen dropped, hyphenated line break rejoined.
        self.assertIn("AI literacy and curriculum design", cleaned)
        # Runs of spaces collapsed; ligature folded by NFKC.
        self.assertIn("improve critical thinking.", cleaned)
        self.assertIn("The final section follows.", cleaned)
        # Blank-line runs squeezed to a single blank line; trailing newline added.
        self.assertNotIn("\n\n\n", cleaned)
        self.assertTrue(cleaned.endswith("\n"))

    def test_clean_extracted_text_handles_empty(self) -> None:
        self.assertEqual(clean_extracted_text("   \n\n  "), "")


class CandidateTriageTests(unittest.TestCase):
    """The candidate-backlog worksheet is read-only and mirrors the real data."""

    def test_worksheet_lists_every_open_candidate_claim(self) -> None:
        worksheet = build_worksheet()
        rows = worksheet["open_candidate_claims"]
        open_claim_ids = {c["id"] for c in load_records("claims") if c.get("status") == "candidate"}
        self.assertEqual({row["claim_id"] for row in rows}, open_claim_ids)
        # No reviewed/rejected claim leaks into the worksheet.
        non_candidate = {c["id"] for c in load_records("claims") if c.get("status") != "candidate"}
        self.assertFalse({row["claim_id"] for row in rows} & non_candidate)

    def test_worksheet_is_deterministic_and_undecided(self) -> None:
        first = build_worksheet()
        second = build_worksheet()
        self.assertEqual(first, second)
        for row in first["open_candidate_claims"]:
            # Every row ships undecided and carries actionable review commands.
            self.assertIsNone(row["decision"])
            self.assertTrue(any("promote_candidate.py claim" in cmd for cmd in row["review_commands"]))

    def test_worksheet_promotes_nothing(self) -> None:
        before = [dict(c) for c in load_records("claims")]
        build_worksheet()
        after = load_records("claims")
        self.assertEqual(before, after)


class PrefillScoringTests(unittest.TestCase):
    """The pre-fill eval's field matching and gated-vs-advisory split."""

    def test_age_range_lower_bound_tolerates_one_year(self) -> None:
        import eval_claim_prefill as ev

        # Entry age is precise: +/-1 on the lower bound (and overlapping) agrees.
        self.assertTrue(ev._values_match("age_range", "12-18", "11-18"))
        self.assertTrue(ev._values_match("age_range", "10-14", "11-14"))
        self.assertTrue(ev._values_match("age_range", "4-6", "3-6"))

    def test_age_range_upper_bound_tolerates_two_years(self) -> None:
        import eval_claim_prefill as ev

        # The school-stage "end" is fuzzier: an upper bound off by two agrees
        # (e.g. a secondary study reported as 12-16 vs the model's 12-18)...
        self.assertTrue(ev._values_match("age_range", "12-16", "12-18"))
        # ...but off by three does not, and a lower bound off by two does not.
        self.assertFalse(ev._values_match("age_range", "12-15", "12-18"))
        self.assertFalse(ev._values_match("age_range", "14-18", "12-18"))

    def test_age_range_flags_disjoint_bands(self) -> None:
        import eval_claim_prefill as ev

        self.assertFalse(ev._values_match("age_range", "5-8", "12-15"))
        self.assertTrue(ev._values_match("age_range", "6-12", "6-12"))

    def test_evidence_strength_stays_exact(self) -> None:
        import eval_claim_prefill as ev

        self.assertTrue(ev._values_match("evidence_strength", "moderate", "moderate"))
        # Adjacent categories are NOT folded together: a one-notch disagreement
        # remains a miss, so the strength metric keeps its bite.
        self.assertFalse(ev._values_match("evidence_strength", "high", "moderate"))
        self.assertFalse(ev._values_match("evidence_strength", "moderate", "low"))

    def test_only_structured_fields_are_gated(self) -> None:
        import eval_claim_prefill as ev

        # outcome/context are advisory (reported, not gated); the gated micro
        # average covers exactly age_range + evidence_strength.
        self.assertEqual(ev.GATED_FIELDS, ("age_range", "evidence_strength"))
        self.assertEqual(set(ev.ADVISORY_FIELDS), {"outcome", "context"})
        metrics = {
            "age_range": ev.FieldMetrics("age_range", matches=8, predicted=10, gold=10),
            "evidence_strength": ev.FieldMetrics("evidence_strength", matches=7, predicted=10, gold=10),
            "outcome": ev.FieldMetrics("outcome", matches=1, predicted=10, gold=10),
            "context": ev.FieldMetrics("context", matches=1, predicted=10, gold=10),
        }
        gated = ev.micro_average(metrics, ev.GATED_FIELDS)
        # 15 / 20 from the two structured fields only -- the weak advisory text
        # fields do not drag the gated number down.
        self.assertEqual(gated.predicted, 20)
        self.assertAlmostEqual(gated.precision, 0.75)


if __name__ == "__main__":
    unittest.main()
