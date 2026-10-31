# Implementation Tasks — AEGIS PRO v2.0 Landing Page Redesign

Tasks are ordered by dependency. Each task is independently completable once its prerequisites are done. Every task names the exact files it touches and includes a verifiable acceptance test.

---

## TASK 01 — Add color and font tokens to Tailwind config

**Prerequisite:** none

**Files touched:**
- `frontend/tailwind.config.js`
- `frontend/index.html`

**What to do:**
1. Add an `aegis` namespace to `theme.extend.colors` with these six tokens:
   - `aegis.bg`: `#0A0F1A`
   - `aegis.surface`: `#111827`
   - `aegis.line`: `#1F2937`
   - `aegis.amber`: `#D97706`
   - `aegis.red`: `#DC2626`
   - `aegis.green`: `#16A34A`
2. Add to `theme.extend.fontFamily`:
   - `sans`: `['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif']`
   - `mono`: `['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace']`
3. Add the Tailwind animation utilities to `theme.extend.animation` (so TASK 04, 05, 06, 09 can use them immediately — see note in dependency graph):
   ```js
   animation: {
     'aegis-callout-in':   'aegis-callout-in 0.3s ease-out both',
     'aegis-narration-in': 'aegis-narration-in 0.3s ease-out forwards',
     'aegis-diff-fadein':  'aegis-diff-fadein 0.3s ease-out both',
     'aegis-progress':     'aegis-progress-indeterminate 1s linear infinite',
   },
   ```
   The keyframe bodies are moved to `src/index.css` in TASK 14. For now, `tailwind.config.js` registers the names; the keyframes will be in CSS. (Tailwind resolves `animate-*` class names against the `animation` map; the `@keyframes` block just needs to exist in any CSS loaded by the page.)
4. In `index.html`, add two `<link rel="preconnect" href="https://fonts.googleapis.com">` tags and a Google Fonts import for `Inter` (weights 400, 500, 600, 700) and `JetBrains Mono` (weights 400, 500), both with `display=swap`.

**Acceptance test:**
- `cd frontend && npm run build` exits 0.
- Inspect the generated CSS: confirm utility classes like `bg-aegis-bg` and `text-aegis-amber` appear (search for `aegis-bg` or `aegis-amber` in the output CSS file under `dist/`).
- Inspect `index.html`: confirm two `<link rel="preconnect">` tags and a Google Fonts `<link>` are present.

---

## TASK 02 — Update types.ts: add reducedMotion-aware playback types

**Prerequisite:** none (types.ts already exists, only additive changes)

**Files touched:**
- `frontend/src/v2/types.ts`

**What to do:**
Add to the existing file (do not remove anything):
```ts
/** Per-event-kind auto-advance durations in milliseconds. */
export const EVENT_DURATIONS: Partial<Record<V2Event['kind'], number>> = {
  'investigation.started': 800,
  'file.opened': 800,
  'hypothesis.formed': 1200,
  'symbol.located': 800,
  'chain.resolved': 1000,
  'probe.running': 2500,
  'probe.reproduced': 2500,
  'bug.confirmed': 1200,
  'fix.proposed': 1500,  // delay before fix.proposed fires; then transitions to awaiting-approval
  'fix.verified': 3000,
  'investigation.complete': 1500,
};

export const DEFAULT_EVENT_DURATION = 1200;
```

Also update the `V2Event` union in `types.ts`: add `line: number` to the three callout-eligible event types that were previously missing it:
```ts
| { kind: "hypothesis.formed"; text: string; line: number }
| { kind: "probe.reproduced"; error: string; line: number }
| { kind: "bug.confirmed"; fix_location: string; failure_mode: string; line: number }
```
All three events are conceptually about line 116 (the crash site), so `line: number` is semantically correct. Update `demo-investigation.json` if the JSON events for these kinds do not already include a `line` field — add `"line": 116` to each.

**Acceptance test:**
- `npx tsc -p tsconfig.app.json --noEmit` from `frontend/` exits 0.
- `EVENT_DURATIONS['probe.running']` is `2500`.
- `EVENT_DURATIONS['fix.proposed']` is `1500` (present in map; auto-advance timer fires then transitions to `awaiting-approval`).
- `types.ts` V2Event union has `line: number` on `hypothesis.formed`, `probe.reproduced`, and `bug.confirmed`.
- `demo-investigation.json` events for `hypothesis.formed`, `probe.reproduced`, `bug.confirmed` each contain a `"line"` field (value `116`).

---

## TASK 03 — Rewrite usePlayback.ts: per-event timing + reduced-motion support

**Prerequisite:** TASK 02

**Files touched:**
- `frontend/src/v2/demo/usePlayback.ts`

**New function signature:**
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

`reducedMotion` is used inside the hook to guard auto-advance. It is NOT echoed back in the return value — children receive `reducedMotion` as a prop from `LandingPage`.

**What to do:**
1. Add `reducedMotion: boolean` as the second parameter to the hook signature.
2. Replace the flat `1500` constant in the auto-advance `useEffect` with a lookup:
   ```ts
   import { EVENT_DURATIONS, DEFAULT_EVENT_DURATION } from '../types';
   const nextEvent = events[nextIndex];
   const duration = nextEvent
     ? (EVENT_DURATIONS[nextEvent.kind] ?? DEFAULT_EVENT_DURATION)
     : DEFAULT_EVENT_DURATION;
   ```
3. Guard the auto-advance timer: if `reducedMotion === true`, the `useEffect` that sets up `setTimeout` must return early without scheduling anything.
4. The `fix.proposed` special-case: the timer fires using `EVENT_DURATIONS['fix.proposed']` (1500ms), advances to `fix.proposed`, then sets `playbackState` to `'awaiting-approval'` instead of continuing auto-advance. (Previously hardcoded to 1500ms; now read from the map — same value.)
5. Add a **separate** `useEffect` that is independent of the auto-advance timer. It fires whenever `currentIndex` changes and checks whether the current event is `fix.proposed`. If so, it sets `playbackState` to `'awaiting-approval'` (unless already in `awaiting-approval` or `applying`). This ensures manual-step users always reach the Apply/Dismiss buttons regardless of `reducedMotion`:
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
   Note: `awaiting-approval` is triggered by **arrival at `fix.proposed`**, not by the auto-advance timer. This effect runs regardless of `reducedMotion`.
6. Remove `reducedMotion` from the return value (it is not needed there; callers get it from `LandingPage`).

