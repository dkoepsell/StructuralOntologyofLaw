"use strict";

const $ = (id) => document.getElementById(id);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

/* ---------------------------
   Typology tags (same set)
---------------------------- */
const TAGS = [
  { key: "Conferral failure", loc: "Link 1→3", short: "No valid power for this role/action" },
  { key: "Jurisdictional contradiction", loc: "Link 2→6", short: "Rule/power applied outside its scope" },
  { key: "Procedural contradiction", loc: "Link 2→5", short: "Required steps missing or wrong process" },
  { key: "Temporal contradiction", loc: "Link 2↔4", short: "Timing mismatch (effective dates, retroactivity, overlap)" },
  { key: "Recognition failure", loc: "Link 6/7", short: "Wrong status or status not institutionally supported" },
  { key: "Role contradiction", loc: "Link 3 or 7", short: "Incompatible roles/duties/permissions imposed" },
  { key: "Correlativity contradiction", loc: "Link 7", short: "Rights/duties misaligned (missing correlates)" },
  { key: "Repair failure", loc: "Link 8", short: "No workable remedy or built-in correction" }
];

function getTag(key) { return TAGS.find(t => t.key === key) || TAGS[0]; }

/* ---------------------------
   Domain configuration
---------------------------- */
const DOMAIN = {
  criminal: {
    label: "Criminal law",
    sourceTypes: [
      { value: "", label: "Select..." },
      { value: "state_statute", label: "State criminal statute (recommended)" },
      { value: "federal_statute", label: "Federal criminal statute" },
      { value: "common_law", label: "Common law (if applicable)" }
    ],
    sourceHints: "Example: Texas Penal Code § 31.03; 18 U.S.C. § 875; etc.",
    effectChoices: [
      { value: "", label: "Select..." },
      { value: "exposure_liability", label: "Exposure to criminal liability" },
      { value: "probable_cause", label: "Creation of probable cause / basis for investigation" },
      { value: "alleged_offense", label: "Commission of an alleged offense" },
      { value: "no_legal_effect_yet", label: "No legal effect yet (threat only)" }
    ],
    remedyChoices: [
      { value: "", label: "Select..." },
      { value: "report_investigate", label: "Report to law enforcement (investigation decision)" },
      { value: "prosecution_discretion", label: "Possible prosecution (state discretion)" },
      { value: "civil_protective", label: "Civil protective relief (injunction/harassment order) if available" },
      { value: "bar_discipline", label: "Bar discipline / ethics complaint (if lawyer misconduct)" }
    ],
    overlay: [
      "State criminal code: extortion/blackmail/coercion statutes",
      "Elements of the offense and defenses",
      "Cases on threats involving legal process or reporting",
      "Professional conduct rules on threatening criminal charges for advantage (jurisdiction-specific)",
      "Procedure: evidence preservation, reporting, and any civil protective options"
    ],
    wizard: [
      {
        q: "Was a threat made using legal process (e.g., prosecution, arrest, reporting to authorities) to obtain money or another benefit?",
        help: "This often points toward extortion/blackmail/coercion analysis and correlativity issues."
      },
      {
        q: "Did the person making the threat have a lawful entitlement to the demanded money or benefit?",
        help: "If not, the structure is often 'demand without entitlement' (correlativity mismatch)."
      },
      {
        q: "Is the threatened legal action knowingly baseless, time-barred, or outside the actor’s authority?",
        help: "This can indicate misuse of legal threats and role contradiction (especially if the threat is leveraged as coercion)."
      },
      {
        q: "Is there a clear lawful remedy path that does not require assuming guilt (e.g., report/investigate)?",
        help: "If remedies are unclear or effectively unavailable, repair failure may be present."
      }
    ]
  },

  civil: {
    label: "Civil liability",
    sourceTypes: [
      { value: "", label: "Select..." },
      { value: "state_statute", label: "State statute" },
      { value: "federal_statute", label: "Federal statute" },
      { value: "common_law", label: "Common law doctrine (tort/contract)" }
    ],
    sourceHints: "Example: state contract law; state tort statute; UCC provision; etc.",
    effectChoices: [
      { value: "", label: "Select..." },
      { value: "liability_exposure", label: "Exposure to civil liability" },
      { value: "duty_created", label: "Creation of a duty / obligation" },
      { value: "right_lost", label: "Loss of a right or entitlement" },
      { value: "no_legal_effect_yet", label: "No legal effect yet (dispute stage)" }
    ],
    remedyChoices: [
      { value: "", label: "Select..." },
      { value: "damages", label: "Damages" },
      { value: "injunction", label: "Injunction" },
      { value: "declaratory", label: "Declaratory relief" },
      { value: "rescission", label: "Rescission / restitution (if applicable)" }
    ],
    overlay: [
      "Elements of claim and defenses",
      "Standing and cause of action",
      "Remedies: damages/injunction/declaration",
      "Procedure: jurisdiction/venue, pleading standards"
    ],
    wizard: [
      { q: "Is someone claiming a right or entitlement that the law may not recognize?", help: "This can indicate recognition or correlativity issues." },
      { q: "Is the dispute about whether the rule applies to these facts/people (scope)?", help: "That often points to jurisdictional contradiction." },
      { q: "Is the problem that required steps were not followed (notice, hearing, timing)?", help: "That points to procedural contradiction." },
      { q: "Is there a workable remedy path (cause of action, standing, enforceability)?", help: "If not, repair failure may be present." }
    ]
  },

  constitutional: {
    label: "Constitutional law",
    sourceTypes: [
      { value: "", label: "Select..." },
      { value: "us_const", label: "U.S. Constitution (specify clause/amendment)" },
      { value: "state_const", label: "State constitution" }
    ],
    sourceHints: "Example: U.S. Const. amend. I; amend. XIV; etc.",
    effectChoices: [
      { value: "", label: "Select..." },
      { value: "right_restricted", label: "Restriction of a protected right" },
      { value: "condition_imposed", label: "Unconstitutional condition imposed" },
      { value: "status_changed", label: "Change in legal status (classification, disability, etc.)" },
      { value: "no_legal_effect_yet", label: "No legal effect yet (policy threat/chill)" }
    ],
    remedyChoices: [
      { value: "", label: "Select..." },
      { value: "injunction", label: "Injunction" },
      { value: "declaratory", label: "Declaratory judgment" },
      { value: "suppression", label: "Suppression / exclusion (if applicable)" },
      { value: "damages_1983", label: "Damages under civil rights statute (if available)" }
    ],
    overlay: [
      "Rights doctrine: speech/equal protection/due process",
      "State action and forum analysis (if speech)",
      "Level of scrutiny / tests",
      "Remedies and posture: pre-enforcement, standing, immunity"
    ],
    wizard: [
      { q: "Is the government (or a state institution) restricting a protected activity or right?", help: "If yes, recognition/jurisdictional issues may arise." },
      { q: "Is the restriction targeted at certain viewpoints/content or classifications?", help: "That can indicate jurisdictional contradiction and recognition failure." },
      { q: "Is the problem about procedure (notice/hearing/standards) rather than substance?", help: "That points to procedural contradiction." },
      { q: "Is the remedy path blocked by standing, immunity, or lack of a cause of action?", help: "That points to repair failure." }
    ]
  },

  administrative: {
    label: "Administrative / regulatory",
    sourceTypes: [
      { value: "", label: "Select..." },
      { value: "enabling_statute", label: "Enabling statute (recommended)" },
      { value: "regulation", label: "Regulation (must trace to enabling authority)" },
      { value: "order", label: "Order/adjudication (must trace to authority)" }
    ],
    sourceHints: "Example: Title/section authorizing agency action; rulemaking authority clause.",
    effectChoices: [
      { value: "", label: "Select..." },
      { value: "benefit_denied", label: "Benefit/permission denied or conditioned" },
      { value: "penalty_imposed", label: "Penalty/sanction imposed" },
      { value: "license_revoked", label: "License/authorization revoked" },
      { value: "no_legal_effect_yet", label: "No legal effect yet (proposed rule / notice stage)" }
    ],
    remedyChoices: [
      { value: "", label: "Select..." },
      { value: "admin_appeal", label: "Administrative appeal / internal review" },
      { value: "judicial_review", label: "Judicial review (APA-type) if available" },
      { value: "injunction", label: "Injunction / declaratory relief" },
      { value: "exhaustion", label: "Exhaustion required first (procedural gate)" }
    ],
    overlay: [
      "Enabling statute and scope limits",
      "Required procedures (rulemaking/adjudication)",
      "Standards of review (arbitrary/capricious, substantial evidence)",
      "Remedies and exhaustion"
    ],
    wizard: [
      { q: "Is the actor’s power traceable to a specific enabling statute?", help: "If not, conferral failure is likely." },
      { q: "Is the dispute about whether the rule applies to this target/context (scope)?", help: "That suggests jurisdictional contradiction." },
      { q: "Were required procedures followed (notice/comment, hearing, record)?", help: "That suggests procedural contradiction." },
      { q: "Is there a clear route for appeal or judicial review?", help: "If not, repair failure may be present." }
    ]
  },

  ethics: {
    label: "Professional responsibility / ethics",
    sourceTypes: [
      { value: "", label: "Select..." },
      { value: "rules", label: "Rules of Professional Conduct (jurisdiction-specific)" },
      { value: "bar_authority", label: "Bar/regulatory authority (court rules)" }
    ],
    sourceHints: "Example: ABA Model Rules; Texas Disciplinary Rules; local court rules.",
    effectChoices: [
      { value: "", label: "Select..." },
      { value: "discipline_exposure", label: "Exposure to professional discipline" },
      { value: "duty_breached", label: "Potential breach of professional duty" },
      { value: "no_legal_effect_yet", label: "No legal effect yet (risk stage)" }
    ],
    remedyChoices: [
      { value: "", label: "Select..." },
      { value: "bar_complaint", label: "File a bar complaint / grievance" },
      { value: "court_sanctions", label: "Seek court sanctions (if litigation context)" },
      { value: "injunction", label: "Injunction / protective relief (if harassment/coercion)" }
    ],
    overlay: [
      "Rules on threats and leverage",
      "Conflicts and misuse of process",
      "Disciplinary procedure and remedies",
      "Related civil/criminal statutes if conduct overlaps"
    ],
    wizard: [
      { q: "Is a professional role being used to pressure someone beyond lawful entitlement?", help: "Often indicates role contradiction and correlativity issues." },
      { q: "Is the conduct tied to threats of reporting/prosecution as leverage?", help: "May implicate ethics rules and criminal extortion statutes." },
      { q: "Are internal remedies (bar process) workable and accessible?", help: "If not, repair failure may be present." },
      { q: "Is the governing authority clearly identified (jurisdiction’s rules)?", help: "If not, conferral/recognition issues may arise." }
    ]
  },

  unsure: {
    label: "Unsure – guide me",
    sourceTypes: [
      { value: "", label: "Select..." },
      { value: "unknown", label: "Unknown (start by identifying whether a statute/constitution/rule is involved)" }
    ],
    sourceHints: "Start by identifying whether this is criminal, civil, constitutional, administrative, or ethics.",
    effectChoices: [
      { value: "", label: "Select..." },
      { value: "unknown", label: "Unknown (describe what you think changed legally)" }
    ],
    remedyChoices: [
      { value: "", label: "Select..." },
      { value: "unknown", label: "Unknown (describe what response seems available)" }
    ],
    overlay: [
      "Identify governing legal domain first",
      "Locate a controlling text (statute/regulation/constitution/rules)",
      "Then return and pick the correct domain"
    ],
    wizard: [
      { q: "Is the government involved as actor or regulator?", help: "If yes, constitutional/administrative issues may be present." },
      { q: "Is the issue about punishment or prosecution?", help: "If yes, criminal law may be central." },
      { q: "Is the issue about money damages or breach of agreement?", help: "If yes, civil liability may be central." },
      { q: "Is the issue about lawyer conduct or professional duties?", help: "If yes, ethics may be central." }
    ]
  }
};

