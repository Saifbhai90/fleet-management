/**
 * Tool Workstation — header, search, drawer, homepage filters.
 */
(function () {
  function tools() {
    try {
      return JSON.parse(window.TW_TOOLS_JSON || '[]');
    } catch (e) {
      return [];
    }
  }

  function toolHref(slug) {
    return '/admin/tool-workstation/tool/' + encodeURIComponent(slug);
  }

  function initDrawer() {
    var drawer = document.getElementById('twDrawer');
    if (!drawer) return;
    var open = function () {
      drawer.setAttribute('aria-hidden', 'false');
    };
    var close = function () {
      drawer.setAttribute('aria-hidden', 'true');
    };
    document.getElementById('twMenuToggle')?.addEventListener('click', open);
    document.getElementById('twDrawerClose')?.addEventListener('click', close);
    document.getElementById('twDrawerBackdrop')?.addEventListener('click', close);
    var links = document.getElementById('twDrawerLinks');
    if (links) {
      tools().forEach(function (t) {
        var a = document.createElement('a');
        a.href = toolHref(t.slug);
        a.textContent = t.name;
        links.appendChild(a);
      });
    }
  }

  function filterHome(query, category) {
    var cards = document.querySelectorAll('[data-tw-card]');
    var sections = document.querySelectorAll('[data-tw-section]');
    var any = false;
    var ranked = query ? window.TWFuzzy.rankTools(query, tools()) : null;
    var allowed = ranked ? new Set(ranked.map(function (t) { return t.slug; })) : null;

    cards.forEach(function (card) {
      var cat = card.getAttribute('data-category');
      var slug = card.getAttribute('data-slug');
      var matchCat = !category || category === 'all' || cat === category;
      var matchQ = !allowed || allowed.has(slug);
      var show = matchCat && matchQ;
      card.hidden = !show;
      if (show) any = true;
    });

    sections.forEach(function (sec) {
      var cat = sec.getAttribute('data-tw-section');
      var visible = sec.querySelector('[data-tw-card]:not([hidden])');
      sec.hidden = !visible && (category === 'all' || !category || cat === category);
    });

    var empty = document.getElementById('twEmpty');
    if (empty) empty.hidden = any;
  }

  function initSearch() {
    var input = document.getElementById('twGlobalSearch');
    if (!input) return;
    var cat = 'all';
    document.querySelectorAll('[data-tw-filter]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        document.querySelectorAll('[data-tw-filter]').forEach(function (b) {
          b.classList.remove('active');
        });
        btn.classList.add('active');
        cat = btn.getAttribute('data-tw-filter') || 'all';
        filterHome(input.value.trim(), cat);
      });
    });
    input.addEventListener('input', function () {
      filterHome(input.value.trim(), cat);
    });
    document.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        input.focus();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initDrawer();
    if (window.TW_PAGE === 'index') initSearch();
  });
})();
