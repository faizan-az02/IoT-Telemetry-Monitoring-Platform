# IoT Telemetry Monitoring Platform

A telemetry monitoring platform that:

- Collects **CPU / Memory / Disk % utilization** samples
- Stores them in **MongoDB**
- Displays them on a **Dashboard** and **Analytics** page
- Supports **Natural Language queries** on Analytics via **LangChain**

The system is designed to run in a portable way using **Docker Compose** for the web app + MongoDB, plus an optional **Windows host agent** to collect **host machine** metrics instead of container metrics.

---

## Key idea: Host metrics vs Docker metrics

When the web app runs in Docker, any code executed inside that container only “sees” the container.

To collect **host** CPU/Disk like Task Manager, run `host_agent.py` on the Windows host:

- The **web UI** triggers collection by calling the agent on `localhost:8765`
- The **agent writes samples into the same Docker MongoDB**, published on host port `27018`
- The UI reads everything from Mongo and shows a `collector` column:
  - `Host` = collected by host agent
  - `Docker` = collected inside container

---

## Data schema

Each telemetry document contains:

- `collector`: `"Host"` or `"Docker"`
- `cpu_usage (%)`: number
- `memory_usage (%)`: number
- `disk_usage (%)`: number
- `timestamp`: UTC datetime (stored as datetime in Mongo; API serializes to ISO `...Z`)
- `datetime_str`: local time string (legacy / display helper)

The UI sorts by `timestamp` - newest first.

---

## Prerequisites

- **Docker Desktop** (Windows) with Docker Compose
- **Python 3.10+** on Windows (only needed for `host_agent.py`)

For NL queries:

- A **GitHub Models** token, set in `.env.docker`.
- You can add any other API Key and then revise the code to read that from an env file.

---

## Quickstart (recommended)

### 1) Create `.env.docker`

Copy the example:

```bash
copy .env.example .env.docker
```

Edit `.env.docker` and set:

- `GITHUB_MODELS_TOKEN=...` (required only for NL queries)

Everything else can usually stay as-is for Docker Compose.

### 2) Start the host agent (recommended for real host metrics)

In a terminal on Windows (host), from repo root:

```bash
python host_agent.py
```

You should see it listening on `http://127.0.0.1:8765`.

### 3) Start Docker Compose

In another terminal (repo root):

```bash
docker compose up -d --build
```

Open the app:

- `http://localhost:5000`

---

## How to use the app

- **Dashboard** (`/dashboard`)
  - Shows latest samples + a table of most recent telemetry
  - Includes a `collector` column to distinguish Host vs Docker
- **Collect** (`/collect`)
  - Starts a collection job
  - If the host agent is reachable, collection runs on **Host**
  - Otherwise, it falls back to collecting inside the **Docker container**
- **Analytics** (`/analytics`)
  - Charts over recent data
  - NL query box to ask in plain English (requires GitHub Models token)
- **Admin** (`/admin`)
  - Shows DB stats and allows clearing the DB

---

## Ports

- **Web app (Flask via Waitress)**: `5000` → `http://localhost:5000`
- **Host agent**: `8765` → `http://127.0.0.1:8765`
- **MongoDB published for host agent access**: `27018` on host → container `27017`

---

## Common commands

### Start/stop

```bash
docker compose up -d --build
docker compose down
```

### View logs

```bash
docker compose logs -f web
docker compose logs -f mongo
```

## Repo layout

- `app.py`: Flask app (dashboard/analytics/admin + API endpoints)
- `telemetry.py`: telemetry sampling logic (Windows counters + psutil)
- `host_agent.py`: host-native collector service (recommended)
- `nl_query_langchain.py`: NL → safe MongoDB query planning (LangChain)
- `templates/`: Jinja HTML templates
- `static/`: JS + CSS assets
- `compose.yaml`: Docker Compose for web + mongo
- `Dockerfile`: web image build

---

## Security notes

- The host agent is intended for **local use** only (`127.0.0.1`) and should not be exposed publicly.
- Do **not** commit `.env.docker`, it contains secrets. Use `.env.example` as the template.