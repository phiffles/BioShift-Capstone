# BS BioShifting

An offline, browser-based prototype for age-progressing a legacy face photograph and comparing it with a current photograph. It also includes a standalone photo-age estimator, a face-quality check, scan history, and an administrator review queue.

## Requirements

- Windows 10/11
- Python 3.13 (the project was tested with Python 3.13.5)
- At least 8 GB RAM; 16 GB or more is recommended. CPU inference works, but the age-progression model is large and can take a while to start.
- About 5 GB free disk space for model files. They are downloaded separately and are intentionally not stored in Git.
- Internet access during the one-time model download and first start (InsightFace downloads its `buffalo_l` recognition model automatically). After that, normal use is local.

> A CUDA-capable NVIDIA GPU is optional. The project automatically uses it when PyTorch can see it; otherwise it runs on CPU.

## Windows setup and run

Open PowerShell in the folder where you want the project, then run:

```powershell
git clone <YOUR-GITHUB-REPOSITORY-URL>
cd <YOUR-REPOSITORY-FOLDER>

py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

# CPU build of PyTorch (works on any supported Windows PC)
python -m pip install torch==2.13.0 torchvision==0.28.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt

# Downloads about 4 GB of project model files. Do this once.
python download_models.py

python server.py
```

If PowerShell blocks virtual-environment activation, run this once in the same PowerShell window and activate it again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

When startup completes, open <http://127.0.0.1:5000>. A successful startup prints `[OK]` messages for SAM, InsightFace, DEX, and MediaPipe. The first launch can take a few minutes because InsightFace also downloads its own `buffalo_l` model.

Stop the server with `Ctrl+C`.

## Mobile presentation

The same application can be presented with the phone-oriented interface:

```powershell
python server_mobile.py
```

Open <http://127.0.0.1:5001>. To use a real phone on the same Wi-Fi network, run `python server_mobile.py --lan --https` and accept the browser's self-signed-certificate warning. HTTPS is needed for the phone browser to permit camera access.

## What is downloaded and why

`download_models.py` puts each required file at the exact path expected by the application:

| File | Purpose |
| --- | --- |
| `SAM/pretrained_models/sam_ffhq_aging.pt` | SAM age-progression model |
| `SAM/pretrained_models/dex_age_classifier.pth` | DEX photo-age estimator |
| `SAM/shape_predictor_68_face_landmarks.dat` | dlib face-alignment landmarks |
| `face_reaging/face_landmarker.task` | MediaPipe face-quality checks |
| `~/.insightface/models/buffalo_l/` | InsightFace detection and face verification; auto-downloaded at first launch |

These files are excluded by `.gitignore` because GitHub rejects files over 100 MB and the two main model files alone are about 4 GB.

## Troubleshooting

- **`py -3.13` is not found:** install Python 3.13 from [python.org](https://www.python.org/downloads/windows/) and select **Add Python to PATH** during installation.
- **A model reports as missing:** re-run `python download_models.py` from the repository root; existing non-empty downloads are skipped.
- **The site opens but a feature says its model is unavailable:** check the console output, confirm the file names and paths in the table above, then restart the server.
- **Port 5000 is already in use:** close the other process using it, or change `port=5000` near the end of `server.py`.
- **Camera is unavailable on a phone:** use `--lan --https`; plain HTTP on a LAN is not a secure browser origin.

## Project structure

| Path | Contents |
| --- | --- |
| `server.py` | Desktop Flask application and API |
| `server_mobile.py` | Mobile-oriented Flask presentation |
| `sam_wrapper.py` | SAM model loading and age-progression pipeline |
| `age_estimator.py` | DEX age estimation and calibration |
| `database.py` | Local SQLite persistence |
| `templates/`, `static/` | Browser pages, styles, and JavaScript |
| `DOCUMENTATION.md` | Technical architecture, API, model, and design notes |

## Third-party work

The bundled `SAM/` directory is based on **Only a Matter of Style: Age Transformation Using a Style-Based Regression Model** (SIGGRAPH 2021). Its original README and licence are in [`SAM/`](SAM/README.md). The application also uses Flask, PyTorch, InsightFace, MediaPipe, dlib, OpenCV, and their respective licences.
