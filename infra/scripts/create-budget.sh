#!/usr/bin/env bash
# Create a £10/month AWS cost budget with email alerts at 80% and 100%.
#
# Kept OUT of the CDK stack on purpose: AWS Budgets is a global (us-east-1)
# service, and a region-restricting SCP could reject it — which, if it were part
# of the main stack, would roll back the whole app deploy. Running it standalone
# isolates that risk and is trivially reversible.
#
# Usage:
#   ALERT_EMAIL=luke.willcox@outlook.com bash scripts/create-budget.sh
set -euo pipefail

ALERT_EMAIL="${ALERT_EMAIL:?set ALERT_EMAIL to the address that should get alerts}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUDGET_NAME="job-tracker-monthly-gbp10"

BUDGET_JSON="$(mktemp)"; NOTIF_JSON="$(mktemp)"
trap 'rm -f "$BUDGET_JSON" "$NOTIF_JSON"' EXIT

cat > "$BUDGET_JSON" <<JSON
{
  "BudgetName": "$BUDGET_NAME",
  "BudgetLimit": { "Amount": "10", "Unit": "GBP" },
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST"
}
JSON

cat > "$NOTIF_JSON" <<JSON
[
  {
    "Notification": { "NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN", "Threshold": 80, "ThresholdType": "PERCENTAGE" },
    "Subscribers": [ { "SubscriptionType": "EMAIL", "Address": "$ALERT_EMAIL" } ]
  },
  {
    "Notification": { "NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN", "Threshold": 100, "ThresholdType": "PERCENTAGE" },
    "Subscribers": [ { "SubscriptionType": "EMAIL", "Address": "$ALERT_EMAIL" } ]
  },
  {
    "Notification": { "NotificationType": "FORECASTED", "ComparisonOperator": "GREATER_THAN", "Threshold": 100, "ThresholdType": "PERCENTAGE" },
    "Subscribers": [ { "SubscriptionType": "EMAIL", "Address": "$ALERT_EMAIL" } ]
  }
]
JSON

echo "Creating budget '$BUDGET_NAME' (GBP 10/month) with alerts to $ALERT_EMAIL ..."
aws budgets create-budget \
  --account-id "$ACCOUNT_ID" \
  --budget "file://$BUDGET_JSON" \
  --notifications-with-subscribers "file://$NOTIF_JSON"

echo "Done. View it in the Billing console -> Budgets."
