# Design Review — AEGIS PRO v2.0 Landing Page Redesign (Round 3)

**Reviewer:** Design Review Agent  
**Review type:** Re-review of Round-2-revised documents  
**Documents reviewed:** `requirements.md`, `design.md`, `tasks.md`  
**Previous review verdict:** CHANGES_REQUESTED (3 HIGH, 4 MEDIUM, 2 NIT from Round 2)  
**Source files verified:** `types.ts`, `usePlayback.ts`, `demo-investigation.json`, `V2DemoSection.tsx`, `EditorCanvas.tsx`, `ChainPanel.tsx`, `LandingPage.tsx`, `NarrationPanel.tsx`, `PlaybackControls.tsx`, `Cta.tsx`

---

## Resolution of Round-2 Findings

| Round-2 Finding | Severity | Status |
|----------------|----------|--------|
| F01 `event.line` on lineless event types → TS build failure | HIGH | ✅ RESOLVED — `types.ts` verified: `hypothesis.formed`, `probe.reproduced`, `bug.confirmed` all have `line: number`; `demo-investigation.json` verified: all three events carry `"line": 116`. TASK 02 documents this. |
| F02 DiffView content: hardcoded vs verbatim contradiction | HIGH | ✅ RESOLVED — design.md Validation Rules now says hardcoded constants only; "displayed verbatim" removed. TASK 06 defines `REMOVED_LINE` / `FIXED_LINE` constants explicitly. |
| F03 `EditorCard` used but never defined | HIGH | ✅ RESOLVED — TASK 10 now creates `frontend/src/v2/demo/EditorCard.tsx` with full props interface and JSX. Component tree updated to reflect it as a real component. |
| F04 `className` passed to `HeroColumn` but missing from props interface | MEDIUM | ✅ RESOLVED — `className?: string` added to `HeroColumnProps` in both design.md and TASK 12. Root `<div>` applies it. |
| F05 Empty green `+` line in `awaiting-approval` state | MEDIUM | ✅ RESOLVED — `awaiting-approval` branch now shows full `REMOVED_LINE` (red) and full `FIXED_LINE` (green) before the Apply/Dismiss buttons. |
| F06 `awaiting-approval` unreachable in reduced-motion manual-step mode | MEDIUM | ✅ RESOLVED — a dedicated `useEffect` independent of the auto-advance timer sets `playbackState` to `'awaiting-approval'` whenever `currentIndex` reaches `fix.proposed`, regardless of `reducedMotion`. |
| F07 Callout count: design.md says 5, TASK 05 says 4 | MEDIUM | ✅ RESOLVED — design.md Validation Rules updated to 4 callouts, `fix.proposed` explicitly excluded with note that DiffView handles it. |
| F08 "Applying…" text placement not explicit | NIT | ✅ RESOLVED — TASK 06 now explicitly states "show 'Applying…' text above the diff lines" for both reducedMotion branches. |
| F09 `V2DemoSection` dual import of events | NIT | ✅ RESOLVED — TASK 10 step 3 removes local `demoEvents` import; TASK 12 step 4 adds `events: V2Event[]` to `V2DemoSectionProps`; `LandingPage` is the single import point. |

All Round-2 findings are resolved in the design documents.

---

## New Findings

---

### FINDING 01 — MEDIUM | `CalloutLayer` component tree lists `scrollContainerRef` prop but `CalloutLayerProps` interface omits it — TS error at the call site

**Where:** `design.md` component tree (line: "CalloutLayer (receives: visibleCallouts[], codeViewRef, containerRef, scrollContainerRef, reducedMotion)") vs `tasks.md` TASK 05 `CalloutLayerProps` interface.

**Problem:** The component tree in design.md shows `CalloutLayer` receiving five props including `scrollContainerRef`. But the `CalloutLayerProps` interface defined in TASK 05 is:
```ts
interface CalloutLayerProps {
  events: V2Event[];
  currentIndex: number;
  codeViewRef: React.RefObject<CodeViewHandle | null>;
  containerRef: React.RefObject<HTMLDivElement | null>;
  reducedMotion: boolean;
}
```
`scrollContainerRef` is absent. The component tree also lists `visibleCallouts[]` (not `events`/`currentIndex`). There are two sub-problems here:

1. **`scrollContainerRef` in tree but not in interface.** If the implementer follows the interface (TASK 05), they won't pass `scrollContainerRef`. If they follow the tree, they add a prop that the interface doesn't declare — a TS error. The scroll-container is obtained internally via `codeViewRef.current?.getScrollContainer()` in TASK 05, so `scrollContainerRef` is not needed as a prop. The component tree is stale.