**Acceptance test:**
- **Do NOT run `npx tsc -p tsconfig.app.json --noEmit` after TASK 03 alone.** Adding `reducedMotion: boolean` as a second parameter to `usePlayback` breaks the existing `LandingPage.tsx` call site (`usePlayback(events)` with one argument) until TASK 12 updates it. The type-clean build check is deferred to TASK 12's acceptance test.
- Manual: with `reducedMotion` set to `true` in the hook call, clicking Play does not advance the event index automatically. Only pressing → or clicking Step Forward advances it.
- Manual: with `reducedMotion` set to `false`, `probe.running` visibly holds for ~2.5 seconds before advancing (time it with a stopwatch during playback).
- Manual (reduced-motion mode): step forward manually until reaching `fix.proposed`. Verify `playbackState` transitions to `'awaiting-approval'` and DiffView shows "Apply fix" and "Dismiss" buttons.

---

## TASK 04 — Create CodeView component (replaces Monaco EditorCanvas)

**Prerequisite:** TASK 01 (for color tokens and animation names registered in tailwind.config.js)

**Files touched:**
- `frontend/src/v2/demo/CodeView.tsx` ← NEW FILE
- `frontend/src/v2/demo/tokenise.ts` ← NEW FILE

**What to do:**

### tokenise.ts
Export a function `tokenise(line: string): Token[]` where:
```ts
type TokenType = 'keyword' | 'string' | 'comment' | 'number' | 'operator' | 'builtin' | 'plain';
interface Token { type: TokenType; text: string; }
```
Python keywords to highlight: `def`, `return`, `if`, `else`, `elif`, `for`, `while`, `import`, `from`, `class`, `not`, `and`, `or`, `in`, `is`, `None`, `True`, `False`, `pass`, `raise`, `try`, `except`, `with`, `as`, `lambda`, `yield`.
Python builtins to highlight: `str`, `int`, `list`, `dict`, `tuple`, `set`, `len`, `range`, `print`, `type`, `isinstance`, `sorted`, `enumerate`, `zip`, `map`, `filter`.
Tokenisation order: comments (`#` to end of line) → strings (`'...'`, `"..."`, triple-quoted) → numbers (`\d+`) → keywords/builtins (word-boundary match) → operators (`+`, `-`, `*`, `/`, `=`, `!=`, `==`, `<`, `>`, `:`, `,`, `(`, `)`, `[`, `]`, `{`, `}`) → plain (everything else).

### CodeView.tsx

The `CodeViewHandle` interface:
```ts
export interface CodeViewHandle {
  getLineElement: (lineNum: number) => HTMLDivElement | undefined;
  getScrollContainer: () => HTMLDivElement | undefined;
}
```

Props:
```ts
interface CodeViewProps {
  lines: string[];          // source lines, 0-indexed, line 1 = lines[0]
  startLineNumber: number;  // first line number displayed (default 1)
  highlightLine: number;    // 1-indexed; receives amber background + gutter arrow
  gutterState: 'none' | 'amber' | 'green'; // controls gutter icon on highlightLine
  lineHeight?: number;      // px, default 20; used by CalloutLayer fallback
  reducedMotion?: boolean;  // if true, use 'auto' scroll behavior instead of 'smooth'
}
```
The component is a `forwardRef<CodeViewHandle, CodeViewProps>`.
- Outer container: `overflow-x-auto overflow-y-auto h-full` with `font-mono text-sm`. Attach a ref to this element and expose it via `getScrollContainer()`.
- Each line is `<div className="flex items-start leading-5" data-line={lineNum} ref={...}>`.
  - **`leading-5` is required** — it sets line height to exactly 20px, which the `CalloutLayer` fallback calculation (`(lineNum - firstVisibleLine) * LINE_HEIGHT` where `LINE_HEIGHT = 20`) depends on.
  - Gutter: fixed width `w-12` (3rem / 48px), `text-right pr-2`, `text-dark-muted`, `select-none`, `bg-aegis-line`. If `lineNum === highlightLine && gutterState === 'amber'`, render a `▶` in `text-aegis-amber`. If `gutterState === 'green'`, render `✓` in `text-aegis-green`.
  - Token area: `flex-1 pl-2 whitespace-pre`. Apply `bg-aegis-amber/10 outline outline-1 outline-aegis-amber/40` to the whole line div when `lineNum === highlightLine`.
  - Each token is a `<span>` with a class derived from its `TokenType`:
    - `keyword`: `text-purple-400`
    - `string`: `text-green-300`
    - `comment`: `text-slate-500 italic`
    - `number`: `text-orange-300`
    - `operator`: `text-slate-400`
    - `builtin`: `text-cyan-300`
    - `plain`: `text-slate-300`
- On mount and when `highlightLine` changes, call `lineEl.scrollIntoView({ block: 'center', behavior: reducedMotion ? 'auto' : 'smooth' })`. Use the `reducedMotion` prop for this check (see `CodeViewProps` below — `reducedMotion?: boolean` is included, consistent with prop-drilling used throughout).
- Forward ref via `useImperativeHandle` exposing `getLineElement` and `getScrollContainer`.

**Acceptance test:**
- `npx tsc -p tsconfig.app.json --noEmit` exits 0.
- Render `<CodeView lines={PYTHON_SOURCE.split('\n')} startLineNumber={1} highlightLine={116} gutterState="amber" />` in a test: assert the element `[data-line="116"]` has a class containing `bg-aegis-amber`.
- Assert that a `▶` character or equivalent icon appears in the gutter of line 116.
- Assert `getScrollContainer()` returns the scrollable outer div (not undefined).

---

## TASK 05 — Create CalloutLayer component

**Prerequisite:** TASK 04

**Files touched:**
- `frontend/src/v2/demo/CalloutLayer.tsx` ← NEW FILE
- `frontend/src/v2/demo/CalloutCard.tsx` ← NEW FILE (rename/replace existing `Callout.tsx`)

**What to do:**

### CalloutCard.tsx
Replace the existing `Callout.tsx` logic with a `CalloutCard` component. Props:
```ts
interface CalloutCardProps {
  event: V2Event;
  topPx: number;         // absolute Y position from top of editor container
  reducedMotion: boolean;
}
```
- Positioned `absolute right-4` at `top: topPx`.
- Width: `w-60` (240px).
- Color: amber border/bg for `hypothesis.formed` and `symbol.located`; red for `probe.reproduced`; green for `bug.confirmed`, `fix.proposed`, `fix.verified`.
- Connector: a horizontal `<div>` with `absolute` positioning, `left: 3rem` (48px — the right edge of the `w-12` gutter), width `calc(100% - 3rem - 16rem - 1rem)` which simplifies to `calloutCard.offsetLeft - 48px`. In practice: the callout card is `right-4` (16px) with `w-60` (240px), so its left edge is at `containerWidth - 256px`. Set connector width as `containerWidth - 48 - 256` or measure at render time via a ref on the callout card element.
  - `height: 1px`, `border-top: 1px dashed`, color matching the callout.
  - The connector's `top` is `topPx + lineHeight/2` where `lineHeight = 20px` (half-way up the target line).
