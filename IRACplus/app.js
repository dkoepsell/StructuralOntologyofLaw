import { SOOL_TERMS } from "./SOOL_TERMS.js";

/* ============================================================
   SOoL IRAC+ Engine
   Full workflow restored
   Terminology locked to poem and square
   ============================================================ */

const CHAIN_IDS = {
  1: "chainSource",
  2: "chainNorm",
  3: "chainActorRole",
  4: "chainFacts",
  5: "chainAction",
  6: "chainTarget",
  7: "chainEffect",
  8: "chainRemedy"
};

const $ = (id) => document.getElementById(id);
const qsa = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  domain: "",
  wizard: {
    idx: 0,
    answers: [],
    scores: new Map()
  }
};
async function loadMLCWidget(){
  const host = document.getElementById("mlcHost");
  if (!host) return;

  const res = await fetch("./mlc-status.svg");
  host.innerHTML = await res.text();
}

/* ---------------------------
   Boot
--------------------------- */
document.addEventListener("DOMContentLoaded", async () => {
  initScores();
  bindEvents();
  populateStaticSelects();
  await loadMLCWidget();
  refreshAllGates();
});


/* ---------------------------
   Canonical contradiction list
--------------------------- */
function contradictionList() {
  return Object.values(SOOL_TERMS.CONTRADICTIONS)
    .slice()
    .sort((a, b) => a.id - b.id);
}

function initScores() {
  state.wizard.scores = new Map();
  contradictionList().forEach(c => state.wizard.scores.set(c.name, 0));
}

/* ---------------------------
   Domain-specific picklists
--------------------------- */
function sourceTypeOptions(domain) {
  const base = [
    { v: "", t: "Select a source type" },
    { v: "constitution", t: "Constitution" },
    { v: "statute", t: "Statute" },
    { v: "regulation", t: "Regulation" },
    { v: "case", t: "Case law (precedent)" },
    { v: "local", t: "Local ordinance / policy" },
    { v: "contract", t: "Contract / agreement" },
    { v: "professional", t: "Professional rule / code" }
  ];
  if (domain === "criminal") return base;
  if (domain === "civil") return base;
  if (domain === "constitutional") return base;
  if (domain === "administrative") return base;
  if (domain === "ethics") return base;
  return base;
}

function effectOptions(domain) {
  const base = [
    { v: "", t: "Select legal effect category" },
    { v: "no_effect_yet", t: "No legal effect yet (threat only, not acted upon)" },
    { v: "duty", t: "Duty imposed / obligation created" },
    { v: "right", t: "Right recognized / affirmed" },
    { v: "liability", t: "Liability or exposure increased" },
    { v: "status", t: "Status changed (license, eligibility, custody, etc.)" },
    { v: "penalty", t: "Penalty imposed (fine, sentence, sanction)" },
    { v: "restriction", t: "Restriction imposed (speech, movement, access)" },
    { v: "benefit", t: "Benefit granted or denied" }
  ];
  return base;
}

function remedyOptions(domain) {
  const base = [
    { v: "", t: "Select remedy type" },
    { v: "injunction", t: "Injunction / court order" },
    { v: "declaratory", t: "Declaratory relief" },
    { v: "damages", t: "Damages / compensation" },
    { v: "suppression", t: "Suppression / exclusion of evidence" },
    { v: "appeal", t: "Appeal / review" },
    { v: "administrative", t: "Administrative appeal / hearing" },
    { v: "discipline", t: "Discipline / sanction (institutional)" },
    { v: "criminal_process", t: "Criminal investigation / prosecution decision" }
  ];
  return base;
}

/* ---------------------------
   Wizard questions (yes/no)
   Each YES adds weights to contradiction types
--------------------------- */
const WIZARD = [
  {
    q: "Is the actor claiming power without a valid source of authority behind it?",
    help: "If there is no valid Source of authority, legality cannot stand.",
    yes: { "Conferral failure": 3 }
  },
  {
    q: "Is the actor acting outside the role that the system actually confers?",
    help: "Actor in role must be real, not merely asserted.",
    yes: { "Role contradiction": 3, "Conferral failure": 1 }
  },
  {
    q: "Is the norm being applied to a target outside its jurisdiction or scope?",
    help: "Jurisdictional contradiction is the classic Link 2↔6 mismatch.",
    yes: { "Jurisdictional contradiction": 4 }
  },
  {
    q: "Were required procedural steps skipped or not satisfied?",
    help: "Procedural contradiction is a mismatch between Norm and Legal action / omission (Link 2→5).",
    yes: { "Procedural contradiction": 4 }
  },
  {
    q: "Is the norm being applied at the wrong time relative to the triggering facts?",
    help: "Temporal contradiction is a mismatch between Norm and Triggering facts (Link 2↔4).",
    yes: { "Temporal contradiction": 4 }
  },
  {
    q: "Is the system refusing to recognize the target or the legal effect as legally salient?",
    help: "Recognition failure lives at the Target and Legal effect positions (Link 6/7).",
    yes: { "Recognition failure": 4 }
  },
  {
    q: "Is a right asserted without a corresponding duty, or a duty imposed without a corresponding right?",
    help: "Correlativity contradiction is a mismatch inside Legal effect (Link 7).",
    yes: { "Correlativity contradiction": 4 }
  },
  {
    q: "Even if there is a violation, is there no remedy available in the system?",
    help: "Repair failure is the Remedy position (Link 8).",
    yes: { "Repair failure": 4 }
  },
  {
    q: "Is a remedy named but legally barred or not permitted for recognition reasons?",
    help: "Recognition repair failure is a Remedy failure tied to recognition conditions.",
    yes: { "Recognition repair failure": 4 }
  },
  {
    q: "Is a remedy available in theory but blocked by procedure or inability to initiate it?",
    help: "Procedural repair failure is a Remedy failure tied to procedural barriers.",
    yes: { "Procedural repair failure": 4 }
  },
  {
    q: "Is a remedy blocked because no court or institution has jurisdiction to grant it?",
    help: "Jurisdictional repair failure is a Remedy failure tied to jurisdiction.",
    yes: { "Jurisdictional repair failure": 4 }
  },
  {
    q: "Do multiple failures appear to be present at once?",
    help: "Compound contradiction is multiple breaks colliding.",
    yes: { "Compound contradiction": 4 }
  },
  {
    q: "Does the system appear to know the contradiction exists and still let it persist as normal practice?",
    help: "Institutionalized contradiction is contradiction that has become stable in the institution.",
    yes: { "Institutionalized contradiction": 4 }
  }
];

