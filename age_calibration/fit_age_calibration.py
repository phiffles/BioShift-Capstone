"""
Fit the age-correction curve and write age_calibration.json.

GOAL: conditional unbiasedness — an 18-year-old should read ~18 on average and a
60-year-old ~60. DEX currently compresses toward the middle (measured: 18-24 reads
+2.3y too old, >55 reads -11.4y too young).

METHOD. Two curves could be fitted here and they are NOT the same thing:

  * E[true | pred] would minimise average error, but it stays compressed by
    construction — a conditional mean is always regressive — so it would not fix
    the symptom.
  * inverse of E[pred | true] is what actually delivers "18 reads 18". We bin by
    TRUE age (noise-free), take the mean prediction per bin to get g(true), then
    invert g. Binning by the noise-free axis also avoids regression dilution,
    which is what made a naive slope fit report a meaningless 1.02x gain.

g must be increasing to invert; it is enforced with pool-adjacent-violators.

Usage (from anywhere):
    python age_calibration/fit_age_calibration.py [--n 750] [--single-margin]

Expects the UTKFace tarball extracted to age_calibration/calibration_data/UTKFace/.
Writes age_calibration/age_calibration.json, which age_estimator.py loads at startup.
"""

import argparse
import json
import os
import random
import re
import sys
from datetime import date
from pathlib import Path

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import cv2
import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).parent
PROJECT_ROOT = BASE_DIR.parent
# age_estimator lives at the project root, so make it importable no matter where
# this script is invoked from.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = BASE_DIR / "calibration_data"
IMAGES_DIR = DATA_DIR / "UTKFace"
OUT_PATH = BASE_DIR / "age_calibration.json"

NAME_RE = re.compile(r"^(\d{1,3})_(\d)_(\d)_")
BUCKETS = [("<18", 0, 17), ("18-35", 18, 35), ("36-55", 36, 55), (">55", 56, 200)]
STRATA = [(1, 12), (13, 17), (18, 25), (26, 35), (36, 45),
          (46, 55), (56, 65), (66, 75), (76, 120)]

# Bins for building g(true). Narrow where faces change fast (childhood), wider
# where they change slowly and the data thins out.
FIT_BINS = [(1, 5), (6, 9), (10, 13), (14, 17), (18, 21), (22, 25), (26, 30),
            (31, 35), (36, 42), (43, 50), (51, 58), (59, 66), (67, 75), (76, 116)]


def load_index():
    root = IMAGES_DIR if IMAGES_DIR.is_dir() else DATA_DIR
    items = []
    for p in root.rglob("*.jpg"):
        m = NAME_RE.match(p.name)
        if m:
            age = int(m.group(1))
            if 1 <= age <= 116:
                items.append((p, age))
    return items


def stratified_sample(items, n, seed=0):
    rng = random.Random(seed)
    buckets = {s: [] for s in STRATA}
    for p, age in items:
        for lo, hi in STRATA:
            if lo <= age <= hi:
                buckets[(lo, hi)].append((p, age))
                break
    per = max(1, n // len(STRATA))
    out = []
    for s in STRATA:
        pool = buckets[s]
        rng.shuffle(pool)
        out.extend(pool[:per])
    rng.shuffle(out)
    return out


def pad_replicate(img, frac=0.6):
    """UTKFace chips are 200x200 with no context and SCRFD detects nothing in them
    (measured 0/12). Replicate-padding restores detection (12/12) and lets the
    production detect -> crop_face(margin) path run on this data."""
    p = int(max(img.shape[:2]) * frac)
    return cv2.copyMakeBorder(img, p, p, p, p, cv2.BORDER_REPLICATE)


def pava(y, w):
    """Pool-adjacent-violators: nearest increasing sequence, weighted."""
    y = list(map(float, y))
    w = list(map(float, w))
    i = 0
    while i < len(y) - 1:
        if y[i] <= y[i + 1]:
            i += 1
            continue
        tot = w[i] + w[i + 1]
        y[i] = (y[i] * w[i] + y[i + 1] * w[i + 1]) / tot
        w[i] = tot
        del y[i + 1], w[i + 1]
        if i > 0:
            i -= 1
    return y, w


def run_inference(sample, est, app, use_ensemble):
    rows, skipped = [], 0
    for i, (p, true_age) in enumerate(sample, 1):
        img = cv2.imread(str(p))
        if img is None:
            skipped += 1
            continue
        padded = pad_replicate(img)
        faces = app.get(padded)
        if not faces:
            skipped += 1
            continue
        f = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))

        if use_ensemble:
            import age_estimator as AE
            out = est.predict_from_face(padded, f.bbox)
            if out is None:
                skipped += 1
                continue
            _cal, raw, _conf = out
        else:
            import age_estimator as AE
            crop = AE.crop_face(padded, f.bbox, margin=0.4)
            if crop.size == 0:
                skipped += 1
                continue
            raw, _ = est.predict(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))

        rows.append((true_age, raw))
        if i % 50 == 0:
            print(f"  {i}/{len(sample)} (kept {len(rows)}, skipped {skipped})", flush=True)
    return rows


