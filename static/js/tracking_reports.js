/* ================================================================
   tracking_reports.js
   Shared mobile behaviour for the PortalXS report screens.

   Opt in from a template with data attributes — no per-page wiring:
     [data-trk-filters-toggle]  toggles the .trk-filters panel
     [data-trk-search]          filters .trk-item rows in the target list
     [data-trk-tab]             switches .trk-pane panels (alerts)
     [data-trk-cards]           builds phone cards from the desktop table
   ================================================================ */
(function () {
  'use strict';

  var MOBILE = 767;

  function isMobile() {
    return window.innerWidth <= MOBILE;
  }

  /* ── Filters panel ────────────────────────────────────────────
     Collapsed on phones whenever the page already has results, so
     the screen opens on data rather than on a form. */
  function initFilters() {
    var toggle = document.querySelector('[data-trk-filters-toggle]');
    var panel = document.getElementById('trkFilters');
    if (!toggle || !panel) return;

    var openByDefault = panel.getAttribute('data-trk-open') === '1';
    var startOpen = !isMobile() || openByDefault;
    panel.classList.toggle('is-open', startOpen);
    toggle.classList.toggle('is-open', startOpen);
    toggle.setAttribute('aria-expanded', startOpen ? 'true' : 'false');

    toggle.addEventListener('click', function () {
      var open = panel.classList.toggle('is-open');
      toggle.classList.toggle('is-open', open);
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) {
        panel.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    });

    // Desktop must always show the filters even if the phone collapsed them.
    window.addEventListener('resize', function () {
      if (!isMobile()) panel.classList.add('is-open');
    });
  }

  /* A day heading whose alerts were all filtered out would otherwise sit
     above the next day's rows and mislabel them. */
  function hideEmptyDayHeadings(scope) {
    scope.querySelectorAll('.trk-feed-day').forEach(function (heading) {
      var visible = false;
      var node = heading.nextElementSibling;
      while (node && !node.classList.contains('trk-feed-day')) {
        if (node.style.display !== 'none') {
          visible = true;
          break;
        }
        node = node.nextElementSibling;
      }
      heading.style.display = visible ? '' : 'none';
    });
  }

  /* ── Mobile list search ─────────────────────────────────────── */
  function initSearch() {
    document.querySelectorAll('[data-trk-search]').forEach(function (input) {
      var list = document.getElementById(input.getAttribute('data-trk-search'));
      if (!list) return;
      var countEl = input.getAttribute('data-trk-count')
        ? document.getElementById(input.getAttribute('data-trk-count'))
        : null;
      var timer;

      input.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(function () {
          var words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
          var shown = 0;
          list.querySelectorAll('.trk-item, .trk-alert').forEach(function (item) {
            var text = item.textContent.toLowerCase();
            var match = words.every(function (w) { return text.indexOf(w) >= 0; });
            item.style.display = match ? '' : 'none';
            if (match) shown += 1;
          });
          hideEmptyDayHeadings(list);
          if (countEl) countEl.textContent = shown + ' shown';
        }, 180);
      });
    });
  }

  /* ── Tab panes (alerts: current vs history) ─────────────────── */
  function initTabs() {
    var tabs = Array.prototype.slice.call(document.querySelectorAll('[data-trk-tab]'));
    if (!tabs.length) return;

    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        var target = tab.getAttribute('data-trk-tab');
        tabs.forEach(function (t) {
          t.classList.toggle('is-active', t === tab);
        });
        document.querySelectorAll('.trk-pane').forEach(function (pane) {
          pane.hidden = pane.getAttribute('data-trk-pane') !== target;
        });
      });
    });
  }

  /* ── Cards built from the desktop table ─────────────────────────
     Long reports (thousands of GPS points) must not ship a second
     copy of every row in the HTML, so the phone view is generated
     from the table that is already there. Presentation is configured
     once on the table by column index — nothing per row.

       data-trk-cards            id of the target .trk-list
       data-trk-card-title       column index used as the card title
       data-trk-card-lead        column index shown as the header badge
       data-trk-card-lead-suffix text appended to the badge
       data-trk-card-class-from  copy this column's classes onto the card
       data-trk-card-skip        comma-separated column indexes to omit
       data-trk-card-full        column indexes rendered full width    */
  function parseIndexes(value) {
    return (value || '').split(',')
      .map(function (n) { return parseInt(n, 10); })
      .filter(function (n) { return !isNaN(n); });
  }

  function buildCardsFromTable(table) {
    var list = document.getElementById(table.getAttribute('data-trk-cards'));
    if (!list || list.dataset.trkBuilt) return;

    var headers = [];
    table.querySelectorAll('thead th, thead td').forEach(function (th) {
      headers.push(th.textContent.trim());
    });
    var skip = parseIndexes(table.getAttribute('data-trk-card-skip'));
    var full = parseIndexes(table.getAttribute('data-trk-card-full'));
    var titleCol = parseInt(table.getAttribute('data-trk-card-title'), 10);
    var leadCol = parseInt(table.getAttribute('data-trk-card-lead'), 10);
    var leadSuffix = table.getAttribute('data-trk-card-lead-suffix') || '';
    var classCol = parseInt(table.getAttribute('data-trk-card-class-from'), 10);
    var frag = document.createDocumentFragment();

    table.querySelectorAll('tbody tr').forEach(function (row) {
      var cells = row.querySelectorAll('td');
      if (!cells.length) return;

      var card = document.createElement('div');
      card.className = 'trk-item';
      var classSource = !isNaN(classCol) && cells[classCol];
      if (classSource) card.className += ' ' + classSource.className;
      if (row.dataset.trkClass) card.className += ' ' + row.dataset.trkClass;

      var head = document.createElement('div');
      head.className = 'trk-item-head';
      var titleCell = !isNaN(titleCol) && cells[titleCol];
      var title = document.createElement('span');
      title.className = 'trk-item-title';
      title.textContent = row.dataset.trkTitle
        || (titleCell ? titleCell.textContent.trim() : cells[0].textContent.trim());
      head.appendChild(title);

      var leadCell = !isNaN(leadCol) && cells[leadCol];
      var leadText = row.dataset.trkLead
        || (leadCell ? leadCell.textContent.trim() + leadSuffix : '');
      if (leadText) {
        var lead = document.createElement('span');
        lead.className = 'trk-item-lead';
        lead.textContent = leadText;
        head.appendChild(lead);
      }

      var grid = document.createElement('div');
      grid.className = 'trk-item-grid';
      cells.forEach(function (cell, i) {
        if (skip.indexOf(i) >= 0) return;
        var cellDiv = document.createElement('div');
        cellDiv.className = 'trk-cell' + (full.indexOf(i) >= 0 ? ' is-full' : '');
        var label = document.createElement('span');
        label.className = 'trk-cell-label';
        label.textContent = headers[i] || '';
        var val = document.createElement('span');
        val.className = 'trk-cell-val';
        val.innerHTML = cell.innerHTML;
        cellDiv.appendChild(label);
        cellDiv.appendChild(val);
        grid.appendChild(cellDiv);
      });

      card.appendChild(head);
      card.appendChild(grid);
      frag.appendChild(card);
    });

    list.appendChild(frag);
    list.dataset.trkBuilt = '1';
  }

  function initTableCards() {
    if (!isMobile()) return;
    document.querySelectorAll('table[data-trk-cards]').forEach(buildCardsFromTable);
  }

  function init() {
    initFilters();
    initTableCards();
    initSearch();
    initTabs();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