/* ---------------------------
   Bind events
--------------------------- */
function bindEvents() {
  // domain
  qsa('input[name="domain"]').forEach(r => {
    r.addEventListener("change", () => {
      state.domain = r.value;
      populateGuidedPicklists();
      refreshAllGates();
    });
  });

  // toolbar
  $("btnLoadSample")?.addEventListener("click", loadUniversitySample);
  $("btnLoadSampleCriminal")?.addEventListener("click", loadCriminalSample);
  $("btnClear")?.addEventListener("click", clearAll);
  $("btnExport")?.addEventListener("click", exportJSON);
  $("btnPrint")?.addEventListener("click", () => window.print());

  // chain inputs refresh gates
  Object.values(CHAIN_IDS).forEach(id => {
    $(id)?.addEventListener("input", refreshAllGates);
  });

  $("sourceType")?.addEventListener("change", onAuthorityPickChange);
  $("sourceSpecify")?.addEventListener("input", onAuthorityPickChange);

  $("effectPick")?.addEventListener("change", onEffectPickChange);
  $("effectDescribe")?.addEventListener("input", onEffectPickChange);

  $("remedyPick")?.addEventListener("change", onRemedyPickChange);
  $("remedyDescribe")?.addEventListener("input", onRemedyPickChange);

  // chain buttons
  $("btnMakeChain")?.addEventListener("click", makeChainLine);
  $("btnCopyChain")?.addEventListener("click", () => copyText($("chainLine")?.textContent || ""));

  // wizard
  $("btnWizYes")?.addEventListener("click", () => wizardAnswer(true));
  $("btnWizNo")?.addEventListener("click", () => wizardAnswer(false));
  $("btnWizBack")?.addEventListener("click", wizardBack);
  $("btnWizReset")?.addEventListener("click", wizardReset);

  // tagging
  $("primaryTag")?.addEventListener("change", refreshAllGates);
  $("secondaryTags")?.addEventListener("change", refreshAllGates);
  $("tagLocation")?.addEventListener("change", refreshAllGates);

  $("btnMakeDiagnosis")?.addEventListener("click", makeDiagnosis);
  $("btnCopyDiagnosis")?.addEventListener("click", () => copyText($("diagnosticStatement")?.value || ""));

  // research + IRAC
  $("btnMakeResearch")?.addEventListener("click", makeResearchPlan);
  $("btnCopyResearch")?.addEventListener("click", () => copyText($("researchPlan")?.textContent || ""));

  $("btnMakeIRAC")?.addEventListener("click", makeIRACDraft);
  $("btnCopyIRAC")?.addEventListener("click", () => copyText($("iracDraft")?.textContent || ""));
}

/* ---------------------------
   Populate selects
--------------------------- */
function populateStaticSelects() {
  // primary + secondary contradiction lists
  const primary = $("primaryTag");
  const secondary = $("secondaryTags");
  if (primary) primary.innerHTML = "";
  if (secondary) secondary.innerHTML = "";

  contradictionList().forEach(c => {
    primary?.appendChild(new Option(`Type ${c.id}: ${c.name}`, c.name));
    secondary?.appendChild(new Option(`Type ${c.id}: ${c.name}`, c.name));
  });

  populateGuidedPicklists();
}

function populateGuidedPicklists() {
  // source type
  const st = $("sourceType");
  if (st) {
    st.innerHTML = "";
    sourceTypeOptions(state.domain).forEach(o => st.appendChild(new Option(o.t, o.v)));
  }

  // effect
  const ep = $("effectPick");
  if (ep) {
    ep.innerHTML = "";
    effectOptions(state.domain).forEach(o => ep.appendChild(new Option(o.t, o.v)));
  }

  // remedy
  const rp = $("remedyPick");
  if (rp) {
    rp.innerHTML = "";
    remedyOptions(state.domain).forEach(o => rp.appendChild(new Option(o.t, o.v)));
  }
}

/* ---------------------------
   Guided fields: authority/effect/remedy
--------------------------- */
function onAuthorityPickChange() {
  const type = $("sourceType")?.value || "";
  const spec = $("sourceSpecify")?.value?.trim() || "";
  const out = $("chainSource");
  if (!out) return;

  const typeLabel = authorityTypeLabel(type);
  const text = spec ? `${typeLabel}: ${spec}` : (typeLabel ? `${typeLabel}:` : "");
  out.value = text;

  refreshAllGates();
}

function authorityTypeLabel(type) {
  switch (type) {
    case "constitution": return "Constitution";
    case "statute": return "Statute";
    case "regulation": return "Regulation";
    case "case": return "Case law";
    case "local": return "Local ordinance / policy";
    case "contract": return "Contract";
    case "professional": return "Professional rule";
    default: return "";
  }
}

