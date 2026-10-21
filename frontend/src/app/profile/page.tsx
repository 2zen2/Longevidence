"use client";

import type { ReactNode } from "react";
import { initials } from "@/data/patients";
import { useRequirePatient } from "@/components/AppState";
import { BackLink, Label } from "@/components/ui";

const METRICS: [string, string, string][] = [
  ["heightCm", "Height", "cm"], ["weightKg", "Weight", "kg"], ["bmi", "BMI", ""], ["bloodPressure", "Blood pressure", "mmHg"],
  ["restingHeartRateBpm", "Resting heart rate", "bpm"], ["hba1cPercent", "HbA1c", "%"], ["ldlCholesterolMgDl", "LDL cholesterol", "mg/dL"],
];
const LIFESTYLE: [string, string][] = [
  ["activityLevel", "Activity"], ["dailySteps", "Daily steps"], ["exercise", "Exercise"], ["recoveryPractices", "Recovery"], ["diet", "Diet"],
  ["eatingPattern", "Eating pattern"], ["coffeeCupsPerDay", "Coffee (cups/day)"], ["sugaryDrinks", "Sugary drinks"], ["sleepHoursPerNight", "Sleep (hours/night)"], ["goals", "Goals"],
];

export default function Profile() {
  const patient = useRequirePatient();
  if (!patient) return null;
  const meds = [...patient.medications.map((m) => ({ ...m, kind: "Medication" })), ...patient.supplements.map((m) => ({ ...m, kind: "Supplement" }))];
  const life = LIFESTYLE.flatMap(([k, label]) => {
    const v = patient.lifestyle[k];
    return v === undefined ? [] : [[label, Array.isArray(v) ? v.join("; ") : k === "dailySteps" ? Number(v).toLocaleString() : String(v)] as const];
  });

  return (
    <div className="mx-auto max-w-3xl pt-4">
      <BackLink href="/search">Search</BackLink>
      <div className="mt-6 flex items-center gap-4">
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-primary text-base font-medium text-white" aria-hidden>{initials(patient.name)}</span>
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{patient.name}</h1>
          <p className="mt-0.5 text-muted">{patient.age}, {patient.sex} · {patient.profileType}</p>
        </div>
      </div>

      <div className="mt-10 space-y-10">
        <Section title="Health metrics">
          <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-line bg-line sm:grid-cols-4">
            {METRICS.map(([k, label, unit]) => patient.healthMetrics[k] !== undefined && (
              <div key={k} className="bg-surface p-4">
                <dt className="text-xs text-muted">{label}</dt>
                <dd className="mt-1 text-xl font-semibold tracking-tight">{k === "hba1cPercent" ? Number(patient.healthMetrics[k]).toFixed(1) : String(patient.healthMetrics[k])}{unit && <span className="ml-1 text-xs font-normal text-muted">{unit}</span>}</dd>
              </div>
            ))}
            <div className="bg-surface" aria-hidden />
          </dl>
        </Section>

        <Section title="Medical history">
          <List items={patient.medicalHistory} />
        </Section>

        <Section title="Medications and supplements">
          {meds.length === 0 ? <p className="text-sm text-muted">None listed.</p> : (
            <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
              {meds.map((m) => (
                <li key={m.kind + m.name} className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5 px-5 py-3.5">
                  <span className="font-medium">{m.name}</span>
                  <span className="text-sm text-muted">{m.dose} · {m.reason}</span>
                  <span className="ml-auto rounded-full border border-line px-2.5 py-0.5 text-xs text-muted">{m.kind}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Lifestyle">
          <dl className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
            {life.map(([k, v]) => (
              <div key={k} className="grid gap-x-6 gap-y-0.5 px-5 py-3.5 sm:grid-cols-[11rem_1fr]">
                <dt className="text-sm text-muted">{k}</dt><dd>{v}</dd>
              </div>
            ))}
          </dl>
        </Section>

        <Section title="Health interests">
          <ul className="flex flex-wrap gap-2">
            {patient.healthInterests.map((i) => <li key={i} className="rounded-full bg-tint px-3.5 py-1.5 text-sm text-primary">{i}</li>)}
          </ul>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section><Label>{title}</Label><div className="mt-3">{children}</div></section>;
}

function List({ items }: { items: string[] }) {
  return (
    <ul className="space-y-2">
      {items.map((x) => <li key={x} className="flex gap-3"><span className="mt-2.5 h-1 w-1 shrink-0 rounded-full bg-muted" aria-hidden />{x}</li>)}
    </ul>
  );
}
