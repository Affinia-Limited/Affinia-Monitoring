#!/usr/bin/env bash
# Start the Container Apps migration job and wait for it to finish.
# Usage: scripts/run-migration-job.sh <resource-group> <job-name> [timeout-seconds]
set -euo pipefail

RG="$1"
JOB="$2"
TIMEOUT="${3:-1200}"

EXECUTION=$(az containerapp job start -g "$RG" -n "$JOB" --query name -o tsv)
echo "Started migration execution: $EXECUTION"

elapsed=0
while (( elapsed < TIMEOUT )); do
  STATUS=$(az containerapp job execution show -g "$RG" -n "$JOB" --job-execution-name "$EXECUTION" \
    --query properties.status -o tsv)
  echo "Status: $STATUS"
  case "$STATUS" in
    Succeeded) exit 0 ;;
    Failed|Stopped|Degraded)
      echo "Migration job $STATUS. Inspect logs: az containerapp job logs show -g $RG -n $JOB --execution $EXECUTION" >&2
      exit 1 ;;
  esac
  sleep 10
  elapsed=$(( elapsed + 10 ))
done

echo "Timed out waiting for migration job after ${TIMEOUT}s" >&2
exit 1