function onEffectPickChange() {
  const pick = $("effectPick")?.value || "";
  const desc = $("effectDescribe")?.value?.trim() || "";
  const out = $("chainEffect");
  if (!out) return;

  const base = effectOptions(state.domain).find(o => o.v === pick)?.t || "";
  out.value = desc ? `${base}: ${desc}` : base;

  refreshAllGates();
}

function onRemedyPickChange() {
  const pick = $("remedyPick")?.value || "";
  const desc = $("remedyDescribe")?.value?.trim() || "";
  const out = $("chainRemedy");
  if (!out) return;

  const base = remedyOptions(state.domain).find(o => o.v === pick)?.t || "";
  out.value = desc ? `${base}: ${desc}` : base;

  refreshAllGates();
}

/* ---------------------------
   Validations and gates
--------------------------- */
function refreshAllGates() {
  // domain gate
  setGate(
    "domainGate",
    !!state.domain && state.domain !== "",
    "Select a domain to unlock the workflow."
  );

  // one-sentence gate (soft)
  const issueOk = ($("oneSentence")?.value || "").trim().length > 0;
  setGate("issueGate", issueOk, "Add a one-sentence problem to anchor the analysis.");

  // source authority strict
  const sourceOk = validateSourceAuthority();
  setGate("sourceGate", sourceOk.ok, sourceOk.msg);

  // effect strict
  const effectOk = validateEffect();
  setGate("effectGate", effectOk.ok, effectOk.msg);

  // remedy strict
  const remedyOk = validateRemedy();
  setGate("remedyGate", remedyOk.ok, remedyOk.msg);

  // global chain gate
  const chainOk = chainComplete() && sourceOk.ok && effectOk.ok && remedyOk.ok;
  setGate("chainGlobalGate", chainOk, "Complete the Minimum Legal Chain (1–8) and required validations.");

  // unlock chain line button
  $("btnMakeChain").disabled = !(chainOk && state.domain);

  // chain copy gate
  const hasChainLine = ($("chainLine")?.textContent || "").trim().length > 0;
  $("btnCopyChain").disabled = !hasChainLine;

  // wizard gate
  const wizardUnlocked = chainOk && !!state.domain;
  toggleWizard(wizardUnlocked);

  // diagnosis gate
  const primary = ($("primaryTag")?.value || "").trim();
  const loc = ($("tagLocation")?.value || "").trim();
  const tagsOk = !!primary && !!loc;

  $("btnMakeDiagnosis").disabled = !tagsOk;

  // research and IRAC gates will be enabled by making diagnosis and research, but keep safe fallback
  const hasDiagnosis = ($("diagnosticStatement")?.value || "").trim().length > 0;
  $("btnMakeResearch").disabled = !hasDiagnosis;
  $("btnCopyDiagnosis").disabled = !hasDiagnosis;

  const hasResearch = ($("researchPlan")?.textContent || "").trim().length > 0;
  $("btnCopyResearch").disabled = !hasResearch;
  $("btnMakeIRAC").disabled = !hasResearch;

  const hasIRAC = ($("iracDraft")?.textContent || "").trim().length > 0;
  $("btnCopyIRAC").disabled = !hasIRAC;

  // tag gate helper
  setGate("tagGate", tagsOk, "Select a primary contradiction type and chain link location.");
  updateMLCVisual();

}

function setGate(id, ok, failMsg) {
  const el = $(id);
  if (!el) return;
  if (ok) {
    el.classList.remove("gate-warn");
    el.textContent = "";
  } else {
    el.classList.add("gate-warn");
    el.textContent = failMsg || "";
  }
}

function validateSourceAuthority() {
  const text = ($(CHAIN_IDS[1])?.value || "").trim();
  if (!text) return { ok: false, msg: `${SOOL_TERMS.MLC[1]} is required.` };

  // block generic
  const tooGeneric = ["statute", "constitution", "regulation", "case law", "policy"]
    .some(g => text.toLowerCase() === g);
  if (tooGeneric) return { ok: false, msg: "Make the source specific (include jurisdiction and section/clause if possible)." };

  return { ok: true, msg: "" };
}

function validateEffect() {
  const pick = ($("effectPick")?.value || "").trim();
  const text = ($(CHAIN_IDS[7])?.value || "").trim();
  if (!pick) return { ok: false, msg: `${SOOL_TERMS.MLC[7]} category is required.` };
  if (!text) return { ok: false, msg: `${SOOL_TERMS.MLC[7]} is required.` };
  return { ok: true, msg: "" };
}

function validateRemedy() {
  const pick = ($("remedyPick")?.value || "").trim();
  const text = ($(CHAIN_IDS[8])?.value || "").trim();
  if (!pick) return { ok: false, msg: `${SOOL_TERMS.MLC[8]} type is required.` };
  if (!text) return { ok: false, msg: `${SOOL_TERMS.MLC[8]} is required.` };
  return { ok: true, msg: "" };
}

function chainComplete() {
  // positions 2–6 can be blank in early drafting, but for unlock require all 1–8
  for (let i = 1; i <= 8; i++) {
    const v = ($(CHAIN_IDS[i])?.value || "").trim();
    if (!v) return false;
  }
  return true;
}

/* ---------------------------
   Wizard UI control
--------------------------- */
function toggleWizard(on) {
  const gate = $("wizardGate");
  const wiz = $("wizard");
  if (!wiz || !gate) return;

  if (!on) {
    gate.textContent = "Complete Step 3 validations to unlock the wizard.";
    wiz.classList.add("disabled");
    return;
  }

  gate.textContent = "";
  wiz.classList.remove("disabled");

  // initialize view if never started
  if (!state.wizard.answers.length) {
    wizardReset();
  }
}

