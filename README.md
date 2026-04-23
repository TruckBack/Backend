# TruckBack Backend

Production-grade async FastAPI backend for a truck/delivery platform connecting customers and drivers.

## Tech Stack

- **Python 3.11+**, **FastAPI**, **Pydantic v2**
- **SQLAlchemy 2.0** async + **PostgreSQL**
- **Redis** (caching + pub/sub for WebSocket fan-out across workers)
- **JWT** auth (access + refresh tokens)
- **AWS S3** pre-signed uploads
- **Alembic** async migrations
- **Docker / docker-compose**

## Architecture

Clean layered architecture:

```
routers (HTTP/WS) -> services (business logic) -> repositories (data) -> models (ORM)
                                ^
                                |
                        schemas (Pydantic v2)
```

Fully async (`async`/`await` everywhere), DI via FastAPI `Depends`, environment-based config.

## Quick Start

```bash
cp .env.example .env
# edit SECRET_KEY (and AWS creds if you need real S3)

docker-compose up --build
# migrations run automatically via the api container's command
```

- API docs: http://localhost:8000/docs
- Health:   http://localhost:8000/health
- Base URL: http://localhost:8000/api/v1

### Local (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Postgres & Redis must be reachable per .env
alembic upgrade head
uvicorn app.main:app --reload
```

## Endpoints

All HTTP endpoints are mounted under `/api/v1`.

### Auth
- `POST /auth/register/customer`
- `POST /auth/register/driver`
- `POST /auth/login` (OAuth2 form: `username` = email)
- `POST /auth/login/json` (JSON body alternative)
- `POST /auth/refresh`

### Users
- `GET /users/me`
- `PUT /users/me`
- `GET /users/{user_id}`

### Drivers (driver role only)
- `PUT /drivers/me/profile`
- `PUT /drivers/me/status`
- `POST /drivers/me/location`

### Uploads
- `POST /uploads/image/profile` -> returns S3 pre-signed PUT URL

### Orders
- `POST /orders` (customer)
- `GET /orders/available`
- `GET /orders/history`
- `GET /orders/me/active`
- `GET /orders/{order_id}`
- `POST /orders/{order_id}/accept` (driver)
- `POST /orders/{order_id}/start` (driver)
- `POST /orders/{order_id}/pickup` (driver)
- `POST /orders/{order_id}/complete` (driver)
- `POST /orders/{order_id}/cancel`

### WebSocket
- `WS /api/v1/ws/orders/{order_id}/track?token=<access_token>`
  - Driver sends `{"type":"location","lat":..,"lng":..}`
  - Customer/driver receive `location` and `status` events
  - Multi-worker safe via Redis pub/sub fan-out

## Order State Machine

```
pending -> accepted -> in_progress -> picked_up -> completed
   \          \             \             \
    \--------- \------------ \------------ +--> cancelled
```

Transitions are enforced server-side; row-level locks (`SELECT ... FOR UPDATE`)
prevent two drivers from accepting the same order.

## Project Structure

```
Backend/
├── alembic/
│   ├── versions/0001_initial.py
│   ├── env.py
│   └── script.py.mako
├── alembic.ini
├── app/
│   ├── main.py
│   ├── core/        # config, security, exceptions, deps, redis, logging
│   ├── db/          # base + async session
│   ├── models/      # SQLAlchemy 2.0 ORM
│   ├── schemas/     # Pydantic v2
│   ├── repositories/
│   ├── services/    # business logic + ws manager
│   ├── routers/     # auth, users, drivers, uploads, orders, ws
│   └── utils/       # s3 helper
├── .env.example
├── .gitignore
├── .dockerignore
├── Dockerfile          # multi-stage, non-root user
├── docker-compose.yml  # api + postgres + redis
├── requirements.txt
└── pyproject.toml
```

## Notes

- No secrets are baked into the image — everything comes from env vars.
- Errors return a consistent JSON shape: `{"error":{"code":..,"message":..}}`.
- The driver-going-offline guard, active-order guard on accept, and FOR UPDATE
  lock cover the main race conditions.