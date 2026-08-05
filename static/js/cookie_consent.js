(() => {
  "use strict";

  const COOKIE_NAME = "jobapply_cookie_notice";
  const MAX_AGE_SECONDS = 60 * 60 * 24 * 180;

  const readCookie = (name) => {
    const prefix = `${name}=`;
    return document.cookie
      .split(";")
      .map((item) => item.trim())
      .find((item) => item.startsWith(prefix))
      ?.slice(prefix.length) || "";
  };

  const storeAcknowledgement = () => {
    const secure = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `${COOKIE_NAME}=necessary-v1; Max-Age=${MAX_AGE_SECONDS}; Path=/; SameSite=Lax${secure}`;
  };

  document.addEventListener("DOMContentLoaded", () => {
    const element = document.querySelector("[data-cookie-consent-modal]");
    if (!element || !window.bootstrap) return;

    const modal = window.bootstrap.Modal.getOrCreateInstance(element);
    const openSettings = () => modal.show();

    document.querySelectorAll("[data-open-cookie-settings]").forEach((button) => {
      button.addEventListener("click", openSettings);
    });

    element.querySelector("[data-save-cookie-settings]")?.addEventListener("click", () => {
      storeAcknowledgement();
      modal.hide();
    });

    if (!readCookie(COOKIE_NAME)) openSettings();
  });
})();
