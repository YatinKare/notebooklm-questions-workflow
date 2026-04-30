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
- [ ] `db.py` runs the PRD §5.4 schema as `CREATE TABLE IF NOT EXISTS` on startup. No external migration tool — single file, single user.
- [ ] CRUD helpers: `create_upload`, `update_state`, `insert_questions`, `update_question_answer`, `list_uploads(limit=50)`, `get_upload_full(id)`.
- [ ] Nightly cleanup task (asyncio background task) that deletes rows beyond the 50-most-recent cap.

### 2.4 Pipeline orchestrator
- [ ] Single asyncio queue + worker task started on FastAPI startup.
- [ ] Job lifecycle exactly matches PRD §5.2 stages: `extracting → querying → parsing → verifying → done` (or `error`).
- [ ] Every stage transition: write to SQLite, push `stage_changed` event onto the event bus.
- [ ] Verifier stage: `asyncio.gather` over per-question verifier calls (PRD §5.3 — they don't touch NotebookLM).
- [ ] Parsing retry: one retry with stricter "ONLY valid JSON" preamble (PRD §5.2 step 3). Second failure → mark job `error`, persist the raw NotebookLM response into `uploads.raw_notebooklm_response` for the UI's "show raw" toggle.

### 2.5 Agents (ADK, code-first)
- [ ] `extractor_agent`: vision-capable Gemini model, single LLM call, no tools. Prompt instructs it to return strict JSON `[{number, type, stem, options?}]` and to use exactly the seven `type` values from PRD §5.2.
- [ ] `verifier_agent`: text Gemini model, no tools. Input: question + options + NotebookLM's draft answer + justification. Output: `{correct_answer, reasoning, confidence: "high"|"low", flagged: bool}`.
- [ ] Both prompts kept in the agent files (not externalized) and written to be the main quality lever — easy to tweak.
- [ ] Model IDs read from config so the user can swap Pro ↔ Flash without code edits.

### 2.6 NotebookLM MCP client
- [ ] On FastAPI startup: spawn `notebooklm-mcp-cli` (or whatever the MCP server binary is named after `uv tool install`) as a subprocess; speak MCP over stdio.
- [ ] Wrap the "ask question" MCP tool in an async method `client.ask(prompt: str) -> str`.
- [ ] Robustness: timeout, single auto-restart on subprocess crash, log stderr. Exit cleanly on FastAPI shutdown.
- [ ] Read `NOTEBOOK_ID` and `NLM_COOKIE_PATH` from config and pass through.

### 2.7 SSE
- [ ] `GET /events/{job_id}` opens an `EventSourceResponse` (sse-starlette). Subscribes to that job's queue on the event bus, yields events as they come, closes on `done`/`error`.
- [ ] Events: `stage_changed`, `question_extracted` (one per question after stage 1 so frontend can render placeholders immediately — PRD §2 step 3), `question_completed`, `complete`, `error`.
- [ ] Heartbeat every 15s to keep Cloudflare from idling the connection.

### 2.8 Routes
- [ ] `POST /uploads`: multipart image upload, validate it's an image, create upload row, enqueue, return `{job_id}`. Don't store the raw image — only the extracted questions.
- [ ] `GET /uploads`: list 50 most recent.
- [ ] `GET /uploads/{job_id}`: full record so the frontend can re-open from history without replaying SSE.
- [ ] `GET /health`: returns 200 + checks DB and MCP subprocess liveness.
- [ ] CORS middleware reading `CORS_ORIGIN`.

---

## 3. Backend infra (needed to deploy before frontend exists)

- [ ] `infra/Dockerfile` exactly per PRD §8 (python:3.12-slim, uv sync, `uv tool install notebooklm-mcp-cli`, uvicorn entrypoint).
- [ ] `infra/deploy-backend.sh` — wraps the `gcloud run deploy` command from PRD §8 with the volume mount and env vars; reads project ID/region from arguments. For first deploy, set `CORS_ORIGIN=*` so curl tests don't need a frontend yet — tighten to the Pages URL later.
- [ ] `.dockerignore` excluding `node_modules`, `.venv`, `frontend/`, `*.db`, etc.

---

## 4. Backend deploy + end-to-end verification (before any frontend work)

Goal: prove the deployed backend works end-to-end via HTTP only. No frontend needed — CORS does not apply to curl.

**Prereqs from user_plan:** §1 (gcloud, GCP project), §2 (NotebookLM cookies + `NOTEBOOK_ID`), §3 (Cloud Run volume, secrets, env var values). User_plan §4 (Cloudflare) is NOT needed yet.

- [ ] Confirm with user that user_plan §1–§3 are done and they have: project ID, region, volume name, cookie path inside container, `NOTEBOOK_ID`, `GOOGLE_API_KEY` in Secret Manager.
- [ ] Run `infra/deploy-backend.sh` (or have the user run it and paste back the Cloud Run URL).
- [ ] `curl $URL/health` → expect 200, DB + MCP subprocess both healthy. If MCP fails: cookie file path or notebook ID is wrong — fix before continuing.
- [ ] Run 3 e2e curl tests, each with a different sample screenshot (provide them in `scripts/test-images/`):
  - [ ] `curl -F "file=@scripts/test-images/q1.png" $URL/uploads` → capture `job_id`.
  - [ ] `curl -N $URL/events/$JOB_ID` → watch SSE stream; verify `stage_changed` events fire in order `extracting → querying → parsing → verifying → done`, plus one `question_extracted` per question and one `question_completed` per question.
  - [ ] `curl $URL/uploads/$JOB_ID` → verify the returned JSON: every question has a `correct_answer`, non-empty `reasoning`, a `confidence` value, and the `type` matches one of the seven PRD §5.2 types.
  - [ ] Sanity-check answers against the source material — they should actually be right, not just well-formed.
- [ ] Test the error path: upload a screenshot with no questions / unreadable text. Expect `state: error` and `raw_notebooklm_response` populated.
- [ ] Test the parsing-retry path: temporarily lower the parser's strictness or inject a malformed response in a one-off script to confirm the retry preamble fires. (Optional — only if 5.2 step 3 isn't otherwise exercised.)
- [ ] Write a short `scripts/e2e-curl.sh` that does the happy-path sequence above so it can be re-run after any backend change.

