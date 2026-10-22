const status = document.getElementById("status");
async function check() {
  const r = await chrome.runtime.sendMessage({ path: "/ext/ping", body: {} });
  const msg = { "no-token": "Paste your engine token to connect.", "bad-token": "That token doesn't match your engine.",
                offline: "Engine not running. Start it: uv run python -m engine serve" };
  status.className = r?.ok ? "ok" : "bad";
  status.innerHTML = `<span class="dot"></span>${r?.ok ? `Connected. ${r.roles} roles in your tracker.` : msg[r?.error] || "Can't reach your engine."}`;
}
document.getElementById("save").addEventListener("click", async () => {
  await chrome.storage.local.set({ token: document.getElementById("token").value.trim() });
  check();
});
check();
