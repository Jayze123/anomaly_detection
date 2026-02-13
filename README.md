# Anomaly Detection (FastAPI + NiceGUI + PostgreSQL)

End-to-end visual inspection demo system with:
- JWT auth (`ADMIN` and `USER` RBAC)
- Admin module: factories, users, products, product statuses, status images
- User module: camera scan workflow, trigger-based capture, deterministic inference, history
- PostgreSQL with SQLAlchemy 2.0 + Alembic migration
- Image storage under `/data/...`
- Pytest coverage for auth, RBAC, image-limit, scan flow

## 1. Project Tree

```text
anomaly_detection/
  app/
    main.py
    core/
      config.py
      security.py
      logging.py
    db/
      base.py
      session.py
      models.py
      crud.py
      seed.py
      migrations/
        alembic.ini
        env.py
        script.py.mako
        versions/
          0001_initial.py
    api/
      deps.py
      auth.py
      admin.py
      user.py
    services/
      storage.py
      camera.py
      inference.py
  ui/
    app_ui.py
    auth_ui.py
    admin_ui.py
    user_ui.py
    components.py
  tests/
    conftest.py
    test_auth.py
    test_rbac.py
    test_images_limit.py
    test_scan_flow.py
  docker-compose.yml
  Dockerfile
  pyproject.toml
  README.md
  .env.example
```

## 2. Local Run (Docker Compose + Alembic + App)

### Prerequisites
- Docker + Docker Compose
- Python 3.11+

### Steps
1. `cd anomaly_detection`
2. `cp .env.example .env`
3. `docker compose up -d db`
4. `python -m venv .venv && source .venv/bin/activate`
5. `pip install -e .`
6. `alembic -c app/db/migrations/alembic.ini upgrade head`
7. `python -m app.main`

App runs at `http://localhost:8080`.

## 3. Seeded Accounts

- Admin:
  - Email: `admin@local`
  - Password: `admin123`
- User:
  - Email: `user@local`
  - Password: `user123`

Seed logic runs on startup and creates:
- Default factory
- Default product category and product
- Base statuses: `NORMAL`, `SCRATCH`, `DENT`, `MISALIGNMENT`

## 4. API Summary

### Auth
- `POST /auth/login`
- `GET /auth/me`

### Admin (`ADMIN` only)
- Factories: `GET/POST/PUT/DELETE /admin/factories...`
- Users: `GET/POST/PUT/DELETE /admin/users...`
- Products: `GET/POST/PUT/DELETE /admin/products...`, `GET /admin/products/{id}`
- Product statuses:
  - `GET /admin/products/{id}/statuses`
  - `POST /admin/products/{id}/statuses`
  - `PUT /admin/statuses/{status_id}`
  - `DELETE /admin/statuses/{status_id}`
- Status images:
  - `POST /admin/statuses/{status_id}/images`
  - `POST /admin/statuses/{status_id}/images/reorder`
  - `DELETE /admin/status-images/{image_id}`

### User (`USER` only)
- `GET /user/products`
- `POST /user/scans`
- `GET /user/scans`
- `GET /user/scans/{id}`

## 5. NiceGUI Routes

- `/login`
- `/admin/dashboard`
- `/admin/factories`
- `/admin/users`
- `/admin/products`
- `/admin/products/{id}`
- `/user/scan`

RBAC UI guard:
- Admin is redirected to `/admin/dashboard`
- User is redirected to `/user/scan`
- Invalid/expired token redirects to `/login` with toast

## 6. Camera Trigger + Inference

### Trigger flow (`app/services/camera.py`)
- Uses OpenCV `VideoCapture`
- Optional ROI from env: `ROI=x,y,w,h`
- Foreground extraction via `BackgroundSubtractorMOG2`
- Motion ratio threshold (`TRIGGER_THRESHOLD`)
- Debounce window (`DEBOUNCE_MS`)
- Callbacks:
  - `on_frame(frame)` for live preview
  - `on_capture(frame)` only when trigger condition passes

### Inference stub (`app/services/inference.py`)
- Deterministic heuristic using:
  - Grayscale mean brightness
  - Laplacian variance
- Outputs `(predicted_status, confidence, is_defect)`
- Status mapping:
  - `NORMAL` / `SCRATCH` / `DENT` / `MISALIGNMENT`

## 7. Storage

- Root: `STORAGE_ROOT` (default `./data`)
- Product status images: `/data/status_images/<status_id>/<uuid>.(jpg|png)`
- Scan images: `/data/scan_images/...`
- Upload validation:
  - Types: `jpg/jpeg/png`
  - Max size: `5MB`
- Files are served via mounted static route: `/data`

## 8. Run Tests

From `anomaly_detection/`:

```bash
pytest
```

Included tests:
- `tests/test_auth.py`
- `tests/test_rbac.py`
- `tests/test_images_limit.py`
- `tests/test_scan_flow.py`

## 9. Demo Walkthrough

1. Login as admin (`admin@local/admin123`).
2. Open `/admin/products`, create/edit/delete products.
3. Open product detail (`/admin/products/{id}`), add statuses and upload up to 4 images.
4. Login as user (`user@local/user123`).
5. Open `/user/scan`, select product, click Start.
6. Show live preview and wait for conveyor motion trigger capture.
7. Observe immediate result panel updates and counters.
8. Open History tab, filter results, and view image details.