- Animation: `motion-safe:animate-aegis-callout-in` (keyframe defined in TASK 14 / `src/index.css`).
- Does NOT render for `fix.proposed` onwards — `DiffView` handles that event.

### CalloutLayer.tsx
Props:
```ts
interface CalloutLayerProps {
  events: V2Event[];
  currentIndex: number;
  codeViewRef: React.RefObject<CodeViewHandle | null>;
  containerRef: React.RefObject<HTMLDivElement | null>;
  reducedMotion: boolean;
}
```
- Derive `visibleCalloutEvents`: filter `events.slice(0, currentIndex + 1)` for kinds: `hypothesis.formed`, `symbol.located`, `probe.reproduced`, `bug.confirmed`. (Exclude `fix.proposed` — handled by `DiffView`.) Maximum callout count is 4.
- For each event, get `topPx` by calling:
  ```ts
  codeViewRef.current?.getLineElement(event.line)?.getBoundingClientRect().top
    - containerRef.current?.getBoundingClientRect().top
  ```
  All four callout-eligible event kinds (`hypothesis.formed`, `symbol.located`, `probe.reproduced`, `bug.confirmed`) now have `line: number` in the `V2Event` discriminated union (added in TASK 02), so `event.line` is valid TypeScript for all of them. No type guard is needed.
  Fallback if element not found or `lineRect.height === 0`: `(event.line - startLineNumber) * 20` (using `LINE_HEIGHT = 20` per `leading-5`).
