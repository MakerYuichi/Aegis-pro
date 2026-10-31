# Requirements — AEGIS PRO v2.0 Landing Page Redesign

## Summary

Redesign the `/v2` landing page so the demo investigation is the hero: visible on first load, playing automatically within seconds. Fix nine concrete problems in the current implementation — callout anchoring, missing fix diff, emoji controls, Monaco version mismatch, fake chain data, internal-facing CTA copy, log-style narration, flat event pacing, and generic visual design — without touching any other route or the backend.

**Assumptions:**
- "Auto-start" means: trigger playback when the demo section enters the viewport via IntersectionObserver, not on page load. If the user has `prefers-reduced-motion` enabled, the observer is not set up at all; a manual Play button is shown unconditionally instead.
- "Verified fix" moment is defined as: `fix.verified` event fires AND `passed: true`. If `passed` is false the diff view should show a red failure state instead (out of scope for the demo JSON which always passes, but the component must accept both paths).
- "No fake data" means: no hardcoded logos, testimonials, or metrics that are not sourced from the real codebase or the real incident. The "799 tests · 6 pipeline stages" stat in `EverythingElse.tsx` is from a real build and may stay.
- The `WhatItIs` section and `EverythingElse` section are removed; below the demo only two sections remain: the verifier flow (four steps) and the "About this demo" note.
- The existing `/demo` route and all files outside `src/v2/` (except `tailwind.config.js` and `index.html`) are not modified.

---

## User Stories

**US-1 — First impression**
As a visitor landing on `/v2`, I want to see the investigation already running in the editor within the first viewport, so I immediately understand what the product does without scrolling.

**US-2 — Callout anchoring**
As a visitor watching the demo, I want each callout to appear next to the code line it describes (with a visible connector from the gutter), so I can see exactly what the agent is pointing at.

**US-3 — Fix payoff**
As a visitor, I want to see a proper before/after diff view when the fix is proposed and verified — with red removed lines, green added lines, and a "Probe failed before, passed after" confirmation — so the fix moment feels significant.

**US-4 — Playback controls**
As a visitor, I want clear, accessible playback controls with labeled icons (not emoji), so I can step through the investigation at my own pace.

**US-5 — Honest chain panel**
As a visitor, I want the invocation chain to show only the real single-file link, not placeholder boxes labeled "(example)", so I can trust what I'm seeing.

**US-6 — Relevant CTA**
As a visitor who has watched the demo, I want the call-to-action to tell me what AEGIS PRO actually does and offer two specific next steps (try the live v1 demo, view the GitHub repo), so I know where to go next.

**US-7 — Natural narration**
As a visitor, I want the narration strip to read as a colleague thinking aloud in first person, not as a numbered log, so I feel the agent has a voice.

**US-8 — Varied pacing**
As a visitor, I want quick events (file read, symbol found) to feel fast, and slow events (running a probe, verifying a fix) to feel deliberate, so the pacing reflects what's actually happening.

**US-9 — Reduced motion**
As a visitor who has enabled `prefers-reduced-motion`, I want the demo to not auto-play — instead showing a manual Play button — so the page respects my system accessibility setting.

**US-10 — Mobile layout**
As a visitor on a 390px-wide screen, I want the chain panel to collapse below the editor and the narration strip to remain visible, so the demo is usable on mobile.

**US-11 — Keyboard navigation**
As a keyboard user, I want to control playback with Space, ←, →, and Esc, and see a visible focus ring on all interactive elements, so I can use the page without a mouse.

**US-12 — Screen reader narration**
As a screen reader user, I want each new narration line announced automatically, so I can follow the investigation aurally.

---

## Functional Requirements

### FR-1: Hero layout
- FR-1.1 The demo editor (`V2DemoSection`) must be visible within the first viewport at 1440px wide desktop without scrolling.
- FR-1.2 The page headline must appear beside or above the editor, not as a full-screen splash that pushes the demo below the fold.
- FR-1.3 The `Hero` section must be removed or collapsed to a brief headline+subhead that does not consume a full viewport height.

### FR-2: Viewport-triggered auto-play
- FR-2.1 An `IntersectionObserver` must watch the demo section. When `intersectionRatio >= 0.3`, playback starts automatically.
- FR-2.2 The observer must fire at most once per page load (disconnect after first trigger).
- FR-2.3 When `prefers-reduced-motion: reduce` is active, the `IntersectionObserver` must NOT be created; auto-play must NOT trigger; a manual Play button must be shown unconditionally in the hero column.

