"""Turn the human review ledger into evidence for the search allowlist.

The search allowlist has two coupled halves (see OPERATIONS.md and
``docs/allowlist-pflegen.md``):

- ``data/source_domains.json`` — the **soft** trust tiers (``trusted`` / ``watch``
  / ``open``) that label every web-search hit and steer triage ordering;
- ``resolve_source_url.CREDIBLE_DOMAINS`` — the **hard** open-web allowlist the
  URL resolver accepts hits from.

Both are curated by hand. The risk of any hand-curated allowlist is that it
drifts from reality: a publisher that keeps yielding accepted evidence stays
stuck in ``open``, while a tiered domain that only ever produces rejects keeps
its rank boost. This routine closes that gap by mining the one ground truth the
project already records — the reviewer's promote/reject decisions on sources —
and proposing allowlist changes *backed by that ledger*:

- **Promotion candidates**: untiered (``open``) hosts that have earned several
  accepted (``status='reviewed'``) sources at a high acceptance rate. They are
  pulling their weight from the bottom of the worksheet and have evidence to be
  tiered up (and added to ``CREDIBLE_DOMAINS``).
- **Review candidates**: tiered (``trusted`` / ``watch``) hosts whose ledger is
  all-rejects / zero-accepts — their a-priori standing is not borne out by the
  data and a human should reconsider it.
- **Invariant drift**: any ``CREDIBLE_DOMAINS`` host the tier list forgot to list
  (kept empty by a test; reported here for completeness).

Like ``triage_candidates.py`` it writes **nothing** into ``data/`` and changes
**no** allowlist: it reads the committed sources and emits a gitignored
worksheet plus the exact edits a maintainer would make. Every change still lands
through a human-reviewed pull request.

    python scripts/audit_domains.py            # write eval/domain_audit.json

Run it on the same cadence as the candidate review (see OPERATIONS.md): the more
review decisions accumulate, the sharper the proposals.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from common import ROOT, TODAY, load_records, write_json
from ingest_websearch import host_tier, load_domain_tiers, registrable_host
from resolve_source_url import CREDIBLE_DOMAINS

WORKSHEET_PATH = ROOT / "eval" / "domain_audit.json"

# Evidence thresholds. A promotion needs more than a single lucky hit; a review
# flag needs a real pattern of rejects, not one off-scope paper. Deliberately
# conservative — the worksheet only *proposes*, a human decides per PR.
MIN_ACCEPTED_FOR_PROMOTION = 2
MIN_ACCEPT_RATE_FOR_PROMOTION = 0.6
MIN_REJECTED_FOR_REVIEW = 2

# A source counts as "accepted" once a reviewer promoted it; "rejected" once a
# reviewer turned it down. Candidates are still undecided and only inform volume.
ACCEPTED_STATUS = "reviewed"
REJECTED_STATUS = "rejected"

# DOI/handle resolvers and catalogue aggregators are *link infrastructure*, not
# publishers: the catalogue importers store a DOI link in ``url``, whose host is
# ``doi.org`` regardless of the real publisher behind it. Allowlisting them would
# whitelist every DOI link and defeat the allowlist's purpose, so they never
# become promotion candidates — they are flagged ``infrastructure`` in the ledger
# and skipped. Edit this set when a new resolver shows up in the ledger.
NON_PUBLISHER_HOSTS = frozenset({
    "doi.org", "dx.doi.org", "hdl.handle.net", "handle.net",
    "semanticscholar.org", "api.semanticscholar.org",
    "openalex.org", "api.openalex.org",
    "crossref.org", "api.crossref.org", "search.crossref.org",
    "researchgate.net", "academia.edu",
})


def _is_infrastructure(host: str) -> bool:
    return any(host == d or host.endswith(f".{d}") for d in NON_PUBLISHER_HOSTS)


def _blank_ledger() -> dict[str, Any]:
    return {"accepted": 0, "rejected": 0, "candidate": 0, "examples": []}


def domain_ledger(sources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate the review decisions per registrable host.

    Every source with a resolvable URL contributes to its host's tally, regardless
    of which importer found it: the allowlist is about *publishers*, and a
    publisher's track record is the union of all evidence it has produced here.
    """
    ledger: dict[str, dict[str, Any]] = {}
    for source in sources:
        host = registrable_host(str(source.get("url") or ""))
        if not host:
            continue
        entry = ledger.setdefault(host, _blank_ledger())
        status = source.get("status")
        if status == ACCEPTED_STATUS:
            entry["accepted"] += 1
        elif status == REJECTED_STATUS:
            entry["rejected"] += 1
        else:
            entry["candidate"] += 1
        if len(entry["examples"]) < 3:
            entry["examples"].append(
                {"id": source.get("id", ""), "title": source.get("title", ""), "status": status}
            )
    return ledger


def _accept_rate(entry: dict[str, Any]) -> float:
    decided = entry["accepted"] + entry["rejected"]
    return entry["accepted"] / decided if decided else 0.0