2. **`visibleCallouts[]` in tree but `events`/`currentIndex` in interface.** The tree implies the parent derives `visibleCallouts` and passes them down; the interface says the component derives them internally. Both are valid patterns, but they disagree on where filtering happens. design.md Validation Rules say "derived in `V2DemoSection`" — which agrees with the tree — but TASK 05 says `CalloutLayer` derives them internally from `events + currentIndex`. Whichever is correct, V2DemoSection's JSX in TASK 10 just shows `<CalloutLayer ... />` with no props listed, so the implementer cannot resolve this from TASK 10 alone.

**Fix:** Update the component tree in design.md to match the TASK 05 interface:
```
├── CalloutLayer (receives: events, currentIndex, codeViewRef, containerRef, reducedMotion)
```
Remove `scrollContainerRef` and `visibleCallouts[]` from the tree description. Also update design.md Validation Rules to align: "derived internally in `CalloutLayer`" (matching TASK 05).

---

### FINDING 02 — MEDIUM | `V2DemoSection` TASK 10 JSX layout puts `DiffView` inside `EditorCard` children, but `EditorCard` is defined with `overflow-hidden` — will clip the `DiffView` entrance animation

**Where:** `tasks.md` TASK 10 layout JSX; `design.md` EditorCard component spec.

**Problem:** TASK 10 JSX layout:
```tsx
<EditorCard ...>
  <div class="relative flex-1"> (code + callouts)
    <CodeView ... />
    <CalloutLayer ... />
  </div>
  <DiffView ... />   ←  inside EditorCard children
</EditorCard>
```

`EditorCard` outer div is `rounded-lg overflow-hidden ...` (from design.md EditorCard spec and TASK 10). `DiffView` has `motion-safe:animate-aegis-diff-fadein` entrance which starts at `translateY(-4px)`. The `overflow-hidden` on `EditorCard` clips the upward offset, cutting off the fade-in animation. The `-4px` vertical movement will be invisible (clipped to 0 before it starts).

This is a real visual defect — it will silently not animate, producing a hard appearance rather than the designed fade-in.

**Fix:** Either:

**Option A** — Remove `overflow-hidden` from `EditorCard`'s outer div. `overflow-hidden` is needed to clip `CalloutLayer` within the code area. Move it to the inner content div only:
```tsx
// EditorCard outer: rounded-lg border border-aegis-line bg-aegis-surface flex flex-col
// EditorCard content area: overflow-hidden flex-1
```
`DiffView` renders in the normal flow below the content area, outside the `overflow-hidden` boundary.

**Option B** — Move `DiffView` outside `EditorCard`, still inside the editor column:
```tsx
<div class="flex flex-col lg:w-[65%]">
  <EditorCard ...>
    <div class="relative flex-1">
      <CodeView ... />
      <CalloutLayer ... />
    </div>
  </EditorCard>
  <DiffView ... />   ←  sibling of EditorCard, not a child
</div>
```
Specify this explicitly in TASK 10 and update the TASK 10 JSX pseudocode.

**Recommendation: Option B** — it keeps `EditorCard` cleanly as "the editor chrome" without needing to split overflow behavior inside the component. TASK 10 pseudocode must be updated.

---

### FINDING 03 — MEDIUM | `usePlayback` signature in design.md/tasks.md adds `reducedMotion` parameter but the actual `usePlayback.ts` source does not — tasks need to be clear this is a new signature, not an additive change

**Where:** `tasks.md` TASK 03; `design.md` usePlayback signature; existing `usePlayback.ts` source.

**Problem:** Verified from `usePlayback.ts` (read above), the current signature is:
```ts
export function usePlayback(events: V2Event[]): { ... }
```

TASK 03 specifies the new signature:
```ts
export function usePlayback(events: V2Event[], reducedMotion: boolean): { ... }
```

This is a breaking change to the hook's call site — `LandingPage.tsx` currently calls `usePlayback(events)` with one argument. TASK 12 ("Restructure LandingPage") updates the call site to `usePlayback(events, reducedMotion)`. Both TASK 03 and TASK 12 are prerequisites-aware of each other (TASK 12 depends on TASK 03), so the ordering is correct.

The problem is that TASK 03 says "Add `reducedMotion: boolean` as the second parameter to the hook signature" — this is correct — but if an implementer completes TASK 03 and tries to build before TASK 12, `LandingPage.tsx` will fail to compile because it still calls `usePlayback(events)` without the second argument. This is a guaranteed TS error in the intermediate build state.

This is not a design flaw per se (the tasks are correctly ordered) but TASK 03's acceptance test says "`npx tsc -p tsconfig.app.json --noEmit` exits 0" — which will **fail** until TASK 12 is also done. The acceptance test is wrong.

**Fix:** Update TASK 03's acceptance test to:
```
The acceptance test for type-correctness should be run AFTER TASK 12, not after TASK 03 alone.
After TASK 03: verify the hook's internal logic only (timer behavior, reducedMotion guard).
After TASK 12: verify `npx tsc -p tsconfig.app.json --noEmit` exits 0.
```
Or alternatively, add `LandingPage.tsx` call-site update to TASK 03's scope (not TASK 12) so the build is never broken.

