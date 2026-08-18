/* ============================================================
   VERITAS — 6-Step Scan Wizard Controller
   Step 1: Direction   | Step 2: Legacy Photo | Step 3: Present Photo (FQA)
   Step 4: Age Target  | Step 5: Processing   | Step 6: Results
   ============================================================ */
(() => {
  "use strict";
  const { $, $$, toast, wireDropzone, fmtTime, sleep } = V;

  // ── State ──────────────────────────────────────────────
  const MAX_LEGACY_PHOTOS = 5;
  const TOTAL_STEPS = 6;

  const S = {
    step: 1,
    direction: "older",     // "older" (progression) | "younger" (regression)
    legacyFiles: [],        // [{ file, dataUrl }]
    primaryLegacyIndex: 0,
    liveFile: null,
    liveDataUrl: null,
    currentAge: 10,
    targetAge: 40,
    caseName: "",
    notes: "",
    scan: null,        // result from server
    generatedUrl: null,
    legacyUrl: null,
    liveUrl: null,
    numLegacyPhotos: 1,
    legacyAgeEstimate: null,     // {age, confidence} from the primary legacy photo
    legacyAgeEstimating: false,
    presentAgeEstimate: null,    // {age, confidence} from the present photo
    presentAgeEstimating: false,
  };

  const panels = {};
  function cachePanel(n) { panels[n] = $(`#step-${n}`); }

  // ══════════════════════════════════════════════════════════
  // AGE ESTIMATION — runs quietly in the background as legacy/present
  // photos are set in steps 2 & 3, so Step 4 already has a suggested age
  // by the time the user gets there. Purely a suggestion: it never writes
  // into the age input itself, the user has to click "Use this".
  // ══════════════════════════════════════════════════════════
  function confidenceWord(c) {
    if (c == null) return null;
    const pct = Math.round(c * 100);
    return pct >= 80 ? "high" : pct >= 50 ? "moderate" : "low";
  }

  async function estimateAgeFromFile(file) {
    if (!file) return null;
    try {
      const fd = new FormData();
      fd.append("image", file);
      const resp = await fetch("/api/estimate-age", { method: "POST", body: fd });
      const data = await resp.json();
      if (!resp.ok || data.error) return null;
      return { age: data.age, confidence: data.confidence };
    } catch {
      return null;
    }
  }

  async function estimateLegacyAge() {
    const primary = S.legacyFiles[S.primaryLegacyIndex];
    if (!primary) {
      S.legacyAgeEstimate = null;
      S.legacyAgeEstimating = false;
      updateAgeHints();
      return;
    }
    S.legacyAgeEstimating = true;
    S.legacyAgeEstimate = null;
    updateAgeHints();
    const result = await estimateAgeFromFile(primary.file);
    S.legacyAgeEstimating = false;
    S.legacyAgeEstimate = result;
    updateAgeHints();
  }

  async function estimatePresentAge() {
    if (!S.liveFile) {
      S.presentAgeEstimate = null;
      S.presentAgeEstimating = false;
      updateAgeHints();
      return;
    }
    S.presentAgeEstimating = true;
    S.presentAgeEstimate = null;
    updateAgeHints();
    const result = await estimateAgeFromFile(S.liveFile);
    S.presentAgeEstimating = false;
    S.presentAgeEstimate = result;
    updateAgeHints();
  }

  function updateAgeHints() {
    const lh = $("#legacy-age-hint");
    const lt = $("#legacy-age-hint-text");
    const lu = $("#legacy-age-use-btn");
    if (lh && lt) {
      if (S.legacyAgeEstimating) {
        lh.style.display = "flex";
        lt.textContent = "Estimating age from your legacy photo…";
        if (lu) lu.style.display = "none";
      } else if (S.legacyAgeEstimate) {
        lh.style.display = "flex";
        const word = confidenceWord(S.legacyAgeEstimate.confidence);
        lt.textContent = `AI estimate from your legacy photo: ~${S.legacyAgeEstimate.age} yrs`
          + (word ? ` (${word} confidence)` : "");
        if (lu) lu.style.display = "inline-flex";
      } else {
        lh.style.display = "none";
      }
    }

    const ph = $("#present-age-hint");
    const pt = $("#present-age-hint-text");
    if (ph && pt) {
      if (S.presentAgeEstimating) {
        ph.style.display = "flex";
        pt.textContent = "Estimating age from your present photo…";
      } else if (S.presentAgeEstimate) {
        ph.style.display = "flex";
        const word = confidenceWord(S.presentAgeEstimate.confidence);
        pt.textContent = `AI estimate from your present photo: ~${S.presentAgeEstimate.age} yrs`
          + (word ? ` (${word} confidence)` : "");
      } else {
        ph.style.display = "none";
      }
    }
  }

  // ── Step Navigation ────────────────────────────────────
  function goTo(n) {
    if (n < 1 || n > TOTAL_STEPS) return;
    S.step = n;
    $$(".step-dot").forEach((d, i) => {
      d.classList.remove("active", "done");
      if (i + 1 < n) d.classList.add("done");
      if (i + 1 === n) d.classList.add("active");
    });
    $$(".step-line").forEach((l, i) => l.classList.toggle("done", i + 1 < n));
    $$(".step-label").forEach((l, i) => l.classList.toggle("active", i + 1 === n));
    Object.entries(panels).forEach(([k, p]) => {
      if (p) p.classList.toggle("active", parseInt(k) === n);
    });
    if (n === 3) enterPresentPhotoStep();
    if (n === 5) runPipeline();
  }

  // ══════════════════════════════════════════════════════════
  // STEP 1 — DIRECTION (Progression / Regression)
  // ══════════════════════════════════════════════════════════
  function initStep1() {
    const btnOlder = $("#dir-older");
    const btnYounger = $("#dir-younger");

    function choose(direction) {
      S.direction = direction;
      btnOlder.classList.toggle("selected", direction === "older");
      btnYounger.classList.toggle("selected", direction === "younger");
      goTo(2);
    }

    btnOlder.addEventListener("click", () => choose("older"));
    btnYounger.addEventListener("click", () => choose("younger"));
  }

  // ══════════════════════════════════════════════════════════
  // STEP 2 — LEGACY PHOTO (Upload + Camera)
  // ══════════════════════════════════════════════════════════
  let legacyStream = null;
  let legacyCameraMode = "upload";  // "upload" | "camera"

  function initStep2() {
    const dz = $("#legacy-dropzone");
    const fi = $("#legacy-file-input");
    const grid = $("#legacy-photo-grid");
    const maxNote = $("#legacy-max-note");
    const nb = $("#step1-next-btn");
    const backBtn = $("#step2-back-to-direction-btn");

    // Mode toggle buttons
    const modeUploadBtn = $("#legacy-mode-upload-btn");
    const modeCameraBtn = $("#legacy-mode-camera-btn");

    // Camera elements
    const legacyVid = $("#legacy-video");
    const legacyCapturedImg = $("#legacy-captured-img");
    const legacyCanvas = $("#legacy-canvas");
    const legacyCaptureRow = $("#legacy-camera-capture-row");
    const legacyReviewRow = $("#legacy-camera-review-row");
    const legacyCaptureBtn = $("#legacy-camera-capture-btn");
    const legacyRetakeBtn = $("#legacy-camera-retake-btn");
    const legacyUseBtn = $("#legacy-camera-use-btn");
    const legacyFallback = $("#legacy-camera-fallback");

    function renderLegacyGrid() {
      if (S.legacyFiles.length === 0) {
        grid.style.display = "none";
        grid.innerHTML = "";
        if (legacyCameraMode === "upload") dz.style.display = "block";
        maxNote.style.display = "none";
        nb.disabled = true;
        return;
      }

      grid.style.display = "grid";
      grid.innerHTML = S.legacyFiles.map((f, idx) => `
        <div class="legacy-thumb ${idx === S.primaryLegacyIndex ? "primary" : ""}">
          <img src="${f.dataUrl}" alt="">
          <button class="legacy-thumb-remove" data-idx="${idx}" title="Remove">✕</button>
          ${idx === S.primaryLegacyIndex ? '<span class="legacy-thumb-badge">Primary</span>' : ""}
        </div>`).join("");

      grid.querySelectorAll(".legacy-thumb-remove").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const idx = parseInt(btn.dataset.idx);
          S.legacyFiles.splice(idx, 1);
          if (S.primaryLegacyIndex >= S.legacyFiles.length) S.primaryLegacyIndex = Math.max(0, S.legacyFiles.length - 1);
          else if (S.primaryLegacyIndex > idx) S.primaryLegacyIndex--;
          renderLegacyGrid();
          estimateLegacyAge();
        });
      });

      const atMax = S.legacyFiles.length >= MAX_LEGACY_PHOTOS;
      if (legacyCameraMode === "upload") {
        dz.style.display = atMax ? "none" : "block";
      }
      // In camera mode, disable the capture button when at max
      if (legacyCaptureBtn) legacyCaptureBtn.disabled = atMax;
      maxNote.style.display = atMax ? "block" : "none";
      nb.disabled = false;
    }

    function addLegacyFiles(fileList) {
      const room = MAX_LEGACY_PHOTOS - S.legacyFiles.length;
      const files = Array.from(fileList).filter((f) => f.type.startsWith("image/")).slice(0, room);
      let pending = files.length;
      if (pending === 0) return;
      files.forEach((file) => {
        const r = new FileReader();
        r.onload = (e) => {
          S.legacyFiles.push({ file, dataUrl: e.target.result });
          pending--;
          if (pending === 0) {
            renderLegacyGrid();
            estimateLegacyAge();
          }
        };
        r.readAsDataURL(file);
      });
    }

    // ── Upload mode wiring ──
    dz.addEventListener("click", () => fi.click());
    dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("dragover"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      dz.classList.remove("dragover");
      addLegacyFiles(e.dataTransfer.files);
    });
    fi.addEventListener("change", (e) => {
      addLegacyFiles(e.target.files);
      fi.value = "";
    });

    // ── Camera mode wiring ──
    function startLegacyCamera() {
      try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error("No camera API");
        navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: "environment",
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
        }).then((s) => {
          legacyStream = s;
          legacyVid.srcObject = s;
          if (legacyFallback) legacyFallback.style.display = "none";
        }).catch((err) => {
          console.error("Legacy camera error:", err);
          if (legacyFallback) legacyFallback.style.display = "block";
        });
      } catch (err) {
        console.error("Legacy camera error:", err);
        if (legacyFallback) legacyFallback.style.display = "block";
      }
    }

    function stopLegacyCamera() {
      if (legacyStream) { legacyStream.getTracks().forEach((t) => t.stop()); legacyStream = null; }
    }

    function resetLegacyCameraUI() {
      if (legacyCapturedImg) { legacyCapturedImg.style.display = "none"; legacyCapturedImg.src = ""; }
      if (legacyVid) legacyVid.style.display = "block";
      const overlay = $("#legacy-camera-mode .capture-overlay");
      if (overlay) overlay.style.display = "flex";
      if (legacyCaptureRow) legacyCaptureRow.style.display = "flex";
      if (legacyReviewRow) legacyReviewRow.style.display = "none";
      const atMax = S.legacyFiles.length >= MAX_LEGACY_PHOTOS;
      if (legacyCaptureBtn) legacyCaptureBtn.disabled = atMax;
    }

    function captureLegacyFrame() {
      if (S.legacyFiles.length >= MAX_LEGACY_PHOTOS) return;
      const vw = legacyVid.videoWidth || 480;
      const vh = legacyVid.videoHeight || 640;
      legacyCanvas.width = vw;
      legacyCanvas.height = vh;
      const ctx = legacyCanvas.getContext("2d");
      ctx.drawImage(legacyVid, 0, 0, vw, vh);
      const dataUrl = legacyCanvas.toDataURL("image/jpeg", 0.9);

      // Show captured preview
      legacyCapturedImg.src = dataUrl;
      legacyCapturedImg.style.display = "block";
      legacyVid.style.display = "none";
      const overlay = $("#legacy-camera-mode .capture-overlay");
      if (overlay) overlay.style.display = "none";
      legacyCaptureRow.style.display = "none";
      legacyReviewRow.style.display = "flex";
      // Store temporarily for the "Add" step
      legacyCapturedImg._pendingDataUrl = dataUrl;
    }

    function addCapturedLegacyPhoto() {
      const dataUrl = legacyCapturedImg._pendingDataUrl;
      if (!dataUrl) return;
      // Convert dataURL to File
      fetch(dataUrl).then(r => r.blob()).then(blob => {
        const file = new File([blob], `legacy_capture_${Date.now()}.jpg`, { type: "image/jpeg" });
        S.legacyFiles.push({ file, dataUrl });
        renderLegacyGrid();
        estimateLegacyAge();
        resetLegacyCameraUI();
        toast("Legacy photo added");
      });
    }

    if (legacyCaptureBtn) legacyCaptureBtn.addEventListener("click", captureLegacyFrame);
    if (legacyRetakeBtn) legacyRetakeBtn.addEventListener("click", resetLegacyCameraUI);
    if (legacyUseBtn) legacyUseBtn.addEventListener("click", addCapturedLegacyPhoto);

    // ── Mode switching ──
    function chooseLegacyMode(mode) {
      legacyCameraMode = mode;
      const uploadSection = $("#legacy-upload-mode");
      const cameraSection = $("#legacy-camera-mode");

      if (mode === "upload") {
        if (uploadSection) uploadSection.style.display = "block";
        if (cameraSection) cameraSection.style.display = "none";
        modeUploadBtn.classList.replace("btn-ghost", "btn-primary");
        modeCameraBtn.classList.replace("btn-primary", "btn-ghost");
        stopLegacyCamera();
        renderLegacyGrid();   // re-show dropzone if needed
      } else {
        if (uploadSection) uploadSection.style.display = "none";
        if (cameraSection) cameraSection.style.display = "block";
        modeCameraBtn.classList.replace("btn-ghost", "btn-primary");
        modeUploadBtn.classList.replace("btn-primary", "btn-ghost");
        resetLegacyCameraUI();
        startLegacyCamera();
      }
    }

    modeUploadBtn.addEventListener("click", () => chooseLegacyMode("upload"));
    modeCameraBtn.addEventListener("click", () => chooseLegacyMode("camera"));

    backBtn.addEventListener("click", () => { stopLegacyCamera(); goTo(1); });
    nb.addEventListener("click", () => { if (S.legacyFiles.length > 0) { stopLegacyCamera(); goTo(3); } });
  }

  // ══════════════════════════════════════════════════════════
  // STEP 3 — PRESENT PHOTO (Live Scan first, Upload as fallback)
  // ══════════════════════════════════════════════════════════
  let stream = null;
  let fqaInterval = null;
  let latestFaceBox = null;
  // FQA runs on a downscaled frame (see startFQALoop), so face_box comes back
  // in that smaller coordinate space. Capture needs it in full video pixels.
  let fqaScale = 1;

  function initStep3() {
    const backBtn = $("#step2-back-btn");
    backBtn.addEventListener("click", () => goTo(2));

    // Upload mode (fallback)
    const udz = $("#live-upload-dropzone");
    const ufi = $("#live-upload-file-input");
    const upw = $("#live-upload-preview-wrap");
    const upi = $("#live-upload-preview-img");
    const urb = $("#live-upload-remove-btn");
    const ubtn = $("#step2-use-upload-btn");

    wireDropzone(udz, ufi, (file) => {
      S.liveFile = file;
      const r = new FileReader();
      r.onload = (e) => {
        S.liveDataUrl = e.target.result;
        upi.src = e.target.result;
        udz.style.display = "none";
        upw.style.display = "block";
        ubtn.disabled = false;
      };
      r.readAsDataURL(file);
      estimatePresentAge();
    });
    urb.addEventListener("click", () => {
      S.liveFile = null;
      S.liveDataUrl = null;
      upi.src = "";
      upw.style.display = "none";
      udz.style.display = "block";
      ufi.value = "";
      ubtn.disabled = true;
      estimatePresentAge();
    });
    ubtn.addEventListener("click", () => { if (S.liveFile) goTo(4); });

    // Scan mode buttons
    const captBtn = $("#capture-btn");
    const retakeBtn = $("#retake-btn");
    const useBtn = $("#use-photo-btn");

    captBtn.addEventListener("click", captureFrame);
    retakeBtn.addEventListener("click", retake);
    useBtn.addEventListener("click", () => {
      if (S.liveDataUrl) goTo(4);
    });

    // Switch links
    const toUpload = $("#switch-to-upload");
    const toScan = $("#switch-to-scan");
    if (toUpload) toUpload.addEventListener("click", (e) => { e.preventDefault(); chooseLiveMode("upload"); });
    if (toScan) toScan.addEventListener("click", (e) => { e.preventDefault(); chooseLiveMode("scan"); });
  }

  function enterPresentPhotoStep() {
    // Scanning is shown first every time this step is entered; upload is reachable via the link.
    chooseLiveMode("scan");
  }

  function chooseLiveMode(mode) {
    $("#scan-screen").style.display = mode === "scan" ? "block" : "none";
    $("#upload-screen").style.display = mode === "upload" ? "block" : "none";
    $("#capture-row").style.display = mode === "scan" ? "flex" : "none";
    $("#review-row").style.display = "none";
    $("#upload-row").style.display = mode === "upload" ? "flex" : "none";

    if (mode === "scan") {
      resetScanUI();
      startCamera();
    } else {
      stopCamera();
    }
  }

  function resetScanUI() {
    S.liveDataUrl = null;
    S.liveFile = null;
    latestFaceBox = null;
    const ci = $("#captured-img");
    const vid = $("#live-video");
    if (ci) ci.style.display = "none";
    if (vid) vid.style.display = "block";
    const ov = $(".capture-overlay");
    const fb = $(".fqa-feedback");
    if (ov) ov.style.display = "flex";
    if (fb) fb.style.display = "flex";
    $("#capture-btn").disabled = true;
    $$(".fqa-checklist .fqa-item").forEach((c) => c.classList.remove("pass"));
    const pill = $("#fqa-pill");
    if (pill) pill.classList.remove("ok");
  }

  async function startCamera() {
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error("No camera API");
      // Without an explicit size browsers hand back their default capture
      // resolution — usually 640x480, which is then face-cropped and upscaled
      // to 512x512, so the photo that reaches ArcFace is mostly interpolation.
      // `ideal` degrades gracefully on webcams that can't do 1080p.
      stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: "user",
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
      });
      const vid = $("#live-video");
      vid.srcObject = stream;
      startFQALoop();
    } catch (err) {
      console.error("Camera error:", err);
      const fb = $("#camera-fallback");
      if (fb) fb.style.display = "block";
      const pill = $("#fqa-pill");
      if (pill) { pill.classList.remove("ok"); $("#fqa-text").textContent = "Camera unavailable"; }
    }
  }

  function stopCamera() {
    if (fqaInterval) { clearInterval(fqaInterval); fqaInterval = null; }
    if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
  }

  function startFQALoop() {
    const vid = $("#live-video");
    const canvas = $("#fqa-canvas");
    const pill = $("#fqa-pill");
    const fqaText = $("#fqa-text");
    const captBtn = $("#capture-btn");
    const checks = { light: false, blur: false, pose: false, eye: false };

    fqaInterval = setInterval(async () => {
      if (!stream || vid.readyState < 2) return;
      // Analyse at ~640px wide regardless of stream size: MediaPipe gains
      // nothing from 1080p here and it runs on CPU every 800ms, so full-res
      // frames would just add landmark latency and upload weight.
      const vw = vid.videoWidth || 480;
      const vh = vid.videoHeight || 640;
      fqaScale = Math.min(1, 640 / vw);
      canvas.width = Math.round(vw * fqaScale);
      canvas.height = Math.round(vh * fqaScale);
      const ctx = canvas.getContext("2d");
      ctx.drawImage(vid, 0, 0, canvas.width, canvas.height);

      try {
        const blob = await new Promise((r) => canvas.toBlob(r, "image/jpeg", 0.7));
        const fd = new FormData();
        fd.append("frame", blob, "frame.jpg");
        const resp = await fetch("/api/fqa", { method: "POST", body: fd });
        const data = await resp.json();

        if (data.checks) {
          Object.entries(data.checks).forEach(([k, v]) => {
            checks[k] = v.pass;
            const el = $(`.fqa-checklist .fqa-item[data-k="${k}"]`);
            if (el) el.classList.toggle("pass", v.pass);
          });
        }

        if (data.face_box) {
          latestFaceBox = data.face_box;
        }

        fqaText.textContent = data.msg || "Analyzing…";
        const allOk = data.overall;
        pill.classList.toggle("ok", allOk);
        captBtn.disabled = !allOk;
      } catch {
        // FQA server down — allow capture anyway
        fqaText.textContent = "FQA check unavailable";
        pill.classList.add("ok");
        captBtn.disabled = false;
      }
    }, 800);
  }

  function captureFrame() {
    const vid = $("#live-video");
    const canvas = $("#fqa-canvas");

    if (latestFaceBox) {
      // Map the box back from the downscaled FQA frame into video pixels.
      const [sbx, sby, sbw, sbh] = latestFaceBox;
      const bx = sbx / fqaScale, by = sby / fqaScale;
      const bw = sbw / fqaScale, bh = sbh / fqaScale;

      // Never upscale: on a 1080p stream the face crop is usually larger than
      // 512, so this downsamples (sharp) instead of interpolating (soft).
      const out = Math.min(768, Math.max(256, Math.round(Math.min(bw, bh))));
      canvas.width = out;
      canvas.height = out;
      const ctx = canvas.getContext("2d");
      ctx.imageSmoothingQuality = "high";

      // Mirror the output since the user expects a mirrored live preview
      ctx.translate(canvas.width, 0);
      ctx.scale(-1, 1);

      ctx.drawImage(vid, bx, by, bw, bh, 0, 0, out, out);
    } else {
      canvas.width = vid.videoWidth || 480;
      canvas.height = vid.videoHeight || 640;
      const ctx = canvas.getContext("2d");
      ctx.translate(canvas.width, 0);
      ctx.scale(-1, 1);
      ctx.drawImage(vid, 0, 0, canvas.width, canvas.height);
    }

    const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
    showCaptured(dataUrl);
  }

  function showCaptured(dataUrl) {
    S.liveDataUrl = dataUrl;
    // Convert dataURL to File for upload
    fetch(dataUrl).then(r => r.blob()).then(blob => {
      S.liveFile = new File([blob], "capture.jpg", { type: "image/jpeg" });
      estimatePresentAge();
    });

    const ci = $("#captured-img");
    ci.src = dataUrl;
    ci.style.display = "block";
    $("#live-video").style.display = "none";
    $(".capture-overlay").style.display = "none";
    $(".fqa-feedback").style.display = "none";
    $("#capture-row").style.display = "none";
    $("#review-row").style.display = "flex";
    stopCamera();
  }

  function retake() {
    $("#review-row").style.display = "none";
    $("#capture-row").style.display = "flex";
    resetScanUI();
    startCamera();
    estimatePresentAge();
  }

  // ══════════════════════════════════════════════════════════
  // STEP 4 — AGE TARGET
  // ══════════════════════════════════════════════════════════
  function initStep4() {
    const currentAgeInput = $("#current-age-input");
    const targetAgeSlider = $("#target-age-slider");
    const targetAgeVal = $("#target-age-value");

    const backBtn = $("#step3-back-btn");
    const runBtn = $("#step3-run-btn");

    function clampCurrentAge() {
      let v = parseInt(currentAgeInput.value, 10);
      if (isNaN(v)) v = 10;
      v = Math.max(1, Math.min(100, v));
      currentAgeInput.value = v;
      S.currentAge = v;
    }

    function clampTargetAge(raw) {
      let v = parseInt(raw, 10);
      if (isNaN(v)) v = 40;
      return Math.max(1, Math.min(100, v));
    }

    // Slider moved → the number box follows.
    function updateTargetAge() {
      S.targetAge = clampTargetAge(targetAgeSlider.value);
      targetAgeVal.value = S.targetAge;
    }

    // Typed → move the slider, but deliberately do NOT rewrite the box on every
    // keystroke: clamping mid-type fights the user (typing "8" toward 18 would
    // snap the field). An empty box is left alone so it can be cleared.
    function targetAgeTyped() {
      if (targetAgeVal.value.trim() === "") return;
      S.targetAge = clampTargetAge(targetAgeVal.value);
      targetAgeSlider.value = S.targetAge;
    }

    // Done typing → normalise whatever is in the box.
    function commitTargetAge() {
      S.targetAge = clampTargetAge(targetAgeVal.value);
      targetAgeVal.value = S.targetAge;
      targetAgeSlider.value = S.targetAge;
    }

    currentAgeInput.addEventListener("input", clampCurrentAge);
    currentAgeInput.addEventListener("change", clampCurrentAge);
    targetAgeSlider.addEventListener("input", updateTargetAge);
    targetAgeVal.addEventListener("input", targetAgeTyped);
    targetAgeVal.addEventListener("change", commitTargetAge);
    targetAgeVal.addEventListener("blur", commitTargetAge);

    backBtn.addEventListener("click", () => goTo(3));

    // "Use this" on the auto-estimate hint under Age in Legacy Photo
    const legacyUseBtn = $("#legacy-age-use-btn");
    if (legacyUseBtn) legacyUseBtn.addEventListener("click", () => {
      if (!S.legacyAgeEstimate) return;
      currentAgeInput.value = S.legacyAgeEstimate.age;
      clampCurrentAge();
      toast("Applied estimated age");
    });

    // Consent checkbox gates the Run button
    const consentCb = $("#consent-checkbox");
    const consentCard = $("#consent-card");
    consentCb.addEventListener("change", () => {
      runBtn.disabled = !consentCb.checked;
      if (consentCb.checked) {
        if (consentCard) consentCard.classList.add("consent-agreed");
      } else {
        if (consentCard) consentCard.classList.remove("consent-agreed");
      }
    });

    runBtn.addEventListener("click", () => {
      if (!consentCb.checked) return;
      S.caseName = ($("#case-name-input") || {}).value || "";
      S.notes = ($("#notes-input") || {}).value || "";
      S.consentGiven = true;
      goTo(5);
    });
  }

  // ══════════════════════════════════════════════════════════
  // STEP 5 — PROCESSING (PIPELINE)
  // ══════════════════════════════════════════════════════════
  let abortController = null;
  let pipelineTimer = null;
  let pipelineStartTime = 0;
  let agingTickerInterval = null;

  function startAgingTicker(from, to) {
    const ageTag = $("#orb-age-tag");
    const orb = $("#futuristic-orb");
    if (orb) orb.classList.add("aging-fx");
    let val = from;
    let dir = to >= from ? 1 : -1;
    if (ageTag) ageTag.textContent = "Age " + val;
    agingTickerInterval = setInterval(() => {
      val += dir;
      if (dir > 0 && val >= to) dir = -1;
      else if (dir < 0 && val <= to) dir = 1;
      if (ageTag) ageTag.textContent = "Age " + val;
    }, 110);
  }

  function stopAgingTicker(finalAge) {
    if (agingTickerInterval) { clearInterval(agingTickerInterval); agingTickerInterval = null; }
    const orb = $("#futuristic-orb");
    if (orb) orb.classList.remove("aging-fx");
    const ageTag = $("#orb-age-tag");
    if (ageTag) ageTag.textContent = "Age " + finalAge;
  }

  function crossfadeOrbImage(url) {
    return new Promise((resolve) => {
      const imgA = $("#futuristic-img");
      const imgB = $("#futuristic-img-b");
      const orb = $("#futuristic-orb");
      if (!imgA || !imgB || !orb || !url) return resolve();
      imgB.onload = () => {
        orb.classList.add("crossfade");
        setTimeout(() => {
          imgA.src = url;
          orb.classList.remove("crossfade");
          resolve();
        }, 650);
      };
      imgB.onerror = () => resolve();
      imgB.src = url;
    });
  }

  async function runPipeline() {
    const steps = $$("#pipeline-steps .fqa-item");
    const errorEl = $("#pipeline-error");
    const progress = $("#pipeline-progress");
    const pct = $("#pipeline-pct");
    const timerEl = $("#pipeline-timer");
    const cancelBtn = $("#pipeline-cancel-btn");
    const orbImg = $("#futuristic-img");
    const orbImgB = $("#futuristic-img-b");
    const orb = $("#futuristic-orb");
    const ageTag = $("#orb-age-tag");
    const vsWrap = $("#proc-vs-wrap");
    const currentOrbWrap = $("#current-orb-wrap");
    const currentOrbImg = $("#current-orb-img");

    if (orbImg) orbImg.src = (S.legacyFiles[S.primaryLegacyIndex] || {}).dataUrl || "";
    if (orbImgB) orbImgB.src = "";
    if (orb) orb.classList.remove("aging-fx", "crossfade");
    if (ageTag) ageTag.textContent = "Age " + S.currentAge;
    if (vsWrap) vsWrap.classList.remove("show");
    if (currentOrbWrap) currentOrbWrap.classList.remove("show");
    if (currentOrbImg) currentOrbImg.src = "";

    errorEl.style.display = "none";
    steps.forEach((s) => { s.classList.remove("pass"); s.classList.remove("active"); });
    if (progress) progress.style.width = "0%";
    if (pct) pct.textContent = "0%";
    if (timerEl) timerEl.textContent = "00:00 elapsed";

    pipelineStartTime = Date.now();
    pipelineTimer = setInterval(() => {
      const diff = Math.floor((Date.now() - pipelineStartTime) / 1000);
      const m = String(Math.floor(diff / 60)).padStart(2, "0");
      const s = String(diff % 60).padStart(2, "0");
      if (timerEl) timerEl.textContent = `${m}:${s} elapsed`;
    }, 1000);

    abortController = new AbortController();

    const handleCancel = () => {
      abortController.abort();
      clearInterval(pipelineTimer);
      stopAgingTicker(S.targetAge);
      goTo(4);
    };
    if (cancelBtn) {
      cancelBtn.removeEventListener("click", cancelBtn._handler);
      cancelBtn._handler = handleCancel;
      cancelBtn.addEventListener("click", handleCancel);
    }

    try {
      await markStepAdv(steps, 0, 10, pct, progress);

      const fd = new FormData();
      S.legacyFiles.forEach((f) => fd.append("legacy_images", f.file));
      fd.append("primary_index", S.primaryLegacyIndex);
      fd.append("live_image", S.liveFile);
      fd.append("current_age", S.currentAge);
      fd.append("target_age", S.targetAge);
      fd.append("direction", S.direction);
      fd.append("case_name", S.caseName);
      fd.append("notes", S.notes);
      fd.append("consent", S.consentGiven ? "true" : "false");

      await sleep(400); // Simulate loading photos
      await markStepAdv(steps, 1, 20, pct, progress);
      await sleep(600); // Simulate aligning faces

      await markStepAdv(steps, 2, 35, pct, progress);
      startAgingTicker(S.currentAge, S.targetAge);

      const resp = await fetch("/api/scan/submit", {
        method: "POST",
        body: fd,
        signal: abortController.signal
      });
      const data = await resp.json();
      if (!resp.ok || data.error) throw new Error(data.error || "Server error");

      stopAgingTicker(S.targetAge);
      await crossfadeOrbImage(data.generated_url);

      await markStepAdv(steps, 3, 60, pct, progress);
      if (currentOrbImg) currentOrbImg.src = S.liveDataUrl || "";
      if (currentOrbWrap) currentOrbWrap.classList.add("show");
      if (vsWrap) vsWrap.classList.add("show");
      await sleep(500);

      S.scan = data.scan;
      S.generatedUrl = data.generated_url;
      S.legacyUrl = data.legacy_url;
      S.liveUrl = data.live_url;
      S.numLegacyPhotos = data.num_legacy_photos || 1;

      await markStepAdv(steps, 4, 80, pct, progress);
      await sleep(400);

      await markStepAdv(steps, 5, 95, pct, progress);
      await sleep(300);

      steps[5].classList.remove("active");
      steps[5].classList.add("pass");
      if (progress) progress.style.width = "100%";
      if (pct) pct.textContent = "100%";

      clearInterval(pipelineTimer);
      await sleep(500);
      populateResults();
      goTo(6);
    } catch (err) {
      stopAgingTicker(S.targetAge);
      if (err.name === "AbortError") {
        console.log("Pipeline aborted by user.");
      } else {
        clearInterval(pipelineTimer);
        errorEl.style.display = "flex";
        errorEl.querySelector(".ea-text").textContent = err.message;
      }
    }
  }

  function markStepAdv(steps, activeIdx, progressPct, pctEl, progressEl) {
    return new Promise((r) => {
      // mark previous as pass
      for (let i = 0; i < activeIdx; i++) {
        steps[i].classList.remove("active");
        steps[i].classList.add("pass");
      }
      steps[activeIdx].classList.remove("pass");
      steps[activeIdx].classList.add("active");

      if (pctEl) pctEl.textContent = progressPct + "%";
      if (progressEl) progressEl.style.width = progressPct + "%";

      setTimeout(r, 50); // small visual tick
    });
  }

  // ══════════════════════════════════════════════════════════
  // STEP 6 — RESULTS
  // ══════════════════════════════════════════════════════════
  function initStep6() {
    $("#new-scan-btn").addEventListener("click", () => {
      resetAll();
      goTo(1);
    });

    // Slider Logic
    const slider = $("#res-slider-input");
    const overlay = $("#res-legacy-img");
    const handle = $("#res-slider-handle");
    if (slider && overlay && handle) {
      const onSlide = (e) => {
        const val = e.target.value;
        overlay.style.webkitClipPath = `polygon(0% 0%, ${val}% 0%, ${val}% 100%, 0% 100%)`;
        overlay.style.clipPath = `polygon(0% 0%, ${val}% 0%, ${val}% 100%, 0% 100%)`;
        handle.style.left = `${val}%`;
      };
      slider.addEventListener("input", onSlide);
      slider.addEventListener("change", onSlide);
    }
  }

  function populateResults() {
    const s = S.scan;
    if (!s) return;

    // Images
    $("#res-legacy-img").src = S.legacyUrl || "";
    $("#res-generated-img").src = S.generatedUrl || "";
    $("#res-live-img").src = S.liveUrl || "";

    // Multi-photo transparency note
    const multiNote = $("#res-multi-note");
    if (multiNote) {
      if (S.numLegacyPhotos > 1) {
        multiNote.textContent = `Best match selected from ${S.numLegacyPhotos} reference photos`;
        multiNote.style.display = "block";
      } else {
        multiNote.style.display = "none";
      }
    }

    // Badge
    const badge = $("#res-badge");
    const isPending = s.status === "pending_review";
    const isPass = s.status === "pass";
    if (isPass) {
      badge.textContent = "✓ Same Person";
      badge.className = "result-badge pass";
    } else if (isPending) {
      badge.textContent = "⚠ Pending Review";
      badge.className = "result-badge pending";
    } else {
      badge.textContent = "✕ Not Same Person";
      badge.className = "result-badge fail";
    }

    // Score
    const score = s.similarity_score != null ? s.similarity_score : "—";
    $("#res-score").textContent = score !== "—" ? score + "%" : "—";

    // Confidence bar
    const bar = $("#res-bar-fill");
    bar.style.width = "0%";
    if (score !== "—") {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          bar.style.width = Math.min(score, 100) + "%";
        });
      });
    }

    // Stats
    $("#res-age").textContent = s.target_age || "—";
    const gap = s.target_age && s.current_age ? Math.abs(s.target_age - s.current_age) : "—";
    $("#res-gap").textContent = gap !== "—" ? (s.target_age > s.current_age ? `+${gap} yrs` : `-${gap} yrs`) : "—";
    $("#res-threshold").textContent = s.threshold_used ? s.threshold_used + "%" : "—";
    $("#res-status").textContent = s.status || "—";
  }

  // ── Reset ──────────────────────────────────────────────
  function resetAll() {
    S.direction = "older";
    S.legacyFiles = [];
    S.primaryLegacyIndex = 0;
    S.liveFile = null;
    S.liveDataUrl = null;
    S.currentAge = 10;
    S.targetAge = 40;
    S.caseName = "";
    S.notes = "";
    S.scan = null;
    S.consentGiven = false;
    S.numLegacyPhotos = 1;
    S.legacyAgeEstimate = null;
    S.legacyAgeEstimating = false;
    S.presentAgeEstimate = null;
    S.presentAgeEstimating = false;
    updateAgeHints();

    // Reset step 1
    const dirOlder = $("#dir-older");
    const dirYounger = $("#dir-younger");
    if (dirOlder) dirOlder.classList.add("selected");
    if (dirYounger) dirYounger.classList.remove("selected");

    // Reset step 2
    legacyCameraMode = "upload";
    if (legacyStream) { legacyStream.getTracks().forEach((t) => t.stop()); legacyStream = null; }
    const dz1 = $("#legacy-dropzone");
    const grid1 = $("#legacy-photo-grid");
    if (dz1) dz1.style.display = "block";
    if (grid1) { grid1.innerHTML = ""; grid1.style.display = "none"; }
    const maxNote1 = $("#legacy-max-note");
    if (maxNote1) maxNote1.style.display = "none";
    const fi1 = $("#legacy-file-input");
    if (fi1) fi1.value = "";
    const nb = $("#step1-next-btn");
    if (nb) nb.disabled = true;
    // Reset legacy mode toggle to upload
    const legUpMode = $("#legacy-upload-mode");
    const legCamMode = $("#legacy-camera-mode");
    if (legUpMode) legUpMode.style.display = "block";
    if (legCamMode) legCamMode.style.display = "none";
    const legModeUpBtn = $("#legacy-mode-upload-btn");
    const legModeCamBtn = $("#legacy-mode-camera-btn");
    if (legModeUpBtn) { legModeUpBtn.classList.remove("btn-ghost"); legModeUpBtn.classList.add("btn-primary"); }
    if (legModeCamBtn) { legModeCamBtn.classList.remove("btn-primary"); legModeCamBtn.classList.add("btn-ghost"); }
    // Reset legacy camera UI
    const legVid = $("#legacy-video");
    const legCapImg = $("#legacy-captured-img");
    const legCapRow = $("#legacy-camera-capture-row");
    const legRevRow = $("#legacy-camera-review-row");
    if (legVid) legVid.style.display = "block";
    if (legCapImg) { legCapImg.style.display = "none"; legCapImg.src = ""; }
    if (legCapRow) legCapRow.style.display = "flex";
    if (legRevRow) legRevRow.style.display = "none";

    // Reset step 3
    const ss = $("#scan-screen");
    const us = $("#upload-screen");
    if (ss) ss.style.display = "block";
    if (us) us.style.display = "none";
    stopCamera();
    const udz = $("#live-upload-dropzone");
    const upw = $("#live-upload-preview-wrap");
    const ufi = $("#live-upload-file-input");
    const upi = $("#live-upload-preview-img");
    const ubtn = $("#step2-use-upload-btn");
    if (udz) udz.style.display = "block";
    if (upw) upw.style.display = "none";
    if (ufi) ufi.value = "";
    if (upi) upi.src = "";
    if (ubtn) ubtn.disabled = true;
    const ci = $("#captured-img");
    if (ci) ci.style.display = "none";
    const vid = $("#live-video");
    if (vid) vid.style.display = "block";
    const cvRow = $("#capture-row");
    const rvRow = $("#review-row");
    if (cvRow) cvRow.style.display = "none"; // hidden until scan step is entered
    if (rvRow) rvRow.style.display = "none";

    // Reset step 4
    const cai = $("#current-age-input");
    if (cai) cai.value = 10;
    const ts = $("#target-age-slider");
    const tv = $("#target-age-value");
    if (ts) ts.value = 40;
    if (tv) tv.value = 40;

    const cn = $("#case-name-input");
    const nt = $("#notes-input");
    if (cn) cn.value = "";
    if (nt) nt.value = "";
    const ccb = $("#consent-checkbox");
    if (ccb) { ccb.checked = false; }
    const cCard = $("#consent-card");
    if (cCard) { cCard.classList.remove("consent-agreed"); }
    const rb = $("#step3-run-btn");
    if (rb) rb.disabled = true;

    // Reset step 5
    $$("#pipeline-steps .fqa-item").forEach((s) => s.classList.remove("pass"));
    const pe = $("#pipeline-error");
    if (pe) pe.style.display = "none";
    stopAgingTicker(40);
    const orb4 = $("#futuristic-orb");
    if (orb4) orb4.classList.remove("aging-fx", "crossfade");
    const vsWrap4 = $("#proc-vs-wrap");
    if (vsWrap4) vsWrap4.classList.remove("show");
    const currentOrbWrap4 = $("#current-orb-wrap");
    if (currentOrbWrap4) currentOrbWrap4.classList.remove("show");
    const orbImgB4 = $("#futuristic-img-b");
    if (orbImgB4) orbImgB4.src = "";

    // Reset slider
    const slider = $("#res-slider-input");
    const overlay = $("#res-legacy-img");
    const handle = $("#res-slider-handle");
    if (slider && overlay && handle) {
      slider.value = 50;
      overlay.style.webkitClipPath = `polygon(0% 0%, 50% 0%, 50% 100%, 0% 100%)`;
      overlay.style.clipPath = `polygon(0% 0%, 50% 0%, 50% 100%, 0% 100%)`;
      handle.style.left = `50%`;
    }
  }

  // ── History Drawer ─────────────────────────────────────
  function initHistory() {
    const btn = $("#history-toggle-btn");
    const drawer = $("#history-drawer");
    const overlay = $("#history-overlay");
    const close = $("#history-close-btn");
    const open = () => { drawer.classList.add("open"); overlay.classList.add("open"); loadHistory(); };
    const shut = () => { drawer.classList.remove("open"); overlay.classList.remove("open"); };
    if (btn) btn.addEventListener("click", open);
    if (close) close.addEventListener("click", shut);
    if (overlay) overlay.addEventListener("click", shut);
  }

  async function loadHistory() {
    const list = $("#history-list");
    if (!list) return;
    try {
      const data = await (await fetch("/api/history")).json();
      if (data.length === 0) {
        list.innerHTML = '<div class="empty-state"><div class="es-icon">◎</div><p>No scans yet.</p></div>';
        return;
      }
      list.innerHTML = data.slice(0, 20).map((s) => `
        <div class="history-item">
          <img class="hi-thumb" src="${s.generated_photo_url || s.legacy_photo_url || ""}" alt="" onerror="this.style.display='none'">
          <div class="hi-meta">
            <div class="hi-title">${s.case_name || "Scan #" + s.id}</div>
            <div class="hi-date">${fmtTime(s.timestamp)}</div>
            ${s.similarity_score != null ? `<span class="badge badge-${s.status === "pass" ? "pass" : s.status === "pending_review" ? "pending" : "fail"}" style="margin-top:3px;">${s.similarity_score}%</span>` : ""}
          </div>
        </div>`).join("");
    } catch {
      list.innerHTML = '<div class="empty-state"><p>Could not load history.</p></div>';
    }
  }

  // ── Init ───────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => {
    resetAll();
    for (let i = 1; i <= TOTAL_STEPS; i++) cachePanel(i);
    initStep1();
    initStep2();
    initStep3();
    initStep4();
    initStep6();
    initHistory();

    fetch("/api/status").then(r => r.json()).then(d => {
      const badge = $("#device-badge");
      if (badge) {
        badge.textContent = d.device === "cpu" ? "CPU" : "GPU";
        if (d.device !== "cpu") badge.classList.add("badge-pass");
      }
      if (!d.model_loaded) toast("⚠ Model not loaded — run setup.sh first");
    }).catch(() => {});
  });
})();
