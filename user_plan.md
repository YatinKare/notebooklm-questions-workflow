# User Plan — manual steps only

Things **you** need to do by hand. Everything else (code, schema, Dockerfile, Svelte components, SSE wiring) the AI will write.

---

## 1. Accounts & API keys

- [x] **Google AI Studio / Gemini API key** — create at https://aistudio.google.com/app/apikey. Save as `GOOGLE_API_KEY`. Used by both ADK agents (extractor, verifier).
- [x] **Google Cloud project** — create or pick one. Note the project ID. Enable billing.
  - [x] Enable APIs: Cloud Run, Artifact Registry, Cloud Build, Secret Manager.
  - [x] Install `gcloud` CLI locally and run `gcloud auth login` + `gcloud config set project <ID>`.
- [x] **Cloudflare account** — sign up at cloudflare.com. Install `wrangler` (`npm i -g wrangler`) and run `wrangler login`.
- [ ] **GitHub repo** — push this project so Cloud Build / Pages can pull from it (optional but easier than uploading from local).

---

## 2. NotebookLM setup (one-time, manual — the app never does this)

- [ ] Locally: `uv tool install notebooklm-mcp-cli`.
- [ ] Run `nlm login` and complete the Google login flow in the browser. This writes a cookie file — note the path (default `~/.config/notebooklm-mcp/cookies.json` or similar).
- [ ] Go to https://notebooklm.google.com, **create a new notebook**, upload all the PDFs / text / slides you want as the source material for exam questions.
- [ ] Open the notebook and copy its **notebook ID** from the URL (the long string after `/notebook/`). Save as `NOTEBOOK_ID`.
- [ ] Test locally: ask the MCP CLI a question against that notebook ID to confirm cookies + ID work before deploying.

---

## 3. Cloud Run prep

- [ ] **Create a Cloud Run volume / GCS-backed storage** for the SQLite file + cookie file persistence. (Cloud Run supports volume mounts via GCS Fuse or a managed Cloud Storage volume.) Decide the mount path (e.g. `/data`).
- [ ] Upload your `cookies.json` from step 2 into that bucket/volume so the container can read it at startup.
- [ ] Decide region (`us-central1` is fine).
- [ ] Put secrets in **Secret Manager**: `GOOGLE_API_KEY`. Grant the Cloud Run service account access.
- [ ] Confirm env vars you'll set on the service:
  - `GOOGLE_API_KEY` (from Secret Manager)
  - `NOTEBOOK_ID`
  - `NLM_COOKIE_PATH` (path inside container, e.g. `/data/cookies.json`)
  - `DB_PATH` (e.g. `/data/app.db`)
  - `CORS_ORIGIN` (your Pages URL, filled in after step 4)

---

> **Order matters:** finish §1–§3 before the AI deploys the backend. The AI will deploy the backend with `CORS_ORIGIN=*` and run curl-based end-to-end tests against it before any frontend work begins. Do §4 (Cloudflare) only after those backend tests pass.

---

## 4. Cloudflare Pages prep (do this AFTER backend e2e tests pass)

- [ ] In Cloudflare dashboard → Pages → create a new project. Connect it to the GitHub repo (or plan to deploy via `wrangler pages deploy`).
- [ ] Decide the Pages subdomain (e.g. `screenshot-answers.pages.dev`) — you'll paste this into Cloud Run's `CORS_ORIGIN` env var.
- [ ] (Optional) Add a custom domain in Cloudflare if you want one.

---

## 5. After AI writes the code

- [ ] Review the generated code at a high level (don't need to read every line, but skim the agent prompts in the extractor + verifier — those drive quality).
- [ ] Run locally first:
  - [ ] `uv sync` in the backend dir, `uv run uvicorn app.main:app --reload`
  - [ ] `npm install && npm run dev` in the frontend dir
  - [ ] Drop in a test screenshot, confirm cards stream in.
- [ ] Deploy backend: `gcloud run deploy ...` (AI will give you the exact command). Copy the resulting Cloud Run URL.
- [ ] **Backend e2e verification (no frontend yet):** AI will run 3 curl tests against the deployed backend (`/health`, `POST /uploads`, SSE stream, `GET /uploads/{id}`) and confirm answers look right. Only proceed if these pass.
- [ ] Set `PUBLIC_API_BASE` on Cloudflare Pages to the Cloud Run URL. Tighten `CORS_ORIGIN` on Cloud Run from `*` to the Pages URL. Redeploy both.
- [ ] Smoke test the live site end-to-end.

---

## 6. Ongoing maintenance (yours forever)

- [ ] **Re-run `nlm login` every ~2 weeks** when NotebookLM auth fails — re-upload the new cookie file to the volume.
- [ ] Watch the **NotebookLM ~50 queries/day** free-tier limit. One upload = one query, so ~50 uploads/day max.
- [ ] If you want a different subject's source material: create another NotebookLM notebook, swap the `NOTEBOOK_ID` env var, redeploy.

---

## Decisions to make before AI starts coding

- [ ] Confirm Gemini model choices: vision model for extractor (`gemini-2.5-flash` or `gemini-2.5-pro`?), text model for verifier. Pro = better, Flash = cheaper/faster.
- [ ] Confirm volume strategy: GCS bucket via Cloud Storage volume mount, or a Cloud Run integrated volume? (GCS Fuse is the simpler default.)
- [ ] Confirm whether the frontend should live at the Pages default subdomain or a custom domain.
