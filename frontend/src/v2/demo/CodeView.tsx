import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { tokenise } from './tokenise';
import type { TokenType } from './tokenise';

// Token type → Tailwind class
const TOKEN_CLASS: Record<TokenType, string> = {
  keyword:  'text-purple-400',
  string:   'text-green-300',
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

interface CodeViewProps {
  lines: string[];
  startLineNumber: number;
  highlightLine: number;
  gutterState: 'none' | 'amber' | 'green';
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
      reducedMotion = false,
    },
    ref,
  ) {
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const lineRefsMap = useRef<Map<number, HTMLDivElement>>(new Map());

    useImperativeHandle(ref, () => ({
      getLineElement: (lineNum: number) => lineRefsMap.current.get(lineNum),
      getScrollContainer: () => scrollContainerRef.current ?? undefined,
    }));

    // Scroll highlight line into view when it changes or on mount
    useEffect(() => {
      const el = lineRefsMap.current.get(highlightLine);
      if (el) {
        el.scrollIntoView({
          block: 'center',
          behavior: reducedMotion ? 'auto' : 'smooth',
        });
      }
    }, [highlightLine, reducedMotion]);

    return (
      <div
        ref={scrollContainerRef}
        className="overflow-x-auto overflow-y-auto h-full font-mono text-sm bg-aegis-surface"
      >
        {lines.map((lineText, idx) => {
          const lineNum = startLineNumber + idx;
          const isHighlighted = lineNum === highlightLine;
          const tokens = tokenise(lineText);

          return (
            <div
              key={lineNum}
              data-line={lineNum}
              ref={(el) => {
                if (el) lineRefsMap.current.set(lineNum, el);
              }}
              className={[
                'flex items-start leading-5',
                isHighlighted ? 'bg-aegis-amber/10 outline outline-1 outline-aegis-amber/40' : '',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              {/* Gutter */}
              <div
                className="w-12 text-right pr-2 text-slate-600 select-none bg-aegis-line flex-shrink-0 flex items-center justify-end"
                style={{ minWidth: '3rem' }}
              >
                {isHighlighted && gutterState === 'amber' ? (
                  <span className="text-aegis-amber mr-0.5">▶</span>
                ) : isHighlighted && gutterState === 'green' ? (
                  <span className="text-aegis-green mr-0.5">✓</span>
                ) : (
                  <span>{lineNum}</span>
                )}
              </div>

              {/* Token area */}
              <div className="flex-1 pl-2 whitespace-pre overflow-hidden">
                {tokens.map((token, ti) => (
                  <span key={ti} className={TOKEN_CLASS[token.type]}>
                    {token.text}
                  </span>
                ))}
                {/* Ensure empty lines have height */}
                {lineText === '' && <span>&nbsp;</span>}
              </div>
            </div>
          );
        })}
      </div>
    );
  },
);
