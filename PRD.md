# PRD — notebooklm-questions-workflow

A one-page web app. Drop in a screenshot of exam questions, get back graded answer cards with reasoning, powered by a NotebookLM that has the source material loaded.

---

## 1. Goal

Take a screenshot of 3–5 exam questions, OCR them, classify the question types, ask NotebookLM all of them in a single grouped query, double-check each answer with a reasoning agent, and stream the results back as expandable cards.

Single user. No auth. Minimal styling. The complexity lives in the backend pipeline; the frontend is intentionally dumb.

---

## 2. User flow

1. User lands on the page. One drop zone, one history list below.
2. User drags or pastes a screenshot.
3. Card placeholders appear immediately for each question as soon as OCR finishes (e.g. "Q1 – analyzing…").
4. Cards fill in as the job completes — the answer block populates, the card becomes expandable.
5. Collapsed view: question stem + answer choices + the picked answer highlighted.
6. Expanded view: stem, all choices, correct answer(s), 1–2 sentence reasoning, raw NotebookLM excerpt, confidence flag if applicable.
7. Past uploads sit in a history list below the drop zone — click to re-open.

---

## 3. Non-goals (v1)

- No login, no multi-user, no sharing
- No editing of extracted questions before submission
- No re-running individual questions
- No mobile-optimized UI (desktop only is fine)
- No exporting results
- No NotebookLM source management from the UI — the notebook is pre-built with a hardcoded ID

---

## 4. Architecture

```
┌─────────────────────────┐         ┌─────────────────────────────────────┐
│  Cloudflare Pages       │  HTTPS  │  Cloud Run (Python, uv, ADK)        │
│  SvelteKit (static)     │ ──────▶ │  FastAPI + asyncio queue + SSE      │
│                         │   SSE   │                                     │
│  - drop zone            │ ◀────── │  ┌─ OCR/Classify Agent (Gemini)    │
│  - history list         │         │  ├─ Job orchestrator (asyncio)     │
│  - card list            │         │  ├─ NotebookLM MCP client          │
└─────────────────────────┘         │  └─ Reasoning/Verifier Agent       │
                                    │                                     │
                                    │       ┌─────────────────┐           │
                                    │       │  SQLite (file)  │           │
                                    │       │  on attached    │           │
                                    │       │  volume         │           │
                                    │       └─────────────────┘           │
                                    └─────────────────────────────────────┘
                                                     │
                                                     │ MCP (stdio) or HTTP
                                                     ▼
                                          ┌────────────────────┐
                                          │  notebooklm-mcp    │
                                          │  (subprocess in    │
                                          │   same container)  │
                                          └────────────────────┘
                                                     │
                                                     ▼
                                          NotebookLM (preloaded
                                          notebook, hardcoded ID)
```

### Why this shape

- **Cloudflare Pages for the frontend, Cloud Run for the backend** — Cloudflare Python Workers run on Pyodide/WASM and can't host headless Chrome (which `notebooklm-mcp` needs for cookie auth) or long-running asyncio queues. ADK has first-class one-command Cloud Run deploy. Cloudflare can still front the API via a custom domain if desired.
- **In-process asyncio queue** — only one user, low volume, simplest possible thing that works. No Redis, no Cloud Tasks.
- **SQLite on a Cloud Run volume** — keeps history across reloads, single file, zero ops.
- **SSE, not WebSockets** — one-way server→client push is all we need; SSE is one HTTP endpoint and works through Cloudflare without config.
- **notebooklm-mcp in the same container** — installed via `uv tool install notebooklm-mcp-cli`, launched as a subprocess by the backend, talked to over MCP stdio. Cookies live on the volume.

---

## 5. Backend pipeline

### 5.1 Endpoints (FastAPI)

| Method | Path                  | Purpose                                                     |
| ------ | --------------------- | ----------------------------------------------------------- |
| POST   | `/uploads`            | Accept image, return `job_id`, enqueue work                 |
| GET    | `/uploads`            | List recent uploads (history, newest first, max 50)         |
| GET    | `/uploads/{job_id}`   | Full job state + all questions + answers (for reload)       |
| GET    | `/events/{job_id}`    | SSE stream of state changes for a single job                |
| GET    | `/health`             | Liveness                                                    |

### 5.2 Pipeline stages

For each upload, a single job runs through these stages. State transitions are written to SQLite and broadcast over SSE.