/* ---------------------------
   Wizard mechanics
--------------------------- */
function wizardReset() {
  state.wizard.idx = 0;
  state.wizard.answers = [];
  initScores();
  updateWizardView();
  refreshRankingToSelects();
}

function wizardBack() {
  if (state.wizard.idx <= 0) return;
  state.wizard.idx--;
  // do not rewind scoring, keep it simple and deterministic by recomputing
  recomputeScoresFromAnswers();
  updateWizardView();
  refreshRankingToSelects();
}

function wizardAnswer(yes) {
  state.wizard.answers[state.wizard.idx] = !!yes;
  state.wizard.idx++;

  recomputeScoresFromAnswers();
  updateWizardView();
  refreshRankingToSelects();

  // when finished, enable diagnosis button if selections exist
  refreshAllGates();
  applyWizardContradictionToMLC();

}

function recomputeScoresFromAnswers() {
  initScores();
  for (let i = 0; i < state.wizard.answers.length; i++) {
    const ansYes = state.wizard.answers[i];
    const item = WIZARD[i];
    if (!item) continue;
    if (!ansYes) continue;

    const weights = item.yes || {};
    Object.entries(weights).forEach(([name, w]) => {
      state.wizard.scores.set(name, (state.wizard.scores.get(name) || 0) + w);
    });
  }

  // If multiple yes answers, bump compound
  const yesCount = state.wizard.answers.filter(Boolean).length;
  if (yesCount >= 3) {
    bumpScore(SOOL_TERMS.CONTRADICTIONS.COMPOUND_CONTRADICTION.name, 2);
  }
}

function bumpScore(name, w) {
  state.wizard.scores.set(name, (state.wizard.scores.get(name) || 0) + w);
}

function updateWizardView() {
  const idx = Math.min(state.wizard.idx, WIZARD.length - 1);
  const done = state.wizard.idx >= WIZARD.length;

  $("wizCount").textContent = `${Math.min(state.wizard.idx + 1, WIZARD.length)}/${WIZARD.length}`;
  $("btnWizBack").disabled = state.wizard.idx <= 0;

  if (done) {
    $("wizStepLabel").textContent = "Finished";
    $("wizQuestion").textContent = "Wizard complete. Review suggested contradiction types below.";
    $("wizHelp").textContent = "";
    return;
  }

  const item = WIZARD[state.wizard.idx];
  $("wizStepLabel").textContent = "Question";
  $("wizQuestion").textContent = item.q;
  $("wizHelp").textContent = item.help || "";
}

function refreshRankingToSelects() {
  const ranked = contradictionList()
    .map(c => ({ ...c, score: state.wizard.scores.get(c.name) || 0 }))
    .sort((a, b) => b.score - a.score || a.id - b.id);

  // repop primary + secondary in ranked order
  const primary = $("primaryTag");
  const secondary = $("secondaryTags");
  if (!primary || !secondary) return;

  const currentPrimary = primary.value || "";
  const currentSecondary = new Set(Array.from(secondary.selectedOptions).map(o => o.value));

  primary.innerHTML = "";
  secondary.innerHTML = "";

  ranked.forEach(c => {
    primary.appendChild(new Option(`Type ${c.id}: ${c.name}${c.score ? ` (score ${c.score})` : ""}`, c.name));
    secondary.appendChild(new Option(`Type ${c.id}: ${c.name}${c.score ? ` (score ${c.score})` : ""}`, c.name));
    
  });
applyWizardContradictionToMLC();
  // try restore selection
  if (currentPrimary) primary.value = currentPrimary;
  Array.from(secondary.options).forEach(opt => {
    if (currentSecondary.has(opt.value)) opt.selected = true;
  });
}

/* ---------------------------
   Chain line
--------------------------- */
function makeChainLine() {
  if (!chainComplete()) return;

  const parts = [];
  for (let i = 1; i <= 8; i++) {
    const label = SOOL_TERMS.MLC[i];
    const val = ($(CHAIN_IDS[i])?.value || "").trim();
    parts.push(`${i}) ${label}: ${val}`);
  }

  $("chainLine").textContent =
    `${SOOL_TERMS.MLC[1]} → ${SOOL_TERMS.MLC[2]} → ${SOOL_TERMS.MLC[3]} → ${SOOL_TERMS.MLC[4]}\n` +
    `${SOOL_TERMS.MLC[4]} → ${SOOL_TERMS.MLC[5]} → ${SOOL_TERMS.MLC[6]} → ${SOOL_TERMS.MLC[7]}\n` +
    `${SOOL_TERMS.MLC[7]} → ${SOOL_TERMS.MLC[8]}\n\n` +
    parts.join("\n");

  refreshAllGates();
}

/* ---------------------------
   Diagnosis
--------------------------- */
function selectedPrimaryContradiction() {
  const name = ($("primaryTag")?.value || "").trim();
  return contradictionList().find(c => c.name === name);
}

function selectedSecondaryContradictions() {
  const sec = $("secondaryTags");
  if (!sec) return [];
  return Array.from(sec.selectedOptions).map(o => o.value);
}

function makeDiagnosis() {
  const c = selectedPrimaryContradiction();
  const loc = ($("tagLocation")?.value || "").trim();
  if (!c || !loc) return;

  const secondary = selectedSecondaryContradictions();
  const secLine = secondary.length ? `Secondary tags: ${secondary.join(", ")}\n` : "";

  const statement =
    `Primary contradiction: ${c.name}\n` +
    `${secLine}` +
    `Location in chain: ${loc}\n` +
    `Square: ${c.square}\n\n` +
    diagnosisNarrative(c);

  $("diagnosticStatement").value = statement;
  refreshAllGates();
  applyWizardContradictionToMLC();

}

