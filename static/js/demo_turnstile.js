(() => {
  const enabled = document.querySelector('meta[name="jobapply-turnstile-enabled"]')?.content === "1";
  const siteKey = document.querySelector('meta[name="jobapply-turnstile-site-key"]')?.content || "";
  if (!enabled || !siteKey) return;

  const form = document.querySelector('form[action$="/app/demo/start/"]');
  if (!form) return;

  const button = form.querySelector('button[type="submit"], input[type="submit"]');
  if (!button) return;

  const originalLabel = button.textContent || "Try demo without Google";
  let verified = false;
  let widgetId = null;
  let loadingScript = null;

  const container = document.createElement("div");
  container.className = "mt-2";
  container.hidden = true;
  form.appendChild(container);

  const loadTurnstile = () => {
    if (window.turnstile) return Promise.resolve();
    if (loadingScript) return loadingScript;

    loadingScript = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      script.async = true;
      script.defer = true;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
    return loadingScript;
  };

  const resetForRetry = () => {
    verified = false;
    button.disabled = false;
    button.textContent = originalLabel;
    if (widgetId !== null && window.turnstile) {
      try { window.turnstile.remove(widgetId); } catch (_) {}
    }
    widgetId = null;
    container.replaceChildren();
    container.hidden = true;
  };

  form.addEventListener("submit", async (event) => {
    if (verified) return;

    event.preventDefault();
    if (widgetId !== null) return;

    button.disabled = true;
    container.hidden = false;

    try {
      await loadTurnstile();
      widgetId = window.turnstile.render(container, {
        sitekey: siteKey,
        callback: () => {
          verified = true;
          button.disabled = false;
          button.textContent = "Continue to demo";
        },
        "expired-callback": () => {
          verified = false;
          button.disabled = true;
          button.textContent = originalLabel;
        },
        "error-callback": resetForRetry,
      });
    } catch (_) {
      resetForRetry();
    }
  });
})();