---

### FINDING 04 — NIT | `design.md` component tree shows `CodeView` receiving a `lineHeight` prop but `CodeViewProps` in TASK 04 does not include `lineHeight` as a required prop — stale tree

**Where:** `design.md` component tree (line: "CodeView (receives: highlightLine, gutterState, lineHeight)") vs `tasks.md` TASK 04 `CodeViewProps` interface.

**Problem:** The component tree shows `lineHeight` as a prop passed to `CodeView`. TASK 04 defines `CodeViewProps` as:
```ts
interface CodeViewProps {
  lines: string[];
  startLineNumber: number;
  highlightLine: number;
  gutterState: 'none' | 'amber' | 'green';
  lineHeight?: number;     // optional, default 20
}
```
`lineHeight` is present in TASK 04 as optional with a default, which is fine. However TASK 04 also says `reducedMotion?: boolean` is needed for the `scrollIntoView` behavior call: "consider adding `reducedMotion?: boolean` to CodeViewProps or using `window.matchMedia` check inline". This is flagged as "consider" — no decision is made. The component tree doesn't show `reducedMotion` either.

**Fix:** Resolve the "consider" in TASK 04 by picking one approach:
- **Option A**: Add `reducedMotion?: boolean` to `CodeViewProps` and use it in the `scrollIntoView` call.
- **Option B**: Read `window.matchMedia` inline inside `CodeView` (duplicating the detection but avoiding prop drilling).

Given `reducedMotion` is already computed once in `LandingPage` and drilled to all relevant children, Option A is consistent and cleaner. Make the choice explicit in TASK 04 and update the component tree to show it.

---

### FINDING 05 — NIT | TASK 10's acceptance test references `gutterState === 'green'` to derive `isVerified` for `EditorCard`, but the derivation rule in TASK 10 step 6 also requires `symbol.located` to have fired — the condition is incomplete

**Where:** `tasks.md` TASK 10 steps 6–7 and acceptance test.

**Problem:** TASK 10 step 6 says:
```
Derive `gutterState` from `playbackState` and event history:
- 'green' if `fix.verified` has fired
- 'amber' if `symbol.located` has fired but `fix.verified` has not
- 'none' otherwise
```

The acceptance test says:
```
EditorCard title bar shows "✓ Verified" badge when `isVerified === true`.
```
And the `EditorCard` JSX in TASK 10 passes `isVerified={gutterState === 'green'}`.

`gutterState === 'green'` is set when `fix.verified` fires — and `EditorCard`'s `isVerified` is derived from `playbackState === 'verified'` in the design spec (EditorCard spec in design.md says `isVerified: boolean`). But neither the component spec nor TASK 10 makes the exact derivation rule for `isVerified` explicit. The existing `V2DemoSection.tsx` uses `playbackState === 'verified'` directly. TASK 10's proposed derivation via `gutterState === 'green'` also works but couples `isVerified` to gutter state rather than playback state.

**Fix:** Make the derivation explicit in TASK 10 step 6:
```ts
const isVerified = playbackState === 'verified';
// gutterState remains separate:
const gutterState =
  firedKinds.has('fix.verified') ? 'green' :
  firedKinds.has('symbol.located') ? 'amber' : 'none';
```
Pass `isVerified` directly rather than deriving it from `gutterState`.

---

## Verified Assumptions (full set, re-verified in source)

1. **`types.ts` V2Event union** — verified: `hypothesis.formed`, `probe.reproduced`, `bug.confirmed` all carry `line: number`. `fix.proposed` has no `.line` field (correct — CalloutLayer excludes it). `PlaybackState` union includes all 7 states referenced in design.md.

2. **`demo-investigation.json` structure** — verified: 11 events, all kinds present. `hypothesis.formed`, `probe.reproduced`, `bug.confirmed` all carry `"line": 116`. `fix.verified.passed = true`. `chain.resolved.chain` has exactly 1 entry. `fix.proposed.diff` is a pre-formatted string using `...` (not `_codes_str`).

3. **Hardcoded constants are safe** — verified: `fix.proposed.diff` in the JSON uses `...` not `_codes_str`. The hardcoded `REMOVED_LINE` / `FIXED_LINE` design constants use `_codes_str`. These differ from the JSON diff string. Since the design's Option A decision is to use hardcoded constants and NOT parse `proposedEvent.diff`, this is correct and safe. The JSON diff is used only as a signal that the event fired, not for content.

