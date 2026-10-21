"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { PERSONAL, type Guidance } from "@/data/personalization";
import type { EvidenceReport, RelatedPaper, ReportFinding, ReportStudy, Stance } from "@/lib/types";
import { useApp, useRequirePatient } from "./AppState";
import Icon from "./Icon";
import { BackLink, Label } from "./ui";

interface Props { topic: { slug: string | null; label: string; question: string; deep?: boolean }; report: EvidenceReport; related?: RelatedPaper[]; extra?: ReactNode }

/** The engine's seven verdicts mapped to the labels shown to patients. "Does not support" is added because "no clear effect" or "contradicted" is not insufficient, mixed or conflicting. */
function assessment(r: EvidenceReport) {
  switch (r.verdict.label) {
    case "Supported": case "Leans supported": return "Supports";
    case "Mixed / conflicting": return r.conflicts.length ? "Conflicting" : "Mixed";
    case "Insufficient evidence": return "Insufficient";
    default: return "Does not support";
  }
}
const STANCE: Record<Stance, { text: string; cls: string }> = {
  favorable: { text: "Supports", cls: "bg-primary text-white" },
  null: { text: "No clear effect", cls: "border border-line text-ink" },
  unfavorable: { text: "Contradicts", cls: "border border-ink text-ink" },
  unclear: { text: "Unclear", cls: "border border-line text-muted" },
};
const PIPS: Record<string, number> = { high: 4, moderate: 3, low: 2, "very low": 1 };

