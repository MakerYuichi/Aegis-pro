import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { tokenise } from './tokenise';
import type { TokenType } from './tokenise';
import type { PlaybackState } from '../types';

// Token type → Tailwind class
const TOKEN_CLASS: Record<TokenType, string> = {
  keyword:  'text-purple-400',
  string:   'text-yellow-300',
  comment:  'text-slate-500 italic',
  number:   'text-orange-300',
  operator: 'text-slate-400',
  builtin:  'text-cyan-300',
  plain:    'text-slate-300',
};

export interface CodeViewHandle {
  getLineElement: (lineNum: number) => HTMLDivElement | undefined;
  getScrollContainer: () => HTMLDivElement | undefined;
}

// The two versions of line 116
const REMOVED_LINE = "__doc__ = (__doc__ + '\\n' + _codes_str)";
const FIXED_LINE   = "__doc__ = ((__doc__ or '') + '\\n' + _codes_str)";

// Compute the shared prefix and suffix so animation only touches the diff region.
// prefix: "__doc__ = ("  (11 chars)
// old middle: "__doc__"  (7 chars — deleted)
// new middle: "(__doc__ or '')"  (15 chars — typed)
// suffix: " + '\\n' + _codes_str)"  (22 chars — never changes)
function computeDiff(oldStr: string, newStr: string): { prefix: string; oldMid: string; newMid: string; suffix: string } {
  let prefixLen = 0;
  while (prefixLen < oldStr.length && prefixLen < newStr.length && oldStr[prefixLen] === newStr[prefixLen]) prefixLen++;

  let oldSufLen = 0;
  while (
    oldSufLen < oldStr.length - prefixLen &&
    oldSufLen < newStr.length - prefixLen &&
    oldStr[oldStr.length - 1 - oldSufLen] === newStr[newStr.length - 1 - oldSufLen]
  ) oldSufLen++;

  return {
    prefix:  oldStr.slice(0, prefixLen),
    oldMid:  oldStr.slice(prefixLen, oldStr.length - oldSufLen),
    newMid:  newStr.slice(prefixLen, newStr.length - oldSufLen),
    suffix:  oldStr.slice(oldStr.length - oldSufLen),
  };
}

const DIFF = computeDiff(REMOVED_LINE, FIXED_LINE);
// DIFF.prefix  = "__doc__ = ("
// DIFF.oldMid  = "__doc__"      ← chars to delete
// DIFF.newMid  = "(__doc__ or '')"  ← chars to type
// DIFF.suffix  = " + '\\n' + _codes_str)"

// Total animation steps: delete oldMid chars backwards, then type newMid chars forwards
const TOTAL_STEPS = DIFF.oldMid.length + DIFF.newMid.length;

interface CodeViewProps {
  lines: string[];
  startLineNumber: number;
  highlightLine: number;
  gutterState: 'none' | 'amber' | 'green';
  playbackState?: PlaybackState;
  lineHeight?: number;
  reducedMotion?: boolean;
}

