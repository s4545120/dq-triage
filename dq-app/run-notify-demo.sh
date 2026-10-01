#!/usr/bin/env bash
# Run the app on the fixture with the notification transport switched on, to see
# where the decision form discloses it. Sends nothing, twice over: DQ_NOTIFY=log
# only writes to the log, and session-only writes are never read back, so
# `notify.dispatch` returns `unconfirmed` before composing anything.
#
# The form therefore says "Accepting sends nothing here — writes are session-only."
# To see it name a recipient instead, the write has to be durable, which means
# deployed. `tests/test_notify.py` pins both wordings.
set -euo pipefail

export DQ_NOTIFY="${DQ_NOTIFY:-log}"
export DQ_NOTIFY_TO="${DQ_NOTIFY_TO:-*: crm-owners@example.com}"

cd "$(dirname "$0")"
echo "DQ_NOTIFY=$DQ_NOTIFY  to=$DQ_NOTIFY_TO  (fixture, sends nothing)"
exec ../.venv/bin/streamlit run app.py "$@"
