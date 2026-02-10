from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from PIL import Image

from src.config import load_yaml
from src.data.mvtec import iter_mvtec_samples, load_image_rgb
from src.models.mean_diff import MeanDiffModel
from src.postproc.heatmap import normalize_heatmap
from src.postproc.mask import threshold_heatmap
from src.postproc.bboxes import mask_to_bboxes
from src.db import fetch_user_by_email
from src.auth import verify_password, get_session_secret


APP_CONFIG_PATH = os.environ.get("ANOMALY_CONFIG", "configs/base.yaml")


def _load_label_sets() -> dict:
    cfg = load_yaml(APP_CONFIG_PATH)
    return cfg.get("labels", {}).get("labels", {})


def _load_cfg() -> dict:
    return load_yaml(APP_CONFIG_PATH)


def _is_allowed_category(category: str) -> bool:
    label_sets = _load_label_sets()
    return category in label_sets


def _safe_name(name: str) -> str:
    keep = "".join([c for c in name if c.isalnum() or c in ("-", "_", ".")])
    return keep or "upload"


app = FastAPI(title="Anomaly Inspection API", version="0.1.0")
app.add_middleware(SessionMiddleware, secret_key=get_session_secret())


def _save_uint8(path: Path, arr: np.ndarray) -> None:
    img = Image.fromarray(arr.astype(np.uint8))
    img.save(path)


def _analyze_image(image_path: str, category: str, cfg: dict) -> dict:
    data_root = cfg["data"]["root"]
    artifacts_dir = Path(cfg["paths"]["artifacts"])
    heatmap_dir = artifacts_dir / "heatmaps"
    mask_dir = artifacts_dir / "masks"
    heatmap_dir.mkdir(parents=True, exist_ok=True)
    mask_dir.mkdir(parents=True, exist_ok=True)

    train_images = [
        load_image_rgb(s.image_path)
        for s in iter_mvtec_samples(data_root, category, "train")
        if s.label == "good"
    ]
    if not train_images:
        raise HTTPException(status_code=400, detail="No training images found for category.")

    model = MeanDiffModel()
    model.fit(train_images)

    image = load_image_rgb(image_path)
    score, heatmap = model.infer(image)
    heatmap_n = normalize_heatmap(heatmap, method=cfg["postproc"]["heatmap_normalize"])
    mask = threshold_heatmap(
        heatmap_n,
        method=cfg["postproc"]["threshold_method"],
        value=cfg["postproc"]["threshold_value"],
        percentile=cfg["postproc"]["threshold_percentile"],
    )
    bboxes = mask_to_bboxes(mask, min_area=cfg["postproc"]["min_area"])

    base = Path(image_path).stem
    heatmap_path = heatmap_dir / f"{base}_hm.png"
    mask_path = mask_dir / f"{base}_mask.png"
    _save_uint8(heatmap_path, (heatmap_n * 255.0).clip(0, 255))
    _save_uint8(mask_path, (mask * 255))

    image_decision = "anomalous" if score >= cfg["postproc"]["image_threshold"] else "normal"

    return {
        "image_decision": image_decision,
        "anomaly_score": float(score),
        "anomaly_heatmap_path": str(heatmap_path),
        "anomaly_mask_path": str(mask_path),
        "bboxes": bboxes,
    }


@app.get("/", response_class=HTMLResponse)
async def user_ui():
    label_sets = _load_label_sets()
    options = "\n".join([f"<option value='{c}'>{c}</option>" for c in sorted(label_sets.keys())])
    html = f"""
    <html>
      <head>
        <title>User Inspection UI</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 40px; }}
          .panel {{ max-width: 720px; }}
          label {{ display:block; margin-top: 12px; }}
          input, select, textarea {{ width: 100%; padding: 8px; }}
          button {{ margin-top: 12px; padding: 10px 16px; }}
          video, canvas {{ width: 100%; border: 1px solid #ddd; margin-top: 8px; }}
          pre {{ background: #f5f5f5; padding: 12px; }}
          .row {{ display:flex; gap: 12px; }}
          .row > div {{ flex: 1; }}
        </style>
      </head>
      <body>
        <div class="panel">
          <h2>User Camera Inspection</h2>
          <div class="row">
            <div>
              <label>Category</label>
              <select id="category">{options}</select>
              <label>Description</label>
              <textarea id="description" rows="3" placeholder="Describe the suspected anomaly"></textarea>
              <button id="startBtn">Start Camera</button>
              <button id="captureBtn">Capture & Analyze</button>
            </div>
            <div>
              <label>Live Camera</label>
              <video id="video" autoplay playsinline></video>
              <label>Captured Frame</label>
              <canvas id="canvas"></canvas>
            </div>
          </div>
          <h3>Result</h3>
          <pre id="result">No result yet.</pre>
        </div>
        <script>
          const video = document.getElementById('video');
          const canvas = document.getElementById('canvas');
          const startBtn = document.getElementById('startBtn');
          const captureBtn = document.getElementById('captureBtn');
          const resultEl = document.getElementById('result');

          let stream = null;

          startBtn.onclick = async () => {{
            try {{
              stream = await navigator.mediaDevices.getUserMedia({{ video: true }});
              video.srcObject = stream;
            }} catch (err) {{
              resultEl.textContent = 'Camera error: ' + err;
            }}
          }};

          captureBtn.onclick = async () => {{
            if (!stream) {{
              resultEl.textContent = 'Camera not started.';
              return;
            }}
            const w = video.videoWidth;
            const h = video.videoHeight;
            canvas.width = w;
            canvas.height = h;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0, w, h);

            const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
            if (!blob) {{
              resultEl.textContent = 'Capture failed.';
              return;
            }}

            const fd = new FormData();
            fd.append('category', document.getElementById('category').value);
            fd.append('description', document.getElementById('description').value || '');
            fd.append('file', blob, 'capture.png');

            const resp = await fetch('/analyze', {{
              method: 'POST',
              body: fd
            }});
            const text = await resp.text();
            resultEl.textContent = text;
          }};
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


def _require_admin(request: Request) -> bool:
    return bool(request.session.get("admin_user"))


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_form():
    html = """
    <html>
      <head>
        <title>Admin Login</title>
        <style>
          body { font-family: Arial, sans-serif; margin: 40px; }
          .panel { max-width: 420px; }
          label { display:block; margin-top: 12px; }
          input { width: 100%; padding: 8px; }
          button { margin-top: 16px; padding: 10px 16px; }
        </style>
      </head>
      <body>
        <div class="panel">
          <h2>Admin Login</h2>
          <form action="/admin/login" method="post">
            <label>Email</label>
            <input type="email" name="email" required />
            <label>Password</label>
            <input type="password" name="password" required />
            <button type="submit">Login</button>
          </form>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post("/admin/login")