1. **`extracting`** — Gemini vision (via ADK) reads the image and returns a structured array: `[{number, text, options?}, ...]`. Same call also classifies each question into one of: `TF | MCQ | SELECT_MULTIPLE | MATCHING | SHORT_ANSWER | SHORT_ANSWER_MATH | LONG_ANSWER`.
2. **`querying`** — All questions in the job get rolled into one natural-language prompt sent to NotebookLM via the MCP client. Format is human-readable but standardized so the response is parseable:
   ```
   Please answer the following questions using the source material.
   For each, give the answer and a 1–2 sentence justification.
   Format your response as JSON: [{"q": <number>, "answer": <answer>,
   "justification": <text>}, ...]

   1. (MCQ) <stem>
      A) ...  B) ...  C) ...  D) ...
   2. (T/F) <stem>
   ...
   ```
3. **`parsing`** — Try to parse JSON out of NotebookLM's response. If it fails, retry the query once with a stricter "respond with ONLY valid JSON" preamble. If the retry fails too, mark the whole job as `error` and surface the raw text in the UI.
4. **`verifying`** — A separate ADK reasoning agent runs per-question, getting `(question, options, NotebookLM's answer, NotebookLM's justification)` as input. It either confirms the answer or flags it. Output is the final card payload: `{question, type, options, correct_answer, reasoning, confidence: "high" | "low", flagged?}`.
5. **`done`** — Final card payloads written to SQLite, SSE pushes a final `complete` event.

Each stage broadcasts a `stage_changed` SSE event so the frontend can update the placeholder cards (e.g. "querying NotebookLM…").

### 5.3 ADK agents

Two agents, both Gemini-backed, defined in the ADK code-first style:

- **`extractor_agent`** — vision model. Input: image bytes. Tools: none. Output: structured question list with types. Single LLM call, no tool use.
- **`verifier_agent`** — text model. Input: one question + NotebookLM's draft answer. Tools: none. Output: confirmed/flagged final answer + reasoning. Runs N times in parallel per job (asyncio.gather) since these are independent and don't hit NotebookLM.

The NotebookLM call is *not* an ADK tool — it's a direct MCP client call from the orchestrator. That keeps the verifier from accidentally calling NotebookLM again and burning quota.

### 5.4 SQLite schema

```sql
CREATE TABLE uploads (
  id TEXT PRIMARY KEY,             -- uuid
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  state TEXT NOT NULL,             -- extracting|querying|parsing|verifying|done|error
  error_message TEXT,
  raw_notebooklm_response TEXT     -- kept for debugging
);

CREATE TABLE questions (
  id TEXT PRIMARY KEY,             -- uuid
  upload_id TEXT NOT NULL REFERENCES uploads(id),
  number INTEGER NOT NULL,
  type TEXT NOT NULL,              -- TF|MCQ|SELECT_MULTIPLE|MATCHING|SHORT_ANSWER|SHORT_ANSWER_MATH|LONG_ANSWER
  stem TEXT NOT NULL,
  options_json TEXT,               -- JSON array of choices, null for short/long answer
  correct_answer_json TEXT,        -- JSON: string for MCQ/TF, array for SELECT_MULTIPLE/MATCHING
  reasoning TEXT,
  confidence TEXT,                 -- high|low
  flagged INTEGER DEFAULT 0
);

CREATE INDEX idx_questions_upload ON questions(upload_id);
CREATE INDEX idx_uploads_created ON uploads(created_at DESC);
```

### 5.5 NotebookLM setup (one-time, manual)

Outside the app, you do this once:
1. `uv tool install notebooklm-mcp-cli`
2. `nlm login` to extract cookies
3. Create a notebook in the NotebookLM UI, upload the source PDFs/text
4. Grab the notebook ID from the URL, set as `NOTEBOOK_ID` env var on Cloud Run
5. Mount the cookie file from the persistent volume into the container

The app itself never creates notebooks or adds sources.

---

## 6. Frontend (SvelteKit)

One page, deployed as a static export to Cloudflare Pages.

### Layout

