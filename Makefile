# Operations shortcuts. See OPERATIONS.md for the full runbook.
.PHONY: install validate test eval eval-model eval-educator eval-prefill eval-prefill-record build recall-probe recall-ingest triage audit-domains train

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
eval-prefill:
	python scripts/eval_claim_prefill.py

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

# Audit the search allowlist against the reviewer's promote/reject ledger:
# proposes evidence-backed promotions/reviews into eval/domain_audit.json
# (gitignored). Reads only; changes no allowlist. See docs/allowlist-pflegen.md.
audit-domains:
	python scripts/audit_domains.py

train:
	python scripts/train_relevance.py
