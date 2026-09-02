"""The test that keeps the Python fold honest.

`domain/lifecycle.derive_cohort_current` is a copy of `v_cohort_current` in
`sql/ddl/08_views.sql`. A copy is only safe while something proves it is still a
copy, and this is that thing: the fold is run over the generated register and
compared, column by column, against the `v_cohort_current` output the fixture ships.

If this fails after you edited the view, the app has drifted from the definition.
If it fails after you edited the fold, the fold is wrong. Either way the two
disagree, and the view wins.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dq_app.domain.lifecycle import derive_cohort_current


def _equal(left: pd.Series, right: pd.Series) -> pd.Series:
    """Element-wise equality where two nulls count as equal.

    SQL NULL arrives from Parquet as None, NaN or NaT depending on the column's
    dtype, and none of those compare equal to themselves. Without this, a column
    that is correctly NULL on both sides reads as a mismatch.
    """
    null_left, null_right = left.isna(), right.isna()
    both_present = ~null_left & ~null_right
    same = pd.Series(False, index=left.index)
    same[both_present] = (
        left[both_present].astype(str).values == right[both_present].astype(str).values
    )
    return (null_left & null_right) | same


def test_fold_reproduces_shipped_view(cohorts, dispositions, shipped_view):
    got = derive_cohort_current(cohorts, dispositions)

    assert len(got) == len(shipped_view)
    assert set(got["cohort_id"]) == set(shipped_view["cohort_id"])

    a = shipped_view.sort_values("cohort_id").reset_index(drop=True)
    b = got.sort_values("cohort_id").reset_index(drop=True)

    shared = [c for c in a.columns if c in b.columns]
    # Everything the shipped view projects must be reproduced. If the view grows a
    # column the fold does not compute, that is a gap, not a tolerance.
    assert shared == list(a.columns), f"fold is missing {set(a.columns) - set(b.columns)}"

    mismatches = {}
    for col in shared:
        if col == "mttr_days":
            # The fixture rounds MTTR to 2dp on write; the fold keeps full precision.
            close = np.isclose(
                a[col].astype(float), b[col].astype(float), atol=0.01, equal_nan=True
            )
            if not close.all():
                mismatches[col] = a.loc[~close, "cohort_id"].tolist()
            continue
        eq = _equal(a[col], b[col])
        if not eq.all():
            mismatches[col] = a.loc[~eq, "cohort_id"].tolist()

    assert not mismatches, f"fold disagrees with v_cohort_current: {mismatches}"


def test_every_lifecycle_branch_is_exercised(cohorts, dispositions):
    """The fixture is built to hit every branch of the CASE ladder. If a branch stops
    being reachable, a UI state has become untestable and nobody would notice."""
    states = set(derive_cohort_current(cohorts, dispositions)["lifecycle_state"])
    assert {
        "reopened",
        "awaiting_review",
        "approved_awaiting_execution",
        "deferred",
        "closed_verified",
        "closed_rejected",
    } <= states
