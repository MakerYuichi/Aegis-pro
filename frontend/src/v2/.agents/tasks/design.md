# Design — AEGIS PRO v2.0 Landing Page Redesign

## Overview

The redesign restructures the page so the demo investigation is the first thing a visitor sees. The existing five-section layout (Hero → WhatItIs → Demo → EverythingElse → CTA) is collapsed to three: a compact header band with the headline, the full-width demo section, and a quiet two-part footer (verifier flow + about note). The demo section is no longer hidden below a full-screen text hero; it IS the hero. All nine problems are addressed: Monaco is replaced with a custom code view (no CDN, trivial callout anchoring), callouts anchor to DOM line elements, a DiffView component handles the fix payoff, PlaybackControls uses lucide-react icons, ChainPanel shows only real data, the CTA is rewritten for visitors, narration is rewritten as first-person prose, pacing is per-event-kind, and `prefers-reduced-motion` disables auto-play.

---

## Layout Wireframe

### Desktop (1440px)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  AEGIS PRO                                    [Try live demo]  [GitHub]      │  ← NavBar, ~48px
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  Watch the bug get found.          ┌──────────────────────────────────────┐  │
│  AEGIS investigates your code,     │ ● ● ●  requests/status_codes.py  ✓   │  │
│  live. Every move, visible.        ├──────────────────────────────────────┤  │
│                                    │  110  def _build_lookup_dict():       │  │  ← CodeView
│  [▶ Play]  (if reduced-motion)     │  111      codes = _init()             │  │    65% width
│                                    │  112      _codes_str = '\n'.join([    │  │
│                                    │  113          '{} ({})'.format(...)   │  │
│                                    │  114      ])                          │  │
│                                    │  115      ▶ __doc__ = (__doc__ + '\n' │◀═╗│  ← gutter arrow
│                                    │  116                 + _codes_str)    │  ║│    + callout connector
│                                    │             ┌────────────────────┐    │  ║│
│                                    │             │ ⚠ symbol.located   │════╝│  │  ← anchored callout
│                                    │             │ __doc__ · line 116 │     │  │
│                                    │             └────────────────────┘     │  │
│                                    ├──────────────────┬───────────────────┤  │
│                                    │  NarrationPanel  │   ChainPanel       │  │
│                                    │  "Reading…"      │ [status_codes:116] │  │
│                                    ├──────────────────┴───────────────────┤  │
│                                    │ [⟳] [◀] [▶] [▶] ───────── 5/11      │  │  ← PlaybackControls
│                                    └──────────────────────────────────────┘  │
│                                                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│  How the verifier works                                                       │
│  [Found] → [Reproduced] → [Fixed] → [Re-run]                                │  ← VerifierFlow section
├─────────────────────────────────────────────────────────────────────────────┤
│  About this demo                                                              │
│  Recorded replay of a real scan of psf/requests … [View on GitHub]           │  ← AboutDemo section
└─────────────────────────────────────────────────────────────────────────────┘
```

Notes:
- The headline+subhead column is on the LEFT at ~35% width (this is `HeroColumn`, rendered as the left side of the hero row); the demo card is on the RIGHT at ~60%, with 5% gap. At 1440px the full row fits in a single viewport.
- The headline does NOT take full-screen height. The outer section uses `min-h-screen` with `flex items-center`. Both columns are vertically centered.
- The nav bar (`NavBar`) replaces the current `Hero` full-screen section.
- Both `HeroColumn` and `V2DemoSection` are direct children of `LandingPage`, laid out side-by-side in a flex row. There is no additional wrapper component combining them.

### Mobile (390px)

```
┌────────────────────────────┐
│ AEGIS PRO       [☰ menu]   │  ← 48px NavBar
├────────────────────────────┤
│                            │
│  Watch the bug get found.  │  ← HeroColumn, stacked above demo
│  AEGIS investigates your   │
│  code, live.               │
│                            │
├────────────────────────────┤
│ ● ● ●  status_codes.py     │
├────────────────────────────┤
│  110  def _build_lookup…   │  ← CodeView, full width, h-scroll
│  111      codes = _init()  │
│  …                         │
│  ▶ 116  __doc__ = …       │
├────────────────────────────┤
│  "Reading status_codes.py" │  ← NarrationPanel, always visible
├────────────────────────────┤
│ [⟳][◀][▶/⏸][▶] ── 5/11   │  ← PlaybackControls
├────────────────────────────┤
│  Invocation chain          │  ← ChainPanel BELOW editor
│  [status_codes:116]        │
├────────────────────────────┤
│  How the verifier works    │
│  Found → Reproduced → …    │
├────────────────────────────┤
│  About this demo           │
└────────────────────────────┘
```

Notes:
- Chain panel moves below the editor (flex-direction: column on mobile).
- Callouts are hidden on mobile (< 480px) to avoid overlap with the narrow code view.

---

## Named Color Tokens

Add these to `tailwind.config.js` under `theme.extend.colors.aegis`. These complement (do not replace) the existing `dark.*`, `brand.*`, `severity.*` tokens.

| Token name             | Hex value  | Semantic meaning |
|------------------------|------------|------------------|
| `aegis.bg`             | `#0A0F1A`  | Page background — slightly bluer than `dark.bg` (`#0F172A`), creates visual depth against editor cards |
| `aegis.surface`        | `#111827`  | Editor card and panel surfaces — neutral near-black |
| `aegis.line`           | `#1F2937`  | Gutter background, separator lines — visible without competing |
| `aegis.amber`          | `#D97706`  | Hypothesis / suspicion state (amber-600, intentionally warm) |
| `aegis.red`            | `#DC2626`  | Reproduced failure (red-600, matches `severity.critical`) |
| `aegis.green`          | `#16A34A`  | Verified / fix applied (green-700, calm and earned, not electric) |