- Run overlap-prevention pass: sort by `topPx`, then for each item if `topPx < prevTop + prevHeight + 8`, set `topPx = prevTop + prevHeight + 8`. Use a minimum callout height of 56px.
- Subscribe to scroll events on the `CodeView` scroll container via `codeViewRef.current?.getScrollContainer()`. Use `requestAnimationFrame` to throttle recomputation:
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
    return () => { scrollEl.removeEventListener('scroll', handler); cancelAnimationFrame(rafId); };
  }, [codeViewRef]);
  ```
- Render each `CalloutCard` with computed `topPx`.
- The entire `CalloutLayer` is `absolute inset-0 pointer-events-none overflow-hidden`.

**Acceptance test:**
- `npx tsc -p tsconfig.app.json --noEmit` exits 0.
- Render `CalloutLayer` with a mock `codeViewRef` that returns a mocked `getLineElement` at known positions and `getScrollContainer` returning a div. Assert each rendered `CalloutCard` has a `top` style value matching the expected line position.
- Verify no `(example)` text appears in any rendered output.

---

## TASK 06 — Create DiffView component

**Prerequisite:** TASK 02 (PlaybackState types)

**Files touched:**
- `frontend/src/v2/demo/DiffView.tsx` ← NEW FILE

**What to do:**
Implement per the spec in `design.md` § "DiffView Component Spec".

Key details:
- Define these two constants at the top of `DiffView.tsx` (before the component function):
  ```ts
  const REMOVED_LINE = "    __doc__ = (__doc__ + '\\n' + _codes_str)";
  const FIXED_LINE   = "    __doc__ = ((__doc__ or '') + '\\n' + _codes_str)";
  ```
  These are the hardcoded line contents. Do NOT parse `proposedEvent.diff` — use these constants directly.
- Outer wrapper: `role="region"` `aria-label="Proposed fix diff"`.
- Header: `text-xs font-mono text-slate-400` reading `Proposed diff · requests/status_codes.py:116`.
- Removed line: bg `bg-red-950/60`, text `text-red-300`, gutter shows `−` in `text-red-500`. Content: `REMOVED_LINE`.
- Added line: bg `bg-green-950/60`, text `text-green-300`, gutter shows `+` in `text-green-500`. Content: `FIXED_LINE`.
- **`awaiting-approval` state**: show full removed line (`REMOVED_LINE`, red) and full added line (`FIXED_LINE`, green), then below them show [Apply fix] and [Dismiss] buttons. Do NOT show an empty added line.
- During `playbackState === 'applying'` and `reducedMotion === false`: show "Applying…" text (text-slate-400, text-sm) **above the diff lines**, then show char-by-char reveal of the added line using `setInterval` at `1500 / FIXED_LINE.length` ms per character with a blinking cursor `<span>`.
- During `playbackState === 'applying'` and `reducedMotion === true`: show full added line immediately (no animation). Show "Applying…" text above the diff lines.
- During `playbackState === 'verified'`: show full diff (no char-by-char, no buttons, no "Applying…") and show the verified banner. This is the steady state after `investigation.complete` fires.
- Verified banner: `role="status"`, text `✓ Probe failed before, passed after. Verified.`, colors `text-aegis-green`, `bg-aegis-green/10`, `border border-aegis-green/50`.
- Apply/Dismiss buttons: `aria-label="Apply fix"`, `aria-label="Dismiss fix"`.
- Entrance animation: `motion-safe:animate-aegis-diff-fadein` (keyframe defined in `src/index.css` by TASK 14).

Props:
```ts
interface DiffViewProps {
  proposedEvent: Extract<V2Event, { kind: 'fix.proposed' }> | null;
  verifiedEvent: Extract<V2Event, { kind: 'fix.verified' }> | null;
  playbackState: PlaybackState;
  reducedMotion: boolean;
  onApproveFix: () => void;
  onRejectFix: () => void;
}
```

**Acceptance test:**
- `npx tsc -p tsconfig.app.json --noEmit` exits 0.
- Render with `proposedEvent = null`: nothing renders.
- Render with `proposedEvent` set, `playbackState = 'awaiting-approval'`: "Apply fix" and "Dismiss" buttons present in DOM; `aria-label` on both.
- Render with `verifiedEvent = { passed: true, ... }` and `playbackState = 'verified'`: verified banner text present; no buttons visible.
- DOM has `role="region"` and `aria-label="Proposed fix diff"`.

---

## TASK 07 — Rewrite PlaybackControls.tsx with lucide-react icons

**Prerequisite:** TASK 02

**Files touched:**
- `frontend/src/v2/demo/PlaybackControls.tsx`

**What to do:**
Replace all emoji/text glyphs with lucide-react icons. Import: `RotateCcw`, `SkipBack`, `Play`, `Pause`, `SkipForward` from `lucide-react`. Add `aria-label` to every button. Keep the progress bar and event counter.

Add a `reducedMotion: boolean` prop. When `reducedMotion === true`, show a text label "(manual mode)" beside the progress bar to indicate auto-play is off.

Button mapping:
| Glyph     | Icon component | `aria-label`             |
|-----------|----------------|--------------------------|
| `⏮`      | `RotateCcw`    | `"Restart investigation"`|
| `◀`       | `SkipBack`     | `"Step back"`            |
| `▶` / `⏸`| `Play`/`Pause` | `"Play"` / `"Pause"`     |
| `▶` (fwd) | `SkipForward`  | `"Step forward"`         |

Note on `SkipBack`: in lucide-react this renders as a single backward-skip chevron (mirror of `SkipForward`), which is the correct icon for "Step back one event". Verify with: `node -e "const { SkipBack, SkipForward } = require('lucide-react'); console.log(typeof SkipBack, typeof SkipForward)"` before implementing.

Icon size: `size={16}`. Button class: `hover:bg-dark-surface rounded p-2 focus:outline-none focus:ring-2 focus:ring-aegis-amber focus:ring-offset-1 focus:ring-offset-dark-bg`.

Also add a visible `role="toolbar"` wrapper with `aria-label="Playback controls"`.

**Acceptance test:**
- `npx tsc -p tsconfig.app.json --noEmit` exits 0.
- `npm run lint` exits 0 for this file.
- Inspect DOM: all four buttons have `aria-label`; wrapper has `role="toolbar"`.
- No emoji characters (`⏮`, `▶`, `◀`, `⏸`) appear in the rendered output.
- Tab through buttons: each shows a visible focus ring (2px amber outline).

---

## TASK 08 — Rewrite ChainPanel.tsx: remove fake boxes

**Prerequisite:** TASK 02

**Files touched:**
- `frontend/src/v2/demo/ChainPanel.tsx`

**What to do:**
1. Remove both fake `ChainBox` instances (models.py:128 and the duplicate status_codes.py entry).
2. Remove the disclaimer legend at the bottom.
3. The single `ChainBox` for `requests/status_codes.py:116` must only render (and only animate/pulse) after `chain.resolved` has fired in the event stream.
4. Before `chain.resolved` fires, show a placeholder: a dashed-border empty box with text "Resolving chain…" in muted color.
5. Update panel header text to `"Invocation chain · single-file finding"` (with middle dot character `·`).
6. The `chain.resolved` event carries `chain: ChainLink[]`; render each link in the array dynamically (today it is always one, but the component should map over them for future correctness).

**Acceptance test:**
- `npx tsc -p tsconfig.app.json --noEmit` exits 0.
- Render with `currentIndex` before the `chain.resolved` index: only the placeholder renders; no real chain box.
- Render with `currentIndex >= chain.resolved index`: exactly one box renders, showing `requests/status_codes.py · 116 · __doc__`.
- No text "(example)" appears anywhere in the rendered output.
- Header text is exactly `"Invocation chain · single-file finding"`.

---

## TASK 09 — Rewrite NarrationPanel.tsx: first-person prose, no numbers, aria-live

**Prerequisite:** TASK 02

**Files touched:**
- `frontend/src/v2/demo/NarrationPanel.tsx`

**What to do:**
1. Remove numeric line prefixes from all narration entries.
2. Replace all narration strings with the approved first-person present-tense versions:

| Event kind              | Narration string |
|-------------------------|------------------|
| `investigation.started` | `"Reading status_codes.py…"` |
| `file.opened`           | `"Scanning the surrounding context."` |
| `hypothesis.formed`     | `"Checking whether __doc__ can be None… Under -OO, Python strips docstrings. That would crash here."` |
| `symbol.located`        | `"Confirmed: __doc__ at line 116."` |
| `chain.resolved`        | `"Single-file finding. The crash site is the cause."` |
| `probe.running`         | `"Running the file under python -OO to see if it actually crashes."` |
| `probe.reproduced`      | `"It crashes. TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'."` |
| `bug.confirmed`         | `"That's a real bug. Generating a fix."` |
| `fix.proposed`          | `"Guard the concatenation with (__doc__ or ''). Does that fix it?"` |
| `fix.verified`          | `"Probe passes now. Verified."` |
| `investigation.complete`| `"Done."` |

3. Add `aria-live="polite"` and `aria-label="Investigation narration"` to the container element.
4. Remove the `font-mono` class from the container. The narration uses the UI font (Inter). Optionally wrap identifiers like `__doc__` and `status_codes.py` in `<code className="font-mono text-sm">` inline elements for legibility.
5. Remove the `{String(idx + 1).padStart(2, '0')}` prefix from each line render.
6. Keep the scroll-to-bottom behavior on new lines.
7. Keep the `aegis-narration-in` entrance animation, wrapped in `motion-safe:animate-aegis-narration-in`.
8. The placeholder idle text should read: `"Waiting to start…"` (not `"Press ▶ Play to start…"`).

**Acceptance test:**
- `npx tsc -p tsconfig.app.json --noEmit` exits 0.
- DOM has `aria-live="polite"` on the container.
- No `01`, `02`, `03` prefixes appear in rendered narration lines.
- Container does NOT have `font-mono` class.
- For `probe.reproduced` event, the narration reads `"It crashes. TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'."`.

---

## TASK 10 — Rebuild EditorCard / V2DemoSection layout

**Prerequisite:** TASK 03, 04, 05, 06, 07, 08, 09

**Files touched:**
- `frontend/src/v2/demo/V2DemoSection.tsx`
- `frontend/src/v2/demo/EditorCard.tsx` ← NEW FILE
- (Remove all inline Monaco-related code; it is replaced by CodeView + CalloutLayer)

**What to do:**
1. Create `frontend/src/v2/demo/EditorCard.tsx` — the chrome wrapper for the editor area:
   ```ts
   interface EditorCardProps {
     fileName: string;
     isVerified: boolean;
     children: React.ReactNode;
   }
   ```
   Renders:
   - Outer: `<div className="rounded-lg overflow-hidden border border-aegis-line bg-aegis-surface flex flex-col">`.
   - Title bar: `<div className="flex items-center gap-2 px-3 h-9 bg-aegis-line select-none">`.
     - Traffic-light dots: three `<div>` elements (`w-3 h-3 rounded-full`). When `isVerified === true`, the third dot is `bg-aegis-green`; otherwise `bg-slate-600`.
     - File name: `<span className="ml-2 text-sm text-slate-400 font-mono">{fileName}</span>`.
     - Verified badge: when `isVerified === true`, render `<span className="ml-auto text-xs text-aegis-green font-medium">✓ Verified</span>`.
   - Content area: `<div className="flex-1 overflow-hidden">{children}</div>`.

2. Replace the `EditorCanvas` import and usage with `CodeView`, `CalloutLayer`, `DiffView`, and `EditorCard`.
3. Remove the local `demoEvents` import from `V2DemoSection.tsx`. Add `events: V2Event[]` to `V2DemoSectionProps`. `V2DemoSection` receives all event data via this prop from `LandingPage`. This satisfies NFR-4 (single source for future WebSocket swap — only `LandingPage` imports from JSON).
4. Remove the `sr-only` hidden `PlaybackControls` wrapper. Use `PlaybackControls` as the actual visible control bar.
5. Layout:
   ```
   <section> (the demo section, ref from LandingPage)
     <div class="flex flex-col lg:flex-row"> (main content)
       <div class="flex flex-col lg:w-[65%]"> (editor column)
         <EditorCard fileName="requests/status_codes.py" isVerified={isVerified}>
           <div class="relative flex-1"> (code + callouts only)
             <CodeView ref={codeViewRef} ... />
             <CalloutLayer ... />
           </div>
         </EditorCard>
         <DiffView ... /> (sibling of EditorCard, NOT a child of it)
       </div>
       <div class="lg:w-[35%]"> (chain column, goes below on mobile)
         <ChainPanel ... />
       </div>
     </div>
     <NarrationPanel ... />
     <PlaybackControls ... />
   </section>
   ```
   **Important:** `DiffView` is a sibling of `EditorCard`, not a child. `EditorCard` has `overflow-hidden` on its outer container; placing `DiffView` inside it would clip the `aegis-diff-fadein` entrance animation (which starts at `translateY(-4px)`). Rendering `DiffView` outside `EditorCard` keeps it in the normal flow where the animation plays correctly.
6. Derive `isVerified` and `gutterState` from `playbackState` and event history:
   ```ts
   const isVerified = playbackState === 'verified';
   const firedKinds = new Set(events.slice(0, currentIndex + 1).map(e => e.kind));
   const gutterState: 'none' | 'amber' | 'green' =
     firedKinds.has('fix.verified') ? 'green' :
     firedKinds.has('symbol.located') ? 'amber' : 'none';
   ```
   `isVerified` is derived directly from `playbackState === 'verified'` (consistent with the existing `V2DemoSection.tsx` source pattern). `gutterState` is kept as a separate derivation — it controls the gutter icon and is not coupled to `isVerified`.
7. Derive `highlightLine`: from `symbol.located` event's `.line` field (116); fallback to `116`.
8. Derive `proposedEvent` and `verifiedEvent` for `DiffView` by finding the respective events in `events.slice(0, currentIndex + 1)`.
9. Remove the entire Monaco-specific `showGutterArrow` prop and related logic.

**Acceptance test:**
- `npx tsc -p tsconfig.app.json --noEmit` exits 0.
- No `import ... from 'monaco-editor'` in V2DemoSection.tsx or any file it imports.
- `V2DemoSection.tsx` does NOT import `demoEvents` directly from JSON — it receives `events: V2Event[]` as a prop.
- `EditorCard.tsx` exists at `frontend/src/v2/demo/EditorCard.tsx` with `EditorCardProps` including `fileName`, `isVerified`, `children`.
- Page renders at 1440px: CodeView visible, callouts anchored, DiffView appears at `fix.proposed` as a sibling of `EditorCard` (not inside it).
- Page renders at 390px: chain panel below editor, narration visible.
- `isVerified` is derived as `playbackState === 'verified'` (not via `gutterState`); `EditorCard` title bar shows "✓ Verified" badge when `isVerified === true`.

---

## TASK 11 — Rewrite CTA section (Cta.tsx)

**Prerequisite:** TASK 01

**Files touched:**
- `frontend/src/v2/landing/Cta.tsx`

**What to do:**
Replace the current content with visitor-facing copy and correct links.

New structure:
```tsx
interface CtaProps {
  onWatchAgain: () => void;
}

