// Syntax highlighting for the page's Source pane, with the desktop editor's rules
// (wiret/syntax.py, which the page gets from webapi.syntax): the same token pattern, word
// lists and tags. It runs in JavaScript so the colours keep up with every keystroke. No DOM
// code, so Node can test it against the Python rules.

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;" };
const escape = (s) => s.replace(/[&<>]/g, (c) => ESC[c]);

/** rules: {pattern, keywords, kinds}. Returns {spans(line), html(text)}. */
export function makeHighlighter(rules) {
  const token = new RegExp(rules.pattern, "g");
  const keywords = new Set(rules.keywords), kinds = new Set(rules.kinds);

  // as syntax.tag_of
  const tagOf = (t) => {
    if (t.startsWith('"')) return "str";
    if (t.startsWith("//")) return "comment";
    if (t.startsWith("@") || t.startsWith("#[") || t === "]") return "attr";
    if (/^[0-9-]/.test(t)) return "num";
    if (keywords.has(t)) return "kw";
    if (kinds.has(t)) return "kind";
    return null;
  };

  /** [start, end, tag] for each coloured token in one line, as syntax.spans. */
  const spans = (line) => {
    const out = [];
    token.lastIndex = 0;
    for (let m; (m = token.exec(line)); ) {
      if (!m[0]) { token.lastIndex++; continue; }
      let tag = tagOf(m[0]);
      if (tag === "kw") {      // as syntax.is_name: next to `.` or before a single `:`, a name
        const before = line.slice(0, m.index).trimEnd(), after = line.slice(m.index + m[0].length);
        const rest = after.trimStart();
        if (before.endsWith(".") || after.startsWith(".") || after.startsWith("(") ||
            (rest.startsWith(":") && !rest.startsWith("::"))) tag = null;
      }
      if (tag) out.push([m.index, m.index + m[0].length, tag]);
    }
    return out;
  };

  /** The text as HTML, each coloured token in a <span class="t-TAG">. */
  const html = (text) => text.split("\n").map((line) => {
    let s = "", at = 0;
    for (const [a, b, tag] of spans(line)) {
      s += escape(line.slice(at, a)) + `<span class="t-${tag}">${escape(line.slice(a, b))}</span>`;
      at = b;
    }
    return s + escape(line.slice(at));
  }).join("\n");

  return { spans, html };
}