### FR-3: Custom code view (replaces Monaco)
- FR-3.1 `EditorCanvas` must be replaced with a custom `CodeView` component that renders the Python source as tokenised lines with line numbers and a gutter column.
- FR-3.2 The `monaco-editor` dynamic import must be removed; the `MonacoEnvironment` CDN stub must be removed.
- FR-3.3 Each rendered line must be a DOM element addressable by `data-line` attribute (e.g. `data-line="116"`).
- FR-3.4 The component must syntax-highlight Python tokens using a regex tokeniser (strings, keywords, comments, numbers, operators) sufficient for the 120-line excerpt.
- FR-3.5 The component must accept a `highlightLine` prop and render that line with an amber background.
- FR-3.6 The component must accept a `gutterState` prop (`'none' | 'amber' | 'green'`) and render the appropriate gutter icon on `highlightLine`.
- FR-3.7 The active highlighted line must scroll into view when `highlightLine` changes.

### FR-4: Callout anchoring
- FR-4.1 Each callout must be rendered at a vertical position matching its target line's Y offset in the code view, derived from `lineRef.getBoundingClientRect()` or a `lineHeight × lineNumber` calculation.
- FR-4.2 A connector line or SVG arrow must run from the gutter to the callout card. The connector must start at `left: 3rem` (48px — the right edge of the `w-12` gutter) and end at the callout card's left edge.
- FR-4.3 Callouts must not overlap each other; if two callouts target the same line or adjacent lines, they must stack with a minimum gap of 8px.
- FR-4.4 Callouts must be positioned absolutely within the editor container, not in a separate column.

### FR-5: DiffView component
- FR-5.1 A new `DiffView` component must render when the current event is `fix.proposed`, `fix.verified`, or the `playbackState` is `awaiting-approval | applying | verified`.
- FR-5.2 DiffView must show: file path header, removed line(s) with red background and a `−` prefix, added line(s) with green background and a `+` prefix.
- FR-5.3 When `playbackState === 'fix.verified' && passed === true`, DiffView must display a green "Probe failed before, passed after" banner below the diff.
- FR-5.4 When `playbackState === 'awaiting-approval'`, DiffView must show "Apply fix" and "Dismiss" buttons with accessible labels.
- FR-5.5 DiffView must be rendered inside the editor panel area (not as a callout overlay), replacing the current inline diff overlay in `EditorCanvas`.

### FR-6: Playback controls
- FR-6.1 All emoji/text glyphs (`⏮`, `▶`, `◀`, `⏸`) must be replaced with lucide-react icons.
- FR-6.2 Every button must have an explicit `aria-label` attribute.
- FR-6.3 Every interactive element must display a visible focus ring (2px, not hidden with `outline: none` without a replacement).
- FR-6.4 The `PlaybackControls` component in `V2DemoSection` inline bar must be replaced with the updated `PlaybackControls` component (remove the `sr-only` wrapper hack).

### FR-7: Chain panel
- FR-7.1 The two fake `(example)` chain boxes in `ChainPanel` must be removed.
- FR-7.2 The single real chain box (`requests/status_codes.py:116 · __doc__ · crash site`) must display, animated (border pulse) only after `chain.resolved` fires.
- FR-7.3 Before `chain.resolved` fires, the chain panel must show a "Waiting…" placeholder or be empty.
- FR-7.4 The panel header must read "Invocation chain · single-file finding" (not "Single-file finding. Boxes 2–3 are synthetic examples…").
- FR-7.5 The legend at the bottom acknowledging fake data must be removed.

### FR-8: CTA rewrite
- FR-8.1 The CTA section headline and body must not use internal roadmap language ("the future of the pipeline you already have", "the body").
- FR-8.2 The CTA must contain: (a) a brief description of what AEGIS PRO does in visitor-facing terms; (b) a link to `/demo` labeled "Try the live v1 demo"; (c) a link to `https://github.com/MakerYuichi/Aegis-pro` labeled "View on GitHub".
- FR-8.3 A "Watch it again" button must appear in the CTA section. It must call `restart()` and scroll back to the demo section (not to the top of the page). `Cta.tsx` receives an `onWatchAgain: () => void` prop from `LandingPage.tsx` which calls `restart()` and then `demoRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })`.