let currentDomain = null;

/* ---------------------------
   Overlay map rendering
---------------------------- */
function renderOverlayMap(items) {
  const wrap = $("overlayMap");
  wrap.innerHTML = "";
  const ul = document.createElement("ul");
  for (const it of items) {
    const li = document.createElement("li");
    li.textContent = it;
    ul.appendChild(li);
  }
  wrap.appendChild(ul);
}

/* ---------------------------
   Populate select utilities
---------------------------- */
function fillSelect(el, options) {
  el.innerHTML = "";
  for (const opt of options) {
    const o = document.createElement("option");
    o.value = opt.value;
    o.textContent = opt.label;
    el.appendChild(o);
  }
}

function fillTags() {
  fillSelect($("primaryTag"), TAGS.map(t => ({ value: t.key, label: `${t.key} (${t.loc})` })));
  fillSelect($("secondaryTags"), TAGS.map(t => ({ value: t.key, label: `${t.key} (${t.loc})` })));
}

/* ---------------------------
   Domain gating
---------------------------- */
function getSelectedDomain() {
  const checked = document.querySelector("input[name='domain']:checked");
  return checked ? checked.value : null;
}

function setDomain(domainKey) {
  currentDomain = domainKey;
  const cfg = DOMAIN[domainKey];

  // Populate guided selects
  fillSelect($("sourceType"), cfg.sourceTypes);
  fillSelect($("effectPick"), cfg.effectChoices);
  fillSelect($("remedyPick"), cfg.remedyChoices);

  // Overlay map
  renderOverlayMap(cfg.overlay);

  // Reset wizard
  wizardReset();

  // Update gates
  $("domainGate").textContent = `Domain selected: ${cfg.label}. Workflow unlocked.`;
  $("domainGate").className = "gate gate-ok";

  // Enable chain buttons if validation allows later
  revalidateAll();
}

