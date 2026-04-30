# notebooklm-questions-workflow

Drop a screenshot of exam questions, get back graded answer cards with reasoning, powered by a NotebookLM that has the source material loaded.

## Quickstart (local)

```bash
# Backend
cd backend
cp .env.example .env   # fill in real values
uv sync
uv run uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend
cp .env.example .env   # set PUBLIC_API_BASE=http://localhost:8000
npm install
npm run dev
```

## Deploy

See `infra/deploy-backend.sh` and `infra/deploy-frontend.sh`.

Complete setup instructions (account creation, secrets, Cloudflare) live in `user_plan.md`.
