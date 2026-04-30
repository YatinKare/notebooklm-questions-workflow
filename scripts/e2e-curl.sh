#!/usr/bin/env bash
set -euo pipefail

API_BASE="${1:-${API_BASE:-}}"
IMAGE="${2:-${IMAGE:-scripts/test-images/q1.png}}"

if [[ -z "${API_BASE}" ]]; then
  echo "usage: scripts/e2e-curl.sh API_BASE [IMAGE]" >&2
  echo "   or: API_BASE=https://... scripts/e2e-curl.sh" >&2
  exit 64
fi

if [[ ! -f "${IMAGE}" ]]; then
  echo "image not found: ${IMAGE}" >&2
  exit 66
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

echo "health"
curl -fsS "${API_BASE}/health" | tee "${TMP_DIR}/health.json"
python3 - "${TMP_DIR}/health.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    payload = json.load(f)
if payload != {"status": "ok", "db": "ok", "mcp": "ok"}:
    raise SystemExit(f"health check failed: {payload}")
PY

echo "upload ${IMAGE}"
curl -fsS -F "file=@${IMAGE}" "${API_BASE}/uploads" | tee "${TMP_DIR}/upload.json"
JOB_ID="$(python3 - "${TMP_DIR}/upload.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    print(json.load(f)["job_id"])
PY
)"
echo "job_id=${JOB_ID}"

echo "events"
curl -fsS -N --max-time "${SSE_TIMEOUT:-240}" "${API_BASE}/events/${JOB_ID}" \
  | tee "${TMP_DIR}/events.txt" || true

python3 - "${TMP_DIR}/events.txt" <<'PY'
import sys

events = []
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if line.startswith("event: "):
        events.append(line.removeprefix("event: "))

required = ["stage_changed", "question_extracted", "question_completed", "complete"]
missing = [event for event in required if event not in events]
if missing:
    raise SystemExit(f"missing SSE event(s): {missing}; saw {events}")
print("saw events:", ", ".join(events))
PY

echo "final job"
curl -fsS "${API_BASE}/uploads/${JOB_ID}" | tee "${TMP_DIR}/job.json"
python3 - "${TMP_DIR}/job.json" <<'PY'
import json
import sys

allowed = {
    "TF",
    "MCQ",
    "SELECT_MULTIPLE",
    "MATCHING",
    "SHORT_ANSWER",
    "SHORT_ANSWER_MATH",
    "LONG_ANSWER",
}

with open(sys.argv[1], encoding="utf-8") as f:
    payload = json.load(f)

if payload["state"] != "done":
    raise SystemExit(f"job did not finish: {payload['state']} {payload.get('error_message')}")
if not payload["questions"]:
    raise SystemExit("job finished without questions")
for question in payload["questions"]:
    if question["type"] not in allowed:
        raise SystemExit(f"invalid question type: {question['type']}")
    if question["correct_answer"] in (None, "", []):
        raise SystemExit(f"missing answer for question {question['number']}")
    if not question["reasoning"]:
        raise SystemExit(f"missing reasoning for question {question['number']}")
    if question["confidence"] not in {"high", "low"}:
        raise SystemExit(f"invalid confidence for question {question['number']}")
print(f"validated {len(payload['questions'])} question(s)")
PY