async def admin_login(request: Request, email: str = Form(...), password: str = Form(...)):
    user = fetch_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        return HTMLResponse(
            "<p>Invalid credentials. <a href='/admin/login'>Try again</a></p>",
            status_code=401,
        )
    request.session["admin_user"] = user["email"]
    return RedirectResponse(url="/admin", status_code=302)


@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=302)


@app.get("/admin", response_class=HTMLResponse)
async def admin_ui(request: Request):
    if not _require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    label_sets = _load_label_sets()
    options = "\n".join([f"<option value='{c}'>{c}</option>" for c in sorted(label_sets.keys())])
    html = f"""
    <html>
      <head>
        <title>Anomaly Inspection Admin</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 40px; }}
          .panel {{ max-width: 640px; }}
          label {{ display:block; margin-top: 12px; }}
          input, select, textarea {{ width: 100%; padding: 8px; }}
          button {{ margin-top: 16px; padding: 10px 16px; }}
          pre {{ background: #f5f5f5; padding: 12px; }}
        </style>
      </head>
      <body>
        <div class="panel">
          <h2>Admin: Anomaly Detection</h2>
          <p><a href="/admin/logout">Logout</a></p>
          <form action="/analyze" method="post" enctype="multipart/form-data">
            <label>Category</label>
            <select name="category">{options}</select>
            <label>Description</label>
            <textarea name="description" rows="3" placeholder="Describe the suspected anomaly"></textarea>
            <label>Image</label>
            <input type="file" name="file" accept="image/*" />
            <button type="submit">Analyze</button>
          </form>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post("/upload")
async def upload_image(
    category: str = Form(...),
    description: str = Form(...),
    file: UploadFile = File(...),
):
    if not _is_allowed_category(category):
        raise HTTPException(status_code=400, detail="Invalid category.")

    uploads_dir = Path("artifacts/uploads")
    uploads_dir.mkdir(parents=True, exist_ok=True)

    ts = int(time.time())
    safe_name = _safe_name(file.filename or "image.png")
    out_name = f"{category}_{ts}_{safe_name}"
    out_path = uploads_dir / out_name

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")

    with open(out_path, "wb") as f:
        f.write(content)

    return JSONResponse(
        {
            "status": "ok",
            "category": category,
            "description": description,
            "filename": out_name,
            "path": str(out_path),
        }
    )


@app.post("/analyze", response_class=HTMLResponse)
async def analyze_image(
    category: str = Form(...),
    description: str = Form(...),
    file: UploadFile = File(...),
):
    if not _is_allowed_category(category):
        raise HTTPException(status_code=400, detail="Invalid category.")

    uploads_dir = Path("artifacts/uploads")
    uploads_dir.mkdir(parents=True, exist_ok=True)

    ts = int(time.time())
    safe_name = _safe_name(file.filename or "image.png")
    out_name = f"{category}_{ts}_{safe_name}"
    out_path = uploads_dir / out_name

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")

    with open(out_path, "wb") as f:
        f.write(content)

    cfg = _load_cfg()
    result = _analyze_image(str(out_path), category, cfg)

    html = f"""
    <html>
      <head><title>Result</title></head>
      <body style="font-family: Arial, sans-serif; margin: 40px;">
        <h2>Result</h2>
        <p><strong>Category:</strong> {category}</p>
        <p><strong>Description:</strong> {description}</p>
        <pre>{result}</pre>
        <p><a href="/">Back</a></p>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
