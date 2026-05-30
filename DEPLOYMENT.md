# Production Deployment Guide

## Prerequisites

- Docker + Docker Compose v2 on the host
- A Groq API key (free tier works) or OpenAI API key
- At least 2 GB RAM for the embedding model, 4 GB recommended
- Ports 3004 and 8004 open (or use a reverse proxy on 80/443)

---

## Step 1 — Environment Configuration

Copy and fill the env file **before** building:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# --- LLM (pick one) ---
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...

# --- Frontend URL (the public URL users will hit) ---
# This is BAKED INTO the Next.js build at compile time.
# Must be the URL your users' browsers can reach.
NEXT_PUBLIC_API_URL=https://api.yourdomain.com

# --- CORS ---
# Must include your frontend's public origin.
CORS_ALLOWED_ORIGINS=https://yourdomain.com

# --- Internal service addresses (Docker default — usually leave these alone) ---
QDRANT_HOST=qdrant
QDRANT_PORT=6333
REDIS_HOST=redis
REDIS_PORT=6379
```

> **`NEXT_PUBLIC_API_URL` is baked in at build time.** If you change it later, you must rebuild the frontend image. It is not an environment variable you can inject at runtime.

---

## Step 2 — Build and Start

```bash
docker compose up --build -d
```

What happens on first start:
1. Backend Dockerfile installs PyTorch (CPU), spaCy, WeasyPrint + system libs, all Python deps.
2. spaCy downloads `en_core_web_sm` during image build (`python -m spacy download en_core_web_sm`).
3. On container startup, `nomic-ai/nomic-embed-text-v1.5` (~270 MB) downloads from HuggingFace and is cached in the `hf_cache` Docker volume. This happens once; subsequent restarts load from cache instantly (5–10 s).
4. Qdrant auto-creates the three collections (`resumes`, `generated_projects`, `candidate_evidence`) on first use.

Expected startup log (backend):
```
Preloading embedding model...
Embedding model ready.
Application startup complete.
```

Verify health:
```bash
curl http://localhost:8004/health   # {"status":"ok"}
```

---

## Step 3 — Persistent Volumes

Docker Compose creates four named volumes automatically. **Do not delete them** — they hold all user data:

| Volume | Contents |
|--------|----------|
| `qdrant_data` | All resume vectors + payloads (primary data store) |
| `hf_cache` | Downloaded HuggingFace model weights |
| `backend_uploads` | Uploaded PDF/DOCX files |
| `postgres_data` | Postgres (currently unused but provisioned) |

Back up `qdrant_data` and `backend_uploads` regularly.

---

## Step 4 — Calibration Data

The `backend/data/` directory holds scoring weights, labels, and logs. In Docker, this is inside the container at `/app/data/` — **not in a named volume by default**, so it is lost on container replacement.

To persist it, add a bind mount to `docker-compose.yml`:

```yaml
backend:
  volumes:
    - hf_cache:/root/.cache/huggingface
    - backend_uploads:/app/uploads
    - ./backend/data:/app/data        # add this line
```

Key files inside `backend/data/`:

| File | Purpose |
|------|---------|
| `weights_active.json` | Live scoring weights (hot-reloaded by mtime) |
| `weights_history/` | Weight snapshots after each calibration run |
| `labels.jsonl` | Implicit labels derived from user suggestion acceptance |
| `upload_events.jsonl` | Upload events that trigger auto-calibration |
| `suggestion_events.jsonl` | Raw acceptance/rejection events |
| `score_log.jsonl` | Per-match scoring history |
| `section_score_log.jsonl` | Per-section scoring history |

If `weights_active.json` is missing, the scorer falls back to built-in defaults — the app still works, just with uncalibrated weights.

---

## Step 5 — Reverse Proxy (nginx or Caddy)

`NEXT_PUBLIC_API_URL` is baked into the frontend bundle, so the backend must be reachable at that exact URL from the user's browser.

Minimal nginx config:

```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;

    location / {
        proxy_pass http://localhost:3004;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

server {
    listen 443 ssl;
    server_name api.yourdomain.com;

    # Larger body for resume uploads
    client_max_body_size 20M;

    location / {
        proxy_pass http://localhost:8004;
        proxy_set_header Host $host;
        proxy_read_timeout 120s;   # LangGraph tailoring can take 30-60 s
    }
}
```

Important: set `proxy_read_timeout` to at least 120 s — the tailoring pipeline runs multiple LLM calls and can take 30–60 seconds.

---

## Step 6 — Admin Endpoint

`GET /api/admin/dashboard` serves a self-contained HTML calibration dashboard. It has **no auth gate** — block it at the proxy level if the API is public:

```nginx
location /api/admin/ {
    allow 10.0.0.0/8;   # internal only
    deny all;
    proxy_pass http://localhost:8004;
}
```

---

## Step 7 — Production Env Vars Checklist

```env
# Required
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...              # or OPENAI_API_KEY
NEXT_PUBLIC_API_URL=https://api.yourdomain.com
CORS_ALLOWED_ORIGINS=https://yourdomain.com

# Recommended in production
CACHE_ENABLED=True                 # Redis caches embeddings (30-day TTL)
PRELOAD_EMBEDDING_MODEL=True       # default; loads model at startup, not on first request

# Internal (Docker default — change only if your compose networking differs)
QDRANT_HOST=qdrant
QDRANT_PORT=6333
REDIS_HOST=redis
REDIS_PORT=6379
```

---

## Updating

```bash
git pull
docker compose up --build -d
```

The frontend bundle is rebuilt from scratch each time (includes the new `NEXT_PUBLIC_API_URL` bake). HuggingFace model cache is preserved in `hf_cache` volume so there is no re-download on update.

---

## Step 8 — CI/CD with GitHub Actions

The repository includes a GitHub Actions workflow in `.github/workflows/deploy.yml` that automates deployment to your DigitalOcean Droplet on every push to `main`.

### Required GitHub Secrets

To use the automated deployment, you must add the following secrets to your GitHub repository (**Settings > Secrets and variables > Actions**):

| Secret | Description | Example |
|--------|-------------|---------|
| `DO_HOST` | The IP address or hostname of your Droplet. | `123.456.78.90` |
| `DO_USERNAME` | The SSH user (usually `root` or a dedicated deploy user). | `root` |
| `DO_SSH_KEY` | The **private** SSH key used to access the Droplet. | `-----BEGIN OPENSSH PRIVATE KEY----- ...` |
| `DEPLOY_DIR` | The absolute path on the Droplet where the repo is cloned. | `/home/root/resume-tailoring` |

### Security Recommendation

It is recommended to use a dedicated SSH key for deployment and add the corresponding public key to `/root/.ssh/authorized_keys` on your Droplet.

---

## Troubleshooting

**Embedding model download hangs on first start**
The `hf_cache` volume is populated on first `up`. On a slow connection this can take several minutes. Watch logs with `docker compose logs -f backend`.

**"CORS policy" errors in browser**
`CORS_ALLOWED_ORIGINS` in `.env` must exactly match the origin in the browser's request (including scheme and port). Wildcard `*` is not supported.

**Tailoring requests time out**
Increase `proxy_read_timeout` on your reverse proxy (see Step 5). The LangGraph pipeline runs up to 2 critique loops × multiple LLM calls.

**Weights not updating after calibration**
`weights_active.json` must be writable inside the container. If using a bind mount (Step 4), ensure the host directory has write permissions for the container user.

**`/api/admin/calibration/run` returns empty results**
Auto-calibration requires at least 50 labels (`MIN_TOTAL_LABELS` in `auto_calibrator.py`). Upload a few resumes and accept/reject suggestions to generate labels first.