function diagnosisNarrative(c) {
  // canonical, poem-consistent phrasing
  const base =
    `Under the Minimum Legal Chain, the failure aligns with ${c.name}. ` +
    `This corresponds to Link ${c.link} on the Square of Legal Contradiction.`;

  // add chain-specific anchors
  switch (c.name) {
    case SOOL_TERMS.CONTRADICTIONS.CONFERRAL_FAILURE.name:
      return `${base}\nThe Source of authority does not successfully confer the Actor in role needed for the legal action.`;
    case SOOL_TERMS.CONTRADICTIONS.JURISDICTIONAL_CONTRADICTION.name:
      return `${base}\nThe Norm is being applied beyond its jurisdiction or scope to the Target.`;
    case SOOL_TERMS.CONTRADICTIONS.ROLE_CONTRADICTION.name:
      return `${base}\nThe Actor in role is not properly conferred or the asserted Legal effect presumes a role the system does not grant.`;
    case SOOL_TERMS.CONTRADICTIONS.PROCEDURAL_CONTRADICTION.name:
      return `${base}\nThe Legal action / omission does not satisfy the procedural requirements of the Norm.`;
    case SOOL_TERMS.CONTRADICTIONS.TEMPORAL_CONTRADICTION.name:
      return `${base}\nThe Triggering facts and the time of application of the Norm do not align.`;
    case SOOL_TERMS.CONTRADICTIONS.RECOGNITION_FAILURE.name:
      return `${base}\nThe system fails to recognize the Target or the Legal effect as legally actionable.`;
    case SOOL_TERMS.CONTRADICTIONS.CORRELATIVITY_CONTRADICTION.name:
      return `${base}\nA right/duty correlativity mismatch appears inside the Legal effect.`;
    default:
      return base;
  }
}

/* ---------------------------
   Research plan + overlay
--------------------------- */
function makeResearchPlan() {
  const c = selectedPrimaryContradiction();
  if (!c) return;

  const loc = ($("tagLocation")?.value || "").trim() || `Link ${c.link}`;
  const plan = buildResearchPlan(state.domain, c.name, loc);
  $("researchPlan").textContent = plan.text;

  $("overlayMap").innerHTML = renderOverlay(plan.overlay);

  refreshAllGates();
}

function buildResearchPlan(domain, contradictionName, loc) {
  const overlay = overlayMap(domain);
  const topics = overlay[contradictionName] || overlay["_default"];

  const chainReview = [];
  for (let i = 1; i <= 8; i++) {
    chainReview.push(`${i}. ${SOOL_TERMS.MLC[i]}: ${($(CHAIN_IDS[i])?.value || "").trim()}`);
  }

  const text =
    `Domain: ${domain || "unsure"}\n` +
    `Primary contradiction: ${contradictionName}\n` +
    `Location: ${loc}\n\n` +
    `Typed research outline:\n` +
    topics.map(t => `- ${t}`).join("\n") +
    `\n\nMinimum Legal Chain review:\n` +
    chainReview.join("\n") +
    `\n\nChain-link checks (explicit):\n` +
    explicitLinkChecks(contradictionName).map(x => `- ${x}`).join("\n");

  return { text, overlay };
}

function explicitLinkChecks(name) {
  // This is the explicit Link tagging logic you requested, rendered as steps
  const C = SOOL_TERMS.CONTRADICTIONS;
  if (name === C.CONFERRAL_FAILURE.name) return ["Check Link 1→3: Source of authority must confer Actor in role."];
  if (name === C.JURISDICTIONAL_CONTRADICTION.name) return ["Check Link 2↔6: Norm scope must cover Target."];
  if (name === C.ROLE_CONTRADICTION.name) return ["Check Link 3 or 7: Actor in role must be real; Legal effect must not presume an unheld role."];
  if (name === C.PROCEDURAL_CONTRADICTION.name) return ["Check Link 2→5: Legal action / omission must satisfy Norm procedure."];
  if (name === C.TEMPORAL_CONTRADICTION.name) return ["Check Link 2↔4: Norm timing must align with Triggering facts."];
  if (name === C.RECOGNITION_FAILURE.name) return ["Check Link 6/7: Target and Legal effect must be recognized as legally actionable."];
  if (name === C.CORRELATIVITY_CONTRADICTION.name) return ["Check Link 7: Rights/duties must correlate within Legal effect."];
  if ([C.REPAIR_FAILURE.name, C.RECOGNITION_REPAIR_FAILURE.name, C.PROCEDURAL_REPAIR_FAILURE.name, C.JURISDICTIONAL_REPAIR_FAILURE.name].includes(name)) {
    return ["Check Link 8: Remedy must exist and be legally and procedurally available within jurisdiction."];
  }
  return ["If multiple breaks are present, treat as Compound contradiction and check all relevant links."];
}

