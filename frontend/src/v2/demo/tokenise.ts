export type TokenType =
  | 'keyword'
  | 'string'
  | 'comment'
  | 'number'
  | 'operator'
  | 'builtin'
  | 'plain';

export interface Token {
  type: TokenType;
  text: string;
}

const KEYWORDS = new Set([
  'def', 'return', 'if', 'else', 'elif', 'for', 'while', 'import', 'from',
  'class', 'not', 'and', 'or', 'in', 'is', 'None', 'True', 'False', 'pass',
  'raise', 'try', 'except', 'with', 'as', 'lambda', 'yield',
]);

const BUILTINS = new Set([
  'str', 'int', 'list', 'dict', 'tuple', 'set', 'len', 'range', 'print',
  'type', 'isinstance', 'sorted', 'enumerate', 'zip', 'map', 'filter',
]);

// Regex patterns applied in priority order
const PATTERNS: { type: TokenType; re: RegExp }[] = [
  // Triple-quoted strings (must come before single-quoted)
  { type: 'string', re: /^("""[\s\S]*?"""|'''[\s\S]*?''')/  },
  // Single-line strings
  { type: 'string', re: /^("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/ },
  // Comments
  { type: 'comment', re: /^(#.*)/ },
  // Numbers
  { type: 'number', re: /^(\d+(?:\.\d+)?)/ },
  // Identifiers (keywords/builtins resolved after match)
  { type: 'plain', re: /^([A-Za-z_]\w*)/ },
  // Operators and punctuation
  { type: 'operator', re: /^([+\-*=/!<>:,.()\]{}[])/ },
  // Whitespace — keep as plain
  { type: 'plain', re: /^(\s+)/ },
  // Fallback single char
  { type: 'plain', re: /^(.)/ },
];

export function tokenise(line: string): Token[] {
  const tokens: Token[] = [];
  let remaining = line;

  while (remaining.length > 0) {
    let matched = false;

    for (const { type, re } of PATTERNS) {
      const m = re.exec(remaining);
      if (m) {
        const text = m[1];
        let resolvedType: TokenType = type;

        // Resolve keywords and builtins from plain identifier matches
        if (type === 'plain' && /^[A-Za-z_]\w*$/.test(text)) {
          if (KEYWORDS.has(text)) resolvedType = 'keyword';
          else if (BUILTINS.has(text)) resolvedType = 'builtin';
        }

        tokens.push({ type: resolvedType, text });
        remaining = remaining.slice(text.length);
        matched = true;
        break;
      }
    }

    // Safety: consume one char to avoid infinite loop
    if (!matched) {
      tokens.push({ type: 'plain', text: remaining[0] });
      remaining = remaining.slice(1);
    }
  }

  return tokens;
}
