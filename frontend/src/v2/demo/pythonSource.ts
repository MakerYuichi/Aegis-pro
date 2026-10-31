// Lines 108-130 of requests/status_codes.py from psf/requests.
// startLineNumber = 108. Line 116 = index 8 (0-based) = the __doc__ concatenation.
export const PYTHON_SOURCE_LINES: string[] = [
  '# Informational.',                                          // 108
  '_codes = {',                                                // 109
  "    100: ('continue',),",                                   // 110
  "    101: ('switching_protocols',),",                        // 111
  "    102: ('processing',),",                                 // 112
  "    200: ('ok', 'okay', 'all_ok', r'\\o/'),",              // 113
  "    201: ('created',),",                                    // 114
  "    204: ('no_content',),",                                 // 115
  "__doc__ = (__doc__ + '\\n' + _codes_str)",                  // 116 ← BUG LINE
  "    301: ('moved_permanently', 'moved', r'\\o-'),",         // 117
  "    302: ('found',),",                                      // 118
  "    304: ('not_modified',),",                               // 119
  "    400: ('bad_request', 'bad'),",                          // 120
  "    401: ('unauthorized',),",                               // 121
  "    403: ('forbidden',),",                                  // 122
  "    404: ('not_found', '-o-'),",                            // 123
  "    500: ('internal_server_error', 'server_error', r'/o\\', r'\\u2717'),", // 124
  '}',                                                         // 125
  '',                                                          // 126
  "_codes_str = '\\n'.join([",                                 // 127
  "    '{} ({})'.format(code, ', '.join(titles))",             // 128
  '    for code, titles in sorted(_codes.items())',            // 129
  '])',                                                        // 130
];

export const START_LINE_NUMBER = 108;
