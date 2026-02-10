(function () {
  const daysSelect = document.getElementById("daysSelect");
  const btnRefresh = document.getElementById("btnRefresh");
  const btnSync = document.getElementById("btnSync");

  const alertBox = document.getElementById("alertBox");
  const metricResponses = document.getElementById("metricResponses");
  const metricRejections = document.getElementById("metricRejections");
  const metricInvites = document.getElementById("metricInvites");
  const metricAutoAck = document.getElementById("metricAutoAck");
  const syncStatusText = document.getElementById("syncStatusText");

  const STATS_URL = "{% url 'gmail_stats_api' %}";
  const SYNC_URL = "{% url 'gmail_sync_api' %}";

  function showAlert(message, kind="danger") {
    alertBox.className = "alert alert-" + kind;
    alertBox.textContent = message;
    alertBox.classList.remove("d-none");
  }

  function hideAlert() {
    alertBox.classList.add("d-none");
  }

  async function loadStats() {
    hideAlert();
    const days = daysSelect.value;

    const resp = await fetch(`${STATS_URL}?days=${encodeURIComponent(days)}`, {
      headers: { "Accept": "application/json" },
      credentials: "same-origin",
    });

    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      showAlert(data.error || "Failed to load stats.");
      return;
    }

    metricResponses.textContent = data.responses ?? "—";
    metricRejections.textContent = data.rejections ?? "—";
    metricInvites.textContent = data.invites ?? "—";
    metricAutoAck.textContent = data.auto_ack ?? "—";
  }

  async function syncGmail() {
    hideAlert();
    btnSync.disabled = true;
    btnSync.textContent = "Syncing...";

    const days = daysSelect.value;

    try {
      const resp = await fetch(`${SYNC_URL}?days=${encodeURIComponent(days)}`, {
        method: "POST",
        headers: {
          "Accept": "application/json",
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
      syncStatusText.textContent =
        `Synced. Created: ${r.created ?? 0}, skipped: ${r.skipped_existing ?? 0}, candidates: ${r.fetched_candidates ?? 0}.`;

      await loadStats();
      showAlert("Sync completed.", "success");
    } catch (e) {
      showAlert("Sync failed: " + String(e));
    } finally {
      btnSync.disabled = false;
      btnSync.textContent = "Sync Gmail";
    }
  }

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  }

  btnRefresh.addEventListener("click", loadStats);
  btnSync.addEventListener("click", syncGmail);
  daysSelect.addEventListener("change", loadStats);

  loadStats();
})();