Only proceed to §5 (frontend) once all three e2e tests pass.

---

## 5. Frontend — SvelteKit static

### 5.1 Setup
- [ ] `npm create svelte@latest` with the static adapter (`@sveltejs/adapter-static`).
- [ ] Configure `svelte.config.js` for full prerender + SPA fallback.
- [ ] `frontend/.env.example` with `PUBLIC_API_BASE`.

### 5.2 Components (PRD §6)
- [ ] `src/routes/+page.svelte` — title, drop zone, current upload card list, history list. No router, single page.
- [ ] `src/lib/DropZone.svelte` — drag/drop + paste-from-clipboard, POSTs to `/uploads`, kicks off SSE subscription.
- [ ] `src/lib/QuestionCard.svelte` — collapsed and expanded states from PRD §6 "Card states", including the "show raw response" toggle on error.
- [ ] `src/lib/eventSource.ts` — SSE wrapper, reconnect on drop, dispatches into a Svelte store keyed by `job_id`.
- [ ] `src/lib/api.ts` — typed fetch helpers for the four REST endpoints.
- [ ] `src/lib/stores.ts` — Svelte stores for current upload, history, per-card state.

### 5.3 Styling
- [ ] One `app.css`, system fonts, two colors (black/white) + green accent + amber warning, exactly as PRD §6 says. No CSS framework.

### 5.4 Behavior details
- [ ] Render placeholder cards as soon as `question_extracted` events arrive, before answers exist (PRD §2 step 3).
- [ ] On page load, `GET /uploads` to populate history. Clicking a history item calls `GET /uploads/{id}` and re-renders cards in their final state (no SSE replay).
- [ ] MCQ: bold the picked letter when collapsed; highlight the correct option when expanded.
- [ ] Low-confidence flag → amber badge on the card.

---

## 6. Frontend infra + deploy

- [ ] `infra/wrangler.toml` with `pages_build_output_dir = "build"`.
- [ ] `infra/deploy-frontend.sh` — `npm run build && npx wrangler pages deploy build`.
- [ ] After Pages deploys, paste the Pages URL back into Cloud Run as `CORS_ORIGIN` and redeploy the backend (tightening the `*` from §4).
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
