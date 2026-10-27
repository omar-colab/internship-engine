// The only part of the extension that talks to the engine. Pages never see the token.
importScripts("web_answers.js");
const ENGINE = "http://127.0.0.1:8765";
const FEED = "https://omar-colab.github.io/internship-engine/feed.json";
const ALERT = "daily-watch";
const APP = "https://omar-colab.github.io/internship-engine/app/";

function nextWatch(now = new Date()) {
  const next = new Date(now);
  next.setHours(8, 0, 0, 0);
  if (next <= now) next.setDate(next.getDate() + 1);
  return next.getTime();
}

function matchingRoles(feed, profile) {
  const today = new Date(feed.built).toISOString().slice(0, 10);
  const all = Array.isArray(feed.roles) ? feed.roles : [];
  // The day dating began every role got the same first_seen; that day nothing is "new".
  const oldest = all.reduce((m, r) => r.first_seen && r.first_seen < m ? r.first_seen : m, "9999");
  if (today <= oldest) return [];
  const fields = (Array.isArray(profile.watch?.fields) ? profile.watch.fields : []).flatMap(source => {
    try { return [new RegExp(source)]; } catch { return []; }
  });
  const places = Array.isArray(profile.watch?.places) ? profile.watch.places.filter(p => typeof p === "string" && p).map(p => p.toLowerCase()) : [];
  const seen = new Set();                     // one role posted in many cities counts once
  return all.filter(role => {
    const title = String(role.title || "").toLowerCase(), location = String(role.location || "").toLowerCase();
    return role.first_seen === today && fields.some(regex => regex.test(title)) &&
      (location.includes("remote") || !places.length || places.some(place => location.includes(place))) &&
      !seen.has(`${role.company}|${title}`) && seen.add(`${role.company}|${title}`);
  });
}

async function checkAlerts() {
  const { profile, alertsEnabled = true, alertedFor } = await chrome.storage.local.get(["profile", "alertsEnabled", "alertedFor"]);
  if (!profile || !alertsEnabled) return 0;
  try {
    const response = await fetch(FEED);
    if (!response.ok) return 0;
    const feed = await response.json();
    if (feed.built === alertedFor) return 0;  // already told you about this feed
    const roles = matchingRoles(feed, profile);
    await chrome.storage.local.set({ alertedFor: feed.built });
    if (!roles.length) return 0;
    // "basic" with lines in the message: macOS shows only the title of "list" notifications.
    await chrome.notifications.create("daily-watch", {
      type: "basic", iconUrl: "icon.png", title: `${roles.length} new internship${roles.length > 1 ? "s" : ""} match you today`,
      message: roles.slice(0, 3).map(role => `${role.company || "Unknown"} — ${role.title || "Untitled"}`).join("\n"),
    });
    return roles.length;
  } catch { return 0; }
}

// Daily repeat; a missed 8:00 (browser closed) fires on next launch, and startup never pushes it back a day.
async function scheduleWatch() {
  if (!(await chrome.alarms.get(ALERT))) chrome.alarms.create(ALERT, { when: nextWatch(), periodInMinutes: 24 * 60 });
}

if (typeof chrome !== "undefined") {
  chrome.runtime.onInstalled.addListener(() => { scheduleWatch(); checkAlerts(); });
  chrome.runtime.onStartup.addListener(scheduleWatch);
  chrome.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === ALERT) checkAlerts();
  });
  chrome.notifications.onClicked.addListener(id => {
    if (id === ALERT) chrome.tabs.create({ url: APP });
  });
}

