# NW Digital Operations Hub V3 - Platform Core & Gateway

Welcome to the central monorepo for the **NW Digital Operations Hub V3**. This platform serves as the core API Gateway, database interface, and frontend workspace. 

This repository has been structured by **Zeenat Yousef (Full-Stack, Integration and Deployment Lead)** to facilitate concurrent development for all four interns (Zeenat, Vishaqa, Asma, and Esha).

---

## 1. Project Architecture & Monorepo Structure

The workspace uses a monorepo pattern with Node.js/npm Workspaces for JavaScript and structured Python paths for FastAPI apps:

```
/nw-digital-ops-hub
  ├── /apps
  │     ├── /web                # Next.js React Frontend (Zeenat's focus)
  │     ├── /core_gateway       # Core API Gateway (FastAPI)
  │     ├── /vishaqa-service    # Vishaqa's FastAPI AI Marketing API (Folder scaffold)
  │     ├── /asma-service       # Asma's FastAPI Service (Folder scaffold)
  │     └── /esha-service       # Esha's FastAPI Service (Folder scaffold)
  ├── /packages
  │     ├── /database           # Shared Database Models, Connections, and Alembic Migrations
  │     └── /shared_dtos        # Shared Pydantic Schemas and Enums
  ├── .env.example              # Template environment file
  ├── docker-compose.yml        # Shared Postgres & Redis container setups
  ├── package.json              # NPM workspace settings
  ├── pyproject.toml            # Code linting/formatting standards (Black, Isort)
  ├── requirements.txt          # Shared Python dependencies
  └── verify_setup.ps1          # Verification script for local workspace run
```

---

## 2. Shared Database Models (ERD)
The backend utilizes PostgreSQL partitioned by `tenant_id` for security. The tables managed by this gateway include:
1. **tenants / users / roles**: Core identity authentication.
2. **clients / client_rooms**: Support and client communications.
3. **messages**: Internal/external split messenger system.
4. **campaigns / content_versions**: Marketing automation.
5. **publishing_jobs**: Celery/Redis social media scheduler.
6. **audit_events / notifications**: Append-only compliance log.

---

## 3. Quick Local Setup (For All 4 Interns)

Follow these steps to run the complete platform core locally on your machine:

### Step A: Clone & Environment Variable Setup
1. Copy `.env.example` file and rename it to `.env`:
   ```bash
   cp .env.example .env
   ```

### Step B: Database & Cache Setup (Docker)
1. Ensure your Docker Desktop daemon is active.
2. Start the database (PostgreSQL) and caching (Redis) services:
   ```bash
   docker-compose up -d
   ```
   *Note: If Docker is not available on your system, you can update `DATABASE_URL` in `.env` to point to a local PostgreSQL instance or a SQLite file for testing (e.g. `sqlite:///temp.db`).*

### Step C: Python Backend Setup
1. Create a Python Virtual Environment:
   ```bash
   python -m venv .venv
   ```
2. Activate the Virtual Environment:
   - **Windows PowerShell:** `.\.venv\Scripts\Activate.ps1`
   - **macOS/Linux:** `source .venv/bin/activate`
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the database migrations (Alembic):
   ```bash
   alembic upgrade head
   ```

### Step D: Frontend Javascript Setup
1. Install Node.js dependencies at the root workspace:
   ```bash
   npm install
   ```

---

## 4. How to Run the Applications Locally

You can launch the Gateway API and Frontend UI simultaneously:

### Run Backend API Gateway:
From the root workspace, run:
```bash
python -m uvicorn apps.core_gateway.main:app --port 8000 --reload
```
- Core gateway API will be live on: [http://localhost:8000](http://localhost:8000)
- Swagger interactive API docs will be live on: [http://localhost:8000/docs](http://localhost:8000/docs)

### Run Next.js Frontend Dashboard:
From the root workspace, run:
```bash
npm run dev --workspace=apps/web -- --port 3000
```
- Dashboard panel will be live on: [http://localhost:3000](http://localhost:3000)

---

## 5. Local Setup Verification Script

To make sure everything is installed correctly, a PowerShell script is provided. Run the following command at the root workspace:

```powershell
powershell -ExecutionPolicy Bypass -File .\verify_setup.ps1
```

It checks:
- Python `.venv` health and core library imports (`fastapi`, `sqlalchemy`, `alembic`, `redis`).
- Next.js workspace structure.
- Existence of database migration revisions.
- Local `.env` existence.