**Justification:** The three semantic colours (amber, red, green) map directly to the three states a visitor observes: "something looks wrong" → "it definitely crashes" → "it's fixed and proven". They are the same stops as a traffic light but in narrative order. All other UI (text, borders, controls) uses the existing `dark.*` neutrals or Tailwind slate tones so colour spend is concentrated on the investigation state, not on decorative chrome.

---

## Typeface Choices

**UI typeface: Inter**
Add `@import` to `index.html` (Google Fonts, subset latin). Extend `tailwind.config.js`:
```js
fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'] }
```
Justification: Inter was designed for screen readability at small sizes. It is neutral without being generic — it does not carry the "corporate SaaS" weight of SF Pro or the "developer blog" feel of Geist. Its tabular numbers (`font-variant-numeric: tabular-nums`) keep the event counter and progress fraction visually stable during playback. It is widely cached (likely already in browser cache for many visitors).

**Monospace typeface: JetBrains Mono**
Add `@import` to `index.html`. Extend `tailwind.config.js`:
```js
fontFamily: { mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'] }
```
Justification: JetBrains Mono is the dominant font in the IDE market segment AEGIS PRO targets. Visitors who write code will recognise it as "their" editor font, reinforcing the product concept that AEGIS works inside an editor. It has distinct ligatures for `->`, `=>`, `!=` that appear in the Python source and narration. It is available via Google Fonts at no cost.

Both fonts are loaded with `display=swap` to avoid render-blocking. The Google Fonts URL should use `preconnect` link tags in `index.html`.

---

## Component Tree

```
LandingPage (owns: usePlayback state, IntersectionObserver, reducedMotion flag)
│
├── NavBar (stateless: headline text + two links)
│   File: frontend/src/v2/landing/NavBar.tsx
│
├── HeroColumn (stateless: headline, subhead, optional Play button)
│   File: frontend/src/v2/landing/HeroColumn.tsx  (replaces Hero.tsx)
│   Props:
│     reducedMotion: boolean
│     onPlayClick: () => void
│   [Play button visible only when reducedMotion=true AND isPlaying=false]
│
├── V2DemoSection (receives: all playback props + reducedMotion flag + events: V2Event[])
│   ├── EditorCard (chrome: title bar, window buttons, verified badge)
│   │   File: frontend/src/v2/demo/EditorCard.tsx
│   │   Props: { fileName: string; isVerified: boolean; children: React.ReactNode }
│   │   ├── CodeView (receives: highlightLine, gutterState, lineHeight, reducedMotion)
│   │   │   └── [line elements with data-line attr, each a <div> with ref]
│   │   └── CalloutLayer (receives: events, currentIndex, codeViewRef, containerRef, reducedMotion)
│   │       └── CalloutCard[] (each anchored via codeViewRef.getLineElement())
│   │
│   ├── DiffView (receives: proposedEvent, verifiedEvent, playbackState, reducedMotion, onApproveFix, onRejectFix)
│   │   │   [rendered as a sibling of EditorCard in the editor column, NOT inside EditorCard]
│   │   ├── DiffLine (removed, red)
│   │   ├── DiffLine (added, green)
│   │   └── VerifiedBanner (conditional on fix.verified.passed)
│   │
│   ├── NarrationPanel (receives: events[], currentIndex)
│   │
│   ├── ChainPanel (receives: events[], currentIndex)
│   │
│   └── PlaybackControls (receives: isPlaying, currentIndex, total, callbacks, reducedMotion)
│
├── VerifierFlow (stateless: 4-step diagram)
│
├── AboutDemo (stateless: note + links)
│
└── Cta (receives: onWatchAgain: () => void)
```

