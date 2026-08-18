/* ============================================================
   VERITAS — Admin Dashboard Controller
   Tabs: Overview | Threshold Config | Discrepancy Queue
   ============================================================ */
(() => {
  "use strict";
  const { $, $$, toast, fmtTime, sleep, wireDropzone } = V;

  let currentTab = "overview";
  let queueData = [];
  let historyData = [];
  let currentThreshold = 75;
  let queueFilter = "all";
  let historySort = "newest";
  let queueSort = "newest";

  function timeAgo(dateString) {
    if (!dateString) return "unknown";
    const diff = (new Date() - new Date(dateString)) / 1000;
    if (diff < 60) return "just now";
    if (diff < 3600) return Math.floor(diff / 60) + " min ago";
    if (diff < 86400) return Math.floor(diff / 3600) + " hr ago";
    if (diff < 172800) return "yesterday";
    return Math.floor(diff / 86400) + " days ago";
  }

  function getScanStatusLabel(r) {
    if (r.status === "pass" || r.status === "resolved") return "resolved";
    if (r.status === "pending_review") return "pending";
    return "failed";
  }

  function getScanReason(r) {
    if (r.status === "pending_review") return "Borderline";
    if (r.status === "fail") {
      const shift = Math.abs(r.target_age - r.person_age);
      if (shift >= 40) return "Large age shift";
      if (r.similarity_score < 40) return "Low confidence";
      return "Failed";
    }
    return "Verified";
  }

  function renderScanCard(r, threshold, isQueue = false) {
    const sType = getScanStatusLabel(r);
    const reason = getScanReason(r);
    const shift = (r.target_age && r.person_age) ? Math.abs(r.target_age - r.person_age) : 0;
    const shiftStr = "+" + shift + " yrs";
    const user = r.case_name || "Unknown";
    const scoreStr = r.similarity_score != null ? r.similarity_score + "%" : "—";
    const scoreNum = r.similarity_score || 0;
    const clickFunc = isQueue ? `window._openCase(${r.id}, 'queue')` : `window._openCase(${r.id}, 'history')`;

    return `
      <div class="scan-card" data-id="${r.id}" onclick="${clickFunc}">
        <div class="sc-left">
          <div class="sc-row-top">
            <div class="sc-title">Scan #${r.id}</div>
            <div class="sc-pill ${sType}">${sType.toUpperCase()}</div>
          </div>
          <div class="sc-row-bottom">
            <span class="sc-reason">${reason}</span>
            <span>${shiftStr}</span>
            <span class="sc-user">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
              ${user}
            </span>
            <span>${timeAgo(r.timestamp)}</span>
          </div>
        </div>
        <div class="sc-right">
          <div class="sc-score ${sType}">${scoreStr}</div>
          <div class="sc-bar-wrap">
            <div class="sc-bar-fill ${sType}" style="width:${scoreNum}%"></div>
            <div class="sc-bar-tick" style="left:${threshold}%"></div>
          </div>
        </div>
      </div>
    `;
  }

  // ── Tab Navigation ─────────────────────────────────────
  function initTabs() {
    $$(".admin-nav a").forEach((link) => {
      link.addEventListener("click", (e) => {
        e.preventDefault();
        const tab = link.dataset.tab;
        if (!tab) return;
        switchTab(tab);
      });
    });
  }

  function switchTab(tab) {
    currentTab = tab;
    $$(".admin-nav a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
    $$(".admin-tab-content").forEach((p) => p.classList.toggle("active", p.id === `tab-${tab}`));

    if (tab === "overview") loadOverview();
    if (tab === "threshold") loadThreshold();
    if (tab === "queue") loadQueue();
    if (tab === "training") loadTraining();
  }

  function initBrandHome() {
    const brand = $("#admin-brand-btn");
    if (brand) {
      brand.addEventListener("click", (e) => {
        e.preventDefault();
        switchTab("overview");
      });
    }
  }

  // ══════════════════════════════════════════════════════════
  // OVERVIEW TAB
  // ══════════════════════════════════════════════════════════
  async function loadOverview() {
    try {
      const stats = await (await fetch("/api/stats")).json();
      const kpis = $("#kpi-grid");
      if (kpis) {
        kpis.innerHTML = `
          <div class="kpi"><div class="n">${stats.total_scans}</div><div class="l">Total Scans</div></div>
          <div class="kpi"><div class="n">${stats.pass_rate}%</div><div class="l">Pass Rate</div></div>
          <div class="kpi ${stats.flagged > 0 ? "warn" : ""}"><div class="n">${stats.flagged}</div><div class="l">Flagged</div></div>
          <div class="kpi"><div class="n">${stats.threshold}%</div><div class="l">Threshold</div></div>
        `;
      }

      const history = await (await fetch("/api/history")).json();
      const tbody = $("#recent-rows");
      if (tbody) {
        if (history.length === 0) {
          tbody.innerHTML = '<div style="color:var(--text-faint);">No scans recorded yet.</div>';
        } else {
          historyData = history;
          currentThreshold = stats.threshold || 75;
          renderOverview(currentThreshold);
        }
      }
    } catch (err) {
      console.error("Overview load error:", err);
    }
  }

  function renderOverview(threshold) {
    const tbody = $("#recent-rows");
    if (!tbody) return;

    if (historyData.length === 0) {
      tbody.innerHTML = '<div style="color:var(--text-faint);">No scans recorded yet.</div>';
      return;
    }

    let sorted = [...historyData];
    if (historySort === "score_desc") {
      sorted.sort((a, b) => (b.similarity_score || 0) - (a.similarity_score || 0));
    } else if (historySort === "score_asc") {
      sorted.sort((a, b) => (a.similarity_score || 0) - (b.similarity_score || 0));
    } else {
      sorted.sort((a, b) => b.id - a.id);
    }

    tbody.innerHTML = sorted.map((r) => renderScanCard(r, threshold, false)).join("");
  }

  // ══════════════════════════════════════════════════════════
  // THRESHOLD TAB
  // ══════════════════════════════════════════════════════════
  async function loadThreshold() {
    try {
      const data = await (await fetch("/api/threshold")).json();
      const slider = $("#threshold-slider");
      const val = $("#threshold-val");
      if (slider && val) {
        slider.value = data.threshold;
        val.textContent = data.threshold + "%";
      }
    } catch {}
  }

  function initThreshold() {
    const slider = $("#threshold-slider");
    const val = $("#threshold-val");
    const saveBtn = $("#threshold-save-btn");

    if (slider) {
      slider.addEventListener("input", () => {
        val.textContent = slider.value + "%";
      });
    }

    if (saveBtn) {
      saveBtn.addEventListener("click", async () => {
        try {
          const resp = await fetch("/api/threshold", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ threshold: parseInt(slider.value) }),
          });
          const data = await resp.json();
          if (data.success) {
            toast("Threshold updated to " + slider.value + "%");
          } else {
            toast("Error: " + (data.error || "Unknown"));
          }
        } catch (err) {
          toast("Failed to save threshold");
        }
      });
    }
  }

  // ══════════════════════════════════════════════════════════
  // QUEUE TAB
  // ══════════════════════════════════════════════════════════
  async function loadQueue() {
    try {
      const stats = await (await fetch("/api/stats")).json();
      currentThreshold = stats.threshold || 75;
      queueData = await (await fetch("/api/queue")).json();
      renderQueue(currentThreshold);
    } catch (err) {
      console.error("Queue load error:", err);
    }
  }

  function renderQueue(threshold = 75) {
    const tbody = $("#queue-rows");
    if (!tbody) return;

    let allC = 0, penC = 0, failC = 0, resC = 0;
    queueData.forEach(r => {
      allC++;
      const s = getScanStatusLabel(r);
      if (s === "pending") penC++;
      else if (s === "failed") failC++;
      else if (s === "resolved") resC++;
    });

    const fns = $$(".q-filter");
    if (fns.length === 4) {
      fns[0].querySelector(".qf-count").textContent = allC;
      fns[1].querySelector(".qf-count").textContent = penC;
      fns[2].querySelector(".qf-count").textContent = failC;
      fns[3].querySelector(".qf-count").textContent = resC;
    }

    let filtered = queueData.filter(r => {
      if (queueFilter === "all") return true;
      return getScanStatusLabel(r) === queueFilter;
    });

    if (queueSort === "score_desc") {
      filtered.sort((a, b) => (b.similarity_score || 0) - (a.similarity_score || 0));
    } else if (queueSort === "score_asc") {
      filtered.sort((a, b) => (a.similarity_score || 0) - (b.similarity_score || 0));
    } else {
      filtered.sort((a, b) => b.id - a.id);
    }

    if (filtered.length === 0) {
      tbody.innerHTML = '<div style="color:var(--text-faint);">Queue is empty — nothing needs review.</div>';
      $("#case-review-panel").style.display = "none";
      return;
    }

    tbody.innerHTML = filtered.map((item) => renderScanCard(item, threshold, true)).join("");
  }

  // ══════════════════════════════════════════════════════════
  // TRAINING DATA TAB (Step 6 — training data submission)
  // ══════════════════════════════════════════════════════════
  const TRAIN_STATUS_LABEL = { sent: "Sent", received: "Received", used: "Used in Training" };

  async function loadTraining() {
    const list = $("#training-rows");
    if (!list) return;
    try {
      const data = await (await fetch("/api/training")).json();
      if (data.length === 0) {
        list.innerHTML = '<div style="color:var(--text-faint);">No training data submitted yet.</div>';
        return;
      }
      list.innerHTML = data.map(renderTrainingRow).join("");
    } catch (err) {
      console.error("Training load error:", err);
      list.innerHTML = '<div style="color:var(--text-faint);">Could not load training submissions.</div>';
    }
  }

  function renderTrainingRow(t) {
    const label = TRAIN_STATUS_LABEL[t.status] || t.status;
    const pillCls = t.status === "used" ? "resolved" : t.status === "received" ? "pending" : "failed";
    const caseLabel = t.scan_id ? (t.scan_case_name || "Case SCN-" + String(t.scan_id).padStart(4, "0")) : "Standalone submission";
    let actionBtn = "";
    if (t.status === "sent") actionBtn = `<button class="btn btn-ghost btn-sm" onclick="window._advanceTraining(${t.id}, 'received')">Mark Received</button>`;
    else if (t.status === "received") actionBtn = `<button class="btn btn-ghost btn-sm" onclick="window._advanceTraining(${t.id}, 'used')">Mark Used in Training</button>`;

    return `
      <div class="scan-card" style="cursor:default;">
        <div class="sc-left" style="display:flex; gap:12px; align-items:center;">
          <div style="display:flex; gap:4px;">
            <img src="${t.old_photo_url || ""}" alt="" style="width:42px;height:42px;border-radius:8px;object-fit:cover;border:1px solid var(--border);background:var(--panel-2);" onerror="this.style.opacity=0.15">
            <img src="${t.current_photo_url || ""}" alt="" style="width:42px;height:42px;border-radius:8px;object-fit:cover;border:1px solid var(--border);background:var(--panel-2);" onerror="this.style.opacity=0.15">
          </div>
          <div>
            <div class="sc-title">${caseLabel}</div>
            <div class="sc-row-bottom">
              <span class="sc-reason">${t.note || "No note"}</span>
              <span>${timeAgo(t.timestamp)}</span>
            </div>
          </div>
        </div>
        <div class="sc-right" style="align-items:flex-end;">
          <div class="sc-pill ${pillCls}">${label.toUpperCase()}</div>
          <div style="margin-top:8px;">${actionBtn}</div>
        </div>
      </div>`;
  }

  window._advanceTraining = async function (id, status) {
    try {
      const resp = await fetch(`/api/training/${id}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      const data = await resp.json();
      if (data.success) {
        toast("Marked as " + (TRAIN_STATUS_LABEL[status] || status));
        loadTraining();
      } else {
        toast("Error: " + (data.error || "Unknown"));
      }
    } catch {
      toast("Failed to update status");
    }
  };

  // ── Case Review: Training Data Submission Form ─────────
  let crTrainOldFile = null;
  let crTrainCurrentFile = null;

  function resetCrTrainingForm() {
    crTrainOldFile = null;
    crTrainCurrentFile = null;
    const odz = $("#cr-train-old-dropzone"), opw = $("#cr-train-old-preview-wrap"), oi = $("#cr-train-old-input");
    const cdz = $("#cr-train-current-dropzone"), cpw = $("#cr-train-current-preview-wrap"), ci = $("#cr-train-current-input");
    if (odz) odz.style.display = "block";
    if (opw) opw.style.display = "none";
    if (oi) oi.value = "";
    if (cdz) cdz.style.display = "block";
    if (cpw) cpw.style.display = "none";
    if (ci) ci.value = "";
    const note = $("#cr-train-note");
    if (note) note.value = "";
    const btn = $("#cr-train-submit-btn");
    if (btn) btn.disabled = true;
  }

  function updateCrTrainSubmitState() {
    const btn = $("#cr-train-submit-btn");
    if (btn) btn.disabled = !(crTrainOldFile && crTrainCurrentFile);
  }

  function initCrTrainingForm() {
    const odz = $("#cr-train-old-dropzone"), ofi = $("#cr-train-old-input");
    const opw = $("#cr-train-old-preview-wrap"), opi = $("#cr-train-old-preview-img"), orb = $("#cr-train-old-remove-btn");
    const cdz = $("#cr-train-current-dropzone"), cfi = $("#cr-train-current-input");
    const cpw = $("#cr-train-current-preview-wrap"), cpi = $("#cr-train-current-preview-img"), crb = $("#cr-train-current-remove-btn");
    const submitBtn = $("#cr-train-submit-btn");

    if (odz && ofi) {
      wireDropzone(odz, ofi, (file) => {
        crTrainOldFile = file;
        const r = new FileReader();
        r.onload = (e) => {
          opi.src = e.target.result;
          odz.style.display = "none";
          opw.style.display = "block";
          updateCrTrainSubmitState();
        };
        r.readAsDataURL(file);
      });
    }
    if (orb) orb.addEventListener("click", () => {
      crTrainOldFile = null;
      opi.src = "";
      opw.style.display = "none";
      odz.style.display = "block";
      ofi.value = "";
      updateCrTrainSubmitState();
    });

    if (cdz && cfi) {
      wireDropzone(cdz, cfi, (file) => {
        crTrainCurrentFile = file;
        const r = new FileReader();
        r.onload = (e) => {
          cpi.src = e.target.result;
          cdz.style.display = "none";
          cpw.style.display = "block";
          updateCrTrainSubmitState();
        };
        r.readAsDataURL(file);
      });
    }
    if (crb) crb.addEventListener("click", () => {
      crTrainCurrentFile = null;
      cpi.src = "";
      cpw.style.display = "none";
      cdz.style.display = "block";
      cfi.value = "";
      updateCrTrainSubmitState();
    });

    if (submitBtn) {
      submitBtn.addEventListener("click", async () => {
        const panel = $("#case-review-panel");
        const scanId = panel.dataset.scanId;
        if (!crTrainOldFile || !crTrainCurrentFile) return;

        const fd = new FormData();
        fd.append("old_image", crTrainOldFile);
        fd.append("current_image", crTrainCurrentFile);
        fd.append("note", ($("#cr-train-note") || {}).value || "");
        if (scanId) fd.append("scan_id", scanId);

        submitBtn.disabled = true;
        submitBtn.textContent = "Submitting…";
        try {
          const resp = await fetch("/api/training/submit", { method: "POST", body: fd });
          const data = await resp.json();
          if (data.success) {
            toast("Training pair submitted");
            resetCrTrainingForm();
          } else {
            toast("Error: " + (data.error || "Unknown"));
          }
        } catch {
          toast("Failed to submit training pair");
        } finally {
          submitBtn.textContent = "Submit Training Pair";
          updateCrTrainSubmitState();
        }
      });
    }
  }

  // ── Case Review ────────────────────────────────────────
  window._openCase = function (id, source = "queue") {
    const scan = (source === "history" ? historyData : queueData).find((s) => s.id === id);
    if (!scan) return;

    if (source === "history") {
        switchTab("queue");
    }

    const panel = $("#case-review-panel");
    panel.style.display = "block";
    panel.dataset.scanId = id;
    resetCrTrainingForm();

    // Fill in data
    $("#cr-case-name").textContent = scan.case_name || "Scan #" + scan.id;
    $("#cr-case-id").textContent = "SCN-" + String(scan.id).padStart(4, "0");

    // Images
    const legacyImg = $("#cr-legacy-img");
    const genImg = $("#cr-generated-img");
    const liveImg = $("#cr-live-img");
    if (legacyImg) legacyImg.src = scan.legacy_photo_url || "";
    if (genImg) genImg.src = scan.generated_photo_url || "";
    if (liveImg) liveImg.src = scan.live_photo_url || "";

    // Stats
    const scoreEl = $("#cr-score");
    const ageEl = $("#cr-age");
    if (scoreEl) scoreEl.textContent = scan.similarity_score != null ? scan.similarity_score + "%" : "—";
    if (ageEl) ageEl.textContent = scan.person_age || "—";
    
    // Hide resolve buttons if not pending review
    const resolveArea = $("#cr-resolve-area");
    if (resolveArea) {
        resolveArea.style.display = scan.status === "pending_review" ? "block" : "none";
    }

    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  function initCaseReview() {
    const approveBtn = $("#cr-approve-btn");
    const rejectBtn = $("#cr-reject-btn");
    const deleteBtn = $("#cr-delete-btn");

    if (approveBtn) {
      approveBtn.addEventListener("click", () => resolveCase("approved"));
    }
    if (rejectBtn) {
      rejectBtn.addEventListener("click", () => resolveCase("rejected"));
    }
    if (deleteBtn) {
      deleteBtn.addEventListener("click", deleteCase);
    }
  }

  async function deleteCase() {
    const panel = $("#case-review-panel");
    const scanId = panel.dataset.scanId;
    if (!scanId) return;

    if (!confirm(`Are you sure you want to delete Case SCN-${String(scanId).padStart(4, "0")}? This cannot be undone.`)) {
      return;
    }

    try {
      const resp = await fetch(`/api/scan/${scanId}`, { method: "DELETE" });
      const data = await resp.json();
      if (data.success) {
        toast("Case deleted successfully");
        panel.style.display = "none";
        loadOverview();
        loadQueue();
      } else {
        toast("Error deleting case");
      }
    } catch (err) {
      toast("Failed to delete case");
    }
  }

  async function resolveCase(resolution) {
    const panel = $("#case-review-panel");
    const scanId = panel.dataset.scanId;
    if (!scanId) return;

    const note = ($("#cr-note") || {}).value || "";

    try {
      const resp = await fetch("/api/queue/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scan_id: parseInt(scanId), resolution, reviewer_note: note }),
      });
      const data = await resp.json();
      if (data.success) {
        toast(resolution === "approved" ? "Case marked as Same Person" : "Case marked as Not Same Person");
        panel.style.display = "none";
        loadQueue();
      } else {
        toast("Error: " + (data.error || "Unknown"));
      }
    } catch (err) {
      toast("Failed to resolve case");
    }
  }

  // ── Logout ─────────────────────────────────────────────
  function initLogout() {
    const btn = $("#admin-logout-btn");
    if (btn) {
      btn.addEventListener("click", () => {
        if (confirm("Log out of Veritas Admin?")) {
          window.location.href = "/admin-login";
        }
      });
    }
  }

  function initQueueFilters() {
    $$(".q-filter").forEach(btn => {
      btn.addEventListener("click", () => {
        $$(".q-filter").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        queueFilter = btn.dataset.filter;
        renderQueue(currentThreshold);
      });
    });

    const historySortSel = $("#history-sort");
    if (historySortSel) {
      historySortSel.addEventListener("change", (e) => {
        historySort = e.target.value;
        renderOverview(currentThreshold);
      });
    }

    const queueSortSel = $("#queue-sort");
    if (queueSortSel) {
      queueSortSel.addEventListener("change", (e) => {
        queueSort = e.target.value;
        renderQueue(currentThreshold);
      });
    }
  }

  // ── Init ───────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    initThreshold();
    initCaseReview();
    initCrTrainingForm();
    initLogout();
    initQueueFilters();
    initBrandHome();
    loadOverview();
  });
})();
