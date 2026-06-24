/* ═══════════════════════════════════════════════════════════════
   Fleet Manager — Mobile JS (extracted from base.html)
   ═══════════════════════════════════════════════════════════════ */

(function() {
    'use strict';

    /* ── inputmode auto-setter for touch keyboards ── */
    function setInputModes() {
        var numPatterns = /salary|amount|mileage|reading|odometer|km|distance|price|cost|rate|qty|quantity|balance|fine|penalty|fuel|liter|litre|hour|day|year/i;
        var telPatterns = /phone|mobile|cell|contact|cnic|whatsapp|emergency/i;
        var emailPatterns = /email/i;

        document.querySelectorAll('input[type="text"], input[type="number"]').forEach(function(inp) {
            if (inp.getAttribute('inputmode')) return; // already set
            var name = (inp.name || inp.id || '').toLowerCase();
            if (emailPatterns.test(name)) {
                inp.setAttribute('inputmode', 'email');
                inp.setAttribute('autocomplete', inp.getAttribute('autocomplete') || 'email');
            } else if (telPatterns.test(name)) {
                inp.setAttribute('inputmode', 'tel');
            } else if (numPatterns.test(name) || inp.type === 'number') {
                inp.setAttribute('inputmode', 'decimal');
            }
        });
    }

    /* ── Detect action column ── */
    function isActionCol(header, td, colIndex, totalCols) {
        var h = (header || '').toLowerCase().trim();
        if (h === 'action' || h === 'actions' || h === '#' || h === '') return false; // '#' is usually row number
        // Last column containing only buttons/links
        if (colIndex === totalCols - 1) {
            var clone = td.cloneNode(true);
            var text = clone.textContent.trim();
            var hasBtn = clone.querySelector('a.btn, button, a[href], form');
            // If almost all content is buttons and minimal text, treat as actions
            if (hasBtn && text.length < 60) return true;
        }
        return false;
    }

    /* ── Build card for one table row ── */
    function buildCard(row, headers, themeClass) {
        var tds = row.querySelectorAll('td');
        if (!tds.length) return null;

        // Single-cell empty/no-data row
        if (tds.length === 1 && (parseInt(tds[0].getAttribute('colspan') || '1') > 1)) {
            var empty = document.createElement('div');
            empty.className = 'mp-card-empty';
            empty.innerHTML = tds[0].innerHTML;
            return empty;
        }

        var card = document.createElement('div');
        card.className = 'mp-card' + (themeClass ? ' ' + themeClass : '');

        var body = document.createElement('div');
        body.className = 'mp-card-body';

        var actionsDiv = null;
        var titleText = '';
        var titleBadgeHTML = '';
        var firstDataIndex = -1;

        tds.forEach(function(td, i) {
            var header = headers[i] || '';
            var headerLow = header.toLowerCase().trim();
            var cellHTML = td.innerHTML.trim();
            var cellText = td.textContent.trim();

            // Skip pure serial number columns
            if ((headerLow === '#' || headerLow === 'sr.' || headerLow === 'sr.no' || headerLow === 'no.') && /^\d+$/.test(cellText)) {
                return;
            }

            // Detect action column (last col with buttons)
            var isAction = isActionCol(header, td, i, tds.length);
            if (isAction) {
                actionsDiv = document.createElement('div');
                actionsDiv.className = 'mp-card-actions';
                // Clone TD children individually so we can fix form display:inline
                Array.from(td.childNodes).forEach(function(node) {
                    var clone = node.cloneNode(true);
                    if (clone.nodeType === 1 && clone.tagName === 'FORM') {
                        clone.style.removeProperty('display');
                    }
                    actionsDiv.appendChild(clone);
                });
                return;
            }

            // First meaningful column → use as card title
            if (firstDataIndex === -1 && cellText) {
                firstDataIndex = i;
                titleText = cellText;
                // Check for badge in second column
                if (headers[i + 1]) {
                    var nextTD = tds[i + 1];
                    if (nextTD) {
                        var badge = nextTD.querySelector('.badge, .badge-sm');
                        if (badge) {
                            titleBadgeHTML = badge.outerHTML;
                        }
                    }
                }
                return; // Title row is shown in card header, skip adding as body row
            }

            // Skip column if its value was used as badge in title
            if (titleBadgeHTML && tds[i - 1] === tds[firstDataIndex] ) return;

            var rowDiv = document.createElement('div');
            rowDiv.className = 'mp-card-row';

            var lbl = document.createElement('span');
            lbl.className = 'mp-card-label';
            lbl.textContent = header;

            var val = document.createElement('span');
            val.className = 'mp-card-val';
            val.innerHTML = cellHTML;

            rowDiv.appendChild(lbl);
            rowDiv.appendChild(val);
            body.appendChild(rowDiv);
        });

        // Card title header
        var titleDiv = document.createElement('div');
        titleDiv.className = 'mp-card-title';
        titleDiv.innerHTML = '<span>' + escapeHTML(titleText || 'Record') + '</span>' +
            (titleBadgeHTML ? '<span class="mp-card-title-badge">' + titleBadgeHTML + '</span>' : '');

        card.appendChild(titleDiv);
        card.appendChild(body);
        if (actionsDiv) card.appendChild(actionsDiv);

        return card;
    }

    function escapeHTML(str) {
        return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    /* ── Detect theme from section-heading background ── */
    function detectTheme(container) {
        var heading = container.querySelector('.section-heading');
        if (!heading) return '';
        var bg = window.getComputedStyle(heading).backgroundColor;
        if (!bg) return '';
        // Green
        if (bg.indexOf('76, 175, 80') !== -1 || bg.indexOf('34, 197, 94') !== -1) return 'mp-theme-green';
        // Purple
        if (bg.indexOf('147, 51, 234') !== -1 || bg.indexOf('139, 92, 246') !== -1) return 'mp-theme-purple';
        // Red/orange
        if (bg.indexOf('220, 53, 69') !== -1 || bg.indexOf('239, 68, 68') !== -1) return 'mp-theme-red';
        // Teal
        if (bg.indexOf('20, 184, 166') !== -1 || bg.indexOf('15, 118, 110') !== -1) return 'mp-theme-teal';
        return 'mp-theme-blue';
    }

    /* ── Main converter ── */
    function buildAllCards() {
        // Broad selector: any table inside a table-responsive OR explicit compact-table
        var tables = Array.from(document.querySelectorAll(
            '.data-table-wrapper table, .table-responsive table, table.compact-table'
        ));
        // Deduplicate (a table may match multiple selectors)
        var seen = new Set();
        tables = tables.filter(function(t) {
            if (seen.has(t)) return false;
            seen.add(t);
            return true;
        });

        tables.forEach(function(tbl) {
            if (tbl.dataset.mpBuilt) return;
            /* Batch forms (e.g. New Task Entry): must keep one DOM tree — footer Save + input listeners.
               Mobile “cards” duplicate cells and hide the whole .card, breaking save + live totals. */
            if (tbl.getAttribute('data-mp-skip-cards') === '1') {
                tbl.dataset.mpBuilt = 'skip-cards';
                return;
            }
            tbl.dataset.mpBuilt = '1';

            // Skip tiny utility tables (< 2 columns or 0 header rows)
            var headers = [];
            tbl.querySelectorAll('thead th, thead td').forEach(function(th) {
                headers.push(th.textContent.trim());
            });
            if (headers.length < 2) return;

            // Detect theme
            var pageContainer = document.querySelector('.container-fluid') || document.body;
            var theme = detectTheme(pageContainer);

            // Build card list
            var cardList = document.createElement('div');
            cardList.className = 'mp-card-list';

            var rows = tbl.querySelectorAll('tbody tr');
            if (rows.length === 0) {
                var empty = document.createElement('div');
                empty.className = 'mp-card-empty';
                empty.textContent = 'No records found.';
                cardList.appendChild(empty);
            }
            rows.forEach(function(row) {
                var card = buildCard(row, headers, theme);
                if (card) cardList.appendChild(card);
            });

            // ── Find the BROADEST wrapper to hide on mobile ──────────────
            // Priority: .data-table-wrapper > .card (data card) > .table-responsive
            var wrapper = tbl.closest('.data-table-wrapper') || null;
            if (!wrapper) {
                // Check if table is in a .card that serves as a data container
                var parentCard = tbl.closest('.card');
                if (parentCard) {
                    // Only treat as data card if it has a card-header or section-heading
                    var hasHeader = parentCard.querySelector('.card-header, .section-heading');
                    if (hasHeader) wrapper = parentCard;
                }
            }
            if (!wrapper) {
                wrapper = tbl.closest('.table-responsive') || tbl.parentNode;
            }

            // Insert cards right AFTER the hidden wrapper
            wrapper.parentNode.insertBefore(cardList, wrapper.nextSibling);
            wrapper.classList.add('mp-hide-mobile');

            // Hide .table-footer sibling (record count bar)
            var sib = wrapper.nextSibling;
            // skip the cardList we just inserted
            if (sib === cardList) sib = cardList.nextSibling;
            if (sib && sib.classList && sib.classList.contains('table-footer')) {
                sib.classList.add('mp-hide-mobile');
                var mf = document.createElement('div');
                mf.className = 'mp-table-footer-mobile';
                mf.innerHTML = sib.innerHTML;
                cardList.after(mf);
            }
        });
    }

    /* ── Multi-word AND match: every word must appear somewhere in text ── */
    function multiWordMatch(text, query) {
        if (!query) return true;
        var words = query.toLowerCase().split(/\s+/).filter(Boolean);
        var lower = text.toLowerCase();
        for (var i = 0; i < words.length; i++) {
            if (lower.indexOf(words[i]) === -1) return false;
        }
        return true;
    }

    /* ── Add search bar above each card list ── */
    function addCardSearch() {
        if (window.innerWidth > 767) return;
        document.querySelectorAll('.mp-card-list').forEach(function(list) {
            if (list.dataset.mpSearchDone) return;
            list.dataset.mpSearchDone = '1';

            var cards = list.querySelectorAll('.mp-card');
            if (cards.length < 3) return;

            var wrap = document.createElement('div');
            wrap.className = 'mp-search-wrap';
            var inp = document.createElement('input');
            inp.type = 'search';
            inp.className = 'mp-search-input';
            inp.placeholder = 'Search...';
            inp.setAttribute('autocomplete', 'off');
            inp.setAttribute('autocorrect', 'off');
            inp.setAttribute('spellcheck', 'false');

            var countEl = document.createElement('span');
            countEl.className = 'mp-search-count';
            countEl.textContent = cards.length + ' records';

            wrap.appendChild(inp);
            wrap.appendChild(countEl);
            list.parentNode.insertBefore(wrap, list);

            var debounce;
            inp.addEventListener('input', function() {
                clearTimeout(debounce);
                debounce = setTimeout(function() {
                    var q = inp.value.trim();
                    var shown = 0;
                    cards.forEach(function(card) {
                        if (multiWordMatch(card.textContent, q)) {
                            card.style.display = '';
                            shown++;
                        } else {
                            card.style.display = 'none';
                        }
                    });
                    countEl.textContent = q ? (shown + ' / ' + cards.length) : (cards.length + ' records');
                }, 150);
            });
        });
    }

    /* ── Run on DOM ready ── */
    function init() {
        setInputModes();
        buildAllCards();
        addCardSearch();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

/* ── Section separator ── */

/* ── Block with Jinja2 statements, kept inline in base.html ── */

/* ── Section separator ── */

/* ── Block with Jinja2 statements, kept inline in base.html ── */

/* ── Resume path after native camera / file picker ── */

/* ═══════════════════════════════════════════════════════════════════
   Resume path after native camera / file picker (localStorage + cookie).
   Survives Android WebView process kill; returns user to Task Report etc.
   ═══════════════════════════════════════════════════════════════════ */
(function() {
  'use strict';
  var FLEET_RESUME_KEY = 'fleet_resume_url';
  var FLEET_RESUME_ROW = 'fleet_resume_odom_row';
  var FLEET_RESUME_TS = 'fleet_resume_ts';
  var RESUME_MAX_AGE_MS = 30 * 60 * 1000;

  function _resumeCookieSuffix() {
    return (location.protocol === 'https:') ? '; Secure' : '';
  }

  window.fleetClearResumePath = function() {
    try {
      localStorage.removeItem(FLEET_RESUME_KEY);
      localStorage.removeItem(FLEET_RESUME_ROW);
      localStorage.removeItem(FLEET_RESUME_TS);
      document.cookie = 'fleet_resume_path=; path=/; max-age=0; SameSite=Lax' + _resumeCookieSuffix();
    } catch (e) { /* ignore */ }
  };

  window.fleetSetResumePath = function(opts) {
    opts = opts || {};
    try {
      var url = location.pathname + location.search + location.hash;
      localStorage.setItem(FLEET_RESUME_KEY, url);
      localStorage.setItem(FLEET_RESUME_TS, String(Date.now()));
      if (opts.odomRow) localStorage.setItem(FLEET_RESUME_ROW, String(opts.odomRow));
      else localStorage.removeItem(FLEET_RESUME_ROW);
      document.cookie = 'fleet_resume_path=' + encodeURIComponent(url) + '; path=/; max-age=1800; SameSite=Lax' + _resumeCookieSuffix();
    } catch (e) { /* ignore */ }
  };

  /* Auto-restore of Task Report after login was a source of bugs (app would reopen an
     unfinished report instead of the dashboard). Resume redirect is now disabled:
     after any login the user always lands on the dashboard. The setter/clearer are kept
     as harmless no-op-ish helpers so existing call sites (camera/file picker) don't error,
     but nothing reads the marker to perform a redirect anymore. */
  window.fleetHasPendingNativeResume = function() { return false; };

  window.fleetApplyResumeRedirect = function() {
    try { window.fleetClearResumePath(); } catch (e) { /* ignore */ }
    return false;
  };
})();

/* ═══════════════════════════════════════════════════════════════════
   App Lifecycle (Capacitor): a NEW WebView process has empty sessionStorage.
   If it restores a logged-in URL with a still-valid cookie (force-close reopen,
   OS-killed process), force /mobile-init → login → dashboard. Same-process
   navigations (incl. returning from the camera) keep _fleetAppSession and stay put.
   ═══════════════════════════════════════════════════════════════════ */
(function() {
  'use strict';
  if (!window.Capacitor || Capacitor.getPlatform() === 'web') return;

  var SESSION_KEY = '_fleetAppSession';
  var currentPath = window.location.pathname;

  if (sessionStorage.getItem(SESSION_KEY)) return;

  var qs = window.location.search || '';
  if (qs.indexOf('from_login=1') !== -1) {
    sessionStorage.setItem(SESSION_KEY, '1');
    return;
  }

  sessionStorage.setItem(SESSION_KEY, '1');

  if (window.FleetConfig.userId) { window.location.replace('/mobile-init');
  return; }

  if (currentPath === '/mobile-init' || currentPath === '/login') return;
  window.location.replace('/mobile-init');
})();

/* ═══════════════════════════════════════════════════════════════════
   Save logged-in user info to localStorage for HBL login view
   Runs on every native page load when user is logged in.
   This sets fleet_saved_name so the Welcome [Name] view shows.
   ═══════════════════════════════════════════════════════════════════ */
if (window.FleetConfig && window.FleetConfig.userId) {
(function() {
  'use strict';
  if (!window.Capacitor || Capacitor.getPlatform() === 'web') return;

  /* Always save display name for HBL login view */
  var displayName = window.FleetConfig.userName;
  if (displayName) {
    localStorage.setItem('fleet_saved_name', displayName);
  }
})();
}