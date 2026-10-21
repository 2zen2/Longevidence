/**
 * MOCK personalization for the demo. Hand-written from the fictional profiles in mock_users.json; it is not produced by the
 * research pipeline, makes no diagnosis, and never states a study result. Topics are keyed by the question slug.
 * `relevance` is the suggestion-card blurb; `interpretation` and `fields` are background kept for review and checked by the
 * validation script (the profile fields each entry rests on). `recovery` is shown as "Follow-up":
 * monitoring / re-measure guidance only, never a time-to-effect promise. Missing data (kidney function, triglycerides,
 * smoking, 10-year risk, actual sodium intake) is stated, not inferred.
 * Slugs with no sensible patient link are intentionally omitted (see NO_MATCH in the validation script).
 */
export type Guidance = { firstLine: string; secondLine?: string; alternatives?: string; benefits: string; risks: string; recovery?: string; sources: string[] };
export type Personal = { relevance: string; interpretation: string; nextStep: string; fields: string[]; guidance?: Guidance };

/**
 * Cards shown on the search screen, in order (clinician "revised ranking": urgency and expected value, not novelty).
 * Alex: LDL / CV risk (sat-fat), soda replacement (ssb), Mediterranean/DASH substitution (med-diet). NMN is not top-3.
 * Jamie: BP follow-up (sodium, then dash carry it as the highlighted nextStep), and "fiber" as the third card because it is
 * the existing slug that links prediabetes (HbA1c 6.0%, refined-grain swap, diabetes prevention) and LDL 148 together.
 * ssb/low-carb cover prediabetes only; sat-fat covers CV risk only (still shown on her list). Vitamin D does not outrank these.
 */
export const SUGGESTED: Record<string, string[]> = {
  "alex-morgan": ["sat-fat", "ssb", "med-diet"],
  "jamie-chen": ["sodium", "dash", "fiber"],
};

// Guideline and evidence citations ("Issuer. Title. Year."), plain text only.
const HBP = "AHA/ACC multisociety. 2025 Guideline for the Prevention, Detection, Evaluation and Management of High Blood Pressure in Adults. 2025.";
const LIPID = "ACC/AHA. 2026 Guideline on the Management of Dyslipidemia. 2026.";
const DGA = "US HHS and USDA. Dietary Guidelines for Americans, 2025-2030. 2026.";
const ADA3 = "American Diabetes Association. Standards of Care in Diabetes-2026, Section 3: Prevention or Delay of Diabetes and Associated Comorbidities. 2026.";
const ADA5 = "American Diabetes Association. Standards of Care in Diabetes-2026, Section 5: Facilitating Positive Health Behaviors and Well-being. 2026.";
const ENDO = "Endocrine Society. Vitamin D for the Prevention of Disease. 2024.";
const USPSTF_D = "US Preventive Services Task Force. Vitamin D, Calcium, or Combined Supplementation for the Primary Prevention of Fractures in Community-Dwelling Adults. 2018.";
const AHA21 = "American Heart Association. Dietary Guidance to Improve Cardiovascular Health. 2021.";
const WHO_NA = "World Health Organization. Guideline: Sodium Intake for Adults and Children. 2012.";
const WHO_SUG = "World Health Organization. Guideline: Sugars Intake for Adults and Children. 2015.";
const WHO_NSS = "World Health Organization. Use of Non-Sugar Sweeteners: WHO Guideline. 2023.";
const ACR = "American College of Radiology. ACR Statement on Screening Total Body MRI. 2023.";
const AHA_O3 = "American Heart Association. Omega-3 Polyunsaturated Fatty Acid (Fish Oil) Supplementation and the Prevention of Clinical Cardiovascular Disease: A Science Advisory. 2017.";
// Descriptive titles for the two reviewer-cited papers (issuer/exact title not given in the review notes).
const COLD = "Published systematic review and meta-analysis. Cold-water immersion after resistance training and muscle adaptation. 2024.";
const IF_BMJ = "BMJ. Intermittent fasting versus continuous energy restriction: systematic review and network meta-analysis. 2025.";

// Shared wording for Jamie's treated-but-above-target BP (reviewer's suggested patient-facing wording, shortened).
const JAMIE_BP_STEP = "Your 146/90 is above goal on amlodipine. Take home readings with a validated upper-arm cuff as your care team advises, and contact your prescriber soon to review them. Do not change or stop the medicine yourself.";
const JAMIE_BP_ER = "Seek emergency care for a very high reading (about 180/120 or more) with chest pain, shortness of breath, weakness, confusion, or vision or speech changes.";
const JAMIE_BP_FOLLOW = "Home BP averages as your clinician directs; share them and your medicine routine with the prescriber.";