def report(true, pred, label):
    err = pred - true
    print(f"\n{label}: MAE {np.abs(err).mean():5.2f}y | bias {err.mean():+5.2f}y "
          f"| r={np.corrcoef(true, pred)[0,1]:.3f}")
    print(f"  {'bucket':<8}{'n':>5}{'true':>8}{'pred':>8}{'bias':>8}{'MAE':>8}")
    for name, lo, hi in BUCKETS:
        m = (true >= lo) & (true <= hi)
        if not m.any():
            continue
        print(f"  {name:<8}{m.sum():>5}{true[m].mean():>8.1f}{pred[m].mean():>8.1f}"
              f"{err[m].mean():>+8.1f}{np.abs(err[m]).mean():>8.1f}")
    return float(np.abs(err).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=750)
    ap.add_argument("--single-margin", action="store_true",
                    help="fit at margin 0.4 only instead of the MARGINS ensemble")
    args = ap.parse_args()
    use_ensemble = not args.single_margin

    if not IMAGES_DIR.is_dir():
        sys.exit(f"Missing {IMAGES_DIR}. Download + extract UTKFace first.")

    items = load_index()
    print(f"Indexed {len(items)} labelled images.")
    sample = stratified_sample(items, args.n)
    print(f"Stratified sample: {len(sample)}  (ensemble={use_ensemble})")

    import age_estimator as AE
    from insightface.app import FaceAnalysis

    # Fit against RAW model output: ignore any curve already on disk.
    est = AE.get_age_estimator()
    est._cal = None

    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))

    print("\nRunning inference ...", flush=True)
    rows = run_inference(sample, est, app, use_ensemble)
    if len(rows) < 100:
        sys.exit(f"Only {len(rows)} usable samples — too few to fit.")

    rng = np.random.default_rng(0)
    idx = rng.permutation(len(rows))
    cut = int(len(rows) * 0.8)
    train = [rows[i] for i in idx[:cut]]
    test = [rows[i] for i in idx[cut:]]
    print(f"\nSplit: {len(train)} train / {len(test)} test")

    tr_true = np.array([r[0] for r in train], float)
    tr_pred = np.array([r[1] for r in train], float)

    # ── g(true) = E[pred | true], binned on the noise-free axis ──
    centres, means, weights = [], [], []
    for lo, hi in FIT_BINS:
        m = (tr_true >= lo) & (tr_true <= hi)
        if m.sum() < 5:
            continue
        centres.append(float(tr_true[m].mean()))
        means.append(float(tr_pred[m].mean()))
        weights.append(int(m.sum()))

    mono, _ = pava(means, weights)

    print(f"\n{'true (bin mean)':<18}{'raw pred':>10}{'monotonic':>12}{'n':>6}")
    print("-" * 46)
    for c, raw_m, mo, w in zip(centres, means, mono, weights):
        print(f"{c:<18.1f}{raw_m:>10.1f}{mo:>12.1f}{w:>6}")

    # Invert: knots map raw prediction -> corrected age.
    knots = [[round(float(m), 3), round(float(c), 3)] for m, c in zip(mono, centres)]

    est._cal = (np.array([k[0] for k in knots]), np.array([k[1] for k in knots]))

    te_true = np.array([r[0] for r in test], float)
    te_pred_raw = np.array([r[1] for r in test], float)
    te_pred_cal = np.array([est.calibrate(p) for p in te_pred_raw])

    print(f"\n{'='*60}\nHELD-OUT EVALUATION (n={len(test)})\n{'='*60}")
    mae_before = report(te_true, te_pred_raw, "BEFORE (raw)")
    mae_after = report(te_true, te_pred_cal, "AFTER  (calibrated)")

    print("\nWorked examples (raw -> corrected):")
    for probe in (10, 15, 20, 25, 30, 40, 50, 60):
        print(f"  model says {probe:>3}  ->  {est.calibrate(probe):5.1f}")

    payload = {
        "knots": knots,
        "margins": list(AE.MARGINS) if use_ensemble else [0.4],
        "fitted": date.today().isoformat(),
        "n_train": len(train),
        "n_test": len(test),
        "mae_before": round(mae_before, 2),
        "mae_after": round(mae_after, 2),
        "source": "UTKFace (py97/UTKFace-Cropped), stratified, replicate-padded",
        "method": "inverse of E[pred|true], monotonic via PAVA",
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_PATH.name}: MAE {mae_before:.2f} -> {mae_after:.2f}")


if __name__ == "__main__":
    main()
