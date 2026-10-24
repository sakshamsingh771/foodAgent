import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}", "./providers/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["var(--font-body)", "system-ui", "sans-serif"], display: ["var(--font-display)", "system-ui", "sans-serif"] },
      colors: {
        bg: "hsl(var(--bg))", surface: "hsl(var(--surface))", subtle: "hsl(var(--subtle))", border: "hsl(var(--border))",
        fg: "hsl(var(--fg))", muted: "hsl(var(--muted))", brand: "hsl(var(--brand))", "brand-fg": "hsl(var(--brand-fg))",
        safe: "hsl(var(--safe))", warn: "hsl(var(--warn))", danger: "hsl(var(--danger))", info: "hsl(var(--info))",
      },
      borderRadius: { lg: "0.625rem", md: "0.5rem", sm: "0.375rem" },
      boxShadow: { card: "0 1px 2px hsl(var(--shadow) / 0.06)", pop: "0 8px 24px hsl(var(--shadow) / 0.14)" },
    },
  },
  plugins: [],
};
export default config;
