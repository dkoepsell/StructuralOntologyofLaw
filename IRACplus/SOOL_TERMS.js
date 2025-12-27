/* ============================================================
   SOoL_TERMS.js
   AUTHORITATIVE LANGUAGE LAYER
   ============================================================ */

export const SOOL_TERMS = {
  SQUARE: {
    AUTHORITY: "Authority",
    EFFECT: "Effect",
    RECOGNITION: "Recognition",
    REPAIR: "Repair"
  },

  MLC: {
    1: "Source of authority",
    2: "Norm",
    3: "Actor in role",
    4: "Triggering facts",
    5: "Legal action / omission",
    6: "Target",
    7: "Legal effect",
    8: "Remedy"
  },

  MLC_ORDER: [
    "Source of authority",
    "Norm",
    "Actor in role",
    "Triggering facts",
    "Legal action / omission",
    "Target",
    "Legal effect",
    "Remedy"
  ],

  CONTRADICTIONS: {
    CONFERRAL_FAILURE: { id: 1, name: "Conferral failure", link: "1→3", square: "Authority" },
    JURISDICTIONAL_CONTRADICTION: { id: 2, name: "Jurisdictional contradiction", link: "2↔6", square: "Authority" },
    ROLE_CONTRADICTION: { id: 3, name: "Role contradiction", link: "3 or 7", square: "Authority / Recognition" },
    PROCEDURAL_CONTRADICTION: { id: 4, name: "Procedural contradiction", link: "2→5", square: "Effect" },
    TEMPORAL_CONTRADICTION: { id: 5, name: "Temporal contradiction", link: "2↔4", square: "Effect" },
    RECOGNITION_FAILURE: { id: 6, name: "Recognition failure", link: "6/7", square: "Recognition" },
    CORRELATIVITY_CONTRADICTION: { id: 7, name: "Correlativity contradiction", link: "7", square: "Recognition" },
    REPAIR_FAILURE: { id: 8, name: "Repair failure", link: "8", square: "Repair" },
    RECOGNITION_REPAIR_FAILURE: { id: 9, name: "Recognition repair failure", link: "8", square: "Repair" },
    PROCEDURAL_REPAIR_FAILURE: { id: 10, name: "Procedural repair failure", link: "8", square: "Repair" },
    JURISDICTIONAL_REPAIR_FAILURE: { id: 11, name: "Jurisdictional repair failure", link: "8", square: "Repair" },
    COMPOUND_CONTRADICTION: { id: 12, name: "Compound contradiction", link: "Multiple", square: "Multiple" },
    INSTITUTIONALIZED_CONTRADICTION: { id: 13, name: "Institutionalized contradiction", link: "Multiple", square: "Multiple" }
  }
};
