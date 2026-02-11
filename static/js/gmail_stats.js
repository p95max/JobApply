console.log("GMAIL_STATS_JS_LOADED_VERSION=2026-02-11");


document.addEventListener("DOMContentLoaded", () => {
  const daysSelect = document.getElementById("daysSelect");
  const btnRefresh = document.getElementById("btnRefresh");
  const btnSync = document.getElementById("btnSync");

  const alertBox = document.getElementById("alertBox");
  const metricResponses = document.getElementById("metricResponses");
  const metricRejections = document.getElementById("metricRejections");
  const metricInvites = document.getElementById("metricInvites");
  const metricAutoAck = document.getElementById("metricAutoAck");
  const syncStatusText = document.getElementById("syncStatusText");

  function showAlert(message, kind = "danger") {
    if (!alertBox) return;
    alertBox.className = "alert alert-" + kind;
    alertBox.textContent = message;
    alertBox.classList.remove("d-none");
  }

  function hideAlert() {
    if (!alertBox) return;
    alertBox.classList.add("d-none");
  }

  const cfg = document.getElementById("gmailStatsConfig");
  if (!cfg) {
    showAlert("Missing #gmailStatsConfig in HTML. Put it inside {% block content %}.", "danger");
    return;
  }

  const STATS_URL = (cfg.dataset.statsUrl || "").trim();
  const SYNC_URL = (cfg.dataset.syncUrl || "").trim();

  console.log("[gmail_stats] statsUrl=", STATS_URL, "syncUrl=", SYNC_URL);

  if (!STATS_URL || STATS_URL.includes("{%")) {
    showAlert(
      "statsUrl is not rendered (contains '{% ... %}'). You are editing a different template OR server didn't reload the file. Check View Page Source for data-stats-url.",
      "danger"
    );
    return;
  }

  if (!SYNC_URL || SYNC_URL.includes("{%")) {
    showAlert(
      "syncUrl is not rendered (contains '{% ... %}'). Check View Page Source for data-sync-url.",
      "danger"
    );
    return;
  }

  async function loadStats() {
    hideAlert();
    const days = daysSelect?.value || "180";

    const resp = await fetch(`${STATS_URL}?days=${encodeURIComponent(days)}`, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });

    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      showAlert(data.error || "Failed to load stats.");
      return;
    }

    if (metricResponses) metricResponses.textContent = data.responses ?? "—";
    if (metricRejections) metricRejections.textContent = data.rejections ?? "—";
    if (metricInvites) metricInvites.textContent = data.invites ?? "—";
    if (metricAutoAck) metricAutoAck.textContent = data.auto_ack ?? "—";
  }

  async function syncGmail() {
    hideAlert();
    if (btnSync) {
      btnSync.disabled = true;
      btnSync.textContent = "Syncing...";
    }

    const days = daysSelect?.value || "180";

    try {
      const resp = await fetch(`${SYNC_URL}?days=${encodeURIComponent(days)}`, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        credentials: "same-origin",
      });

      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        showAlert(data.error || "Sync failed.");
        return;
      }

      const r = data.result || {};
      if (syncStatusText) {
        syncStatusText.textContent =
          `Synced. Created: ${r.created ?? 0}, skipped: ${r.skipped_existing ?? 0}, candidates: ${r.fetched_candidates ?? 0}.`;
      }

      await loadStats();
      showAlert("Sync completed.", "success");
    } catch (e) {
      showAlert("Sync failed: " + String(e));
    } finally {
      if (btnSync) {
        btnSync.disabled = false;
        btnSync.textContent = "Sync Gmail";
      }
    }
  }

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  }

  btnRefresh?.addEventListener("click", loadStats);
  btnSync?.addEventListener("click", syncGmail);
  daysSelect?.addEventListener("change", loadStats);

  loadStats();
});

