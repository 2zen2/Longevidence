import type { QuestionBrief } from "./types";

/** Extra search words per topic slug (the API's own aliases are used too). */
const EXTRA: Record<string, string[]> = {
  "sglt2-hf": ["heart failure", "jardiance", "farxiga"],
  vitd: ["vitamin d", "d3", "bone", "fracture", "osteoporosis"],
  "med-diet": ["mediterranean", "olive oil"],
  fasting: ["time restricted", "calorie restriction"],
  upf: ["processed food", "ultra processed"],
  sodium: ["salt", "blood pressure", "hypertension"],
  ssb: ["soda", "sugary drinks", "soft drink", "sugar sweetened"],
  "red-meat": ["bacon", "beef", "processed meat"],
  fiber: ["whole grain", "whole grains"],
  "plant-based": ["vegan", "vegetarian"],
  nuts: ["almonds", "walnuts"],
  "fruit-veg": ["fruit", "vegetables", "veggies"],
  "sat-fat": ["cholesterol", "ldl", "butter"],
  "low-carb": ["keto", "ketogenic", "atkins", "carbohydrate"],
  sweeteners: ["aspartame", "stevia", "sucralose", "diet soda"],
  coffee: ["caffeine"],
  dash: ["blood pressure", "hypertension"],
  omega3: ["fish oil", "omega 3", "dha", "epa"],
  nmn: ["nad", "nicotinamide", "niagen"],
  "cold-lifting": ["cold plunge", "ice bath", "cold water", "muscle growth", "hypertrophy"],
  "wb-mri": ["mri", "body scan", "imaging", "prenuvo"],
};
const STOP = new Set("the and for with from that this does do is are can will you your has have how what why when which about into than then more less most lower higher reduce reduces improve improves increase increases risk risks health healthy adults adult intake linked associated lead greater better early outcomes outcome effect effects help any".split(" "));

export const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const tokens = (s: string) => norm(s).split(" ").filter((t) => t.length >= 3 && !STOP.has(t));

export interface TopicMatch { topic: QuestionBrief & { slug: string }; score: number }

/** Rank the topics a free-text query refers to. An empty result means the demo does not cover it. */
export function matchTopics(query: string, topics: (QuestionBrief & { slug: string })[]): TopicMatch[] {
  const q = norm(query);
  if (q.length < 2) return [];
  const padded = ` ${q} `;
  const qTokens = tokens(q);
  const out: TopicMatch[] = [];
  for (const t of topics) {
    const phrases = [t.label, t.slug.replace(/-/g, " "), ...t.aliases, ...(EXTRA[t.slug] ?? [])].map(norm).filter((p) => p.length >= 2);
    let score = 0;
    for (const p of phrases) {
      if (padded.includes(` ${p} `)) score = Math.max(score, 10 + p.length / 100);
      else if (q.length >= 3 && (p.startsWith(q) || p.split(" ").some((w) => w.startsWith(q)))) score = Math.max(score, 6);
    }
    const bag = new Set([...tokens(t.question), ...t.tags.flatMap(tokens)]);
    const overlap = qTokens.filter((w) => bag.has(w)).length;
    score = Math.max(score, overlap * 2);
    if (score > 0) out.push({ topic: t, score });
  }
  return out.sort((a, b) => b.score - a.score).slice(0, 5);
}
