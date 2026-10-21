"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { PATIENTS, initials } from "@/data/patients";
import { useApp } from "@/components/AppState";

export default function SignIn() {
  const { login, patient, ready } = useApp();
  const router = useRouter();
  const signingIn = useRef(false);
  useEffect(() => { if (ready && patient && !signingIn.current) router.replace("/search"); }, [ready, patient, router]);
  const pick = (id: string) => { signingIn.current = true; login(id); router.push("/devices"); };
  if (!ready || patient) return null;
  return (
    <div className="mx-auto max-w-xl pt-12 sm:pt-24">
      <h1 className="text-3xl font-semibold tracking-tight">Sign in</h1>
      <p role="note" className="mt-6 rounded-xl border border-ink/70 px-4 py-3 text-sm leading-relaxed">
        Authentication and the User DB are omitted in this demo. Choose a profile to continue.
      </p>
      <ul className="mt-8 space-y-3">
        {PATIENTS.map((p) => (
          <li key={p.id} className="flex items-center gap-4 rounded-2xl border border-line bg-surface p-4 sm:p-5">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-tint-strong text-sm font-medium text-primary" aria-hidden>{initials(p.name)}</span>
            <span className="min-w-0 flex-1">
              <span className="block font-medium">{p.name}</span>
              <span className="block text-sm text-muted">{p.age}, {p.sex} · {p.profileType}</span>
            </span>
            <button onClick={() => pick(p.id)} aria-label={`Sign in as ${p.name}`} className="shrink-0 rounded-full bg-primary px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90">Sign in</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