### FR-9: Narration rewrite
- FR-9.1 Narration lines must not have numeric prefixes.
- FR-9.2 Narration must NOT use a monospace font and must NOT render line numbers. The narration should use the UI font (Inter).
- FR-9.3 Each line must be first-person present tense, reading as a colleague thinking aloud (see approved narration strings in the design doc).
- FR-9.4 The narration container must have `aria-live="polite"` and `aria-label="Investigation narration"`.
- FR-9.5 Each new line must be appended as new content (not replacing previous lines), so screen readers announce only the new line.

### FR-10: Event pacing
- FR-10.1 `usePlayback` must use per-event-kind durations, not a flat 1500ms.
- FR-10.2 Required durations: `file.opened` → 800ms, `symbol.located` → 800ms, `investigation.started` → 800ms, `chain.resolved` → 1000ms, `hypothesis.formed` → 1200ms, `bug.confirmed` → 1200ms, `probe.running` → 2500ms, `probe.reproduced` → 2500ms, `fix.proposed` → 1500ms (then pauses for approval — this is the delay spent on the preceding event before `fix.proposed` fires), `fix.verified` → 3000ms, `investigation.complete` → 1500ms.
- FR-10.3 When `prefers-reduced-motion: reduce` is active, `usePlayback` must not use `setTimeout` for auto-advance; it must wait for manual input.

### FR-11: Below-demo sections
- FR-11.1 The `WhatItIs` and `EverythingElse` sections must be replaced with exactly two sections: (a) a 4-step verifier flow (Found → Reproduced → Fixed → Re-run), (b) an "About this demo" note.
- FR-11.2 The "About this demo" note must state it is a recorded replay of a real scan of `psf/requests` and link to `https://github.com/MakerYuichi/Aegis-pro`.
- FR-11.3 No fake logos, testimonials, or metrics may be added. The pipeline stage count and test count may stay if sourced from the real build.

### FR-12: Mobile layout
- FR-12.1 At 390px viewport width, the chain panel must render below the editor in a vertical stack (not beside it).
- FR-12.2 At 390px, the narration strip must remain visible (not hidden or clipped below the fold).
- FR-12.3 The editor code view must be horizontally scrollable (not text-wrapped) at mobile widths.

### FR-13: Color and typography
- FR-13.1 The palette must be defined as 4–6 named hex tokens in `tailwind.config.js` under a new `aegis` namespace.
- FR-13.2 Color usage must be semantic: amber/yellow for suspicion/hypothesis, red for reproduced failure, green for verified. All other UI must use neutral tokens.
- FR-13.3 The page must not use purple or blue gradient washes, all-caps tracked eyebrow labels, or per-section fade-up animations.
- FR-13.4 One UI typeface and one monospace typeface must be declared in `tailwind.config.js` with `fontFamily` extensions; the choices must be justified in `design.md`.

---

## Non-Functional Requirements

- **NFR-1 Bundle size**: Removing Monaco must reduce the JS bundle by at least 2MB. The final bundle for the `/v2` route must not introduce any new dependency heavier than 50KB gzipped.
- **NFR-2 Build**: `cd frontend && npm run build` must pass with zero TypeScript errors and zero ESLint errors for files under `src/v2/`.
- **NFR-3 No-touch constraint**: Files outside `src/v2/` other than `tailwind.config.js` and `index.html` must not be modified. The `/demo` route and dashboard pages must render without change.
- **NFR-4 WebSocket readiness**: The `V2Event` union in `types.ts` and the event-driven architecture in `usePlayback.ts` must be preserved so a live WebSocket stream can replace `demo-investigation.json` with no UI changes.
- **NFR-5 Performance**: The demo section must reach first meaningful paint within 2 seconds on a simulated 4G connection (no blocking network requests on initial load; all assets either bundled or from system fonts).

---

## Acceptance Criteria

**AC-1** On a 1440px desktop, opening `/v2` shows the editor with the Python source visible without scrolling. *(FR-1.1)*

**AC-2** On a 1440px desktop, the first event fires within 5 seconds of the demo section entering the viewport (measured from `intersectionRatio >= 0.3`). *(FR-2.1)*

**AC-3** When `prefers-reduced-motion: reduce` is active (set via OS or DevTools → Rendering → Emulate CSS media features; reload), the demo does NOT auto-play on viewport entry; a "Play" button is visible and clicking it starts playback. *(FR-2.3, FR-10.3)*

