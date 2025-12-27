# IRAC+  
**A structural legal reasoning engine grounded in the Structural Ontology of Law (SOoL)**

IRAC+ is not a writing template.  
It is a **structural reasoning system** that makes legal coherence, contradiction, and repair *visible*.

IRAC+ extends traditional IRAC by enforcing a **Minimum Legal Chain (MLC)**, diagnosing **typed legal contradictions**, and separating **existence conditions** from **coherence conditions** in legal analysis.

---

## Core Idea

Legal analysis fails not only when rules are wrong, but when **structure breaks**.

IRAC+ models law as a chain of dependencies:

1. Source of authority  
2. Norm  
3. Actor in role  
4. Triggering facts  
5. Legal action / omission  
6. Target  
7. Legal effect  
8. Remedy  

If any link fails, downstream legal force cannot propagate.  
If incompatible claims coexist, **contradiction debt** accumulates.

IRAC+ makes these failures explicit.

---

## What IRAC+ Does

### 1. Enforces the Minimum Legal Chain (MLC)

Users must explicitly populate all eight structural positions.  
The system blocks progress when required links are missing or invalid.

This prevents:
- phantom authority
- role assertions without conferral
- effects without correlativity
- violations without remedies

---

### 2. Separates Completeness from Coherence

IRAC+ distinguishes two stages:

- **Step 3: Structural Completeness**  
  Can the legal chain exist at all?

- **Step 4: Structural Coherence**  
  Does the chain contradict itself?

A chain can be **complete and still contradictory**.  
IRAC+ treats this as a first-class state, not an error.

---

### 3. Diagnoses Typed Legal Contradictions

The contradiction wizard is a guided yes/no diagnostic that identifies failures such as:

- Conferral failure (Link 1→3)
- Jurisdictional contradiction (Link 2↔6)
- Procedural contradiction (Link 2→5)
- Temporal contradiction (Link 2↔4)
- Recognition failure (Link 6/7)
- Correlativity contradiction (Link 7)
- Repair failures (Link 8)
- Compound and institutionalized contradictions

Each contradiction maps directly to the **Square of Legal Contradiction**.

---

### 4. Visualizes Legal Structure in Real Time

IRAC+ includes a **graphical Minimum Legal Chain status bar**:

- 🟢 Structurally sound  
- 🟡 Incomplete  
- 🔴 Invalid  
- 🟣 Contradictory  

The graphic updates dynamically:
- completion is shown after Step 3
- contradiction overlays appear after the wizard runs

This makes structural failure visible *before* prose is written.

---

### 5. Produces Three Distinct Outputs

IRAC+ generates:

1. **Structural map** (machine-readable JSON)
2. **Contradiction diagnosis** (typed, located, justified)
3. **IRAC-style prose** (Issue, Rule, Application, Conclusion)

Good writing follows good structure, not the reverse.

---

## File Overview

