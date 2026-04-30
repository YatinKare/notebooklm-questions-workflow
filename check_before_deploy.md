# Check Before Deploy

- Set `NLM_COOKIE_PATH` to the cookie JSON file path, not to individual cookie values.
- Local example: `NLM_COOKIE_PATH=/Users/yatink/.notebooklm-mcp-cli/profiles/default/cookies.json`
- Cloud Run example: `NLM_COOKIE_PATH=/mnt/data/nlm_cookies.json`
- Do not commit `cookies.json`, `.env`, API keys, or NotebookLM cookie contents.
- If cookies were pasted or exposed, regenerate them with `nlm login` before deploying.
- Confirm `NOTEBOOK_ID`, `GOOGLE_API_KEY`, and Gemini model env vars are set before starting the backend.