function overlayMap(domain) {
  // Typed outline overlays by domain and contradiction type
  // Kept concise but complete enough for guided research
  const common = {
    "_default": [
      "Confirm Source of authority (jurisdiction and section/clause).",
      "Extract the Norm elements and definitions.",
      "Identify Actor in role and how role is conferred.",
      "List Triggering facts (known, unknown, disputed).",
      "Classify Legal action / omission.",
      "Define Target and any legally relevant status.",
      "State Legal effect in rights, duties, status, exposure terms.",
      "Inventory Remedy pathways (court, agency, internal, timing)."
    ]
  };

  const byType = {
    [SOOL_TERMS.CONTRADICTIONS.CONFERRAL_FAILURE.name]: [
      "Trace Source of authority to the conferral of the relevant role or power.",
      "Identify the conferring instrument (statute, appointment, delegation).",
      "Check limits on delegated power and required prerequisites.",
      "Collect cases on ultra vires actions and authority defects."
    ],
    [SOOL_TERMS.CONTRADICTIONS.JURISDICTIONAL_CONTRADICTION.name]: [
      "Define jurisdiction and scope limits for the Norm.",
      "Confirm Target is within the scope (subject, territory, time, status).",
      "Check preemption or supremacy conflicts if cross-level.",
      "Collect cases on subject-matter and personal jurisdiction or statutory scope."
    ],
    [SOOL_TERMS.CONTRADICTIONS.ROLE_CONTRADICTION.name]: [
      "Identify required role for the action and how it is conferred.",
      "Test whether Actor in role is valid at the time of action.",
      "Check conflicts of interest or disqualification rules where relevant.",
      "Collect cases on improper actors, void acts, and role invalidation."
    ],
    [SOOL_TERMS.CONTRADICTIONS.PROCEDURAL_CONTRADICTION.name]: [
      "List required procedural steps in the Norm (notice, hearing, warrant, filing).",
      "Check which step was skipped and what consequence follows.",
      "Collect cases on procedural due process or statutory procedure defects.",
      "Identify preservation requirements and deadlines."
    ],
    [SOOL_TERMS.CONTRADICTIONS.TEMPORAL_CONTRADICTION.name]: [
      "Check timing conditions (effective dates, retroactivity, limitations).",
      "Confirm Triggering facts occurred within the legally relevant window.",
      "Collect cases on retroactivity and limitations periods.",
      "Identify tolling, relation-back, and emergency exceptions."
    ],
    [SOOL_TERMS.CONTRADICTIONS.RECOGNITION_FAILURE.name]: [
      "Identify recognition conditions for Target and Legal effect (standing, status, eligibility).",
      "Check whether the system recognizes the claim type at all.",
      "Collect cases on standing, immunity, justiciability, or non-recognition doctrines.",
      "Identify evidentiary or proof burdens that function as recognition gates."
    ],
    [SOOL_TERMS.CONTRADICTIONS.CORRELATIVITY_CONTRADICTION.name]: [
      "Translate Legal effect into explicit right-duty or power-liability pairs.",
      "Check whether a claimed right has an identifiable duty-bearer.",
      "Collect doctrine on correlativity and remedies tied to recognized duties.",
      "Test for conflicting duties imposed by multiple norms."
    ],
    [SOOL_TERMS.CONTRADICTIONS.REPAIR_FAILURE.name]: [
      "List all Remedy pathways and confirm none exist or are accessible.",
      "Check immunity, political question, non-reviewability, or statutory bars.",
      "Collect cases on remedial gaps and jurisdictional or procedural limits.",
      "Consider whether only non-legal remedies remain (still record legally)."
    ],
    [SOOL_TERMS.CONTRADICTIONS.RECOGNITION_REPAIR_FAILURE.name]: [
      "Determine whether the legal system recognizes the remedy claimant or harm.",
      "Check standing/eligibility barriers to remedial access.",
      "Collect cases where remedy is denied due to status or recognition defects."
    ],
    [SOOL_TERMS.CONTRADICTIONS.PROCEDURAL_REPAIR_FAILURE.name]: [
      "Map the procedural steps required to obtain the remedy.",
      "Identify deadlines, exhaustion, preservation, and filing requirements.",
      "Collect cases on procedural bars to remedy."
    ],
    [SOOL_TERMS.CONTRADICTIONS.JURISDICTIONAL_REPAIR_FAILURE.name]: [
      "Identify which institution could grant the remedy and whether it has power.",
      "Check venue, subject-matter jurisdiction, sovereign immunity, and preclusion.",
      "Collect cases where courts decline power to grant the remedy."
    ],
    [SOOL_TERMS.CONTRADICTIONS.COMPOUND_CONTRADICTION.name]: [
      "Identify all chain breaks and select a primary for analysis order.",
      "Run link checks for each involved contradiction type.",
      "Collect authorities for each failure class and then test interactions."
    ],
    [SOOL_TERMS.CONTRADICTIONS.INSTITUTIONALIZED_CONTRADICTION.name]: [
      "Identify repeated or normalized contradiction patterns.",
      "Collect institutional policies, reports, and recurring case law references.",
      "Assess remedy gaps and structural persistence over time."
    ]
  };

  // domain adds a small prefix section
  const domainPrefix = {
    criminal: [
      "Start with statute elements, mens rea, defenses, and jurisdiction.",
      "Check charging authority, discretion, and procedural protections."
    ],
    civil: [
      "Start with cause of action elements and burdens of proof.",
      "Check remedies in damages, injunctions, and defenses."
    ],
    constitutional: [
      "Start with state action, standard of review, and doctrine tests.",
      "Check remedies (injunction, declaratory relief, suppression)."
    ],
    administrative: [
      "Start with enabling act authority and agency procedure.",
      "Check exhaustion, deference doctrines, and reviewability."
    ],
    ethics: [
      "Start with professional rule source and interpretive materials.",
      "Check jurisdiction of discipline bodies and procedural protections."
    ],
    unsure: [
      "Identify whether the Source of authority is constitutional, statutory, or regulatory.",
      "Use the contradiction type to choose the doctrinal entry point."
    ]
  };

  // merge
  const out = { ...common };
  Object.keys(byType).forEach(k => {
    const prefix = domainPrefix[domain] || domainPrefix.unsure;
    out[k] = [...prefix, ...byType[k], ...common._default];
  });
  return out;
}

