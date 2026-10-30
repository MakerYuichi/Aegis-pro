import { useEffect, useRef, useState } from 'react';
import type { editor } from 'monaco-editor';
import type { PlaybackState, V2Event } from '../types';

// Configure Monaco workers via CDN to avoid Vite bundling issues
declare global {
  interface Window {
    MonacoEnvironment?: {
      getWorkerUrl: (moduleId: string, label: string) => string;
    };
  }
}

if (typeof window !== 'undefined') {
  window.MonacoEnvironment = {
    getWorkerUrl: (_moduleId: string, label: string): string => {
      if (label === 'json') return `https://cdn.jsdelivr.net/npm/monaco-editor@0.52.0/min/vs/language/json/json.worker.js`;
      if (label === 'css' || label === 'scss' || label === 'less') return `https://cdn.jsdelivr.net/npm/monaco-editor@0.52.0/min/vs/language/css/css.worker.js`;
      if (label === 'html' || label === 'handlebars' || label === 'razor') return `https://cdn.jsdelivr.net/npm/monaco-editor@0.52.0/min/vs/language/html/html.worker.js`;
      if (label === 'typescript' || label === 'javascript') return `https://cdn.jsdelivr.net/npm/monaco-editor@0.52.0/min/vs/language/typescript/ts.worker.js`;
      return `https://cdn.jsdelivr.net/npm/monaco-editor@0.52.0/min/vs/editor/editor.worker.js`;
    },
  };
}

// Realistic approximation of requests/status_codes.py around line 116.
// The bug line (__doc__ concatenation) is at line 116.
const PYTHON_SOURCE = [
  '# requests/status_codes.py',
  '# -*- coding: utf-8 -*-',
  '',
  '"""',
  'The ``codes`` object defines a mapping from common names for HTTP statuses',
  'to their numerical codes, accessible either as attributes or as dictionary',
  'items.',
  '',
  'Example::',
  '',
  "    >>> import requests",
  "    >>> requests.codes['temporary_redirect']",
  '    307',
  '    >>> requests.codes.teapot',
  '    418',
  "    >>> requests.codes['\\o/']",
  '    200',
  '',
  '"""',
  '',
  'from .structures import LookupDict',
  '',
  '_codes = {',
  '    # Informational.',
  "    100: ('continue',),",
  "    101: ('switching_protocols',),",
  "    102: ('processing',),",
  "    103: ('early_hints',),",
  '',
  '    # Success.',
  "    200: ('ok', 'okay', 'all_ok', '\\o/'),",
  "    201: ('created',),",
  "    202: ('accepted',),",
  "    203: ('non_authoritative_info', 'non_authoritative_information'),",
  "    204: ('no_content',),",
  "    205: ('reset_content', 'reset'),",
  "    206: ('partial_content', 'partial'),",
  "    207: ('multi_status', 'multiple_status', 'multi_stati', 'multiple_stati'),",
  "    208: ('already_reported',),",
  "    226: ('im_used',),",
  '',
  '    # Redirection.',
  "    300: ('multiple_choices',),",
  "    301: ('moved_permanently', 'moved', '\\o-'),",
  "    302: ('found',),",
  "    303: ('see_other', 'other'),",
  "    304: ('not_modified',),",
  "    305: ('use_proxy',),",
  "    307: ('temporary_redirect', 'temporary_moved', 'temporary'),",
  "    308: ('permanent_redirect',),",
  '',
  '    # Client Error.',
  "    400: ('bad_request', 'bad'),",
  "    401: ('unauthorized',),",
  "    403: ('forbidden',),",
  "    404: ('not_found', '-o-'),",
  "    405: ('method_not_allowed', 'not_allowed'),",
  "    408: ('request_timeout', 'timeout'),",
  "    409: ('conflict',),",
  "    410: ('gone',),",
  "    418: ('teapot', 'i_am_a_teapot'),",
  "    429: ('too_many_requests', 'too_many'),",
  '',
  '    # Server Error.',
  "    500: ('internal_server_error', 'server_error', '/o\\', '\u2717'),",
  "    501: ('not_implemented',),",
  "    502: ('bad_gateway',),",
  "    503: ('service_unavailable', 'unavailable'),",
  "    504: ('gateway_timeout',),",
  "    505: ('http_version_not_supported', 'http_version'),",
  '}',
  '',
  '',
  'def _init():',
  "    codes = LookupDict(name='status_codes')",
  '    for (code, titles) in list(_codes.items()):',
  '        for title in titles:',
  '            setattr(codes, title, code)',
  "            if not title.startswith(('\\\\\\\\', '/o')):",
  '                setattr(codes, title.upper(), code)',
  '',
  '    return codes',
  '',
  '',
  'def _build_lookup_dict():',
  '    codes = _init()',
  "    _codes_str = '\\n'.join([",
  "        '{} ({})'.format(code, ', '.join(titles))",
  '        for code, titles in sorted(_codes.items())',
  '    ])',
  "    __doc__ = (__doc__ + '\\n' + _codes_str)  # line 116 \u2014 bug: __doc__ is None under -OO",
  '    codes.__doc__ = __doc__',
  '    return codes',
  '',
  '',
  'codes = _build_lookup_dict()',
].join('\n');

