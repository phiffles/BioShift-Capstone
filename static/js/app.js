/* ============================================================
   VERITAS — Shared Utilities
   ============================================================ */

const V = (() => {
  "use strict";

  const $ = (sel, ctx) => (ctx || document).querySelector(sel);
  const $$ = (sel, ctx) => (ctx || document).querySelectorAll(sel);

  // ── Toast ────────────────────────────────────────────
  function toast(msg) {
    let t = $(".toast");
    if (!t) {
      t = document.createElement("div");
      t.className = "toast";
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.remove("show"), 3000);
  }

  // ── File to DataURL ──────────────────────────────────
  function fileToDataURL(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(r.result);
      r.onerror = reject;
      r.readAsDataURL(file);
    });
  }

  // ── Dropzone wiring ──────────────────────────────────
  function wireDropzone(dropzoneEl, fileInputEl, onFile) {
    dropzoneEl.addEventListener("click", () => fileInputEl.click());
    dropzoneEl.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropzoneEl.classList.add("dragover");
    });
    dropzoneEl.addEventListener("dragleave", () => {
      dropzoneEl.classList.remove("dragover");
    });
    dropzoneEl.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzoneEl.classList.remove("dragover");
      const f = e.dataTransfer.files;
      if (f.length > 0 && f[0].type.startsWith("image/")) onFile(f[0]);
    });
    fileInputEl.addEventListener("change", (e) => {
      if (e.target.files.length > 0) onFile(e.target.files[0]);
    });
  }

  // ── Format timestamp ─────────────────────────────────
  function fmtTime(ts) {
    if (!ts) return "";
    try {
      return new Date(ts).toLocaleDateString("en-US", {
        month: "short", day: "numeric", year: "numeric",
        hour: "2-digit", minute: "2-digit",
      });
    } catch { return ts; }
  }

  // ── Sleep ────────────────────────────────────────────
  function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

  // ── Theme Management ──────────────────────────────────
  function initTheme() {
    const saved = localStorage.getItem('theme') || 'dark';
    setTheme(saved, false);

    document.querySelectorAll('.theme-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme') || 'dark';
        setTheme(current === 'dark' ? 'light' : 'dark', true);
      });
    });
  }

  function setTheme(theme, animate) {
    if (animate) {
      document.documentElement.classList.add('theme-transition');
      setTimeout(() => document.documentElement.classList.remove('theme-transition'), 300);
    }
    
    if (theme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
      localStorage.setItem('theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
      localStorage.setItem('theme', 'dark');
    }
    
    updateThemeIcons(theme);
    
    // Dispatch event for particles.js
    window.dispatchEvent(new CustomEvent('themechanged', { detail: { theme } }));
  }

  function updateThemeIcons(theme) {
    document.querySelectorAll('.theme-toggle').forEach(btn => {
      const sun = btn.querySelector('.sun-icon');
      const moon = btn.querySelector('.moon-icon');
      if (sun && moon) {
        if (theme === 'light') {
          sun.style.display = 'block';
          moon.style.display = 'none';
        } else {
          sun.style.display = 'none';
          moon.style.display = 'block';
        }
      }
    });
  }

  // ── Console Boot Sequence (used for the login boot/auth overlays) ──
  function runConsoleSequence(opts) {
    const { overlay, linesEl, fillEl, pctEl, lines } = opts;
    const lineDelay = opts.lineDelay || 550;
    const holdAfter = opts.holdAfter || 700;
    return new Promise((resolve) => {
      let skip = false;
      if (overlay) overlay.addEventListener('click', () => { skip = true; }, { once: true });
      linesEl.innerHTML = '';
      if (fillEl) fillEl.style.width = '0%';
      if (pctEl) pctEl.textContent = '0%';
      let i = 0;
      function next() {
        if (i < lines.length) {
          const div = document.createElement('div');
          div.className = 'boot-line';
          div.textContent = lines[i];
          linesEl.appendChild(div);
          i++;
          const pct = Math.round((i / lines.length) * 100);
          if (fillEl) fillEl.style.width = pct + '%';
          if (pctEl) pctEl.textContent = pct + '%';
          setTimeout(next, skip ? 30 : lineDelay);
        } else {
          setTimeout(resolve, skip ? 100 : holdAfter);
        }
      }
      next();
    });
  }

  // ── Age Estimator widget (upload/camera/estimate wiring for the standalone
  //    /age-estimator page. It reaches its markup through a `${prefix}-*` id
  //    namespace, from back when the same widget was embedded in two pages at
  //    once — which is still what would let it be mounted twice.) ──
  function initAgeEstimatorCore(prefix, opts) {
    opts = opts || {};
    const id = (suffix) => document.getElementById(`${prefix}-${suffix}`);

    const modeUploadBtn = id("mode-upload-btn");
    const modeCameraBtn = id("mode-camera-btn");
    const uploadMode = id("upload-mode");
    const cameraMode = id("camera-mode");

    const dz = id("dropzone");
    const fi = id("file-input");
    const previewWrap = id("preview-wrap");
    const previewImg = id("preview-img");
    const previewRemoveBtn = id("preview-remove-btn");

    const video = id("video");
    const capturedImg = id("captured-img");
    const canvas = id("canvas");
    const captureRow = id("camera-capture-row");
    const retakeRow = id("camera-retake-row");
    const captureBtn = id("camera-capture-btn");
    const retakeBtn = id("camera-retake-btn");
    // Optional — only the camera-first pages carry a live status pill and a
    // "couldn't reach your camera" fallback card.
    const statusPill = id("camera-status");
    const statusText = id("camera-status-text");
    const cameraFallback = id("camera-fallback");

    const estimateBtn = id("estimate-btn");
    const resultBox = id("result");
    const resultValue = id("result-value");
    const resultLabel = id("result-label");
    const resultMeta = id("result-meta");
    const resultFaces = id("result-faces");
    const annotatedWrap = id("annotated-wrap");
    const annotatedImg = id("annotated-img");

    // Markup not present on this page (e.g. widget not embedded here) — skip.
    if (!estimateBtn || !dz || !fi) return null;

    // Pages that lead with the live scan pass defaultMode:"camera"; everything
    // else keeps opening on the dropzone.
    const defaultMode = opts.defaultMode === "camera" ? "camera" : "upload";
    let mode = defaultMode;
    let photoFile = null;
    let stream = null;

    function setStatus(text, ok) {
      if (!statusPill || !statusText) return;
      statusText.textContent = text;
      statusPill.className = ok ? "fqa-pill ok" : "fqa-pill";
    }

    function resetResult() {
      resultBox.style.display = "none";
      resultValue.textContent = "—";
      resultLabel.textContent = "Estimated Age";
      resultMeta.style.display = "none";
      resultMeta.textContent = "";
      if (resultFaces) { resultFaces.style.display = "none"; resultFaces.textContent = ""; }
      if (annotatedWrap) annotatedWrap.style.display = "none";
      if (annotatedImg) annotatedImg.src = "";
      const applyBtn = id("apply-btn");
      if (applyBtn) applyBtn.style.display = "none";
    }

    function setPhoto(file) {
      photoFile = file;
      estimateBtn.disabled = !photoFile;
      resetResult();
    }

    function stopCamera() {
      if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
    }

    async function startCamera() {
      setStatus("Starting camera…", false);
      if (cameraFallback) cameraFallback.style.display = "none";
      try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error("No camera API");
        // Ask for a real resolution — the browser default is typically 640x480,
        // which the age classifier then has to work from. `ideal` falls back
        // gracefully on webcams that can't manage 1080p.
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: "user",
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
        });
        video.srcObject = stream;
        setStatus("Center your face in the frame", true);
      } catch (err) {
        toast("Couldn't access camera");
        setStatus("Camera unavailable", false);
        // On a camera-first page a dead camera would otherwise leave a blank
        // stage, so surface the upload route right where the user is looking.
        if (cameraFallback) cameraFallback.style.display = "block";
      }
    }

    function setMode(next) {
      mode = next;
      modeUploadBtn.className = next === "upload" ? "btn btn-primary btn-sm" : "btn btn-ghost btn-sm";
      modeCameraBtn.className = next === "camera" ? "btn btn-primary btn-sm" : "btn btn-ghost btn-sm";
      uploadMode.style.display = next === "upload" ? "block" : "none";
      cameraMode.style.display = next === "camera" ? "block" : "none";
      setPhoto(null);

      if (next === "camera") {
        video.style.display = "block";
        capturedImg.style.display = "none";
        captureRow.style.display = "flex";
        retakeRow.style.display = "none";
        startCamera();
      } else {
        stopCamera();
        if (cameraFallback) cameraFallback.style.display = "none";
      }
    }

    modeUploadBtn.addEventListener("click", () => setMode("upload"));
    modeCameraBtn.addEventListener("click", () => setMode("camera"));

    wireDropzone(dz, fi, (file) => {
      setPhoto(file);
      const r = new FileReader();
      r.onload = (e) => {
        previewImg.src = e.target.result;
        dz.style.display = "none";
        previewWrap.style.display = "block";
      };
      r.readAsDataURL(file);
    });
    function clearPreview() {
      setPhoto(null);
      previewImg.src = "";
      previewWrap.style.display = "none";
      dz.style.display = "block";
      fi.value = "";
    }

    previewRemoveBtn.addEventListener("click", () => {
      clearPreview();
    });

    captureBtn.addEventListener("click", () => {
      canvas.width = video.videoWidth || 480;
      canvas.height = video.videoHeight || 640;
      const ctx = canvas.getContext("2d");
      ctx.translate(canvas.width, 0);
      ctx.scale(-1, 1);
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
      capturedImg.src = dataUrl;
      capturedImg.style.display = "block";
      video.style.display = "none";
      captureRow.style.display = "none";
      retakeRow.style.display = "flex";
      stopCamera();
      setStatus("Photo captured", true);
      fetch(dataUrl).then((r) => r.blob()).then((blob) => {
        setPhoto(new File([blob], "capture.jpg", { type: "image/jpeg" }));
      });
    });

    retakeBtn.addEventListener("click", () => {
      capturedImg.style.display = "none";
      video.style.display = "block";
      captureRow.style.display = "flex";
      retakeRow.style.display = "none";
      setPhoto(null);
      startCamera();
    });

    estimateBtn.addEventListener("click", async () => {
      if (!photoFile) return;
      estimateBtn.disabled = true;
      estimateBtn.textContent = "Estimating…";
      try {
        const fd = new FormData();
        fd.append("image", photoFile);
        const resp = await fetch("/api/estimate-age", { method: "POST", body: fd });
        const data = await resp.json();
        if (!resp.ok || data.error) throw new Error(data.error || "Could not estimate age");

        resultValue.textContent = data.age;
        resultLabel.textContent = "Estimated Age";

        if (data.confidence != null) {
          const pct = Math.round(data.confidence * 100);
          const sureness = pct >= 80 ? "high" : pct >= 50 ? "moderate" : "low";
          resultMeta.textContent = `${sureness} confidence (${pct}% of the estimate falls within ±5 years)`;
          resultMeta.style.display = "block";
        }

        if (data.annotated_url && annotatedWrap && annotatedImg) {
          annotatedImg.src = data.annotated_url;
          annotatedWrap.style.display = "block";
        }

        if (data.face_count > 1 && resultFaces) {
          const others = data.faces.slice(1).map((f) => f.age).join(", ");
          resultFaces.textContent = `${data.face_count} faces detected — showing the largest. Others: ${others}`;
          resultFaces.style.display = "block";
        }

        resultBox.style.display = "block";
        // .content is its own scroll container, so a freshly revealed result
        // can sit below the fold — bring it into view.
        resultBox.scrollIntoView({ behavior: "smooth", block: "nearest" });

        if (opts.onResult) opts.onResult(data);
      } catch (err) {
        resultValue.textContent = "—";
        resultLabel.textContent = err.message;
        resultBox.style.display = "block";
        resultBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } finally {
        estimateBtn.disabled = !photoFile;
        estimateBtn.textContent = "Estimate Age";
      }
    });

    function reset() {
      stopCamera();
      clearPreview();
      setMode(defaultMode);
    }

    if (defaultMode === "camera") setMode("camera");

    return { setMode, stopCamera, reset };
  }

  document.addEventListener('DOMContentLoaded', initTheme);

  return { $, $$, toast, fileToDataURL, wireDropzone, fmtTime, sleep, runConsoleSequence, initAgeEstimatorCore };
})();
