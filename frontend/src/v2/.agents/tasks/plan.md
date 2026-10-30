# Implementation Plan — AEGIS PRO v2.0 Demo Landing Page

## Codebase Findings

**@monaco-editor/react**: NOT in package.json. Confirmed: only raw `monaco-editor` will be installed via `cd /Users/sanchiagarwal/VS_Code/aegis-pro/frontend && npm install monaco-editor`. monaco-editor is not yet installed (checked node_modules: absent).

**App.tsx insertion point**: The `<Routes>` block ends with `<Route path="*" element={<Navigate to="/" replace />} />` on the last line before `</Routes>`. The new `/v2` route goes immediately before the wildcard `*` route. Two lines only: one import at the top, one Route inside the Routes block.

**Tailwind v3**: Confirmed. `tailwindcss: "^3.4.0"` in package.json. Content paths cover `./src/**/*.{js,ts,jsx,tsx}` — the new `src/v2/**` files are automatically included. Dark mode is `class`-based. Custom colors use tokens: `dark-bg`, `dark-card`, `dark-border`, `dark-text`, `dark-muted`, `brand-primary`, `brand-success`, `brand-warning`, `brand-danger`, `severity-critical`. These are all available to v2 code.

**vite.config.ts**: Minimal — only `@vitejs/plugin-react`. No aliases, no special worker config. Monaco worker bundling therefore requires a `MonacoEnvironment` stub in `EditorCanvas.tsx` to point workers at the CDN or no-op them, avoiding Vite worker-import errors entirely.

**tsconfig.app.json**: `"moduleResolution": "bundler"`, `"verbatimModuleSyntax": true`, `"noUnusedLocals": true`, `"noUnusedParameters": true`. Strict-ish but not full `strict: true`. Implications: every import must be used, every parameter used, type-only imports need `import type`.

**TypeScript version**: `~6.0.2` — supports all modern patterns.

**React version**: `^19.2.8`. `useRef`, `useEffect`, `useState`, `useCallback` are all available.

**framer-motion**: `^13.1.1` in dependencies — available for fade transitions on narration lines.

**lucide-react**: `^1.38.0` in dependencies — available for Play/Pause/RotateCcw/ChevronRight/ChevronLeft icons.

**Existing page pattern**: `DemoPage.tsx` exports a named function `DemoPage`. The new `LandingPage` will be a default export (required by the route import pattern: `import LandingPage from './v2/landing/LandingPage'`).

---

## Architecture Decisions

**Monaco worker strategy**: Use a `MonacoEnvironment` global with `getWorkerUrl` returning empty blob URLs (no real workers). This avoids all Vite bundler worker-import issues without needing any Vite plugin or CDN. Monaco degrades gracefully — syntax highlighting for Python is not needed for this read-only demo (the editor just shows text). The stub is set once in `EditorCanvas.tsx` before the `monaco.editor.create()` call. Decision: **blob stub, no plugin**, because the Vite config has no existing worker handling and adding a plugin would require touching `vite.config.ts` which is outside the constraint scope.

**Component data flow**: `usePlayback` is the single source of truth. It holds `currentIndex` (which event is "active") and exposes `{ events, currentIndex, isPlaying, play, pause, restart, step, stepBack }`. Every visual component receives only what it needs as props — `EditorCanvas` gets the current event to know which line to decorate, `NarrationPanel` gets all events up to `currentIndex`, `ChainPanel` gets the `chain.resolved` event if seen, `PlaybackControls` gets the playback control functions and `isPlaying`.

**Auto-play on CTA scroll**: The Hero "▶ Watch it work" button calls `scrollIntoView` on the demo section ref AND calls `play()` from a lifted `usePlayback` instance. `LandingPage.tsx` owns both the ref and the `usePlayback` instance, passing `play` down to `Hero` as a prop and the playback state down to `V2DemoSection`.

**Callout rendering**: Callouts are rendered inside `EditorCanvas.tsx` as absolutely-positioned DOM elements overlaid on the Monaco container div, not as Monaco widgets. Monaco's `addContentWidget` API requires a DOM node with specific methods; a simpler approach is a `<div>` positioned relative to the editor container at a calculated top offset (`(lineNumber - 1) * lineHeight`). This avoids Monaco widget lifecycle complexity. Multiple callouts from `events[0..currentIndex]` are filtered for callout-eligible event kinds and all rendered simultaneously.

