# Age calibration

Corrects the DEX age estimator's compression toward the middle of the range.

| file | what it is |
|---|---|
| `age_calibration.json` | the fitted curve — loaded by `age_estimator.py` at startup |
| `fit_age_calibration.py` | regenerates that curve |
| `calibration_data/` | UTKFace, downloaded on demand (gitignored, ~107 MB) |

## Why

Raw DEX reads young faces slightly old and old faces much too young. Measured on 149
held-out UTKFace images through the production path:

| bucket | bias before | bias after |
|---|---|---|
| `<18`   | +0.4y  | −0.2y |
| `18-35` | +1.0y  | +1.2y |
| `36-55` | −6.0y  | +1.1y |
| `>55`   | −12.8y | −3.7y |

Overall bias −5.49y → −0.87y; MAE 8.37 → 7.90.

The curve fits the **inverse of E[pred | true]**, not E[true | pred]. That distinction is
the whole point: E[true | pred] minimises average error but is a conditional mean, so it
stays compressed and would not fix the symptom. Binning on the true age also avoids the
regression dilution that makes a naive slope fit report a meaningless ~1.0x gain.

## Trade-off

Inverting a compressed mapping amplifies noise where the compression was strongest, so
middle-bucket MAE got worse (18-35: 3.9 → 5.4, 36-55: 7.0 → 8.5) while the ends improved
(>55: 15.3 → 12.4). This was chosen deliberately: the displayed number should look right
across the range rather than minimise average error.

It also reads this project's own photos ~1–2 years younger (adult ~25: 25.2 → 23.1), since
that range was already accurate before correction.

## Refitting

```bash
# 1. dataset (ungated, ~107 MB, age is in each filename)
mkdir -p age_calibration/calibration_data
curl -L -o age_calibration/calibration_data/UTKFace.tar.gz \
  https://huggingface.co/datasets/py97/UTKFace-Cropped/resolve/main/UTKFace.tar.gz
tar -xzf age_calibration/calibration_data/UTKFace.tar.gz -C age_calibration/calibration_data

# 2. fit (~2 hours on CPU at n=750; use python -u to see progress)
python -u age_calibration/fit_age_calibration.py --n 750
```

Two gotchas worth knowing before touching this:

- **UTKFace chips cannot be face-detected as-is.** They are 200×200 with no surrounding
  context and SCRFD finds nothing (measured 0/12). `fit_age_calibration.py` replicate-pads
  every image first, which restores detection (12/12). Don't remove that step.
- **Crop margin is load-bearing.** Predictions move up to 15 years across margins 0.0–0.8,
  so the curve is only valid for the `MARGINS` it was fitted with (recorded in the JSON).
  Change `age_estimator.MARGINS` and you must refit.

## Disabling

Delete `age_calibration.json` — `AgeEstimator.calibrate()` becomes the identity and the app
runs on raw predictions. To soften rather than remove it, damp toward identity:
`raw + lam * (calibrate(raw) - raw)` with `lam` around 0.5–0.7.
