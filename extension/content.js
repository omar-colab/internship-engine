// Internship Engine: runs on job-application pages. Shows the fit, saves the job, fills what your profile backs.
// Rules it shares with the engine: never press Enter, never click Submit, never guess an answer.
(() => {
  if (window.__internshipEngine) return;
  window.__internshipEngine = true;

  const send = (path, body) => new Promise(res => chrome.runtime.sendMessage({ path, body }, res));
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const clean = t => (t || "").trim().replace(/\s+/g, " ");
  const plain = t => clean(t).toLowerCase().replace(/[’']/g, "").replace(/[^a-z0-9 ]/g, "");
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) && getComputedStyle(el).visibility !== "hidden";
  const FIELDS = "input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select, [role=combobox]";
  const SUBMIT = /submit|send application/i;

  // ---- reading the form (same logic as engine/read_form.py) ------------------------------------
  const LABELISH = "label, legend, [class*=label], [class*=Label], [class*=title], [class*=question-text], [class*=prompt]";
  function labelOf(e) {
    const group = (e.type === "radio" || e.type === "checkbox") && e.name;
    if (!group) {
      const byId = e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
      if (byId && clean(byId.innerText)) return clean(byId.innerText);
      if (e.getAttribute("aria-label")) return clean(e.getAttribute("aria-label"));
      const lb = (e.getAttribute("aria-labelledby") || "").split(" ").map(id => document.getElementById(id)?.innerText || "").join(" ");
      if (clean(lb)) return clean(lb);
    }
    const mine = group ? [...document.querySelectorAll(`input[name="${CSS.escape(e.name)}"]`)] : [e];
    let n = e;
    for (let i = 0; i < 7 && n.parentElement; i++) {
      n = n.parentElement;
      if (group && !mine.every(x => n.contains(x))) continue;
      const hit = [...n.querySelectorAll(LABELISH)]
        .filter(c => !mine.some(x => c.contains(x) || (x.id && c.getAttribute("for") === x.id)))
        .map(c => clean(c.innerText)).find(t => t && t.length < 400);
      if (hit) return hit;
      if (group && n.tagName === "FIELDSET") break;
    }
    return clean(e.name || e.placeholder || "");
  }
  const optionLabel = e => clean(((e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`)) || e.closest("label") || e.parentElement)?.innerText || e.value);
  const kindOf = e => e.getAttribute("role") === "combobox" ? "combobox" : (e.type || e.tagName).toLowerCase();
  const required = e => e.required || e.getAttribute("aria-required") === "true" || /\*|✱/.test((e.closest("label, fieldset, div")?.innerText || "").slice(0, 200));

  function menuOf(el) {
    const lb = el.getAttribute("aria-controls") || el.getAttribute("aria-owns");
    if (lb && document.getElementById(lb)) return [...document.getElementById(lb).querySelectorAll("[role=option]")];
    let n = el;
    for (let i = 0; i < 8 && n.parentElement; i++) {
      n = n.parentElement;
      const opts = n.querySelectorAll("[role=option]");
      if (opts.length) return [...opts].filter(visible);
    }
    return [];
  }
  const key = (el, type) => el.dispatchEvent(new KeyboardEvent(type, { key: el._k, code: el._k, bubbles: true }));
  function press(el, k) { el._k = k; key(el, "keydown"); key(el, "keyup"); }
  async function waitOptions(el, ms) {
    for (let t = 0; t < ms; t += 200) { const o = menuOf(el); if (o.length) return o; await sleep(200); }
    return [];
  }
  async function readOptions(el) {
    el.focus(); press(el, "ArrowDown");
    const opts = (await waitOptions(el, 1500)).map(o => clean(o.innerText.split("\n")[0])).slice(0, 60);
    press(el, "Escape"); el.blur();
    return opts;
  }

  async function collect() {
    const out = [], seen = new Set();
    for (const el of [...document.querySelectorAll(FIELDS)].filter(visible)) {
      if (el.closest("#internship-engine-root")) continue;
      const kind = kindOf(el);
      if (kind !== "combobox" && el.closest("[class*=select__control], [class*=select-shell]")) continue;
      const label = labelOf(el), group = (kind === "radio" || kind === "checkbox");
      const k = group ? "g|" + (el.name || label) : `${label}|${el.name}|${kind}`;
      if (seen.has(k)) continue;
      seen.add(k);
      const q = { el, label, kind, name: el.name || "", required: required(el) };
      if (kind.startsWith("select")) q.options = [...el.options].map(o => clean(o.text)).filter(Boolean);
      else if (kind === "combobox") q.options = await readOptions(el);
      else if (group && el.name) q.options = [...document.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`)].map(optionLabel);
      out.push(q);
    }
    return out;
  }

  // ---- filling (React-safe: native setters + the events frameworks listen for) -----------------
  function setValue(el, v) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  const clickLike = el => ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach(t => el.dispatchEvent(new MouseEvent(t, { bubbles: true })));
  async function typeInto(el, text) {
    setValue(el, "");
    for (const ch of text) { setValue(el, el.value + ch); await sleep(35); }   // keystroke-by-keystroke: autocompletes listen
  }
  const searchWord = a => (a.match(/[A-Za-z0-9]+/g) || [a]).sort((x, y) => y.length - x.length)[0];

  async function chooseCombobox(el, answer, options) {
    press(document.activeElement || document.body, "Escape");
    el.scrollIntoView({ block: "center" }); el.focus(); press(el, "ArrowDown");
    const want = plain(answer), city = plain(answer.split(",")[0]);
    let typed = false;
    for (let round = 0; round < 2; round++) {
      if (typed || !options.length || options.length > 15) { await typeInto(el, searchWord(answer.split(",")[0])); typed = true; }
      const opts = await waitOptions(el, typed ? 5000 : 2500);
      const lines = opts.map(o => plain(o.innerText.split("\n")[0]));
      let i = lines.findIndex(t => t === want);
      if (i < 0 && typed) i = lines.findIndex(t => t.startsWith(city));
      if (i >= 0) { clickLike(opts[i]); return true; }
      if (typed) break;
      typed = true;
    }
    press(el, "Escape");
    return false;
  }

  async function fillOne(q, a, resumeFile) {
    const { el, kind } = q, ans = String(a.answer);
    try {
      if (kind === "file") {
        if (!resumeFile) return "skipped";
        const dt = new DataTransfer(); dt.items.add(resumeFile); el.files = dt.files;
        el.dispatchEvent(new Event("change", { bubbles: true }));
      } else if (kind.startsWith("select")) {
        const opt = [...el.options].find(o => plain(o.text) === plain(ans));
        if (!opt) return "failed";
        el.value = opt.value; el.dispatchEvent(new Event("change", { bubbles: true }));
      } else if (kind === "combobox") {
        if (!(await chooseCombobox(el, ans, q.options || []))) return "failed";
      } else if (kind === "radio" || kind === "checkbox") {
        const box = [...document.querySelectorAll(`input[name="${CSS.escape(q.name)}"]`)].find(b => plain(optionLabel(b)) === plain(ans));
        if (!box) return "failed";
        if (!box.checked) box.click();
      } else {
        setValue(el, ans);
      }
      return "filled";
    } catch { return "failed"; }
  }

  function stillThere(q, a) {
    const { el, kind } = q, ans = String(a.answer);
    if (kind === "file") return el.files?.length > 0;
    if (kind === "radio" || kind === "checkbox")
      return [...document.querySelectorAll(`input[name="${CSS.escape(q.name)}"]`)].some(b => b.checked && plain(optionLabel(b)) === plain(ans));
    if (kind === "combobox") {
      let n = el, shown = "";
      for (let i = 0; i < 5 && n.parentElement && !shown; i++) { n = n.parentElement; shown = clean(n.innerText); }
      const code = ans.match(/\+\d{1,3}$/);
      return plain(shown).includes(plain(ans.split(",")[0])) || plain(el.value).includes(plain(ans.split(",")[0])) || !!(code && shown.includes(code[0]));
    }
    if (kind.startsWith("select")) return plain(el.options[el.selectedIndex]?.text) === plain(ans);
    const digits = t => String(t).replace(/\D/g, "");
    if (kind === "tel" || /phone|mobile/i.test(q.label)) return digits(el.value).endsWith(digits(ans));   // "(555) 555-5555"
    return el.value === ans || plain(el.value).includes(plain(ans));
  }

  // What you typed into a question the engine left to you. Essays and files aren't learned (see answers.py).
  function current(q) {
    const { el, kind } = q;
    if (kind === "radio" || kind === "checkbox")
      return [...document.querySelectorAll(`input[name="${CSS.escape(q.name)}"]`)].filter(b => b.checked).map(optionLabel).join(", ");
    if (kind.startsWith("select")) return el.value ? clean(el.options[el.selectedIndex]?.text) : "";
    if (kind === "combobox") {                         // only a choice from its own list, never the widget's other text
      let n = el, shown = "";
      for (let i = 0; i < 5 && n.parentElement && !shown; i++) { n = n.parentElement; shown = plain(n.innerText); }
      return (q.options || []).find(o => plain(o) && shown.includes(plain(o))) || "";
    }
    return kind === "textarea" || kind === "file" || kind === "password" ? "" : String(el.value || "").trim();
  }
  let yoursLeft = [];

  async function fillPage(ui) {
    ui.busy("Reading every question…");
    const qs = await collect();
    const res = await send("/ext/answers", { questions: qs.map(({ el, ...q }) => q) });
    if (res?.error) return ui.error(res.error);
    let resumeFile = null;
    if (qs.some(q => q.kind === "file")) {
      const r = await new Promise(ok => chrome.runtime.sendMessage({ type: "resume", url: location.href }, ok));
      if (r?.b64) resumeFile = new File([Uint8Array.from(atob(r.b64), c => c.charCodeAt(0))], r.name, { type: "application/pdf" });
    }
    const plan = res.answers;
    ui.busy(`Filling ${plan.filter(a => a.status === "auto").length} answers…`);
    for (let i = 0; i < qs.length; i++) plan[i].result = plan[i].status === "auto" ? await fillOne(qs[i], plan[i], resumeFile) : plan[i].status;
    for (let pass = 0; pass < 2; pass++)                // a later field can wipe an earlier one: check, refill once
      for (let i = 0; i < qs.length; i++)
        if (plan[i].result === "filled" && !stillThere(qs[i], plan[i]))
          plan[i].result = pass === 0 ? await fillOne(qs[i], plan[i], resumeFile) : "failed";
    const submit = [...document.querySelectorAll("button, input[type=submit]")].find(b => visible(b) && SUBMIT.test(b.innerText || b.value));
    submit?.scrollIntoView({ block: "center" });
    yoursLeft = qs.filter((q, i) => ["needs_you", "failed"].includes(plan[i].result));
    ui.done(plan);
  }

  // ---- the floating panel (shadow DOM: the page's CSS can't touch it, ours can't touch the page) -
  const host = document.createElement("div");
  host.id = "internship-engine-root";
  const root = host.attachShadow({ mode: "closed" });
  root.innerHTML = `<style>
    :host { all: initial; }
    .pill { position: fixed; right: 20px; bottom: 20px; z-index: 2147483647; font: 500 13px/1.4 ui-sans-serif, -apple-system, "Segoe UI", sans-serif;
      color: #F4F6FF; background: #0D1430; border: 1px solid #2A3566; border-radius: 16px; box-shadow: 0 18px 50px -12px rgba(13,20,48,.55);
      width: 300px; overflow: hidden; }
    .head { display: flex; align-items: center; gap: 10px; padding: 12px 14px; cursor: pointer; }
    .logo { width: 22px; height: 22px; border-radius: 7px; background: #2335F5; display: grid; place-items: center; font-weight: 800; font-size: 12px; }
    .title { flex: 1; font-weight: 700; letter-spacing: -.01em; }
    .sig { display: flex; gap: 2px; align-items: flex-end; height: 16px; }
    .sig i { width: 4px; border-radius: 2px; background: #2A3566; }
    .sig i.on { background: #7C8CFF; }
    .body { padding: 0 14px 14px; }
    .why { color: #AEB6DA; font-size: 12px; margin: 0 0 10px; }
    .note { color: #FFB86B; font-size: 12px; margin: 0 0 10px; }
    .row { display: flex; gap: 8px; }
    button { all: unset; cursor: pointer; flex: 1; text-align: center; font-weight: 700; font-size: 13px; padding: 9px 10px; border-radius: 10px;
      background: #1B2550; color: #F4F6FF; }
    button.go { background: #2335F5; }
    button:focus-visible { outline: 2px solid #7C8CFF; outline-offset: 2px; }
    ul { margin: 8px 0 0; padding-left: 16px; color: #D6DBF5; font-size: 12px; max-height: 180px; overflow: auto; }
    li { margin: 3px 0; }
    .muted { color: #8C94BD; font-size: 12px; }
    .min .body { display: none; }
  </style>
  <div class="pill" role="region" aria-label="Internship Engine">
    <div class="head" tabindex="0"><div class="logo">IE</div><div class="title">Internship Engine</div><div class="sig" aria-hidden="true"></div></div>
    <div class="body"></div>
  </div>`;
  document.documentElement.appendChild(host);
  const pill = root.querySelector(".pill"), body = root.querySelector(".body"), sig = root.querySelector(".sig");
  root.querySelector(".head").addEventListener("click", () => pill.classList.toggle("min"));
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const showFit = f => sig.innerHTML = [1, 2, 3, 4, 5].map(n => `<i class="${f >= n ? "on" : ""}" style="height:${4 + n * 2.4}px"></i>`).join("");
  const ERR = { "no-token": "Open the extension and paste your engine token.", "bad-token": "That token doesn't match your engine. Run: uv run python -m engine token",
                offline: "Your engine isn't running. Start it: uv run python -m engine serve" };

  const ui = {
    busy: t => body.innerHTML = `<p class="muted">${esc(t)}</p>`,
    error: e => body.innerHTML = `<p class="note">${esc(ERR[e] || e)}</p>`,
    done: plan => {
      const filled = plan.filter(a => a.result === "filled").length, yours = plan.filter(a => ["needs_you", "failed"].includes(a.result));
      body.innerHTML = `<p class="why"><b style="color:#fff">Filled ${filled} of ${plan.length}.</b> ${yours.length ? "These are yours, then Submit:" : "Read it over, then Submit."}</p>
        ${yours.length ? `<ul>${yours.map(a => `<li>${esc(a.label)}</li>`).join("")}</ul>` : ""}
        <p class="muted" style="margin-top:10px">The engine never clicks Submit. When you do, it's tracked.</p>`;
    },
  };

  async function start() {
    const res = await send("/ext/lookup", { url: location.href });
    if (res?.error) return ui.error(res.error);
    const r = res.role;
    if (r?.fit) showFit(r.fit);
    const formHere = [...document.querySelectorAll(FIELDS)].filter(visible).length >= 3;
    let kw = null; try { kw = JSON.parse(r?.keywords || "null"); } catch {}
    const appliedNote = r?.applied_on ? `<p class="note">You applied here on ${esc(r.applied_on)}. Applying twice rarely helps.</p>` : "";
    const extra = [r?.pay, kw?.asked?.length ? `${kw.have.length}/${kw.asked.length} skills on your resume` : ""].filter(Boolean).join(" · ");
    body.innerHTML = `${appliedNote}${r ? `<p class="why">${esc(r.fit ? `Fit ${r.fit}/5 · ${r.fit_why || ""}` : "Saved in your tracker")}</p>` : `<p class="why">Not in your tracker yet.</p>`}
      ${extra ? `<p class="muted" style="margin:-4px 0 10px">${esc(extra)}</p>` : ""}
      ${r?.eligible === 0 ? `<p class="note">You may not be eligible: ${esc(r.eligible_why)}</p>` : r?.eligible === 2 ? `<p class="note">Check first: ${esc(r.eligible_why)}</p>` : ""}
      <div class="row">${r ? "" : `<button class="save">Save job</button>`}${formHere ? `<button class="go fill">Fill application</button>` : ""}</div>
      ${!formHere ? `<p class="muted" style="margin-top:8px">Open the application form and the Fill button appears here.</p>` : ""}`;
    body.querySelector(".save")?.addEventListener("click", async () => {
      ui.busy("Saving and scoring…");
      const h = document.querySelector("h1, h2");
      const out = await send("/ext/save", { url: location.href, title: clean(h?.innerText) || document.title, company: document.title.split(/[-|–@]/).pop().trim() });
      if (out?.error) return ui.error(out.error);
      start();
    });
    body.querySelector(".fill")?.addEventListener("click", () => fillPage(ui));
  }

  // You clicked Submit: record it (the confirmation email will confirm it again later)
  document.addEventListener("click", e => {
    const b = e.target.closest?.("button, input[type=submit]");
    if (b && SUBMIT.test(b.innerText || b.value || "") && !b.closest("#internship-engine-root")) send("/ext/applied", {
      url: location.href, learned: yoursLeft.map(q => ({ label: q.label, answer: current(q) })).filter(x => x.answer) });
  }, true);

  start();
  // single-page boards (Workday) change the page without reloading: re-check when the URL changes
  let last = location.href;
  setInterval(() => { if (location.href !== last) { last = location.href; start(); } }, 1500);
})();
