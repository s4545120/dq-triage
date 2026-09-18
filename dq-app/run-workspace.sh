#!/usr/bin/env bash
# Run the app against Unity Catalog instead of the bundled fixture.
#
# Reads are live. WRITES WILL BE REFUSED: a laptop has no x-forwarded-email header, so
# identity.py stamps actor_source = 'local_standin', which violates two CHECK constraints
# on dq_results_disposition. That is deliberate — a laptop must not be able to forge a
# steward's decision into the audit register. Deploy as a Databricks App to write.
#
# Override any of these in the environment before calling.
set -euo pipefail

export DQ_APP_DATA_SOURCE="${DQ_APP_DATA_SOURCE:-databricks}"
export DQ_CATALOG="${DQ_CATALOG:-workspace}"
export DQ_SCHEMA="${DQ_SCHEMA:-dq_triage}"
export DQ_PREFIX="${DQ_PREFIX:-dq_}"
export DATABRICKS_WAREHOUSE_ID="${DATABRICKS_WAREHOUSE_ID:-ebf2cf6b81ca710b}"
export DATABRICKS_CONFIG_PROFILE="${DATABRICKS_CONFIG_PROFILE:-dbc-19c77b90-423e}"

cd "$(dirname "$0")"
echo "source=$DQ_APP_DATA_SOURCE  $DQ_CATALOG.$DQ_SCHEMA  warehouse=$DATABRICKS_WAREHOUSE_ID"
exec ../.venv/bin/streamlit run app.py "$@"