export const PERSONAL: Record<string, Record<string, Personal>> = {
  "alex-morgan": {
    "sat-fat": {
      relevance: "LDL 132 mg/dL, father's heart attack at 59 (above the usual under-55 cutoff for male relatives, but still relevant to risk assessment), BP 132/84 and a meat-several-times-weekly diet. Triglycerides, smoking status and 10-year risk are not recorded.",
      interpretation: "LDL is one part of cardiovascular risk. Diet is one lever; whether a medicine is appropriate depends on an overall risk estimate that cannot be made from this profile.",
      nextStep: "Ask your clinician to review your full lipid panel and estimated 10-year risk (PREVENT), and to discuss a one-time Lp(a) test.",
      fields: ["healthMetrics.ldlCholesterolMgDl", "healthMetrics.bloodPressure", "medicalHistory", "lifestyle.diet"],
      guidance: {
        firstLine: "Your LDL is one part of your cardiovascular risk. Your father's heart attack at 59 is worth reviewing with your clinician; the LDL number alone does not decide the best option.",
        secondLine: "Options may include diet change, a cholesterol-lowering medicine, or more risk assessment. Guidance supports measuring Lp(a) at least once in adulthood.",
        alternatives: "Replace saturated fat with unsaturated fat. ApoB or a coronary calcium scan are used selectively, only if the result would change a shared decision.",
        benefits: "Replacing saturated fat can lower LDL; lowering LDL in the right people reduces heart attacks and strokes.",
        risks: "Medicine benefit depends on baseline risk. Statins can cause muscle symptoms (serious muscle injury is rare) and modestly raise diabetes risk in some people; the choice and dose matter if other medicines are added later.",
        recovery: "Lipids are often rechecked 4 to 12 weeks after starting or changing a lipid-lowering medicine; response varies. Timing after diet change is set by your clinician.",
        sources: [LIPID, AHA21, DGA],
      },
    },
    ssb: {
      relevance: "Soda several times a week, BMI 27.8, BP 132/84. HbA1c 5.6% is not in the prediabetes range.",
      interpretation: "Sugary drinks add liquid calories and added sugar; replacing them is a concrete, measurable change.",
      nextStep: "Count your weekly sodas, then replace some or all with water, sparkling water or unsweetened drinks.",
      fields: ["lifestyle.sugaryDrinks", "healthMetrics.bmi", "healthMetrics.bloodPressure"],
      guidance: {
        firstLine: "Swap sugary soda for water, sparkling water or unsweetened tea or coffee. Counting servings makes progress measurable.",
        secondLine: "WHO suggests keeping free sugars below 10% of energy; this is population guidance, not a personal calorie prescription.",
        alternatives: "If it helps you drop soda, a diet drink can be a short-term bridge; water is the best default.",
        benefits: "Less added sugar and fewer liquid calories, which supports weight and overall diet quality.",
        risks: "Cravings or a caffeine-withdrawal headache if you cut caffeinated soda abruptly.",
        recovery: "Track weekly servings and recheck weight at routine visits; response varies.",
        sources: [WHO_SUG, DGA, AHA21],
      },
    },
    "med-diet": {
      relevance: "LDL 132 mg/dL, BP 132/84, a meat-heavy diet with inconsistent vegetables and whole grains, father's heart attack at 59.",
      interpretation: "A Mediterranean or DASH pattern addresses LDL, BP and diet quality together; it is a substitution strategy, not a single food.",
      nextStep: "Replace butter and frequent red or processed meat with olive oil, beans, nuts, whole grains, vegetables and fish.",
      fields: ["healthMetrics.ldlCholesterolMgDl", "healthMetrics.bloodPressure", "lifestyle.diet", "medicalHistory"],
      guidance: {
        firstLine: "Replace, rather than just add: olive or canola oil for butter, legumes and nuts for some meat, whole grains for refined grains, plus vegetables, fruit and fish if you eat it.",
        alternatives: "DASH is also reasonable, especially for blood pressure.",
        benefits: "Better overall diet quality; can lower LDL and BP and support weight and blood sugar. Healthy patterns help, not any single food.",
        risks: "Low risk. Oils and nuts add calories if added on top rather than swapped in; cost and preferences matter.",
        recovery: "Recheck weight, BP and lipids at routine visits; the size of change varies.",
        sources: [AHA21, ADA5],
      },
    },
    fasting: {
      relevance: "BMI 27.8 and weight management is a stated interest.",
      interpretation: "Time-restricted eating is one optional way to cut energy intake; it is not shown to be uniquely effective.",
      nextStep: "Note your usual eating window for a week and decide whether a modest, sustainable calorie reduction would fit you better.",
      fields: ["healthMetrics.bmi", "healthInterests"],
      guidance: {
        firstLine: "No guideline requires fasting. Intermittent fasting is an optional way to reduce calories, not a longevity strategy.",
        alternatives: "Continuous modest calorie reduction, a Mediterranean or DASH pattern, or structured support.",
        benefits: "Can help some people eat less and lose weight. Trials show no consistent large advantage over steady calorie reduction; the plan you can keep matters most.",
        risks: "Hunger, tiredness, rebound eating, poor nutrition. Take care with eating-disorder history, pregnancy, frailty or glucose-lowering medicines.",
        recovery: "Track weight trend and energy over time; response varies.",
        sources: [IF_BMJ],
      },
    },
    upf: {
      relevance: "Soda several times a week; inconsistent vegetable and whole-grain intake. Actual sodium, added-sugar and saturated-fat intake are not recorded.",
      interpretation: "Ultra-processed food intake is linked to worse outcomes, partly in observational studies; measurable targets (sodium, added sugar, saturated fat, fiber) are more useful than ingredient-list length.",
      nextStep: "Check sodium, added sugar and saturated fat on the packaged foods you buy most, and swap the highest ones.",
      fields: ["lifestyle.diet", "lifestyle.sugaryDrinks"],
      guidance: {
        firstLine: "Focus on measurable swaps: fewer sugary drinks, high-sodium sauces and snacks, and processed meats; check labels for sodium, added sugar, saturated fat and fiber.",
        alternatives: "Frozen or canned (no added salt or sugar) options are fine; cook more meals at home.",
        benefits: "Usually less sodium, added sugar and excess calories. The wider link to ultra-processed food is partly observational.",
        risks: "Cost, access and preparation time. Not all packaged foods are harmful.",
        recovery: "Re-check label numbers for your top items from time to time.",
        sources: [DGA, AHA21],
      },
    },
    "red-meat": {
      relevance: "Meat several times weekly, LDL 132 mg/dL, father's heart attack at 59.",
      interpretation: "Processed meat and the replacement food matter more than occasional servings of lean unprocessed meat.",
      nextStep: "Replace processed meat first, then swap one or two red-meat meals a week for beans, lentils, fish or poultry.",
      fields: ["lifestyle.diet", "healthMetrics.ldlCholesterolMgDl", "medicalHistory"],
      guidance: {
        firstLine: "Replace processed meat first, then some red-meat meals, with beans, lentils, nuts, tofu, fish or poultry. Lean unprocessed meat can fit a healthy pattern.",
        alternatives: "Beans, lentils, nuts, tofu, fish, poultry.",
        benefits: "May lower saturated fat and sodium, depending on what replaces it; plant proteins add fiber.",
        risks: "If you cut many animal foods, make sure you get enough B12, iron and protein.",
        recovery: "Lipids can be rechecked at routine visits; response varies.",
        sources: [AHA21, DGA],
      },
    },
    fiber: {
      relevance: "Inconsistent vegetable and whole-grain intake, LDL 132 mg/dL. HbA1c 5.6% is not prediabetes.",
      interpretation: "Soluble fiber modestly lowers LDL and supports fullness and glucose health; food-based fiber is preferred.",
      nextStep: "Replace one refined-grain serving a day with oats, barley, beans or whole grains, and build up gradually.",
      fields: ["lifestyle.diet", "healthMetrics.ldlCholesterolMgDl", "healthMetrics.hba1cPercent"],
      guidance: {
        firstLine: "Swap refined grains for oats, barley, whole grains, beans and lentils rather than only adding food; add vegetables and fruit.",
        alternatives: "Nuts, seeds, fruit and vegetables.",
        benefits: "Soluble fiber can modestly lower LDL; fiber-rich foods support fullness and blood sugar health.",
        risks: "Gas or bloating if increased quickly; drink water.",
        recovery: "Recheck lipids at routine visits; response varies.",
        sources: [AHA21, DGA],
      },
    },
    "plant-based": {
      relevance: "Meat several times weekly, inconsistent vegetables, LDL 132 mg/dL.",
      interpretation: "A partial, substitution-based shift is a realistic step; full vegan eating is not required.",
      nextStep: "Pick two regular meals to make meat-free using beans, lentils, tofu, nuts or whole grains.",
      fields: ["lifestyle.diet", "healthMetrics.ldlCholesterolMgDl"],
      guidance: {
        firstLine: "Try two recurring meat-free meals. This is a substitution, not an all-or-nothing rule.",
        alternatives: "Mediterranean or DASH patterns are equally reasonable.",
        benefits: "Swapping saturated-fat foods for legumes, nuts, soy and whole grains can lower LDL and improve diet quality.",
        risks: "Strict vegan diets need a reliable B12 source; plan iron, calcium, iodine and protein.",
        recovery: "Recheck lipids at routine visits; response varies.",
        sources: [AHA21],
      },
    },
    nuts: {
      relevance: "Cardiovascular prevention is a stated interest; LDL 132 mg/dL; weight management interest. Current nut intake is not recorded.",
      interpretation: "Benefit is greatest when nuts replace less healthy snacks, not when added on top.",
      nextStep: "Swap a modest portion of unsalted nuts for a salty or processed snack.",
      fields: ["healthInterests", "healthMetrics.ldlCholesterolMgDl"],
      guidance: {
        firstLine: "Swap a modest portion of unsalted nuts for salty or processed snacks, rather than adding them daily on top of what you eat.",
        alternatives: "Seeds or legumes.",
        benefits: "Unsaturated fat, fiber and plant protein that fit a heart-healthy pattern.",
        risks: "Energy-dense; allergy risk; salted nuts add sodium.",
        sources: [AHA21],
      },
    },
    "fruit-veg": {
      relevance: "Inconsistent vegetable intake; BP 132/84; cardiovascular prevention interest. No known chronic kidney disease in profile.",
      interpretation: "Ordinary produce does not need restriction; potassium cautions apply to specific kidney conditions or medicines, not to routine fruit and vegetables.",
      nextStep: "Add one vegetable serving to your main meal each day; frozen or no-salt-added canned is fine.",
      fields: ["lifestyle.diet", "healthMetrics.bloodPressure", "healthInterests"],
      guidance: {
        firstLine: "Add vegetables and fruit gradually; frozen or no-salt-added canned produce counts.",
        benefits: "Fiber, potassium and micronutrients with lower calorie density support BP, diet quality and weight.",
        risks: "Few. Potassium limits matter only with certain kidney conditions or potassium-raising medicines, and are different from potassium salt substitutes.",
        recovery: "Recheck BP and weight at routine visits; response varies.",
        sources: [AHA21, DGA],
      },
    },
    "low-carb": {
      relevance: "BMI 27.8, HbA1c 5.6% (not prediabetes), interest in weight and metabolic health.",
      interpretation: "A low-carb plan is one option for weight; it should not be framed as diabetes prevention for Alex based on this HbA1c.",
      nextStep: "If you prefer low-carb, plan unsaturated fats, vegetables, fiber and minimally processed protein, and recheck LDL after a major change.",
      fields: ["healthMetrics.bmi", "healthMetrics.hba1cPercent", "healthInterests"],
      guidance: {
        firstLine: "A moderate, nutrient-dense low-carb plan can be considered if you prefer it. No single eating pattern is best for everyone.",
        alternatives: "Mediterranean or DASH patterns are equally reasonable.",
        benefits: "Can improve weight and blood sugar for some people, especially in the short term.",
        risks: "LDL can rise substantially if saturated fat goes up (yours is 132 mg/dL); restrictive plans are hard to sustain.",
        recovery: "Recheck lipids after a major diet change, as your clinician advises.",
        sources: [ADA5, AHA21],
      },
    },
    sweeteners: {
      relevance: "Soda several times a week; BMI 27.8. No diabetes in profile.",
      interpretation: "WHO's advice is conditional and is not a toxicology finding; diet drinks are not necessarily worse than sugary soda.",
      nextStep: "Make water your default; use a diet drink only as a bridge while you cut sugary soda.",
      fields: ["lifestyle.sugaryDrinks", "healthMetrics.bmi"],
      guidance: {
        firstLine: "Water or unsweetened drinks are a good default. A diet drink can be a practical bridge if it replaces sugary soda and helps you stick with the change.",
        secondLine: "WHO conditionally advises against using non-sugar sweeteners to control weight; this is not a finding that approved sweeteners are toxic.",
        alternatives: "Water, sparkling water, unsweetened tea.",
        benefits: "Swapping sugary drinks for no-calorie ones cuts sugar and calories; long-term weight benefit is uncertain.",
        risks: "Few. The WHO recommendation is conditional and debated.",
        sources: [WHO_NSS],
      },
    },
    coffee: {
      relevance: "2 cups of coffee a day and 6.5 hours of sleep.",
      interpretation: "Sleep is the more actionable detail than coffee quantity.",
      nextStep: "Try an earlier last cup and see if your sleep changes.",
      fields: ["lifestyle.coffeeCupsPerDay", "lifestyle.sleepHoursPerNight"],
      guidance: {
        firstLine: "No need to start or stop coffee for longevity. With 6.5 hours of sleep, try an earlier caffeine cutoff.",
        benefits: "Alertness and enjoyment; links to better health in observational studies do not prove cause.",
        risks: "Can disturb sleep or trigger anxiety or palpitations in some people; sugar and cream add calories.",
        sources: [],
      },
    },
    omega3: {
      relevance: "Not taking omega-3; cardiovascular prevention interest; LDL 132 mg/dL. Triglycerides not recorded.",
      interpretation: "Low priority: over-the-counter fish oil is not recommended solely for primary prevention; fish as food is reasonable.",
      nextStep: "Eat fish as part of meals; skip over-the-counter fish oil unless a clinician has a specific reason.",
      fields: ["supplements", "healthInterests", "healthMetrics.ldlCholesterolMgDl"],
      guidance: {
        firstLine: "Low priority. Fish as food is reasonable. Over-the-counter fish oil is not recommended on its own to prevent heart disease.",
        secondLine: "Prescription omega-3 is for specific cases, such as high triglycerides, and is not the same as store-bought fish oil.",
        benefits: "Fish provides protein and unsaturated fat, with less saturated fat than red meat.",
        risks: "Higher-dose omega-3 products are linked to atrial fibrillation; bleeding risk and product quality vary.",
        recovery: "If triglycerides are high, your clinician sets any recheck.",
        sources: [AHA_O3, AHA21],
      },
    },
    "cold-lifting": {
      relevance: "Strength training twice weekly with occasional cold-water immersion afterward. Father's heart attack alone is not a contraindication; no cardiovascular disease or arrhythmia is listed.",
      interpretation: "If building muscle is the goal, routine immediate cold immersion may modestly blunt gains; evidence is limited.",
      nextStep: "If muscle gain is your priority, skip routine cold immersion right after lifting or separate it from the session.",
      fields: ["lifestyle.exercise", "lifestyle.recoveryPractices"],
      guidance: {
        firstLine: "If muscle or strength is your priority, avoid routine cold immersion right after every lifting session, or separate it from lifting. For soreness, occasional use is a preference-based trade-off.",
        alternatives: "Sleep, enough protein and calories, light activity, gradual progression.",
        benefits: "May reduce soreness short term. Repeated immediate use may slightly blunt muscle growth; evidence is limited.",
        risks: "Cold shock (sudden gasp and heart-rate surge) and drowning risk; more concern with heart disease, arrhythmia or uncontrolled high BP. Avoid solo immersion and long or extreme exposure.",
        sources: [COLD],
      },
    },
    vitd: {
      relevance: "Takes vitamin D3 1,000 IU daily (not automatically a high dose); no bone or fracture history listed; reason given is general health.",
      interpretation: "Neither routine testing nor automatic stopping is indicated; review the reason, diet and any bone or absorption concerns.",
      nextStep: "Review why you take it and your total intake with your clinician; testing and dose are individualized.",
      fields: ["supplements", "age"],
      guidance: {
        firstLine: "Review your reason for taking it and your total vitamin D intake with your clinician. In healthy adults, routine testing is not advised, but known deficiency, bone disease, absorption problems or some medicines are different cases.",
        benefits: "Supports bone health when intake or status is low. Benefit for preventing fractures in healthy adults is not established.",
        risks: "Very high long-term doses can cause high calcium and kidney stones. 1,000 IU a day is usually well below the adult upper limit (4,000 IU).",
        recovery: "Any recheck after a dose change is set by your clinician.",
        sources: [ENDO, USPSTF_D],
      },
    },
    nmn: {
      relevance: "Takes NMN 500 mg daily for longevity.",
      interpretation: "Low priority and low evidence; human studies are small and short and show biomarker changes, not health outcomes.",
      nextStep: "Review the brand, dose and cost with your clinician and decide whether it is worth continuing.",
      fields: ["supplements"],
      guidance: {
        firstLine: "Optional, low-evidence supplement. It has not been shown to extend lifespan or reliably prevent disease in humans. Review the product and dose with your clinician, especially with other medicines or planned surgery.",
        alternatives: "Better-supported levers: regular activity, blood pressure and LDL control, and diet quality.",
        benefits: "Small studies show changes in NAD-related blood markers; meaningful health benefit is not established.",
        risks: "Long-term safety, interactions and product purity are uncertain. Stopping is not medically necessary, but it is reasonable to pause spending until evidence improves.",
        sources: [],
      },
    },
    sodium: {
      relevance: "BP 132/84 is in the stage-1 range but one reading is not an average. Actual sodium intake not recorded; no known CKD.",
      interpretation: "Confirming with correctly taken home readings and reviewing sodium sources is a low-risk first step; lifestyle-first is for lower-risk adults after confirming average BP, not a universal rule.",
      nextStep: "Measure BP correctly at home (validated cuff, seated, two readings, several days) and check sodium on packaged foods.",
      fields: ["healthMetrics.bloodPressure", "lifestyle.diet"],
      guidance: {
        firstLine: "132/84 is above ideal, but one reading is not enough to set a diagnosis. Confirm with properly taken home readings and risk-based follow-up.",
        secondLine: "WHO suggests under 2,000 mg sodium (about 5 g salt) a day; an individual target can be discussed.",
        alternatives: "Look first at packaged sauces, snacks and processed meats. Potassium salt substitutes only after checking kidney function and medicines.",
        benefits: "Can lower BP, especially if intake is high, and supports lower cardiovascular risk.",
        risks: "Very strict limits may be impractical. Potassium salt substitutes can be unsafe with kidney disease or potassium-raising medicines.",
        recovery: "Home BP averages as your clinician directs; follow-up depends on your overall risk.",
        sources: [HBP, WHO_NA],
      },
    },
    dash: {
      relevance: "BP 132/84 (stage-1 range, single reading), BMI 27.8, inconsistent vegetable and whole-grain intake.",
      interpretation: "DASH has strong BP evidence and suits a reading just above 130/80; it should come with confirmed home readings.",
      nextStep: "Confirm 132/84 with properly taken home readings, and pick one DASH habit such as a daily vegetable or whole-grain swap.",
      fields: ["healthMetrics.bloodPressure", "healthMetrics.bmi", "lifestyle.diet"],
      guidance: {
        firstLine: "DASH emphasizes vegetables, fruit, whole grains, legumes, nuts, low-fat dairy or alternatives, and less sodium. 132/84 warrants confirmation with home readings and risk-based follow-up.",
        alternatives: "Mediterranean pattern; more activity and weight management also help.",
        benefits: "Strong evidence for lowering BP, and it improves overall diet quality.",
        risks: "Usually low. Potassium precautions apply only to specific kidney conditions or medicines.",
        recovery: "Home BP averages as your clinician directs; response varies.",
        sources: [HBP, AHA21],
      },
    },
    "wb-mri": {
      relevance: "Preventive-health profile, no symptoms listed, father's heart attack at 59. Family history is not an indication for whole-body MRI.",
      interpretation: "Avoid as routine screening for an asymptomatic person; it is not a heart-risk test.",
      nextStep: "Skip routine whole-body MRI; ask which evidence-based screenings fit your age and history.",
      fields: ["profileType", "medicalHistory"],
      guidance: {
        firstLine: "Not recommended as routine screening. The ACR does not recommend whole-body MRI for people without symptoms, and it is not a test of heart risk.",
        alternatives: "Age- and risk-appropriate screening your clinician advises; manage BP and lipids directly.",
        benefits: "May find a rare abnormality, but benefit for living longer has not been shown.",
        risks: "False positives, incidental findings, further tests or biopsies, anxiety and cost.",
        sources: [ACR],
      },
    },
  },
  "jamie-chen": {
    sodium: {
      relevance: "BP 146/90 on amlodipine 5 mg is in the stage-2 range and above goal despite treatment; frequent packaged sauces and salty snacks. Kidney function and actual sodium intake are not recorded.",
      interpretation: "Treated but above-target BP needs timely prescriber review and a home-BP protocol, not a 3 to 6 month wait. Sodium reduction is a useful partner to medicine.",
      nextStep: JAMIE_BP_STEP,
      fields: ["healthMetrics.bloodPressure", "medications", "lifestyle.diet"],
      guidance: {
        firstLine: "Your recent BP is above goal even though you take amlodipine. Measure at home (validated upper-arm cuff, seated 5 minutes, two readings a minute apart, morning and evening for several days) and share the averages with your prescriber soon.",
        secondLine: JAMIE_BP_ER,
        alternatives: "Check sodium per serving on your five most-used sauces and snacks; use herbs, spices, citrus, vinegar or no-salt-added options. Avoid potassium salt substitutes until a clinician or pharmacist has checked kidney function and medicines.",
        benefits: "Less sodium can lower BP and add to your medicine's effect.",
        risks: "Potassium salt substitutes can cause high potassium with kidney disease or potassium-raising medicines (kidney function is not in your data). Do not adjust or stop amlodipine on your own.",
        recovery: JAMIE_BP_FOLLOW,
        sources: [HBP, WHO_NA],
      },
    },
    dash: {
      relevance: "BP 146/90 above target on amlodipine 5 mg; improving BP is a stated goal; kidney function not recorded.",
      interpretation: "Strong BP evidence for DASH, but diet is an add-on to prompt prescriber review, not a substitute.",
      nextStep: JAMIE_BP_STEP,
      fields: ["healthMetrics.bloodPressure", "medications", "lifestyle.goals"],
      guidance: {
        firstLine: "Adopt DASH-style meals (vegetables, fruit, whole grains, legumes, low-fat dairy, less sodium) alongside your medicine, and send home BP averages and your medicine details to your prescriber promptly.",
        secondLine: JAMIE_BP_ER,
        alternatives: "Mediterranean pattern; weight loss and more activity also lower BP.",
        benefits: "Strong evidence for lowering BP; may also help weight and lipids.",
        risks: "Watch for dizziness if BP falls, but diet is not a reason to stop medicine. Potassium is a concern only with CKD or certain drugs.",
        recovery: JAMIE_BP_FOLLOW,
        sources: [HBP, AHA21],
      },
    },
    fiber: {
      relevance: "HbA1c 6.0% (prediabetes range), LDL 148 mg/dL, mother had type 2 diabetes; diabetes prevention and weight loss are stated interests. Fiber intake is not recorded.",
      interpretation: "Best single card linking prediabetes and cardiovascular risk: refined-grain swaps and fiber fit glucose and LDL goals, but BP follow-up and overall ASCVD risk still need attention.",
      nextStep: "Replace one refined-grain serving a day with oats, barley, whole grains or beans, and ask your clinician about a diabetes-prevention program and your cardiovascular risk.",
      fields: ["healthMetrics.hba1cPercent", "healthMetrics.ldlCholesterolMgDl", "healthInterests"],
      guidance: {
        firstLine: "HbA1c 6.0% is in the prediabetes range, not diabetes. Ask your clinician about a structured diabetes-prevention program, activity (often about 150 minutes a week) and a 5 to 7% weight-loss goal if it applies.",
        secondLine: "In daily meals, swap refined grains for oats, barley, whole grains or beans, and replace sugary drinks. Also review blood pressure and overall heart risk at follow-up.",
        alternatives: "Mediterranean or DASH patterns; vegetables, nuts and seeds.",
        benefits: "Soluble fiber can modestly lower LDL; fiber-rich patterns support blood sugar control and fullness.",
        risks: "Gas or bloating if increased quickly.",
        recovery: "HbA1c recheck timing is clinician-directed; about yearly is common for prediabetes, sooner when appropriate.",
        sources: [ADA3, ADA5, AHA21, DGA],
      },
    },
    vitd: {
      relevance: "Postmenopausal, takes vitamin D3 1,000 IU daily (not automatically excessive); vitamin D status and kidney function unknown; no known fragility fracture. Lower priority than BP and cardiometabolic risk.",
      interpretation: "Postmenopausal status alone does not mean testing or stopping is required; a clinician-led bone-health review is the sensible step.",
      nextStep: "Ask your clinician for a bone-health review, including whether a bone density (DXA) scan is indicated.",
      fields: ["sex", "supplements", "medicalHistory"],
      guidance: {
        firstLine: "Ask your clinician to review your diet, bone health, fall or fracture history and why you take vitamin D. A bone density (DXA) scan is a separate question from vitamin D testing.",
        alternatives: "Dietary calcium and vitamin D, weight-bearing exercise.",
        benefits: "Adequate vitamin D supports bone health; routine supplements have not been shown to prevent fractures in all healthy adults.",
        risks: "Excess dosing can cause high calcium and kidney stones. 1,000 IU a day is not automatically too much; total intake and your conditions matter.",
        recovery: "Any recheck after a dose change is set by your clinician.",
        sources: [ENDO, USPSTF_D],
      },
    },
    "med-diet": {
      relevance: "BP 146/90, LDL 148 mg/dL, HbA1c 6.0%, mostly home-cooked meals with packaged sauces.",
      interpretation: "Fits BP, lipid and glucose concerns together; sodium from cheese, olives, sauces and cured foods must be watched.",
      nextStep: "Replace butter and processed meat with olive oil, beans and fish in a few home meals, and choose low-sodium versions.",
      fields: ["healthMetrics.bloodPressure", "healthMetrics.ldlCholesterolMgDl", "healthMetrics.hba1cPercent", "lifestyle.diet"],
      guidance: {
        firstLine: "Replace butter and processed meat with unsaturated oils, legumes, nuts, whole grains, vegetables, fruit and fish if you eat it. Prioritize low sodium because your BP is above goal despite treatment.",
        alternatives: "A DASH pattern may be especially useful for BP.",
        benefits: "Supports BP, LDL, weight and blood sugar risk management.",
        risks: "Generally low. Salt in cheese, olives, sauces and cured foods can undermine BP goals.",
        recovery: "Recheck BP, lipids and HbA1c as your clinician directs; response varies.",
        sources: [AHA21, ADA5],
      },
    },
    fasting: {
      relevance: "Occasionally skips breakfast with no structured plan; weight loss goal; takes amlodipine.",
      interpretation: "Occasional breakfast skipping does not need to become a protocol; amlodipine does not make fasting categorically unsafe, but symptoms, hydration and other medicines matter.",
      nextStep: "Ask about dizziness when you skip meals, and discuss any planned fasting regimen with your clinician.",
      fields: ["lifestyle.eatingPattern", "lifestyle.goals", "medications"],
      guidance: {
        firstLine: "No need to turn occasional breakfast skipping into a fasting protocol. A sustainable modest calorie reduction or a Mediterranean or DASH pattern is a better first step.",
        alternatives: "Continuous modest calorie reduction; more daily steps.",
        benefits: "May help weight loss if it lowers total calories; not consistently better than steady calorie reduction.",
        risks: "Dizziness or low BP can occur if food or fluid intake drops; mention symptoms and any other medicines to your clinician.",
        recovery: "Track weight trend and any dizziness; discuss a planned regimen first.",
        sources: [IF_BMJ],
      },
    },
    upf: {
      relevance: "Frequent packaged sauces and salty snacks; BP 146/90.",
      interpretation: "Focus on sodium and added sugar rather than condemning all processed food.",
      nextStep: "Check sodium per serving and a realistic portion on your five most-used sauces and snacks.",
      fields: ["lifestyle.diet", "healthMetrics.bloodPressure"],
      guidance: {
        firstLine: "Check sodium per serving, at a realistic portion, on your five most-used sauces and snacks, and swap the highest.",
        alternatives: "Herbs, spices, citrus, vinegar and no-salt-added options instead of packaged sauces.",
        benefits: "Can meaningfully cut sodium and added sugar without overhauling your whole diet.",
        risks: "Cost, availability and cooking time.",
        recovery: "Re-check label numbers for your top items from time to time.",
        sources: [DGA, AHA21],
      },
    },
    ssb: {
      relevance: "Sweetened drinks on weekends; HbA1c 6.0% (prediabetes range); mother had type 2 diabetes.",
      interpretation: "A small, easy target, but should sit inside a structured prediabetes plan rather than be oversold as a single fix.",
      nextStep: "Replace weekend sweetened drinks with water, sparkling water or unsweetened tea.",
      fields: ["lifestyle.sugaryDrinks", "healthMetrics.hba1cPercent", "medicalHistory"],
      guidance: {
        firstLine: "Replace weekend sweetened drinks with water, sparkling water or unsweetened tea. A non-sugar-sweetened drink can be a stepping stone if it replaces sugar.",
        secondLine: "Pair this with a structured prediabetes plan; one swap alone is not enough.",
        benefits: "Less added sugar and fewer calories, which supports diabetes prevention.",
        risks: "Few; preference and access matter.",
        recovery: "HbA1c recheck timing is clinician-directed; about yearly is common for prediabetes.",
        sources: [WHO_SUG, DGA, ADA3],
      },
    },
    "red-meat": {
      relevance: "Red or processed meat several times weekly; LDL 148 mg/dL; BP 146/90.",
      interpretation: "Processed meat adds sodium and saturated fat; unprocessed red meat servings do not all carry identical risk.",
      nextStep: "Replace processed meat first, then swap some red-meat meals for beans, lentils, fish or poultry.",
      fields: ["lifestyle.diet", "healthMetrics.ldlCholesterolMgDl", "healthMetrics.bloodPressure"],
      guidance: {
        firstLine: "Replace processed meat first because it adds sodium and saturated fat; then swap some red-meat meals for beans, lentils, tofu, nuts, fish or poultry.",
        alternatives: "Beans, lentils, nuts, tofu, fish, poultry.",
        benefits: "May improve sodium and saturated-fat intake; plant swaps add fiber.",
        risks: "If you remove many animal foods, check B12, iron and protein.",
        recovery: "Recheck lipids and BP as your clinician directs; response varies.",
        sources: [AHA21, DGA],
      },
    },
    "plant-based": {
      relevance: "Red or processed meat several times weekly; BP 146/90; LDL 148 mg/dL.",
      interpretation: "A two-meal substitution is achievable and helps saturated fat and fiber; not a requirement to become vegan.",
      nextStep: "Try two meat-free meals a week using beans, lentils, tofu, nuts and whole grains.",
      fields: ["lifestyle.diet", "healthMetrics.bloodPressure", "healthMetrics.ldlCholesterolMgDl"],
      guidance: {
        firstLine: "Try two meat-free meals with beans, lentils, tofu, nuts and whole grains. This is an achievable swap, not a vegan requirement.",
        alternatives: "Mediterranean or DASH patterns.",
        benefits: "Can lower saturated fat and add fiber, supporting LDL and BP.",
        risks: "If fully vegan, ensure B12; consider iron, calcium and protein, especially after menopause.",
        recovery: "Recheck BP and lipids as your clinician directs; response varies.",
        sources: [AHA21],
      },
    },
    nuts: {
      relevance: "LDL 148 mg/dL, BP 146/90; weight loss goal; salty snacks eaten frequently.",
      interpretation: "Benefit and sodium goals are served when unsalted nuts explicitly replace a salty snack.",
      nextStep: "Swap one salty snack a day for a small portion of unsalted nuts.",
      fields: ["healthMetrics.ldlCholesterolMgDl", "lifestyle.diet", "healthInterests"],
      guidance: {
        firstLine: "Swap a small portion of unsalted nuts for a salty snack. Salted nuts work against your sodium goal.",
        alternatives: "Seeds, fruit or other low-sodium snacks.",
        benefits: "Unsaturated fat, fiber and plant protein, with less sodium if it replaces the salty snack.",
        risks: "Energy-dense (weight goal); allergy risk.",
        sources: [AHA21],
      },
    },
    "fruit-veg": {
      relevance: "BP 146/90 and practical dietary change is a stated interest. Kidney function not recorded; no known CKD.",
      interpretation: "Ordinary produce generally need not be restricted without a specific medical reason; concentrated potassium products are the real concern.",
      nextStep: "Add a vegetable to your main meal each day; frozen or no-salt-added canned is fine.",
      fields: ["healthMetrics.bloodPressure", "healthInterests"],
      guidance: {
        firstLine: "Add vegetables and fruit routinely; frozen and no-salt-added canned choices are useful.",
        benefits: "Fiber and potassium-rich foods fit a healthy pattern and may help BP.",
        risks: "Ordinary fruit and vegetables need no restriction without a medical reason. Ask your clinician or pharmacist before using concentrated potassium products with kidney disease or potassium-raising medicines.",
        recovery: "Home BP averages as your clinician directs; response varies.",
        sources: [AHA21, DGA, HBP],
      },
    },
    "sat-fat": {
      relevance: "LDL 148 mg/dL, BP 146/90, HbA1c 6.0%, red or processed meat several times weekly. Triglycerides, smoking status and 10-year risk not recorded.",
      interpretation: "Escalate: treated BP and lipids together drive cardiovascular risk; LDL 148 alone does not set an exact goal.",
      nextStep: "Ask your clinician to calculate your 10-year risk (PREVENT), review your full lipid panel, and discuss a one-time Lp(a) test and whether a cholesterol-lowering medicine suits you.",
      fields: ["healthMetrics.ldlCholesterolMgDl", "healthMetrics.bloodPressure", "lifestyle.diet"],
      guidance: {
        firstLine: "Ask your clinician to calculate your 10-year risk (PREVENT), review your full lipid panel and other causes of high LDL, and decide together about cholesterol-lowering treatment. BP control matters now too.",
        secondLine: "Eat less saturated fat (processed and red meat, butter) and more vegetables, whole grains, legumes, nuts and fish. Lp(a) is measured once in adulthood.",
        alternatives: "ApoB or other tests are used selectively if they would change the decision.",
        benefits: "Lowering saturated fat and, when indicated, LDL reduces heart attacks and strokes.",
        risks: "Statins can cause muscle symptoms (serious injury is rare) and modestly raise diabetes risk in some people; for people at enough risk, benefit generally outweighs this. Amlodipine interacts with some statins, notably simvastatin, so your prescriber or pharmacist can pick a compatible one and dose.",
        recovery: "Lipids are often rechecked 4 to 12 weeks after starting or changing a lipid-lowering medicine; response varies.",
        sources: [LIPID, AHA21, DGA],
      },
    },
    omega3: {
      relevance: "Cardiovascular risk reduction is a stated interest. Triglycerides not recorded.",
      interpretation: "Low priority: over-the-counter fish oil is not recommended solely for prevention; amlodipine alone is not a standard omega-3 interaction.",
      nextStep: "Eat fish as part of meals; skip over-the-counter fish oil unless a clinician has a specific reason.",
      fields: ["healthInterests", "healthMetrics.ldlCholesterolMgDl"],
      guidance: {
        firstLine: "Low priority. Fish as food is reasonable. Over-the-counter fish oil is not recommended on its own to prevent heart disease.",
        secondLine: "Prescription omega-3 is for specific cases, such as high triglycerides, and is not interchangeable with store-bought fish oil.",
        benefits: "Fish provides protein and unsaturated fat, with less saturated fat than red meat.",
        risks: "Higher-dose omega-3 products are linked to atrial fibrillation; bleeding concerns depend on dose and context.",
        recovery: "If triglycerides are checked, your clinician sets any recheck.",
        sources: [AHA_O3, AHA21],
      },
    },
    sweeteners: {
      relevance: "Sweetened drinks on weekends; weight loss and diabetes prevention goals. WHO's recommendation excludes people with pre-existing diabetes (she has prediabetes range, not diabetes).",
      interpretation: "Water is the default but diet drinks can be a bridge; neither is proven harmful.",
      nextStep: "Make water or unsweetened drinks your default on weekends; use a diet drink only as a bridge if needed.",
      fields: ["lifestyle.sugaryDrinks", "lifestyle.goals", "healthInterests"],
      guidance: {
        firstLine: "Water or unsweetened drinks are a good default. A diet drink can be a bridge away from sugary drinks if it helps.",
        secondLine: "WHO's advice against using non-sugar sweeteners for weight control is conditional and excludes people with diabetes; it is not a finding that approved sweeteners are toxic.",
        alternatives: "Water, sparkling water, unsweetened tea.",
        benefits: "Replacing sugary drinks cuts sugar exposure; long-term weight benefit of sweeteners is uncertain.",
        risks: "No proven harm; the evidence is debated.",
        sources: [WHO_NSS],
      },
    },
    "low-carb": {
      relevance: "HbA1c 6.0% (prediabetes range), weight loss goal, BP 146/90, LDL 148 mg/dL. Amlodipine is not a direct contraindication.",
      interpretation: "Reasonable with qualification; BP control and diabetes-prevention support come first.",
      nextStep: "Discuss diet options with your clinician or dietitian, and choose unsaturated fats if you cut carbohydrates.",
      fields: ["healthMetrics.hba1cPercent", "lifestyle.goals", "healthMetrics.ldlCholesterolMgDl"],
      guidance: {
        firstLine: "A moderate low-carb pattern can be used if you prefer it, but avoid high saturated-fat replacements. Mediterranean or DASH is equally reasonable. Prioritize BP control and diabetes-prevention support.",
        alternatives: "Mediterranean, DASH or another sustainable calorie-appropriate pattern.",
        benefits: "Can improve weight and blood sugar for some people; ADA lists Mediterranean and lower-carbohydrate approaches for prediabetes.",
        risks: "LDL may rise with high saturated fat (yours is 148 mg/dL); hard to sustain. If weight or BP falls, your clinician may review your overall treatment.",
        recovery: "Recheck HbA1c, lipids and BP as your clinician directs.",
        sources: [ADA3, ADA5],
      },
    },
    coffee: {
      relevance: "1 cup of coffee a day; BP 146/90.",
      interpretation: "One cup is no reason to stop automatically; a single before/after reading is not a diagnosis.",
      nextStep: "Keep caffeine timing and BP measurement conditions consistent, and note any short-term rise or symptoms.",
      fields: ["lifestyle.coffeeCupsPerDay", "healthMetrics.bloodPressure"],
      guidance: {
        firstLine: "One cup daily is not a reason to stop. Keep caffeine timing and your BP measurement routine consistent; do not judge from a single reading.",
        benefits: "Enjoyment and alertness; no need to start or stop for longevity.",
        risks: "Caffeine can briefly raise BP in some people and affect sleep or palpitations; sugar and cream add calories.",
        sources: [],
      },
    },
    "wb-mri": {
      relevance: "Preventive screening is a stated interest; no symptoms or prior events listed.",
      interpretation: "Avoid as routine screening; it does not replace management of hypertension, LDL or prediabetes.",
      nextStep: "Skip routine whole-body MRI; ask which evidence-based screenings fit your age and history.",
      fields: ["healthInterests", "medicalHistory"],
      guidance: {
        firstLine: "Not recommended as routine screening. The ACR does not recommend whole-body MRI for people without symptoms, and it is not a substitute for managing BP, LDL or prediabetes.",
        alternatives: "Age- and risk-appropriate screening, plus BP, lipid and HbA1c follow-up.",
        benefits: "No established evidence that it improves survival in people without symptoms.",
        risks: "Incidental findings, false positives, extra tests, anxiety and cost.",
        sources: [ACR],
      },
    },
  },
};