export default function ResultsView({ topic, report: r, related = [], extra }: Props) {
  const from = topic.slug ? `from=${topic.slug}` : `q=${encodeURIComponent(topic.question)}${topic.deep ? "&deep=1" : ""}`;
  const patient = useRequirePatient();
  const app = useApp();
  const counted = useMemo(() => r.studies.filter((s) => s.counted && s.headline).sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0)), [r]);
  const tally = useMemo(() => {
    const t: Record<Stance, number> = { favorable: 0, null: 0, unfavorable: 0, unclear: 0 };
    counted.forEach((s) => (t[s.headline!.stance] += 1));
    return t;
  }, [counted]);
  // Sticky only while the whole column fits in the viewport; otherwise it scrolls normally.
  const col = useRef<HTMLDivElement>(null);
  const [stick, setStick] = useState(false);
  useEffect(() => {
    const el = col.current;
    if (!el) return;
    const check = () => setStick(window.innerWidth >= 1024 && el.offsetHeight <= window.innerHeight - 48);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    window.addEventListener("resize", check);
    return () => { ro.disconnect(); window.removeEventListener("resize", check); };
  }, [patient]);
  if (!patient) return null;

  const mine = topic.slug ? PERSONAL[patient.id]?.[topic.slug] : undefined;
  const first = patient.name.split(" ")[0];
  const summary = r.conclusion.find((s) => s.kind === "headline")?.text ?? `${counted.length} studies answer this question.`;
  const limits = limitations(r, counted.length);
  const level = r.certainty.level;

  return (
    <div className="pt-4">
      <BackLink href="/search">{app.query && app.query !== topic.label ? `“${app.query}”` : "Search"}</BackLink>
      <p className="mt-6 text-sm font-medium text-primary">{topic.label}</p>
      <h1 className="mt-1.5 max-w-4xl text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">{topic.question}</h1>
      {r.interpretation?.model_read && (
        <p className="mt-3 text-sm text-muted">Read as: <span className="text-ink">{r.interpretation.exposure_terms.join(" ") || "any exposure"}</span> → <span className="text-ink">{r.interpretation.outcome_terms.join(", ") || "any outcome"}</span></p>
      )}
      {extra && <div className="mt-8">{extra}</div>}

      <div className="mt-10 grid gap-x-14 gap-y-12 lg:grid-cols-[3fr_2fr]">
        <div ref={col} className={`space-y-10 ${stick ? "lg:sticky lg:top-6 lg:self-start" : "lg:self-start"}`}>
          <section aria-label="Evidence assessment">
            <Label>Evidence assessment</Label>
            <p className="mt-2 text-4xl font-semibold tracking-tight text-primary">{assessment(r)}</p>
            {counted.length > 0 && (
              <div className="mt-4 max-w-md">
                <div className="flex h-2 gap-0.5 overflow-hidden rounded-full" role="img" aria-label={`${tally.favorable} support, ${tally.null} no clear effect, ${tally.unfavorable} contradict`}>
                  {([["favorable", "bg-primary"], ["null", "bg-accent"], ["unfavorable", "bg-ink-soft"], ["unclear", "bg-line"]] as const).map(([k, c]) => tally[k] > 0 && <span key={k} className={c} style={{ flex: tally[k] }} />)}
                </div>
                <p className="mt-2 flex flex-wrap gap-x-4 text-sm text-muted">
                  <span>{tally.favorable} support</span><span>{tally.null} no clear effect</span><span>{tally.unfavorable} contradict</span>{tally.unclear > 0 && <span>{tally.unclear} unclear</span>}
                </p>
              </div>
            )}
            <p className="mt-5 max-w-prose leading-relaxed">{summary}</p>
          </section>

          <div className="!mt-6">
            <p className="flex items-center gap-2 text-sm text-muted">
              Certainty
              <span className="inline-flex gap-0.5" aria-hidden>{[1, 2, 3, 4].map((i) => <span key={i} className={`h-1.5 w-5 rounded-full ${i <= (PIPS[level] ?? 0) ? "bg-primary" : "bg-line"}`} />)}</span>
              <span className="font-medium text-ink">{level === "not rated" ? "Not rated" : level[0].toUpperCase() + level.slice(1)}</span>
            </p>
            {limits.length > 0 && (
              <details className="group mt-3 max-w-prose border-y border-line">
                <summary className="flex cursor-pointer list-none items-center justify-between py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
                  Limitations ({limits.length})
                  <Icon name="chevron" size={16} className="transition-transform group-open:rotate-180" />
                </summary>
                <ul className="space-y-2 pb-4 text-sm leading-relaxed">
                  {limits.map((l) => <li key={l} className="flex gap-3"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted" aria-hidden />{l}</li>)}
                </ul>
              </details>
            )}
          </div>

          {mine && (
            <section aria-label={`Recommendations for ${first}`} className="rounded-2xl bg-tint-strong p-6 sm:p-8">
              <h2 className="flex items-center gap-3 text-2xl font-semibold tracking-tight text-primary">
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent text-primary" aria-hidden><Icon name="user" size={18} /></span>
                For {first}
              </h2>
              {mine.guidance && <GuidanceBlock g={mine.guidance} />}
              <div className="mt-6 rounded-xl bg-primary p-5 text-white">
                <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.08em] text-accent"><Icon name="arrowRight" size={16} />Next step</p>
                <p className="mt-2 max-w-prose text-lg leading-snug">{mine.nextStep}</p>
              </div>
              {mine.guidance && mine.guidance.sources.length > 0 && <Sources items={mine.guidance.sources} />}
            </section>
          )}
        </div>

        <section aria-label="Research papers">
          <div className="flex items-baseline justify-between">
            <Label>Research papers</Label>
            <span className="text-sm text-muted">{counted.length}</span>
          </div>
          <ul className="mt-3 divide-y divide-line border-y border-line">
            {counted.map((s) => <Paper key={s.paper_id} s={s} r={r} from={from} open={app.expanded.includes(s.paper_id)} toggle={() => app.toggleExpanded(s.paper_id)} />)}
            {counted.length === 0 && <li className="py-6 text-sm text-muted">No paper in the corpus answers this question directly.</li>}
          </ul>
          {related.length > 0 && (
            <div className="mt-8">
              <Label>Closest papers on file</Label>
              <p className="mt-1 text-sm text-muted">These match your wording but may not answer the question.</p>
              <ul className="mt-3 divide-y divide-line border-y border-line">
                {related.map((p) => (
                  <li key={p.id} className="py-4">
                    <Link href={`/papers/${p.id}?${from}`} className="font-medium leading-snug hover:text-primary hover:underline">{p.title}</Link>
                    <p className="mt-1 text-sm text-muted">{[p.year, p.journal].filter(Boolean).join(" · ")}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function GuidanceBlock({ g }: { g: Guidance }) {
  const options: [string, string | undefined][] = [["First line", g.firstLine], ["Second line", g.secondLine], ["Alternatives", g.alternatives]];
  const rows = options.filter((o): o is [string, string] => !!o[1]);
  return (
    <div className="mt-5 space-y-6">
      <div>
        <dl className="space-y-3">
          {rows.map(([k, v]) => (
            <div key={k} className="grid gap-x-6 gap-y-0.5 sm:grid-cols-[7rem_1fr]">
              <dt className="text-sm font-medium text-primary">{k}</dt>
              <dd className="max-w-prose text-[15px] leading-relaxed">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="grid gap-6 border-t border-primary/15 pt-6 sm:grid-cols-2">
        <Fact title="Benefits" text={g.benefits} />
        <Fact title="Risks" text={g.risks} />
        {g.recovery && <div className="sm:col-span-2"><Fact title="Follow-up" text={g.recovery} /></div>}
      </div>
    </div>
  );
}

function Fact({ title, text }: { title: string; text: string }) {
  return <div><h3 className="text-xs font-medium uppercase tracking-[0.08em] text-muted">{title}</h3><p className="mt-2 text-[15px] leading-relaxed">{text}</p></div>;
}

function Sources({ items }: { items: string[] }) {
  return (
    <div className="mt-6 border-t border-primary/15 pt-5">
      <h3 className="text-xs font-medium uppercase tracking-[0.08em] text-muted">Sources</h3>
      <ul className="mt-2 space-y-1.5 text-sm">
        {items.map((x) => <li key={x} className="text-muted">{x}</li>)}
      </ul>
    </div>
  );
}

/** Plain-language limitations, rewritten from the engine's certainty reasons and caveats. */
function limitations(r: EvidenceReport, n: number): string[] {
  const out: string[] = [];
  if (n < 3) out.push(`Only ${n} ${n === 1 ? "study answers" : "studies answer"} this question directly.`);
  for (const d of r.certainty.downgrades.filter((x) => x.applied)) {
    if (d.domain === "risk of bias") {
      const m = d.reason.match(/(\d+) of (\d+) could be screened/);
      out.push(m ? `Only ${m[1]} of ${m[2]} studies could be fully checked for risk of bias.` : "Many studies have some risk of bias or could not be fully checked.");
    } else if (d.domain === "inconsistency") {
      out.push(d.reason.includes("differ in size") ? "Results differ in size between studies, though they point the same way." : "Studies don’t fully agree: some support the question and some show no effect.");
    } else if (d.domain === "imprecision") out.push("Estimates are imprecise, so the true effect could be larger or smaller.");
    else if (d.domain === "indirectness") out.push("Some studies don’t cover every part of the question.");
    else out.push(sentence(d.reason));
  }
  const abstractOnly = r.certainty.cap?.match(/(\d+)% of studies were appraised from the abstract only/);
  if (abstractOnly) out.push(`${abstractOnly[1]}% of studies were read from the abstract only, so dose and safety details may be missing.`);
  const pops = r.caveats?.populations.slice(0, 2).map((p) => p.text);
  if (pops?.length) out.push(`Studied in: ${pops.join("; ")}.`);
  const dur = r.caveats?.durations.slice(0, 2).map((p) => p.text);
  if (dur?.length) out.push(`Study length: ${dur.join("; ")}.`);
  const note = r.caveats?.notes.find((x) => !/abstract only/i.test(x)) ?? r.conclusion.find((x) => x.kind === "caveat" && !/abstract only/i.test(x.text))?.text;
  if (note) out.push(sentence(note));
  return [...new Set(out)].slice(0, 5);
}
const sentence = (s: string) => (/[.!?]$/.test(s) ? s : `${s}.`).replace(/^./, (c) => c.toUpperCase());

function Paper({ s, r, from, open, toggle }: { s: ReportStudy; r: EvidenceReport; from: string; open: boolean; toggle: () => void }) {
  const h = s.headline!;
  const st = STANCE[h.stance];
  const findings = evidenceOf(s, h, r.passages);
  const id = `paper-${s.paper_id}`;
  return (
    <li className="py-5">
      <h3 className="font-medium leading-snug">
        <Link href={`/papers/${s.paper_id}?${from}`} className="hover:text-primary hover:underline">{s.title}</Link>
      </h3>
      <p className="mt-1 text-sm text-muted">{[s.year, s.design_label, s.sample_size ? `N = ${s.sample_size.toLocaleString()}` : null, s.journal].filter(Boolean).join(" · ")}</p>
      <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${st.cls}`}>{st.text}</span>
        <span className="text-muted">{h.outcome}{h.estimate ? `: ${h.estimate}` : ""}</span>
      </p>
      {findings.length > 0 && (
        <button onClick={toggle} aria-expanded={open} aria-controls={id} className="mt-3 inline-flex items-center gap-1 text-sm text-primary hover:underline">
          Evidence <Icon name="chevron" size={16} className={`transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
      )}
      {open && (
        <div id={id} className="mt-3 space-y-4">
          {findings.map((f) => <Passage key={f.claim_id} f={f} r={r} />)}
          <Link href={`/papers/${s.paper_id}?${from}`} className="inline-flex items-center gap-1 text-sm text-primary hover:underline">Read the paper and our evaluation<Icon name="arrowRight" size={14} /></Link>
        </div>
      )}
    </li>
  );
}

/** Up to three findings with a stored passage, headline first, one per distinct quote. */
function evidenceOf(s: ReportStudy, h: ReportFinding, passages: EvidenceReport["passages"]): ReportFinding[] {
  const seen = new Set<string>(), out: ReportFinding[] = [];
  for (const f of [h, ...(s.findings ?? []).filter((x) => x.outcome_relevant && !x.subgroup)]) {
    const e = f.evidence[0];
    const key = e && `${e.passage_uid}:${e.quote_start}`;
    if (!e || !passages[e.passage_uid] || seen.has(key)) continue;
    seen.add(key);
    out.push(f);
  }
  return out.slice(0, 3);
}

/** The stored passage behind a finding, trimmed around the verified quote, which is highlighted. */
function Passage({ f, r }: { f: ReportFinding; r: EvidenceReport }) {
  const e = f.evidence[0];
  const p = r.passages[e.passage_uid];
  if (!p) return null;
  const from = Math.max(0, e.quote_start - 160), to = Math.min(p.text.length, e.quote_end + 160);
  const kind = p.doc_kind === "pmc_jats" ? "Full text" : "Abstract";
  const where = p.label ?? p.section_title ?? p.section;
  const ref = where && where.toLowerCase() !== kind.toLowerCase() ? `${kind} · ${where}` : kind;
  return (
    <figure className="border-l-2 border-accent pl-4">
      <figcaption className="text-xs text-muted">{ref}</figcaption>
      <blockquote className="mt-1 text-sm leading-relaxed">
        {from > 0 && "… "}{p.text.slice(from, e.quote_start)}<mark className="evidence">{p.text.slice(e.quote_start, e.quote_end)}</mark>{p.text.slice(e.quote_end, to)}{to < p.text.length && " …"}
      </blockquote>
    </figure>
  );
}