/* ---------------------------
   Guided field builders
---------------------------- */
function autoComposeSource() {
  const cfg = DOMAIN[currentDomain];
  const type = $("sourceType").value;
  const spec = $("sourceSpecify").value.trim();

  let prefix = "";
  if (type === "state_statute") prefix = "State statute";
  else if (type === "federal_statute") prefix = "Federal statute";
  else if (type === "common_law") prefix = "Common law authority";
  else if (type === "us_const") prefix = "U.S. Constitution";
  else if (type === "state_const") prefix = "State constitution";
  else if (type === "enabling_statute") prefix = "Enabling statute";
  else if (type === "regulation") prefix = "Regulation (trace to enabling statute)";
  else if (type === "order") prefix = "Agency order/adjudication (trace to authority)";
  else if (type === "rules") prefix = "Rules of Professional Conduct";
  else if (type === "bar_authority") prefix = "Bar/court regulatory authority";
  else if (type === "unknown") prefix = "Unknown legal authority";

  const composed = spec ? `${prefix}: ${spec}` : (prefix ? `${prefix}` : "");
  $("chainSource").value = composed;
}

function autoComposeEffect() {
  const pick = $("effectPick").value;
  const desc = $("effectDescribe").value.trim();
  const label = (DOMAIN[currentDomain].effectChoices.find(x => x.value === pick) || {}).label || "";
  const composed = desc ? `${label}. ${desc}` : label;
  $("chainEffect").value = composed;
}

function autoComposeRemedy() {
  const pick = $("remedyPick").value;
  const desc = $("remedyDescribe").value.trim();
  const label = (DOMAIN[currentDomain].remedyChoices.find(x => x.value === pick) || {}).label || "";
  const composed = desc ? `${label}. ${desc}` : label;
  $("chainRemedy").value = composed;
}

/* ---------------------------
   Validation helpers
---------------------------- */
const GENERIC_SOURCE_PATTERNS = [
  /^criminal law$/i,
  /^civil law$/i,
  /^the law$/i,
  /^law$/i,
  /^statute$/i,
  /^constitution$/i,
  /^case law$/i,
  /^rules$/i
];

const NON_LEGAL_EFFECT_HINTS = [
  "felt", "afraid", "scared", "upset", "concerned", "seeking legal advice", "asked a lawyer", "worried", "confused",
  "decided", "went", "called", "emailed", "panic"
];

const ASSUMED_OUTCOME_HINTS = [
  "will be convicted", "will be charged", "will be prosecuted", "will go to jail", "criminal charges against",
  "guaranteed", "certainly", "for sure"
];

function setGate(elId, kind, msg) {
  const el = $(elId);
  if (!msg) {
    el.className = "gate";
    el.textContent = "";
    return;
  }
  el.className = `gate ${kind}`;
  el.textContent = msg;
}

function validateDomain() {
  if (!currentDomain) {
    setGate("domainGate", "gate-warn", "Select a domain to unlock the workflow.");
    return false;
  }
  return true;
}

function validateSource() {
  const text = $("chainSource").value.trim();
  const type = $("sourceType").value;

  if (!text) {
    setGate("sourceGate", "gate-bad", "❌ Source of authority is required. Choose a source type and specify it if possible.");
    return false;
  }
  if (!type) {
    setGate("sourceGate", "gate-bad", "❌ Choose a source type. Then specify a statute section, clause, or rule if possible.");
    return false;
  }
  if (GENERIC_SOURCE_PATTERNS.some(rx => rx.test(text))) {
    setGate("sourceGate", "gate-bad",
      "❌ This is too generic. A source identifies who has power (e.g., a statute section or constitutional clause).");
    return false;
  }
  if (text.length < 8) {
    setGate("sourceGate", "gate-warn", "⚠️ Consider adding a section/clause for clarity.");
    return true;
  }

  setGate("sourceGate", "gate-ok", "✅ Source of authority looks usable.");
  return true;
}

function validateEffect() {
  const pick = $("effectPick").value;
  const text = $("chainEffect").value.trim().toLowerCase();

  if (!pick) {
    setGate("effectGate", "gate-bad", "❌ Legal effect is required. Select a legal-effect category.");
    return false;
  }
  if (!text) {
    setGate("effectGate", "gate-bad", "❌ Legal effect is required.");
    return false;
  }

  // Block common non-legal phrasing if user didn't select a meaningful category
  const containsNonLegal = NON_LEGAL_EFFECT_HINTS.some(h => text.includes(h));
  if (containsNonLegal) {
    setGate("effectGate", "gate-bad",
      "❌ This describes behavior or feelings, not a legal effect. Select what changed legally (rights/duties/status/exposure).");
    return false;
  }

  // If they selected no_legal_effect_yet, warn if they claim strong legal effect language
  if ($("effectPick").value === "no_legal_effect_yet") {
    setGate("effectGate", "gate-warn",
      "⚠️ You selected 'No legal effect yet.' That is often correct for threats/policies. Make sure your remedy does not assume guilt or enforcement.");
    return true;
  }

  setGate("effectGate", "gate-ok", "✅ Legal effect looks legally stated.");
  return true;
}