export function Cta({ onWatchAgain }: CtaProps) {
  return (
    <section className="py-24 bg-aegis-bg px-4">
      <div className="max-w-2xl mx-auto text-center space-y-6">
        <h2 className="text-4xl font-bold text-slate-100">
          Bug found. Fix proven. Yours to approve.
        </h2>
        <p className="text-lg text-slate-400 leading-relaxed">
          AEGIS PRO scans your codebase, reproduces the crash, patches it, and runs your tests —
          before you ever see a diff. You review what passed, not what might work.
        </p>
        <div className="flex flex-col sm:flex-row gap-4 justify-center pt-4">
          <a
            href="/demo"
            className="px-6 py-3 bg-aegis-green text-white font-semibold rounded-lg
                       hover:bg-aegis-green/80 transition-colors
                       focus:outline-none focus:ring-2 focus:ring-aegis-green focus:ring-offset-2"
          >
            Try the live v1 demo
          </a>
          <a
            href="https://github.com/MakerYuichi/Aegis-pro"
            target="_blank"
            rel="noopener noreferrer"
            className="px-6 py-3 border border-slate-600 text-slate-300 font-semibold rounded-lg
                       hover:border-slate-400 hover:text-slate-100 transition-colors
                       focus:outline-none focus:ring-2 focus:ring-slate-400 focus:ring-offset-2"
          >
            View on GitHub
          </a>
        </div>
        <button
          onClick={onWatchAgain}
          className="text-sm text-slate-500 hover:text-slate-300 underline transition-colors"
        >
          Watch it again
        </button>
      </div>
    </section>
  );
}
```

Keep the `onWatchAgain` prop. `LandingPage.tsx` passes a handler that calls `restart()` and then `demoRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })`.

**Acceptance test:**
- `npx tsc -p tsconfig.app.json --noEmit` exits 0.
- DOM contains `<a href="/demo">` with text "Try the live v1 demo".
- DOM contains `<a href="https://github.com/MakerYuichi/Aegis-pro">` with text "View on GitHub".
- DOM contains a button with text "Watch it again".
- No text "the future of the pipeline" appears anywhere in `Cta.tsx`.

---

## TASK 12 — Restructure LandingPage and create NavBar / HeroColumn

**Prerequisite:** TASK 03, 10, 11

**Files touched:**
- `frontend/src/v2/landing/LandingPage.tsx`
- `frontend/src/v2/landing/NavBar.tsx` ← NEW FILE
- `frontend/src/v2/landing/HeroColumn.tsx` ← NEW FILE (replaces `Hero.tsx`)

**What to do:**

### NavBar.tsx
Create a stateless nav component. No props.
```tsx
export function NavBar() {
  return (
    <nav className="sticky top-0 z-10 bg-aegis-bg/90 backdrop-blur-sm border-b border-aegis-line">
      <div className="max-w-7xl mx-auto px-4 h-12 flex items-center justify-between">
        <span className="font-semibold text-slate-100">AEGIS PRO</span>
        <div className="flex items-center gap-6">
          <a href="/demo" className="text-sm text-slate-400 hover:text-slate-100 transition-colors">
            Try live demo
          </a>
          <a
            href="https://github.com/MakerYuichi/Aegis-pro"
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-slate-400 hover:text-slate-100 transition-colors"
          >
            GitHub
          </a>
        </div>
      </div>
    </nav>
  );
}
```

### HeroColumn.tsx
Replace the full-screen `Hero.tsx` with a compact headline component. Props:
```ts
interface HeroColumnProps {
  reducedMotion: boolean;
  onPlayClick: () => void;
  className?: string;
}
```
- No `min-h-screen`. No `onWatchClick`.
- Root element: `<div className={`flex flex-col justify-center ${className ?? ''}`}>`.
- Headline: `"Watch the bug get found."` in `text-4xl lg:text-5xl font-bold text-slate-100`.
- Subhead: `"AEGIS investigates your code, live. Every arrow, every callout, every fix — visible."` in `text-lg text-slate-400`.
- When `reducedMotion === true`: render a `<button aria-label="Play investigation" onClick={onPlayClick}>` with `Play` lucide icon (size 20) and text "Play". Otherwise: render nothing in place of the button.

### LandingPage.tsx
1. Read `reducedMotion` once with `useMemo`:
   ```ts
   const reducedMotion = useMemo(
     () =>
       typeof window !== 'undefined' &&
       window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true,
     []
   );
   ```
2. Pass `reducedMotion` to `usePlayback(events, reducedMotion)`.
3. Pass `reducedMotion` to `V2DemoSection`, `PlaybackControls`, and `HeroColumn`.
4. Import `demoEvents` from `demo-investigation.json` in `LandingPage` and pass it to `usePlayback` and `V2DemoSection` as `events`. `V2DemoSection` no longer imports events itself.
4. Set up `IntersectionObserver` in `useEffect`. When `reducedMotion === true`, return early without creating the observer:
   ```ts
   useEffect(() => {
     if (!demoRef.current || reducedMotion) return;
     const observer = new IntersectionObserver(
       ([entry]) => { if (entry.intersectionRatio >= 0.3) { play(); observer.disconnect(); } },
       { threshold: 0.3 }
     );
     observer.observe(demoRef.current);
     return () => observer.disconnect();
   }, [play, reducedMotion]);
   ```
5. Wire `onWatchAgain` for `Cta`:
   ```ts
   const handleWatchAgain = useCallback(() => {
     restart();
     demoRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
   }, [restart]);
   ```
6. Remove `WhatItIs` and `EverythingElse` imports and usage.
7. Add `VerifierFlow` and `AboutDemo` sections (see TASK 13).
8. New page structure — `HeroColumn` and `V2DemoSection` are siblings in a flex row (no additional wrapper):
   ```tsx
   <div className="bg-aegis-bg text-slate-100 font-sans">
     <NavBar />
     <section className="min-h-screen flex items-center">
       <div className="max-w-7xl mx-auto px-4 w-full flex flex-col lg:flex-row gap-8 py-12">
         <HeroColumn
           reducedMotion={reducedMotion}
           onPlayClick={play}
           className="lg:w-[35%]"
         />
         <div ref={demoRef} className="lg:w-[65%]">
           <V2DemoSection ... />
         </div>
       </div>
     </section>
     <VerifierFlow />
     <AboutDemo />
     <Cta onWatchAgain={handleWatchAgain} />
   </div>
   ```

**Acceptance test:**
- `npx tsc -p tsconfig.app.json --noEmit` exits 0.
- With `reducedMotion = false`: the `IntersectionObserver` is set up on `demoRef.current`; no Play button in the hero column.
- With `reducedMotion = true`: no IntersectionObserver fires; a button with `aria-label="Play investigation"` is visible in `HeroColumn`.
- `WhatItIs` and `EverythingElse` are not imported in `LandingPage.tsx`.
- Clicking "Watch it again" in `Cta` calls `restart()` and scrolls `demoRef` into view.

---

## TASK 13 — Create VerifierFlow and AboutDemo sections

**Prerequisite:** TASK 01

**Files touched:**
- `frontend/src/v2/landing/VerifierFlow.tsx` ← NEW FILE
- `frontend/src/v2/landing/AboutDemo.tsx` ← NEW FILE

**What to do:**

### VerifierFlow.tsx
A stateless four-step flow diagram showing how the verifier works.

Steps array:
```ts
const STEPS = [
  { label: 'Found',       color: 'text-aegis-amber', desc: 'Bug located in source' },
  { label: 'Reproduced',  color: 'text-aegis-red',   desc: 'Crash confirmed by probe' },
  { label: 'Fixed',       color: 'text-slate-300',   desc: 'Patch generated' },
  { label: 'Re-run',      color: 'text-aegis-green', desc: 'Tests pass with fix applied' },
];
```
Render as a horizontal row on desktop, vertical stack on mobile. Steps connected by `→` arrows (plain text or a thin `<div>` border). No animation. No icons (keep it quiet).

Section wrapper: `<section className="py-20 bg-aegis-bg px-4">`.
Heading: `<h2 className="text-2xl font-semibold text-slate-300 text-center mb-12">How the verifier works</h2>`.

### AboutDemo.tsx
A stateless note section.

Content:
```
This is a recorded replay of a real investigation — incident INC-20261029-A42D5F,
a real scan of the psf/requests library. The bug is real. The fix is real.
The probe output is real.
```
Link to `https://github.com/MakerYuichi/Aegis-pro` with text "View the source on GitHub →".

