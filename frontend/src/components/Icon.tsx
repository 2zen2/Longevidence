const PATHS = {
  search: <><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></>,
  arrowLeft: <path d="M19 12H5m6-6-6 6 6 6" />,
  arrowRight: <path d="M5 12h14m-6-6 6 6-6 6" />,
  chevron: <path d="m6 9 6 6 6-6" />,
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  external: <path d="M14 5h5v5m0-5-8 8M18 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h4" />,
  heart: <path d="M12 20.5C6 16.5 3.5 13 3.5 9.5A4.2 4.2 0 0 1 12 7.6a4.2 4.2 0 0 1 8.5 1.9c0 3.5-2.5 7-8.5 11Z" />,
  ring: <><circle cx="12" cy="12" r="7" /><circle cx="12" cy="12" r="3.5" /></>,
  activity: <path d="M3 12h4l3-7 4 14 3-7h4" />,
  watch: <><rect x="7" y="7" width="10" height="10" rx="3" /><path d="M9 7l.7-3h4.6L15 7M9 17l.7 3h4.6l.7-3" /></>,
  band: <><rect x="3" y="9" width="18" height="6" rx="3" /><path d="M9 12h6" /></>,
  phone: <><rect x="7" y="3" width="10" height="18" rx="2.5" /><path d="M11 18h2" /></>,
  user: <><circle cx="12" cy="8.5" r="3.5" /><path d="M5 20c.6-3.6 3.4-5.5 7-5.5s6.4 1.9 7 5.5" /></>,
  note: <path d="M8 4h8l3 3v13H5V4h3Zm0 6h8M8 14h8" />,
} as const;
export type IconName = keyof typeof PATHS;

/** Simple 1.5px line icon. */
export default function Icon({ name, size = 18, className = "" }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden className={className}>
      {PATHS[name]}
    </svg>
  );
}
