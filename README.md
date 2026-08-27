# BioShift Capstone

BioShift is a local, browser-based face age-progression and verification prototype. It can age-progress a legacy photograph, compare it with a current photograph, estimate photo age, run face-quality checks, save scan history, and route results to an administrator review queue.

All processing and saved scan data stay on the computer running the application.

## Features

- SAM-based facial age progression and regression
- InsightFace face detection and similarity scoring
- DEX photo-age estimation
- MediaPipe face-quality checks
- Local SQLite scan history and administrator review
- Desktop and phone-oriented browser interfaces

## Quick start on Windows

### 1. Install the prerequisites

You need:

- 64-bit Windows 10 or 11
- [Git for Windows](https://git-scm.com/download/win)
- [Python 3.13 (64-bit)](https://www.python.org/downloads/windows/)
- At least 8 GB RAM; 16 GB or more is recommended
- About 8 GB of free disk space for Python packages and model files
- Internet access during installation and the first launch

When installing Python, enable **Add Python to PATH** if the installer offers that option.

### 2. Download and install BioShift

Open PowerShell and run:

```powershell
git clone https://github.com/phiffles/BioShift-Capstone.git
cd BioShift-Capstone
.\install.bat
```

`install.bat` creates an isolated `.venv`, installs the tested CPU dependencies, and downloads approximately 4 GB of required model files. It is safe to run the installer again: completed downloads are reused.

### 3. Start BioShift

```powershell
.\start.bat
```

Wait for the startup messages, then open <http://127.0.0.1:5000>. Stop the server with `Ctrl+C`.

After the first installation, `start.bat` is the only command normally needed.

## Environment variables and API keys

Never put API keys, access tokens, passwords, or other credentials directly in
the source code. Copy `.env.example` to `.env` and place local secrets in that
file. `.env` and its local variants are ignored by Git; `.env.example` is a
safe template and must contain placeholder values only.

```powershell
Copy-Item .env.example .env
```

`server.py` loads `.env` during startup. Python integrations must read each
value from the environment and fail clearly when a required value is missing:

```python
import os

api_key = os.getenv("SERVICE_API_KEY")
if not api_key:
    raise RuntimeError("SERVICE_API_KEY is not configured")
```

Do not expose a secret to browser JavaScript or include it in an HTTP response.
If a secret was ever committed, remove it from Git history and rotate it at the
provider; adding it to `.gitignore` afterward is not sufficient.

## Download without Git

If you do not want to install Git, use GitHub's **Code > Download ZIP** button, extract the ZIP, open the extracted folder, and double-click `install.bat`. When installation finishes, double-click `start.bat`.

Do not run the scripts from inside the ZIP preview; extract the entire folder first.

## Phone-oriented interface

For a phone on the same Wi-Fi network, activate the installed environment and start the mobile server:

```powershell
.\.venv\Scripts\python.exe server_mobile.py --lan --https
```

The terminal prints the address to open on the phone. Accept the self-signed certificate warning. HTTPS is required for camera access in most phone browsers.

For a phone-shaped interface on the same computer, omit `--lan --https` and open <http://127.0.0.1:5001>.

## Manual installation

The automated installer is recommended. To perform the same setup manually from PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install torch==2.13.0 torchvision==0.28.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe download_models.py
.\.venv\Scripts\python.exe verify_install.py
.\.venv\Scripts\python.exe server.py
```

If `python` is not recognized but the Python launcher is installed, replace the first command with `py -3.13 -m venv .venv`.

## NVIDIA GPU support

The automated installer uses the CPU build of PyTorch so that BioShift works on the widest range of Windows computers. CPU processing works but age progression can be slow.

Advanced users with a compatible NVIDIA GPU can replace the CPU build inside `.venv` with the appropriate Windows command from the [official PyTorch installation selector](https://pytorch.org/get-started/locally/). BioShift automatically uses CUDA when PyTorch detects it.

## Model files

The large model files are intentionally excluded from Git because GitHub does not accept files of this size. `download_models.py` installs them at the paths expected by the application:

| File | Purpose |
| --- | --- |
| `SAM/pretrained_models/sam_ffhq_aging.pt` | SAM age-progression model |
| `SAM/pretrained_models/dex_age_classifier.pth` | DEX photo-age estimator |
| `SAM/shape_predictor_68_face_landmarks.dat` | dlib facial landmarks |
| `face_reaging/face_landmarker.task` | MediaPipe face-quality checks |
| `~/.insightface/models/buffalo_l/` | Face detection and verification; downloaded on first launch |

Run `.\.venv\Scripts\python.exe verify_install.py` at any time to check the Python packages and project model files.

## Troubleshooting

- **Python 3.13 was not found:** install the 64-bit version from python.org, close and reopen PowerShell, then run `install.bat` again.
- **A download was interrupted:** run `install.bat` again. Partial downloads are discarded and completed model files are skipped.
- **A model is reported as missing:** run `.\.venv\Scripts\python.exe download_models.py`, followed by `.\.venv\Scripts\python.exe verify_install.py`.
- **The first launch appears stuck:** model initialization can take several minutes on a CPU. Wait for the Flask server address before opening the site.
- **Port 5000 is already in use:** stop the other process using it, or change the port near the end of `server.py`.
- **The camera is unavailable on a phone:** use `server_mobile.py --lan --https`; plain HTTP over Wi-Fi is not treated as a secure camera origin.
- **PowerShell blocks scripts:** use `install.bat`, which starts the included setup script with a process-local execution-policy bypass.

## Local data and privacy

BioShift writes scan records to `history.db` and uploaded/generated images to `image_folder/`. Both paths are ignored by Git. Delete those local files when you no longer need the scan data. Do not upload real identity documents or face photographs to a public repository.

## Project structure

| Path | Contents |
| --- | --- |
| `install.bat`, `setup.ps1` | Automated Windows installation |
| `start.bat` | Desktop application launcher |
| `server.py` | Desktop Flask application and API |
| `server_mobile.py` | Mobile-oriented Flask presentation |
| `sam_wrapper.py` | SAM model loading and age-progression pipeline |
| `age_estimator.py` | DEX age estimation and calibration |
| `database.py` | Local SQLite persistence |
| `templates/`, `static/` | Browser pages, styles, and JavaScript |

## Third-party software and model terms

The bundled `SAM/` directory is based on **Only a Matter of Style: Age Transformation Using a Style-Based Regression Model** (SIGGRAPH 2021). Its original README and licence are in [`SAM/`](SAM/README.md).

The application also uses Flask, PyTorch, InsightFace, MediaPipe, dlib, OpenCV, and their respective licences. In particular, InsightFace states that its pretrained models, including automatically downloaded model packs, are provided for non-commercial research use. Review the upstream terms before using BioShift outside an academic prototype.
