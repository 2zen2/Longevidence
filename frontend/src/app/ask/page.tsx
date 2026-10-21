import { redirect } from "next/navigation";
import { api } from "@/lib/api";
import ResultsView from "@/components/ResultsView";
import AskTools from "@/components/AskTools";

export const dynamic = "force-dynamic";

/** Free-form question: the same evidence engine as the preset topics, over whatever the corpus holds. */
export default async function AskPage({ searchParams }: { searchParams: Promise<{ q?: string | string[]; deep?: string; refresh?: string }> }) {
  const sp = await searchParams;
  const q = (Array.isArray(sp.q) ? sp.q[0] : sp.q)?.trim().slice(0, 400) ?? "";   // the API accepts at most 400 characters
  if (q.length < 8) redirect("/search");
  const [assist, ingest] = await Promise.all([api.assistEnabled(), api.ingestStatus()]);
  const deep = assist && sp.deep === "1";
  let report;
  try { report = await api.ask(q, { deep, refresh: sp.refresh === "1" }); } catch {
    return <p className="pt-24 text-center text-muted">The research service is unreachable. Start it with <code>make api</code>.</p>;
  }
  const counted = report.studies.filter((s) => s.counted).length;
  const related = counted < 3 ? await api.search(q).catch(() => []) : [];
  const tools = <AskTools q={q} deep={deep} assist={assist} ingest={ingest} thin={counted < 3} />;
  return <ResultsView topic={{ slug: null, label: "Your question", question: q, deep }} report={report} related={related} extra={assist || ingest?.enabled ? tools : undefined} />;
}
