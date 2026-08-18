"""
BS BioShifting — Unified Age-Progression & Face Verification Server
=============================================================
Full pipeline: Legacy ID Scan → Live Frame FQA → AIFR Pipeline
             → Similarity Score → Threshold Routing → Admin Queue

Runs 100 % locally with SQLite. One command:
    python server.py
    → http://127.0.0.1:5000
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import uuid
import io
import threading
import traceback
from datetime import datetime
from pathlib import Path
from math import atan2, degrees

import cv2
import numpy as np
from flask import (
    Flask, render_template, request, jsonify, send_from_directory,
)
from PIL import Image, ImageOps
import torch

import database

# ─── Paths ────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
IMAGE_DIR = BASE_DIR / "image_folder"
IMAGE_DIR.mkdir(exist_ok=True)

# ─── Flask app ────────────────────────────────────────────────
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB
app.config["TEMPLATES_AUTO_RELOAD"] = True

# ─── Database ─────────────────────────────────────────────────
database.init_db()

# ─── Load SAM (age-progression) ───────────────────────────────
model_loaded = False
try:
    import sam_wrapper
    sam_model = sam_wrapper.get_sam_wrapper()
    model_loaded = True
    print("  [OK] SAM model loaded")
except Exception as exc:
    print(f"  [X] Model load failed: {exc}")

# ─── Load InsightFace (face verification) ─────────────────────
insightface_ok = False
face_app = None
try:
    from insightface.app import FaceAnalysis
    face_app = FaceAnalysis(
        name="buffalo_l",
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    face_app.prepare(ctx_id=0 if torch.cuda.is_available() else -1, det_size=(640, 640))
    insightface_ok = True
    print("  [OK] InsightFace (buffalo_l) loaded")
except Exception as exc:
    print(f"  [!] InsightFace not available: {exc}")

# ─── Load DEX age classifier (age estimation) ─────────────────
# InsightFace's bundled genderage head is not a usable age estimator (it never
# predicted below 24 on this project's own photos, scoring childhood ID photos
# at ~30). DEX predicts over 101 age classes and handles children correctly.
age_model_ok = False
age_model = None
try:
    import age_estimator
    age_model = age_estimator.get_age_estimator()
    age_model_ok = True
    print("  [OK] DEX age classifier loaded")
except FileNotFoundError:
    print("  [!] DEX age classifier weights missing — age estimation disabled.")
    print("      Download: python -c \"import gdown; gdown.download("
          "id='1atzjZm_dJrCmFWCqWlyspSpr3nI6Evsh', "
          "output='SAM/pretrained_models/dex_age_classifier.pth')\"")
except Exception as exc:
    print(f"  [!] DEX age classifier failed to load: {exc}")

# ─── Load MediaPipe Face Landmarker (FQA) ─────────────────────
fqa_ok = False
landmarker = None
landmarker_lock = threading.Lock()

try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision as mp_vision

    _mp_model = BASE_DIR / "face_reaging" / "face_landmarker.task"
    if _mp_model.exists():
        _opts = mp_vision.FaceLandmarkerOptions(
            base_options=mp_tasks.BaseOptions(model_asset_path=str(_mp_model)),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_faces=2,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
        )
        landmarker = mp_vision.FaceLandmarker.create_from_options(_opts)
        fqa_ok = True
        print("  [OK] MediaPipe FQA loaded")
    else:
        print("  [!] face_landmarker.task not found — FQA disabled")
except ImportError:
    print("  [!] mediapipe not installed — FQA disabled")
except Exception as exc:
    # A corrupt .task file or a mediapipe version mismatch must not take the
    # whole server down — FQA is optional, every other model block degrades.
    print(f"  [!] MediaPipe FQA failed to load: {exc}")

# FQA config
FQA_CFG = {
    "light_mean_min": 60,   "light_mean_max": 195,
    "light_blown_max": 0.06, "light_dark_max": 0.30,
    "blur_min_var": 25.0,
    "roll_max_deg": 10.0,
    "yaw_ratio_min": 0.35,  "yaw_ratio_max": 0.65,
    "pitch_ratio_min": 0.30, "pitch_ratio_max": 0.62,
    "eye_center_x_min": 0.33, "eye_center_x_max": 0.67,
    "eye_center_y_min": 0.25, "eye_center_y_max": 0.55,
    "face_width_min": 0.22,  "face_width_max": 0.75,
}
L_EYE, R_EYE = 33, 263
NOSE_TIP, CHIN = 1, 152
L_CHEEK, R_CHEEK = 234, 454


# ==============================================================
# FQA helpers
# ==============================================================
def _fqa_lighting(gray):
    mn = float(gray.mean())
    blown = float((gray > 245).mean())
    dark = float((gray < 25).mean())
    if mn < FQA_CFG["light_mean_min"] or dark > FQA_CFG["light_dark_max"]:
        return {"pass": False, "msg": "Too dark — face a light source"}
    if mn > FQA_CFG["light_mean_max"] or blown > FQA_CFG["light_blown_max"]:
        return {"pass": False, "msg": "Too bright — reduce direct light"}
    return {"pass": True, "msg": "Lighting OK"}


def _fqa_blur(gray):
    h, w = gray.shape
    sc = 256.0 / max(1, w)
    resized = cv2.resize(gray, (256, max(1, int(h * sc))))
    var = float(cv2.Laplacian(resized, cv2.CV_64F).var())
    ok = var >= FQA_CFG["blur_min_var"]
    return {"pass": ok, "msg": "Sharpness OK" if ok else "Image is blurry — hold still", "var": round(var, 1)}


def _fqa_pose(pts):
    le, re = pts[L_EYE], pts[R_EYE]
    nose, chin = pts[NOSE_TIP], pts[CHIN]
    lch, rch = pts[L_CHEEK], pts[R_CHEEK]
    roll = degrees(atan2(re[1] - le[1], re[0] - le[0]))
    yaw_r = (nose[0] - lch[0]) / max(1e-6, rch[0] - lch[0])
    eye_mid = (le + re) / 2.0
    pitch_r = (nose[1] - eye_mid[1]) / max(1e-6, chin[1] - eye_mid[1])
    res = {"pass": True, "msg": "Head pose OK"}
    if abs(roll) > FQA_CFG["roll_max_deg"]:
        res = {"pass": False, "msg": "Straighten your head — remove the tilt"}
    elif not (FQA_CFG["yaw_ratio_min"] <= yaw_r <= FQA_CFG["yaw_ratio_max"]):
        res = {"pass": False, "msg": "Face the camera straight on"}
    elif pitch_r < FQA_CFG["pitch_ratio_min"]:
        res = {"pass": False, "msg": "Lower your chin slightly"}
    elif pitch_r > FQA_CFG["pitch_ratio_max"]:
        res = {"pass": False, "msg": "Raise your chin slightly"}
    res.update(roll_deg=round(float(roll), 1), yaw_ratio=round(float(yaw_r), 2),
               pitch_ratio=round(float(pitch_r), 2))
    return res


def _fqa_eye(pts, fw, fh, face_frac):
    le, re = pts[L_EYE], pts[R_EYE]
    ex, ey = ((le + re) / 2.0)[0] / fw, ((le + re) / 2.0)[1] / fh
    if face_frac < FQA_CFG["face_width_min"]:
        return {"pass": False, "msg": "Move closer to the camera"}
    if face_frac > FQA_CFG["face_width_max"]:
        return {"pass": False, "msg": "Move back from the camera"}
    if not (FQA_CFG["eye_center_x_min"] <= ex <= FQA_CFG["eye_center_x_max"]) or \
       not (FQA_CFG["eye_center_y_min"] <= ey <= FQA_CFG["eye_center_y_max"]):
        return {"pass": False, "msg": "Center your face in the guide"}
    return {"pass": True, "msg": "Eyes level and centered"}


def run_fqa(img_bgr):
    """Full FQA analysis on a BGR image. Returns dict."""
    fh, fw = img_bgr.shape[:2]
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    with landmarker_lock:
        res = landmarker.detect(mp_img)
    faces = res.face_landmarks or []
    if len(faces) == 0:
        g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        hint = " (frame looks very dark)" if g.mean() < 45 else ""
        return {"face_count": 0, "checks": {}, "overall": False,
                "msg": "No face detected — center your face" + hint}
    if len(faces) > 1:
        return {"face_count": len(faces), "checks": {}, "overall": False,
                "msg": "Multiple faces — only one person in frame"}
    lm = faces[0]
    pts = np.array([[p.x * fw, p.y * fh] for p in lm], dtype=np.float32)
    x0, y0 = pts[:, 0].min(), pts[:, 1].min()
    x1, y1 = pts[:, 0].max(), pts[:, 1].max()
    pad = 0.08 * max(x1 - x0, y1 - y0)
    # MediaPipe returns normalised coords that can fall outside [0,1] when the
    # face is partly out of frame, which would otherwise produce an empty crop
    # and blow up cv2 further down. Clamp so the box is always at least 1px.
    xa, ya = max(0, min(fw - 1, int(x0 - pad))), max(0, min(fh - 1, int(y0 - pad)))
    xb, yb = max(xa + 1, min(fw, int(x1 + pad))), max(ya + 1, min(fh, int(y1 + pad)))
    gray = cv2.cvtColor(img_bgr[ya:yb, xa:xb], cv2.COLOR_BGR2GRAY)
    face_w = (x1 - x0) / fw
    checks = {
        "light": _fqa_lighting(gray),
        "blur": _fqa_blur(gray),
        "pose": _fqa_pose(pts),
        "eye": _fqa_eye(pts, fw, fh, face_w),
    }

    # Calculate a square crop box for frontend auto-zooming
    w_face = x1 - x0
    h_face = y1 - y0
    size = max(w_face, h_face) * 1.8  # 80% padding for a nice portrait crop
    half = size / 2.0
    cx, cy = x0 + w_face / 2.0, y0 + h_face / 2.0

    crop_x = max(0, int(cx - half))
    crop_y = max(0, int(cy - half))
    crop_size = min(int(size), fw - crop_x, fh - crop_y)

    overall = all(c["pass"] for c in checks.values())
    first_fail = next((c["msg"] for c in checks.values() if not c["pass"]), None)
    return {"face_count": 1, "checks": checks, "overall": overall,
            "msg": "Frame quality OK — ready to capture" if overall else first_fail,
            "face_box": [crop_x, crop_y, crop_size, crop_size]}


# ==============================================================
# Helpers
# ==============================================================
def _form_int(name, default):
    """Read an integer form field, falling back to default for blank or
    non-numeric input rather than raising into the generic 500 handler."""
    try:
        return int(float((request.form.get(name) or "").strip()))
    except ValueError:
        return default


def build_image_path(kind, *, scan_id=None, index=None, submission_id=None,
                     filename=None, ext="jpg"):
    """Single source of truth for where every image this app writes lives.

    Layout:
        image_folder/<scan_id>/legacy/legacy_00.jpg        kind="legacy"
        image_folder/<scan_id>/current/current_00.jpg      kind="current"
        image_folder/<scan_id>/generated/generated_00.jpg  kind="generated"
        image_folder/age_estimation/<ts>_<uid>.jpg         kind="age_estimation"
        image_folder/training/<submission_id>/<name>       kind="training"

    The index in generated_NN.jpg always matches the legacy_NN.jpg it was
    produced from. Parent directories are created on demand.

    Returns (abs_path: Path, url: str).
    """
    if kind in ("legacy", "current", "generated"):
        if scan_id is None or index is None:
            raise ValueError(f"kind={kind!r} requires scan_id and index")
        directory = IMAGE_DIR / str(scan_id) / kind
        name = filename or f"{kind}_{index:02d}.{ext}"
    elif kind == "age_estimation":
        directory = IMAGE_DIR / "age_estimation"
        name = filename or f"{datetime.now():%Y%m%d-%H%M%S}_{uuid.uuid4().hex[:8]}.{ext}"
    elif kind == "training":
        if submission_id is None or not filename:
            raise ValueError("kind='training' requires submission_id and filename")
        directory = IMAGE_DIR / "training" / str(submission_id)
        name = filename
    else:
        raise ValueError(f"Unknown output kind: {kind!r}")

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    return path, _path_to_url(path)


def _save_upload(file_storage, dest_path):
    """Save an uploaded file to dest_path (from build_image_path) and return
    (abs_path, url_path, pil_image).
    Applies EXIF-orientation correction so photos taken on phones (which
    store rotation as metadata rather than rotating the pixels) are saved
    upright — otherwise face alignment/detection sees a sideways photo."""
    img = Image.open(file_storage.stream)
    img = (ImageOps.exif_transpose(img) or img).convert("RGB")
    img.save(str(dest_path), quality=92)
    return str(Path(dest_path).resolve()), _path_to_url(dest_path), img


def _path_to_url(abspath):
    """Map an on-disk image path to its /image_folder/... URL, preserving the
    subfolder structure. Falls back to the bare filename for legacy rows
    that still point at the old flat layout."""
    if not abspath:
        return None
    p = Path(abspath)
    try:
        rel = p.resolve().relative_to(IMAGE_DIR.resolve())
    except (ValueError, OSError):
        return f"/image_folder/{p.name}"
    return "/image_folder/" + rel.as_posix()


def _scan_to_json(scan):
    """Add URL fields to a scan dict for the frontend."""
    scan["legacy_photo_url"] = _path_to_url(scan.get("legacy_photo"))
    scan["live_photo_url"] = _path_to_url(scan.get("live_photo"))
    scan["generated_photo_url"] = _path_to_url(scan.get("generated_photo"))
    return scan


# ==============================================================
# PAGE ROUTES
# ==============================================================
@app.route("/")
def index():
    return render_template("login.html")

@app.route("/home")
def home_page():
    return render_template("home.html")

@app.route("/scan")
def scan_page():
    return render_template("scan.html")

@app.route("/age-estimator")
def age_estimator_page():
    return render_template("age-estimator.html")

@app.route("/admin-login")
def admin_login_page():
    return render_template("admin-login.html")

@app.route("/admin")
def admin_page():
    return render_template("admin.html")

@app.route("/image_folder/<path:filename>")
def serve_image(filename):
    return send_from_directory(str(IMAGE_DIR), filename)


@app.errorhandler(413)
def handle_too_large(_err):
    """Flask's default 413 is an HTML page, which the fetch() handlers in the
    frontend cannot parse — they all expect JSON."""
    return jsonify({"error": "Upload too large — the limit is 32 MB per request"}), 413


# ==============================================================
# API — STATUS
# ==============================================================
@app.route("/api/status")
def api_status():
    return jsonify({
        "model_loaded": model_loaded,
        "insightface": insightface_ok,
        "age_model": age_model_ok,
        "age_calibrated": bool(age_model_ok and age_model.calibrated),
        "fqa": fqa_ok,
        "device": "cuda" if torch.cuda.is_available() else "cpu",
    })


# ==============================================================
# API — FQA
# ==============================================================
@app.route("/api/fqa", methods=["POST"])
def api_fqa():
    if not fqa_ok:
        return jsonify({"overall": True, "msg": "FQA unavailable — skipping checks",
                        "checks": {}, "face_count": 1})
    if "frame" not in request.files:
        return jsonify({"overall": False, "msg": "No frame"}), 400
    data = request.files["frame"].read()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return jsonify({"overall": False, "msg": "Could not decode image"}), 400
    try:
        return jsonify(run_fqa(img))
    except Exception as exc:
        # This runs on every live preview frame — a bad frame must not break
        # the polling loop, so report it as a failed check, not an HTTP error.
        print(f"  FQA error on frame (non-fatal): {exc}")
        return jsonify({"face_count": 0, "checks": {}, "overall": False,
                        "msg": "Could not analyse this frame — hold still"})


# ==============================================================
# API — AGE ESTIMATOR (standalone, home-page feature)
# ==============================================================
@app.route("/api/estimate-age", methods=["POST"])
def api_estimate_age():
    """Estimate the age of every face in a photo.

    InsightFace does the detection (it is good at that); the age itself comes
    from the DEX VGG classifier, which predicts a distribution over ages 0-100
    and takes its expectation. The genderage head bundled with buffalo_l is
    deliberately NOT used for the number — it could not distinguish this
    project's childhood ID photos from present-day adult captures.
    """
    if not insightface_ok:
        return jsonify({"error": "Face analysis is not available"}), 503
    if not age_model_ok:
        return jsonify({"error": "Age model unavailable — the DEX age classifier "
                                 "weights are missing on the server"}), 503
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400
    data = request.files["image"].read()
    try:
        pil_img = Image.open(io.BytesIO(data))
        pil_img = (ImageOps.exif_transpose(pil_img) or pil_img).convert("RGB")
    except Exception:
        return jsonify({"error": "Could not decode image"}), 400

    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    faces = face_app.get(img)
    if not faces:
        return jsonify({"error": "No face detected in the photo"}), 400

    # Largest face first — that's the subject; the rest are bystanders.
    faces = sorted(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
                   reverse=True)

    annotated = img.copy()
    scale = max(1.0, min(annotated.shape[:2]) / 500.0)
    thick = max(1, int(2 * scale))
    results = []

    for i, face in enumerate(faces):
        out = age_model.predict_from_face(img, face.bbox)
        if out is None:
            continue
        age_f, raw_f, confidence = out
        age = int(round(age_f))
        results.append({
            "age": age,
            "age_precise": round(age_f, 1),
            "age_raw": round(raw_f, 1),
            "confidence": round(confidence, 3),
            "is_primary": i == 0,
        })

        colour = (246, 130, 59) if i == 0 else (150, 150, 150)
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        cv2.rectangle(annotated, (x1, y1), (x2, y2), colour, thick)
        label = f"Age ~{age}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7 * scale, thick)
        ly = max(th + 4, y1 - 6)
        cv2.rectangle(annotated, (x1, ly - th - 6), (x1 + tw + 8, ly + 4), colour, -1)
        cv2.putText(annotated, label, (x1 + 4, ly), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7 * scale, (255, 255, 255), thick, cv2.LINE_AA)

    if not results:
        return jsonify({"error": "No face detected in the photo"}), 400

    dest, url = build_image_path("age_estimation")
    cv2.imwrite(str(dest), annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 92])

    primary = results[0]
    return jsonify({
        "age": primary["age"],
        "age_precise": primary["age_precise"],
        "age_raw": primary["age_raw"],
        "confidence": primary["confidence"],
        "calibrated": age_model.calibrated,
        "face_count": len(results),
        "faces": results,
        "annotated_url": url,
        "model": "DEX VGG (IMDB-WIKI / FFHQ-Aging)",
    })


# ==============================================================
# API — FULL SCAN PIPELINE
# ==============================================================
def _get_embedding(img_path):
    """Extract the face embedding from an image file."""
    img = cv2.imread(img_path)
    if img is None:
        return None
    faces = face_app.get(img)
    if not faces:
        return None
    return faces[0].normed_embedding


def _cosine_to_pct(cosine_sim):
    """Rescale raw cosine similarity to an intuitive 0-100% range.
    Face embeddings typically yield cosine similarities in 0.1-0.7 range.
    We map [0.0, 0.6] → [0%, 100%] so that scores feel more natural,
    while clamping to [0, 100]."""
    scaled = (cosine_sim / 0.6) * 100.0
    return round(max(0.0, min(100.0, scaled)), 1)


@app.route("/api/scan/submit", methods=["POST"])
def api_scan_submit():
    """
    Full pipeline: receive one-or-more legacy photos + a live photo →
    age-progress each legacy photo → verify each against the live photo →
    keep the best-scoring pair as the official result → save → route.
    Form fields: legacy_images (file, repeatable), live_image (file),
                 primary_index (int), current_age/target_age (int),
                 case_name (str), notes (str)
    """
    if not model_loaded:
        return jsonify({"error": "Age-progression model not loaded"}), 503

    legacy_files = request.files.getlist("legacy_images")
    if not legacy_files or "live_image" not in request.files:
        return jsonify({"error": "At least one legacy photo and a live photo are required"}), 400

    case_name = request.form.get("case_name", "").strip() or None
    notes = request.form.get("notes", "").strip() or None
    primary_index = int(request.form.get("primary_index", 0) or 0)
    if not (0 <= primary_index < len(legacy_files)):
        primary_index = 0

    # ── Consent gate ──────────────────────────────────────
    consent = request.form.get("consent", "").strip().lower()
    if consent != "true":
        return jsonify({"error": "Consent to process biometric data is required"}), 400

    scan_id = None
    try:
        current_age = _form_int("current_age", 20)
        target_age = _form_int("target_age", 40)
        direction = (request.form.get("direction") or "").strip().lower()
        if direction not in ("older", "younger"):
            direction = "older" if target_age > current_age else "younger"

        # Amplify the target age to produce a stronger visual effect
        # e.g., aging from 10 to 18 (delta 8) becomes aging to 22 (delta 12)
        age_gap = target_age - current_age
        amplified_target = int(current_age + (age_gap * 1.5))
        # Ensure it stays within reasonable bounds (0 to 100)
        amplified_target = max(0, min(100, amplified_target))

        threshold_val = float(database.get_setting("threshold", "75"))

        # The per-scan output folder is named after scan_id, so the row has to
        # exist before any file can be placed. Photo paths are filled in below.
        scan_id = database.create_scan(
            None, None, current_age, case_name, notes, consent_given=True,
        )

        live_dest, _ = build_image_path("current", scan_id=scan_id, index=0)
        live_path, live_url, live_img = _save_upload(request.files.get("live_image"), live_dest)

        emb_live = _get_embedding(live_path) if insightface_ok else None

        # 1) Age-progress + score every uploaded legacy photo
        candidates = []
        for idx, file_storage in enumerate(legacy_files):
            legacy_dest, _ = build_image_path("legacy", scan_id=scan_id, index=idx)
            legacy_path, legacy_url, legacy_img = _save_upload(file_storage, legacy_dest)

            try:
                result_img, gen_meta = sam_model.process_image(image=legacy_path, target_age=amplified_target)
            except sam_wrapper.FaceNotFoundError:
                result_img, gen_meta = legacy_img, {"face_detected": False}
            face_detected = gen_meta.get("face_detected", False)
            # same index as the legacy photo it came from
            gen_dest, gen_url = build_image_path("generated", scan_id=scan_id, index=idx)
            result_img.save(str(gen_dest), quality=92)
            gen_path = str(gen_dest.resolve())

            cosine = sim_score = dist = match_source = None
            if emb_live is not None:
                try:
                    emb_gen = _get_embedding(gen_path)
                    emb_legacy = _get_embedding(legacy_path)
                    # Both the aged render and the untouched legacy photo are
                    # scored against the live capture and the better one wins.
                    # match_source records which, because a win on "legacy"
                    # means the verdict did not use the age progression at all.
                    scores = []
                    if emb_gen is not None:
                        cos1 = float(np.dot(emb_gen, emb_live))
                        scores.append(("generated", cos1))
                        print(f"  InsightFace [{idx}] generated→live  cosine={cos1:.4f}")
                    if emb_legacy is not None:
                        cos2 = float(np.dot(emb_legacy, emb_live))
                        scores.append(("legacy", cos2))
                        print(f"  InsightFace [{idx}] legacy→live     cosine={cos2:.4f}")
                    if scores:
                        match_source, cosine = max(scores, key=lambda s: s[1])
                        sim_score = _cosine_to_pct(cosine)
                        dist = round(1 - cosine, 4)
                except Exception as vex:
                    print(f"  InsightFace error on photo [{idx}] (non-fatal): {vex}")

            candidates.append({
                "legacy_path": legacy_path, "legacy_url": legacy_url,
                "gen_path": gen_path, "gen_url": gen_url,
                "cosine": cosine, "sim_score": sim_score, "dist": dist,
                "match_source": match_source,
                "is_primary": idx == primary_index,
                "face_detected": face_detected,
            })

        # 2) The candidate with the highest similarity becomes the official result.
        # Prefer candidates where a face was actually detected/aged — a photo with
        # no detectable face (e.g. not a portrait) shouldn't win by default.
        with_face = [c for c in candidates if c["face_detected"]]
        pool = with_face or candidates
        best = max(pool, key=lambda c: c["cosine"] if c["cosine"] is not None else -1)
        verified = bool(best["sim_score"] is not None and best["sim_score"] >= threshold_val)
        print(f"  InsightFace best of {len(candidates)} photo(s): "
              f"score={best['sim_score']}%  match={best['match_source']}  verified={verified}")

        # 3) Point the scan record at the best pair
        database.set_scan_photos(scan_id, best["legacy_path"], live_path)
        database.update_scan_results(
            scan_id, best["gen_path"], current_age, target_age, direction,
            best["sim_score"], best["dist"], threshold_val, verified,
        )

        # 4) Keep every candidate photo on record for audit/training purposes
        for c in candidates:
            database.add_legacy_photo(scan_id, c["legacy_path"], c["gen_path"], c["sim_score"], c["is_primary"])

        scan = database.get_scan(scan_id)
        return jsonify({
            "success": True,
            "scan": _scan_to_json(scan),
            "generated_url": best["gen_url"],
            "legacy_url": best["legacy_url"],
            "live_url": live_url,
            "num_legacy_photos": len(candidates),
            "match_source": best["match_source"],
        })

    except Exception as exc:
        traceback.print_exc()
        # The scan row is created before any file is written (the folder is
        # named after it), so a failure here would otherwise strand a row in
        # 'processing' with no photos, which then shows up in /api/history.
        if scan_id is not None:
            try:
                database.delete_scan(scan_id)
            except Exception:
                pass
        return jsonify({"error": str(exc)}), 500


# ==============================================================
# API — HISTORY
# ==============================================================
@app.route("/api/history")
def api_history():
    scans = database.get_all_scans()
    return jsonify([_scan_to_json(s) for s in scans])


@app.route("/api/scan/<int:scan_id>", methods=["DELETE"])
def api_scan_delete(scan_id):
    database.delete_scan(scan_id)
    return jsonify({"success": True})


# ==============================================================
# API — ADMIN: QUEUE
# ==============================================================
@app.route("/api/queue")
def api_queue():
    queue = database.get_queue()
    return jsonify([_scan_to_json(s) for s in queue])


@app.route("/api/queue/resolve", methods=["POST"])
def api_queue_resolve():
    data = request.get_json(silent=True) or {}
    scan_id = data.get("scan_id")
    resolution = data.get("resolution")  # 'approved' or 'rejected'
    note = data.get("reviewer_note", "")
    if not scan_id or resolution not in ("approved", "rejected"):
        return jsonify({"error": "Invalid request"}), 400
    database.resolve_scan(int(scan_id), resolution, note)
    return jsonify({"success": True})


# ==============================================================
# API — ADMIN: THRESHOLD
# ==============================================================
@app.route("/api/threshold", methods=["GET"])
def api_threshold_get():
    return jsonify({"threshold": float(database.get_setting("threshold", "75"))})


@app.route("/api/threshold", methods=["POST"])
def api_threshold_set():
    data = request.get_json(silent=True) or {}
    try:
        val = float(data.get("threshold"))
    except (TypeError, ValueError):
        return jsonify({"error": "Threshold must be a number between 40 and 95"}), 400
    if not (40 <= val <= 95):
        return jsonify({"error": "Threshold must be 40-95"}), 400
    database.set_setting("threshold", str(int(val)))
    return jsonify({"success": True, "threshold": int(val)})


# ==============================================================
# API — ADMIN: TRAINING DATA SUBMISSION
# ==============================================================
@app.route("/api/training/submit", methods=["POST"])
def api_training_submit():
    if "old_image" not in request.files or "current_image" not in request.files:
        return jsonify({"error": "Both Legacy Picture and Present Picture are required"}), 400

    scan_id = (request.form.get("scan_id") or "").strip()
    scan_id = int(scan_id) if scan_id.isdigit() else None
    note = (request.form.get("note") or "").strip() or None

    sub_id = None
    try:
        # Folder is named after the submission id, so create the row first.
        sub_id = database.create_training_submission(scan_id, None, None, note)
        old_dest, _ = build_image_path("training", submission_id=sub_id, filename="legacy_00.jpg")
        cur_dest, _ = build_image_path("training", submission_id=sub_id, filename="present_00.jpg")
        old_path, _, _ = _save_upload(request.files.get("old_image"), old_dest)
        current_path, _, _ = _save_upload(request.files.get("current_image"), cur_dest)
        database.set_training_photos(sub_id, old_path, current_path)
        return jsonify({"success": True, "id": sub_id})
    except Exception as exc:
        traceback.print_exc()
        # Same folder-named-after-the-row pattern as /api/scan/submit: drop the
        # placeholder row so a failed upload doesn't linger in the admin list.
        if sub_id is not None:
            try:
                database.delete_training_submission(sub_id)
            except Exception:
                pass
        return jsonify({"error": str(exc)}), 500


@app.route("/api/training")
def api_training_list():
    subs = database.get_training_submissions()
    for s in subs:
        s["old_photo_url"] = _path_to_url(s.get("old_photo"))
        s["current_photo_url"] = _path_to_url(s.get("current_photo"))
    return jsonify(subs)


@app.route("/api/training/<int:sub_id>/status", methods=["POST"])
def api_training_status(sub_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in ("sent", "received", "used"):
        return jsonify({"error": "Invalid status"}), 400
    database.update_training_status(sub_id, status)
    return jsonify({"success": True})


@app.route("/api/training/<int:sub_id>", methods=["DELETE"])
def api_training_delete(sub_id):
    database.delete_training_submission(sub_id)
    return jsonify({"success": True})


# ==============================================================
# API — ADMIN: STATS
# ==============================================================
@app.route("/api/stats")
def api_stats():
    stats = database.get_stats()
    stats["threshold"] = float(database.get_setting("threshold", "75"))
    return jsonify(stats)


# ==============================================================
# MAIN
# ==============================================================
if __name__ == "__main__":
    print()
    print("  +-----------------------------------------------+")
    print("  | BS BioShifting - Age Progression & Verif.     |")
    print("  |   http://127.0.0.1:5000                       |")
    print("  +-----------------------------------------------+")
    print()
    app.run(host="127.0.0.1", port=5000, debug=False)
