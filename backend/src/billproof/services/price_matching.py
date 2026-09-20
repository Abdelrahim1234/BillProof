from dataclasses import dataclass, field
from decimal import Decimal

from billproof.models import PriceRecord
from billproof.repositories import prices as prices_repo
from billproof.schemas.analysis import MatchDetails

# docs/03 "Matching tiers" mapped onto docs/03 "Confidence" base values.
# Tier 5 (description-only) is intentionally absent: it never produces an
# automatic result.
TIER_NAME = {
    1: "same_hospital_exact_code_setting_payer_plan",
    2: "same_hospital_exact_code_setting",
    3: "same_hospital_exact_code_unknown_modifier_setting",
    4: "peer_hospital_exact_code_setting",
}
CONFIDENCE_BASE = {
    1: Decimal("1.00"),
    2: Decimal("0.90"),
    3: Decimal("0.80"),
    4: Decimal("0.70"),
}


@dataclass
class MatchOutcome:
    tier: int
    tier_name: str
    confidence_base: Decimal
    match: MatchDetails
    records: list[PriceRecord]
    warnings: list[str] = field(default_factory=list)


def _source_warnings(records: list[PriceRecord]) -> list[str]:
    warnings = []
    if any(record.charge_scope == "unknown" for record in records):
        warnings.append(
            "The public source does not identify whether this is a facility or professional charge."
        )
    if any(record.rate_unit is None for record in records):
        warnings.append("The public source does not state a service unit for this price.")
    return warnings


async def find_same_hospital_negotiated(
    db,
    *,
    hospital_id: str,
    code_type: str,
    code: str,
    care_setting: str | None,
    modifier: str | None,
    payer_normalized: str | None,
    plan_normalized: str | None,
    charge_scope: str | None = None,
) -> MatchOutcome | None:
    """docs/03 commercial benchmark order, items 1-2: exact payer[+plan] negotiated rate."""
    if not payer_normalized:
        return None

    if plan_normalized:
        records = await prices_repo.query(
            db,
            [hospital_id],
            code_type,
            code,
            charge_type="payer_negotiated",
            care_setting=care_setting,
            payer_normalized=payer_normalized,
            plan_normalized=plan_normalized,
            charge_scope=charge_scope,
        )
        if records:
            return MatchOutcome(
                1,
                TIER_NAME[1],
                CONFIDENCE_BASE[1],
                MatchDetails(
                    hospital_exact=True,
                    code_exact=True,
                    setting_exact=bool(care_setting),
                    modifier_exact=modifier is not None,
                    payer_exact=True,
                    plan_exact=True,
                    factors_used=["hospital", "code", "setting", "payer", "plan"],
                    missing_factors=[],
                ),
                records,
                _source_warnings(records),
            )

    # payer matched, plan unmatched (or not supplied) -> lower confidence + warning
    records = await prices_repo.query(
        db,
        [hospital_id],
        code_type,
        code,
        charge_type="payer_negotiated",
        care_setting=care_setting,
        payer_normalized=payer_normalized,
        charge_scope=charge_scope,
    )
    records = [r for r in records if not plan_normalized or r.plan_normalized != plan_normalized]
    if not records:
        return None
    # Payer matched but plan unmatched: docs/03 narrative minimums put this at
    # Medium (payer/plan missing), not High, so it takes tier 3's base rather
    # than tier 2's cash-price base even though the match shape resembles tier 2.
    return MatchOutcome(
        2,
        "same_hospital_exact_code_setting_payer_unmatched_plan",
        CONFIDENCE_BASE[3],
        MatchDetails(
            hospital_exact=True,
            code_exact=True,
            setting_exact=bool(care_setting),
            modifier_exact=modifier is not None,
            payer_exact=True,
            plan_exact=False,
            factors_used=["hospital", "code", "setting", "payer"],
            missing_factors=["plan"],
        ),
        records,
        warnings=["Exact plan not on file; using another plan's negotiated rate for the same payer."]
        + _source_warnings(records),
    )


async def find_same_hospital_charge_type(
    db,
    *,
    hospital_id: str,
    code_type: str,
    code: str,
    charge_type: str,
    care_setting: str | None,
    modifier: str | None,
    charge_scope: str | None = None,
) -> MatchOutcome | None:
    """Same-hospital lookup for a specific charge type (cash price, allowed_median, ...)."""
    records = await prices_repo.query(
        db,
        [hospital_id],
        code_type,
        code,
        charge_type=charge_type,
        care_setting=care_setting,
        modifier=modifier,
        charge_scope=charge_scope,
    )
    if records:
        return MatchOutcome(
            2,
            TIER_NAME[2],
            CONFIDENCE_BASE[2],
            MatchDetails(
                hospital_exact=True,
                code_exact=True,
                setting_exact=bool(care_setting),
                modifier_exact=modifier is not None,
                factors_used=["hospital", "code", "setting"] + (["modifier"] if modifier else []),
                missing_factors=[],
            ),
            records,
            _source_warnings(records),
        )

    # same hospital, code only (setting/modifier unknown)
    records = await prices_repo.query(
        db, [hospital_id], code_type, code, charge_type=charge_type, charge_scope=charge_scope
    )
    if records:
        return MatchOutcome(
            3,
            TIER_NAME[3],
            CONFIDENCE_BASE[3],
            MatchDetails(
                hospital_exact=True,
                code_exact=True,
                setting_exact=False,
                modifier_exact=None,
                factors_used=["hospital", "code"],
                missing_factors=["setting", "modifier"],
            ),
            records,
            _source_warnings(records),
        )
    return None


async def find_peer_charge_type(
    db,
    *,
    hospital_id: str,
    peer_hospital_ids: list[str],
    code_type: str,
    code: str,
    charge_type: str,
    care_setting: str | None,
    charge_scope: str | None = None,
) -> MatchOutcome | None:
    peers = [h for h in peer_hospital_ids if h != hospital_id]
    if not peers:
        return None
    records = await prices_repo.query(
        db,
        peers,
        code_type,
        code,
        charge_type=charge_type,
        care_setting=care_setting,
        charge_scope=charge_scope,
    )
    if not records:
        return None
    return MatchOutcome(
        4,
        TIER_NAME[4],
        CONFIDENCE_BASE[4],
        MatchDetails(
            hospital_exact=False,
            code_exact=True,
            setting_exact=bool(care_setting),
            factors_used=["code", "setting"],
            missing_factors=["hospital"],
        ),
        records,
        warnings=["No price on file at this hospital; showing a peer hospital's rate instead."]
        + _source_warnings(records),
    )
