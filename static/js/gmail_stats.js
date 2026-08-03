document.addEventListener("DOMContentLoaded", () => {
  const daysSelect = document.getElementById("daysSelect");
  const btnRefresh = document.getElementById("btnRefresh");
  const alertBox = document.getElementById("alertBox");
  const metricEmails = document.getElementById("metricEmails");
  const metricRejections = document.getElementById("metricRejections");
  const metricInvites = document.getElementById("metricInvites");
  const metricAutoAck = document.getElementById("metricAutoAck");
  const syncStatusText = document.getElementById("syncStatusText");
  const config = document.getElementById("gmailStatsConfig");

  function showAlert(message) {
    if (!alertBox) return;
    alertBox.className = "alert alert-danger";
    alertBox.textContent = message;
    alertBox.classList.remove("d-none");
  }

  function hideAlert() {
    alertBox?.classList.add("d-none");
  }

  if (!config?.dataset.statsUrl) {
    showAlert("Gmail statistics configuration is missing.");
    return;
  }

  async function loadStats() {
    hideAlert();
    const days = daysSelect?.value || "180";
    const originalLabel = btnRefresh?.textContent || "Refresh";

    if (btnRefresh) {
      btnRefresh.disabled = true;
      btnRefresh.textContent = "…";
    }

    try {
      const response = await fetch(
        `${config.dataset.statsUrl}?days=${encodeURIComponent(days)}`,
        {headers: {Accept: "application/json"}, credentials: "same-origin"},
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Failed to load statistics.");

      if (metricEmails) metricEmails.textContent = data.job_related_emails ?? "—";
      if (metricRejections) metricRejections.textContent = data.rejections ?? "—";
      if (metricInvites) metricInvites.textContent = data.invites ?? "—";
      if (metricAutoAck) metricAutoAck.textContent = data.auto_ack ?? "—";
      if (syncStatusText) {
        syncStatusText.textContent = data.last_synced_at
          ? new Date(data.last_synced_at).toLocaleString()
          : "—";
      }
    } catch (error) {
      showAlert(error.message || "Failed to load statistics.");
    } finally {
      if (btnRefresh) {
        btnRefresh.disabled = false;
        btnRefresh.textContent = originalLabel;
      }
    }
  }

  btnRefresh?.addEventListener("click", loadStats);
  daysSelect?.addEventListener("change", loadStats);
  loadStats();
});