**State ownership:**
- `usePlayback` in `LandingPage` owns all playback state. No child component has its own playback state.
- `reducedMotion` is read once in `LandingPage` via `useMemo(() => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true, [])`. It does not react to runtime changes (acceptable; users set this before navigating and reload).
- `lineRefs`: a `Map<number, HTMLDivElement>` created in `CodeView` and forwarded to `CalloutLayer` via `useImperativeHandle` (method name `getLineElement`). `CalloutLayer` is a sibling of `CodeView` inside `EditorCard`, so both receive the `codeViewRef` from their common parent (`V2DemoSection`) via a ref.
- `DiffView` renders as a **sibling of `EditorCard`** in the editor column `<div>`, not as a child of `EditorCard`. `EditorCard` has `overflow-hidden` on its outer container to clip `CalloutLayer`; placing `DiffView` outside `EditorCard` keeps it in the normal document flow where the `aegis-diff-fadein` entrance animation (which starts at `translateY(-4px)`) is not clipped.
- `HeroColumn` and `V2DemoSection` are siblings in `LandingPage`; there is no `HeroDemo` wrapper. The side-by-side layout is achieved with a `flex flex-col lg:flex-row` wrapper div inside `LandingPage`.
- `Cta` receives `onWatchAgain` from `LandingPage`, which calls both `restart()` and `demoRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })`.

---

## Monaco vs Custom Code View — Decision

**Decision: Replace Monaco with a custom `CodeView` component.**

**Rationale:**

The current code has two hard problems with Monaco:
1. `EditorCanvas.tsx` loads Monaco workers from `cdn.jsdelivr.net/npm/monaco-editor@0.52.0` while `package.json` pins `monaco-editor@^0.57.0`. This is a version mismatch that can cause silent runtime failures. Fixing it requires either pinning both to the same version (acceptable) or pointing workers at the local package (requires Vite worker config changes, which are outside the allowed file scope).
2. Callout anchoring with Monaco requires `editor.getScrolledVisiblePosition(position)` which returns pixel coordinates relative to the editor DOM element. This works, but it requires: (a) Monaco to be fully initialized before the first callout, (b) manual recalculation on editor resize, (c) the callout DOM element to be positioned as a Monaco content widget OR absolutely positioned over the Monaco DOM container. The current code uses the "absolute overlay" approach but stacks all callouts at `top: 0` of the editor, completely ignoring line positions.

The use case is: a single read-only 120-line Python excerpt, never edited, never syntax-validated, never autocompleted. Monaco's full feature set (IntelliSense, validation, diffing, multi-cursor) is entirely unused. The 2.7MB Monaco bundle (minified, before gzip) is the largest single asset on the page.

A custom `CodeView` eliminates both problems:
- Each line is a `<div data-line={n} ref={lineRefs.get(n)}>`. Getting the Y position of line 116 is `lineRefs.get(116).getBoundingClientRect().top - containerRef.current.getBoundingClientRect().top`. No editor API calls, no async initialization, no race conditions.
- Python tokenisation for ~120 lines using a regex tokeniser (keywords, strings, comments, numbers, identifiers) produces visually adequate highlighting. It does not need to match Monaco's quality; it needs to be readable enough that line 116 is scannable. The tokeniser is ~60 lines of TypeScript.
- Bundle impact: removes the `monaco-editor` dynamic import entirely. The package remains in `package.json` for the existing `/demo` page if it uses it (it does not appear to, but we leave the dependency in place to avoid breaking anything outside `src/v2/`).

**The callout anchoring mechanism is the deciding factor.** Everything else (bundle size, CDN removal) is secondary. With Monaco, anchoring requires async editor initialization and coordinate polling. With a custom code view, anchoring is a single synchronous DOM measurement.

---

## Callout Anchoring Mechanism (precise)

### Data structures

```ts
// In CodeView.tsx
const lineRefs = useRef<Map<number, HTMLDivElement>>(new Map());

// Each line element:
<div
  key={lineNum}
  data-line={lineNum}
  ref={(el) => { if (el) lineRefs.current.set(lineNum, el); }}
  className="flex items-start leading-5"  // leading-5 = 20px line height, required for fallback calc
>
  {/* gutter + tokens */}
</div>

// CodeView forwards lineRefs via useImperativeHandle:
export interface CodeViewHandle {
  getLineElement: (lineNum: number) => HTMLDivElement | undefined;
  getScrollContainer: () => HTMLDivElement | undefined;
}
```

`getLineElement` is the method name used everywhere — in the component definition, in `CalloutLayer`, and in `V2DemoSection`. `getScrollContainer` returns the inner scrollable `<div>` (the one with `overflow-x-auto overflow-y-auto`) so that `CalloutLayer` can subscribe to its scroll events for position recomputation.

### Position calculation

`CalloutLayer` receives `codeViewRef: React.RefObject<CodeViewHandle>` and `callouts: CalloutItem[]`.

For each `CalloutItem`, the Y position is calculated in a `useLayoutEffect` triggered when `callouts` changes:

```ts
const containerRect = containerEl.getBoundingClientRect();
const lineEl = codeViewRef.current?.getLineElement(callout.line);
const lineRect = lineEl?.getBoundingClientRect();
const top = lineRect.top - containerRect.top; // px offset within container
```

`containerEl` is the `EditorCard` container div (the common ancestor of both `CodeView` and `CalloutLayer`). `top` is stored in component state as `{ [calloutId]: number }`.

The callout card is then rendered:
```tsx
<div
  className="absolute right-0 w-64 pointer-events-auto"
  style={{ top: `${top}px` }}
>
  <CalloutCard ... />
</div>
```

### Connector geometry (precise)

