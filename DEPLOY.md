# 🚀 NW Digital Operations Hub — Deployment Guide

Welcome! This guide explains step-by-step how to run and deploy the **NW Digital Operations Hub V3** on any machine, server, or cloud host (VPS, Railway, Render, Docker Host, Vercel, etc.).

---

## 📋 Prerequisites & Quick Overview

The platform consists of two main parts:
1. **Backend API Gateway (FastAPI / Python)**: Runs on port `8000`. Connects to PostgreSQL and Redis. Auto-seeds default database users and demo data on first startup!
2. **Frontend Dashboard (Next.js / React)**: Runs on port `3000`. Communicates with the Backend API.

All environment variables (including pre-configured API keys) are pre-set in `.env`.

---

## ⚡ Option A: Quick Local Testing (Recommended First Step)

### 1. Start Database & Caching (Docker)
```bash
docker compose up -d db redis
```

### 2. Run the Backend API (FastAPI)
```bash
# Create and activate Python virtual environment
python -m venv .venv
# On Windows PowerShell: .\.venv\Scripts\Activate.ps1
# On Linux/macOS: source .venv/bin/activate

pip install -r requirements.txt
alembic upgrade head
python -m uvicorn apps.core_gateway.main:app --host 0.0.0.0 --port 8000 --reload
```
*The backend auto-seeds initial users and data on startup!*
*Interactive API Swagger docs: [http://localhost:8000/docs](http://localhost:8000/docs)*

### 3. Run the Frontend Dashboard (Next.js)
In a second terminal:
```bash
npm install
npm run dev --workspace=apps/web
```
*Frontend will be live at [http://localhost:3000](http://localhost:3000)*

---

## 🐳 Option B: Full Docker Deployment (One-Command Deployment)

To deploy the **entire application** (Postgres + Redis + FastAPI Backend + Next.js Frontend) on any server or VPS with Docker installed:

```bash
# Extract the project on your server and navigate into the folder
cd nw-digital-ops-hub

# Build and start all 4 services in background mode
docker compose up -d --build
```

That's it!
- Frontend UI: `http://<YOUR-SERVER-IP>:3000`
- Backend API: `http://<YOUR-SERVER-IP>:8000`
- Database: PostgreSQL on port `5432`

---

## 🌐 Option C: Deployment Without Docker (Manual VPS / PaaS)

### 1. Database Setup
Set up a PostgreSQL instance (e.g. Supabase, Neon, AWS RDS, or local Postgres) and a Redis instance (e.g. Upstash or local Redis).
Update `DATABASE_URL` and `REDIS_URL` in `.env`.

### 2. Backend Deployment (FastAPI)
- **Install dependencies:** `pip install -r requirements.txt`
- **Run migrations:** `alembic upgrade head`
- **Start command:**
  ```bash
  uvicorn apps.core_gateway.main:app --host 0.0.0.0 --port 8000
  ```

### 3. Frontend Deployment (Vercel / Node VPS)
- **Environment variable to set in build settings:**
  `NEXT_PUBLIC_API_URL=https://your-backend-api-domain.com`
- **Build command:** `npm run build --workspace=apps/web`
- **Start command:** `npm run start --workspace=apps/web`

---

## 🔑 Important Environment Variables to Update for Production

Open `.env` (or set environment variables in your hosting provider's dashboard):

| Variable | Recommended Production Value | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `https://api.yourdomain.com` | Public URL of the backend API Gateway accessed by browser clients. |
| `CORS_ORIGINS` | `https://yourdomain.com` | Allowed frontend origin domains (use comma-separated list or `*`). |
| `JWT_SECRET` | Secret random string | Used to sign auth tokens. |
| `ENCRYPTION_KEY` | 32-byte Base64 Fernet key | Used to encrypt social account access tokens at rest. |
| `GROQ_API_KEY` | Your Groq Cloud GSK Key | Pre-configured in `.env` for AI caption generation. |
| `DATABASE_URL` | Postgres URL | Database connection string. |

---

## 🔑 Default Login Credentials (Pre-seeded)

> ⚠️ **Note (Sirf local dev / ALLOW_SEED=true)**: Below pre-seeded credentials are created on startup ONLY when `ALLOW_SEED=true`. In production environments (`ALLOW_SEED=false`), automatic database seeding is disabled and these default accounts will not be auto-generated.

| Role | Email | Password |
|---|---|---|
| Super Admin | `atif@nationalwireless.com` | `password` |
| Tenant Admin | `admin@nationalwireless.com` | `password` |
| Lead Designer | `designer@nationalwireless.com` | `password` |
| Client Rep | `client@acmewireless.com` | `password` |

---

## 📋 Live / Production Deployment Checklist

Before launching to live production, complete the following security and configuration steps:

- [ ] **Rotate Secrets**: Generate new random values for `JWT_SECRET`, `ENCRYPTION_KEY`, and `POSTGRES_PASSWORD`. Never reuse local development secrets.
- [ ] **Set `ALLOW_SEED=false`**: Ensure `ALLOW_SEED=false` in your production `.env` / container environment to disable auto-seeding and return `404 Not Found` for `POST /api/seed`.
- [ ] **Configure `CORS_ORIGINS`**: Replace `*` in `CORS_ORIGINS` with explicit allowed production domain origins (e.g. `https://app.yourdomain.com`).
- [ ] **Set `NEXT_PUBLIC_API_URL`**: Point `NEXT_PUBLIC_API_URL` to your live production backend URL (e.g. `https://api.yourdomain.com`).

---

## ⚠️ Known Limitations & Scope Notes

1. **Simulated Social Media Publishing**: `PublishingJob` workflow runs internal status transitions (`queued` → `processing` → `completed` / `manual_handoff`), but actual posting calls to Meta Graph API, TikTok, or LinkedIn are not integrated. Note: Simulated publish ke baad campaign 'published' tab hota hai jab job mein `platform_post_id` ya `manual_proof` ho (Rule 3).
2. **Polling-Based Messaging**: Client Rooms, Team Messenger, and Personal Direct Chat operate via REST endpoints + periodic polling (`refreshAllData`). WebSockets, live typing indicators, and real-time presence indicators are not enabled.
3. **Base64 File Storage**: Images and voice attachments are stored as Base64 Data URLs directly inside PostgreSQL text columns instead of external S3/MinIO bucket storage.
4. **Unavailable Advanced Analytics**: Complex metrics (lead scoring, SLA resolution hours, profitability) return an explicit `"unavailable"` status because background data stream processing is pending.
5. **Knowledge Base Article Management**: Knowledge Base articles can be created (`POST /api/kb-articles`) as drafts and approved (`POST /api/kb-articles/{id}/approve`) by admins, after which they are indexed for AI vector retrieval (`POST /api/support/retrieve`).
6. **One-Way Poster Approval Lock**: Media Asset approval (`status=approved`, `is_locked=True`) locks the poster version. Reverting an approved poster requires a direct database update.

---

## Hosting note
Netlify/Railway/Render configs hata di gayi hain. Deployment ab Docker Compose se hoti hai (FRIEND_DEPLOY_NOTES.md dekhein).


