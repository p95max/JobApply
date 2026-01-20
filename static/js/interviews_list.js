document.addEventListener("change", async (e) => {
  const el = e.target;
  if (!el.classList.contains("js-interview-status")) return;

  const id = el.dataset.id;
  const status = el.value;

  const res = await fetch(`/interviews/${id}/status/`, {
    method: "POST",
    headers: {
      "X-CSRFToken": getCookie("csrftoken"),
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({ status }),
  });

  if (!res.ok) {
    alert("Failed to update status");
    return;
  }

  el.classList.remove(
    "status-int-scheduled",
    "status-int-done",
    "status-int-canceled"
  );
  el.classList.add(`status-int-${status}`);
});

function getCookie(name) {
  const m = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return m ? decodeURIComponent(m[2]) : "";
}
