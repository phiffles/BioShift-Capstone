"""Verify that BioShift's dependencies and model assets are installed."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parent

MODULES = {
    "flask": "Flask",
    "torch": "PyTorch",
    "torchvision": "torchvision",
    "cv2": "OpenCV",
    "numpy": "NumPy",
    "PIL": "Pillow",
    "insightface": "InsightFace",
    "onnxruntime": "ONNX Runtime",
    "mediapipe": "MediaPipe",
    "dlib": "dlib (prebuilt dlib-bin package)",
    "scipy": "SciPy",
    "cryptography": "cryptography",
    "gdown": "gdown",
    "dotenv": "python-dotenv",
}

MODEL_FILES = {
    "SAM/pretrained_models/sam_ffhq_aging.pt": 2_000_000_000,
    "SAM/pretrained_models/dex_age_classifier.pth": 1_000_000_000,
    "SAM/shape_predictor_68_face_landmarks.dat": 90_000_000,
    "face_reaging/face_landmarker.task": 3_000_000,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-models",
        action="store_true",
        help="only verify Python dependencies",
    )
    args = parser.parse_args()

    problems: list[str] = []

    print("Checking Python dependencies...")
    for module, label in MODULES.items():
        if importlib.util.find_spec(module) is None:
            problems.append(f"missing Python dependency: {label} ({module})")
            print(f"  [missing] {label}")
        else:
            print(f"  [ok] {label}")

    if not args.skip_models:
        print("Checking model files...")
        for relative_path, minimum_size in MODEL_FILES.items():
            path = ROOT / relative_path
            if not path.is_file():
                problems.append(f"missing model file: {relative_path}")
                print(f"  [missing] {relative_path}")
            elif path.stat().st_size < minimum_size:
                problems.append(f"incomplete model file: {relative_path}")
                print(f"  [incomplete] {relative_path}")
            else:
                print(f"  [ok] {relative_path}")

    if problems:
        print("\nInstallation check failed:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\nBioShift installation check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