export const CodeView = forwardRef<CodeViewHandle, CodeViewProps>(
  function CodeView(
    {
      lines,
      startLineNumber,
      highlightLine,
      gutterState,
      playbackState = 'idle',
      reducedMotion = false,
    },
    ref,
  ) {
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const lineRefsMap = useRef<Map<number, HTMLDivElement>>(new Map());

    // Step-based diff animation for line 116 during 'applying'.
    // Steps 0..oldMid.length-1 → delete old chars one by one (backwards)
    // Steps oldMid.length..TOTAL_STEPS-1 → type new chars one by one
    const [animStep, setAnimStep] = useState(0);
    const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    useEffect(() => {
      if (playbackState !== 'applying') {
        if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
        if (playbackState === 'idle' || playbackState === 'playing') setAnimStep(0);
        return;
      }
      if (reducedMotion) { setAnimStep(TOTAL_STEPS); return; }

      setAnimStep(0);
      let step = 0;
      const msPerStep = 1500 / TOTAL_STEPS;
      intervalRef.current = setInterval(() => {
        step += 1;
        setAnimStep(step);
        if (step >= TOTAL_STEPS) { clearInterval(intervalRef.current!); intervalRef.current = null; }
      }, msPerStep);

      return () => { if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; } };
    }, [playbackState, reducedMotion]);

    // Derive current mid text from animStep
    function getCurrentMid(step: number): { mid: string; phase: 'deleting' | 'typing' | 'done' } {
      if (step < DIFF.oldMid.length) {
        // Still deleting: show oldMid with step chars removed from end
        return { mid: DIFF.oldMid.slice(0, DIFF.oldMid.length - step), phase: 'deleting' };
      }
      // Typing phase
      const typedChars = step - DIFF.oldMid.length;
      return { mid: DIFF.newMid.slice(0, typedChars), phase: typedChars >= DIFF.newMid.length ? 'done' : 'typing' };
    }

    useImperativeHandle(ref, () => ({
      getLineElement: (lineNum: number) => lineRefsMap.current.get(lineNum),
      getScrollContainer: () => scrollContainerRef.current ?? undefined,
    }));

    // Scroll highlight line into view
    useEffect(() => {
      const el = lineRefsMap.current.get(highlightLine);
      if (el) el.scrollIntoView({ block: 'center', behavior: reducedMotion ? 'auto' : 'smooth' });
    }, [highlightLine, reducedMotion]);

    return (
      <div
        ref={scrollContainerRef}
        className="overflow-x-auto overflow-y-auto h-full font-mono text-sm"
        style={{ background: '#1e1e2e' }}
      >
        {lines.map((lineText, idx) => {
          const lineNum = startLineNumber + idx;
          const isHighlighted = lineNum === highlightLine;
          const isBugLine = isHighlighted;

          // Determine what to render for the bug line based on playback state
          let lineContent: React.ReactNode;
          let lineBg = '';
          let gutterIcon: React.ReactNode = <span className="text-slate-600 text-xs">{lineNum}</span>;

          if (isBugLine) {
            // Gutter icon
            if (gutterState === 'amber') {
              gutterIcon = <span className="text-amber-400 text-sm">▶</span>;
            } else if (gutterState === 'green') {
              gutterIcon = <span className="text-green-400 text-sm">✓</span>;
            }

            if (
              playbackState === 'awaiting-approval' ||
              playbackState === 'applying' ||
              playbackState === 'verified' ||
              playbackState === 'rejected'
            ) {
              if (playbackState === 'awaiting-approval') {
                // Show old line with red tint + strikethrough to signal "this is what changes"
                lineBg = 'bg-red-900/30';
                lineContent = (
                  <div className="flex-1 pl-2 whitespace-pre overflow-hidden">
                    {/* Removed line: red + strikethrough */}
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-red-500 text-xs select-none">−</span>
                      <span className="text-red-300 line-through opacity-70">{REMOVED_LINE}</span>
                    </div>
                    {/* Added line: green, full text shown */}
                    <div className="flex items-center gap-2">
                      <span className="text-green-500 text-xs select-none">+</span>
                      <span className="text-green-300">{FIXED_LINE}</span>
                    </div>
                  </div>
                );
              } else if (playbackState === 'applying') {
                lineBg = 'bg-green-900/20';
                const { mid, phase } = getCurrentMid(animStep);
                const currentLineText = DIFF.prefix + mid + DIFF.suffix;
                const tokens = tokenise(currentLineText);
                lineContent = (
                  <div className="flex-1 pl-2 whitespace-pre overflow-hidden flex items-center">
                    {tokens.map((token, ti) => (
                      <span key={ti} className={phase === 'deleting' ? TOKEN_CLASS[token.type] + ' opacity-70' : TOKEN_CLASS[token.type]}>{token.text}</span>
                    ))}
                    {phase !== 'done' && (
                      <span className="inline-block w-[2px] h-[1em] bg-green-400 animate-pulse ml-px align-text-bottom" />
                    )}
                  </div>
                );
              } else if (playbackState === 'verified') {
                // Show only the fixed line, clean
                lineBg = 'bg-green-900/15';
                const tokens = tokenise(FIXED_LINE);
                lineContent = (
                  <div className="flex-1 pl-2 whitespace-pre overflow-hidden">
                    {tokens.map((token, ti) => (
                      <span key={ti} className={TOKEN_CLASS[token.type]}>{token.text}</span>
                    ))}
                  </div>
                );
              } else {
                // rejected — show original dimmed
                lineBg = 'bg-amber-900/10 opacity-50';
                const tokens = tokenise(lineText);
                lineContent = (
                  <div className="flex-1 pl-2 whitespace-pre overflow-hidden">
                    {tokens.map((token, ti) => (
                      <span key={ti} className={TOKEN_CLASS[token.type]}>{token.text}</span>
                    ))}
                  </div>
                );
              }
            } else {
              // Default highlighted state (investigating)
              lineBg = 'bg-amber-500/10 outline outline-1 outline-amber-500/30';
              const tokens = tokenise(lineText);
              lineContent = (
                <div className="flex-1 pl-2 whitespace-pre overflow-hidden">
                  {tokens.map((token, ti) => (
                    <span key={ti} className={TOKEN_CLASS[token.type]}>{token.text}</span>
                  ))}
                </div>
              );
            }
          } else {
            // Normal line
            const tokens = tokenise(lineText);
            lineContent = (
              <div className="flex-1 pl-2 whitespace-pre overflow-hidden">
                {tokens.map((token, ti) => (
                  <span key={ti} className={TOKEN_CLASS[token.type]}>{token.text}</span>
                ))}
                {lineText === '' && <span>&nbsp;</span>}
              </div>
            );
          }

          return (
            <div
              key={lineNum}
              data-line={lineNum}
              ref={(el) => { if (el) lineRefsMap.current.set(lineNum, el); }}
              className={[
                'flex items-start leading-6',
                isBugLine ? lineBg : 'hover:bg-white/5',
              ].filter(Boolean).join(' ')}
            >
              {/* Gutter */}
              <div
                className="flex-shrink-0 w-12 text-right pr-3 select-none flex items-center justify-end"
                style={{ background: '#161622', minWidth: '3rem' }}
              >
                {gutterIcon}
              </div>

              {lineContent}
            </div>
          );
        })}
      </div>
    );
  },
);
