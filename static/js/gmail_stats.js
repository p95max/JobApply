document.addEventListener("DOMContentLoaded", () => {
  const daysSelect = document.getElementById("daysSelect");
  const btnRefresh = document.getElementById("btnRefresh");
  const btnSync = document.getElementById("btnSync");
  const alertBox = document.getElementById("alertBox");
  const metricEmails = document.getElementById("metricEmails");
  const metricRejections = document.getElementById("metricRejections");
  const metricInvites = document.getElementById("metricInvites");
  const metricAutoAck = document.getElementById("metricAutoAck");
  const syncStatusText = document.getElementById("syncStatusText");
  const cfg = document.getElementById("gmailStatsConfig");

  function showAlert(message, kind = "danger") {
    if (!alertBox) return;
    alertBox.className = `alert alert-${kind}`;
    alertBox.textContent = message;
    alertBox.classList.remove("d-none");
  }

  function hideAlert() {
    alertBox?.classList.add("d-none");
  }

  if (!cfg) {
    showAlert("Gmail statistics configuration is missing.");
    return;
  }

  const statsUrl = (cfg.dataset.statsUrl || "").trim();
  const syncUrl = (cfg.dataset.syncUrl || "").trim();

  async function loadStats() {
    hideAlert();
    const days = daysSelect?.value || "180";

    try {
      const response = await fetch(`${statsUrl}?days=${encodeURIComponent(days)}`, {
        headers: {Accept: "application/json"},
        credentials: "same-origin",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Failed to load statistics.");

      if (metricEmails) metricEmails.textContent = data.job_related_emails ?? "—";
      if (metricRejections) metricRejections.textContent = data.rejections ?? "—";
      if (metricInvites) metricInvites.textContent = data.invites ?? "—";
      if (metricAutoAck) metricAutoAck.textContent = data.auto_ack ?? "—";

      if (syncStatusText) {
        syncStatusText.textContent = data.last_synced_at
          ? new Date(data.last_synced_at).toLocaleString()
          : "Not synced yet";
      }
    } catch (error) {
      showAlert(error.message || "Failed to load statistics.");
    }
  }

  async function syncGmail() {
    hideAlert();
    const originalLabel = btnSync?.textContent || "Sync Gmail";
    if (btnSync) {
      btnSync.disabled = true;
      btnSync.textContent = "Syncing…";
    }

    try {
      const days = daysSelect?.value || "180";
      const response = await fetch(`${syncUrl}?days=${encodeURIComponent(days)}`, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        credentials: "same-origin",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Sync failed.");
      await loadStats();
      showAlert("Gmail sync completed.", "success");
    } catch (error) {
      showAlert(error.message || "Sync failed.");
    } finally {
      if (btnSync) {
        btnSync.disabled = false;
        btnSync.textContent = originalLabel;
      }
    }
  }

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    return parts.length === 2 ? parts.pop().split(";").shift() : "";
  }

  btnRefresh?.addEventListener("click", loadStats);
  btnSync?.addEventListener("click", syncGmail);
  daysSelect?.addEventListener("change", loadStats);
  loadStats();
});