function validateRemedy() {
  const pick = $("remedyPick").value;
  const text = $("chainRemedy").value.trim().toLowerCase();

  if (!pick) {
    setGate("remedyGate", "gate-bad", "❌ Remedy is required. Select an available response (not an assumed outcome).");
    return false;
  }
  if (!text) {
    setGate("remedyGate", "gate-bad", "❌ Remedy is required.");
    return false;
  }

  const assumed = ASSUMED_OUTCOME_HINTS.some(h => text.includes(h));
  if (assumed) {
    setGate("remedyGate", "gate-bad",
      "❌ This assumes an outcome. Remedies should be pathways (report/investigate, seek injunction, appeal), not guaranteed results.");
    return false;
  }

  // Cross-check: if effect says no legal effect yet, remedy should not be "prosecution" phrased as certainty
  if ($("effectPick").value === "no_legal_effect_yet" && text.includes("prosecution") && !text.includes("possible")) {
    setGate("remedyGate", "gate-warn",
      "⚠️ If there is no legal effect yet, phrase remedies as possible pathways (investigation/possible prosecution), not certainty.");
    return true;
  }

  setGate("remedyGate", "gate-ok", "✅ Remedy looks like an available response pathway.");
  return true;
}

function validateIssueSentence() {
  if (!validateDomain()) {
    setGate("issueGate", "gate-warn", "Select a domain first.");
    return false;
  }
  const s = $("oneSentence").value.trim();
  if (!s) {
    setGate("issueGate", "gate-warn", "Write a one-sentence problem (neutral framing).");
    return false;
  }
  // Light hint for conclusion-leakage
  const leak = /\b(illegal|unlawful|blackmail|extortion|defamation|constitutional)\b/i.test(s) && s.includes("?");
  if (leak) {
    setGate("issueGate", "gate-warn", "⚠️ Try to phrase neutrally before asking the legal question. Example: 'raising whether...' ");
    return true;
  }
  setGate("issueGate", "gate-ok", "✅ Issue sentence is set.");
  return true;
}

/* Global chain validity gate */
function chainIsValid() {
  if (!validateDomain()) return false;
  const okIssue = validateIssueSentence();
  const okSource = validateSource();
  const okEffect = validateEffect();
  const okRemedy = validateRemedy();

  // Other fields are not hard-stopped, but recommended
  const requiredOk = okSource && okEffect && okRemedy && okIssue;

  if (!requiredOk) {
    setGate("chainGlobalGate", "gate-warn",
      "Complete required fields (Source of authority, Legal effect, Remedy) correctly to unlock the wizard and outputs.");
  } else {
    setGate("chainGlobalGate", "gate-ok",
      "✅ Core ontology checks passed. You can run the contradiction wizard and generate outputs.");
  }

  return requiredOk;
}

/* ---------------------------
   Chain line generation
---------------------------- */
function buildChainLine() {
  const c = {
    source: $("chainSource").value.trim() || "[SOURCE]",
    norm: $("chainNorm").value.trim() || "[NORM]",
    actorRole: $("chainActorRole").value.trim() || "[ACTOR IN ROLE]",
    facts: $("chainFacts").value.trim() || "[TRIGGER FACTS]",
    action: $("chainAction").value.trim() || "[LEGAL ACTION]",
    target: $("chainTarget").value.trim() || "[TARGET]",
    effect: $("chainEffect").value.trim() || "[LEGAL EFFECT]",
    remedy: $("chainRemedy").value.trim() || "[ENFORCEMENT / REMEDY]"
  };

  $("chainLine").textContent =
    `Source: ${c.source}  →  Norm: ${c.norm}  →  Actor/Role: ${c.actorRole}  →  Triggering facts: ${c.facts}  →  Action: ${c.action}  →  Target: ${c.target}  →  Effect: ${c.effect}  →  Enforcement/Remedy: ${c.remedy}`;
}

/* ---------------------------
   Wizard: guided yes/no diagnostic
---------------------------- */
let wiz = {
  i: 0,
  answers: [],
  scores: new Map()
};

function wizardUnlock(isUnlocked) {
  const wrap = $("wizard");
  if (isUnlocked) {
    wrap.classList.remove("disabled");
    $("wizardGate").textContent = "";
    $("wizardGate").className = "gate";
  } else {
    wrap.classList.add("disabled");
    setGate("wizardGate", "gate-warn", "Complete Step 3 validations to unlock the wizard.");
  }
}

function wizardReset() {
  wiz = { i: 0, answers: [], scores: new Map() };
  // Reset scores
  TAGS.forEach(t => wiz.scores.set(t.key, 0));

  // Reset UI
  $("wizStepLabel").textContent = "Question";
  $("wizCount").textContent = "0/0";
  $("wizQuestion").textContent = "";
  $("wizHelp").textContent = "";
  $("btnWizBack").disabled = true;

  // Clear tag selects and gates
  $("diagnosticStatement").value = "";
  $("tagLocation").value = "";
  $("primaryTag").value = TAGS[0].key;
  Array.from($("secondaryTags").options).forEach(o => o.selected = false);
  setGate("tagGate", "", "");
  $("btnMakeDiagnosis").disabled = true;
  $("btnCopyDiagnosis").disabled = true;

  // Disable research/irac until tags confirmed
  $("btnMakeResearch").disabled = true;
  $("btnCopyResearch").disabled = true;
  $("btnMakeIRAC").disabled = true;
  $("btnCopyIRAC").disabled = true;
  setGate("finalGate", "gate-warn", "Complete the wizard and confirm a primary contradiction type to generate outputs.");

  if (currentDomain) wizardRenderQuestion();
}

function wizardQuestions() {
  const cfg = DOMAIN[currentDomain || "unsure"];
  return cfg.wizard;
}

function wizardRenderQuestion() {
  const qs = wizardQuestions();
  const total = qs.length;

  $("wizCount").textContent = `${Math.min(wiz.i + 1, total)}/${total}`;
  $("btnWizBack").disabled = wiz.i === 0;

  if (wiz.i >= total) {
    wizardFinish();
    return;
  }

  const item = qs[wiz.i];
  $("wizQuestion").textContent = item.q;
  $("wizHelp").textContent = item.help || "";
}

function bump(tag, amount) {
  wiz.scores.set(tag, (wiz.scores.get(tag) || 0) + amount);
}

