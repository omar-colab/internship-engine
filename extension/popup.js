const status = document.getElementById("status");
async function check() {
  const r = await chrome.runtime.sendMessage({ path: "/ext/ping", body: {} });
  const msg = { "no-token": "Paste your engine token to connect.", "bad-token": "That token doesn't match your engine.",
                offline: "Engine not running. Start it: uv run python -m engine serve" };
  const webMode = r?.mode === "web";
  status.className = r?.ok ? "ok" : "bad";
  status.innerHTML = `<span class="dot"></span>${webMode ? (r.name ? "Web mode — connected to the web app." : "Web mode — profile from the web app (open it once).") : r?.ok ? `Connected to engine. ${r.roles} roles in your tracker.` : msg[r?.error] || "Can't reach your engine."}`;
  document.getElementById("web-resume").hidden = !webMode;
  document.getElementById("engine").open = !webMode;          // engine users see their setup; web users see it folded away
  const { resumePdf } = await chrome.storage.local.get("resumePdf");
  if (resumePdf?.name && !document.getElementById("resume-status").textContent) document.getElementById("resume-status").textContent = `Saved: ${resumePdf.name}`;
  const { alertsEnabled = true } = await chrome.storage.local.get("alertsEnabled");
  document.getElementById("alerts").checked = alertsEnabled;
}
document.getElementById("alerts").addEventListener("change", event =>
  chrome.storage.local.set({ alertsEnabled: event.target.checked }));
document.getElementById("save").addEventListener("click", async () => {
  await chrome.storage.local.set({ token: document.getElementById("token").value.trim() });
  check();
});
document.getElementById("resume").addEventListener("change", async event => {
  const file = event.target.files?.[0], label = document.getElementById("resume-status");
  if (!file) return;
  if (file.size > 5 * 1024 * 1024 || file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
    label.textContent = "Choose a PDF no larger than 5 MB.";
    event.target.value = "";
    return;
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (new TextDecoder().decode(bytes.slice(0, 5)) !== "%PDF-") {
    label.textContent = "That file is not a PDF.";
    event.target.value = "";
    return;
  }
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  await chrome.storage.local.set({ resumePdf: { name: file.name, b64: btoa(binary) } });
  label.textContent = "Resume saved in this browser.";
});
check();
