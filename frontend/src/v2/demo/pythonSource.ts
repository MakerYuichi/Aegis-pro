// Excerpt from psf/requests — requests/status_codes.py
// START_LINE_NUMBER = 100. Line 116 = index 16 (0-based).
// The __doc__ concatenation at line 116 is the bug site.
export const START_LINE_NUMBER = 100;

export const PYTHON_SOURCE_LINES: string[] = [
  '# -*- coding: utf-8 -*-',                                              // 100
  '',                                                                      // 101
  'from .structures import LookupDict',                                   // 102
  '',                                                                      // 103
  '_codes = {',                                                            // 104
  "    100: ('continue',),",                                               // 105
  "    200: ('ok', 'okay', 'all_ok', r'\\o/'),",                          // 106
  "    201: ('created',),",                                                // 107
  "    204: ('no_content',),",                                             // 108
  "    301: ('moved_permanently', 'moved', r'\\o-'),",                     // 109
  "    302: ('found',),",                                                  // 110
  "    400: ('bad_request', 'bad'),",                                      // 111
  "    401: ('unauthorized',),",                                           // 112
  "    404: ('not_found', '-o-'),",                                        // 113
  "    500: ('internal_server_error', 'server_error', r'/o\\\\'),",        // 114
  '}',                                                                     // 115
  "__doc__ = (__doc__ + '\\n' + _codes_str)",                              // 116  ← BUG: None + str under -OO
  '',                                                                      // 117
  "_codes_str = '\\n'.join([",                                            // 118
  "    '{} ({})'.format(code, ', '.join(titles))",                         // 119
  "    for code, titles in sorted(_codes.items())",                        // 120
  '])',                                                                    // 121
  '',                                                                      // 122
  "codes = LookupDict(name='status_codes')",                               // 123
  '',                                                                      // 124
  "for code, titles in list(_codes.items()):",                             // 125
  '    for title in titles:',                                              // 126
  '        setattr(codes, title, code)',                                   // 127
];
