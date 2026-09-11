"""The deployed app reads `dq_app/fixture_data/`, not `fixtures/out/`.

Only `dq-app/` is shipped to Databricks Apps, and `fixtures/out/` is generated and
gitignored, so the package carries its own copy. Two copies of the same data drift,
and the drift is invisible: the app keeps running and quietly serves last month's
numbers. This test is the thing that notices.

It is skipped on a clone that has not built the fixture, because `fixtures/out/`
genuinely is not there — that is the one case where having no comparison is correct.
Rebuild with `cd fixtures && ../.venv/bin/python build_fixtures.py`, then refresh the
bundle with `cp ../fixtures/out/*.parquet dq_app/fixture_data/`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

BUNDLED = Path(__file__).resolve().parents[1] / "dq_app" / "fixture_data"
GENERATED = Path(__file__).resolve().parents[2] / "fixtures" / "out"


def _digests(directory: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.glob("*.parquet"))
    }


def test_bundle_is_populated():
    """Independent of the generated fixture: a deployed app with an empty bundle
    fails at the first read, and it should fail here first instead."""
    assert BUNDLED.is_dir(), f"no bundled fixture at {BUNDLED}"
    assert _digests(BUNDLED), f"no parquet in {BUNDLED}"


def test_bundle_matches_generated_fixture():
    if not GENERATED.is_dir():
        pytest.skip(f"{GENERATED} not built — nothing to compare against")

    generated, bundled = _digests(GENERATED), _digests(BUNDLED)

    missing = sorted(set(generated) - set(bundled))
    extra = sorted(set(bundled) - set(generated))
    stale = sorted(n for n in set(generated) & set(bundled) if generated[n] != bundled[n])

    assert not missing, f"bundled fixture is missing: {missing}"
    assert not extra, f"bundled fixture has files the generator did not write: {extra}"
    assert not stale, f"bundled fixture is out of date: {stale}"
