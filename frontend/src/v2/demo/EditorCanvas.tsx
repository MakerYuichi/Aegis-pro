import { useEffect, useRef } from 'react';
import type { editor } from 'monaco-editor';

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
// Backticks in the docstring are escaped so they don't terminate the template literal.
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

interface EditorCanvasProps {
  showGutterArrow: boolean;
  highlightLine: number;
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
    .aegis-line-highlight {
      background: rgba(251, 191, 36, 0.12);
      outline: 1px solid rgba(251, 191, 36, 0.5);
    }
  `;
  document.head.appendChild(style);
}

export function EditorCanvas({ showGutterArrow, highlightLine }: EditorCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const editorRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const decorationsRef = useRef<string[]>([]);

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

      // Scroll to the bug line
      editorRef.current.revealLineInCenter(highlightLine);

      // Apply permanent highlight on the bug line
      const initialDecorations: editor.IModelDeltaDecoration[] = [
        {
          range: new monaco.Range(highlightLine, 1, highlightLine, 1),
          options: {
            isWholeLine: true,
            className: 'aegis-line-highlight',
          },
        },
      ];
      decorationsRef.current = editorRef.current.deltaDecorations(
        [],
        initialDecorations,
      );
    });

    return () => {
      disposed = true;
      editorRef.current?.dispose();
      editorRef.current = null;
    };
  }, [highlightLine]);

  // Update gutter arrow decoration when showGutterArrow changes
  useEffect(() => {
    if (!editorRef.current) return;

    import('monaco-editor').then((monaco) => {
      if (!editorRef.current) return;

      const newDecorations: editor.IModelDeltaDecoration[] = [
        {
          range: new monaco.Range(highlightLine, 1, highlightLine, 1),
          options: {
            isWholeLine: true,
            className: 'aegis-line-highlight',
          },
        },
      ];

      if (showGutterArrow) {
        newDecorations.push({
          range: new monaco.Range(highlightLine, 1, highlightLine, 1),
          options: {
            isWholeLine: false,
            glyphMarginClassName: 'aegis-gutter-arrow',
          },
        });
      }

      decorationsRef.current = editorRef.current.deltaDecorations(
        decorationsRef.current,
        newDecorations,
      );
    });
  }, [showGutterArrow, highlightLine]);

  return (
    <div className="relative w-full h-full" style={{ minHeight: 0 }}>
      <div ref={containerRef} className="w-full h-full" />
    </div>
  );
}