const FIXED_LINE = "    __doc__ = ((__doc__ or '') + '\\n' + _codes_str)  # line 116 — fixed";

interface EditorCanvasProps {
  showGutterArrow: boolean;
  highlightLine: number;
  events: V2Event[];
  currentIndex: number;
  playbackState: PlaybackState;
  onApproveFix: () => void;
  onRejectFix: () => void;
}

// CSS for gutter arrow + line highlight decorations
const DECORATION_STYLE_ID = 'aegis-decoration-style';

function ensureDecorationStyle(): void {
  if (document.getElementById(DECORATION_STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = DECORATION_STYLE_ID;
  style.textContent = `
    .aegis-gutter-arrow::before {
      content: '\\25B6';
      color: #f59e0b;
      font-size: 12px;
      line-height: 1;
    }
    .aegis-gutter-arrow-green::before {
      content: '\\2713';
      color: #22c55e;
      font-size: 12px;
      font-weight: bold;
      line-height: 1;
    }
    .aegis-line-highlight {
      background: rgba(251, 191, 36, 0.12);
      outline: 1px solid rgba(251, 191, 36, 0.5);
    }
    .aegis-line-highlight-blue {
      background: rgba(59, 130, 246, 0.15);
      outline: 1px solid rgba(59, 130, 246, 0.5);
    }
    .aegis-line-flash-yellow {
      background: rgba(251, 191, 36, 0.35);
      outline: 1px solid rgba(251, 191, 36, 0.8);
    }
    @keyframes aegis-editor-fadein {
      from { opacity: 0; }
      to   { opacity: 1; }
    }
    @keyframes aegis-progress-indeterminate {
      0%   { left: -40%; width: 40%; }
      100% { left: 100%; width: 40%; }
    }
    @keyframes aegis-diff-fadein {
      from { opacity: 0; transform: translateY(-4px); }
      to   { opacity: 1; transform: translateY(0); }
    }
  `;
  document.head.appendChild(style);
}

export function EditorCanvas({
  showGutterArrow,
  highlightLine,
  events,
  currentIndex,
  playbackState,
  onApproveFix: _onApproveFix,
  onRejectFix: _onRejectFix,
}: EditorCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const editorRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const decorationsRef = useRef<string[]>([]);

  // Animation state
  const [editorVisible, setEditorVisible] = useState(false);
  const [showProgressBar, setShowProgressBar] = useState(false);
  const [progressBarRed, setProgressBarRed] = useState(false);
  const [showDiffOverlay, setShowDiffOverlay] = useState(false);
  const [showVerifiedTitle, setShowVerifiedTitle] = useState(false);
  const [revealedFixChars, setRevealedFixChars] = useState(0);
  const [gutterState, setGutterState] = useState<'none' | 'amber' | 'green'>('none');
  const [lineHighlightState, setLineHighlightState] = useState<'none' | 'flash' | 'amber' | 'blue' | 'green'>('none');

  // Derive which events have fired
  const firedKinds = new Set(
    events.slice(0, currentIndex + 1).map((e) => e.kind),
  );

  // Create the editor on mount
  useEffect(() => {
    ensureDecorationStyle();
    let disposed = false;

    import('monaco-editor').then((monaco) => {
      if (disposed || !containerRef.current) return;

      editorRef.current = monaco.editor.create(containerRef.current, {
        value: PYTHON_SOURCE,
        language: 'python',
        theme: 'vs-dark',
        readOnly: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        fontSize: 13,
        lineNumbers: 'on',
        glyphMargin: true,
        folding: false,
        wordWrap: 'off',
        renderLineHighlight: 'none',
        scrollbar: {
          vertical: 'auto',
          horizontal: 'auto',
        },
      });

      // Scroll to the bug line initially
      editorRef.current.revealLineInCenter(highlightLine);

      const initialDecorations: editor.IModelDeltaDecoration[] = [
        {
          range: new monaco.Range(highlightLine, 1, highlightLine, 1),
          options: {
            isWholeLine: true,
            className: 'aegis-line-highlight',
          },
        },
      ];
      decorationsRef.current = editorRef.current.deltaDecorations([], initialDecorations);
    });

    return () => {
      disposed = true;
      editorRef.current?.dispose();
      editorRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Per-event visual activity
  useEffect(() => {
    if (currentIndex < 0) {
      // Reset all animation state on restart
      setEditorVisible(false);
      setShowProgressBar(false);
      setProgressBarRed(false);
      setShowDiffOverlay(false);
      setShowVerifiedTitle(false);
      setRevealedFixChars(0);
      setGutterState('none');
      setLineHighlightState('none');
      return;
    }

    const event = events[currentIndex];
    if (!event) return;

    if (event.kind === 'investigation.started') {
      setEditorVisible(true);
    }

    if (event.kind === 'file.opened') {
      // Scroll to line 116 and flash yellow then settle to blue
      if (editorRef.current) {
        editorRef.current.revealLineInCenter(highlightLine);
      }
      setLineHighlightState('flash');
      const t = setTimeout(() => setLineHighlightState('blue'), 600);
      return () => clearTimeout(t);
    }

    if (event.kind === 'symbol.located') {
      setGutterState('amber');
      setLineHighlightState('amber');
    }

    if (event.kind === 'probe.running') {
      setShowProgressBar(true);
      setProgressBarRed(false);
    }

    if (event.kind === 'probe.reproduced') {
      setProgressBarRed(true);
      const t = setTimeout(() => setShowProgressBar(false), 800);
      return () => clearTimeout(t);
    }

    if (event.kind === 'bug.confirmed') {
      setGutterState('amber');
    }

    if (event.kind === 'fix.proposed') {
      setShowDiffOverlay(true);
    }

    if (event.kind === 'fix.verified') {
      setShowDiffOverlay(false);
      setGutterState('green');
      setLineHighlightState('green');
    }

    if (event.kind === 'investigation.complete') {
      setShowVerifiedTitle(true);
    }
  // We intentionally depend on currentIndex to re-run per step
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentIndex, events, highlightLine]);

  // Character-by-character reveal when applying
  useEffect(() => {
    if (playbackState !== 'applying') {
      if (playbackState === 'idle') setRevealedFixChars(0);
      return;
    }
    setRevealedFixChars(0);
    const totalChars = FIXED_LINE.length;
    const interval = 1500 / totalChars;
    let count = 0;
    const id = setInterval(() => {
      count += 1;
      setRevealedFixChars(count);
      if (count >= totalChars) clearInterval(id);
    }, interval);
    return () => clearInterval(id);
  }, [playbackState]);

  // Update Monaco decorations based on gutter/highlight state
  useEffect(() => {
    if (!editorRef.current) return;

    import('monaco-editor').then((monaco) => {
      if (!editorRef.current) return;

      const decorations: editor.IModelDeltaDecoration[] = [];

      // Line highlight
      let lineClass = '';
      if (lineHighlightState === 'flash' || lineHighlightState === 'amber') {
        lineClass = 'aegis-line-highlight';
      } else if (lineHighlightState === 'blue') {
        lineClass = 'aegis-line-highlight-blue';
      } else if (lineHighlightState === 'green') {
        lineClass = 'aegis-line-highlight-blue';
      }

      if (lineClass) {
        decorations.push({
          range: new monaco.Range(highlightLine, 1, highlightLine, 1),
          options: { isWholeLine: true, className: lineClass },
        });
      }

      // Gutter arrow
      if (gutterState === 'amber' && showGutterArrow) {
        decorations.push({
          range: new monaco.Range(highlightLine, 1, highlightLine, 1),
          options: { isWholeLine: false, glyphMarginClassName: 'aegis-gutter-arrow' },
        });
      } else if (gutterState === 'green') {
        decorations.push({
          range: new monaco.Range(highlightLine, 1, highlightLine, 1),
          options: { isWholeLine: false, glyphMarginClassName: 'aegis-gutter-arrow-green' },
        });
      } else if (showGutterArrow) {
        decorations.push({
          range: new monaco.Range(highlightLine, 1, highlightLine, 1),
          options: { isWholeLine: false, glyphMarginClassName: 'aegis-gutter-arrow' },
        });
      }

      decorationsRef.current = editorRef.current.deltaDecorations(
        decorationsRef.current,
        decorations,
      );
    });
  }, [showGutterArrow, highlightLine, gutterState, lineHighlightState]);

  const showProbeBar = showProgressBar && firedKinds.has('probe.running');

  return (
    <div
      className="relative w-full h-full flex flex-col"
      style={{ minHeight: 0 }}
    >
      {/* Editor title bar */}
      <div className="flex items-center justify-between bg-slate-800 border-b border-slate-700 px-3 py-1.5 text-xs text-slate-400 flex-shrink-0">
        <span className="font-mono">requests/status_codes.py</span>
        {showVerifiedTitle && (
          <span className="text-green-400 font-semibold flex items-center gap-1">
            <span>✓</span> Verified
          </span>
        )}
      </div>

      {/* Thin progress bar at top of editor */}
      {showProbeBar && (
        <div className="relative h-0.5 w-full overflow-hidden flex-shrink-0" style={{ background: 'rgba(255,255,255,0.08)' }}>
          <div
            className="absolute h-full"
            style={{
              background: progressBarRed ? '#ef4444' : '#3b82f6',
              animation: progressBarRed ? 'none' : 'aegis-progress-indeterminate 1s linear infinite',
              width: progressBarRed ? '100%' : '40%',
              transition: progressBarRed ? 'background 0.2s' : undefined,
            }}
          />
        </div>
      )}

      {/* Monaco editor wrapper with fade-in */}
      <div
        className="relative flex-1"
        style={{
          minHeight: 0,
          opacity: editorVisible ? 1 : 0,
          transition: 'opacity 400ms ease-out',
        }}
      >
        <div ref={containerRef} className="w-full h-full" />

        {/* Diff overlay — shown when fix.proposed is current and applying/awaiting */}
        {showDiffOverlay && (
          <div
            className="absolute left-0 right-0 pointer-events-none"
            style={{
              top: '60%',
              zIndex: 20,
              animation: 'aegis-diff-fadein 0.3s ease-out both',
            }}
          >
            <div className="mx-4 rounded border border-slate-600 bg-slate-950/95 font-mono text-xs overflow-hidden">
              <div className="px-3 py-1 text-slate-500 text-xs border-b border-slate-700 bg-slate-900/80">
                Proposed diff · line 116
              </div>
              {/* Removed line */}
              <div className="px-3 py-1.5 bg-red-950/60 text-red-300 flex items-start gap-2">
                <span className="select-none text-red-500 w-3">-</span>
                <span className="whitespace-pre-wrap break-all">
                  {"__doc__ = (__doc__ + '\\n' + _codes_str)"}
                </span>
              </div>
              {/* Added line — with char-by-char reveal during applying */}
              <div className="px-3 py-1.5 bg-green-950/60 text-green-300 flex items-start gap-2">
                <span className="select-none text-green-500 w-3">+</span>
                <span className="whitespace-pre-wrap break-all">
                  {playbackState === 'applying'
                    ? FIXED_LINE.slice(0, revealedFixChars)
                    : playbackState === 'awaiting-approval'
                    ? ''
                    : FIXED_LINE}
                </span>
                {playbackState === 'applying' && revealedFixChars < FIXED_LINE.length && (
                  <span className="inline-block w-0.5 h-3.5 bg-green-400 animate-pulse ml-0.5" />
                )}
              </div>
            </div>
          </div>
        )}
      </div>

    </div>
  );
}
