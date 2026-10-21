"use client";

import Link from "next/link";
import { initials } from "@/data/patients";
import { useApp } from "./AppState";
import Icon from "./Icon";

export default function Header() {
  const { patient, connected, logout } = useApp();
  return (
    <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5 sm:px-8">
      <Link href={patient ? "/search" : "/"} className="text-[15px] font-semibold tracking-tight text-primary">Longevidence</Link>
      {patient && (
        <nav className="flex items-center gap-1 text-sm" aria-label="Account">
          <Link href="/devices" className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-muted transition-colors hover:bg-tint hover:text-primary">
            <Icon name="activity" size={16} /><span className="hidden sm:inline">{connected.length ? `${connected.length} connected` : "Devices"}</span>
          </Link>
          <Link href="/profile" aria-label="Health profile" className="ml-1 flex min-w-0 items-center gap-2 rounded-full py-1 pl-1 pr-3 transition-colors hover:bg-tint hover:text-primary">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-[11px] font-medium text-white" aria-hidden>{initials(patient.name)}</span>
            <span className="max-w-[7rem] truncate sm:max-w-[12rem]">{patient.name}</span>
          </Link>
          <button onClick={logout} className="shrink-0 whitespace-nowrap rounded-full border border-line bg-surface px-3 py-1.5 transition-colors hover:border-primary hover:text-primary">Log out</button>
        </nav>
      )}
    </header>
  );
}
