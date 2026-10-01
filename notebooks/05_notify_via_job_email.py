# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · Notification via Databricks job email
# MAGIC
# MAGIC The no-credential alternative to `04_send_notification`. This notebook sends
# MAGIC nothing. It receives the message the app already composed, validates it, prints
# MAGIC it and returns it as the run's output. **The email is sent by Databricks**, from
# MAGIC the job's own `email_notifications.on_success` list, when this run succeeds.
# MAGIC
# MAGIC What that trades away, compared with 04:
# MAGIC
# MAGIC * The subject and body are Databricks' generic run notification, not the app's.
# MAGIC   The composed message is one click away, as this run's output.
# MAGIC * Recipients are fixed on the job. The `recipients` parameter the app passes
# MAGIC   (from `DQ_NOTIFY_TO`) is printed for the record and **not** used for delivery.
# MAGIC
# MAGIC What it gains: no SMTP host, no secret scope, no password anywhere.
# MAGIC
# MAGIC Same parameters as 04, so the app's `DQ_NOTIFY=job` path drives either one
# MAGIC unchanged — only `DQ_NOTIFY_JOB_ID` decides which.

# COMMAND ----------

dbutils.widgets.text("recipients", "")
dbutils.widgets.text("subject", "")
dbutils.widgets.text("body_text", "")
dbutils.widgets.text("body_html", "")
dbutils.widgets.text("cohort_id", "")
dbutils.widgets.text("disposition_id", "")

subject = dbutils.widgets.get("subject")
body_text = dbutils.widgets.get("body_text")
recipients = dbutils.widgets.get("recipients")
disposition_id = dbutils.widgets.get("disposition_id")

# Fail on an empty message. A failed run does not trigger on_success, so a wiring
# bug in the caller cannot produce an email that says nothing — it produces a
# failed run, and the job's on_failure list hears about that instead.
missing = [n for n, v in [("subject", subject), ("body_text", body_text),
                          ("disposition_id", disposition_id)] if not v]
if missing:
    raise ValueError(f"nothing to notify - missing: {', '.join(missing)}")

# COMMAND ----------

print(f"Subject: {subject}")
print(f"App-routed recipients (not used for delivery): {recipients or '-'}")
print()
print(body_text)

# COMMAND ----------

# The run output is what the notification email's run link leads to.
dbutils.notebook.exit(f"{subject}\n\n{body_text}")