The horizontal connector runs from the gutter's right edge to the callout card's left edge. The gutter is `w-12` (3rem = 48px). The formula:

```ts
const GUTTER_WIDTH = 48; // px — w-12 = 3rem
// calloutCard.offsetLeft is the left edge of the callout card relative to the container
const connectorWidth = calloutCard.offsetLeft - GUTTER_WIDTH;
```

CSS:
```css
position: absolute;
left: 3rem;   /* 48px — right edge of the w-12 gutter */
width: calc(calloutCard.offsetLeft - 48px);  /* measured at render time */
top: <line_midpoint_y>px;
height: 1px;
border-top: 1px dashed <color>;
```

In practice `calloutCard.offsetLeft` is obtained from the rendered callout card element via a ref after positioning. Since callout cards are `right-4` (16px from the right edge), and the container is a known width, the implementer can derive `calloutCard.offsetLeft = containerWidth - calloutCardWidth - 16` without a ref, where `calloutCardWidth = 240px` (w-60).

### Overlap prevention

If two callouts target the same `top` value (or within 8px), each subsequent callout's `top` is pushed down by `max(8px, previousTop + calloutHeight + 8px)`. This is computed in `CalloutLayer` after all positions are calculated, as a post-processing pass over the sorted `callouts` array. Minimum callout height for the calculation: 56px.

### Scroll handling

The code view scrolls (the Python excerpt is ~120 lines; the visible area is ~20 lines at 20px line height = 400px). Callout Y positions must recompute on scroll. `CalloutLayer` subscribes to scroll events on the `CodeView` scroll container using the `getScrollContainer()` handle:

```ts
useEffect(() => {
  const scrollEl = codeViewRef.current?.getScrollContainer();
  if (!scrollEl) return;
  let rafId: number;
  const handler = () => {
    cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(recomputePositions);
  };
  scrollEl.addEventListener('scroll', handler, { passive: true });
  return () => {
    scrollEl.removeEventListener('scroll', handler);
    cancelAnimationFrame(rafId);
  };
}, [codeViewRef]);
```

`recomputePositions` is the same function called in `useLayoutEffect` — it re-reads `getBoundingClientRect()` for all visible callouts and updates state.

---

## Event Timing Table

| Event kind             | Duration (ms) | Reasoning |
|------------------------|---------------|-----------|
| `investigation.started`| 800           | Quick orientation; visitor just arrived |
| `file.opened`          | 800           | File read is fast |
| `hypothesis.formed`    | 1200          | Slight pause — agent is "thinking" |
| `symbol.located`       | 800           | Confirmation, quick |
| `chain.resolved`       | 1000          | Short chain; no suspense |
| `probe.running`        | 2500          | Probe actually runs; feel the wait |
| `probe.reproduced`     | 2500          | Crash confirmed; let the red land |
| `bug.confirmed`        | 1200          | Transition to fix generation |
| `fix.proposed`         | 1500          | Delay before `fix.proposed` fires (spent on `bug.confirmed` advancing); then pauses for approval |
| `fix.verified`         | 3000          | The payoff moment; let it breathe |
| `investigation.complete`| 1500         | Denouement |

Implementation: `usePlayback` looks up duration from `const EVENT_DURATIONS: Partial<Record<V2Event['kind'], number>>` with a fallback of `DEFAULT_EVENT_DURATION = 1200`. The `fix.proposed` case is handled via the `EVENT_DURATIONS` map (value 1500) — the timer fires, advances to `fix.proposed`, then sets `playbackState` to `'awaiting-approval'` instead of continuing auto-advance.

**`usePlayback` new signature:**
```ts
export function usePlayback(
  events: V2Event[],
  reducedMotion: boolean
): {
  currentIndex: number;
  isPlaying: boolean;
  state: PlaybackState;
  play: () => void;
  pause: () => void;
  restart: () => void;
  stepForward: () => void;
  stepBackward: () => void;
  approveFix: () => void;
  rejectFix: () => void;
}
```

`reducedMotion` is used inside the hook to guard the auto-advance `useEffect` (early-return when `true`). It is NOT re-exported in the return value — children receive `reducedMotion` as a prop from `LandingPage` where it is computed once.

---

## Reduced-Motion Behavior

### Detection
```ts
// In LandingPage.tsx — read once, stable across the lifetime of the component
const reducedMotion = useMemo(
  () =>
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true,
  []
);
```
Passed as `reducedMotion: boolean` prop to all relevant children.

