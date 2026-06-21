# Operations shortcuts. See OPERATIONS.md for the full runbook.
.PHONY: install validate test eval eval-model eval-prefill build recall-probe recall-ingest train

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

# Offline field metrics for the optional LLM claim pre-fill (P1), from fixtures.
eval-prefill:
	python scripts/eval_claim_prefill.py

build:
	python scripts/build_site.py

# Surface the relevance filter's rejected region for labeling (fights the
# harvest's selection bias). Fills eval/recall_probe.json with a worksheet.
recall-probe:
	python scripts/recall_probe.py

# After filling in the 'relevant' fields, fold the labels into the eval set.
recall-ingest:
	python scripts/recall_probe.py --ingest eval/recall_probe.json

train:
	python scripts/train_relevance.py
