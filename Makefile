# Operations shortcuts. See OPERATIONS.md for the full runbook.
.PHONY: install validate test eval eval-model eval-educator eval-prefill eval-prefill-record eval-skill-links eval-skill-links-record compare-providers build recall-probe recall-ingest triage refilter audit-domains train

install:
	pip install -r requirements-dev.txt

validate:
	python scripts/validate_data.py

test:
	python -m unittest discover -s tests

eval:
	python scripts/eval_relevance.py

eval-model:
	python scripts/eval_relevance.py --compare-model

# Measure the automated educator relevance lane against its own labeled set
# (eval/relevance_educator.json), kept separate from the learner labels.
eval-educator:
	python scripts/eval_relevance.py --educator-lane

# Offline field metrics for the optional LLM claim pre-fill (P1), from fixtures.
# This is the regression view: it scores the RECORDED outputs against gold.
# outcome/context are scored semantically (embedding cosine) from the committed
# vectors in tests/fixtures/embeddings/, so this stays offline; the old lexical
# precision is printed alongside. After a --record-live run, run this once with
# sentence-transformers installed to mint vectors for the new texts.
eval-prefill:
	python scripts/eval_claim_prefill.py

# Offline metrics for the OPTIONAL skill-link suggestion, from fixtures. Reports
# only: the golden set (eval/skill_link_labeled.json) carries agent-PROPOSED
# links, so the script refuses any --min-* gate until a reviewer sets its
# _status to 'reviewed'. Watch the 'abstain' column -- 38 of 50 examples map to
# no catalogue skill, and that is where an over-eager model shows up first.
eval-skill-links:
	python scripts/eval_skill_links.py

# Re-record the skill-link fixtures from the live model and report live accuracy.
# Needs AI_PROVIDER=anthropic + ANTHROPIC_API_KEY; commit the refreshed
# eval/skill_link_labeled.json together with tests/fixtures/ai/.
eval-skill-links-record:
	AI_PROVIDER=anthropic python scripts/eval_skill_links.py --record-live

# Compare AI providers on the pre-fill golden set (offline, from fixtures).
# Supporting several providers is only worth the code if the choice can be
# measured; this is that measurement. Record a challenger first with
# `AI_PROVIDER=openai python scripts/compare_providers.py --record openai
#  --model openai=gpt-4o` (ollama needs no key, just a running local server).
compare-providers:
	python scripts/compare_providers.py

# Re-record the pre-fill fixtures from the live model and report live accuracy.
# Needs AI_PROVIDER=anthropic + ANTHROPIC_API_KEY; overwrites '_recorded' and the
# fixtures, so commit both afterwards. See OPERATIONS.md ("Re-recording").
eval-prefill-record:
	AI_PROVIDER=anthropic python scripts/eval_claim_prefill.py --record-live

build:
	python scripts/build_site.py

# Surface the relevance filter's rejected region for labeling (fights the
# harvest's selection bias). Fills eval/recall_probe.json with a worksheet.
recall-probe:
	python scripts/recall_probe.py

# After filling in the 'relevant' fields, fold the labels into the eval set.
recall-ingest:
	python scripts/recall_probe.py --ingest eval/recall_probe.json

# Turn the standing candidate backlog into a review worksheet
# (eval/candidate_triage.json, gitignored). Reads only; promotes nothing.
triage:
	python scripts/triage_candidates.py

# Re-check open candidates against the CURRENT relevance vocabulary
# (eval/candidate_refilter.json, gitignored). Run after every vocabulary
# change. Reads only; rejects nothing.
refilter:
	python scripts/refilter_candidates.py

# Audit the search allowlist against the reviewer's promote/reject ledger:
# proposes evidence-backed promotions/reviews into eval/domain_audit.json
# (gitignored). Reads only; changes no allowlist. See docs/allowlist-pflegen.md.
audit-domains:
	python scripts/audit_domains.py

train:
	python scripts/train_relevance.py
