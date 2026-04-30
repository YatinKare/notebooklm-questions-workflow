# AI Plan — code & config the AI will write

Everything the AI is responsible for, end to end. Anything requiring a human (account creation, OAuth flows, secret values, clicking around dashboards) lives in `user_plan.md` and is intentionally not duplicated here.

Assumes the user has finished `user_plan.md` §1–§4 and handed over: `GOOGLE_API_KEY`, `NOTEBOOK_ID`, the cookie file path, GCP project ID, Pages URL, model choices.

---

## 1. Repo scaffolding

- [x] Top-level layout:
  ```
  /backend     # Python, uv, FastAPI, ADK
  /frontend    # SvelteKit static
  /infra       # Dockerfile, wrangler.toml, deploy scripts
  README.md    # one-pager: how to run locally, how to deploy
  .gitignore   # __pycache__, .venv, node_modules, .env, *.db, build/
  ```
- [x] Root `README.md` with quickstart (`uv sync`, `uv run uvicorn ...`, `npm run dev`) and a pointer to `user_plan.md`.

---

## 2. Backend — Python package

### 2.1 Project setup
- [x] `backend/pyproject.toml` with deps: `fastapi`, `uvicorn[standard]`, `google-adk`, `pydantic`, `aiosqlite`, `sse-starlette`, `python-multipart`, `pillow`, `mcp` (or whatever the `notebooklm-mcp-cli` MCP client lib is), `python-dotenv` (dev only).
- [x] `uv.lock` committed.
- [x] `backend/.env.example` listing every env var from PRD §8 — no real values.

### 2.2 Module layout
```
backend/app/
  main.py              # FastAPI app, CORS, route registration, startup/shutdown
  config.py            # pydantic Settings, reads env
  db.py                # aiosqlite connection, schema migration on startup
  models.py            # pydantic models for Upload, Question, SSE events
  routes/
    uploads.py         # POST /uploads, GET /uploads, GET /uploads/{id}
    events.py          # GET /events/{job_id} SSE
    health.py          # GET /health
  pipeline/
    orchestrator.py    # asyncio queue, per-job state machine, SSE broadcast
    stages.py          # extracting / querying / parsing / verifying / done funcs
    prompts.py         # NotebookLM prompt template + JSON-strict retry preamble
  agents/
    extractor.py       # ADK vision agent
    verifier.py        # ADK text agent, runs in parallel with asyncio.gather
  notebooklm/
    client.py          # MCP stdio client wrapper, manages subprocess lifecycle
  events/
    bus.py             # in-process pub/sub: per-job_id asyncio.Queue fan-out
```

### 2.3 Database
- [x] `db.py` runs the PRD §5.4 schema as `CREATE TABLE IF NOT EXISTS` on startup. No external migration tool — single file, single user.
- [x] CRUD helpers: `create_upload`, `update_state`, `insert_questions`, `update_question_answer`, `list_uploads(limit=50)`, `get_upload_full(id)`.
- [x] Nightly cleanup task (asyncio background task) that deletes rows beyond the 50-most-recent cap.
- [x] **Smoke test:** throwaway `scripts/_smoke_db.py` that calls `create_upload`, `update_state`, `insert_questions`, `update_question_answer`, `get_upload_full`, then asserts the round-trip matches. Run, confirm green, delete the script before commit.

