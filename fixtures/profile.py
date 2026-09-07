"""Profiles every bound CDE column and emits results.cde_profile.

This is the only part of the fixture that describes data rather than judging it, and
the numbers it produces are entirely real: it runs over the pilot CSVs, applies the
binding's scope filter, and counts. Nothing here is back-projected or hand-written.

MASKED SIGNATURES, NOT VALUES. Every value is reduced to its shape before anything
is counted: digits become 9, letters X, whitespace _, and punctuation survives
because it is structure rather than content. Runs collapse to a class and a length,
so `1976-02-02 00:00:00` becomes `9{4}-9{2}-9{2}_9{2}:9{2}:9{2}` and an address
becomes `X{4}.X{5}@X{7}.X{3}`. The transform is one-way and the output is the useful
half: a column with one signature is uniform, and a column with a minority signature
is telling you where its defects are before any rule has been written.

K-ANONYMITY ON PII SIGNATURES. A shape seen on one row of a name column is close to
describing one person. So for an element flagged `pii`, signatures occurring on
fewer than MIN_SIGNATURE_ROWS rows are folded into a single `<rare>` bucket that
keeps the count and discards the shape. `value_stats_withheld` on the row records
that this happened — an omission that says so is auditable, one that is silent is
not. The fourteen malformed dates of birth survive the threshold comfortably, which
is the point: suppression aimed at single rows does not blind you to defects that
matter.
"""

from __future__ import annotations

import uuid
from itertools import groupby

import pandas as pd

import cdes
from cdes import CDE, Binding
from rules import CTCT_TABLE, SENTINELS, SUBS_TABLE, Ctx

TOP_SIGNATURES = 8       # how many shapes to keep per column, most common first
MIN_SIGNATURE_ROWS = 5   # k-anonymity floor for a PII element's signatures
PROFILE_JOB = "job:dq-cde-profiler"


def _cls(ch: str) -> str:
    if ch.isdigit():
        return "9"
    if ch.isalpha():
        return "X"
    if ch.isspace():
        return "_"
    return ch  # punctuation is structure, and structure is what we are keeping


def signature(value: str) -> str:
    """Masked shape of one value: character classes with run lengths, no content."""
    out = []
    for cls, grp in groupby(value, key=_cls):
        n = sum(1 for _ in grp)
        out.append(cls if n == 1 else f"{cls}{{{n}}}")
    return "".join(out)


def _frame(ctx: Ctx, target_table: str) -> pd.DataFrame:
    if target_table == CTCT_TABLE:
        return ctx.ctct
    if target_table == SUBS_TABLE:
        return ctx.subs
    raise KeyError(f"No local frame for {target_table}")


def _top_signatures(values: pd.Series, pii: bool) -> tuple[list[dict], int]:
    """(the top shapes as structs, the number of distinct shapes)."""
    sigs = values.map(signature)
    counts = sigs.value_counts()
    total = int(counts.sum())
    distinct = int(len(counts))
    if total == 0:
        return [], 0

    if pii:
        rare = counts[counts < MIN_SIGNATURE_ROWS]
        counts = counts[counts >= MIN_SIGNATURE_ROWS]
        if len(rare):
            # The count survives, the shape does not.
            counts = pd.concat([counts, pd.Series({"<rare>": int(rare.sum())})])
            counts = counts.sort_values(ascending=False)

    top = [
        dict(signature=str(sig), row_count=int(n), pct=round(n / total * 100, 4))
        for sig, n in counts.head(TOP_SIGNATURES).items()
    ]
    return top, distinct


def profile_binding(ctx: Ctx, cde: CDE, binding: Binding) -> dict:
    df = _frame(ctx, binding.target_table)
    scope = df[binding.scope_fn(df)] if binding.scope_fn is not None else df

    raw = scope[binding.target_column]
    stripped = raw.astype(str).str.strip()

    rows_scanned = int(len(scope))
    # The CSVs are read with keep_default_na=False, so a missing value arrives as an
    # empty string and there are no true NULLs to find. Counting them separately
    # anyway keeps the shape of the row honest against a warehouse that has both.
    null_count = int(raw.isna().sum())
    blank_count = int((stripped == "").sum() - null_count) if rows_scanned else 0
    populated = stripped[stripped != ""]
    populated_count = int(len(populated))

    top, signature_count = _top_signatures(populated, cde.pii)

    match_pct = None
    if cde.expected_signature and populated_count:
        matched = populated.str.match(cde.expected_signature)
        match_pct = round(float(matched.sum()) / populated_count * 100, 4)

    def pct(n: int, d: int) -> float | None:
        return round(n / d * 100, 4) if d else None

    return dict(
        profile_id=None,          # stamped by the caller, which owns the run id
        profile_run_id=None,
        profile_ts=None,
        cde_id=cde.cde_id,
        cde_version=cde.cde_version,
        data_class=cde.data_class,
        criticality=cde.criticality,
        pii=cde.pii,
        target_table=binding.target_table,
        target_column=binding.target_column,
        scope_filter=binding.expected_scope_filter,
        rows_scanned=rows_scanned,
        null_count=null_count,
        null_pct=pct(null_count, rows_scanned),
        blank_count=blank_count,
        blank_pct=pct(blank_count, rows_scanned),
        populated_count=populated_count,
        distinct_count=int(populated.nunique()),
        distinct_pct=pct(int(populated.nunique()), populated_count),
        min_length=int(populated.str.len().min()) if populated_count else None,
        max_length=int(populated.str.len().max()) if populated_count else None,
        signature_count=signature_count,
        top_signatures=top,
        signature_match_pct=match_pct,
        sentinel_count=int(populated.str.lower().isin(SENTINELS).sum()),
        value_stats_withheld=bool(cde.pii),
        profiled_by=PROFILE_JOB,
        duration_sec=None,        # stamped by the caller from its own rng
    )


def build_cde_profile(ctx: Ctx, profile_ts, det_uuid, rng) -> pd.DataFrame:
    """One row per bound binding. `det_uuid` and `rng` come from build_fixtures so
    the output stays deterministic with the rest of the fixture."""
    run_id = det_uuid("cde_profile_run", profile_ts.date().isoformat())
    rows = []
    for cde in cdes.CDES:
        if cde.status != "registered":
            continue
        for binding in cdes.bindings_of(cde):
            row = profile_binding(ctx, cde, binding)
            row.update(
                profile_id=det_uuid("cde_profile", run_id, cde.cde_id,
                                    binding.target_column),
                profile_run_id=run_id,
                profile_ts=profile_ts,
                duration_sec=round(rng.uniform(0.6, 4.5), 2),
            )
            rows.append(row)
    return pd.DataFrame(rows)


def build_cde_registry(effective_from, registered_by: str) -> pd.DataFrame:
    """config.cde_registry. One version per element — the PoC registers each once
    and never re-tiers, so there is no version history to fold. The table is
    append-only regardless, and v_cde_registry_current derives effective_to from
    the next version exactly as the rule registry does."""
    return pd.DataFrame([
        dict(
            cde_id=c.cde_id,
            cde_version=c.cde_version,
            cde_name=c.cde_name,
            business_term=c.business_term,
            data_class=c.data_class,
            definition=c.definition,
            expected_signature=c.expected_signature,
            criticality=c.criticality,
            pii=c.pii,
            regulatory_basis=c.regulatory_basis,
            bindings=[b.to_struct() for b in c.bindings],
            business_domain=c.business_domain,
            owner_group=c.owner_group,
            status=c.status,
            effective_from=effective_from,
            registered_by=registered_by,
            registered_at=effective_from,
            note=c.note,
        )
        for c in cdes.CDES
    ])
