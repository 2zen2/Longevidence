"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { DEVICES, type DeviceId } from "@/data/devices";
import { useApp, useRequirePatient } from "@/components/AppState";
import Icon from "@/components/Icon";
import { btnPrimary, btnQuiet } from "@/components/ui";

export default function Devices() {
  const patient = useRequirePatient();
  const { connected, toggleDevice } = useApp();
  const [pending, setPending] = useState<DeviceId[]>([]);
  const timers = useRef<number[]>([]);
  useEffect(() => { const t = timers.current; return () => t.forEach(window.clearTimeout); }, []);
  if (!patient) return null;

  // Simulated handshake: a short delay, then the toggle flips. Nothing leaves the browser.
  const toggle = (id: DeviceId) => {
    if (connected.includes(id)) return toggleDevice(id);
    setPending((p) => [...p, id]);
    timers.current.push(window.setTimeout(() => { toggleDevice(id); setPending((p) => p.filter((x) => x !== id)); }, 700));
  };

  return (
    <div className="mx-auto max-w-xl pt-10 sm:pt-20">
      <h1 className="text-3xl font-semibold tracking-tight">Connect your devices</h1>
      <p className="mt-2 text-sm text-muted">Connections are simulated. Nothing is shared.</p>
      <ul className="mt-8 divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
        {DEVICES.map((d) => {
          const on = connected.includes(d.id), busy = pending.includes(d.id);
          return (
            <li key={d.id} className="flex items-center gap-4 px-5 py-4">
              <Icon name={d.icon} size={22} className={on ? "text-primary" : "text-muted"} />
              <span className="flex-1 font-medium">{d.name}</span>
              <button role="switch" aria-checked={on} aria-label={d.name} disabled={busy} onClick={() => toggle(d.id)}
                className={`inline-flex min-w-[7rem] items-center justify-center gap-1.5 rounded-full border px-4 py-1.5 text-sm transition-colors ${on ? "border-primary bg-tint text-primary" : "border-line hover:border-primary"} ${busy ? "opacity-60" : ""}`}>
                {on && <Icon name="check" size={14} />}{busy ? "Connecting…" : on ? "Connected" : "Connect"}
              </button>
            </li>
          );
        })}
      </ul>
      <div className="mt-8 flex items-center justify-between">
        <Link href="/search" className={btnQuiet}>Skip</Link>
        <Link href="/search" className={btnPrimary}>Continue</Link>
      </div>
    </div>
  );
}
