/**
 * Productivity & developer utilities — 100% client-side.
 */
(function (global) {
  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  function panel(title) {
    var p = el('div', 'tw-panel');
    if (title) p.appendChild(el('label', '', title));
    return p;
  }

  function actions() {
    return el('div', 'tw-actions');
  }

  function status(msg, ok) {
    var s = el('p', 'tw-status ' + (ok ? 'ok' : 'error'));
    s.textContent = msg;
    return s;
  }

  function readTextarea(p, id) {
    return (p.querySelector('#' + id) || {}).value || '';
  }

  /* Minimal MD5 (RFC 1321) for client-side hashing */
  function md5(s) {
    function cmn(q, a, b, x, s, t) {
      a = (a + q + x + t) | 0;
      return (((a << s) | (a >>> (32 - s))) + b) | 0;
    }
    function ff(a, b, c, d, x, s, t) { return cmn((b & c) | (~b & d), a, b, x, s, t); }
    function gg(a, b, c, d, x, s, t) { return cmn((b & d) | (c & d), a, b, x, s, t); }
    function hh(a, b, c, d, x, s, t) { return cmn(b ^ c ^ d, a, b, x, s, t); }
    function ii(a, b, c, d, x, s, t) { return cmn(c ^ (b | ~d), a, b, x, s, t); }
    var i, len = s.length, words = [], tail = [0x80];
    for (i = 0; i < len; i++) words[i >> 2] |= s.charCodeAt(i) << ((i % 4) * 8);
    words[len >> 2] |= 0x80 << ((len % 4) * 8);
    words[(((len + 8) >> 6) << 4) + 14] = len * 8;
    var a = 1732584193, b = -271733879, c = -1732584194, d = 271733878;
    for (i = 0; i < words.length; i += 16) {
      var oa = a, ob = b, oc = c, od = d;
      a = ff(a, b, c, d, words[i], 7, -680876936);
      d = ff(d, a, b, c, words[i + 1], 12, -389564586);
      c = ff(c, d, a, b, words[i + 2], 17, 606105819);
      b = ff(b, c, d, a, words[i + 3], 22, -1044525330);
      a = ff(a, b, c, d, words[i + 4], 7, -176418897);
      d = ff(d, a, b, c, words[i + 5], 12, 1200080426);
      c = ff(c, d, a, b, words[i + 6], 17, -1473231341);
      b = ff(b, c, d, a, words[i + 7], 22, -45705983);
      a = ff(a, b, c, d, words[i + 8], 7, 1770035416);
      d = ff(d, a, b, c, words[i + 9], 12, -1958414417);
      c = ff(c, d, a, b, words[i + 10], 17, -42063);
      b = ff(b, c, d, a, words[i + 11], 22, -1990404162);
      a = ff(a, b, c, d, words[i + 12], 7, 1804603682);
      d = ff(d, a, b, c, words[i + 13], 12, -40341101);
      c = ff(c, d, a, b, words[i + 14], 17, -1502002290);
      b = ff(b, c, d, a, words[i + 15], 22, 1236535329);
      a = gg(a, b, c, d, words[i + 1], 5, -165796510);
      d = gg(d, a, b, c, words[i + 6], 9, -1069501632);
      c = gg(c, d, a, b, words[i + 11], 14, 643717713);
      b = gg(b, c, d, a, words[i], 20, -373897302);
      a = gg(a, b, c, d, words[i + 5], 5, -701558691);
      d = gg(d, a, b, c, words[i + 10], 9, 38016083);
      c = gg(c, d, a, b, words[i + 15], 14, -660478335);
      b = gg(b, c, d, a, words[i + 4], 20, -405537848);
      a = gg(a, b, c, d, words[i + 9], 5, 568446438);
      d = gg(d, a, b, c, words[i + 14], 9, -1019803690);
      c = gg(c, d, a, b, words[i + 3], 14, -187363961);
      b = gg(b, c, d, a, words[i + 8], 20, 1163531501);
      a = gg(a, b, c, d, words[i + 13], 5, -1444681467);
      d = gg(d, a, b, c, words[i + 2], 9, -51403784);
      c = gg(c, d, a, b, words[i + 7], 14, 1735328473);
      b = gg(b, c, d, a, words[i + 12], 20, -1926607734);
      a = hh(a, b, c, d, words[i + 5], 4, -378558);
      d = hh(d, a, b, c, words[i + 8], 11, -2022574463);
      c = hh(c, d, a, b, words[i + 11], 16, 1839030562);
      b = hh(b, c, d, a, words[i + 14], 23, -35309556);
      a = hh(a, b, c, d, words[i + 1], 4, -1530992060);
      d = hh(d, a, b, c, words[i + 4], 11, 1272893353);
      c = hh(c, d, a, b, words[i + 7], 16, -155497632);
      b = hh(b, c, d, a, words[i + 10], 23, -1094730640);
      a = hh(a, b, c, d, words[i + 13], 4, 681279174);
      d = hh(d, a, b, c, words[i], 11, -358537222);
      c = hh(c, d, a, b, words[i + 3], 16, -722521979);
      b = hh(b, c, d, a, words[i + 6], 23, 76029189);
      a = hh(a, b, c, d, words[i + 9], 4, -640364487);
      d = hh(d, a, b, c, words[i + 12], 11, -421815835);
      c = hh(c, d, a, b, words[i + 15], 16, 530742520);
      b = hh(b, c, d, a, words[i + 2], 23, -995338651);
      a = ii(a, b, c, d, words[i], 6, -198630844);
      d = ii(d, a, b, c, words[i + 7], 10, 1126891415);
      c = ii(c, d, a, b, words[i + 14], 15, -1416354905);
      b = ii(b, c, d, a, words[i + 5], 21, -57434055);
      a = ii(a, b, c, d, words[i + 12], 6, 1700485571);
      d = ii(d, a, b, c, words[i + 3], 10, -1894986606);
      c = ii(c, d, a, b, words[i + 10], 15, -1051523);
      b = ii(b, c, d, a, words[i + 1], 21, -2054922799);
      a = ii(a, b, c, d, words[i + 8], 6, 1873313359);
      d = ii(d, a, b, c, words[i + 15], 10, -30611744);
      c = ii(c, d, a, b, words[i + 6], 15, -1560198380);
      b = ii(b, c, d, a, words[i + 13], 21, 1309151649);
      a = ii(a, b, c, d, words[i + 4], 6, -145523070);
      d = ii(d, a, b, c, words[i + 11], 10, -1120210379);
      c = ii(c, d, a, b, words[i + 2], 15, 718787259);
      b = ii(b, c, d, a, words[i + 9], 21, -343485551);
      a = (a + oa) | 0; b = (b + ob) | 0; c = (c + oc) | 0; d = (d + od) | 0;
    }
    function hex(n) {
      return ('00000000' + (n >>> 0).toString(16)).slice(-8);
    }
    return hex(a) + hex(b) + hex(c) + hex(d);
  }

  async function sha256(text) {
    var buf = new TextEncoder().encode(text);
    var hash = await crypto.subtle.digest('SHA-256', buf);
    return Array.from(new Uint8Array(hash)).map(function (b) {
      return b.toString(16).padStart(2, '0');
    }).join('');
  }

  function textIO(mount, placeholder) {
    var p = panel('Input');
    var ta = document.createElement('textarea');
    ta.id = 'twTextIn';
    ta.placeholder = placeholder || 'Paste or type here…';
    p.appendChild(ta);
    var out = document.createElement('textarea');
    out.id = 'twTextOut';
    out.readOnly = true;
    out.placeholder = 'Output…';
    mount.appendChild(p);
    mount.appendChild(panel('Output')).appendChild(out);
    return { in: ta, out: out };
  }

  var handlers = {
    'json-validate': function (m) {
      var io = textIO(m, '{"example": true}');
      var act = actions();
      var btn = document.createElement('button');
      btn.textContent = 'Validate JSON';
      act.appendChild(btn);
      m.appendChild(act);
      btn.onclick = function () {
        try {
          JSON.parse(io.in.value);
          io.out.value = 'Valid JSON ✓';
          m.appendChild(status('JSON is valid.', true));
        } catch (e) {
          io.out.value = 'Invalid: ' + e.message;
        }
      };
    },
    'url-encode': function (m) {
      var io = textIO(m);
      m.appendChild(actions()).querySelector('.tw-actions') ||
        m.appendChild(actions());
      var btn = document.createElement('button');
      btn.textContent = 'Encode';
      m.querySelector('.tw-actions')?.appendChild(btn) || m.appendChild(btn);
      btn.onclick = function () { io.out.value = encodeURIComponent(io.in.value); };
    },
    'url-decode': function (m) {
      var io = textIO(m);
      var btn = document.createElement('button');
      btn.textContent = 'Decode';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        try { io.out.value = decodeURIComponent(io.in.value); }
        catch (e) { io.out.value = e.message; }
      };
    },
    'md5': function (m) {
      var io = textIO(m);
      var btn = document.createElement('button');
      btn.textContent = 'Generate MD5';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () { io.out.value = md5(io.in.value); };
    },
    'sha256': function (m) {
      var io = textIO(m);
      var btn = document.createElement('button');
      btn.textContent = 'Generate SHA-256';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = async function () {
        io.out.value = await sha256(io.in.value);
      };
    },
    'jwt-decode': function (m) {
      var io = textIO(m, 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...');
      var btn = document.createElement('button');
      btn.textContent = 'Decode JWT';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var parts = io.in.value.trim().split('.');
        if (parts.length < 2) { io.out.value = 'Invalid JWT'; return; }
        function dec(s) {
          s = s.replace(/-/g, '+').replace(/_/g, '/');
          return JSON.parse(atob(s));
        }
        io.out.value = JSON.stringify({ header: dec(parts[0]), payload: dec(parts[1]) }, null, 2);
      };
    },
    'regex-test': function (m) {
      var p = panel('Regex pattern');
      var pat = document.createElement('input');
      pat.id = 'twRegex';
      p.appendChild(pat);
      var io = textIO(m, 'Text to test');
      var btn = document.createElement('button');
      btn.textContent = 'Test';
      m.insertBefore(p, m.firstChild);
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        try {
          var re = new RegExp(pat.value, 'g');
          var mch = io.in.value.match(re);
          io.out.value = mch ? mch.join('\n') : '(no matches)';
        } catch (e) { io.out.value = e.message; }
      };
    },
    'lorem': function (m) {
      var words = 'lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor'.split(' ');
      var p = panel('Paragraphs');
      var n = document.createElement('input');
      n.type = 'number'; n.value = '3'; n.min = '1'; n.max = '20';
      p.appendChild(n);
      var out = document.createElement('textarea');
      out.readOnly = true;
      m.appendChild(p);
      m.appendChild(panel('Output')).appendChild(out);
      var btn = document.createElement('button');
      btn.textContent = 'Generate';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var paras = [];
        for (var i = 0; i < +n.value; i++) {
          var s = [];
          for (var j = 0; j < 40; j++) s.push(words[Math.floor(Math.random() * words.length)]);
          paras.push(s.join(' ').replace(/^\w/, function (c) { return c.toUpperCase(); }) + '.');
        }
        out.value = paras.join('\n\n');
      };
    },
    'case-convert': function (m) {
      var io = textIO(m);
      var sel = document.createElement('select');
      ['lower', 'UPPER', 'Title Case', 'camelCase', 'snake_case'].forEach(function (o) {
        var opt = document.createElement('option');
        opt.value = o; opt.textContent = o; sel.appendChild(opt);
      });
      m.insertBefore(panel('Mode'), m.firstChild).appendChild(sel);
      var btn = document.createElement('button');
      btn.textContent = 'Convert';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var t = io.in.value;
        var mode = sel.value;
        if (mode === 'lower') io.out.value = t.toLowerCase();
        else if (mode === 'UPPER') io.out.value = t.toUpperCase();
        else if (mode === 'snake_case') io.out.value = t.replace(/\s+/g, '_').toLowerCase();
        else if (mode === 'camelCase') {
          io.out.value = t.replace(/(?:^\w|[A-Z]|\b\w)/g, function (w, i) {
            return i === 0 ? w.toLowerCase() : w.toUpperCase();
          }).replace(/\s+/g, '');
        } else {
          io.out.value = t.replace(/\w\S*/g, function (txt) {
            return txt.charAt(0).toUpperCase() + txt.substr(1).toLowerCase();
          });
        }
      };
    },
    'diff': function (m) {
      var a = panel('Text A'); var ta = document.createElement('textarea'); ta.id = 'twA'; a.appendChild(ta);
      var b = panel('Text B'); var tb = document.createElement('textarea'); tb.id = 'twB'; b.appendChild(tb);
      var out = document.createElement('pre');
      m.appendChild(a); m.appendChild(b); m.appendChild(out);
      var btn = document.createElement('button');
      btn.textContent = 'Compare lines';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var la = ta.value.split('\n'), lb = tb.value.split('\n');
        var max = Math.max(la.length, lb.length);
        var lines = [];
        for (var i = 0; i < max; i++) {
          if (la[i] !== lb[i]) lines.push('- ' + (la[i] || '') + '\n+ ' + (lb[i] || ''));
        }
        out.textContent = lines.length ? lines.join('\n') : 'No differences.';
      };
    },
    'markdown-preview': function (m) {
      var io = textIO(m, '# Heading\n\n**bold** text');
      var prev = el('div', 'tw-seo-block');
      m.appendChild(prev);
      var btn = document.createElement('button');
      btn.textContent = 'Render';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        prev.innerHTML = global.marked ? marked.parse(io.in.value) : io.in.value.replace(/\n/g, '<br>');
      };
    },
    'timestamp': function (m) {
      var p = panel('Unix timestamp or ISO date');
      var inp = document.createElement('input');
      inp.placeholder = 'Leave empty for now';
      p.appendChild(inp);
      var out = document.createElement('textarea');
      out.readOnly = true;
      m.appendChild(p);
      m.appendChild(panel('Result')).appendChild(out);
      var btn = document.createElement('button');
      btn.textContent = 'Convert';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var v = inp.value.trim();
        var d = v ? (isNaN(v) ? new Date(v) : new Date(+v * 1000)) : new Date();
        out.value = 'ISO: ' + d.toISOString() + '\nUnix: ' + Math.floor(d.getTime() / 1000);
      };
    },
    'uuid': function (m) {
      var out = document.createElement('textarea');
      out.readOnly = true;
      m.appendChild(panel('UUIDs')).appendChild(out);
      var btn = document.createElement('button');
      btn.textContent = 'Generate 5 UUIDs';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        out.value = Array.from({ length: 5 }, function () {
          return crypto.randomUUID();
        }).join('\n');
      };
    },
    'password-gen': function (m) {
      var len = document.createElement('input');
      len.type = 'number'; len.value = '16';
      m.appendChild(panel('Length')).appendChild(len);
      var out = document.createElement('input');
      out.readOnly = true;
      m.appendChild(panel('Password')).appendChild(out);
      var btn = document.createElement('button');
      btn.textContent = 'Generate';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*';
        var p = '';
        var arr = new Uint32Array(+len.value);
        crypto.getRandomValues(arr);
        for (var i = 0; i < arr.length; i++) p += chars[arr[i] % chars.length];
        out.value = p;
      };
    },
    'box-shadow': function (m) {
      var x = document.createElement('input'); x.type = 'range'; x.min = '-20'; x.max = '20'; x.value = '0';
      var y = document.createElement('input'); y.type = 'range'; y.min = '-20'; y.max = '20'; y.value = '8';
      var b = document.createElement('input'); b.type = 'range'; b.min = '0'; b.max = '40'; b.value = '24';
      ['X', 'Y', 'Blur'].forEach(function (lbl, i) {
        var p = panel(lbl);
        p.appendChild([x, y, b][i]);
        m.appendChild(p);
      });
      var box = el('div', '');
      box.style.cssText = 'width:120px;height:120px;background:#2563eb;border-radius:12px;margin:16px auto';
      var css = document.createElement('input');
      css.readOnly = true;
      m.appendChild(box);
      m.appendChild(css);
      function upd() {
        var v = x.value + 'px ' + y.value + 'px ' + b.value + 'px rgba(37,99,235,0.35)';
        box.style.boxShadow = v;
        css.value = 'box-shadow: ' + v + ';';
      }
      [x, y, b].forEach(function (inp) { inp.oninput = upd; });
      upd();
    },
    'color-convert': function (m) {
      var hex = document.createElement('input');
      hex.value = '#2563eb';
      m.appendChild(panel('Hex')).appendChild(hex);
      var out = document.createElement('textarea');
      out.readOnly = true;
      m.appendChild(panel('Output')).appendChild(out);
      hex.oninput = function () {
        var h = hex.value.replace('#', '');
        if (h.length === 3) h = h.split('').map(function (c) { return c + c; }).join('');
        var r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
        out.value = 'rgb(' + r + ', ' + g + ', ' + b + ')';
      };
      hex.oninput();
    },
    'xml-to-json': function (m) {
      var io = textIO(m, '<root><item>1</item></root>');
      var btn = document.createElement('button');
      btn.textContent = 'Convert';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var xml = new DOMParser().parseFromString(io.in.value, 'text/xml');
        function node(n) {
          if (n.nodeType === 3) return n.textContent.trim() || undefined;
          var o = {};
          Array.from(n.childNodes).forEach(function (c) {
            if (c.nodeType !== 1) return;
            var v = node(c);
            o[c.nodeName] = o[c.nodeName] ? [].concat(o[c.nodeName], v) : v;
          });
          return Object.keys(o).length ? o : n.textContent.trim();
        }
        io.out.value = JSON.stringify(node(xml.documentElement), null, 2);
      };
    },
    'json-to-xml': function (m) {
      var io = textIO(m, '{"name":"Fleet"}');
      var btn = document.createElement('button');
      btn.textContent = 'Convert';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var o = JSON.parse(io.in.value);
        function build(key, val) {
          if (val == null) return '<' + key + '/>';
          if (typeof val !== 'object') return '<' + key + '>' + val + '</' + key + '>';
          if (Array.isArray(val)) return val.map(function (v) { return build(key, v); }).join('');
          return '<' + key + '>' + Object.keys(val).map(function (k) { return build(k, val[k]); }).join('') + '</' + key + '>';
        }
        io.out.value = '<?xml version="1.0"?>\n' + build('root', o);
      };
    },
    'html-encode': function (m) {
      var io = textIO(m);
      m.appendChild(actions()).appendChild(document.createElement('button')).textContent = 'Encode';
      m.querySelector('button').onclick = function () {
        io.out.value = io.in.value.replace(/[&<>"']/g, function (c) {
          return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
        });
      };
    },
    'html-decode': function (m) {
      var io = textIO(m);
      var btn = document.createElement('button');
      btn.textContent = 'Decode';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var d = document.createElement('textarea');
        d.innerHTML = io.in.value;
        io.out.value = d.value;
      };
    },
    'b64-text-encode': function (m) {
      var io = textIO(m);
      var btn = document.createElement('button');
      btn.textContent = 'Encode Base64';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () { io.out.value = btoa(unescape(encodeURIComponent(io.in.value))); };
    },
    'b64-text-decode': function (m) {
      var io = textIO(m);
      var btn = document.createElement('button');
      btn.textContent = 'Decode Base64';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        try { io.out.value = decodeURIComponent(escape(atob(io.in.value.trim()))); }
        catch (e) { io.out.value = e.message; }
      };
    },
    'word-count': function (m) {
      var io = textIO(m);
      var btn = document.createElement('button');
      btn.textContent = 'Count';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var t = io.in.value;
        io.out.value = 'Characters: ' + t.length + '\nWords: ' + (t.trim() ? t.trim().split(/\s+/).length : 0) + '\nLines: ' + (t ? t.split('\n').length : 0);
      };
    },
    'dedupe-lines': function (m) {
      var io = textIO(m);
      var btn = document.createElement('button');
      btn.textContent = 'Deduplicate';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        io.out.value = [...new Set(io.in.value.split('\n'))].join('\n');
      };
    },
    'sort-lines': function (m) {
      var io = textIO(m);
      var btn = document.createElement('button');
      btn.textContent = 'Sort A→Z';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        io.out.value = io.in.value.split('\n').sort(function (a, b) { return a.localeCompare(b); }).join('\n');
      };
    },
    'random-number': function (m) {
      var min = document.createElement('input'); min.type = 'number'; min.value = '1';
      var max = document.createElement('input'); max.type = 'number'; max.value = '100';
      m.appendChild(panel('Min')).appendChild(min);
      m.appendChild(panel('Max')).appendChild(max);
      var out = document.createElement('input');
      out.readOnly = true;
      m.appendChild(panel('Result')).appendChild(out);
      var btn = document.createElement('button');
      btn.textContent = 'Roll';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var a = +min.value, b = +max.value;
        out.value = String(Math.floor(Math.random() * (b - a + 1)) + a);
      };
    },
    'percentage': function (m) {
      var v = document.createElement('input'); v.placeholder = 'Value';
      var p = document.createElement('input'); p.placeholder = 'Percent';
      m.appendChild(panel('Value')).appendChild(v);
      m.appendChild(panel('Percent')).appendChild(p);
      var out = document.createElement('input');
      out.readOnly = true;
      m.appendChild(panel('Result')).appendChild(out);
      var btn = document.createElement('button');
      btn.textContent = 'Calculate';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        out.value = (+v.value * +p.value / 100).toFixed(4);
      };
    },
    'bmi': function (m) {
      var kg = document.createElement('input'); kg.placeholder = 'Weight kg';
      var cm = document.createElement('input'); cm.placeholder = 'Height cm';
      m.appendChild(panel('Weight (kg)')).appendChild(kg);
      m.appendChild(panel('Height (cm)')).appendChild(cm);
      var out = document.createElement('input');
      out.readOnly = true;
      m.appendChild(panel('BMI')).appendChild(out);
      var btn = document.createElement('button');
      btn.textContent = 'Calculate';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var h = (+cm.value) / 100;
        out.value = (h > 0 ? (+kg.value / (h * h)).toFixed(1) : '—');
      };
    },
    'unit-length': function (m) {
      var val = document.createElement('input'); val.value = '1';
      var from = document.createElement('select');
      var to = document.createElement('select');
      var units = { m: 1, km: 1000, cm: 0.01, mm: 0.001, ft: 0.3048, in: 0.0254, mi: 1609.34 };
      Object.keys(units).forEach(function (u) {
        from.appendChild(new Option(u, u));
        to.appendChild(new Option(u, u));
      });
      to.value = 'ft';
      m.appendChild(panel('Value')).appendChild(val);
      m.appendChild(panel('From')).appendChild(from);
      m.appendChild(panel('To')).appendChild(to);
      var out = document.createElement('input');
      out.readOnly = true;
      m.appendChild(panel('Result')).appendChild(out);
      function conv() {
        var meters = +val.value * units[from.value];
        out.value = (meters / units[to.value]).toFixed(6);
      }
      [val, from, to].forEach(function (x) { x.oninput = conv; });
      conv();
    },
    'luhn': function (m) {
      var io = textIO(m, '4111111111111111');
      var btn = document.createElement('button');
      btn.textContent = 'Validate';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var s = io.in.value.replace(/\D/g, '');
        var sum = 0, alt = false;
        for (var i = s.length - 1; i >= 0; i--) {
          var n = +s[i];
          if (alt) { n *= 2; if (n > 9) n -= 9; }
          sum += n; alt = !alt;
        }
        io.out.value = sum % 10 === 0 ? 'Valid (Luhn)' : 'Invalid';
      };
    },
    'iban': function (m) {
      var io = textIO(m, 'GB82WEST12345698765432');
      var btn = document.createElement('button');
      btn.textContent = 'Basic check';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var s = io.in.value.replace(/\s/g, '').toUpperCase();
        io.out.value = /^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$/.test(s) ? 'Format looks valid (full MOD-97 not run)' : 'Invalid IBAN format';
      };
    },
    'cron': function (m) {
      var io = textIO(m, '0 9 * * 1-5');
      var btn = document.createElement('button');
      btn.textContent = 'Explain';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        var p = io.in.value.trim().split(/\s+/);
        if (p.length < 5) { io.out.value = 'Use 5 fields: min hour dom month dow'; return; }
        io.out.value = 'Minute: ' + p[0] + '\nHour: ' + p[1] + '\nDay of month: ' + p[2] + '\nMonth: ' + p[3] + '\nDay of week: ' + p[4];
      };
    },
    'hash-compare': function (m) {
      var a = document.createElement('input');
      var b = document.createElement('input');
      m.appendChild(panel('Hash A')).appendChild(a);
      m.appendChild(panel('Hash B')).appendChild(b);
      var out = document.createElement('input');
      out.readOnly = true;
      m.appendChild(panel('Match')).appendChild(out);
      var btn = document.createElement('button');
      btn.textContent = 'Compare';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        out.value = a.value.trim().toLowerCase() === b.value.trim().toLowerCase() ? 'Match ✓' : 'No match';
      };
    },
    'hmac': function (m) {
      var io = textIO(m);
      var key = document.createElement('input');
      key.placeholder = 'Secret key';
      m.insertBefore(panel('Secret'), m.firstChild).appendChild(key);
      var btn = document.createElement('button');
      btn.textContent = 'HMAC-SHA256 (hex)';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = async function () {
        var k = await crypto.subtle.importKey('raw', new TextEncoder().encode(key.value), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
        var sig = await crypto.subtle.sign('HMAC', k, new TextEncoder().encode(io.in.value));
        io.out.value = Array.from(new Uint8Array(sig)).map(function (b) { return b.toString(16).padStart(2, '0'); }).join('');
      };
    },
    'binary-decode': function (m) {
      var io = textIO(m, '01001000');
      var btn = document.createElement('button');
      btn.textContent = 'Decode';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        io.out.value = io.in.value.replace(/\s/g, '').match(/.{1,8}/g).map(function (b) {
          return String.fromCharCode(parseInt(b, 2));
        }).join('');
      };
    },
    'binary-encode': function (m) {
      var io = textIO(m, 'Hi');
      var btn = document.createElement('button');
      btn.textContent = 'Encode';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        io.out.value = Array.from(io.in.value).map(function (c) {
          return c.charCodeAt(0).toString(2).padStart(8, '0');
        }).join(' ');
      };
    },
    'hex-decode': function (m) {
      var io = textIO(m, '48656c6c6f');
      var btn = document.createElement('button');
      btn.textContent = 'Decode';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        io.out.value = io.in.value.replace(/\s/g, '').match(/.{1,2}/g).map(function (h) {
          return String.fromCharCode(parseInt(h, 16));
        }).join('');
      };
    },
    'hex-encode': function (m) {
      var io = textIO(m, 'Hello');
      var btn = document.createElement('button');
      btn.textContent = 'Encode';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        io.out.value = Array.from(new TextEncoder().encode(io.in.value)).map(function (b) {
          return b.toString(16).padStart(2, '0');
        }).join('');
      };
    },
    'slug': function (m) {
      var io = textIO(m, 'My Page Title');
      var btn = document.createElement('button');
      btn.textContent = 'Generate slug';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        io.out.value = io.in.value.toLowerCase().trim().replace(/[^\w\s-]/g, '').replace(/\s+/g, '-');
      };
    },
    'whitespace': function (m) {
      var io = textIO(m);
      var btn = document.createElement('button');
      btn.textContent = 'Normalize';
      m.appendChild(actions()).appendChild(btn);
      btn.onclick = function () {
        io.out.value = io.in.value.replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
      };
    },
  };

  function init(mount, tool) {
    mount.innerHTML = '';
    var fn = handlers[tool.method];
    if (fn) fn(mount);
    else mount.appendChild(status('Tool UI loading: ' + tool.method, false));
  }

  global.TWTextEngine = { init: init, handlers: handlers };
})(window);