4. **`usePlayback.ts` current state** — verified: (a) flat 1500ms, no per-event durations; (b) `reducedMotion` param absent; (c) `fix.proposed` special case is inside the auto-advance `useEffect`; (d) the dedicated `useEffect` for `fix.proposed → awaiting-approval` does NOT exist yet. All four items are exactly what TASK 03 must add. The design's gap analysis was correct.

5. **`PlaybackState` valid transitions** — verified in design.md: `applying → playing` (after approve timer). This is confirmed in `usePlayback.ts` source (`approveFix` sets state to `'applying'`, timer advances index and sets state back to `'playing'`). The `playing → verified` transition (when `investigation.complete` fires) is handled by the existing `useEffect` in source. Design is consistent.

6. **`lucide-react` exports** — verified in previous round: `RotateCcw`, `Play`, `Pause`, `SkipBack`, `SkipForward` all exist. No change since Round 2.

7. **`tailwind.config.js` existing tokens** — verified: `dark.muted`, `dark.surface`, `dark.bg` exist. New `aegis.*` tokens are additive, no conflict.

8. **Monaco CDN mismatch** — verified: `EditorCanvas.tsx` uses `0.52.0` CDN URLs. `package.json` pins `^0.57.0`. Monaco removal is correct.

9. **ChainPanel fake boxes** — verified in source: two `ChainBox` instances with `label="(example)"` are present. TASK 08 correctly removes them.

10. **NarrationPanel issues** — verified: `font-mono` class on container confirmed; numeric `{String(idx + 1).padStart(2, '0')}` prefix confirmed; `aria-live` absent confirmed. TASK 09 fixes all three.

11. **PlaybackControls emoji glyphs** — verified in source: `⏮ Restart`, `◀ Back`, `▶ Play`, `Forward ▶` all present. TASK 07 replacement is valid.

12. **Cta.tsx internal-roadmap copy** — verified in source: "This is v2.0.", "ambient agent", "The engine is done. This is the body." all present. TASK 11 rewrite is valid.

13. **`V2DemoSection.tsx` dual event import** — verified: imports `demoEvents` locally AND receives events-dependent props. TASK 10 fix is valid and needed.

14. **`LandingPage.tsx` `handleWatchAgain` scrolls to `window.scrollTo({ top: 0 })`** — verified in source. FR-8.3 correction to scroll to demo section (`demoRef.current?.scrollIntoView(...)`) is valid.

15. **`EditorCard` does not currently exist as a file** — verified: no `EditorCard.tsx` found under `src/v2/`. TASK 10 creates it as a new file.

16. **`NavBar.tsx` and `HeroColumn.tsx` do not currently exist** — verified: `src/v2/landing/` contains `Hero.tsx`, `WhatItIs.tsx`, `EverythingElse.tsx`, `Cta.tsx`, `LandingPage.tsx`. TASK 12 creates both new files.

---

## Unverified / Wrong Assumptions

1. **UNVERIFIED: Monaco bundle size claim (~2.7MB)** — direction is correct (Monaco is large), specific figure not measured. NFR-1's "2MB" threshold is not verifiable without before/after build comparison.

2. **UNVERIFIED: existing `/demo` route does not use `monaco-editor`** — not searched. Design notes this but says "it does not appear to." No impact on the task: `monaco-editor` stays in `package.json` regardless.

3. **PARTIALLY UNVERIFIED: `motion-safe:` Tailwind prefix on custom animate-* utilities** — Tailwind v3 documentation supports this pattern. Not verified via a live build, but the mechanism is well-established.

4. **WRONG (minor): `CalloutLayer` component tree prop list is stale** — tree shows `scrollContainerRef` and `visibleCallouts[]`; TASK 05 interface shows `events`, `currentIndex`, `codeViewRef`, `containerRef`, `reducedMotion`. See Finding 01.

5. **WRONG: `DiffView` placement inside `overflow-hidden EditorCard`** — will clip entrance animation. See Finding 02.

---

## Summary

| Severity | Round-2 count | Resolved | New | Net |
|----------|--------------|----------|-----|-----|
| HIGH     | 3            | 3        | 0   | 0   |
| MEDIUM   | 4            | 4        | 3   | 3   |
| NIT      | 2            | 2        | 2   | 2   |

**Verdict: CHANGES_REQUESTED** — 3 MEDIUM findings.

**Most critical:**
- **Finding 02** (MEDIUM — `DiffView` inside `overflow-hidden EditorCard` clips entrance animation; layout JSX must be corrected in TASK 10)
- **Finding 01** (MEDIUM — stale component tree props for `CalloutLayer`; `scrollContainerRef` appears in tree but not in interface; inconsistency will confuse implementer)
- **Finding 03** (MEDIUM — TASK 03 acceptance test claims `tsc --noEmit` exits 0, but adding the `reducedMotion` parameter to `usePlayback` will break `LandingPage.tsx`'s call site until TASK 12 is done — the acceptance test is wrong)
