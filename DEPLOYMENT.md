# Production Deployment Runbook

This guide ensures a bug-free, zero-downtime production deployment for the **Resume Tailor** application under the `/resume_generator` sub-path.

---

## 1. Prerequisites

- **OS:** Ubuntu 22.04 LTS (Minimum 4 GB RAM required for the embedding model)
- **Software:** Docker, Docker Compose v2, Nginx, Certbot
- **Firewall:** Open ONLY ports `22` (SSH), `80` (HTTP), and `443` (HTTPS). **Do not expose Docker ports directly to the internet.**

---

## 2. Environment Configuration (`.env`)

Always copy `.env.example` to `.env` and fill in the missing values. 

> ⚠️ **CRITICAL:** `NEXT_PUBLIC_*` variables are baked into the Next.js bundle at compile time. Any changes require a full `docker compose up --build -d`.

```env
# --- LLM Provider ---
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_YOUR_API_KEY_HERE

# --- Production Sub-path Routing ---
# These are baked into Next.js at build time to serve the app under /resume_generator
NEXT_PUBLIC_API_URL=https://brollysolutions.in/resume_generator/api
NEXT_PUBLIC_BASE_PATH=/resume_generator
BACKEND_ROOT_PATH=/resume_generator/api

# --- CORS Security ---
# Ensure no trailing slash
CORS_ALLOWED_ORIGINS=https://brollysolutions.in

# --- Internal Database Credentials ---
POSTGRES_USER=postgres
POSTGRES_PASSWORD=secure_password_here
POSTGRES_DB=resumedb

# --- Performance Flags ---
CACHE_ENABLED=True
PRELOAD_EMBEDDING_MODEL=True
```

---

## 3. Build & Run Containers

Start the containers. The initial boot will take 10-20 minutes as it downloads PyTorch, SpaCy models, and the local HuggingFace embedding model.

```bash
# Pull latest code
git pull origin main

# Build and start in detached mode
docker compose up --build -d

# Monitor startup until "Application startup complete"
docker compose logs -f backend
```

### Health Checks
Run these locally on the server to verify container health before touching Nginx:
```bash
# Backend
curl http://127.0.0.1:8055/health

# Frontend
curl -I http://127.0.0.1:3055/resume_generator
```

---

## 4. Nginx Reverse Proxy (Zero Bugs Routing)

To serve the app under the `brollysolutions.in/resume_generator` sub-path without routing bugs, add these location blocks to your **existing** `brollysolutions.in` server block in Nginx.

> ⚠️ **CRITICAL ORDER:** The API block (`/resume_generator/api/`) MUST come before the frontend block (`/resume_generator`).

```nginx
# 1. API Block (FastAPI)
location /resume_generator/api/ {
    # Strip the prefix so FastAPI receives /api/... internally
    rewrite ^/resume_generator/api/(.*)$ /api/$1 break;

    proxy_pass http://127.0.0.1:8055;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # Allow large PDF/DOCX uploads
    client_max_body_size 20M;
    
    # LangGraph LLM tailoring takes 30-60s
    proxy_read_timeout 120s;
    proxy_send_timeout 120s;
}

# 2. Block Admin Dashboard from Public Access
location /resume_generator/api/admin/ {
    allow 127.0.0.1;
    deny all;
    rewrite ^/resume_generator/api/(.*)$ /api/$1 break;
    proxy_pass http://127.0.0.1:8055;
}

# 3. Frontend Block (Next.js)
location /resume_generator {
    proxy_pass http://127.0.0.1:3055;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}

# 4. Aggressive Cache for Static Assets
location /resume_generator/_next/static/ {
    proxy_pass http://127.0.0.1:3055;
    add_header Cache-Control "public, max-age=31536000, immutable";
}
```

Reload Nginx safely:
```bash
nginx -t && systemctl reload nginx
```

---

## 5. Data Backup Protocol

Docker volumes handle all persistence. The database, uploaded resumes, and cached AI weights are stored here:

- `qdrant_data`: All vector embeddings and JSON parsed resumes.
- `backend_uploads`: The original raw PDF/DOCX files.

Backup command (cron recommended):
```bash
docker run --rm -v resume-tailoring_qdrant_data:/data -v $(pwd):/backup alpine tar czf /backup/qdrant_$(date +%Y%m%d).tar.gz /data
docker run --rm -v resume-tailoring_backend_uploads:/data -v $(pwd):/backup alpine tar czf /backup/uploads_$(date +%Y%m%d).tar.gz /data
```

---

## 6. Troubleshooting Cheat Sheet

- **CORS Errors:** Verify `CORS_ALLOWED_ORIGINS` exactly matches the browser URL. No trailing slashes.
- **Wrong API Calls in Browser:** Re-verify `NEXT_PUBLIC_API_URL` in `.env` and run `docker compose up --build -d` (the variable is baked into the React bundle).
- **FastAPI /docs Empty:** Verify `BACKEND_ROOT_PATH` is set correctly so FastAPI knows it's behind a proxy.
- **504 Gateway Timeout:** Increase `proxy_read_timeout` in Nginx to `120s` or higher.