### Playback effect
When `reducedMotion === true`:
1. `usePlayback` receives `reducedMotion = true`. The auto-advance `useEffect` early-returns if `reducedMotion` is true — no `setTimeout` is ever scheduled.
2. The `IntersectionObserver` in `LandingPage` is **never created** (the `useEffect` returns early when `reducedMotion === true`). No `demoVisible` flag is used.
3. `HeroColumn` always shows the Play button when `reducedMotion === true`, regardless of `isPlaying` state.
4. All CSS transitions and keyframe animations in the demo components are wrapped in `motion-safe:` Tailwind modifier (`motion-safe:transition-opacity`, `motion-safe:animate-aegis-callout-in`, etc.), which suppresses them when `prefers-reduced-motion: reduce` is active. No prop-drilling needed for the CSS side.
5. A **separate** `useEffect` in `usePlayback` — independent of the auto-advance timer — fires whenever `currentIndex` reaches the `fix.proposed` event index and unconditionally sets `playbackState` to `'awaiting-approval'` (if not already in `awaiting-approval` or `applying`). This ensures manual-step users can reach the Apply/Dismiss buttons regardless of `reducedMotion`:
   ```ts
   useEffect(() => {
     if (currentIndex < 0) return;
     const event = events[currentIndex];
     if (
       event?.kind === 'fix.proposed' &&
       playbackState !== 'awaiting-approval' &&
       playbackState !== 'applying'
     ) {
       setPlaybackState('awaiting-approval');
     }
   }, [currentIndex, events, playbackState]);
   ```
   This effect runs regardless of `reducedMotion`. `awaiting-approval` is triggered by **arrival at `fix.proposed`**, not by the auto-advance timer.

### Animation effect
CSS animations (`animate-pulse`, `aegis-callout-in`, `aegis-narration-in`) are all wrapped in `motion-safe:` Tailwind modifier. This handles the CSS side without prop-drilling. Auto-play suppression is a JS concern handled inside `usePlayback` and the `LandingPage` observer effect.

---

## NavBar Component Spec

**File:** `frontend/src/v2/landing/NavBar.tsx`

**Props:** None (stateless)

**Renders:**
- A `<nav>` element, `sticky top-0 z-10`, `bg-aegis-bg/90 backdrop-blur-sm border-b border-aegis-line`.
- Inner: `max-w-7xl mx-auto px-4 h-12 flex items-center justify-between`.
- Left: `<span className="font-semibold text-slate-100">AEGIS PRO</span>`.
- Right: two links:
  - `<a href="/demo">Try live demo</a>` — `text-sm text-slate-400 hover:text-slate-100`.
  - `<a href="https://github.com/MakerYuichi/Aegis-pro" target="_blank" rel="noopener noreferrer">GitHub</a>` — same style.
- No `onWatchClick`, no `isPlaying`, no state of any kind.

---

## HeroColumn Component Spec

**File:** `frontend/src/v2/landing/HeroColumn.tsx` (replaces `Hero.tsx`)

**Props:**
```ts
interface HeroColumnProps {
  reducedMotion: boolean;
  onPlayClick: () => void;
  className?: string;
}
```

**Renders:**
- A `<div className={`flex flex-col justify-center ${className ?? ''}`}>` (not a full-screen `<section>`). No `min-h-screen`. Flex column, justify-center.
- `<h1 className="text-4xl lg:text-5xl font-bold text-slate-100 leading-tight">Watch the bug get found.</h1>`
- `<p className="mt-4 text-lg text-slate-400 leading-relaxed">AEGIS investigates your code, live. Every arrow, every callout, every fix — visible.</p>`
- When `reducedMotion === true`: render a `<button aria-label="Play investigation" onClick={onPlayClick}>` with a `Play` lucide icon (size 20) and text "Play". Otherwise: render nothing in place of the button.
- No blue button. No gradient background. No `onWatchClick` prop.

---

## DiffView Component Spec

### Purpose
Renders the before/after diff for the single-line fix at `requests/status_codes.py:116`. Replaces the current inline diff overlay in `EditorCanvas`.

### Location in layout
Rendered below `CodeView` in the editor column, in the normal document flow. Visible only when `currentEvent.kind` is `fix.proposed` or any later event (`fix.verified`, `investigation.complete`).

### Props
```ts
interface DiffViewProps {
  /** The fix.proposed event, or null if not yet fired */
  proposedEvent: Extract<V2Event, { kind: 'fix.proposed' }> | null;
  /** The fix.verified event, or null if not yet fired */
  verifiedEvent: Extract<V2Event, { kind: 'fix.verified' }> | null;
  /** Current playback state */
  playbackState: PlaybackState;
  /** Whether prefers-reduced-motion is active */
  reducedMotion: boolean;
  /** Callbacks for the approval flow */
  onApproveFix: () => void;
  onRejectFix: () => void;
}
```

### Rendering logic

