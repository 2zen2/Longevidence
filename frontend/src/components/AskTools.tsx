"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { IngestStatus } from "@/lib/types";

interface Plan { query: string; count?: number }
interface Job { status: string; stage?: string | null; error?: string | null }
const ACTIVE = new Set(["queued", "running"]);
const DONE = "done";
const PAPERS = 30;   // papers per job asked for (the API caps it at INGEST_MAX_PAPERS)
const MAX_POLL_ERRORS = 4;

async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/ingest${path}`, body === undefined ? undefined : { method: "POST", body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data?.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data as T;
}

/** Optional model-backed features for a free-form question. Renders nothing unless a model is connected. */
export default function AskTools({ q, deep, assist, ingest, thin }: { q: string; deep: boolean; assist: boolean; ingest: IngestStatus | null; thin: boolean }) {
  const router = useRouter();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval>>(undefined);
  const enc = encodeURIComponent(q);

  useEffect(() => {
    if (jobId == null) return;
    let errors = 0;
    const tick = async () => {
      try {
        const j = await call<Job>(`/${jobId}`);
        errors = 0;
        setJob(j);
        if (!ACTIVE.has(j.status)) {
          clearInterval(timer.current);
          if (j.status === DONE) router.replace(`/ask?q=${enc}&refresh=1${deep ? "&deep=1" : ""}`);
        }
      } catch (e) {   // one dropped poll should not strand the page; give up after a few in a row
        if (++errors < MAX_POLL_ERRORS) return;
        clearInterval(timer.current);
        setJob({ status: "failed", error: (e as Error).message });
      }
    };
    tick();
    timer.current = setInterval(tick, 2500);
    return () => clearInterval(timer.current);
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  const wrap = async (fn: () => Promise<void>) => { setBusy(true); setErr(null); try { await fn(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); } };
  const propose = () => wrap(async () => setPlan(await call<Plan>("/plan", { topic: q.slice(0, 200) })));
  const start = () => wrap(async () => {
    const r = await call<{ job_id: number }>("", { topic: q.slice(0, 200), query: plan!.query, retmax: Math.min(PAPERS, ingest?.max_papers ?? PAPERS) });
    setPlan(null); setJobId(r.job_id);
  });

  const showAssist = assist;
  const finished = job != null && !ACTIVE.has(job.status);
  const showIngest = !!ingest?.enabled && (thin || jobId != null) && !(finished && job.status === DONE && !thin);
  if (!showAssist && !showIngest) return null;
  const running = jobId != null && (!job || ACTIVE.has(job.status));

  return (
    <div className="space-y-3 rounded-2xl border border-line bg-surface p-5 text-sm">
      {showAssist && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-muted">{deep ? "An AI model re-read your question to find the right studies." : "Not what you meant? An AI model can re-read your question."}</span>
          <Link href={`/ask?q=${enc}${deep ? "" : "&deep=1"}`} className="font-medium text-primary underline underline-offset-4">{deep ? "Use standard reading" : "Interpret with AI"}</Link>
        </div>
      )}
      {showIngest && (
        <div className={showAssist ? "border-t border-line pt-3" : ""}>
          {running ? (
            <p className="text-muted">Researching this topic{job?.stage ? ` — ${job.stage}` : ""}…</p>
          ) : plan ? (
            <div className="space-y-3">
              <p className="text-muted">The model proposes this PubMed search{typeof plan.count === "number" ? ` (${plan.count} records match)` : ""}. Up to {Math.min(PAPERS, ingest?.max_papers ?? PAPERS)} papers will be read and added.</p>
              <code className="block overflow-x-auto rounded-lg bg-tint p-3 text-xs">{plan.query}</code>
              <div className="flex gap-3">
                <button onClick={start} disabled={busy} className="rounded-full bg-primary px-4 py-2 text-white disabled:opacity-50">Add these papers</button>
                <button onClick={() => setPlan(null)} className="px-2 text-muted">Cancel</button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="text-muted">{finished ? "The new papers did not add enough evidence to answer this." : "Little research on file for this question."}</span>
              <button onClick={propose} disabled={busy} className="font-medium text-primary underline underline-offset-4 disabled:opacity-50">{busy ? "Working…" : "Research this topic"}</button>
            </div>
          )}
        </div>
      )}
      {finished && job.status !== DONE && <p className="text-ink">The job ended with status “{job.status}”{job.error ? `: ${job.error}` : ""}.</p>}
      {err && <p className="text-ink">{err}</p>}
    </div>
  );
}
