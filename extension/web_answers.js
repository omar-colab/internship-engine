// Browser-side answer rules for users who only use the hosted app.
(() => {
  const SENSITIVE = /social security|\bssn\b|\bsin\b|date of birth|\bdob\b|birth ?date|passport|driver.?s? licen|license number|bank|routing|account number|credit card|card number|password|passcode|\bpin\b|tax id|\btin\b|national id/i;
  const DECLINE = /decline|don.?t wish|prefer not|not to (answer|disclose|say)|choose not/i;
  const plain = s => String(s || "").toLowerCase().replace(/[’']/g, "").replace(/[^a-z0-9 ]/g, "");
  const pick = (options, ...prefs) => {
    for (const rx of prefs) for (const option of options)
      if (rx.test(option) || rx.test(plain(option))) return option;
    return null;
  };
  const yesNo = (options, yes) => pick(options, yes ? /^\s*yes\b/i : /^\s*no\b/i);
  const key = label => plain(String(label).slice(0, 500).replace(/[*✱]|\(required\)/g, "")).trim().replace(/\s+/g, " ");
  const auth = (p, name, field, yesMeans) => {
    const value = p[name] == null ? "unknown" : p[name];
    // "sponsor" can't answer "authorized to work?" either way (F-1/CPT depends on the role), so the person answers it.
    if (value === "unknown" || value === "" || (name === "work_authorization" && value === "sponsor")) return null;
    const yes = name === "work_authorization"
      ? ["citizen", "permanent", "us_citizen", "permanent_resident", "authorized", true, "yes"].includes(value)
      : [true, "yes"].includes(value);
    return field.options && field.options.length ? yesNo(field.options, yesMeans ? yes : !yes) : (yes ? "Yes" : "No");
  };
  const grad = (options, p) => {
    const y = Number(String(p.graduation || "").slice(0, 4)), m = Number(String(p.graduation || "").slice(5, 7));
    if (!y || m < 1 || m > 12) return null;
    const season = m <= 6 ? "spring" : m >= 9 ? "fall" : "summer";
    const month = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"][m - 1];
    return pick(options, new RegExp(season + "\\s*" + y + "|" + y + "\\s*" + season, "i"), new RegExp(month + "\\s*" + y, "i"), new RegExp("\\b" + y + "\\b", "i"));
  };
  const suggest = (label, text) => {
    const ignored = new Set(["what", "your", "with", "this", "that", "have", "about", "would", "describe", "please"]);
    const words = new Set((label.toLowerCase().match(/[a-z]{4,}/g) || []).filter(word => !ignored.has(word)));
    return String(text || "").split(/\r?\n/).map(line => line.trim()).filter(line => line.length > 40)
      .map(line => {
        const lineWords = new Set(line.toLowerCase().match(/[a-z]{4,}/g) || []);
        let score = 0;
        for (const word of words) if (lineWords.has(word)) score++;
        return [score, line];
      }).filter(([score]) => score).sort((a, b) => b[0] - a[0] || b[1].localeCompare(a[1])).slice(0, 3)
      .map(([, line]) => line.replace(/^[•\s]+/, ""));
  };
  const rules = [
    [/gender|sex\b|\brace\b|racial|ethnic|hispanic|latin|veteran|disabilit|sexual orientation|transgender|pronoun/i,
      (p, f) => p.eeo === "decline" && f.options && pick(f.options, DECLINE) ? [pick(f.options, DECLINE), "profile.eeo=decline"] : null],
    [/^\s*first name|given name/i, p => [p.first_name, "profile.first_name"]],
    [/^\s*last name|family name|surname/i, p => [p.last_name, "profile.last_name"]],
    [/preferred (first )?name/i, p => [p.first_name, "profile.first_name"]],
    [/^\s*(full )?name\*?\s*$/i, p => [(p.first_name || "") + " " + (p.last_name || ""), "profile.first_name+last_name"]],
    [/e-?mail/i, p => [p.email, "profile.email"]],
    [/^\s*country\b/i, (p, f) => [pick(f.options || [], new RegExp("^" + String(p.country || "") + "\\b", "i")) || p.country, "profile.country"]],
    [/phone|mobile/i, p => [p.phone, "profile.phone"]],
    [/linkedin/i, p => [p.linkedin, "profile.linkedin"]],
    [/\blocation|\bcity\b|where (do you|are you) (live|located|based)/i, (p, f) => {
      const country = p.country && pick(f.options || [], new RegExp("^" + String(p.country) + "$", "i"));
      return f.label.length < 40 ? (country ? [country, "profile.country"] : [(p.city || "") + (p.state ? ", " + p.state : ""), "profile.city+state"]) : null;
    }],
    [/^\s*(resume|cv)\b|attach/i, p => [p.resume_pdf, "profile.resume_pdf"]],
    [/^\s*school|university|college|institution/i, p => [p.school, "profile.school"]],
    [/^\s*degree\b|degree type|level of (education|study)/i, (p, f) => [pick(f.options || [], /bachelor/i) || p.degree_type, "profile.degree_type"]],
    [/^\s*(discipline|major)\b|field of study|area of study|what (is|was) your major/i, p => [p.major, "profile.major"]],
    [/graduat/i, (p, f) => [f.options && f.options.length ? grad(f.options, p) || p.graduation : /date|year/i.test(f.label) ? p.graduation : null, "profile.graduation"]],
    [/(legally )?(authori[sz]ed|eligible) to work/i, (p, f) => [auth(p, "work_authorization", f, true), "profile.work_authorization"]],
    [/sponsor/i, (p, f) => [auth(p, "needs_sponsorship", f, true), "profile.needs_sponsorship"]],
    [/relocat/i, (p, f) => p.open_to_relocation == null ? null : [yesNo(f.options || [], !!p.open_to_relocation) || (p.open_to_relocation ? "Yes" : "No"), "profile.open_to_relocation"]],
    [/how did you (hear|find|learn)|source|referr(al|ed) (source|by)/i, (p, f) => [pick(f.options || [], /job board|website|online|internet|other/i) || p.heard_about, "profile.heard_about"]],
  ];
  const answer = (field, profile, bank, resumeText) => {
    const label = String(field.label || "").replace(/[*✱]|\(required\)/g, "").trim(), kind = field.kind || "text", options = field.options || [];
    if (SENSITIVE.test(label)) return { label, kind, answer: null, source: null, status: field.required ? "needs_you" : "skip", ...(field.required ? { options: options.slice(0, 12) } : {}) };
    let got = null;
    for (const pair of rules) if (pair[0].test(label)) { got = pair[1](profile, field); break; }
    const searchable = got && ["profile.school", "profile.city+state"].includes(got[1]);
    const openList = !options.length || (kind === "combobox" && (options.length >= 60 || searchable));
    if (got && got[0] && (openList || options.some(o => plain(o) === plain(got[0]))))
      return { label, kind, answer: got[0], source: got[1], status: "auto" };
    const saved = (bank || {})[key(label)];
    if (saved && kind !== "textarea" && kind !== "file") {
      const hit = options.length ? options.find(o => plain(o) === plain(saved.answer)) : saved.answer;
      if (hit) return { label, kind, answer: hit, source: "you (" + (saved.on || "saved") + ")", status: "auto" };
    }
    if (!field.required) return { label, kind, answer: null, source: null, status: "skip" };
    const suggestions = ["textarea", "text"].includes(kind) ? (saved ? [saved.answer] : []).concat(suggest(label, resumeText)) : [];
    return { label, kind, answer: null, source: null, status: "needs_you", options: options.slice(0, 12), suggest: suggestions };
  };
  globalThis.InternshipWebAnswers = { answer, key, sensitive: label => SENSITIVE.test(label) };
  if (typeof module !== "undefined") module.exports = globalThis.InternshipWebAnswers;
})();