### 2.4 Pipeline orchestrator
- [x] Single asyncio queue + worker task started on FastAPI startup.
- [x] Job lifecycle exactly matches PRD §5.2 stages: `extracting → querying → parsing → verifying → done` (or `error`).
- [x] Every stage transition: write to SQLite, push `stage_changed` event onto the event bus.
- [x] Verifier stage: `asyncio.gather` over per-question verifier calls (PRD §5.3 — they don't touch NotebookLM).
- [x] Parsing retry: one retry with stricter "ONLY valid JSON" preamble (PRD §5.2 step 3). Second failure → mark job `error`, persist the raw NotebookLM response into `uploads.raw_notebooklm_response` for the UI's "show raw" toggle.
- [x] **Smoke test:** throwaway `scripts/_smoke_pipeline.py` that monkeypatches the extractor, NotebookLM client, and verifier with stub coroutines returning canned data, enqueues one job, and asserts stages fire in order `extracting → querying → parsing → verifying → done` plus the expected SSE events land on the bus. Also exercise the parsing-retry → `error` path with a stub that returns malformed JSON twice. Delete the script before commit.

### 2.5 Agents (ADK, code-first)
- [x] `extractor_agent`: vision-capable Gemini model, single LLM call, no tools. Prompt instructs it to return strict JSON `[{number, type, stem, options?}]` and to use exactly the seven `type` values from PRD §5.2.
- [x] `verifier_agent`: text Gemini model, no tools. Input: question + options + NotebookLM's draft answer + justification. Output: `{correct_answer, reasoning, confidence: "high"|"low", flagged: bool}`.
- [x] Both prompts kept in the agent files (not externalized) and written to be the main quality lever — easy to tweak.
- [x] Model IDs read from config so the user can swap Pro ↔ Flash without code edits.
- [x] **Smoke test:** throwaway `scripts/_smoke_agents.py` that runs `extractor_agent` against one sample screenshot in `scripts/test-images/` and `verifier_agent` against a hand-written `(question, draft_answer)` pair, prints both outputs, and asserts the JSON shape matches PRD §5.2 (extractor) and the verifier schema. Requires `GOOGLE_API_KEY`. Delete the script before commit.

### 2.6 NotebookLM MCP client
- [x] On FastAPI startup: spawn `notebooklm-mcp-cli` (or whatever the MCP server binary is named after `uv tool install`) as a subprocess; speak MCP over stdio.
- [x] Wrap the "ask question" MCP tool in an async method `client.ask(prompt: str) -> str`.
- [x] Robustness: timeout, single auto-restart on subprocess crash, log stderr. Exit cleanly on FastAPI shutdown.
- [x] Read `NOTEBOOK_ID` and `NLM_COOKIE_PATH` from config and pass through.
- [x] **Smoke test:** throwaway `scripts/_smoke_mcp.py` that spawns the MCP subprocess, calls `client.ask("Give me one sample question from this notebook.")`, prints the response, and exits cleanly. Confirms cookies + `NOTEBOOK_ID` work and the subprocess lifecycle is sane. Requires user_plan §2 to be done. Delete the script before commit.

### 2.7 SSE
- [x] `GET /events/{job_id}` opens an `EventSourceResponse` (sse-starlette). Subscribes to that job's queue on the event bus, yields events as they come, closes on `done`/`error`.
- [x] Events: `stage_changed`, `question_extracted` (one per question after stage 1 so frontend can render placeholders immediately — PRD §2 step 3), `question_completed`, `complete`, `error`.
- [x] Heartbeat every 15s to keep Cloudflare from idling the connection.
- [x] **Smoke test:** throwaway `scripts/_smoke_sse.py` that uses `httpx.AsyncClient` against the FastAPI app, creates a fake upload/questions row directly in SQLite, opens `/events/{job_id}`, publishes `stage_changed`, `question_completed`, and `complete` events through the bus, and asserts the SSE stream receives them in order and closes on `complete`. Also assert a late subscriber receives enough current DB state/backfill to render the job even if early in-memory events were missed. Delete the script before commit.

### 2.8 Routes
- [x] `POST /uploads`: multipart image upload, validate it's an image, create upload row, enqueue, return `{job_id}`. Don't store the raw image — only the extracted questions.
- [x] `GET /uploads`: list 50 most recent.
- [x] `GET /uploads/{job_id}`: full record so the frontend can re-open from history without replaying SSE.
- [x] `GET /health`: returns 200 + checks DB and MCP subprocess liveness.
- [x] CORS middleware reading `CORS_ORIGIN`.
- [x] **Smoke test:** throwaway `scripts/_smoke_routes.py` that monkeypatches the orchestrator with a stub queue, posts a tiny generated PNG to `/uploads`, asserts `{job_id}` is returned, verifies the upload row exists and no raw image bytes are stored, calls `GET /uploads` and `GET /uploads/{job_id}`, checks invalid/non-image upload rejection, and confirms `/health` reports DB + MCP status. Delete the script before commit.

---

## 3. Backend infra (needed to deploy before frontend exists)

- [x] `infra/Dockerfile` exactly per PRD §8 (python:3.12-slim, uv sync, `uv tool install notebooklm-mcp-cli`, uvicorn entrypoint).
- [x] `infra/deploy-backend.sh` — wraps the `gcloud run deploy` command from PRD §8 with the volume mount and env vars; reads project ID/region from arguments. For first deploy, set `CORS_ORIGIN=*` so curl tests don't need a frontend yet — tighten to the Pages URL later.
- [x] `.dockerignore` excluding `node_modules`, `.venv`, `frontend/`, `*.db`, etc.

---

## 4. Backend deploy + end-to-end verification (before any frontend work)

Goal: prove the deployed backend works end-to-end via HTTP only. No frontend needed — CORS does not apply to curl.

**Prereqs from user_plan:** §1 (gcloud, GCP project), §2 (NotebookLM cookies + `NOTEBOOK_ID`), §3 (Cloud Run volume, secrets, env var values). User_plan §4 (Cloudflare) is NOT needed yet.

- [x] Confirm with user that user_plan §1–§3 are done and they have: project ID, region, volume name, cookie path inside container, `NOTEBOOK_ID`, `GOOGLE_API_KEY` in Secret Manager.
- [x] Run `infra/deploy-backend.sh` (or have the user run it and paste back the Cloud Run URL).
- [x] `curl $URL/health` → expect 200, DB + MCP subprocess both healthy. If MCP fails: cookie file path or notebook ID is wrong — fix before continuing.
- [x] Run 3 e2e curl tests, each with a different sample screenshot (provide them in `scripts/test-images/`):
  - [x] `curl -F "file=@scripts/test-images/q1.png" $URL/uploads` → capture `job_id`.
  - [x] `curl -N $URL/events/$JOB_ID` → watch SSE stream; verify `stage_changed` events fire in order `extracting → querying → parsing → verifying → done`, plus one `question_extracted` per question and one `question_completed` per question.
  - [x] `curl $URL/uploads/$JOB_ID` → verify the returned JSON: every question has a `correct_answer`, non-empty `reasoning`, a `confidence` value, and the `type` matches one of the seven PRD §5.2 types.
  - [ ] Sanity-check answers against the source material — they should actually be right, not just well-formed.
- [ ] Test the error path: upload a screenshot with no questions / unreadable text. Expect `state: error` and `raw_notebooklm_response` populated.
- [ ] Test the parsing-retry path: temporarily lower the parser's strictness or inject a malformed response in a one-off script to confirm the retry preamble fires. (Optional — only if 5.2 step 3 isn't otherwise exercised.)
- [x] Write a short `scripts/e2e-curl.sh` that does the happy-path sequence above so it can be re-run after any backend change.