function wizardAnswer(yes) {
  const qs = wizardQuestions();
  if (wiz.i >= qs.length) return;

  wiz.answers[wiz.i] = yes;

  // Scoring by domain question index
  // This is intentionally simple and pedagogical, not a hidden ML model.
  const idx = wiz.i;

  if (currentDomain === "criminal") {
    if (idx === 0 && yes) { bump("Correlativity contradiction", 3); bump("Role contradiction", 2); }
    if (idx === 1 && yes) { bump("Correlativity contradiction", 3); }
    if (idx === 2 && yes) { bump("Role contradiction", 2); bump("Procedural contradiction", 1); }
    if (idx === 3 && yes) { bump("Repair failure", 2); }
  } else if (currentDomain === "constitutional") {
    if (idx === 0 && yes) { bump("Jurisdictional contradiction", 2); bump("Recognition failure", 1); }
    if (idx === 1 && yes) { bump("Jurisdictional contradiction", 3); bump("Recognition failure", 2); }
    if (idx === 2 && yes) { bump("Procedural contradiction", 3); }
    if (idx === 3 && yes) { bump("Repair failure", 3); }
  } else if (currentDomain === "administrative") {
    if (idx === 0 && yes) { /* yes means traceable -> less conferral risk */ bump("Conferral failure", -1); }
    if (idx === 0 && !yes) { bump("Conferral failure", 4); }
    if (idx === 1 && yes) { bump("Jurisdictional contradiction", 3); }
    if (idx === 2 && yes) { bump("Procedural contradiction", 3); }
    if (idx === 3 && yes) { bump("Repair failure", 3); }
  } else if (currentDomain === "ethics") {
    if (idx === 0 && yes) { bump("Role contradiction", 3); bump("Correlativity contradiction", 2); }
    if (idx === 1 && yes) { bump("Correlativity contradiction", 2); bump("Role contradiction", 2); }
    if (idx === 2 && yes) { bump("Repair failure", 2); }
    if (idx === 3 && yes) { bump("Conferral failure", 2); bump("Recognition failure", 1); }
  } else if (currentDomain === "civil") {
    if (idx === 0 && yes) { bump("Recognition failure", 2); bump("Correlativity contradiction", 1); }
    if (idx === 1 && yes) { bump("Jurisdictional contradiction", 3); }
    if (idx === 2 && yes) { bump("Procedural contradiction", 3); }
    if (idx === 3 && yes) { bump("Repair failure", 3); }
  } else {
    // unsure
    if (idx === 0 && yes) bump("Jurisdictional contradiction", 1);
    if (idx === 1 && yes) bump("Correlativity contradiction", 1);
    if (idx === 2 && yes) bump("Correlativity contradiction", 1);
    if (idx === 3 && yes) bump("Role contradiction", 1);
  }

  wiz.i += 1;
  wizardRenderQuestion();
}

function wizardBack() {
  if (wiz.i === 0) return;
  wiz.i -= 1;
  // We do not "undo" scores perfectly; reset and replay answers up to wiz.i
  const saved = [...wiz.answers];
  wizardReset();
  wizardUnlock(true);
  // replay
  for (let k = 0; k < wiz.i; k++) {
    if (typeof saved[k] === "boolean") {
      wiz.i = k;
      wizardAnswer(saved[k]);
    }
  }
}

function wizardFinish() {
  // Produce ranked suggestions
  const ranked = [...wiz.scores.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => ({ k, v }))
    .filter(x => x.v > 0);

  // If everything is 0 or negative, default
  const primary = ranked.length ? ranked[0].k : "Jurisdictional contradiction";

  $("primaryTag").value = primary;

  // Set secondary as next top 3 excluding primary
  const secondaries = ranked.slice(1, 4).map(x => x.k);
  Array.from($("secondaryTags").options).forEach(o => o.selected = secondaries.includes(o.value));

  // Recommend location
  $("tagLocation").value = getTag(primary).loc;

  // Enable diagnostic generation
  $("btnMakeDiagnosis").disabled = false;
  $("btnCopyDiagnosis").disabled = false;

  setGate("tagGate", "gate-ok",
    `✅ Wizard complete. Suggested primary: ${primary}. You can adjust tags if needed.`);

  // Now enable downstream generation after diagnostic exists
  $("btnMakeResearch").disabled = false;
  $("btnMakeIRAC").disabled = false;

  setGate("finalGate", "gate-warn", "Generate the diagnostic statement, then generate research plan and IRAC+ output.");
}

function wizardFinishedAlready() {
  const done = $("btnMakeDiagnosis").disabled === false;
  return done;
}

/* ---------------------------
   Diagnostic statement generator
---------------------------- */
function makeDiagnosis() {
  if (!chainIsValid()) {
    setGate("tagGate", "gate-bad", "❌ Fix chain validation errors before generating a diagnosis.");
    return;
  }
  if (!wizardFinishedAlready()) {
    setGate("tagGate", "gate-bad", "❌ Complete the contradiction wizard first.");
    return;
  }

  const primary = $("primaryTag").value;
  const t = getTag(primary);
  const loc = $("tagLocation").value || t.loc;

  const effect = $("chainEffect").value.trim();
  const remedy = $("chainRemedy").value.trim();

  const reason = effect ? `because it produces ${effect}` : "because of the identified mismatch in the chain";
  const repair = remedy ? `unless repaired via ${remedy}` : "unless repaired via an available remedy";

  const diag = `This dispute is best understood as a ${t.key}, located at ${loc}, ${reason}, ${repair}.`;
  $("diagnosticStatement").value = diag;

  setGate("finalGate", "gate-ok", "✅ Diagnostic statement generated. You can now generate the research plan and IRAC+ draft.");
}

