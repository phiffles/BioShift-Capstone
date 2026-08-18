"""Download the model assets excluded from Git because of their size.

Run from the repository root after installing requirements.txt:
    python download_models.py
"""

from pathlib import Path
from urllib.request import urlretrieve

import gdown


ROOT = Path(__file__).resolve().parent


def download_google_drive(file_id: str, destination: Path) -> None:
    if destination.exists() and destination.stat().st_size > 0:
        print(f"[skip] {destination.relative_to(ROOT)} already exists")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"[download] {destination.relative_to(ROOT)}")
    gdown.download(id=file_id, output=str(destination), quiet=False)
    if not destination.exists() or destination.stat().st_size == 0:
        raise RuntimeError(f"Download did not create {destination}")


def download_url(url: str, destination: Path) -> None:
    if destination.exists() and destination.stat().st_size > 0:
        print(f"[skip] {destination.relative_to(ROOT)} already exists")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"[download] {destination.relative_to(ROOT)}")
    urlretrieve(url, destination)


def main() -> None:
    download_google_drive(
        "1XyumF6_fdAxFmxpFcmPf-q84LU_22EMC",
        ROOT / "SAM" / "pretrained_models" / "sam_ffhq_aging.pt",
    )
    download_google_drive(
        "1atzjZm_dJrCmFWCqWlyspSpr3nI6Evsh",
        ROOT / "SAM" / "pretrained_models" / "dex_age_classifier.pth",
    )
    download_url(
        "https://github.com/italojs/facial-landmarks-recognition/raw/master/shape_predictor_68_face_landmarks.dat",
        ROOT / "SAM" / "shape_predictor_68_face_landmarks.dat",
    )
    download_url(
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
        ROOT / "face_reaging" / "face_landmarker.task",
    )
    print("\nModel files are ready. Start the app with: python server.py")
    print("InsightFace downloads buffalo_l automatically on first startup.")


if __name__ == "__main__":
    main()
