const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const answers = require("../extension/web_answers.js");
const ROOT = require("node:path").resolve(__dirname, "..");

const profile = {
  first_name: "Fictional", last_name: "Applicant", email: "applicant@contoso.example", phone: "555-0100",
  linkedin: "https://linkedin.example.invalid/in/applicant", city: "Hartford", state: "CT", country: "United States",
  school: "Contoso University", degree_type: "Bachelor's", major: "Economics", graduation: "2028-05",
  work_authorization: "unknown", needs_sponsorship: "unknown", open_to_relocation: true,
  heard_about: "Job board", eeo: "decline", resume_pdf: "resume.pdf",
};
const check = (label, kind = "text", options = [], required = true, p = profile, bank = {}) =>
  answers.answer({ label, kind, options, required }, p, bank, "Contoso analytics project improved reporting speed for fictional clients.");

// These mirror engine/answers.py's rule self-check using fictional-only values.
assert.equal(check("First Name*").answer, "Fictional");
assert.equal(check("Last Name*").answer, "Applicant");
assert.equal(check("Country*", "combobox", ["United States +1", "Afghanistan +93"]).answer, "United States +1");
assert.equal(check("Degree", "combobox", ["Associate's Degree", "Bachelor's Degree"]).answer, "Bachelor's Degree");
assert.equal(check("What is your expected graduation date?", "checkbox", ["Spring 2027", "Winter 2027", "Spring 2028", "Winter 2028"]).answer, "Spring 2028");
assert.equal(check("Are you legally eligible to work in the United States?", "combobox", ["Yes", "No"]).status, "needs_you");
assert.equal(check("Will you require visa sponsorship?", "combobox", ["Yes", "No"]).status, "needs_you");
const known = { ...profile, work_authorization: "us_citizen", needs_sponsorship: "no" };
assert.equal(check("Are you legally eligible to work in the US?", "combobox", ["Yes", "No"], true, known).answer, "Yes");
assert.equal(check("Will you require sponsorship?", "combobox", ["Yes", "No"], true, known).answer, "No");
assert.equal(check("Veteran Status", "combobox", ["I am not a protected veteran", "I don't wish to answer"], false).answer, "I don't wish to answer");
assert.equal(check("Gender", "combobox", ["Male", "Female"], false).status, "skip");
assert.equal(check("Disability", "combobox", ["Yes", "No", "I don’t wish to answer"], false).answer, "I don’t wish to answer");
assert.equal(check("Why work at Contoso?", "textarea").status, "needs_you");
assert.match(check("Why work at Contoso?", "textarea").suggest[0], /Contoso analytics/);
assert.equal(check("Full name ✱").answer, "Fictional Applicant");
assert.equal(check("What is your location?", "select-one", ["Select...", "Afghanistan", "United States"]).answer, "United States");
assert.equal(check("Resume", "file", [], true, { ...profile, resume_pdf: "resume.pdf" }).status, "auto");
assert.equal(check("Pick a city", "select-one", ["Boston", "Austin"], false).status, "skip");
assert.equal(check("School", "combobox", Array(60).fill("Aalborg University")).answer, "Contoso University");
assert.equal(check("How did you hear about us?", "combobox", ["LinkedIn", "Indeed"]).status, "needs_you");
assert.equal(check("Are you willing to work at Contoso's Chicago office?", "text").status, "needs_you");
assert.equal(check("Location (City)*", "combobox").answer, "Hartford, CT");
// Web-app profiles: "sponsor" never answers "authorized to work?", and unknown relocation is asked, not guessed.
const visa = { ...profile, work_authorization: "sponsor", needs_sponsorship: true };
assert.equal(check("Are you legally authorized to work in the US?", "combobox", ["Yes", "No"], true, visa).status, "needs_you");
assert.equal(check("Will you require sponsorship?", "combobox", ["Yes", "No"], true, visa).answer, "Yes");
assert.equal(check("Are you open to relocation?", "combobox", ["Yes", "No"], true, { ...profile, open_to_relocation: undefined }).status, "needs_you");
assert.equal(check("Social Security Number*", "text").status, "needs_you");
const learned = { [answers.key("Can you work in the office 3-4 days per week?*")]: { answer: "yes", on: "saved" } };
assert.equal(check("Can you work in the office 3–4 days per week? (required)", "combobox", ["Yes", "No"], true, profile, learned).answer, "Yes");
assert.equal(check("Can you work in the office 3-4 days per week?", "combobox", ["Agree", "Disagree"], true, profile, learned).status, "needs_you");
assert.equal(check("Can you work in the office 5 days per week?", "combobox", ["Yes", "No"], true, profile, learned).status, "needs_you");
assert.equal(check("First name", "text", [], true, profile, { [answers.key("First name")]: { answer: "Bad", on: "saved" } }).answer, "Fictional");
assert.equal(check("Why work here?", "textarea", [], true, profile, { [answers.key("Why work here?")]: { answer: "Contoso work", on: "saved" } }).status, "needs_you");
assert.equal(check("Why work here?", "textarea", [], true, profile, { [answers.key("Why work here?")]: { answer: "Contoso work", on: "saved" } }).suggest[0], "Contoso work");

