import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import type { DocClaim, DocPassage, PaperDocument, Stance } from "@/lib/types";
import PaperGate from "@/components/PaperGate";
import { BackLink, Label } from "@/components/ui";

export const dynamic = "force-dynamic";

const STANCE: Record<Stance, { text: string; cls: string }> = {
  favorable: { text: "Supports", cls: "bg-primary text-white" },
  null: { text: "No clear effect", cls: "border border-line text-ink" },
  unfavorable: { text: "Contradicts", cls: "border border-ink text-ink" },
  unclear: { text: "Unclear", cls: "border border-line text-muted" },
};
const DIRECTION: Record<string, string> = {
  favors_intervention: "Favors the intervention or higher exposure", favors_comparator: "Favors the comparator or lower exposure",
  no_difference: "No significant difference", unclear: "Direction unclear",
};
const VERIFIED: Record<string, string> = { exact: "Quote found in the text", numeric: "Numbers found in the text" };
const STUDY_FACTS: [string, string][] = [["design", "Design"], ["sample_size", "Sample size"], ["population", "Population"], ["intervention", "Intervention"], ["comparator", "Comparator"]];

export default async function PaperPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ from?: string; q?: string; deep?: string }> }) {
  const { id } = await params;
  const { from, q: rawQ, deep } = await searchParams;
  const q = rawQ?.slice(0, 400);
  const pid = Number(id);
  if (!Number.isInteger(pid)) notFound();
  let paper, doc: PaperDocument, topic, report;
  try {
    [paper, doc] = await Promise.all([api.paper(pid), api.paperDocument(pid)]);
  } catch (e) {
    if (e instanceof Error && /-> 404/.test(e.message)) notFound();
    return <p className="pt-24 text-center text-muted">The research service is unreachable. Start it with <code>make api</code>.</p>;
  }
  try {   // the stance badges are optional: the paper itself still shows if the report cannot be built
    if (from) {
      topic = (await api.questions()).find((t) => t.slug === from);
      if (topic) report = await api.ask(topic.question);
    } else if (q && q.length >= 8) report = await api.ask(q, { deep: deep === "1" });
  } catch { /* no badges */ }

  const study = report?.studies.find((s) => s.paper_id === pid);
  const stanceOf = new Map((study?.findings ?? []).map((f) => [f.claim_id, f.stance]));
  const passages = new Map(doc.passages.map((p) => [p.uid, p]));
  const abstract = doc.passages.filter((p) => p.doc_kind === "pubmed_abstract");
  const fullText = doc.passages.filter((p) => p.doc_kind !== "pubmed_abstract");
  const facts = STUDY_FACTS.flatMap(([t, label]) => { const c = doc.claims.find((x) => x.claim_type === t); return c ? [[label, c.structured.value ?? c.text] as const] : []; });
  const findings = doc.claims.filter((c) => c.claim_type === "finding").sort((a, b) => Number(a.structured.scope === "subgroup") - Number(b.structured.scope === "subgroup"));
  const limits = doc.claims.filter((c) => c.claim_type === "limitation");
  const meta = [paper.journal, paper.publication_date?.slice(0, 4), paper.publication_types.filter((t) => t !== "Journal Article").join(", ")].filter(Boolean).join(" · ");

  return (
    <PaperGate>
      <div className="mx-auto max-w-3xl pt-4">
        <BackLink href={topic ? `/results/${topic.slug}` : report ? `/ask?q=${encodeURIComponent(q ?? "")}${deep === "1" ? "&deep=1" : ""}` : "/search"}>{topic ? topic.label : report ? "Your question" : "Search"}</BackLink>
        <h1 className="mt-6 text-2xl font-semibold leading-snug tracking-tight sm:text-3xl">{paper.title}</h1>
        <p className="mt-2 text-sm text-muted">{meta}</p>

        <div className="mt-10 space-y-12">
          {facts.length > 0 && (
            <section>
              <Label>Study</Label>
              <dl className="mt-3 divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
                {facts.map(([k, v]) => (
                  <div key={k} className="grid gap-x-6 gap-y-0.5 px-5 py-3.5 sm:grid-cols-[9rem_1fr]"><dt className="text-sm text-muted">{k}</dt><dd>{String(v)}</dd></div>
                ))}
              </dl>
            </section>
          )}

          <section>
            <Label>Results and our evaluation</Label>
            {study && !study.counted && <p className="mt-3 rounded-xl bg-tint px-4 py-3 text-sm text-primary">Not counted for this question: {study.excluded_detail ?? "set aside by the evidence evaluation"}.</p>}
            <ul className="mt-3 divide-y divide-line border-y border-line">
              {findings.map((c) => <Finding key={c.id} c={c} stance={stanceOf.get(c.id)} passages={passages} />)}
              {findings.length === 0 && <li className="py-6 text-sm text-muted">No results were extracted from this paper.</li>}
            </ul>
          </section>

          {limits.length > 0 && (
            <section>
              <Label>Limitations stated by the authors</Label>
              <ul className="mt-3 space-y-4">
                {limits.map((c) => (
                  <li key={c.id}><p className="leading-relaxed">{c.text.replace(/^Stated limitation:\s*/, "")}</p><Evidence c={c} passages={passages} /></li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <Label>Text on file</Label>
            {abstract.length === 0 && fullText.length === 0 && <p className="mt-3 text-sm text-muted">No text is stored for this paper.</p>}
            {abstract.length > 0 && (
              <div className="mt-3">
                <h3 className="text-sm font-medium">Abstract</h3>
                <Passages items={abstract} />
              </div>
            )}
            {fullText.length > 0 && (
              <details className="group mt-6 border-y border-line">
                <summary className="flex cursor-pointer list-none items-center justify-between py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
                  Full text ({fullText.length} passages)
                  <span className="text-muted transition-transform group-open:rotate-180" aria-hidden>⌄</span>
                </summary>
                <div className="pb-4"><Passages items={fullText} /></div>
              </details>
            )}
          </section>
        </div>
      </div>
    </PaperGate>
  );
}

function Finding({ c, stance, passages }: { c: DocClaim; stance?: Stance; passages: Map<string, DocPassage> }) {
  const st = stance && STANCE[stance];
  return (
    <li className="py-5">
      <p className="font-medium leading-snug">{c.structured.outcome ?? c.text}</p>
      <p className="mt-1 text-sm text-muted">{c.text.replace(c.structured.outcome ? `${c.structured.outcome}: ` : "", "")}</p>
      <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
        {st && <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${st.cls}`}>{st.text}</span>}
        {c.structured.scope === "subgroup" && <span className="rounded-full border border-line px-2.5 py-0.5 text-xs text-muted">Subgroup</span>}
        <span className="text-muted">{DIRECTION[c.structured.direction ?? ""] ?? c.structured.direction}</span>
      </p>
      <Evidence c={c} passages={passages} />
    </li>
  );
}

/** The stored passage behind a claim, trimmed around the verified quote, which is highlighted. */
function Evidence({ c, passages }: { c: DocClaim; passages: Map<string, DocPassage> }) {
  const e = c.evidence.find((x) => passages.has(x.passage_uid));
  const p = e && passages.get(e.passage_uid);
  if (!e || !p) return null;
  const from = Math.max(0, e.quote_start - 160), to = Math.min(p.text.length, e.quote_end + 160);
  const where = p.label ?? p.section_title ?? p.section;
  return (
    <figure className="mt-3 border-l-2 border-accent pl-4">
      <figcaption className="text-xs text-muted">{p.doc_kind === "pubmed_abstract" ? "Abstract" : "Full text"}{where ? ` · ${where}` : ""} · {VERIFIED[e.verification] ?? e.verification}</figcaption>
      <blockquote className="mt-1 text-sm leading-relaxed">
        {from > 0 && "… "}{p.text.slice(from, e.quote_start)}<mark className="evidence">{p.text.slice(e.quote_start, e.quote_end)}</mark>{p.text.slice(e.quote_end, to)}{to < p.text.length && " …"}
      </blockquote>
    </figure>
  );
}

function Passages({ items }: { items: DocPassage[] }) {
  return (
    <div className="mt-3 space-y-4">
      {items.map((p) => (
        <div key={p.uid}>
          {(p.label ?? p.section_title) && <h4 className="text-xs font-medium uppercase tracking-[0.08em] text-muted">{p.label ?? p.section_title}</h4>}
          <p className="mt-1 max-w-prose text-[15px] leading-relaxed">{p.text}</p>
        </div>
      ))}
    </div>
  );
}
