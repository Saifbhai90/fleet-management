/**
 * Lightweight fuzzy match for omni-search (no dependencies).
 */
(function (global) {
  function normalize(s) {
    return (s || '').toLowerCase().trim();
  }

  function score(query, text) {
    const q = normalize(query);
    const t = normalize(text);
    if (!q) return 1;
    if (t.includes(q)) return 0.9 + (q.length / t.length) * 0.1;
    let qi = 0;
    let bonus = 0;
    for (let i = 0; i < t.length && qi < q.length; i++) {
      if (t[i] === q[qi]) {
        qi++;
        bonus += 0.05;
      }
    }
    if (qi === q.length) return 0.5 + bonus;
    return 0;
  }

  function rankTools(query, tools) {
    return tools
      .map(function (tool) {
        const blob = [tool.name, tool.slug, tool.category, tool.categoryLabel]
          .concat(tool.keywords || [])
          .join(' ');
        return { tool: tool, s: score(query, blob) };
      })
      .filter(function (r) {
        return r.s > 0.35;
      })
      .sort(function (a, b) {
        return b.s - a.s;
      })
      .map(function (r) {
        return r.tool;
      });
  }

  global.TWFuzzy = { score: score, rankTools: rankTools };
})(typeof window !== 'undefined' ? window : global);