Status note, 2026-04-30:
- Backend is deployed at `https://screenshot-answers-94247799819.us-central1.run.app`; `/health` returns `{"status":"ok","db":"ok","mcp":"ok"}`.
- Current serving revision is `screenshot-answers-00004-pgp` at 100% traffic.
- `EXTRACTOR_MODEL` and `VERIFIER_MODEL` are both pinned to `gemini-2.5-flash` in code and Cloud Run.

### 4.1 Resolve Gemini extractor 503 blocker

- [x] Preserve the Cloud Run error logs for investigation:
  - `/tmp/notebooklm-questions-workflow/gemini-503-cloud-run-logs.json`
  - `/tmp/notebooklm-questions-workflow/recent-cloud-run-service.log`
- [x] Review the local retry wrapper in `backend/app/pipeline/stages.py` for transient external-call failures from extractor, NotebookLM query, and verifier calls.
- [x] Run backend checks locally after the retry change: `cd backend && uv run ruff check app && uv run mypy app`.
- [x] Rebuild and redeploy the backend image with the retry change using `infra/deploy-backend.sh notebooklm-questions-workflow us-central1 notebooklm-questions-workflow-data "$NOTEBOOK_ID"`.
- [x] Confirm `/health` still returns `{"status":"ok","db":"ok","mcp":"ok"}` after redeploy.
- [x] Re-run `scripts/e2e-curl.sh` for `q2.png`. Expected result: transient Gemini 503s are retried inside the job instead of immediately producing `state: error`.
- [x] Confirm deployed `EXTRACTOR_MODEL` and `VERIFIER_MODEL` remain pinned to `gemini-2.5-flash`.
- [x] Once q2 passes, rerun q1, q2, and q3 as the official three happy-path tests and continue the Step 4 checklist.

Changes made, 2026-04-30:
- Added transient retry/backoff in `backend/app/pipeline/stages.py` around extractor, NotebookLM query, and verifier calls.
- Fixed the retry helper typing so `cd backend && uv run ruff check app && uv run mypy app` both pass.
- Deployed revision `screenshot-answers-00004-pgp` with `EXTRACTOR_MODEL=gemini-2.5-flash`, `VERIFIER_MODEL=gemini-2.5-flash`, and `NLM_COOKIE_PATH=/mnt/data/profiles/default/cookies.json`.
- `scripts/e2e-curl.sh https://screenshot-answers-94247799819.us-central1.run.app scripts/test-images/q1.png` passed with job `aef4ae55-596c-4989-b732-fd943ebcf1de`.
- `scripts/e2e-curl.sh https://screenshot-answers-94247799819.us-central1.run.app scripts/test-images/q2.png` passed with job `e16b08e4-c84b-4ee2-9d24-adafffbfed82`.
- `scripts/e2e-curl.sh https://screenshot-answers-94247799819.us-central1.run.app scripts/test-images/q3.png` passed with job `3c9bfb70-b4e6-492b-8c3f-56362fda905f`.
- Current revision error check: `gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="screenshot-answers" AND resource.labels.revision_name="screenshot-answers-00004-pgp" AND severity>=ERROR' --project notebooklm-questions-workflow --limit 20` returns no entries.