**TypeScript strict compliance**: All files use explicit return types on exported functions/hooks. No `any` unless Monaco's untyped API forces it (cast to `unknown` first). All event discriminant unions use exhaustive narrowing with `kind` checks.

---

## Implementation Plan

- [ ] 1. Install monaco-editor dependency.
      Run `npm install monaco-editor` from the frontend directory. This adds `monaco-editor` to `node_modules` without modifying `package.json` devDependencies (it goes to dependencies since no `--save-dev` flag). Actually: do add it properly with `--save` to keep package.json accurate.
      Files: `frontend/package.json` (updated by npm), `frontend/node_modules/monaco-editor/` (created)
      Verify: `ls /Users/sanchiagarwal/VS_Code/aegis-pro/frontend/node_modules/monaco-editor/package.json` — file exists. Then `cd /Users/sanchiagarwal/VS_Code/aegis-pro/frontend && npm run build` completes without error (or `tsc -b` passes).

- [ ] 2. Create `frontend/src/v2/types.ts` — the complete V2Event discriminated union and ChainLink type.
      Export `ChainLink` and `V2Event` exactly as specified. Also export a `PlaybackState` interface used by `usePlayback` so downstream components can import the type without circular deps.
      Files: `frontend/src/v2/types.ts`
      Verify: `cd /Users/sanchiagarwal/VS_Code/aegis-pro/frontend && npx tsc -p tsconfig.app.json --noEmit` — no errors in types.ts.

- [ ] 3. Create `frontend/src/v2/demo/demo-investigation.json` — the recorded investigation data.
      This is the exact JSON array from the task specification for INC-20261029-A42D5F. All 11 events in order from `investigation.started` through `investigation.complete`.
      Files: `frontend/src/v2/demo/demo-investigation.json`
      Verify: `node -e "const d = require('./src/v2/demo/demo-investigation.json'); console.log(d.length)"` from `frontend/` outputs `11`.

- [ ] 4. Create `frontend/src/v2/adapters/historyToEvents.ts` — the adapter that converts raw JSON into typed `V2Event[]`.
      Exports one function: `historyToEvents(raw: unknown[]): V2Event[]`. Validates each element has a `kind` field matching a known V2Event kind; throws or skips invalid entries. Import `V2Event` from `../types`.
      Files: `frontend/src/v2/adapters/historyToEvents.ts`
      Verify: `npx tsc -p tsconfig.app.json --noEmit` — no errors.

- [ ] 5. Create `frontend/src/v2/demo/usePlayback.ts` — the playback state hook.
      ```
      Interface exported: PlaybackHandle {
        events: V2Event[];
        currentIndex: number;  // -1 = not started, 0..n-1 = active event index
        isPlaying: boolean;
        play(): void;
        pause(): void;
        restart(): void;
        step(): void;
        stepBack(): void;
      }
      ```
      Implementation: loads `demo-investigation.json` via static import, runs it through `historyToEvents`. Uses `useRef` for the interval timer (1200ms per event when playing). `play()` advances `currentIndex` every 1200ms via `setInterval`; stops at the last event. `restart()` resets `currentIndex` to -1 and stops the interval. Keyboard listeners (`keydown`) for Space (toggle), Escape (restart), ArrowRight (step), ArrowLeft (stepBack) are set up in this hook via `useEffect` with proper cleanup. Returns `PlaybackHandle`.
      Files: `frontend/src/v2/demo/usePlayback.ts`
      Verify: `npx tsc -p tsconfig.app.json --noEmit` — no errors.

- [ ] 6. Create `frontend/src/v2/demo/EditorCanvas.tsx` — the Monaco read-only editor.
      **Monaco worker stub** (must come before `monaco.editor.create`):
      ```ts
      window.MonacoEnvironment = {
        getWorkerUrl(_moduleId: string, _label: string): string {
          return URL.createObjectURL(new Blob([''], { type: 'application/javascript' }));
        },
      };
      ```
      Props: `{ currentEvent: V2Event | null }`. Uses `useRef<HTMLDivElement>` for the container. In `useEffect` (runs once on mount): imports monaco via `import * as monaco from 'monaco-editor'`, creates a read-only editor with the Python source text (hardcoded as a const in the file — the relevant excerpt from `requests/status_codes.py` lines 110-125 plus surrounding context), sets language to `'python'`, theme to `'vs-dark'`. A second `useEffect` (dep: `currentEvent`) applies/clears decorations: when `currentEvent` has a `line` field, scroll to that line and apply a `lineHighlight` decoration class and a gutter arrow decoration using `monaco.editor.instance.deltaDecorations`. Callouts: render `<Callout>` components positioned absolutely over the editor container — one per visible callout event in `events[0..currentIndex]`. Since `EditorCanvas` only knows the `currentEvent`, callout accumulation must be lifted to the parent (`V2DemoSection`) which passes `visibleCalloutEvents: V2Event[]` as a second prop.

      Full props: `{ currentEvent: V2Event | null; visibleCalloutEvents: V2Event[] }`.
      Files: `frontend/src/v2/demo/EditorCanvas.tsx`
      Verify: `npx tsc -p tsconfig.app.json --noEmit` — no errors.

