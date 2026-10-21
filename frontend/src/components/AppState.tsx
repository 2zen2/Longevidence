"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { getPatient, type Patient } from "@/data/patients";
import type { DeviceId } from "@/data/devices";

/** State shared across screens, kept in sessionStorage so a refresh keeps the place. */
interface Saved {
  patientId: string | null;
  devices: Record<string, DeviceId[]>; // connected devices per patient
  query: string;
  topic: string | null; // slug of the topic the query resolved to
  expanded: number[]; // paper ids whose evidence is open
}
const EMPTY: Saved = { patientId: null, devices: {}, query: "", topic: null, expanded: [] };
const KEY = "longevidence-demo";

interface Ctx extends Saved {
  ready: boolean;
  patient: Patient | null;
  connected: DeviceId[];
  login: (id: string) => void;
  logout: () => void;
  toggleDevice: (id: DeviceId) => void;
  setSearch: (query: string, topic: string | null) => void;
  toggleExpanded: (paperId: number) => void;
}
const AppCtx = createContext<Ctx | null>(null);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [s, setS] = useState<Saved>(EMPTY);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(KEY);
      if (raw) setS({ ...EMPTY, ...JSON.parse(raw) });
    } catch { /* storage unavailable: start fresh */ }
    setReady(true);
  }, []);
  useEffect(() => {
    if (!ready) return;
    try {
      if (s.patientId) sessionStorage.setItem(KEY, JSON.stringify(s));
      else sessionStorage.removeItem(KEY);
    } catch { /* ignore */ }
  }, [s, ready]);

  // Signing in always starts from a clean slate, so nothing carries over between profiles.
  const login = useCallback((id: string) => setS({ ...EMPTY, patientId: id }), []);
  const logout = useCallback(() => {
    setS(EMPTY);
    try { sessionStorage.removeItem(KEY); } catch { /* ignore */ }
    router.replace("/");
  }, [router]);
  const toggleDevice = useCallback((id: DeviceId) => setS((p) => {
    if (!p.patientId) return p;
    const cur = p.devices[p.patientId] ?? [];
    return { ...p, devices: { ...p.devices, [p.patientId]: cur.includes(id) ? cur.filter((d) => d !== id) : [...cur, id] } };
  }), []);
  const setSearch = useCallback((query: string, topic: string | null) => setS((p) => ({ ...p, query, topic })), []);
  const toggleExpanded = useCallback((paperId: number) => setS((p) => ({ ...p, expanded: p.expanded.includes(paperId) ? p.expanded.filter((x) => x !== paperId) : [...p.expanded, paperId] })), []);

  const value = useMemo<Ctx>(() => ({
    ...s, ready, patient: getPatient(s.patientId), connected: (s.patientId && s.devices[s.patientId]) || [],
    login, logout, toggleDevice, setSearch, toggleExpanded,
  }), [s, ready, login, logout, toggleDevice, setSearch, toggleExpanded]);
  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>;
}

export function useApp() {
  const c = useContext(AppCtx);
  if (!c) throw new Error("useApp outside AppStateProvider");
  return c;
}

/** For screens that need a selected patient: sends the visitor to sign-in otherwise. */
export function useRequirePatient() {
  const app = useApp();
  const router = useRouter();
  useEffect(() => { if (app.ready && !app.patient) router.replace("/"); }, [app.ready, app.patient, router]);
  return app.ready ? app.patient : null;
}