async function webCall(path, body = {}) {
  const data = await chrome.storage.local.get(["profile", "learnedAnswers", "resumePdf"]);
  const profile = data.profile || {};
  if (path === "/ext/ping") return { ok: true, mode: "web", name: profile.first_name || "" };
  if (path === "/ext/lookup") return { role: null };
  if (path === "/ext/answers") {
    const questions = (body.questions || []).filter(q => q && typeof q === "object" && q.label != null).slice(0, 200);
    return { answers: questions.map(q => InternshipWebAnswers.answer({
      label: String(q.label).slice(0, 500), kind: String(q.kind || "text"),
      options: (Array.isArray(q.options) ? q.options : []).slice(0, 300).map(o => String(o).slice(0, 200)),
      required: !!q.required,
    }, { ...profile, resume_pdf: profile.resume_pdf || (data.resumePdf?.b64 ? data.resumePdf.name || "resume.pdf" : undefined) },
      data.learnedAnswers || {}, profile.resume_text || "")) };
  }
  if (path === "/ext/save") {
    if (!String(body.url || "").startsWith("https://")) return { error: "invalid-url" };
    await queueEvent({ kind: "saved", url: body.url, company: String(body.company || "Unknown").slice(0, 120), title: String(body.title || "Saved role").slice(0, 200) });
    return { role: null };
  }
  if (path === "/ext/applied") {
    const bank = data.learnedAnswers || {};
    for (const item of (body.learned || []).slice(0, 50)) {
      if (!item || !item.label || !item.answer || String(item.answer).length > 300) continue;
      const label = String(item.label).slice(0, 500), k = InternshipWebAnswers.key(label), answer = String(item.answer).trim();
      if (!k || !answer || InternshipWebAnswers.sensitive(k)) continue;
      if (!(k in bank) && Object.keys(bank).length >= 2000) continue;
      bank[k] = { answer: answer.slice(0, 300), label, on: new Date().toISOString().slice(0, 10) };
    }
    await chrome.storage.local.set({ learnedAnswers: bank });
    await queueEvent({ kind: "applied", url: body.url, company: body.company || "", title: body.title || "" });
    return { ok: true };
  }
  return { error: "offline" };
}

async function queueEvent(event) {
  const { events = [] } = await chrome.storage.local.get("events");
  events.push({ id: crypto.randomUUID(), kind: event.kind, url: String(event.url || ""), company: event.company, title: event.title, at: new Date().toISOString() });
  await chrome.storage.local.set({ events: events.slice(-200) });
}

async function call(path, body = {}) {
  const { token } = await chrome.storage.local.get("token");
  if (!token) return webCall(path, body);
  try {
    const r = await fetch(ENGINE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Engine-Token": token },
      body: JSON.stringify(body),
    });
    if (r.status === 401) return { error: "bad-token" };
    return await r.json();
  } catch {
    return webCall(path, body);
  }
}

async function resume(url) {
  const { token } = await chrome.storage.local.get("token");
  if (!token) {
    const { resumePdf } = await chrome.storage.local.get("resumePdf");
    return resumePdf?.b64 ? { name: resumePdf.name || "resume.pdf", b64: resumePdf.b64 } : { error: "no-resume" };
  }
  try {
    const r = await fetch(ENGINE + "/ext/resume", { method: "POST", headers: { "Content-Type": "application/json", "X-Engine-Token": token },
                                                     body: JSON.stringify({ url }) });
    if (!r.ok) {
      if (r.status === 401) return { error: "bad-token" };
      const { resumePdf } = await chrome.storage.local.get("resumePdf");
      return resumePdf?.b64 ? { name: resumePdf.name || "resume.pdf", b64: resumePdf.b64 } : { error: "no-resume" };
    }
    const buf = new Uint8Array(await r.arrayBuffer());
    let bin = "";
    for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
    return { name: r.headers.get("X-File-Name") || "resume.pdf", b64: btoa(bin) };
  } catch {
    const { resumePdf } = await chrome.storage.local.get("resumePdf");
    return resumePdf?.b64 ? { name: resumePdf.name || "resume.pdf", b64: resumePdf.b64 } : { error: "offline" };
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  (msg.type === "resume" ? resume(msg.url) : call(msg.path, msg.body)).then(reply);
  return true; // async reply
});

if (typeof module !== "undefined") module.exports = { webCall, queueEvent, call, resume, nextWatch, matchingRoles, checkAlerts, scheduleWatch };