### 4.2 Follow-up investigations before frontend

- [x] Source-grounding sanity check: compare q1/q2/q3 answers against the loaded NotebookLM source material, not just response shape. Resources: final job IDs above, `curl https://screenshot-answers-94247799819.us-central1.run.app/uploads/<job_id>`, and the NotebookLM notebook/source set from `user_plan.md` §2.
- [x] Error-path test: verify an unreadable/no-question screenshot produces a useful `state: error` payload. Commands: upload `scripts/test-images/blank.png`, stream `/events/$JOB_ID`, then inspect `/uploads/$JOB_ID`.
- [x] Parsing-retry test: add a focused mocked test for malformed NotebookLM JSON twice and confirm the strict retry path persists `raw_notebooklm_response`. Resources: `backend/app/pipeline/stages.py` `_parse_response` / `run_pipeline`; command target should be `cd backend && uv run pytest`.
- [x] Deployment env hardening: prevent local `.env` values from leaking Mac paths into Cloud Run deploys. Relevant mismatch: `backend/app/config.py` default `NLM_COOKIE_PATH`, `infra/deploy-backend.sh` default path, and `check_before_deploy.md` recommendation differ. Verification command: `gcloud run services describe screenshot-answers --project notebooklm-questions-workflow --region us-central1 --format='value(spec.template.spec.containers[0].env)'`.

Changes made, 2026-04-30:
- Added a no-question guard in `backend/app/pipeline/stages.py`: if extraction returns `[]`, the job now ends with `state: error`, `error_message="No questions were detected in the uploaded image."`, and `raw_notebooklm_response="Extractor returned no questions; NotebookLM was not queried."`.
- Added mocked pytest coverage for the no-question path and the malformed-NotebookLM JSON retry path in `backend/tests/test_pipeline_parsing_retry.py`.
- Added verifier source-grounding hardening in `backend/app/agents/verifier.py`: answers are forced to `confidence="low"` and `flagged=true` when NotebookLM says the answer is not in, not derived from, or unsupported by the provided sources.
- Added focused tests for the verifier source-grounding marker detection in `backend/tests/test_verifier_grounding.py`.
- Aligned backend/deploy cookie defaults to the actual mounted Cloud Run layout: `NLM_COOKIE_PATH=/mnt/data/profiles/default/cookies.json`.
- Hardened `infra/deploy-backend.sh` so `NLM_COOKIE_PATH` and `DB_PATH` must be absolute paths inside the mounted Cloud Run volume, preventing local `/Users/...` `.env` values from leaking into deploys.
- Local verification passed: `cd backend && uv run pytest` (4 passed), `cd backend && uv run ruff check app tests`, and `cd backend && uv run mypy app`.
- Deployed revision `screenshot-answers-00005-k7l` at 100% traffic; `/health` returns `{"status":"ok","db":"ok","mcp":"ok"}`.
- Deployment env verification shows `NLM_COOKIE_PATH=/mnt/data/profiles/default/cookies.json`, `DB_PATH=/mnt/data/app.db`, `EXTRACTOR_MODEL=gemini-2.5-flash`, and `VERIFIER_MODEL=gemini-2.5-flash`.
- Blank image error-path test passed with job `a0f6c22c-99d3-4864-90f3-df6086dc7ead`.
- `scripts/e2e-curl.sh https://screenshot-answers-94247799819.us-central1.run.app scripts/test-images/q1.png` passed with job `6637d3c8-3074-4a3a-a737-88392fde6a1c`.
- `scripts/e2e-curl.sh https://screenshot-answers-94247799819.us-central1.run.app scripts/test-images/q2.png` passed with job `7126dbf0-2bb5-424c-8663-eff812d5564c`.
- `scripts/e2e-curl.sh https://screenshot-answers-94247799819.us-central1.run.app scripts/test-images/q3.png` passed with job `6806a9c9-98ff-4334-b989-d44d8c8b02c0`.
- Source-grounding result: q1/q2/q3 are well-formed but not supported by the currently loaded NotebookLM source set; NotebookLM describes the loaded sources as unrelated to these biology/chemistry/history samples, and the verifier now flags all of those answers low-confidence instead of treating outside knowledge as source-grounded.
- Replaced `scripts/test-images/q1.png`, `q2.png`, and `q3.png` with computer-networking questions matching the loaded NotebookLM source set.
- Network `q1.png` passed with high-confidence grounded answers: job `f79170a2-2eca-48c1-bbf8-73c7af966911`.
- Network `q2.png` passed with high-confidence grounded answers: job `3f0219e9-9e27-4d88-870c-e6c110b03066`.
- Network `q3.png` passed with high-confidence grounded answers: job `6780426a-2996-49e8-a2b3-2c1fb6d683e6`.
- Quick closure check after network-image update: live `/health` passed, `cd backend && uv run pytest` passed, `cd backend && uv run ruff check app tests` passed, and `cd backend && uv run mypy app` passed.

