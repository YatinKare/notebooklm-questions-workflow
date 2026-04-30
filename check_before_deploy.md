# Check Before Deploy

- Set `NLM_COOKIE_PATH` to the cookie JSON file path, not to individual cookie values.
- Local example: `NLM_COOKIE_PATH=~/.notebooklm-mcp-cli/profiles/default/cookies.json`
- Cloud Run current layout: mount/copy the whole NotebookLM MCP CLI storage directory into the bucket root, preserving `profiles/default/cookies.json` and `profiles/default/metadata.json`, then set `NLM_COOKIE_PATH=/mnt/data/profiles/default/cookies.json`.
- If only a standalone cookie JSON is mounted, the backend falls back to `NOTEBOOKLM_COOKIES`, but this can miss profile metadata such as CSRF/session/build labels and may fail even when `nlm doctor` passes locally.
- Do not commit `cookies.json`, `.env`, API keys, or NotebookLM cookie contents.
- If cookies were pasted or exposed, regenerate them with `nlm login` before deploying.
- Confirm `NOTEBOOK_ID`, `GOOGLE_API_KEY`, and Gemini model env vars are set before starting the backend.
- Before deploying, run `uvx --from notebooklm-mcp-cli nlm doctor` and confirm the target profile has cookies and a CSRF token.

## Review Additions

- Do not deploy until `/uploads`, `/events/{job_id}`, and orchestrator startup wiring are complete; the current app can start but cannot run an HTTP upload pipeline yet.
- Confirm the Cloud Run image has every runtime dependency needed by `notebooklm-mcp-cli`, including any browser/headless Chrome and OS libraries it requires. Avoid first-run browser or tool downloads in production startup.
- Prefer a pinned MCP executable in the image or set `NLM_MCP_COMMAND` explicitly. Do not rely on the `uvx --from notebooklm-mcp-cli ...` fallback in production because it can add startup latency, network dependency, and version drift.
- Re-check the SQLite storage plan before deploy. SQLite on object-storage/FUSE-style mounts can be fragile; if using a Cloud Storage volume anyway, keep `max-instances=1`, verify locking/write behavior under load, and be ready to move history to Cloud SQL/Firestore if corruption or latency appears.
- Keep Cloud Run `--min-instances=1` and `--max-instances=1`. The in-process queue and in-memory SSE bus are not safe across multiple instances.
- Make `/health` verify both SQLite read/write access and MCP liveness before using it as the deploy gate. A response body of `{"status":"degraded"}` should fail deployment checks even if the HTTP status is 200.
- Ensure SSE connections either replay current job state from SQLite on connect or otherwise tolerate missed in-memory events. Since upload creation happens before the browser opens `EventSource`, fast `question_extracted` or `stage_changed` events can be missed without a backfill.
- Confirm SSE does not close on `stage_changed: done`; the pipeline emits a separate `complete` event afterward, and clients should receive both before the connection terminates.
- Add upload guardrails before exposing the backend: validate image MIME by decoding with Pillow, cap upload size and pixel dimensions, and reject non-image files before enqueueing work.
- Cap extracted question count and verifier concurrency before deploy. The prompt asks for 3-5 questions, but production code should still enforce a hard limit to prevent accidental cost or latency spikes.
- Ensure the deployment script inspects the `/health` JSON and the e2e curl results, not just process exit or HTTP 200 status.