```
if proposedEvent === null → render nothing

if proposedEvent !== null:
  Show header: "Proposed diff · requests/status_codes.py:116"
  
  Show removed line:
    bg-red-950/60, text-red-300, prefix "−"
    content: REMOVED_LINE constant = "    __doc__ = (__doc__ + '\n' + _codes_str)"
  
  Show added line:
    bg-green-950/60, text-green-300, prefix "+"
    content: FIXED_LINE constant = "    __doc__ = ((__doc__ or '') + '\n' + _codes_str)"
  
  if playbackState === 'awaiting-approval':
    Show removed line (full content: REMOVED_LINE, red)
    Show added line (full content: FIXED_LINE, green)  ← full content, not empty
    show [Apply fix] (bg-aegis-green, aria-label="Apply fix") 
    show [Dismiss] (bg-dark-surface, aria-label="Dismiss fix")
  
  if playbackState === 'applying':
    show "Applying…" in slate text
    if reducedMotion === false:
      animate the added line (char-by-char reveal, 1500ms total)
      cursor blink at current reveal position
    if reducedMotion === true:
      show full added line immediately (no animation)
  
  if playbackState === 'verified':
    show full diff (no char-by-char, no buttons, no "Applying…")
    show verified banner (same as fix.verified state below)
  
  if verifiedEvent !== null && verifiedEvent.passed === true:
    show verified banner:
      bg-aegis-green/10, border border-aegis-green, text-aegis-green
      role="status"
      "✓ Probe failed before, passed after. Verified."
  
  if verifiedEvent !== null && verifiedEvent.passed === false:
    show failure banner:
      bg-aegis-red/10, border border-aegis-red, text-aegis-red
      role="status"
      "✗ Probe still failing after fix. Review needed."
  
  if playbackState === 'rejected':
    dim the entire DiffView (opacity-40)
    show "Fix dismissed." caption
```

The `'verified'` state (set when `investigation.complete` fires) renders the same as the completed `fix.verified` state: full diff visible, no buttons, no "Applying…", verified banner shown. This is the steady-state after the investigation ends.

### Accessibility
- The diff container has `role="region"` and `aria-label="Proposed fix diff"`.
- The verified/failure banner has `role="status"` so screen readers announce it.
- Apply/Dismiss buttons each have `aria-label`.

### Animation
- Entrance: `motion-safe:animate-aegis-diff-fadein` (keyframe defined in `src/index.css`, registered in `tailwind.config.js` — see TASK 14).
- The char-by-char reveal only runs under `playbackState === 'applying'` and only when `reducedMotion === false`. When `reducedMotion === true`, the full added line is shown immediately.

---

## Error Handling

### `demo-investigation.json` parsing
The JSON is imported statically (`import demoEvents from './demo-investigation.json'`). TypeScript validates the shape at build time via the `V2Event[]` cast. No runtime failure is possible unless the JSON is malformed, which would be caught by `tsc`. No runtime error handler is needed.

### `IntersectionObserver` unavailability
Guard: `if ('IntersectionObserver' in window)`. If not available (very old browsers), auto-play simply does not trigger. The demo is still manually playable. Log: nothing — silent degradation is appropriate.

### `window.matchMedia` unavailability
Guard: `window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true`. Optional chaining ensures that if `matchMedia` is absent the expression evaluates to `false`, defaulting `reducedMotion = false` (auto-play enabled). This is the safer default.

### Callout position calculation
`getBoundingClientRect()` returns zeros if the element is not yet rendered or is display:none. Guard: check `lineEl` is non-null and `lineRect.height > 0` before using the value. If zero, use a fallback of `(lineNum - firstVisibleLine) * LINE_HEIGHT` where `LINE_HEIGHT = 20`. This is accurate only if each line element uses `leading-5` (20px line height) — which is required in `CodeView` (see CodeView spec). Log: nothing — the fallback is visually acceptable.

### `CodeView` tokeniser
The regex tokeniser may produce unexpected output for edge-case Python syntax. Since the source is hardcoded and known, this is not a runtime risk. If a token is not matched by any pattern, the text falls through as `type: 'plain'` and renders in the default text color. No error state needed.

---

## Validation Rules

### `V2Event` union
Each event kind has required fields enforced by TypeScript's discriminated union. Any event parsed from JSON that does not match a known `kind` is filtered out by `historyToEvents` (skipped silently). The remaining events are the source of truth for all components.

### `PlaybackState`
Valid transitions:
- `idle` → `playing` (via `play()`)
- `playing` → `paused` (via `pause()`)
- `playing` → `awaiting-approval` (when `fix.proposed` fires during auto-play)
- `paused` → `playing` (via `play()`)
- `awaiting-approval` → `applying` (via `approveFix()`)
- `awaiting-approval` → `rejected` (via `rejectFix()`)
- `applying` → `playing` (after apply timer expires; auto-advances to `fix.verified`)
- `playing` → `verified` (when `investigation.complete` fires)
- Any state → `idle` (via `restart()` or Esc key)
Invalid transitions (e.g., `verified` → `playing`) are ignored in `usePlayback` (the setter returns the current state unchanged).

### `DiffView` inputs
- `DiffView` uses hardcoded string constants for both diff lines (defined at the top of `DiffView.tsx`):
  - `REMOVED_LINE = "    __doc__ = (__doc__ + '\\n' + _codes_str)"`
  - `FIXED_LINE   = "    __doc__ = ((__doc__ or '') + '\\n' + _codes_str)"`
  These are the exact source lines from `requests/status_codes.py:116`. The `proposedEvent` prop is only used to determine that the event has fired — the content is not parsed from `proposedEvent.diff`. This is safe because the source is a static, known JSON file.
- `verifiedEvent.passed` is a boolean. If `undefined` (should not happen with current JSON), treat as `false`.