Section wrapper: `<section className="py-16 bg-aegis-bg border-t border-aegis-line px-4">`.
Max-width: `max-w-xl mx-auto text-center`.
Text style: `text-slate-500 text-sm leading-relaxed`. Link style: `text-slate-400 underline hover:text-slate-200`.

**Acceptance test:**
- `npx tsc -p tsconfig.app.json --noEmit` exits 0.
- `VerifierFlow` renders four labeled steps with no extra content.
- `AboutDemo` contains the link `https://github.com/MakerYuichi/Aegis-pro`.
- Neither section contains fake testimonials, metrics, or logos.

---

## TASK 14 — Add global keyframe animations and remove per-component inline styles

**Prerequisite:** TASK 01 (animation names registered in tailwind.config.js in step 3)

**Files touched:**
- `frontend/src/index.css`

**What to do:**
Move the keyframe definitions that are currently inlined as `<style>` tags inside components into `frontend/src/index.css`:

```css
@keyframes aegis-callout-in {
  from { opacity: 0; transform: translateX(8px); }
  to   { opacity: 1; transform: translateX(0); }
}

@keyframes aegis-narration-in {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}

@keyframes aegis-diff-fadein {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}

@keyframes aegis-progress-indeterminate {
  0%   { left: -40%; width: 40%; }
  100% { left: 100%; width: 40%; }
}
```

