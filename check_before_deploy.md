# Check Before Deploy

- Set `NLM_COOKIE_PATH` to the cookie JSON file path, not to individual cookie values.
- Local example: `NLM_COOKIE_PATH=/Users/yatink/.notebooklm-mcp-cli/profiles/default/cookies.json`
- Cloud Run recommended: mount/copy the whole NotebookLM MCP CLI storage directory, preserving `profiles/default/cookies.json` and `profiles/default/metadata.json`, then set `NLM_COOKIE_PATH=/mnt/data/.notebooklm-mcp-cli/profiles/default/cookies.json`.
- If only a standalone cookie JSON is mounted, the backend falls back to `NOTEBOOKLM_COOKIES`, but this can miss profile metadata such as CSRF/session/build labels and may fail even when `nlm doctor` passes locally.
- Do not commit `cookies.json`, `.env`, API keys, or NotebookLM cookie contents.
- If cookies were pasted or exposed, regenerate them with `nlm login` before deploying.
- Confirm `NOTEBOOK_ID`, `GOOGLE_API_KEY`, and Gemini model env vars are set before starting the backend.
- Before deploying, run `uvx --from notebooklm-mcp-cli nlm doctor` and confirm the target profile has cookies and a CSRF token.