/* ---------------------------
   Research plan generator (domain-locked + tag-locked)
---------------------------- */
function makeResearchPlan() {
  if (!chainIsValid()) {
    setGate("finalGate", "gate-bad", "❌ Fix validation errors before generating research guidance.");
    return;
  }
  if (!wizardFinishedAlready()) {
    setGate("finalGate", "gate-bad", "❌ Complete the wizard first.");
    return;
  }
  const primary = getTag($("primaryTag").value);
  const secs = Array.from($("secondaryTags").selectedOptions).map(o => o.value);
  const cfg = DOMAIN[currentDomain];

  const lines = [];
  lines.push(`Domain: ${cfg.label}`);
  lines.push(`Primary tag: ${primary.key} (${primary.loc})`);
  lines.push("");

  lines.push("A) Start here (domain-first outline entry points)");
  for (const it of cfg.overlay) lines.push(`- ${it}`);
  lines.push("");

  lines.push("B) Then narrow by the contradiction type");
  lines.push(`- ${primary.key}: ${primary.short}`);
  lines.push("");

  if (secs.length) {
    lines.push("C) Secondary tags to check");
    for (const s of secs) {
      const st = getTag(s);
      lines.push(`- ${st.key} (${st.loc}): ${st.short}`);
    }
    lines.push("");
  }

  lines.push("D) Authority bundle to collect (by function)");
  lines.push("- Confers authority (source text + delegation/competence where relevant)");
  lines.push("- Limits authority (rights/scope/defenses)");
  lines.push("- Defines elements/tests (what must be proven, burdens, exceptions)");
  lines.push("- Defines procedures (if the dispute turns on process)");
  lines.push("- Supplies remedies and posture (standing, review routes, enforcement discretion)");

  $("researchPlan").textContent = lines.join("\n");
  $("btnCopyResearch").disabled = false;
}

/* ---------------------------
   IRAC+ draft generator (blocked unless valid)
---------------------------- */
function makeIRAC() {
  if (!chainIsValid()) {
    setGate("finalGate", "gate-bad", "❌ Fix validation errors before generating IRAC+ output.");
    return;
  }
  if (!wizardFinishedAlready()) {
    setGate("finalGate", "gate-bad", "❌ Complete the wizard first.");
    return;
  }
  const issue = $("oneSentence").value.trim() || "[Insert one-sentence problem.]";
  const chainLine = $("chainLine").textContent || "[Generate chain line first.]";
  const diag = $("diagnosticStatement").value.trim() || "[Generate diagnostic statement first.]";

  const primary = getTag($("primaryTag").value);
  const cfg = DOMAIN[currentDomain];

  const R = [
    `Rule(s) to research (guided by domain + ${primary.key}):`,
    `- Domain: ${cfg.label}`,
    `- Structural focus: ${primary.loc} (${primary.short})`,
    "",
    "Insert controlling authorities here after research:",
    "- [Governing text: statute/regulation/constitution/rules]",
    "- [Key interpretive cases applying the test/elements]",
    "- [Any defenses/exceptions/burdens relevant to the domain]"
  ].join("\n");

  const A = [
    "Application (link-by-link):",
    `1) Source of authority: ${$("chainSource").value.trim()}`,
    `2) Norm: ${$("chainNorm").value.trim() || "[NORM]"}`,
    `3) Actor in a role: ${$("chainActorRole").value.trim() || "[ACTOR/ROLE]"}`,
    `4) Triggering facts: ${$("chainFacts").value.trim() || "[FACTS]"}`,
    `5) Legal action: ${$("chainAction").value.trim() || "[ACTION]"}`,
    `6) Target: ${$("chainTarget").value.trim() || "[TARGET]"}`,
    `7) Legal effect: ${$("chainEffect").value.trim()}`,
    `8) Enforcement/remedy: ${$("chainRemedy").value.trim()}`,
    "",
    `Structural pressure point: ${$("tagLocation").value || primary.loc}`,
    "After research, apply each element/test to the triggering facts and show precisely where coherence fails or holds."
  ].join("\n");

  const C = [
    "Conclusion:",
    `Based on the current structural map, the issue is best framed as a ${primary.key}.`,
    "After collecting controlling authority, refine whether the mismatch is:",
    "- repaired (narrowing construction, correct procedure, clarified scope, proper remedy), or",
    "- fatal (invalid act/policy/offense/claim fails as a matter of law)."
  ].join("\n");

  const out = [
    "IRAC+ Draft",
    "====================",
    "",
    "I) Issue",
    issue,
    "",
    "S-Map) Minimum Legal Chain",
    chainLine,
    "",
    "C-Tag) Diagnostic statement",
    diag,
    "",
    "R) Rule(s)",
    R,
    "",
    "A) Application",
    A,
    "",
    "C) Conclusion",
    C
  ].join("\n");

  $("iracDraft").textContent = out;
  $("btnCopyIRAC").disabled = false;
}

/* ---------------------------
   Copy / export / print
---------------------------- */
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    alert("Copied to clipboard.");
  } catch {
    alert("Copy failed. You can select and copy manually.");
  }
}