### `CalloutLayer` inputs
- `visibleCallouts` is derived **internally in `CalloutLayer`** by filtering `events.slice(0, currentIndex + 1)` for callout-eligible kinds. `CalloutLayer` receives `events: V2Event[]` and `currentIndex: number` as props; the parent (`V2DemoSection`) does not pre-filter. The filter is exhaustive over known kinds; unknown kinds produce no callout. Maximum callout count in the current demo: 4 (`hypothesis.formed`, `symbol.located`, `probe.reproduced`, `bug.confirmed`). `fix.proposed` is handled by `DiffView`, not `CalloutLayer`. UI is designed to accommodate up to 8 without overflow. The scroll container for position recomputation is obtained internally via `codeViewRef.current?.getScrollContainer()` — it is not passed as a prop.

---

## Testability

### Unit-testable (no DOM)
- `usePlayback`: timer logic, state transitions, keyboard handler logic. Mock `window.matchMedia` and `setTimeout`.
- `getNarration(event)`: pure function, test all 11 event kinds.
- `EVENT_DURATIONS` lookup: trivially testable.
- `historyToEvents`: pure function.

### Integration-testable (with JSDOM/Testing Library)
- `CalloutLayer`: render `CodeView` + `CalloutLayer` together, assert callout `top` values match expected line positions.
- `DiffView`: render with various `playbackState` values, assert correct elements are visible.
- `ChainPanel`: render with `currentIndex` before and after `chain.resolved` index, assert box count.
- `NarrationPanel`: assert `aria-live="polite"`, assert no numeric prefixes.
- `PlaybackControls`: assert `aria-label` on each button, assert lucide icons render.

### Manual test protocol (on completion)
1. Open `/v2` at 1440px. Verify editor visible in first viewport. Measure time to first arrow (< 5s).
2. Step through all 11 events. Screenshot each. Check callout positions against line numbers.
3. Reach `fix.proposed`. Verify DiffView appears. Click "Apply fix". Verify `fix.verified` banner.
4. Set OS `prefers-reduced-motion: reduce`. Reload. Verify no auto-play; Play button visible.
5. Resize to 390px. Verify chain panel below editor; narration visible.
6. Tab through all controls. Verify focus rings.
7. Use Space/←/→/Esc. Verify correct behavior.
8. Inspect DOM: verify `aria-live="polite"` on narration, `aria-label` on all buttons, `role="region"` on DiffView.

---

## Review Response Notes

**Finding 01 (HIGH — getLineRef vs getLineElement):** Standardised on `getLineElement` throughout this document. Updated `CodeViewHandle` interface, all `CalloutLayer` call sites, and the `V2DemoSection` description.

**Finding 02 (HIGH — reducedMotion missing from DiffViewProps):** Added `reducedMotion: boolean` to `DiffViewProps`. Updated rendering logic to document the full-line-immediately behavior when `reducedMotion === true`.

**Finding 03 (HIGH — NavBar and HeroColumn unspecified):** Added explicit component specs for `NavBar` and `HeroColumn` with file paths and props interfaces. Clarified that `HeroColumn` and `V2DemoSection` are siblings in `LandingPage` (no wrapper); `HeroDemo` name dropped. `Hero.tsx` is replaced by `HeroColumn.tsx`.

**Finding 04 (HIGH — fix.proposed duration):** Added `fix.proposed: 1500` to the Event Timing Table with a note that this is the delay before `fix.proposed` fires (spent on the preceding event advancing). Updated implementation description accordingly.

**Finding 05 (HIGH — usePlayback signature):** Written out the full new function signature in the Event Timing section. Clarified that `reducedMotion` is NOT re-exported in the return value — it is a parameter used internally by the hook.

**Finding 06 (HIGH — connector width formula):** Connector geometry section rewritten with precise formula: `connectorWidth = calloutCard.offsetLeft - GUTTER_WIDTH` where `GUTTER_WIDTH = 48px` (w-12). Gutter offset updated from `2.5rem` to `3rem / 48px` throughout.

**Finding 10 (MEDIUM — CalloutLayer scroll container access):** Extended `CodeViewHandle` to expose `getScrollContainer(): HTMLDivElement | undefined`. Scroll handling section updated to use this method.

**Finding 11 (MEDIUM — DiffView 'verified' state missing):** Added explicit `'verified'` branch to the rendering logic: show full diff (no buttons, no "Applying…") and show the verified banner. This is the steady state after `investigation.complete` fires.

**Finding 12 (MEDIUM — IntersectionObserver demoVisible flag):** Removed the `demoVisible` flag description. Aligned to tasks.md's simpler approach: when `reducedMotion === true`, the observer is never created; `HeroColumn` shows the Play button unconditionally.

**Finding 15 (NIT — leading-5 for 20px line height):** Added `leading-5` requirement to each line div in the `CodeViewHandle` data structures section. Documented that `LINE_HEIGHT = 20` fallback is accurate only when `leading-5` is applied.

