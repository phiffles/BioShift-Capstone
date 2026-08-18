/* ============================================================
   VERITAS — Home Page Controller
   Recent scans list + tap-to-open detail view
   ============================================================ */
(() => {
  "use strict";
  const { $, fmtTime } = V;

  let historyData = [];

  function timeAgo(dateString) {
    if (!dateString) return "unknown";
    const diff = (new Date() - new Date(dateString)) / 1000;
    if (diff < 60) return "just now";
    if (diff < 3600) return Math.floor(diff / 60) + " min ago";
    if (diff < 86400) return Math.floor(diff / 3600) + " hr ago";
    if (diff < 172800) return "yesterday";
    return Math.floor(diff / 86400) + " days ago";
  }

  function statusInfo(r) {
    if (r.status === "pass") return { cls: "resolved", text: "Same Person" };
    if (r.status === "pending_review") return { cls: "pending", text: "Pending Review" };
    return { cls: "failed", text: "Not Same Person" };
  }

  function renderCard(r) {
    const st = statusInfo(r);
    const gap = (r.target_age != null && r.current_age != null) ? Math.abs(r.target_age - r.current_age) : null;
    const scoreStr = r.similarity_score != null ? r.similarity_score + "%" : "—";
    const scoreNum = r.similarity_score || 0;

    return `
      <div class="scan-card" data-id="${r.id}" onclick="window._openHomeCase(${r.id})">
        <div class="sc-left">
          <div class="sc-row-top">
            <div class="sc-title">${r.case_name || "Scan #" + r.id}</div>
            <div class="sc-pill ${st.cls}">${st.text}</div>
          </div>
          <div class="sc-row-bottom">
            ${gap != null ? `<span>${gap} yrs gap</span>` : ""}
            <span>${timeAgo(r.timestamp)}</span>
          </div>
        </div>
        <div class="sc-right">
          <div class="sc-score ${st.cls}">${scoreStr}</div>
          <div class="sc-bar-wrap"><div class="sc-bar-fill ${st.cls}" style="width:${scoreNum}%"></div></div>
        </div>
      </div>`;
  }

  async function loadRecent() {
    const list = $("#home-scan-list");
    if (!list) return;
    try {
      const data = await (await fetch("/api/history")).json();
      historyData = data;
      if (data.length === 0) {
        list.innerHTML = '<div class="empty-state"><div class="es-icon">◎</div><p>No scans yet — start your first verification above.</p></div>';
        return;
      }
      const sorted = [...data].sort((a, b) => b.id - a.id);
      list.innerHTML = sorted.map(renderCard).join("");
    } catch {
      list.innerHTML = '<div class="empty-state"><p>Could not load recent scans.</p></div>';
    }
  }

  window._openHomeCase = function (id) {
    const scan = historyData.find((s) => s.id === id);
    if (!scan) return;

    $("#home-list-section").style.display = "none";
    const panel = $("#home-detail-panel");
    panel.style.display = "block";

    $("#hd-case-id").textContent = "SCN-" + String(scan.id).padStart(4, "0");
    $("#hd-case-name").textContent = scan.case_name || "Scan #" + scan.id;
    $("#hd-date").textContent = fmtTime(scan.timestamp);

    $("#hd-legacy-img").src = scan.legacy_photo_url || "";
    $("#hd-generated-img").src = scan.generated_photo_url || "";
    $("#hd-live-img").src = scan.live_photo_url || "";

    $("#hd-score").textContent = scan.similarity_score != null ? scan.similarity_score + "%" : "—";
    const gap = (scan.target_age != null && scan.current_age != null) ? Math.abs(scan.target_age - scan.current_age) : null;
    $("#hd-gap").textContent = gap != null ? gap + " yrs" : "—";

    const st = statusInfo(scan);
    const badge = $("#hd-badge");
    badge.textContent = st.text;
    badge.className = "result-badge " + (st.cls === "resolved" ? "pass" : st.cls === "pending" ? "pending" : "fail");

    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  function initBack() {
    const back = $("#home-detail-back");
    if (back) back.addEventListener("click", (e) => {
      e.preventDefault();
      $("#home-detail-panel").style.display = "none";
      $("#home-list-section").style.display = "block";
    });
  }

  function initNewScan() {
    const btn = $("#new-scan-cta");
    if (btn) btn.addEventListener("click", () => { window.location.href = "/scan"; });
  }

  // ── Age Estimator — now its own guided page, independent of the scan flow ──
  function initAgeEstimator() {
    const toggleBtn = $("#age-estimator-toggle-btn");
    if (toggleBtn) toggleBtn.addEventListener("click", () => { window.location.href = "/age-estimator"; });
  }


  function initLogout() {
    const btn = $("#home-logout-btn");
    if (btn) btn.addEventListener("click", () => {
      if (confirm("Log out of BS BioShifting?")) window.location.href = "/";
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initNewScan();
    initAgeEstimator();
    initBack();
    initLogout();
    loadRecent();
  });
})();