Then in components, replace `style={{ animation: 'aegis-callout-in 0.3s ease-out both' }}` with `className="motion-safe:animate-aegis-callout-in"`, etc.

Remove the inline `<style>` blocks from `Callout.tsx` (now `CalloutCard.tsx`), `NarrationPanel.tsx`, and `EditorCanvas.tsx` (now removed).

Note: TASK 01 already registers the animation names in `tailwind.config.js`. TASK 14 only adds the `@keyframes` CSS bodies to `index.css`. Both must be done before any component using `motion-safe:animate-aegis-*` is built and tested visually.

**Acceptance test:**
- `npm run lint` exits 0 (no inline style warnings, if linting for them).
- `npm run build` exits 0.
- The animations still play correctly: callouts slide in, narration lines fade up, diff fades in.
- `motion-safe:` prefix means animations are suppressed when `prefers-reduced-motion: reduce` is active.

---

## TASK 15 — Final integration, cleanup, and build verification

**Prerequisite:** all previous tasks

**Files touched:**
- `frontend/src/v2/demo/EditorCanvas.tsx` — DELETE (replaced by CodeView)
- `frontend/src/v2/landing/WhatItIs.tsx` — DELETE (removed from layout)
- `frontend/src/v2/landing/EverythingElse.tsx` — DELETE (removed from layout)
- `frontend/src/v2/demo/Callout.tsx` — DELETE (replaced by CalloutCard.tsx)
- `frontend/src/v2/landing/Hero.tsx` — DELETE (replaced by HeroColumn.tsx)
- `frontend/src/v2/landing/LandingPage.tsx` — verify final imports
- `frontend/src/v2/demo/V2DemoSection.tsx` — verify final imports

**What to do:**
1. Delete the five files listed above (they have been fully replaced).
2. Verify that no remaining file under `src/v2/` imports from the deleted files.
3. Verify that lucide-react named exports are functional:
   ```
   node -e "const { RotateCcw, Play, Pause, SkipBack, SkipForward } = require('lucide-react'); console.log(typeof RotateCcw)"
   ```
   If any export is `undefined`, reinstall from the npm registry.
4. Run `cd frontend && npm run build`. Fix any TypeScript errors.
5. Run `cd frontend && npm run lint`. Fix any lint errors under `src/v2/`.
6. Open `/v2` in the browser at 1440px. Replay the full 11-event sequence. Screenshot at each of these events and note any visual anomalies:
   - `investigation.started` (editor visible, idle)
   - `symbol.located` (gutter arrow amber, callout anchored)
   - `probe.reproduced` (red callout, red progress bar)
   - `fix.proposed` (DiffView visible, Apply/Dismiss buttons)
   - `fix.verified` (green gutter, verified banner in DiffView)
   - `investigation.complete` (verified badge in title bar)
7. Resize to 390px. Verify layout per design wireframe.
8. Set `prefers-reduced-motion` via DevTools → Rendering → Emulate CSS media features. Reload. Verify manual Play button visible, no auto-play.

**Acceptance test:**
- `npm run build` exits 0, zero TypeScript errors, zero lint errors under `src/v2/`.
- All 20 acceptance criteria from `requirements.md` pass.
- No reference to `monaco-editor` CDN URLs (`jsdelivr.net`) exists in any `src/v2/` file.
- No `(example)` text exists in any rendered element of the ChainPanel.
- The page passes the manual test protocol from `design.md` § Testability.

---

## Dependency graph

```
TASK 01 (tokens + animation names)
TASK 02 (types + EVENT_DURATIONS + types.ts V2Event line fields)   ← TASK 03 (usePlayback)
TASK 01                             ← TASK 04 (CodeView)
TASK 04                             ← TASK 05 (CalloutLayer)
TASK 02                             ← TASK 06 (DiffView)
TASK 02                             ← TASK 07 (PlaybackControls)
TASK 02                             ← TASK 08 (ChainPanel)
TASK 02                             ← TASK 09 (NarrationPanel)
TASK 01                             ← TASK 10 (EditorCard + V2DemoSection)
TASK 03+04+05+06+07+08+09+10        ← TASK 10 (V2DemoSection wiring)
TASK 01                             ← TASK 11 (Cta)
TASK 03+10+11                       ← TASK 12 (LandingPage + NavBar + HeroColumn)
TASK 01                             ← TASK 13 (VerifierFlow + AboutDemo)
TASK 01                             ← TASK 14 (CSS keyframes → index.css)
ALL                                 ← TASK 15 (integration + cleanup)
```

**Parallelism:** After TASK 01 completes, TASK 02, 04, 11, 13, 14 can start in parallel. After TASK 02 completes, TASK 06, 07, 08, 09 can start in parallel (these depend on types, not tokens). TASK 04 and TASK 02 can also run in parallel (both depend only on TASK 01 and nothing, respectively). TASK 05 must wait for TASK 04. TASK 10 must wait for all of TASK 03–09.

**Critical path note:** TASK 14 must be complete (or TASK 01 must have added the animation names to tailwind.config.js) before TASK 04, 05, 06, 09 are tested visually — otherwise `motion-safe:animate-aegis-*` classes produce no animation (silently, not a build error). Since TASK 01 now registers the animation names, visual testing of animations is unblocked as soon as TASK 01 and TASK 14 are both done.

---

## Review Response Notes

**Finding 01 (HIGH — CodeViewHandle interface mismatch):** `getLineRef` renamed to `getLineElement` in TASK 04 and TASK 05. Consistent throughout.

**Finding 02 (HIGH — reducedMotion missing from DiffViewProps):** Added `reducedMotion: boolean` to `DiffViewProps` in TASK 06. Full line immediately shown when `reducedMotion === true` is documented in the 'applying' rendering logic.