**Finding 17 (NIT — HeroDemo vs HeroColumn):** Component tree now clearly shows `HeroColumn` as a sibling of `V2DemoSection` under `LandingPage`. `HeroDemo` name removed entirely. Side-by-side layout lives in `LandingPage`.

**Finding 18 (NIT — useRef for reducedMotion):** Updated the detection snippet to use `useMemo([], [])` instead of `useRef(...).current`.

---

## Review Response Notes (Round 2)

**F01 (HIGH — `event.line` on lineless event types):** Resolved via Option A. Added `line: number` to `hypothesis.formed`, `probe.reproduced`, and `bug.confirmed` in `types.ts`. This is semantically correct — all three events are conceptually about line 116, the crash site. Updated TASK 02 to document this change in `types.ts`. TASK 05 `CalloutLayer` can now access `event.line` directly without a type guard, and TypeScript's discriminated union will accept it.

**F02 (HIGH — DiffView content contradiction):** Resolved via Option A (hardcoded strings). Removed "displayed verbatim" from the Validation Rules section. The rendering logic now specifies `REMOVED_LINE` and `FIXED_LINE` named constants. Both TASK 06 and the rendering logic refer to these constants. `FIXED_LINE.length` used in the char-by-char animation is unambiguously the constant defined at the top of `DiffView.tsx`.

**F03 (HIGH — `EditorCard` undefined):** Resolved via Option A. `EditorCard` is now a real component defined in `frontend/src/v2/demo/EditorCard.tsx` with props `{ fileName: string; isVerified: boolean; children: React.ReactNode }`. The component tree updated to reflect this. TASK 10 updated with creation instructions.

**F04 (MEDIUM — `HeroColumnProps` missing `className`):** Added `className?: string` to `HeroColumnProps` in the component spec. The root `<div>` applies it: `<div className={`flex flex-col justify-center ${className ?? ''}`}>`. TASK 12 JSX passes `className="lg:w-[35%]"` as before; it now compiles.

**F05 (MEDIUM — empty added line in `awaiting-approval`):** The `awaiting-approval` rendering branch now shows both the removed line (full content: `REMOVED_LINE`) and the added line (full content: `FIXED_LINE`) before the Apply/Dismiss buttons. Empty green row eliminated.

**F06 (MEDIUM — `awaiting-approval` unreachable in reduced-motion):** Added a dedicated `useEffect` in `usePlayback` (in the Reduced-Motion Behavior section) that fires whenever `currentIndex` reaches the `fix.proposed` event, unconditionally setting `playbackState` to `'awaiting-approval'` regardless of `reducedMotion`. This is independent of the auto-advance timer.

**F07 (MEDIUM — callout count 5 vs 4):** Updated the Validation Rules section: maximum callout count is 4. `fix.proposed` is explicitly excluded with a note that it is handled by `DiffView`.

**F08 (NIT — "Applying…" text placement):** The rendering logic for the `applying` branch already shows "Applying…" text. TASK 06 now explicitly states it appears above the diff lines.

**F09 (NIT — `V2DemoSection` dual import):** Component tree updated: `V2DemoSection` receives `events: V2Event[]` as a prop. TASK 10 updated to remove the local `demoEvents` import and add `events` to `V2DemoSectionProps`.

---

## Review Response Notes (Round 3)

**F01 (MEDIUM — `CalloutLayer` component tree stale props):** Component tree updated. `scrollContainerRef` and `visibleCallouts[]` removed from the `CalloutLayer` tree entry. Replaced with the correct interface: `events`, `currentIndex`, `codeViewRef`, `containerRef`, `reducedMotion`. Validation Rules section updated to state that `visibleCallouts` is derived **internally in `CalloutLayer`** from `events + currentIndex`, and that the scroll container is obtained via `codeViewRef.current?.getScrollContainer()` — not passed as a prop.

**F02 (MEDIUM — `DiffView` inside `overflow-hidden EditorCard` clips animation):** Adopted Option B. `DiffView` is now documented as a **sibling of `EditorCard`** in the editor column `<div>`, not a child of it. The component tree moves `DiffView` out of `EditorCard`'s subtree. State ownership note updated: `DiffView` renders in the normal flow of the editor column, below `EditorCard`. TASK 10 JSX pseudocode also updated (see tasks.md Review Response Notes Round 3).

**F03 (MEDIUM — TASK 03 acceptance test incorrectly requires `tsc --noEmit` to pass):** No change needed in design.md; the fix is in tasks.md TASK 03 acceptance test. See tasks.md Review Response Notes Round 3.

**F04 (NIT — `CodeView` `reducedMotion` prop undecided):** Resolved via Option A: `reducedMotion?: boolean` added to `CodeViewProps`. Component tree updated to show `CodeView` receiving `reducedMotion` alongside `highlightLine`, `gutterState`, `lineHeight`. This is consistent with the prop-drilling pattern used for `reducedMotion` throughout the component tree.

**F05 (NIT — `isVerified` derivation coupling):** No change needed in design.md (EditorCard spec only declares the prop type); the fix is in tasks.md TASK 10 step 6. See tasks.md Review Response Notes Round 3.
