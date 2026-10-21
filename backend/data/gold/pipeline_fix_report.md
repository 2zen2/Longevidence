# Pipeline fix report (engine v4)

Scope: backend evidence evaluation across all 21 preset topics. Before = engine v3 reports (`before.json`), after = engine v4 re-run with refresh.

## Caveats first

- The gold labels in `pipeline_gold.json` are **not expert-labelled**. They were made by a single labeller (no second reviewer) from the extracted text, partly while developing against the pipeline, so there is an overfitting risk. The set deliberately over-represents suspicious studies, so its pass rate is not an accuracy estimate.
- Counts are shown as supports/null/contradicts/unclear among counted studies, using each study's headline finding.
- No verdict was set in advance; verdict moves follow from the rules below.

## What changed

1. **Direction per claim.** Each finding is oriented by which arm is the exposure (exposure vs comparator), and replacement/substitution, composition ratios (e.g. P:S) and contrast wording are read as 'less'. Calorie/time restriction is not a 'less' cue.
2. **Outcome head.** Outcomes are matched on the head noun phrase only (before comma/per/vs/in ...), not the whole string. Outcomes are tiered: 1 clinical events, 2 validated surrogates (lipids, BP, HbA1c, weight/BMI), 3 other biomarkers. The verdict is judged on one tier: the tier of the question's first outcome term if it has >=3 informative studies, else the first tier with >=3, else the tier with most. Other-tier studies are listed as `other_outcome_tier`, not tallied; per-tier counts are in `report.tiers`. Judging on a tier worse than asked costs one certainty step.
3. **Scope exclusions, logged with a reason** (`report.scope_exclusions`): pregnancy/infant/perinatal; children only when the question says 'adults'; acute/critical illness; prognosis in diagnosed patients for mortality/progression outcomes; policy/tax/global-burden analyses. Look-alike exposures (e.g. diet soda for SSB, pescatarian for plant-based, pickled vegetables for fruit-veg) are excluded via preset `exposure_not_terms`; abbreviations are recognised via `exposure_extra_terms` (both in questions.json, preset topics only).
4. **Mixed rule (reviewed only after 1-3).** The 20% each-side threshold is unchanged, but each side now also needs at least 2 studies (`mixed_min_studies_each_side = 2`). A single dissenting study no longer makes a topic Mixed, though it still lowers certainty through inconsistency. The verdict now reports n_supports and n_contradicts.

## Cache invalidation

`ENGINE_VERSION` is now `4`. It is part of the input hash and is also the `engine_version` column in the unique key `(input_hash, engine_version)`, so v1-v3 rows are never served. Verified: existing rows are v1-v3, a non-refresh `build_report` after the re-run returned engine_version 4 (cached), and the live API returned v4.

## Before / after

