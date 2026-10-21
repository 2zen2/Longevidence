// Usage (from frontend/): node scripts/validate-personalization.mjs
// Asserts slug coverage, field-path validity and schema shape for src/data/personalization.ts.
import fs from "node:fs"; import path from "node:path"; import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const ts = require("typescript");
const root = path.resolve(import.meta.dirname, "..", "..");
const src = fs.readFileSync(path.join(root, "frontend/src/data/personalization.ts"), "utf8");
const js = ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
const m = { exports: {} }; new Function("module", "exports", js)(m, m.exports);
const { PERSONAL, SUGGESTED } = m.exports;
const users = JSON.parse(fs.readFileSync(path.join(root, "frontend/src/data/mock_users.json"), "utf8")).patients;
const qs = JSON.parse(fs.readFileSync(path.join(root, "backend/data/questions.json"), "utf8"));
const questions = Array.isArray(qs) ? qs : qs.questions;
const slugs = questions.map((q) => q.slug);

const NO_MATCH = {
  "alex-morgan": { "sglt2-hf": "No heart failure, diabetes or CKD and no cardiac medication in profile; reviewer: do not introduce an SGLT2 inhibitor for longevity; eligibility depends on a real diagnosis." },
  "jamie-chen": {
    "sglt2-hf": "Profile states no known heart failure and no diabetes (HbA1c 6.0% is prediabetes range); HbA1c alone is not an indication for heart-failure treatment.",
    "nmn": "Jamie takes no NMN and has no listed interest; could appear only in a general library, clearly labelled low-evidence and not personalized.",
    "cold-lifting": "No structured strength training or cold immersion in the profile; not actionable without changing her behaviour context.",
  },
};
const SAFETY = {
  "alex-morgan": { nmn: "Low-evidence supplement: uncertain long-term safety, purity and interactions", omega3: "High-dose omega-3 products linked to atrial fibrillation; OTC fish oil not recommended for primary prevention", vitd: "Excess long-term dosing can cause high calcium / kidney stones (1,000 IU is below the usual upper limit)", "cold-lifting": "Cold shock, drowning risk (solo immersion); extra caution with CVD, arrhythmia or uncontrolled hypertension; family history alone is not a contraindication", fasting: "Caution with eating-disorder history, pregnancy, frailty or glucose-lowering drugs (none listed)", "sat-fat": "If a statin is considered: muscle symptoms, modest diabetes risk, drug interactions depend on the specific statin", sodium: "Potassium salt substitutes: hyperkalemia risk with CKD or potassium-raising medicines (no CKD listed)", "low-carb": "LDL may rise with higher saturated fat", "wb-mri": "Incidental findings / false positives / overdiagnosis" },
  "jamie-chen": { sodium: "BP 146/90 on amlodipine needs timely prescriber review; potassium salt substitutes risky with CKD or potassium-raising medicines (kidney function unknown)", dash: "BP 146/90 on amlodipine needs timely prescriber review; monitor for dizziness if BP falls; potassium only with CKD or potassium-raising drugs", vitd: "Excess dosing can cause high calcium / kidney stones; status unknown", fasting: "Dizziness or low BP if food or fluid intake falls; not a known direct amlodipine interaction", omega3: "High-dose omega-3 products linked to atrial fibrillation; OTC fish oil not recommended for primary prevention", "sat-fat": "If a statin is considered: amlodipine interacts with some statins (notably simvastatin); prescriber or pharmacist chooses agent and dose", "low-carb": "LDL may rise with higher saturated fat; clinician reviews treatment if weight or BP falls", "fruit-veg": "Concentrated potassium products only matter with CKD or potassium-raising medicines; ordinary produce is fine", "wb-mri": "Incidental findings / false positives / overdiagnosis" },
};
const SUGG_WHY = {
  "alex-morgan": { "sat-fat": "Reviewer: highest value (ESCALATE). LDL 132 mg/dL plus father's MI at 59 (relevant, not a premature-ASCVD label); PREVENT-ASCVD risk, Lp(a) once, apoB/CAC selectively.", ssb: "Reviewer: concrete and easy to act on (soda several times weekly, BMI 27.8, BP 132/84); water first, diet drink as a bridge.", "med-diet": "Reviewer: broad benefit for LDL and BP via substitution (butter/red meat/refined grains to unsaturated oils, legumes, nuts, whole grains); NMN is low priority and not top-3." },
  "jamie-chen": { sodium: "Reviewer: top priority. BP 146/90 on amlodipine is above goal; home BP protocol and timely prescriber review (not 3-6 months), plus sodium swaps for packaged sauces and salty snacks.", dash: "Reviewer: strong practical choice plus escalate; DASH is her stated BP goal and carries the same BP follow-up message.", fiber: "Chosen as the third card because it is the best existing slug linking prediabetes (HbA1c 6.0%, refined-grain swap, diabetes prevention) with LDL 148 and CV risk follow-up. Vitamin D does not outrank BP or cardiometabolic risk." },
};
const get = (o, p) => p.split(".").reduce((a, k) => (a == null ? undefined : a[k]), o);
const errs = [];
for (const u of users) {
  const P = PERSONAL[u.id]; if (!P) { errs.push(`no PERSONAL for ${u.id}`); continue; }
  for (const s of slugs) if (!P[s] && !NO_MATCH[u.id]?.[s]) errs.push(`${u.id}/${s}: neither covered nor listed no-match`);
  for (const s of Object.keys(P)) {
    if (!slugs.includes(s)) errs.push(`${u.id}/${s}: unknown slug`);
    if (NO_MATCH[u.id]?.[s]) errs.push(`${u.id}/${s}: both covered and no-match`);
    const e = P[s];
    for (const k of ["relevance", "interpretation", "nextStep"]) if (!e[k] || typeof e[k] !== "string") errs.push(`${u.id}/${s}: missing ${k}`);
    if (!Array.isArray(e.fields) || !e.fields.length) errs.push(`${u.id}/${s}: empty fields`);
    for (const f of e.fields ?? []) if (get(u, f) === undefined) errs.push(`${u.id}/${s}: field path not found: ${f}`);
    const g = e.guidance;
    if (g) {
      for (const k of ["firstLine", "benefits", "risks"]) if (!g[k]) errs.push(`${u.id}/${s}: guidance.${k} missing`);
      if (!Array.isArray(g.sources)) errs.push(`${u.id}/${s}: sources not array`);
      for (const x of g.sources ?? []) if (!/\.\s.+\.\s\d{4}\.$/.test(x)) errs.push(`${u.id}/${s}: bad source format: ${x}`);
    } else errs.push(`${u.id}/${s}: no guidance`);
    if (/\byou have\b/i.test(JSON.stringify(e))) errs.push(`${u.id}/${s}: diagnosis-style wording "you have"`);
  }
  for (const s of SUGGESTED[u.id] ?? []) if (!P[s]) errs.push(`${u.id}: suggested ${s} has no personal entry`);
  if ((SUGGESTED[u.id] ?? []).length !== 3) errs.push(`${u.id}: SUGGESTED must have 3`);
}
for (const u of users) for (const [s, e] of Object.entries(PERSONAL[u.id] ?? {})) {
  const g = e.guidance ?? {};
  const all = JSON.stringify(e);
  if (/premature/i.test(all)) errs.push(`${u.id}/${s}: contains "premature" (father's MI at 59 is not premature for a male relative)`);
  if (g.recovery && /\b(within|adjusts?|appears?|settle|take[s]? (a few )?weeks)\b/i.test(g.recovery)) errs.push(`${u.id}/${s}: recovery reads like a time-to-effect promise: ${g.recovery}`);
  if (/\b(3|three) to (6|six) months\b/i.test(g.recovery ?? "") ) errs.push(`${u.id}/${s}: recovery must not use a 3-6 month wait`);
  if (u.id === "jamie-chen" && /3[- ]to[- ]6 month|3-6 month/i.test(JSON.stringify({ n: e.nextStep, g }))) errs.push(`${u.id}/${s}: Jamie must not be told to wait 3-6 months`);
}
for (const s of ["sodium", "dash"]) if (!/prescriber|clinician/i.test(PERSONAL["jamie-chen"]?.[s]?.nextStep ?? "") || !/146\/90/.test(PERSONAL["jamie-chen"][s].nextStep)) errs.push(`jamie-chen/${s}: nextStep must carry the BP follow-up`);
const covered = users.reduce((n, u) => n + Object.keys(PERSONAL[u.id] ?? {}).length, 0);
const nm = Object.values(NO_MATCH).reduce((n, o) => n + Object.keys(o).length, 0);
console.log(`pairs: ${users.length * slugs.length}; covered ${covered}; no-match ${nm}`);
if (errs.length) { console.error("FAIL\n" + errs.join("\n")); process.exit(1); }
console.log("OK");
