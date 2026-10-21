import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import Icon from "./Icon";

const BTN = "inline-flex items-center justify-center gap-2 rounded-full px-6 py-2.5 text-sm font-medium transition-colors disabled:opacity-50";
export const hoverPrimary = "hover:bg-[color-mix(in_srgb,var(--primary)_88%,white)]";
export const btnPrimary = `${BTN} bg-primary text-white ${hoverPrimary}`;
export const btnQuiet = "text-sm text-muted transition-colors hover:text-primary";

export function Button({ className = "", ...p }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...p} className={`${btnPrimary} ${className}`} />;
}

export function BackLink({ href, children }: { href: string; children: ReactNode }) {
  return <Link href={href} className={`${btnQuiet} inline-flex items-center gap-1.5`}><Icon name="arrowLeft" size={16} />{children}</Link>;
}

export function Label({ children }: { children: ReactNode }) {
  return <h2 className="text-xs font-medium uppercase tracking-[0.08em] text-muted">{children}</h2>;
}