| Topic | Before | Cert. | Counted (S/N/C/U) | After | Cert. | Counted (S/N/C/U) | Judged on | Why |
|---|---|---|---|---|---|---|---|---|
| sglt2-hf | Mixed / conflicting | very low | 5 (1/2/1/1) | Leans supported | very low | 4 (2/2/0/0) | tier 1 | The one 'contradicting' study was a stratum or off-question result; exposure look-alikes and out-of-scope populations removed. No remaining dissent. |
| vitd | No clear effect | low | 16 (6/9/1/0) | No clear effect | low | 5 (0/4/1/0) | tier 1 | 11 studies left the tally: populations out of scope (7) and only part of a combination or not the exposure (2), plus outcome-tier separation. Remaining 5 are mostly null. |
| med-diet | Supported | very low | 13 (12/1/0/0) | Supported | very low | 12 (11/1/0/0) | tier 1 | One study removed (exposure/scope). Verdict unchanged. |
| fasting | Mixed / conflicting | low | 5 (2/1/2/0) | Leans supported | low | 7 (4/2/1/0) | tier 2 | Calorie/time-restriction cues no longer read as 'less' of the exposure; 37 non-fasting or combination papers excluded; judged on tier 2 (weight/HbA1c). Only 1 dissenting study, so the Mixed rule no longer fires. |
| upf | Supported | very low | 4 (4/0/0/0) | Supported | very low | 5 (4/0/0/1) | tier 1 | Outcomes matched on head; BMI-change study set aside as other tier; one mediation result added. Verdict unchanged. |
| sodium | Supported | very low | 6 (4/2/0/0) | Supported | moderate | 8 (7/1/0/0) | tier 2 | Salt-substitute and comparator-arm studies now signed correctly; judged on blood pressure (tier 2); the false conflict is gone so certainty rises. |
| ssb | Mixed / conflicting | very low | 9 (3/2/2/2) | Supported | very low | 4 (4/0/0/0) | tier 2 | Non-sugar-sweetened/diet drinks excluded as look-alikes, tax-policy study excluded, SSB abbreviations recognised; judged on tier 2 (BMI/weight). Now 4 favourable studies, no conflict. Caveat: includes a child BMI meta-analysis (422) because the question does not say 'adults', and a review (216). |
| red-meat | Supported | very low | 12 (9/2/1/0) | Supported | very low | 12 (11/1/0/0) | tier 1 | Substitution analyses are now counted and read as less red meat; a mis-signed study corrected. Verdict unchanged. |
| fiber | Supported | low | 11 (8/2/1/0) | Supported | very low | 7 (7/0/0/0) | tier 1 | Combination add-on and lipid/triglyceride studies set aside by tier; pregnancy study excluded; fewer studies, so certainty falls from low to very low. |
| plant-based | Supported | very low | 11 (9/0/2/0) | Supported | moderate | 6 (4/2/0/0) | tier 1 | Pescatarian/plant-based-oil look-alikes excluded; two mis-signed contradicting findings fixed; false conflict gone so certainty rises to moderate. |
| nuts | Supported | moderate | 6 (5/1/0/0) | Insufficient evidence | not rated | 2 (2/0/0/0) | tier 1 | Only 2 clinical-event studies remain; LDL/ApoB studies are tier 2 and are not mixed in. Falls below the 3-study minimum -> Insufficient evidence. |
| fruit-veg | Supported | very low | 9 (6/2/1/0) | Leans supported | very low | 8 (5/2/1/0) | tier 1 | Preserved/pickled vegetable studies excluded; one study set aside by tier. Leans supported rather than Supported because of 1 dissenting study out of 8. |
| sat-fat | Mixed / conflicting | very low | 16 (10/2/3/1) | Leans supported | very low | 7 (5/2/0/0) | tier 1 | 369 (P:S ratio) and 373 (exposure is the comparator arm) re-signed, 74 off-topic removed, pregnancy/infant (358, 376, 368) excluded, LDL studies set aside as tier 2. Remaining 7: 5 support, 2 null, 0 contradict. |
| low-carb | Supported | low | 7 (6/0/1/0) | Supported | low | 7 (6/0/1/0) | tier 2 | No change in verdict; two BMI findings flipped sign when the arm was read correctly (385 and 403), net counts identical. |
| sweeteners | Mixed / conflicting | low | 11 (5/2/2/2) | Contradicted | moderate | 7 (0/0/6/1) | tier 2 | Judged on tier 2 (weight/BMI/HbA1c), where 6 of 7 studies are unfavourable; tier 1 has only 2 informative studies (incident T2D cohort 408 set aside). Replacement/comparator mis-signs removed; certainty rises because the conflict was an artefact. |
| coffee | Supported | very low | 8 (6/1/1/0) | Supported | moderate | 7 (6/1/0/0) | tier 1 | Cancer-patient prognosis and other scope exclusions removed; false conflict gone so certainty rises. |
| dash | Supported | moderate | 9 (7/2/0/0) | Supported | moderate | 6 (5/1/0/0) | tier 2 | Judged on blood pressure (tier 2); 6 studies set aside as other tiers. Verdict and certainty unchanged. |
| omega3 | Supported | moderate | 8 (7/1/0/0) | Supported | very low | 3 (2/1/0/0) | tier 1 | Biomarker and other-tier studies set aside, populations excluded; only 3 studies remain, so certainty falls to very low. |
| nmn | Supported | moderate | 12 (9/3/0/0) | Supported | moderate | 9 (7/2/0/0) | tier 3 | Judged on tier 3 (NAD+), the first outcome the question names, which has 9 informative studies (tier 1 has 3 and tier 2 has 4, shown separately); 3 studies set aside or excluded; certainty unchanged. |
| cold-lifting | Leans supported | very low | 6 (3/2/0/1) | Leans supported | very low | 5 (2/2/0/1) | tier 1 | One study excluded (exposure). Verdict unchanged. |
| wb-mri | Insufficient evidence | not rated | 1 (0/0/0/1) | Insufficient evidence | not rated | 2 (0/0/0/2) | tier 1 | Still too little evidence; one more study counted (unclear). |

## Things to review by hand

- sat-fat and sglt2-hf: Mixed -> Leans supported (false contradicts removed).
- ssb: Mixed -> Supported and sweeteners: Mixed -> Contradicted. Both rest on tier-2 weight/BMI/HbA1c outcomes, not clinical events.
- fasting: Mixed -> Leans supported; nuts: Supported -> Insufficient evidence.
- Certainty rises to moderate for sodium, plant-based, coffee, sweeteners (conflicts were artefacts); falls for fiber, omega3 (thin base).
- nmn is judged on NAD+ (tier 3) and dash on blood pressure (tier 2); other tiers are shown separately, not mixed in. nmn: the clinical-event tier has 3 and tier 2 has 4 informative studies, so the choice of NAD+ follows the question's first outcome term; check it is what you want.

## Known residual misses (documented in pipeline_gold.json as known_miss)

29 (AF stratum counted as headline), 31 (single dose arm), 96 (bulking-phase TRE), 223 (tea pooled with unsweetened tea), 265 (fiber as combination add-on), 356 (low-quality stratum), 187 (sodium-stratum finding); also noted: 243 (ambiguous extraction), 216 (a review counted), 301 and 287 (plant-based strata).

## Tests

`tests/test_pipeline_units.py` (no DB), `tests/test_pipeline_gold.py` (regression over the gold labels; sat-fat has no false contradictions; every verdict is judged on one tier). `test_claim_battery.py` changed intentionally: substitution analyses are now counted as less red meat.
