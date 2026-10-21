export interface QuestionBrief { id: number; label: string; question: string; slug: string | null; tags: string[]; aliases: string[] }

export interface PaperDetail { id: number; title: string; journal: string | null; publication_date: string | null; publication_types: string[] }
export interface DocPassage { uid: string; document_id: number; ordinal: number; section: string; section_title: string | null; kind: string; label: string | null; text: string; doc_kind: string }
export interface DocClaimEvidence { passage_uid: string; quote_start: number; quote_end: number; verification: string; origin: string }
export interface DocClaim {
  id: number; claim_type: string; text: string; extraction_status: string; status_reasons: string[]; evidence: DocClaimEvidence[];
  structured: { outcome?: string; direction?: string; scope?: string; value?: string | number; quote?: string };
}
export interface PaperDocument { documents: { id: number; kind: string }[]; passages: DocPassage[]; claims: DocClaim[] }

export type Stance = "favorable" | "unfavorable" | "null" | "unclear";
export interface ReportEvidence { passage_uid: string; quote_start: number; quote_end: number; verification: string; doc_kind: string }
export interface ReportFinding {
  claim_id: number; outcome: string; estimate: string; stance: Stance; outcome_relevant: boolean; subgroup: boolean; evidence: ReportEvidence[];
}
export interface ReportStudy {
  paper_id: number; title: string; journal: string | null; pmid: string | null; year: number | null; counted: boolean;
  design_label?: string; sample_size?: number | null; weight?: number; basis?: "fulltext" | "abstract";
  findings?: ReportFinding[]; headline?: ReportFinding | null; excluded_detail?: string;
}
export interface Statement { id: string; kind: "headline" | "verdict" | "study" | "conflict" | "caveat"; text: string }
export interface CaveatGroup { text: string; paper_ids: number[]; n: number }
export interface Passage { paper_id: number; section: string; section_title: string | null; kind: string; label: string | null; text: string; doc_kind: string }
export interface EvidenceReport {
  question: string;
  verdict: { label: string };
  certainty: { level: string; downgrades: { domain: string; applied: boolean; reason: string }[]; cap: string | null };
  counts: { retrieved: number; counted: number };
  studies: ReportStudy[];
  caveats?: { populations: CaveatGroup[]; durations: CaveatGroup[]; notes: string[] };
  interpretation?: { model_read: boolean; exposure_terms: string[]; outcome_terms: string[]; polarity: string };
  conflicts: unknown[];
  conclusion: Statement[];
  passages: Record<string, Passage>;
}

export interface IngestStatus { enabled: boolean; max_papers: number; active_job: number | null; reason?: string | null }

export interface RelatedPaper { id: number; title: string; journal: string | null; year: number | null; design: string }
