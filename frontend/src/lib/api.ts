import type { EvidenceReport, IngestStatus, PaperDetail, PaperDocument, QuestionBrief, RelatedPaper } from "./types";

// Server-side only: pages fetch here and pass plain props to the browser, so the API never has to be reachable from it.
const BASE = process.env.API_URL ?? "http://localhost:8010";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  questions: () => get<QuestionBrief[]>("/api/questions"),
  ask: (q: string, o: { deep?: boolean; refresh?: boolean } = {}) =>
    get<EvidenceReport>(`/api/ask?q=${encodeURIComponent(q)}${o.deep ? "&deep=true" : ""}${o.refresh ? "&refresh=true" : ""}`),
  /** Optional features that need a connected language model. Both are false/null when none is configured. */
  assistEnabled: async () => (await get<{ enabled: boolean }>("/api/assist/status").catch(() => ({ enabled: false }))).enabled,
  ingestStatus: () => (process.env.INGEST_UI === "off" ? Promise.resolve(null) : get<IngestStatus>("/api/ingest/status").catch(() => null)),
  /** Closest stored papers for free text (hybrid keyword + semantic search). */
  search: async (q: string, limit = 5) => (await get<{ cards: RelatedPaper[] }>(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`)).cards,
  paper: (id: number) => get<PaperDetail>(`/api/papers/${id}`),
  /** Stored passages and extracted claims for one paper. */
  paperDocument: (id: number) => get<PaperDocument>(`/api/papers/${id}/document`),
};
