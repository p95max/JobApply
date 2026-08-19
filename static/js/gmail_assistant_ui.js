(() => {
  const assistant = document.querySelector(".gmail-assistant");
  if (!assistant) return;

  const faqHeading = Array.from(assistant.querySelectorAll("section.card.mt-4 h2.h6"))
    .find((heading) => heading.textContent.trim() === "FAQ");
  if (!faqHeading) return;

  const card = faqHeading.closest("section.card");
  const body = faqHeading.closest(".card-body");
  if (!card || !body) return;

  const items = Array.from(body.children).filter((element) => element.tagName === "DETAILS");
  if (!items.length) return;

  items.forEach((item) => {
    item.hidden = true;
  });

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "btn btn-link p-0 text-body text-decoration-none d-flex align-items-center justify-content-between w-100 text-start";
  toggle.setAttribute("aria-expanded", "false");
  toggle.innerHTML = `<span class="h6 mb-0">${faqHeading.textContent.trim()}</span><span class="ms-3 text-muted" aria-hidden="true">⌄</span>`;

  faqHeading.replaceWith(toggle);
  body.classList.add("py-3");

  toggle.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(open));
    items.forEach((item) => {
      item.hidden = !open;
    });
    toggle.lastElementChild.textContent = open ? "⌃" : "⌄";
  });
})();