// Run the content bridge against a fake app page and fake extension storage.
const listeners = {}, posted = [], storageListeners = [];
const store = { events: [{ id: "event-1", kind: "saved", url: "https://jobs.example.invalid/role", company: "Contoso", title: "Analyst", at: "2026-10-26T12:00:00Z" }] };
const chrome = {
  runtime: { getManifest: () => ({ version: "0.2.0" }) },
  storage: {
    local: {
      async get(key) { return { [key]: store[key] }; },
      async set(values) {
        Object.assign(store, values);
        for (const listener of storageListeners) listener(Object.fromEntries(Object.entries(values).map(([k, v]) => [k, { newValue: v }])), "local");
      },
    },
    onChanged: { addListener(listener) { storageListeners.push(listener); } },
  },
};
const window = {
  addEventListener(type, listener) { listeners[type] = listener; },
  postMessage(message, origin) { posted.push({ message, origin }); },
};
const context = {
  window, chrome, location: { origin: "https://omar-colab.github.io", pathname: "/internship-engine/app/" },
  console, Set,
};
vm.runInNewContext(fs.readFileSync(ROOT + "/extension/bridge.js", "utf8"), context);
const appPost = data => listeners.message({ source: window, origin: "https://omar-colab.github.io", data });
(async () => {
  listeners.message({ source: {}, origin: "https://omar-colab.github.io", data: { source: "internship-engine-app", type: "hello" } });
  listeners.message({ source: window, origin: "https://example.invalid", data: { source: "internship-engine-app", type: "hello" } });
  assert.equal(posted.length, 1);                       // the bridge's own hello on load
  assert.equal(posted[0].message.type, "hello");
  posted.length = 0;
  appPost({ source: "internship-engine-app", type: "profile", profile: { first_name: "Fictional", resume_text: "Contoso" } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(store.profile.first_name, "Fictional");
  appPost({ source: "internship-engine-app", type: "hello" });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(posted[0].origin, "https://omar-colab.github.io");
  assert.equal(JSON.stringify(posted[0].message), JSON.stringify({ source: "internship-engine-ext", type: "hello", version: "0.2.0" }));
  assert.equal(posted[1].message.type, "events");
  assert.equal(posted[1].message.events[0].id, "event-1");
  appPost({ source: "internship-engine-app", type: "ack", ids: ["event-1"] });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(store.events, []);

  // Daily alerts use a fictional feed and mocked Chrome APIs; no network is used.
  const alertListeners = {}, alertStore = {
    profile: { watch: { fields: ["data|software", "["], places: ["hartford"] } }, alertsEnabled: true,
  };
  const alertCalls = { fetched: 0, notifications: [], tabs: [], alarms: [] };
  const alertChrome = {
    storage: { local: { async get(keys) { return Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(key => [key, alertStore[key]])); },
                        async set(values) { Object.assign(alertStore, values); } } },
    runtime: {
      onMessage: { addListener() {} }, onInstalled: { addListener(fn) { alertListeners.install = fn; } },
      onStartup: { addListener(fn) { alertListeners.startup = fn; } },
    },
    alarms: { create(...args) { alertCalls.alarms.push(args); }, async get(name) { return alertCalls.alarms.find(a => a[0] === name); }, onAlarm: { addListener(fn) { alertListeners.alarm = fn; } } },
    notifications: { create: async (...args) => alertCalls.notifications.push(args), onClicked: { addListener(fn) { alertListeners.clicked = fn; } } },
    tabs: { create: options => alertCalls.tabs.push(options) },
  };
  const fictionalFeed = { built: "2026-10-26T23:30:00Z", roles: [
    { first_seen: "2026-10-26", company: "Contoso", title: "Data Intern", location: "Hartford, CT" },
    { first_seen: "2026-10-26", company: "Northwind", title: "Software Intern", location: "Remote" },
    { first_seen: "2026-10-26", company: "Adatum", title: "Data Science Intern", location: "Hartford" },
    { first_seen: "2026-10-26", company: "Wide World Importers", title: "Data Engineering Intern", location: "Hartford" },
    { first_seen: "2026-10-25", company: "Fabrikam", title: "Data Intern", location: "Hartford" },
    { first_seen: "2026-10-26", company: "Tailspin", title: "Data Intern", location: "Boston" },
    { first_seen: "2026-10-26", company: "Litware", title: "Design Intern", location: "Hartford" },
    { first_seen: "2026-10-26", company: "Contoso", title: "Data Intern", location: "Remote" },
  ] };
  const alertModule = { exports: {} };
  let alertId = 0;
  vm.runInNewContext(fs.readFileSync(ROOT + "/extension/background.js", "utf8"), {
    chrome: alertChrome, importScripts() {}, module: alertModule,
    fetch: async url => { alertCalls.fetched++; assert.equal(url, "https://omar-colab.github.io/internship-engine/feed.json"); return { ok: true, json: async () => fictionalFeed }; },
    crypto: { randomUUID: () => String(++alertId) }, Date, String, Array, Set, RegExp,
  });
  assert.equal(alertModule.exports.matchingRoles(fictionalFeed, alertStore.profile).length, 4);
  assert.equal(await alertModule.exports.checkAlerts(), 4);
  assert.equal(alertCalls.notifications[0][1].title, "4 new internships match you today");
  assert.equal(alertCalls.notifications[0][1].message, "Contoso — Data Intern\nNorthwind — Software Intern\nAdatum — Data Science Intern");
  assert.equal(await alertModule.exports.checkAlerts(), 0);                    // same feed: no second alert
  assert.equal(alertCalls.notifications.length, 1);
  delete alertStore.alertedFor;
  assert.equal(alertModule.exports.matchingRoles({ built: "2026-10-26T10:00:00Z", roles: fictionalFeed.roles.map(r => ({ ...r, first_seen: "2026-10-26" })) }, alertStore.profile).length, 0);   // dating's first day
  alertListeners.clicked("daily-watch");
  assert.equal(JSON.stringify(alertCalls.tabs), JSON.stringify([{ url: "https://omar-colab.github.io/internship-engine/app/" }]));
  alertStore.profile.watch.fields = ["^no match$", "["]; delete alertStore.alertedFor;
  assert.equal(await alertModule.exports.checkAlerts(), 0);
  assert.equal(alertCalls.notifications.length, 1);
  alertStore.alertsEnabled = false;
  assert.equal(await alertModule.exports.checkAlerts(), 0);
  alertStore.alertsEnabled = true; delete alertStore.alertedFor;
  delete alertStore.profile;
  assert.equal(await alertModule.exports.checkAlerts(), 0);
  assert.equal(alertCalls.fetched, 3);
  assert.equal(alertCalls.notifications.length, 1);
  assert.equal(alertCalls.alarms.length, 0);
  alertStore.profile = { watch: { fields: ["data"], places: [] } };
  const fetchedBeforeInstall = alertCalls.fetched;
  await alertListeners.install({ reason: "update" });
  assert.equal(alertCalls.fetched, fetchedBeforeInstall);                    // updates schedule only; they do not send install alerts
  await alertListeners.install({ reason: "install" });
  assert.equal(alertCalls.fetched, fetchedBeforeInstall + 1);
  await alertListeners.startup();
  assert.equal(alertCalls.alarms.length, 1);
  await alertListeners.startup();
  assert.equal(alertCalls.alarms.length, 1);                                    // startup never reschedules an existing alarm
  assert.equal(alertCalls.alarms[0][0], "daily-watch");
  assert.equal(alertCalls.alarms[0][1].periodInMinutes, undefined);        // one-shot alarm stays at local 8:00 across DST
  alertListeners.alarm({ name: "daily-watch" });
  assert.equal(alertCalls.alarms.length, 2);
  await Promise.all([
    alertModule.exports.queueEvent({ kind: "saved", url: "https://jobs.example.invalid/1" }),
    alertModule.exports.queueEvent({ kind: "saved", url: "https://jobs.example.invalid/2" }),
  ]);
  assert.equal(alertStore.events.length, 2);                               // concurrent messages don't overwrite each other
  console.log("ok");
})().catch(error => { console.error(error); process.exitCode = 1; });
