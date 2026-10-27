// Private bridge for the hosted app; page messages never cross other origins or paths.
(() => {
  const APP_ORIGIN = "https://omar-colab.github.io";
  if (location.origin !== APP_ORIGIN || !location.pathname.startsWith("/internship-engine/app/")) return;
  let ready = false;
  const post = message => window.postMessage({ source: "internship-engine-ext", ...message }, location.origin);
  const sendEvents = async () => {
    if (!ready) return;
    const { events = [] } = await chrome.storage.local.get("events");
    if (events.length) post({ type: "events", events });
  };
  window.addEventListener("message", async event => {
    if (event.source !== window || event.origin !== APP_ORIGIN || !location.pathname.startsWith("/internship-engine/app/")) return;
    const message = event.data;
    if (!message || message.source !== "internship-engine-app") return;
    if (message.type === "hello") {
      ready = true;
      const manifest = chrome.runtime.getManifest();
      post({ type: "hello", version: manifest.version });
      await sendEvents();
    } else if (message.type === "profile" && message.profile && typeof message.profile === "object") {
      await chrome.storage.local.set({ profile: message.profile });
    } else if (message.type === "ack" && Array.isArray(message.ids)) {
      const { events = [] } = await chrome.storage.local.get("events");
      const ids = new Set(message.ids);
      await chrome.storage.local.set({ events: events.filter(item => !ids.has(item.id)) });
    }
  });
  // The app may have said hello before this script loaded; announce ourselves so it says hello again.
  post({ type: "hello", version: chrome.runtime.getManifest().version });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes.events) sendEvents();
  });
})();