Only proceed to §5 (frontend) once §4.2 is closed.

---

## 5. Frontend — SvelteKit static

### 5.1 Setup
- [x] Scaffolded SvelteKit with `@sveltejs/adapter-static` (manual scaffold — `sv create` is interactive).
- [x] `svelte.config.js` with SPA fallback (`fallback: '404.html'`), `+layout.ts` with `ssr: false, prerender: true`.
- [x] `frontend/.env.example` with `PUBLIC_API_BASE`. `frontend/.env` set to the live Cloud Run URL.

### 5.2 Components (PRD §6)
- [x] `src/routes/+page.svelte` — title, drop zone, current upload card list, history list. No router, single page.
- [x] `src/lib/DropZone.svelte` — drag/drop + paste-from-clipboard, POSTs to `/uploads`, kicks off SSE subscription.
- [x] `src/lib/QuestionCard.svelte` — collapsed and expanded states from PRD §6 "Card states", including the "show raw response" toggle on error.
- [x] `src/lib/eventSource.ts` — SSE wrapper, up to 3 reconnect retries, dispatches into the stores singleton.
- [x] `src/lib/api.ts` — typed fetch helpers for the four REST endpoints.
- [x] `src/lib/stores.svelte.ts` — Svelte 5 `$state` class singleton for current upload, history, per-card state.

### 5.3 Styling
- [x] `src/app.css` — system fonts, black/white + green accent (`#16a34a`) + amber warning (`#b45309`). No CSS framework.

Build: `npm run build` passes, `npm run check` reports 0 errors / 0 warnings (2026-04-30).

### 5.4 Behavior details
- [x] Placeholder cards appear on `question_extracted` events (stem + spinner + stage label); fill in on `question_completed`.
- [x] On page load, `GET /uploads` populates history. Clicking a history item calls `GET /uploads/{id}` and loads cards from final DB state (no SSE replay).
- [x] MCQ: `→ **A**` bolded when collapsed; correct option highlighted green when expanded.
- [x] T/F: answer shown in green when collapsed.
- [x] Low-confidence flag → amber badge on both collapsed and expanded card.
- [x] Pending card shows stem + italic stage label (`querying NotebookLM…` etc.) + spinner.

---

## 6. Frontend infra + deploy

- [x] `infra/wrangler.toml` with `pages_build_output_dir = "build"`.
- [x] `infra/deploy-frontend.sh` — `npm install && npm run build && npx wrangler pages deploy build`.
- [ ] **User action:** run `./infra/deploy-frontend.sh`, copy the Pages URL, update `CORS_ORIGIN` in Cloud Run (command printed by the script).
- [ ] Smoke-test the full stack in a browser: drop a screenshot, confirm cards stream in via SSE.

---

## 7. Quality

- [ ] Backend smoke tests with `pytest` + `httpx.AsyncClient`: `/health`, `POST /uploads` with a fixture image (mock the agents and MCP client), state-machine progression, parsing retry path, error path. No live Gemini / NotebookLM calls in tests.
- [ ] One end-to-end manual test script (`scripts/e2e.sh`) that hits a running local backend with a sample screenshot.
- [ ] Type checking: `mypy` strict on `backend/app`, `svelte-check` on the frontend.
- [ ] `ruff` + `ruff format` config in `pyproject.toml`.

---

## 8. Handoff to the user

When the AI is done, the user should be able to:
1. `cd backend && uv sync && uv run uvicorn app.main:app --reload` — runs against a local SQLite file, expects env vars from `.env`.
2. `cd frontend && npm install && npm run dev` — points at `http://localhost:8000` by default.
3. Run the two deploy scripts in `infra/` once their accounts/secrets from `user_plan.md` are in place.

The AI will produce a short `HANDOFF.md` summarizing: what was built, every env var that must be set, the exact deploy commands, and which files to tweak when the user wants to change agent prompts or model choices.