**Finding 03 (HIGH — NavBar and HeroColumn unspecified):** Added explicit tasks for `NavBar.tsx` and `HeroColumn.tsx` (both in TASK 12). File paths, props interfaces, and JSX structure specified. `HeroDemo` wrapper dropped — `HeroColumn` and the `V2DemoSection` wrapper div are direct children of `LandingPage`'s hero section.

**Finding 04 (HIGH — fix.proposed duration conflict):** Added `'fix.proposed': 1500` to `EVENT_DURATIONS` in TASK 02. Updated TASK 03 to document that the timer fires, advances to `fix.proposed`, then transitions to `awaiting-approval` (no conflict with FR-10.2).

**Finding 05 (HIGH — usePlayback signature unspecified):** Full new signature written out at the top of TASK 03. `reducedMotion` is a parameter, used internally, and NOT re-exported in the return value.

**Finding 06 (HIGH — connector width formula):** Corrected in TASK 05 CalloutCard section: `left: 3rem` (48px, matching `w-12` gutter). Connector width formula documented precisely as `calloutCard.offsetLeft - 48px` with an alternative static calculation.

**Finding 07 (HIGH — TASK 14 dependency on TASK 04/05/06/09):** Resolved by moving animation name registration into TASK 01 (step 3). TASK 14 only moves `@keyframes` CSS bodies. Dependency graph updated. Critical path note added.

**Finding 08 (MEDIUM — FR-9.2 monospace contradiction):** TASK 09 acceptance test now includes assertion that the container does NOT have `font-mono`. Step 4 updated to explicitly say "Remove the `font-mono` class from the container."

**Finding 09 (MEDIUM — "Watch it again" gap):** `Cta.tsx` keeps `onWatchAgain` prop and renders the "Watch it again" button. TASK 12 specifies `handleWatchAgain` in `LandingPage` which calls both `restart()` and `demoRef.current?.scrollIntoView(...)`.

**Finding 10 (MEDIUM — CalloutLayer scroll container access):** `CodeViewHandle` now includes `getScrollContainer(): HTMLDivElement | undefined`. TASK 05 scroll handler uses `codeViewRef.current?.getScrollContainer()` instead of listening on `containerRef`.

**Finding 11 (MEDIUM — DiffView 'verified' state):** TASK 06 rendering logic now explicitly documents the `'verified'` branch: full diff visible, no buttons, no animation, verified banner shown.

**Finding 13 (MEDIUM/NIT — TASK 01 CSS variable acceptance test):** Updated to: "Inspect the generated CSS: confirm utility classes like `bg-aegis-bg` and `text-aegis-amber` appear (search for `aegis-bg` or `aegis-amber` in the output CSS file under `dist/`)."

**Finding 14 (NIT — SkipBack icon):** Added verification note in TASK 07: run `node -e "..."` to confirm `SkipBack` export before implementing.

**Finding 15 (NIT — leading-5):** Added `leading-5` requirement to TASK 04 with explicit documentation that it sets line height to 20px for the fallback calculation.

**Finding 16 (NIT — dependency graph note):** Rewritten to: "After TASK 01 completes, TASK 02, 04, 11, 13, 14 can start in parallel. After TASK 02 completes, TASK 06, 07, 08, 09 can start in parallel."

**Finding 17 (NIT — HeroDemo vs HeroColumn):** Dropped `HeroDemo`. `HeroColumn` is the left column; `V2DemoSection` is the right. Both are siblings in `LandingPage`. Component tree and TASK 12 now agree.

**Finding 18 (NIT — useRef for reducedMotion):** TASK 12 now uses `useMemo(() => ..., [])` instead of `useRef(...).current`.

**Finding 19 (NIT — lucide-react version):** Added verification step in TASK 15 step 3 to confirm lucide-react exports are functional before implementation proceeds.

---

## Review Response Notes (Round 2)

**F01 (HIGH — `event.line` on lineless event types):** Resolved via Option A. TASK 02 now explicitly instructs adding `line: number` to `hypothesis.formed`, `probe.reproduced`, and `bug.confirmed` in both `types.ts` and `demo-investigation.json`. The change has already been applied to `types.ts`. TASK 05 CalloutLayer can now access `event.line` directly on all four callout event kinds — no type guard needed, TypeScript's discriminated union accepts it.

**F02 (HIGH — DiffView content contradiction):** Resolved via Option A (hardcoded strings). TASK 06 now defines `REMOVED_LINE` and `FIXED_LINE` as named constants at the top of `DiffView.tsx`. All references to "verbatim" removed from validation rules. `FIXED_LINE.length` used in char-by-char animation refers unambiguously to this constant.

**F03 (HIGH — `EditorCard` undefined):** Resolved via Option A. TASK 10 now creates `frontend/src/v2/demo/EditorCard.tsx` with full props interface (`fileName: string`, `isVerified: boolean`, `children: React.ReactNode`) and JSX specification. The existing inline title bar logic in `V2DemoSection.tsx` moves into this component.

**F04 (MEDIUM — `HeroColumnProps` missing `className`):** Added `className?: string` to `HeroColumnProps` in TASK 12. The root `<div>` applies it. The `LandingPage` JSX passes `className="lg:w-[35%]"` as before — now compiles cleanly.

**F05 (MEDIUM — empty added line in `awaiting-approval`):** TASK 06 `awaiting-approval` branch now shows full `REMOVED_LINE` (red) and full `FIXED_LINE` (green) before the Apply/Dismiss buttons. No empty green row.

**F06 (MEDIUM — `awaiting-approval` unreachable in reduced-motion):** TASK 03 step 5 adds a dedicated `useEffect` independent of the auto-advance timer that fires whenever `currentIndex` reaches `fix.proposed` and sets `playbackState` to `'awaiting-approval'`. This runs regardless of `reducedMotion`. Acceptance test updated with a manual-step verification for this path.

**F07 (MEDIUM — callout count 5 vs 4):** Dependency graph updated; TASK 05 description explicitly states maximum callout count is 4 and that `fix.proposed` is excluded. This aligns with both TASK 05 logic and the correction made to design.md.

**F08 (NIT — "Applying…" text placement):** TASK 06 now explicitly states "show 'Applying…' text (text-slate-400, text-sm) **above the diff lines**" in the `applying` branch, for both `reducedMotion === true` and `false`.

**F09 (NIT — `V2DemoSection` dual import):** TASK 10 step 3 now explicitly instructs removing the local `demoEvents` import from `V2DemoSection.tsx` and adding `events: V2Event[]` to `V2DemoSectionProps`. TASK 12 step 4 instructs `LandingPage` to import events and pass them down. Single source of truth for WebSocket readiness.
