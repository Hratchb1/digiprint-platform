# RollCall — Theme Palette Fix (why light/dark looks wrong)

**Diagnosis (15 Aug 2026).** The token migration is correct and the mechanism works (`@layer base` applies `bg-background`/`text-foreground`; `@theme inline` maps tokens; `useTheme` toggles `.dark`). The problem is purely the **token values**: `theme.css` ships the stock shadcn palette (light `--background: #ffffff`, `--card: #ffffff`, `--muted: #ececf0`…), so light mode renders as a generic stark-white theme, not the Figma design.

**Why the Figma prototype looked right:** it *ignored* its own tokens (identical generic values) and hardcoded a warm palette in every component via `theme === 'light' ? 'bg-[#e8e4df]' : 'bg-[#1c1c1e]'`. The designed look lives in those conditionals, not the tokens.

**The fix:** keep the token architecture; set the token *values* in `frontend/src/styles/theme.css` to the Figma palette below (extracted from the prototype's `App.tsx` conditionals). Then every already-migrated page renders the real design in both themes — no prop-drilling, no per-component conditionals.

---

## Palette to set in `theme.css`

Replace the **surface / text / border** values in `:root` (light) and `.dark` (dark). Leave `--primary*`, `--destructive*`, `--ring`, `--chart-*`, `--radius`, and the font-weight vars as they are. Keep **brand orange `#ff6600`** and the **success green** literal in components (they're deliberately theme-constant).

### `:root` (LIGHT — warm cream)
```css
--background: #e8e4df;
--foreground: #1c1c1e;
--card: #f5f1ec;
--card-foreground: #1c1c1e;
--popover: #f5f1ec;
--popover-foreground: #1c1c1e;
--muted: #ddd9d4;
--muted-foreground: #57534e;
--accent: #ede8e2;
--accent-foreground: #1c1c1e;
--border: #d8d4cf;
--input: #f5f1ec;
--input-background: #f5f1ec;
--secondary: #ddd9d4;
--secondary-foreground: #1c1c1e;
--sidebar: #ede8e2;
--sidebar-foreground: #1c1c1e;
--sidebar-accent: #e8e4df;
--sidebar-border: #d8d4cf;
```

### `.dark` (DARK — charcoal)
```css
--background: #1c1c1e;
--foreground: #ffffff;
--card: #2c2c2e;
--card-foreground: #ffffff;
--popover: #2c2c2e;
--popover-foreground: #ffffff;
--muted: #3a3a3c;
--muted-foreground: #9ca3af;
--accent: #3a3a3c;
--accent-foreground: #ffffff;
--border: #3a3a3c;
--input: #2c2c2e;
--input-background: #2c2c2e;
--secondary: #3a3a3c;
--secondary-foreground: #ffffff;
--sidebar: #202022;
--sidebar-foreground: #ffffff;
--sidebar-accent: #3a3a3c;
--sidebar-border: #3a3a3c;
```

*(Palette source, prototype `App.tsx`: light bg `#e8e4df`, card `#f5f1ec`, border `#d8d4cf`, chip `#ddd9d4`; dark bg `#1c1c1e`, card `#2c2c2e`, border `#3a3a3c`, muted text gray-400.)*

---

## Apply + verify
1. Edit only the token values above in `theme.css` (two blocks). No component changes needed — the migrated IntakePage already consumes these tokens.
2. Re-open the **Intake gate** in both themes: light should now be warm cream (`#e8e4df` bg, `#f5f1ec` cards), dark unchanged/charcoal. Text legible in both; brand orange + success green constant.
3. Show Hratch the updated light/dark Intake before continuing the Part 1 rollout to the other pages.

## Note
Any spot that still looks off after this is a page still using a **hardcoded** colour instead of a token (i.e. not yet migrated) — fix by swapping it to the matching token class, not by changing the palette.