function renderOverlay(overlay) {
  // simple readable HTML, no tables required
  const entries = Object.entries(overlay)
    .filter(([k]) => k !== "_default");

  return entries.map(([k, arr]) => {
    const title = escapeHtml(k);
    const items = arr.map(x => `<li>${escapeHtml(x)}</li>`).join("");
    return `<div class="card" style="margin:0 0 12px 0;"><h4 style="margin:0 0 8px 0;">${title}</h4><ul>${items}</ul></div>`;
  }).join("");
}

/* ---------------------------
   IRAC+ draft
--------------------------- */
function makeIRACDraft() {
  const c = selectedPrimaryContradiction();
  if (!c) return;

  const issue = ($("oneSentence")?.value || "").trim() || "[state issue]";
  const rule = ($(CHAIN_IDS[2])?.value || "").trim();
  const app = iracApplicationLine(c);
  const concl = `Conclusion: The structure exhibits ${c.name} at Link ${c.link} on the Square. Remedy analysis occurs at ${SOOL_TERMS.MLC[8]}.`;

  const text = [
    "Issue:",
    issue,
    "",
    "Rule:",
    rule || "[state the governing norm]",
    "",
    "Application:",
    app,
    "",
    concl
  ].join("\n");

  $("iracDraft").textContent = text;
  refreshAllGates();
}

function iracApplicationLine(c) {
  const a = ($(CHAIN_IDS[1])?.value || "").trim();
  const ar = ($(CHAIN_IDS[3])?.value || "").trim();
  const f = ($(CHAIN_IDS[4])?.value || "").trim();
  const act = ($(CHAIN_IDS[5])?.value || "").trim();
  const t = ($(CHAIN_IDS[6])?.value || "").trim();
  const e = ($(CHAIN_IDS[7])?.value || "").trim();
  const r = ($(CHAIN_IDS[8])?.value || "").trim();

  return (
    `From ${SOOL_TERMS.MLC[1]} (${a}), the ${SOOL_TERMS.MLC[2]} is applied by the ${SOOL_TERMS.MLC[3]} (${ar}). ` +
    `Given ${SOOL_TERMS.MLC[4]} (${f}) and ${SOOL_TERMS.MLC[5]} (${act}) directed at the ${SOOL_TERMS.MLC[6]} (${t}), ` +
    `the asserted ${SOOL_TERMS.MLC[7]} is (${e}). ` +
    `The structure indicates ${c.name} at Link ${c.link}. ` +
    `The remedy pathway considered is (${r}).`
  );
}

/* ---------------------------
   Examples
--------------------------- */
function loadUniversitySample() {
  clearAll();

  // set domain
  setDomain("constitutional");

  $("oneSentence").value =
    "A public university requires prior approval for certain classroom topics, raising whether the restriction violates the First Amendment.";

  $("anchorsActors").value = "Public university; professor; department chair; administration.";
  $("anchorsRoles").value = "State actor; instructor; administrator.";
  $("anchorsNorms").value = "U.S. Constitution, First Amendment; content-based restriction doctrine; strict scrutiny.";
  $("anchorsEvent").value = "Policy requires prior approval before discussing specified topics in class.";

  $("sourceType").value = "constitution";
  $("sourceSpecify").value = "U.S. Constitution, First Amendment";
  onAuthorityPickChange();

  $(CHAIN_IDS[2]).value =
    "Content-based restrictions on protected speech by state actors are presumptively unconstitutional unless they satisfy strict scrutiny.";
  $(CHAIN_IDS[3]).value = "Public university acting as state actor; administrator enforcing policy.";
  $(CHAIN_IDS[4]).value = "Policy requires prior approval; professor intends to cover affected topics; approval denied or chilled.";
  $(CHAIN_IDS[5]).value = "Restriction imposed by enforcing the prior-approval requirement.";
  $(CHAIN_IDS[6]).value = "Professor (and students as audience).";

  $("effectPick").value = "restriction";
  $("effectDescribe").value = "Restriction of protected speech in classroom instruction.";
  onEffectPickChange();

  $("remedyPick").value = "injunction";
  $("remedyDescribe").value = "Declaratory and injunctive relief to prevent enforcement of the policy.";
  onRemedyPickChange();

  refreshAllGates();
}

function loadCriminalSample() {
  clearAll();

  setDomain("criminal");

  $("oneSentence").value =
    "An attorney emails a private person demanding money and threatening to report alleged criminal conduct unless payment is made, raising whether this constitutes extortion or coercion.";

  $("anchorsActors").value = "Attorney; target private individual; law enforcement (potential).";
  $("anchorsRoles").value = "Threat-maker; private person; potential state prosecutor.";
  $("anchorsNorms").value = "State penal code extortion/coercion statute; threat definition; defenses.";
  $("anchorsEvent").value = "Email demand for payment with threat to report alleged crime; entitlement disputed.";

  $("sourceType").value = "statute";
  $("sourceSpecify").value = "State penal code provision defining extortion/coercion (insert jurisdiction and section).";
  onAuthorityPickChange();

  $(CHAIN_IDS[2]).value =
    "Obtaining property/benefit by threat where there is no lawful entitlement is prohibited; threat definition and defenses vary by jurisdiction.";
  $(CHAIN_IDS[3]).value = "Attorney as threat-maker; target as private person.";
  $(CHAIN_IDS[4]).value = "Email demands money; threatens criminal accusation/reporting; demand may exceed lawful entitlement.";
  $(CHAIN_IDS[5]).value = "Threat communicated by email to obtain payment.";
  $(CHAIN_IDS[6]).value = "Private person (target of threat).";

  $("effectPick").value = "liability";
  $("effectDescribe").value = "Exposure to criminal liability for extortion/coercion (attempted).";
  onEffectPickChange();

  $("remedyPick").value = "criminal_process";
  $("remedyDescribe").value = "Report to law enforcement; investigation and prosecution decision; potential protective orders.";
  onRemedyPickChange();

  refreshAllGates();
}

