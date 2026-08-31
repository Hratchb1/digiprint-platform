# RollCall — UX Polish Brief: Theme Migration + Intake Refinements

**Prepared 15 Aug 2026.** Scope decided with Hratch. Real backend entry point: `app/main.py`. Frontend is Vite + React + Tailwind **v4**. Standing prefs: full-file replacements, incremental, dev-server verify, show one screen before rolling out.

**In scope:** (1) make light/dark actually work across all pages; (2) three intake refinements. **Out of scope:** border scans (next task), multi-store rollout (Bondi-only for now).

**Important — most of the intake is already built.** The rapid-entry loop (`resetForNext()` after each save returns to a focused order-number input), the right-side **Session Log** panel (`sessionLog` / `logBooking`), one-viewport layout, and Enter-to-book (Enter on an empty twin field books + resets) all already exist in `IntakePage.tsx`. This brief refines them; it does not rebuild them.

---

## Part 1 — Light/Dark theme migration (all pages)

### Key fact: the token system already exists
`src/styles/theme.css` defines a full CSS-variable palette for light (`:root`) and dark (`.dark`), and maps them to Tailwind color utilities via `@theme inline` (Tailwind v4). `useTheme` (`src/hooks/useTheme.ts`) toggles the `.dark` class on `<html>` and persists to `localStorage`. So the toggle already works mechanically — light mode looks unchanged only because the pages **hardcode dark colours** instead of using the tokens.

**The job is a migration, not a theming build:** replace hardcoded neutrals with the semantic token classes that already exist, so they respond to the toggle.

### Two forms of hardcoding to replace
1. **Literal Tailwind classes:** `text-white`, `text-gray-300/400/500/600`, `bg-gray-700`, `border-[#2a2a2a]`, `border-[#1e1e1e]`, `border-[#222222]`, `bg-[#111]`, etc.
2. **Inline style hexes:** `style={{ backgroundColor: "#111111" }}`, `"#0f0f0f"`, `"#1a1200"`, etc. Convert these to token **classNames** (preferred) — e.g. `className="bg-card"` — rather than leaving inline hexes.

### Mapping (hardcoded → semantic token class)
| Hardcoded | Use |
|---|---|
| page bg `#111` / `#0f0f0f` | `bg-background` |
| card / panel surfaces `#111`, `#1a1a1a` | `bg-card` |
| session-log aside `#0f0f0f` | `bg-sidebar` (or `bg-card`) |
| primary text `text-white` | `text-foreground` |
| secondary text `text-gray-400/500/600` | `text-muted-foreground` |
| borders `border-[#2a2a2a] / [#1e1e1e] / [#222]` | `border-border` |
| input background `#111` | `bg-input-background` / `bg-input` |
| neutral chips `bg-gray-700` | `bg-secondary` or `bg-muted` (+ `text-secondary-foreground`) |
| red errors / destructive | `text-destructive`, `bg-destructive/10` |

### Brand orange `#ff6600`
This is the **brand accent** and is deliberately **not** a neutral token (the `--primary` token is navy/near-white, not orange). Keep orange **constant across both themes** — either leave the literal `#ff6600`, or add a `--brand` variable that's identical in `:root` and `.dark`. **Do not** map orange onto `--primary`. Same for the green "booked" confirmation — keep it a constant success colour (or add a `--success` token) so it reads on both themes.

### Approach (approval gate)
1. Migrate **IntakePage.tsx first**, fully — both the flow and the session log.
2. **Show Hratch that one page in both light and dark before rolling out.** This is the gate.
3. Then migrate the rest: DashboardPage, OrdersPage, OrderDetailPage, LoginPage, `components/layout/Layout.tsx` + Sidebar, and shared components (StatusPill, TwinCheckBadge, MetricCard, AlertItem, ProntoOrderSummary, modals/trays).
4. Confirm the theme toggle control itself is present and wired (it uses `useTheme`); if it was hidden because it did nothing, re-expose it once the migration lands.

### Verify
Toggle light/dark on **every** page: text stays readable, surfaces and borders invert correctly, no white-on-white or black-on-black, brand orange + success green consistent across both. Refresh to confirm the `localStorage` preference persists.

---

## Part 2 — Intake refinements (`frontend/src/pages/IntakePage.tsx`)

### 2a. Show twin checks in the Session Log
`LastBooked` (line 59) stores `orderNum, customerName, rollCount, action, manual` — **no twins**. 
- Add `twins: string[]` to `LastBooked`.
- Populate it in all four `logBooking({...})` calls (≈ lines 441, 464, 493, 514) from `validTwins.map(t => t.twin)`.
- In the session-log panel render (≈ line 986, under the roll-count line), show the twins compactly: a **range** when contiguous (`0042–0044`), otherwise a wrapped list (`0042 · 0047 · 0051`), truncated with `+N` if long. Monospace, muted-foreground.

### 2b. Fewer steps — collapse the Pronto confirm step
Today: lookup → **confirm** (`ProntoOrderSummary` with a "Confirm & enter twins" button → `setStep("twins")`) → twins. That's an extra click on every order.
- After a successful **Pronto** lookup, render the order summary **and** the twin-entry controls on the same screen — no separate Confirm click. The summary collapses to a compact header (customer, order #, service-type selector) sitting above the twin inputs, with the twin field auto-focused.
- Keep the service-type selector reachable in that compact header.
- The **manual-entry** path keeps its confirm step (the user is typing customer details there, so a review step is appropriate).

### 2c. Tighten layout / one viewport
- Compress vertical spacing so lookup + summary + twin entry fit without page scrolling at common shop resolutions (e.g. 1366×768 and up).
- Keep the twin-pills container scrolling internally (`max-h-24 overflow-y-auto`, line 917) rather than growing the page.
- The right-side Session Log should stay visible at all times; only the left flow column scrolls internally if content overflows.

### Verify (Part 2)
- Book an order → the session-log entry shows the actual twin numbers.
- Pronto lookup → twin entry appears immediately with no separate confirm click; field auto-focused; rapid-entry loop still returns to the next order number after booking.
- Manual entry still has its confirm step.
- No page scrolling during normal single/range booking; session log always visible.

---

## Ship order
Part 1 IntakePage migration → **show Hratch (light+dark)** → rest of Part 1 → Part 2a → 2b → 2c. Separate logical commits; dev-server verify each. Bondi-only — no multi-store concerns.

## Out of scope (do not touch)
- Border-scan processing (next task).
- Multi-store rollout / other stores' config.
- Backend logic — this is a frontend/UX pass (2a adds a field to a frontend interface only; no API change).