- [ ] 7. Create `frontend/src/v2/demo/Callout.tsx` — the floating callout overlay.
      Props: `{ event: V2Event; lineNumber: number; lineHeight: number; colorClass: string }`. Renders a small card div positioned `top: (lineNumber - 1) * lineHeight` with `left: 60px` (gutter width). Uses `framer-motion` `motion.div` with `initial={{ opacity: 0, x: -8 }}` and `animate={{ opacity: 1, x: 0 }}` over 300ms. Shows observation text (derived from the event's `text` or `error` or `output` field) and a color-coded left border. For `fix.proposed` events: shows a disabled "Apply fix" button. Color mapping: `hypothesis.formed` → amber, `probe.reproduced` → red, `bug.confirmed` → green, `fix.proposed` / `fix.verified` → green, `symbol.located` → blue, default → blue.
      Files: `frontend/src/v2/demo/Callout.tsx`
      Verify: `npx tsc -p tsconfig.app.json --noEmit` — no errors.

- [ ] 8. Create `frontend/src/v2/demo/NarrationPanel.tsx` — the scrolling narration strip.
      Props: `{ events: V2Event[]; currentIndex: number }`. Renders a ~140px fixed-height horizontal-scroll strip. Derives narration lines from `events[0..currentIndex]` using a `kindToNarration` map (one line per event kind — the exact strings from the task spec). Each new line animates in with `framer-motion` `motion.p` fade. Uses `useEffect` to scroll the container to the bottom whenever `currentIndex` changes.
      Narration map (event kind → string):
      - `investigation.started` → "Opening status_codes.py…"
      - `file.opened` → "Reading lines 110-125…"
      - `hypothesis.formed` → "Checking __doc__ type…"
      - `symbol.located` → "Found: __doc__ can be None under -OO…"
      - `chain.resolved` → (skip — no narration line)
      - `probe.running` → "Probing under -OO…"
      - `probe.reproduced` → "Reproduced: TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'"
      - `bug.confirmed` → "Generating fix…"
      - `fix.proposed` → "Verifying against probe…"
      - `fix.verified` → "Fix verified."
      - `investigation.complete` → (skip)
      Files: `frontend/src/v2/demo/NarrationPanel.tsx`
      Verify: `npx tsc -p tsconfig.app.json --noEmit` — no errors.

- [ ] 9. Create `frontend/src/v2/demo/ChainPanel.tsx` — the right sidebar chain visualization.
      Props: `{ currentIndex: number; events: V2Event[] }`. Renders three chain-link boxes connected by vertical lines. Box 1 (REAL): `requests/status_codes.py:116` — `__doc__` — active/pulsing when `currentIndex >= 0`. Box 2 (SYNTHETIC, dimmed): `requests/models.py:128` — labeled "(example)". Box 3 (SYNTHETIC, dimmed): `requests/status_codes.py:116` — labeled "(example)". Panel header: "Invocation Chain" with a subtitle badge "Single-file finding". Active box uses `animate-pulse-slow` (defined in tailwind.config). Dimmed boxes have `opacity-40` and a dashed border. Connecting lines are `<div>` elements with `border-l-2 border-dashed border-dark-border h-6 ml-4`.
      Files: `frontend/src/v2/demo/ChainPanel.tsx`
      Verify: `npx tsc -p tsconfig.app.json --noEmit` — no errors.

- [ ] 10. Create `frontend/src/v2/demo/PlaybackControls.tsx` — the top control bar.
       Props: `{ isPlaying: boolean; currentIndex: number; totalEvents: number; onPlay(): void; onPause(): void; onRestart(): void; onStep(): void; onStepBack(): void }`. Renders a flex row with: RotateCcw button (restart), ChevronLeft button (stepBack), Play/Pause toggle button (shows Pause icon when `isPlaying`, Play icon otherwise), ChevronRight button (step). Plus a progress indicator: `currentIndex + 1 / totalEvents` as a fraction and a `<progress>` bar. Keyboard shortcut hints displayed as small text badges: `[Space]`, `[→]`, `[←]`, `[Esc]`. All buttons use `onClick` handlers from props. No internal state.
       Files: `frontend/src/v2/demo/PlaybackControls.tsx`
       Verify: `npx tsc -p tsconfig.app.json --noEmit` — no errors.

- [ ] 11. Create `frontend/src/v2/demo/V2DemoSection.tsx` — the demo section shell.
       Props: `{ playback: PlaybackHandle; sectionRef: React.RefObject<HTMLElement> }`. This component owns the layout:
       - `<section ref={sectionRef}>` full viewport height, dark background (`bg-dark-bg`)
       - `<PlaybackControls .../>` wired to `playback.*`
       - Main split: `flex` row, 65% left / 35% right
         - Left: `<EditorCanvas currentEvent={playback.events[playback.currentIndex] ?? null} visibleCalloutEvents={visibleCalloutEvents} />`
         - Right: `<ChainPanel currentIndex={playback.currentIndex} events={playback.events} />`
       - Bottom strip: `<NarrationPanel events={playback.events} currentIndex={playback.currentIndex} />`
       
       `visibleCalloutEvents` is derived by filtering `playback.events.slice(0, playback.currentIndex + 1)` for kinds that produce callouts: `hypothesis.formed`, `symbol.located`, `probe.reproduced`, `bug.confirmed`, `fix.proposed`, `fix.verified`.
       Files: `frontend/src/v2/demo/V2DemoSection.tsx`
       Verify: `npx tsc -p tsconfig.app.json --noEmit` — no errors.

- [ ] 12. Create `frontend/src/v2/landing/Hero.tsx` — the hero section.
       Props: `{ onWatchClick(): void }`. Full-viewport dark section. Contents centered:
       - Headline: "Watch the bug get found." — large, bold, white.
       - Subheadline: "AEGIS PRO investigates your code, live. Every arrow, every callout, every fix — visible." — muted, max-w-xl.
       - CTA button: "▶ Watch it work" — calls `onWatchClick()` on click.
       No internal state. No hooks.
       Files: `frontend/src/v2/landing/Hero.tsx`
       Verify: `npx tsc -p tsconfig.app.json --noEmit` — no errors.

- [ ] 13. Create `frontend/src/v2/landing/Cta.tsx` — the bottom CTA section.
       No props. Full-viewport dark section. Contents centered:
       - Headline: "This is v2.0. The future of the pipeline you already have."
       - Paragraph: explains v1.0 shipped and v2.0 is the next phase — ambient agent, live investigation, visible reasoning.
       - Button: "Back to the top" — calls `window.scrollTo({ top: 0, behavior: 'smooth' })` on click.
       Files: `frontend/src/v2/landing/Cta.tsx`
       Verify: `npx tsc -p tsconfig.app.json --noEmit` — no errors.

- [ ] 14. Create `frontend/src/v2/landing/LandingPage.tsx` — the page root.
       Default export `LandingPage`. This component:
       - Calls `usePlayback()` to get `playback: PlaybackHandle`.
       - Holds `demoRef = useRef<HTMLElement>(null)` for scroll target.
       - `handleWatchClick`: calls `demoRef.current?.scrollIntoView({ behavior: 'smooth' })` then `playback.play()`.
       - Renders three stacked sections:
         1. `<Hero onWatchClick={handleWatchClick} />`
         2. `<V2DemoSection playback={playback} sectionRef={demoRef} />`
         3. `<Cta />`
       - Wraps in a `<div className="bg-dark-bg text-dark-text">` (always dark — this page has its own dark theme independent of the app ThemeProvider).
       Files: `frontend/src/v2/landing/LandingPage.tsx`
       Verify: `npx tsc -p tsconfig.app.json --noEmit` — no errors.

- [ ] 15. Create `frontend/src/v2/index.ts` — the barrel export.
       Exports `LandingPage` as the single public export of the v2 module:
       ```ts
       export { default as LandingPage } from './landing/LandingPage';
       ```
       Files: `frontend/src/v2/index.ts`
       Verify: `npx tsc -p tsconfig.app.json --noEmit` — no errors.

- [ ] 16. Add the route to `frontend/src/App.tsx` — exactly two lines, nothing else changed.
       **Line 1** — import (add after the existing `AdminAuditLogPage` import on line ~21, before the `AdminLayout` import):
       ```ts
       import LandingPage from './v2/landing/LandingPage';
       ```
       **Line 2** — route (add immediately before `<Route path="*" element={<Navigate to="/" replace />} />`):
       ```tsx
       <Route path="/v2" element={<LandingPage />} />
       ```
       No other lines in App.tsx are touched.
       Files: `frontend/src/App.tsx`
       Verify: `cd /Users/sanchiagarwal/VS_Code/aegis-pro/frontend && npm run build` — exits 0 with no TypeScript errors.

---

## Monaco Worker Config Detail

The Vite config has no existing worker plugin. Adding `vite-plugin-monaco-editor` would require modifying `vite.config.ts`. Instead, set a `MonacoEnvironment` global stub in `EditorCanvas.tsx` before any monaco API call:

```ts
// Declare ambient to satisfy TypeScript
declare global {
  interface Window {
    MonacoEnvironment?: {
      getWorkerUrl(moduleId: string, label: string): string;
    };
  }
}

window.MonacoEnvironment = {
  getWorkerUrl(_moduleId: string, _label: string): string {
    // Return a no-op worker blob. Monaco degrades gracefully without real workers.
    return URL.createObjectURL(
      new Blob(['self.onmessage=function(){}'], { type: 'application/javascript' })
    );
  },
};
```

This must be set before `import * as monaco from 'monaco-editor'` is used to call `monaco.editor.create`. Since ESM imports are hoisted, use a dynamic `import()` inside the `useEffect` to ensure the `MonacoEnvironment` assignment runs first:

```ts
useEffect(() => {
  window.MonacoEnvironment = { getWorkerUrl: () => URL.createObjectURL(...) };
  import('monaco-editor').then((monaco) => {
    editorRef.current = monaco.editor.create(containerRef.current!, { ... });
  });
  return () => { editorRef.current?.dispose(); };
}, []);
```

This approach requires no Vite config changes and no extra dependencies.

---

## Python Source Text for EditorCanvas

The editor needs a hardcoded string for `requests/status_codes.py`. Use this excerpt (lines 108-125 of the real file, which establishes context for the `__doc__` concatenation at line 116):

```python
# Excerpt: requests/status_codes.py (lines 108-125)
# Source: INC-20261029-A42D5F recording

_codes = {
    # Informational.
    100: ("continue",),
    101: ("switching_protocols",),
    102: ("processing",),
    103: ("early_hints",),

    # Success.
    200: ("ok", "okay", "all_ok", "\\o/"),
    201: ("created",),
    202: ("accepted",),
    203: ("non_authoritative_info", "non_authoritative_information"),
    204: ("no_content",),
    205: ("reset_content", "reset"),
    206: ("partial_content", "partial"),
    207: ("multi_status", "multiple_status", "multi_stati", "multiple_stati"),
    208: ("already_reported",),
    226: ("im_used",),
}

def lookup(code: int) -> str:
    """Return the description for a status code."""
    return codes[code].__doc__ + " (HTTP " + str(code) + ")"  # line 116
```

Line 116 is the `return codes[code].__doc__ + ...` line. Adjust the `startLineNumber` offset in decorations accordingly based on where this string begins in the editor model.

---

## File Dependency Order

```
types.ts
  └─ demo-investigation.json  (data, no deps)
  └─ adapters/historyToEvents.ts  (imports types.ts)
  └─ demo/usePlayback.ts  (imports types.ts, historyToEvents.ts, demo-investigation.json)
  └─ demo/Callout.tsx  (imports types.ts)
  └─ demo/EditorCanvas.tsx  (imports types.ts, Callout.tsx)
  └─ demo/NarrationPanel.tsx  (imports types.ts)
  └─ demo/ChainPanel.tsx  (imports types.ts)
  └─ demo/PlaybackControls.tsx  (no v2 type deps, just lucide + React)
  └─ demo/V2DemoSection.tsx  (imports all demo/* components + usePlayback)
  └─ landing/Hero.tsx  (no v2 deps)
  └─ landing/Cta.tsx  (no v2 deps)
  └─ landing/LandingPage.tsx  (imports V2DemoSection, Hero, Cta, usePlayback)
  └─ index.ts  (re-exports LandingPage)
App.tsx  (imports LandingPage from ./v2/landing/LandingPage)
```

Build steps 2–15 above follow this dependency order exactly. The final verification after step 16 (`npm run build`) is the authoritative end-to-end check.