function setDomain(val) {
  state.domain = val;
  const r = document.querySelector(`input[name="domain"][value="${val}"]`);
  if (r) r.checked = true;
  populateGuidedPicklists();
}

/* ---------------------------
   Export / Clear / Copy
--------------------------- */
function exportJSON() {
  const payload = {
    domain: state.domain || "",
    oneSentence: ($("oneSentence")?.value || "").trim(),
    anchors: {
      actors: ($("anchorsActors")?.value || "").trim(),
      roles: ($("anchorsRoles")?.value || "").trim(),
      norms: ($("anchorsNorms")?.value || "").trim(),
      event: ($("anchorsEvent")?.value || "").trim()
    },
    chain: {},
    diagnosis: {
      primary: ($("primaryTag")?.value || "").trim(),
      secondary: selectedSecondaryContradictions(),
      location: ($("tagLocation")?.value || "").trim(),
      statement: ($("diagnosticStatement")?.value || "").trim()
    },
    researchPlan: ($("researchPlan")?.textContent || "").trim(),
    iracDraft: ($("iracDraft")?.textContent || "").trim()
  };

  for (let i = 1; i <= 8; i++) {
    payload.chain[i] = {
      label: SOOL_TERMS.MLC[i],
      value: ($(CHAIN_IDS[i])?.value || "").trim()
    };
  }

  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "sool-irac.json";
  a.click();
}

function clearAll() {
  $("oneSentence").value = "";
  $("anchorsActors").value = "";
  $("anchorsRoles").value = "";
  $("anchorsNorms").value = "";
  $("anchorsEvent").value = "";

  $("sourceType").value = "";
  $("sourceSpecify").value = "";
  $(CHAIN_IDS[1]).value = "";

  for (let i = 2; i <= 6; i++) $(CHAIN_IDS[i]).value = "";

  $("effectPick").value = "";
  $("effectDescribe").value = "";
  $(CHAIN_IDS[7]).value = "";

  $("remedyPick").value = "";
  $("remedyDescribe").value = "";
  $(CHAIN_IDS[8]).value = "";

  $("chainLine").textContent = "";
  $("diagnosticStatement").value = "";
  $("researchPlan").textContent = "";
  $("iracDraft").textContent = "";

  $("tagLocation").value = "";
  wizardReset();

  // do not clear domain selection, but do re-gate
  refreshAllGates();
}

async function copyText(text) {
  const t = (text || "").trim();
  if (!t) return;
  try {
    await navigator.clipboard.writeText(t);
  } catch {
    // fallback
    const ta = document.createElement("textarea");
    ta.value = t;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}
function updateMLCVisual(){
  const svg = document.querySelector("#mlcHost svg");
  if (!svg) return;

  const node = (id) => svg.getElementById("r-" + id);
  const badge = (id) => svg.getElementById("b-" + id);
  const link = (id) => svg.getElementById(id);

  const setNode = (id, cls) => {
    const el = node(id);
    if (el) el.setAttribute("class", `node ${cls}`);
  };

  const showBadge = (id, code, kind) => {
    const g = badge(id);
    if (!g) return;
    g.setAttribute("visibility", "visible");
    g.querySelector("text").textContent = code;
  };

  const hideBadge = (id) => {
    const g = badge(id);
    if (g) g.setAttribute("visibility", "hidden");
  };

  // Default all nodes to ok
  ["authority","conferral","role","obligation","correlativity","remedy"].forEach(id=>{
    setNode(id,"st-ok");
    hideBadge(id);
  });

  // === Apply real logic from your validators ===

  const source = validateSourceAuthority();
  const effect = validateEffect();
  const remedy = validateRemedy();

  if (!source.ok){
    setNode("authority","st-bad");
    showBadge("authority","C1","bad");
  }

  if (!effect.ok){
    setNode("obligation","st-warn");
    showBadge("obligation","C7","warn");
  }

  if (!remedy.ok){
    setNode("remedy","st-bad");
    showBadge("remedy","C8","bad");
  }

  // Downstream disable
  if (!source.ok){
    ["conferral","role","obligation","correlativity","remedy"]
      .forEach(id=>setNode(id,"st-off"));
  }
}

function applyWizardContradictionToMLC(){
  // Wizard coherence layer overrides completeness visuals
  const svg = document.querySelector("#mlcHost svg");
  if (!svg) return;

  const primary = ($("primaryTag")?.value || "").trim();
  if (!primary) return;

  const c = contradictionList().find(x => x.name === primary);
  if (!c) return;

  // mark global as contradictory
  const dot = svg.getElementById("mlcGlobalDot");
  const text = svg.getElementById("mlcGlobalText");
  if (dot) dot.setAttribute("class","dot dot-contra");
  if (text) text.textContent = "Contradictory";

  // simple link-based mapping
  if (c.link === "1→3") {
    markContraNode(svg,"authority","C1");
    markContraNode(svg,"role","C1");
  }
}

function markContraNode(svg,id,code){
  const r = svg.getElementById("r-" + id);
  const b = svg.getElementById("b-" + id);
  if (r) r.setAttribute("class","node st-contra");
  if (b){
    b.setAttribute("visibility","visible");
    b.querySelector("text").textContent = code;
  }
}


function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
