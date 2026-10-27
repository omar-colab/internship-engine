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
  runtime: { getManifest: () => ({ version: "0.1.1" }) },
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
  assert.equal(JSON.stringify(posted[0].message), JSON.stringify({ source: "internship-engine-ext", type: "hello", version: "0.1.1" }));
  assert.equal(posted[1].message.type, "events");
  assert.equal(posted[1].message.events[0].id, "event-1");
  appPost({ source: "internship-engine-app", type: "ack", ids: ["event-1"] });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(store.events, []);
  console.log("ok");
})().catch(error => { console.error(error); process.exitCode = 1; });
