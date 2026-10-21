"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useState } from "react";
import { PERSONAL, SUGGESTED } from "@/data/personalization";
import { matchTopics, norm } from "@/lib/match";
import { hoverPrimary } from "./ui";
import type { QuestionBrief } from "@/lib/types";
import { useApp, useRequirePatient } from "./AppState";
import Icon from "./Icon";

type Topic = QuestionBrief & { slug: string };

export default function SearchView({ topics }: { topics: Topic[] }) {
  const patient = useRequirePatient();
  const app = useApp();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [missed, setMissed] = useState<string | null>(null);
  const [focus, setFocus] = useState(false);
  const [picked, setPicked] = useState<number | null>(null); // row chosen by arrow keys or hover
  const listId = useId();

  useEffect(() => { if (app.ready) setQ(app.query); }, [app.ready]); // eslint-disable-line react-hooks/exhaustive-deps
  const matches = useMemo(() => matchTopics(q, topics), [q, topics]);
  if (!patient) return null;

  const open = (t: Topic, query = t.label) => { app.setSearch(query, t.slug); router.push(`/results/${t.slug}`); };
  const query = q.trim();
  const canAsk = query.length >= 8;
  const rows = matches.length + (canAsk ? 1 : 0); // preset matches, then "search all research"
  const ask = () => { app.setSearch(query, null); router.push(`/ask?q=${encodeURIComponent(query)}`); };
  // Without an explicit pick, a short name-level match ("sodium") wins. A full sentence goes to "search all research",
  // since one shared keyword ("cholesterol") does not make it the same question as the preset.
  const words = query.split(/\s+/).length;
  const sameQuestion = matches[0] && norm(query) === norm(matches[0].topic.question);
  const presetFirst = !canAsk || sameQuestion || (matches[0]?.score >= 6 && words < 5);
  const active = picked ?? (presetFirst ? 0 : matches.length);
  const submit = () => {
    if (!query) return;
    const hit = matches[active]?.topic;
    if (hit) return open(hit, query);
    if (canAsk) return ask();
    app.setSearch(query, null);
    setMissed(query);
  };
  const suggestions = (SUGGESTED[patient.id] ?? []).flatMap((slug) => topics.filter((t) => t.slug === slug)).slice(0, 3);
  const showList = focus && rows > 0 && query.length > 0;

  return (
    <div className="mx-auto max-w-3xl pt-10 sm:pt-20">
      <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">What would you like to research?</h1>

      <form role="search" onSubmit={(e) => { e.preventDefault(); submit(); }} className="relative mt-8">
        <Icon name="search" size={20} className="pointer-events-none absolute left-4 top-1/2 sm:left-5 -translate-y-1/2 text-muted" />
        <input value={q} autoFocus autoComplete="off" aria-label="Search treatments, supplements, diagnostics or topics" placeholder="Search a treatment or topic"
          role="combobox" aria-expanded={showList} aria-controls={listId} aria-autocomplete="list" maxLength={400}
          aria-activedescendant={showList ? `${listId}-${active}` : undefined}
          onChange={(e) => { setQ(e.target.value); setMissed(null); setPicked(null); setFocus(true); }}
          onFocus={(e) => { setFocus(true); e.target.select(); }} onBlur={() => setFocus(false)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown" && rows) { e.preventDefault(); setPicked((active + 1) % rows); }
            if (e.key === "ArrowUp" && rows) { e.preventDefault(); setPicked((active - 1 + rows) % rows); }
            if (e.key === "Escape") setFocus(false);
          }}
          className="w-full rounded-2xl border border-line bg-surface py-4 pl-12 pr-16 text-base sm:pl-14 sm:pr-28 sm:text-lg shadow-field outline-none transition-colors placeholder:text-muted focus:border-accent focus:ring-4 focus:ring-ring" />
        <button type="submit" aria-label="Search" className={`absolute right-2.5 top-1/2 flex -translate-y-1/2 items-center rounded-xl bg-primary px-3 py-2.5 text-sm font-medium text-white transition-colors ${hoverPrimary} sm:px-5`}><span className="hidden sm:inline">Search</span><Icon name="arrowRight" size={18} className="sm:hidden" /></button>
        {showList && (
          <ul id={listId} role="listbox" className="absolute inset-x-0 top-full z-10 mt-2 overflow-hidden rounded-2xl border border-line bg-surface shadow-lg">
            {matches.map((m, i) => (
              <li key={m.topic.slug} id={`${listId}-${i}`} role="option" aria-selected={i === active}
                onMouseDown={(e) => { e.preventDefault(); open(m.topic, q.trim()); }} onMouseEnter={() => setPicked(i)}
                className={`flex cursor-pointer items-baseline justify-between gap-4 px-5 py-3 ${i === active ? "bg-tint" : ""}`}>
                <span className="font-medium">{m.topic.label}</span>
                <span className="text-xs text-muted">{m.topic.tags[0]}</span>
              </li>
            ))}
            {canAsk && (
              <li id={`${listId}-${matches.length}`} role="option" aria-selected={active === matches.length} onMouseDown={(e) => { e.preventDefault(); ask(); }} onMouseEnter={() => setPicked(matches.length)}
                className={`flex cursor-pointer items-center gap-3 px-5 py-3 ${matches.length ? "border-t border-line" : ""} ${active === matches.length ? "bg-tint" : ""}`}>
                <Icon name="search" size={16} className="shrink-0 text-muted" />
                <span className="min-w-0 truncate">Search all research for <span className="font-medium">“{query}”</span></span>
              </li>
            )}
          </ul>
        )}
      </form>

      {missed && (
        <p role="status" className="mt-4 text-sm text-muted">The demo doesn’t cover “{missed}” yet. Ask a full question to search all research, or try a suggestion below.</p>
      )}

      <section aria-label="Suggested for you" className="mt-12">
        <h2 className="text-xs font-medium uppercase tracking-[0.08em] text-muted">Suggested for you</h2>
        <ul className="mt-3 grid gap-3 sm:grid-cols-3">
          {suggestions.map((t) => (
            <li key={t.slug}>
              <Link href={`/results/${t.slug}`} onClick={() => app.setSearch(t.label, t.slug)}
                className="group flex h-full flex-col justify-between gap-6 rounded-2xl border border-line bg-surface p-5 transition-colors hover:border-primary">
                <span>
                  <span className="block text-xs text-muted">{t.tags[0]}</span>
                  <span className="mt-1 block text-lg font-medium leading-snug">{t.label}</span>
                </span>
                <span className="flex items-end justify-between gap-3">
                  <span className="text-sm text-primary">{PERSONAL[patient.id]?.[t.slug]?.relevance}</span>
                  <Icon name="arrowRight" size={16} className="shrink-0 text-muted transition-colors group-hover:text-primary" />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