**AC-4** Each callout card is visually connected to its target code line by an arrow or connector line; no callout floats in a column detached from the code. *(FR-4.1, FR-4.2)*

**AC-5** When `fix.proposed` fires, a diff panel appears showing a red `−` line and a green `+` line for the exact change at line 116. *(FR-5.1, FR-5.2)*

**AC-6** When `fix.verified` fires with `passed: true`, a green banner reading "Probe failed before, passed after" appears in the diff panel. *(FR-5.3)*

**AC-7** All playback buttons render lucide-react icons and have an `aria-label` attribute verifiable in the DOM. *(FR-6.1, FR-6.2)*

**AC-8** Pressing Tab through the demo section highlights each control with a visible focus ring (at least 2px outline, not `outline: none` without replacement). *(FR-6.3)*

**AC-9** `ChainPanel` renders exactly one chain box after `chain.resolved` fires; no boxes labeled "(example)" appear at any point. *(FR-7.1, FR-7.2)*

**AC-10** The CTA section contains a link with `href="/demo"` and a link with `href="https://github.com/MakerYuichi/Aegis-pro"`. *(FR-8.2)*

**AC-11** Narration lines have no numeric prefix; each line is first-person present tense; the container has `aria-live="polite"`. *(FR-9.1, FR-9.3, FR-9.4)*

**AC-12** `probe.running` and `probe.reproduced` events each display for at least 2000ms before advancing (verify in `usePlayback` unit test or by manual timing). *(FR-10.1, FR-10.2)*

**AC-13** `fix.verified` displays for at least 2500ms before the investigation completes. *(FR-10.2)*

**AC-14** At 390px viewport width, the chain panel appears below the editor (not to its right); the narration strip is visible. *(FR-12.1, FR-12.2)*

**AC-15** The `tailwind.config.js` contains an `aegis` color namespace with at least 4 named hex tokens. *(FR-13.1)*

**AC-16** `npm run build` from `frontend/` exits with code 0 and no TypeScript or ESLint errors. *(NFR-2)*

**AC-17** The `monaco-editor` dynamic import is absent from all files under `src/v2/`; no CDN URLs for `monaco-editor` appear in any source file under `src/v2/`. *(FR-3.2)*

**AC-18** No text on the page reads as internal roadmap language ("the future of the pipeline you already have", "the body", "ambient agent" used as a tagline). *(FR-8.1)*

**AC-19** The narration container has `aria-live="polite"` verifiable in the rendered DOM. *(FR-9.4)*

**AC-20** Pressing Space toggles play/pause; pressing Esc resets to idle; pressing → advances one event; pressing ← steps back one event — all while the demo section has focus. *(FR-6, keyboard)*

---

## Out of Scope

- Backend changes of any kind.
- The `/demo` route (v1 demo) and dashboard pages.
- Live WebSocket integration (architecture must support it, but wiring is not required now).
- The `fix.proposed` "Dismiss" path beyond what already exists in `usePlayback` (rejected state renders a dismissal message; no further UI is required).
- Analytics or event tracking.
- Internationalisation.
- Dark/light mode toggle for the `/v2` page (it is always dark).
- Full WCAG 2.1 AA audit (key a11y features are required but a full audit requires manual testing with assistive technologies).
- Any changes to `main` branch files.

---

## Review Response Notes

**Finding 04 (HIGH — fix.proposed duration):** FR-10.2 now clarifies that the `fix.proposed` duration (1500ms) is the delay spent on the preceding event before `fix.proposed` fires. `fix.proposed` itself transitions to `awaiting-approval`. This is consistent with adding `'fix.proposed': 1500` to `EVENT_DURATIONS` (see tasks.md TASK 02 update).

**Finding 08 (MEDIUM — FR-9.2 monospace contradiction):** FR-9.2 corrected to state narration must NOT use monospace and must use Inter. This aligns with tasks.md TASK 09 and the original user request intent.

**Finding 09 (MEDIUM — "Watch it again" gap):** FR-8.3 now specifies that the "Watch it again" button stays in `Cta.tsx` with an `onWatchAgain` prop from `LandingPage` that calls both `restart()` and `demoRef.current?.scrollIntoView(...)`. This satisfies the original requirement and closes the gap left by TASK 11's removal.

**Finding 12 (MEDIUM — IntersectionObserver reduced-motion):** FR-2.3 updated to align with tasks.md: when `prefers-reduced-motion` is active, the observer is never created and the Play button is shown unconditionally.