def _in_credible(host: str) -> bool:
    return any(host == d or host.endswith(f".{d}") for d in CREDIBLE_DOMAINS)


def _credible_edit_hint(host: str) -> str:
    return (
        f'add "{host}" to data/source_domains.json (watch.domains) '
        f'and to CREDIBLE_DOMAINS in scripts/resolve_source_url.py'
    )


def build_worksheet(sources: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    ledger = domain_ledger(sources)

    promotion: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    table: list[dict[str, Any]] = []

    for host, entry in ledger.items():
        tier, _delta = host_tier(f"https://{host}/", config)
        rate = _accept_rate(entry)
        infrastructure = _is_infrastructure(host)
        row = {
            "host": host,
            "current_tier": tier,
            "in_credible_domains": _in_credible(host),
            "infrastructure": infrastructure,
            "accepted": entry["accepted"],
            "rejected": entry["rejected"],
            "candidate": entry["candidate"],
            "accept_rate": round(rate, 2),
        }
        table.append(row)

        # Resolvers/aggregators are link infrastructure, never a credibility
        # signal — they inform the ledger but never a promote/review proposal.
        if infrastructure:
            continue

        # Promotion: an untiered host that the reviewer keeps accepting.
        if (
            tier == "open"
            and entry["accepted"] >= MIN_ACCEPTED_FOR_PROMOTION
            and rate >= MIN_ACCEPT_RATE_FOR_PROMOTION
        ):
            promotion.append(
                {
                    **row,
                    "examples": entry["examples"],
                    "suggested_action": "promote to 'watch' (a human picks 'trusted' for official/peer-reviewed publishers)",
                    "edit_hint": _credible_edit_hint(host),
                }
            )
        # Review: a tiered host whose boost the ledger does not earn.
        elif (
            tier in ("trusted", "watch")
            and entry["accepted"] == 0
            and entry["rejected"] >= MIN_REJECTED_FOR_REVIEW
        ):
            review.append(
                {
                    **row,
                    "examples": entry["examples"],
                    "suggested_action": f"reconsider '{tier}' standing — only rejected sources so far",
                }
            )

    # Drift against the hard allowlist (kept empty by a test; reported anyway so
    # this worksheet is a single, self-contained allowlist-health view).
    listed: set[str] = set()
    for tier in config.get("tiers", {}).values():
        if isinstance(tier, dict):
            listed.update(str(d).lower().removeprefix("www.") for d in tier.get("domains", []))
    credible_not_tiered = sorted(CREDIBLE_DOMAINS - listed)

    promotion.sort(key=lambda r: (-r["accepted"], -r["accept_rate"], r["host"]))
    review.sort(key=lambda r: (-r["rejected"], r["host"]))
    table.sort(key=lambda r: (-(r["accepted"] + r["rejected"] + r["candidate"]), r["host"]))

    return {
        "_README": (
            "Search-allowlist health worksheet (gitignored, regenerated each run). "
            "Evidence comes from reviewer promote/reject decisions on sources. This "
            "file proposes nothing binding: promotion_candidates and review_candidates "
            "are leads for a maintainer to act on through a pull request that edits "
            "data/source_domains.json and CREDIBLE_DOMAINS. See docs/allowlist-pflegen.md."
        ),
        "generated_at": TODAY,
        "thresholds": {
            "min_accepted_for_promotion": MIN_ACCEPTED_FOR_PROMOTION,
            "min_accept_rate_for_promotion": MIN_ACCEPT_RATE_FOR_PROMOTION,
            "min_rejected_for_review": MIN_REJECTED_FOR_REVIEW,
        },
        "invariant_credible_not_tiered": credible_not_tiered,
        "promotion_candidates": promotion,
        "review_candidates": review,
        "domain_ledger": table,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit the search allowlist against the reviewer's promote/reject ledger."
    )
    parser.add_argument("--output", default=str(WORKSHEET_PATH.relative_to(ROOT)))
    args = parser.parse_args()

    sources = load_records("sources")
    config = load_domain_tiers()
    worksheet = build_worksheet(sources, config)
    write_json(ROOT / args.output, worksheet)

    promo = worksheet["promotion_candidates"]
    rev = worksheet["review_candidates"]
    drift = worksheet["invariant_credible_not_tiered"]
    print(
        f"Audited {len(worksheet['domain_ledger'])} publisher host(s) across {len(sources)} source(s): "
        f"{len(promo)} promotion candidate(s), {len(rev)} review candidate(s) -> {args.output}."
    )
    if promo:
        print("  Promote: " + ", ".join(f"{r['host']} (+{r['accepted']})" for r in promo))
    if rev:
        print("  Review:  " + ", ".join(f"{r['host']} (-{r['rejected']})" for r in rev))
    if drift:
        print(f"  WARNING: CREDIBLE_DOMAINS not tiered: {', '.join(drift)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
