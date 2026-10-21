import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      boxShadow: { field: "0 1px 2px color-mix(in srgb, var(--ink) 4%, transparent)" },
      colors: {
        bg: "var(--bg)", surface: "var(--surface)", primary: "var(--primary)", accent: "var(--accent)", ink: "var(--ink)",
        muted: "var(--muted)", line: "var(--line)", tint: "var(--tint)", "tint-strong": "var(--tint-strong)", ring: "var(--ring)", "ink-soft": "var(--ink-soft)", "primary-soft": "var(--primary-soft)",
      },
      fontFamily: { sans: ["ui-sans-serif", "-apple-system", "BlinkMacSystemFont", "Inter", "Segoe UI", "system-ui", "sans-serif"] },
    },
  },
  plugins: [],
} satisfies Config;
