"""
Age estimation using the DEX VGG age classifier.

Why not InsightFace's genderage.onnx: it is a tiny attribute head bundled with
buffalo_l for speed, and it is not usable as a real age estimator. Measured on
this project's own photos it never predicted below 24 — childhood ID photos
averaged 29.9 and present-day adult captures averaged 31.3, i.e. it could not
separate children from adults at all.

DEX (Deep EXpectation, ChaLearn LAP winner) instead predicts a distribution
over 101 classes (ages 0-100) and takes the softmax-weighted expectation, so
it covers children properly and returns a smooth real-valued age. These are
the same weights SAM uses for its aging loss, so estimates stay consistent
with the age-progression feature.

Face detection/alignment still comes from InsightFace, which is good at it.
"""

import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

BASE_DIR = Path(__file__).parent
SAM_DIR = BASE_DIR / "SAM"
if str(SAM_DIR) not in sys.path:
    sys.path.append(str(SAM_DIR))

from SAM.models.dex_vgg import VGG

AGE_MODEL_PATH = SAM_DIR / "pretrained_models" / "dex_age_classifier.pth"
CALIBRATION_PATH = BASE_DIR / "age_calibration" / "age_calibration.json"

# DEX expects ImageNet-normalised 224x224 RGB.
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# Crop margins averaged over per estimate. A single margin is fragile: measured on
# this project's photos, one teen face moved 15 years (29.3 -> 14.3) across margins
# 0.0-0.8. Averaging several stabilises that, which also buys the headroom the
# calibration curve needs, since expanding the output range amplifies noise.
MARGINS = (0.25, 0.4, 0.55)


class AgeEstimator:
    def __init__(self, model_path=None, device=None):
        model_path = Path(model_path or AGE_MODEL_PATH)
        if not model_path.exists():
            raise FileNotFoundError(f"DEX age classifier not found at {model_path}")
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.net = VGG()
        ckpt = torch.load(str(model_path), map_location="cpu")
        state = ckpt.get("state_dict", ckpt)
        # checkpoint uses 'fc8-101'-style keys; the module attribute is fc8_101
        state = {k.replace("-", "_"): v for k, v in state.items()}
        self.net.load_state_dict(state)
        self.net.to(self.device).eval()
        self._load_calibration()

    def _prep(self, pil_img):
        arr = np.asarray(pil_img.convert("RGB").resize((224, 224), Image.BILINEAR),
                         dtype=np.float32) / 255.0
        arr = (arr - _MEAN) / _STD
        return torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0)

    @torch.no_grad()
    def _probs(self, pil_img, flip_tta=True):
        """Age distribution (101 classes) for one already-cropped face."""
        batch = [self._prep(pil_img)]
        if flip_tta:
            batch.append(self._prep(pil_img.transpose(Image.FLIP_LEFT_RIGHT)))
        x = torch.cat(batch).to(self.device)
        logits = self.net(x)["fc8"]
        return F.softmax(logits, dim=1).mean(dim=0)  # average over TTA views

    def _age_from_probs(self, probs):
        ages = torch.arange(probs.shape[0], dtype=probs.dtype, device=probs.device)
        age = float((probs * ages).sum())
        lo, hi = max(0, int(age) - 5), min(int(probs.shape[0]), int(age) + 6)
        return age, float(probs[lo:hi].sum())

    def predict(self, pil_img, flip_tta=True):
        """Raw (uncalibrated) age for an image already cropped to a face.

        Returns (age: float, confidence: float). Confidence is the share of
        probability mass within +/-5 years of the prediction, so a peaked
        distribution scores high and a smeared one scores low.
        """
        return self._age_from_probs(self._probs(pil_img, flip_tta))

    def predict_from_face(self, img_bgr, bbox, margins=None):
        """Production entry point: crop at several margins, average the age
        *distributions* (not the scalar ages — averaging distributions is better
        behaved), then apply the calibration curve.

        Returns (calibrated_age, raw_age, confidence), or None if no crop worked.
        """
        margins = MARGINS if margins is None else margins
        acc, n = None, 0
        for m in margins:
            crop = crop_face(img_bgr, bbox, margin=m)
            if crop.size == 0:
                continue
            pil = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            p = self._probs(pil)
            acc = p if acc is None else acc + p
            n += 1
        if acc is None:
            return None
        raw, confidence = self._age_from_probs(acc / n)
        return self.calibrate(raw), raw, confidence

    # ── Calibration ────────────────────────────────────────────
    def _load_calibration(self):
        """Load the correction curve, if one has been fitted."""
        self._cal = None
        if not CALIBRATION_PATH.exists():
            return
        try:
            data = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
            knots = np.asarray(data["knots"], dtype=float)
            if knots.ndim == 2 and len(knots) >= 2:
                self._cal = (knots[:, 0], knots[:, 1])
                print(f"  [OK] Age calibration loaded ({len(knots)} knots)")
        except Exception as exc:
            print(f"  [!] Ignoring unreadable {CALIBRATION_PATH.name}: {exc}")

    def calibrate(self, raw_age):
        """Map a raw DEX age onto the corrected scale.

        Identity when no curve is fitted, so the app still runs uncalibrated.
        Outside the fitted range the end slopes are continued rather than
        clamped flat, so the oldest faces keep separating.
        """
        if self._cal is None:
            return float(raw_age)
        xs, ys = self._cal
        if raw_age <= xs[0]:
            slope = (ys[1] - ys[0]) / max(1e-6, xs[1] - xs[0])
            out = ys[0] + (raw_age - xs[0]) * slope
        elif raw_age >= xs[-1]:
            slope = (ys[-1] - ys[-2]) / max(1e-6, xs[-1] - xs[-2])
            out = ys[-1] + (raw_age - xs[-1]) * slope
        else:
            out = float(np.interp(raw_age, xs, ys))
        return float(min(100.0, max(1.0, out)))

    @property
    def calibrated(self):
        return self._cal is not None


_instance = None


def get_age_estimator():
    global _instance
    if _instance is None:
        _instance = AgeEstimator()
    return _instance


def crop_face(img_bgr, bbox, margin=0.4):
    """Crop a detected face with margin, as DEX expects a fairly tight but
    context-including face crop. bbox is InsightFace's [x1,y1,x2,y2]."""
    h, w = img_bgr.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in bbox]
    bw, bh = x2 - x1, y2 - y1
    cx, cy = x1 + bw / 2.0, y1 + bh / 2.0
    half = max(bw, bh) * (1.0 + margin) / 2.0
    x1 = max(0, int(cx - half))
    y1 = max(0, int(cy - half))
    x2 = min(w, int(cx + half))
    y2 = min(h, int(cy + half))
    return img_bgr[y1:y2, x1:x2]
