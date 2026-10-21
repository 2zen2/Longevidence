"use client";

import type { ReactNode } from "react";
import { useRequirePatient } from "./AppState";

/** Server pages wrap their content here so signed-out visitors are sent to the sign-in screen. */
export default function PaperGate({ children }: { children: ReactNode }) {
  const patient = useRequirePatient();
  return patient ? <>{children}</> : null;
}
