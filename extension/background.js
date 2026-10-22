// The only part of the extension that talks to the engine. Pages never see the token.
const ENGINE = "http://127.0.0.1:8765";

async function call(path, body = {}) {
  const { token } = await chrome.storage.local.get("token");
  if (!token) return { error: "no-token" };
  try {
    const r = await fetch(ENGINE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Engine-Token": token },
      body: JSON.stringify(body),
    });
    if (r.status === 401) return { error: "bad-token" };
    return await r.json();
  } catch {
    return { error: "offline" };
  }
}

async function resume(url) {
  // The resume PDF, so the page's file input can be filled the way a drag-and-drop would.
  const { token } = await chrome.storage.local.get("token");
  try {
    const r = await fetch(ENGINE + "/ext/resume", { method: "POST", headers: { "Content-Type": "application/json", "X-Engine-Token": token },
                                                    body: JSON.stringify({ url }) });
    if (!r.ok) return { error: "no-resume" };
    const buf = new Uint8Array(await r.arrayBuffer());
    let bin = "";
    for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
    return { name: r.headers.get("X-File-Name") || "resume.pdf", b64: btoa(bin) };
  } catch {
    return { error: "offline" };
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  (msg.type === "resume" ? resume(msg.url) : call(msg.path, msg.body)).then(reply);
  return true; // async reply
});
