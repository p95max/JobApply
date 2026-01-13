function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== "") {
    for (const cookie of document.cookie.split(";")) {
      const c = cookie.trim();
      if (c.startsWith(name + "=")) {
        cookieValue = decodeURIComponent(c.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

function getSelectedIds() {
  return Array.from(document.querySelectorAll(".js-row-check:checked")).map(i => i.value);
}

function syncCheckAllState() {
  const all = Array.from(document.querySelectorAll(".js-row-check"));
  const checked = all.filter(i => i.checked);
  const checkAll = document.querySelector(".js-check-all");
  if (!checkAll) return;

  if (all.length === 0) {
    checkAll.checked = false;
    checkAll.indeterminate = false;
    return;
  }

  checkAll.checked = checked.length === all.length;
  checkAll.indeterminate = checked.length > 0 && checked.length < all.length;
}

function syncBulkUI() {
  const ids = getSelectedIds();
  const countEl = document.querySelector(".js-selected-count");
  const delBtn = document.querySelector(".js-bulk-delete");
  if (countEl) countEl.textContent = String(ids.length);
  if (delBtn) delBtn.disabled = ids.length === 0;
}

document.addEventListener("click", function (e) {
  const bulkDelete = e.target.closest(".js-bulk-delete");
if (bulkDelete) {
  const ids = getSelectedIds();
  if (ids.length === 0) return;

  const ok = window.confirm(`Delete ${ids.length} selected application(s)? Data will be deleted!.`);
  if (!ok) return;

  bulkDelete.disabled = true;

  fetch("/applications/bulk-delete/", {
    method: "POST",
    headers: {
      "X-CSRFToken": getCookie("csrftoken"),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ids }),
  })
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json().catch(() => ({}));
    })
    .then(() => window.location.reload())
    .catch(() => {
      bulkDelete.disabled = false;
      alert("Bulk delete failed. Check permissions/endpoint.");
    });

  return;
  }

  const row = e.target.closest(".js-row-link");
  if (!row) return;

  if (
    e.target.closest("select") ||
    e.target.closest("a") ||
    e.target.closest("button") ||
    e.target.closest('input[type="checkbox"]') ||
    e.target.closest("label")
  ) {
    return;
  }

  window.location = row.dataset.href;
});

document.addEventListener("change", function (e) {
  const select = e.target.closest(".js-status-select");
  if (select) {
    fetch(`/applications/${select.dataset.id}/status/`, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCookie("csrftoken"),
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({ status: select.value }),
    });
    return;
  }

  if (e.target.closest(".js-check-all")) {
    const isChecked = e.target.checked;
    document.querySelectorAll(".js-row-check").forEach(cb => cb.checked = isChecked);
    syncCheckAllState();
    syncBulkUI();
    return;
  }

  if (e.target.closest(".js-row-check")) {
    syncCheckAllState();
    syncBulkUI();
    return;
  }
});

document.addEventListener("DOMContentLoaded", function () {
  syncCheckAllState();
  syncBulkUI();
});

document.addEventListener("click", function (e) {
  const btn = e.target.closest(".js-print");
  if (!btn) return;
  window.print();
});
