"""Download the model assets excluded from Git because of their size.

Run from the repository root after installing requirements.txt:
    python download_models.py
"""

from pathlib import Path
from urllib.request import urlretrieve

import gdown


ROOT = Path(__file__).resolve().parent


def is_complete(destination: Path, minimum_size: int) -> bool:
    return destination.is_file() and destination.stat().st_size >= minimum_size


def download_google_drive(
    file_id: str,
    destination: Path,
    minimum_size: int,
) -> None:
    if is_complete(destination, minimum_size):
        print(f"[skip] {destination.relative_to(ROOT)} already exists")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)

    if destination.exists():
        print(f"[replace] {destination.relative_to(ROOT)} is incomplete")
    print(f"[download] {destination.relative_to(ROOT)}")
    try:
        gdown.download(id=file_id, output=str(partial), quiet=False)
        if not is_complete(partial, minimum_size):
            raise RuntimeError(
                f"Download is incomplete: {destination.relative_to(ROOT)}"
            )
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def download_url(url: str, destination: Path, minimum_size: int) -> None:
    if is_complete(destination, minimum_size):
        print(f"[skip] {destination.relative_to(ROOT)} already exists")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)

    if destination.exists():
        print(f"[replace] {destination.relative_to(ROOT)} is incomplete")
    print(f"[download] {destination.relative_to(ROOT)}")
    try:
        urlretrieve(url, partial)
        if not is_complete(partial, minimum_size):
            raise RuntimeError(
                f"Download is incomplete: {destination.relative_to(ROOT)}"
            )
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def main() -> None:
    download_google_drive(
        "1XyumF6_fdAxFmxpFcmPf-q84LU_22EMC",
        ROOT / "SAM" / "pretrained_models" / "sam_ffhq_aging.pt",
        2_000_000_000,
    )
    download_google_drive(
        "1atzjZm_dJrCmFWCqWlyspSpr3nI6Evsh",
        ROOT / "SAM" / "pretrained_models" / "dex_age_classifier.pth",
        1_000_000_000,
    )
    download_url(
        "https://github.com/italojs/facial-landmarks-recognition/raw/master/shape_predictor_68_face_landmarks.dat",
        ROOT / "SAM" / "shape_predictor_68_face_landmarks.dat",
        90_000_000,
    )
    download_url(
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
        ROOT / "face_reaging" / "face_landmarker.task",
        3_000_000,
    )
    print("\nModel files are ready. Start the app with: python server.py")
    print("InsightFace downloads buffalo_l automatically on first startup.")


if __name__ == "__main__":
    main()