function exportJSON() {
  const payload = JSON.stringify(currentState(), null, 2);
  const blob = new Blob([payload], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "iracplus_case.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/* ---------------------------
   State
---------------------------- */
function currentState() {
  return {
    domain: currentDomain,
    oneSentence: $("oneSentence").value.trim(),
    anchors: {
      actors: $("anchorsActors").value.trim(),
      roles: $("anchorsRoles").value.trim(),
      norms: $("anchorsNorms").value.trim(),
      event: $("anchorsEvent").value.trim()
    },
    chain: {
      sourceType: $("sourceType").value,
      sourceSpecify: $("sourceSpecify").value.trim(),
      source: $("chainSource").value.trim(),
      norm: $("chainNorm").value.trim(),
      actorRole: $("chainActorRole").value.trim(),
      facts: $("chainFacts").value.trim(),
      action: $("chainAction").value.trim(),
      target: $("chainTarget").value.trim(),
      effectPick: $("effectPick").value,
      effectDescribe: $("effectDescribe").value.trim(),
      effect: $("chainEffect").value.trim(),
      remedyPick: $("remedyPick").value,
      remedyDescribe: $("remedyDescribe").value.trim(),
      remedy: $("chainRemedy").value.trim()
    },
    tags: {
      primary: $("primaryTag").value,
      secondary: Array.from($("secondaryTags").selectedOptions).map(o => o.value),
      location: $("tagLocation").value,
      diagnostic: $("diagnosticStatement").value.trim()
    },
    outputs: {
      chainLine: $("chainLine").textContent,
      researchPlan: $("researchPlan").textContent,
      iracDraft: $("iracDraft").textContent
    }
  };
}

function setState(state) {
  // domain
  if (state.domain) {
    const r = document.querySelector(`input[name='domain'][value='${state.domain}']`);
    if (r) r.checked = true;
    setDomain(state.domain);
  }

  $("oneSentence").value = state.oneSentence || "";

  $("anchorsActors").value = state.anchors?.actors || "";
  $("anchorsRoles").value = state.anchors?.roles || "";
  $("anchorsNorms").value = state.anchors?.norms || "";
  $("anchorsEvent").value = state.anchors?.event || "";

  // chain guided
  $("sourceType").value = state.chain?.sourceType || "";
  $("sourceSpecify").value = state.chain?.sourceSpecify || "";
  autoComposeSource();
  if (state.chain?.source) $("chainSource").value = state.chain.source;

  $("chainNorm").value = state.chain?.norm || "";
  $("chainActorRole").value = state.chain?.actorRole || "";
  $("chainFacts").value = state.chain?.facts || "";
  $("chainAction").value = state.chain?.action || "";
  $("chainTarget").value = state.chain?.target || "";

  $("effectPick").value = state.chain?.effectPick || "";
  $("effectDescribe").value = state.chain?.effectDescribe || "";
  autoComposeEffect();
  if (state.chain?.effect) $("chainEffect").value = state.chain.effect;

  $("remedyPick").value = state.chain?.remedyPick || "";
  $("remedyDescribe").value = state.chain?.remedyDescribe || "";
  autoComposeRemedy();
  if (state.chain?.remedy) $("chainRemedy").value = state.chain.remedy;

  // tags
  $("primaryTag").value = state.tags?.primary || TAGS[0].key;
  const secs = new Set(state.tags?.secondary || []);
  Array.from($("secondaryTags").options).forEach(o => o.selected = secs.has(o.value));
  $("tagLocation").value = state.tags?.location || "";
  $("diagnosticStatement").value = state.tags?.diagnostic || "";

  // outputs
  $("chainLine").textContent = state.outputs?.chainLine || "";
  $("researchPlan").textContent = state.outputs?.researchPlan || "";
  $("iracDraft").textContent = state.outputs?.iracDraft || "";

  revalidateAll();
}

/* ---------------------------
   Validation / enabling toggles
---------------------------- */
function revalidateAll() {
  const okDomain = validateDomain();
  if (!okDomain) {
    // lock everything
    $("btnMakeChain").disabled = true;
    $("btnCopyChain").disabled = true;
    wizardUnlock(false);
    $("btnMakeResearch").disabled = true;
    $("btnMakeIRAC").disabled = true;
    return;
  }

  validateIssueSentence();

  // keep guided compositions in sync
  validateSource();
  validateEffect();
  validateRemedy();

  const okChain = chainIsValid();

  $("btnMakeChain").disabled = !okChain;
  $("btnCopyChain").disabled = $("chainLine").textContent.length === 0;

  wizardUnlock(okChain);

  // If chain is valid, allow chain line generation; wizard must complete for outputs
  $("btnMakeResearch").disabled = !wizardFinishedAlready();
  $("btnMakeIRAC").disabled = !wizardFinishedAlready();

  // Enable copy buttons if outputs exist
  $("btnCopyResearch").disabled = $("researchPlan").textContent.trim().length === 0;
  $("btnCopyIRAC").disabled = $("iracDraft").textContent.trim().length === 0;
}

/* ---------------------------
   Clear / samples
---------------------------- */
function clearAll() {
  currentDomain = null;
  $$("input[name='domain']").forEach(r => r.checked = false);

  $("oneSentence").value = "";
  $("anchorsActors").value = "";
  $("anchorsRoles").value = "";
  $("anchorsNorms").value = "";
  $("anchorsEvent").value = "";

  $("sourceType").innerHTML = "";
  $("sourceSpecify").value = "";
  $("chainSource").value = "";

  $("chainNorm").value = "";
  $("chainActorRole").value = "";
  $("chainFacts").value = "";
  $("chainAction").value = "";
  $("chainTarget").value = "";

  $("effectPick").innerHTML = "";
  $("effectDescribe").value = "";
  $("chainEffect").value = "";

  $("remedyPick").innerHTML = "";
  $("remedyDescribe").value = "";
  $("chainRemedy").value = "";

  $("chainLine").textContent = "";
  $("researchPlan").textContent = "";
  $("iracDraft").textContent = "";
  $("diagnosticStatement").value = "";
  $("tagLocation").value = "";

  fillTags();
  wizardReset();

  setGate("domainGate", "gate-warn", "Select a domain to unlock the workflow.");
  setGate("chainGlobalGate", "gate-warn", "Select a domain, then complete required fields.");
  setGate("finalGate", "gate-warn", "Complete the wizard and confirm a primary contradiction type to generate outputs.");

  $("btnMakeChain").disabled = true;
  $("btnCopyChain").disabled = true;
  wizardUnlock(false);
}

function loadSampleTexasUniversity() {
  const sample = {
    domain: "constitutional",
    oneSentence: "A public university system conditions or restricts professors’ classroom instruction by requiring prior approval for courses that ‘advocate’ certain ideas about race or gender, raising whether the restriction violates the First Amendment.",
    anchors: {
      actors: "Texas public university system; system administrators; campus presidents/designees; professors; students.",
      roles: "University system as state actor and institutional manager; administrators as policy enforcers; professors as academic instructors and speakers; students as recipients of instruction.",
      norms: "First Amendment; academic freedom doctrine; viewpoint discrimination rules; public employee speech doctrine with academic reservation.",
      event: "System revises course rules: certain ‘advocacy’ of race/gender ideology requires prior approval; compliance enforced via course/syllabus review."
    },
    chain: {
      sourceType: "us_const",
      sourceSpecify: "U.S. Const. amend. I (speech) and amend. XIV (state action)",
      source: "U.S. Constitution: U.S. Const. amend. I (speech) and amend. XIV (state action)",
      norm: "Institutional rule: courses may not advocate specified race/gender ideologies unless pre-approved; instructors must adhere to approved syllabi.",
      actorRole: "University system administrators/presidents as institutional governors acting on faculty instructors (academic speakers).",
      facts: "Course content involving race/gender concepts is flagged as advocacy under policy definitions; prior approval absent or required; enforcement threat chills instruction.",
      action: "Conditioning classroom instruction on prior approval and restricting defined ideological advocacy.",
      target: "Professors teaching courses (public employees with academic instructional duties).",
      effectPick: "right_restricted",
      effectDescribe: "Faculty permission to engage in academic speech is conditioned on ideological approval; chilling effect.",
      effect: "Restriction of a protected right. Faculty permission to engage in academic speech is conditioned on ideological approval; chilling effect.",
      remedyPick: "injunction",
      remedyDescribe: "Pre-enforcement constitutional challenge seeking declaratory and injunctive relief.",
      remedy: "Injunction. Pre-enforcement constitutional challenge seeking declaratory and injunctive relief."
    },
    tags: {
      primary: "Jurisdictional contradiction",
      secondary: ["Recognition failure", "Role contradiction", "Procedural contradiction", "Repair failure"],
      location: "Multiple",
      diagnostic: ""
    }
  };

  setState(sample);
  buildChainLine();
  wizardUnlock(chainIsValid());
  // Run wizard quickly to completion for demo
  // (We do not auto-answer; user should use it. We'll mark as completed by enabling diagnosis.)
  setGate("wizardGate", "gate-warn", "Sample loaded. Run the wizard questions to get suggested contradiction types.");
}

function loadSampleCriminalThreat() {
  const sample = {
    domain: "criminal",
    oneSentence: "A lawyer threatens to report or pursue criminal charges to obtain payment from a private person, raising whether the conduct constitutes extortion/blackmail or unlawful coercion under applicable criminal law.",
    anchors: {
      actors: "Lawyer; recipient of threat; possibly law enforcement; prosecutor; bar authority.",
      roles: "Lawyer acting in private/professional role; private person as target; state as enforcer; bar as disciplinary authority.",
      norms: "State extortion/blackmail/coercion statutes; definitions of threat; professional conduct rules about threats for advantage (jurisdiction-specific).",
      event: "Email demands payment and threatens criminal accusations or reporting; underlying criminal claim may be time-barred or baseless."
    },
    chain: {
      sourceType: "state_statute",
      sourceSpecify: "State penal code provision defining extortion/blackmail/coercion (insert jurisdiction and section)",
      source: "State statute: State penal code provision defining extortion/blackmail/coercion (insert jurisdiction and section)",
      norm: "Elements of extortion/blackmail: obtaining property/benefit by threat where there is no lawful entitlement; threat definition and defenses vary by jurisdiction.",
      actorRole: "Lawyer as threat-maker; target as private person.",
      facts: "Email demands money; threatens criminal accusation/reporting; demand may exceed any lawful entitlement; underlying accusation may be baseless or time-barred.",
      action: "Threat communicated by email to obtain payment.",
      target: "Private person (target of threat).",
      effectPick: "no_legal_effect_yet",
      effectDescribe: "Threat creates risk exposure and attempted coercion; legal status may not change unless reported/acted upon.",
      effect: "No legal effect yet (threat only). Threat creates risk exposure and attempted coercion; legal status may not change unless reported/acted upon.",
      remedyPick: "report_investigate",
      remedyDescribe: "Report to law enforcement for investigation; possible bar complaint depending on jurisdiction rules.",
      remedy: "Report to law enforcement (investigation decision). Report to law enforcement for investigation; possible bar complaint depending on jurisdiction rules."
    }
  };

  setState(sample);
  buildChainLine();
  setGate("wizardGate", "gate-warn", "Sample loaded. Run the wizard to get contradiction-type suggestions.");
}

/* ---------------------------
   Wiring
---------------------------- */
function init() {
  fillTags();
  clearAll();

  // Domain selection
  $$("input[name='domain']").forEach(r => {
    r.addEventListener("change", () => {
      const d = getSelectedDomain();
      if (d) setDomain(d);
    });
  });

  // Guided source/effect/remedy composition
  $("sourceType").addEventListener("change", () => { autoComposeSource(); revalidateAll(); });
  $("sourceSpecify").addEventListener("input", () => { autoComposeSource(); revalidateAll(); });
  $("chainSource").addEventListener("input", revalidateAll);

  $("effectPick").addEventListener("change", () => { autoComposeEffect(); revalidateAll(); });
  $("effectDescribe").addEventListener("input", () => { autoComposeEffect(); revalidateAll(); });
  $("chainEffect").addEventListener("input", revalidateAll);

  $("remedyPick").addEventListener("change", () => { autoComposeRemedy(); revalidateAll(); });
  $("remedyDescribe").addEventListener("input", () => { autoComposeRemedy(); revalidateAll(); });
  $("chainRemedy").addEventListener("input", revalidateAll);

  // Other fields
  ["oneSentence","chainNorm","chainActorRole","chainFacts","chainAction","chainTarget",
   "anchorsActors","anchorsRoles","anchorsNorms","anchorsEvent"]
    .forEach(id => $(id).addEventListener("input", revalidateAll));

  // Chain line
  $("btnMakeChain").addEventListener("click", () => {
    if (!chainIsValid()) return;
    buildChainLine();
    $("btnCopyChain").disabled = $("chainLine").textContent.trim().length === 0;
  });
  $("btnCopyChain").addEventListener("click", () => copyText($("chainLine").textContent || ""));

  // Wizard controls
  $("btnWizYes").addEventListener("click", () => wizardAnswer(true));
  $("btnWizNo").addEventListener("click", () => wizardAnswer(false));
  $("btnWizBack").addEventListener("click", wizardBack);
  $("btnWizReset").addEventListener("click", wizardReset);

  // Diagnosis / research / IRAC
  $("btnMakeDiagnosis").addEventListener("click", makeDiagnosis);
  $("btnCopyDiagnosis").addEventListener("click", () => copyText($("diagnosticStatement").value || ""));

  $("btnMakeResearch").addEventListener("click", makeResearchPlan);
  $("btnCopyResearch").addEventListener("click", () => copyText($("researchPlan").textContent || ""));

  $("btnMakeIRAC").addEventListener("click", makeIRAC);
  $("btnCopyIRAC").addEventListener("click", () => copyText($("iracDraft").textContent || ""));

  // Toolbar
  $("btnExport").addEventListener("click", exportJSON);
  $("btnPrint").addEventListener("click", () => window.print());
  $("btnClear").addEventListener("click", clearAll);
  $("btnLoadSample").addEventListener("click", loadSampleTexasUniversity);
  $("btnLoadSampleCriminal").addEventListener("click", loadSampleCriminalThreat);

  // Initialize wizard UI placeholders
  wizardUnlock(false);
}

document.addEventListener("DOMContentLoaded", init);