```
┌──────────────────────────────────────────────┐
│  Screenshot → Answers                        │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │   Drop a screenshot or paste an image  │  │
│  │            (drag area)                 │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  Current upload                              │
│  ┌────────────────────────────────────────┐  │
│  │ Q1 (MCQ)   "What is the cap…"      ▾   │  │  ← collapsed, shows answer
│  │ Q2 (T/F)   "Mitochondria are…"     ▾   │  │
│  │ Q3 (MCQ)   analyzing…              ⏳  │  │  ← in flight
│  └────────────────────────────────────────┘  │
│                                              │
│  History                                     │
│  • 2:34 PM — biology midterm.png  (5 Qs)     │
│  • 1:12 PM — orgo_pset.png        (3 Qs)     │
└──────────────────────────────────────────────┘
```

### Card states

- **Pending** — spinner, shows current stage label ("extracting", "querying NotebookLM", "verifying")
- **Done, collapsed** — one line: `Q{n} ({type}) "{stem truncated}" → {answer}`. For MCQ, the picked letter is bold. For T/F, just "True" or "False" in green.
- **Done, expanded** — full stem, all options listed, correct option(s) highlighted, reasoning paragraph, low-confidence badge if flagged.
- **Error** — red border, error message, "show raw response" toggle that reveals the raw NotebookLM output for debugging.

### Components

- `+page.svelte` — the whole app
- `DropZone.svelte` — drag/drop + paste handler, POSTs to `/uploads`
- `QuestionCard.svelte` — one card, handles its own expand/collapse
- `eventSource.ts` — thin SSE wrapper, subscribes on upload, updates a Svelte store

### Styling

System fonts. Two colors: black text on white, plus a single accent (probably green) for correct answers and one warning color (amber) for flagged. No framework — plain CSS in one file. The whole thing should feel like a Linear-issued internal tool, not a marketing page.

---

## 7. Tech stack summary

| Layer            | Tech                                          |
| ---------------- | --------------------------------------------- |
| Frontend         | SvelteKit (static adapter), plain CSS         |
| Frontend host    | Cloudflare Pages                              |
| Backend          | Python 3.12, FastAPI, asyncio                 |
| Package mgmt     | uv (`uv sync`, `uv run`, `uv tool install`)   |
| Agent framework  | google-adk (Python)                           |
| LLM              | Gemini (via ADK), model TBD per agent         |
| NotebookLM       | `notebooklm-mcp-cli` package, MCP stdio       |
| Storage          | SQLite (single file on a Cloud Run volume)    |
| Realtime         | Server-Sent Events                            |
| Backend host     | Cloud Run (`adk deploy cloud_run` or Docker)  |

---

## 8. Deployment

### Backend (Cloud Run)

`Dockerfile`:
```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
RUN uv tool install notebooklm-mcp-cli
COPY . .
ENV PORT=8080
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

Deploy:
```
gcloud run deploy screenshot-answers \
  --source . \
  --region us-central1 \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 1 \
  --max-instances 1 \
  --allow-unauthenticated
```

`min-instances=1, max-instances=1` is intentional — the in-memory asyncio queue and SSE connections only work on a single instance. Volume mount the SQLite file and the notebooklm cookies from a Cloud Run volume.

Required env vars: `GOOGLE_API_KEY` (or ADC), `NOTEBOOK_ID`, `NLM_COOKIE_PATH`, `DB_PATH`, `CORS_ORIGIN` (the Pages URL).

### Frontend (Cloudflare Pages)

`wrangler.toml` with `pages_build_output_dir = "build"`, deployed via `npx wrangler pages deploy build` after `vite build`. Set `PUBLIC_API_BASE` to the Cloud Run URL.

---

## 9. Operational notes

- **NotebookLM rate limits** — free tier is ~50 queries/day. Each upload uses 1 query (we batch all questions). Heavy days could exhaust this.
- **Cookie expiration** — re-run `nlm login` every couple weeks when auth fails. The MCP server auto-refreshes CSRF tokens but can't recover from a fully expired Google login.
- **Single-instance** — if Cloud Run scales us to zero between sessions, that's fine; if it ever scales to >1, the queue and SSE break. Min/max=1 enforces this.
- **History cap** — 50 most recent uploads, older ones auto-deleted nightly via a small SQLite cleanup task.

---

## 10. Open questions / future

- Do we want a "edit extracted questions before sending to NotebookLM" step? Skipped for v1, but OCR errors will sometimes warrant it.
- Verifier agent could optionally re-query NotebookLM if confidence is low. Skipped for v1 to keep query count predictable.
- Multiple notebook support (different classes/subjects) — would just need a notebook picker dropdown driven by env config.
- Mobile paste/upload — the page works, but card layout isn't tuned for small screens.
