/* ═══════════════════════════════════════════════════════════════
   Fleet Manager — UI JS (extracted from base.html)
   ═══════════════════════════════════════════════════════════════ */

(function() {
    var bar = document.getElementById('topLoadBar');
    if (!bar) return;
    var growTimer, pct = 0;

    function start() {
        pct = 0;
        bar.style.width = '0%';
        bar.classList.remove('done');
        bar.classList.add('loading');
        grow();
    }
    function grow() {
        clearTimeout(growTimer);
        var inc = pct < 20 ? 8 : pct < 50 ? 5 : pct < 80 ? 2 : 0.5;
        pct = Math.min(pct + inc, 90);
        bar.style.width = pct + '%';
        if (pct < 90) growTimer = setTimeout(grow, 200);
    }
    function finish() {
        clearTimeout(growTimer);
        pct = 100;
        bar.classList.add('done');
        bar.style.width = '100%';
        setTimeout(function() { bar.classList.remove('loading', 'done'); bar.style.width = '0%'; }, 600);
    }

    /* Show bar on any internal link click */
    document.addEventListener('click', function(e) {
        var a = e.target.closest('a[href]');
        if (!a) return;
        var href = a.getAttribute('href') || '';
        /* Skip: external, hash-only, download, target=_blank, javascript: */
        if (!href || href.startsWith('#') || href.startsWith('javascript') ||
            href.startsWith('http') || a.target === '_blank' ||
            a.hasAttribute('download') || a.dataset.bsToggle) return;
        /* Skip command palette / modal triggers */
        if (a.closest('#cmdPalette') || a.dataset.bsToggle) return;
        start();
    }, true);

    /* Show bar on form submit */
    document.addEventListener('submit', function(e) {
        var form = e.target;
        if (form && form.method && form.method.toLowerCase() !== 'get') {
            start();
        }
    }, true);

    /* Finish immediately when this page's DOM loaded */
    if (document.readyState !== 'loading') {
        finish();
    } else {
        document.addEventListener('DOMContentLoaded', finish);
    }
})();

/* ── Section separator ── */

/* ═══════════════════════════════════════════
   DARK MODE
═══════════════════════════════════════════ */
function toggleDarkMode() {
    var isDark = document.body.classList.toggle('dark-mode');
    localStorage.setItem('fleetDarkMode', isDark ? 'on' : 'off');
    if (!document.body.classList.contains('driver-profile-public-view')) {
        document.body.classList.toggle('fm-aurora-theme', !isDark);
    }
    var metaTheme = document.getElementById('metaThemeColor');
    if (metaTheme) metaTheme.setAttribute('content', isDark ? '#0f172a' : '#e0f2fe');
    var icon = document.getElementById('darkModeIcon');
    if (icon) {
        icon.setAttribute('data-lucide', isDark ? 'sun' : 'moon');
        if (window.lucide) lucide.createIcons();
    }
}

/* Apply correct icon on page load */
document.addEventListener('DOMContentLoaded', function() {
    if (document.body.classList.contains('dark-mode')) {
        var icon = document.getElementById('darkModeIcon');
        if (icon) {
            icon.setAttribute('data-lucide', 'sun');
            if (window.lucide) lucide.createIcons();
        }
    }
});

/* ═══════════════════════════════════════════
   COMMAND PALETTE
═══════════════════════════════════════════ */
(function() {
    var palette   = document.getElementById('cmdPalette');
    var input     = document.getElementById('cmdInput');
    var results   = document.getElementById('cmdResults');
    var activeIdx = -1;
    var currentItems = [];
    var searchTimer;

    /* Static nav links (always shown when query is empty or matches) */
    var NAV_LINKS = [
        { title: 'Dashboard',          sub: 'Home',                   icon: 'layout-dashboard', color: '#1d4ed8', bg: '#dbeafe', href: '/' },
        { title: 'Drivers List',        sub: 'Master Data',            icon: 'users',            color: '#059669', bg: '#dcfce7', href: '/drivers' },
        { title: 'Vehicles List',       sub: 'Master Data',            icon: 'truck',            color: '#7c3aed', bg: '#f3e8ff', href: '/vehicles' },
        { title: 'Add Driver',          sub: 'Quick Action',           icon: 'user-plus',        color: '#1d4ed8', bg: '#dbeafe', href: '/driver/new' },
        { title: 'Add Vehicle',         sub: 'Quick Action',           icon: 'plus-circle',      color: '#059669', bg: '#dcfce7', href: '/vehicle/new' },
        { title: 'Mark Attendance',     sub: 'Attendance',             icon: 'calendar-check',   color: '#ea580c', bg: '#ffedd5', href: '/attendance/checkin' },
        { title: 'Assign Driver',       sub: 'Assignment',             icon: 'link',             color: '#7c3aed', bg: '#f3e8ff', href: '/assign/driver-to-vehicle/new' },
        { title: 'Fuel Expenses',       sub: 'Expenses',               icon: 'fuel',             color: '#0369a1', bg: '#e0f2fe', href: '/fuel-expenses' },
        { title: 'Add Fuel Expense',    sub: 'Quick Action',           icon: 'plus',             color: '#0369a1', bg: '#e0f2fe', href: '/fuel-expense/add' },
        { title: 'Driver Transfers',    sub: 'Transfers',              icon: 'arrow-right-left', color: '#dc2626', bg: '#fee2e2', href: '/driver-transfers' },
        { title: 'Reports',             sub: 'Analytics',              icon: 'bar-chart-2',      color: '#0f172a', bg: '#f1f5f9', href: '/reports' },
        { title: 'Expiry Report',       sub: 'Reports',                icon: 'calendar-x',      color: '#dc2626', bg: '#fee2e2', href: '/reports/expiry?days=15' },
        { title: 'Projects',            sub: 'Master Data',            icon: 'briefcase',        color: '#0369a1', bg: '#e0f2fe', href: '/projects' },
        { title: 'Notifications',       sub: 'System',                 icon: 'bell',             color: '#64748b', bg: '#f1f5f9', href: '/notifications' },
        { title: 'My Profile',          sub: 'Account',                icon: 'user-circle',      color: '#64748b', bg: '#f1f5f9', href: '/account/profile' },
    ];

    window.openCmdPalette = function() {
        palette.classList.add('open');
        input.value = '';
        input.focus();
        renderNav('');
        activeIdx = -1;
        if (window.lucide) lucide.createIcons();
    };

    window.closeCmdPalette = function() {
        palette.classList.remove('open');
        input.blur();
    };

    /* Keyboard shortcut Ctrl+K / Cmd+K */
    document.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            if (palette.classList.contains('open')) closeCmdPalette();
            else openCmdPalette();
        }
        if (e.key === 'Escape' && palette.classList.contains('open')) {
            closeCmdPalette();
        }
        if (!palette.classList.contains('open')) return;
        if (e.key === 'ArrowDown') { e.preventDefault(); moveActive(1); }
        if (e.key === 'ArrowUp')   { e.preventDefault(); moveActive(-1); }
        if (e.key === 'Enter')     { e.preventDefault(); activateItem(); }
    });

    /* Input handler */
    input.addEventListener('input', function() {
        clearTimeout(searchTimer);
        var q = input.value.trim();
        if (!q) { renderNav(''); activeIdx = -1; return; }
        searchTimer = setTimeout(function() { doSearch(q); }, 220);
        renderNav(q);
        activeIdx = -1;
    });

    function doSearch(q) {
        fetch('/api/global-search?q=' + encodeURIComponent(q))
            .then(function(r) { return r.json(); })
            .then(function(data) { renderSearchResults(q, data); })
            .catch(function() {});
    }

    function renderNav(q) {
        var ql = q.toLowerCase();
        var filtered = ql
            ? NAV_LINKS.filter(function(l) { return l.title.toLowerCase().includes(ql) || l.sub.toLowerCase().includes(ql); })
            : NAV_LINKS.slice(0, 8);
        if (!filtered.length && !ql) { results.innerHTML = '<div class="cmd-empty">Start typing to search…</div>'; currentItems = []; return; }
        var html = '';
        if (filtered.length) {
            html += '<div class="cmd-section-header">Pages</div>';
            filtered.forEach(function(l) {
                html += '<a class="cmd-item" href="' + l.href + '">' +
                    '<div class="cmd-item-icon" style="background:' + l.bg + ';color:' + l.color + ';">' +
                    '<i data-lucide="' + l.icon + '" style="width:16px;height:16px;"></i></div>' +
                    '<div><div class="cmd-item-title">' + l.title + '</div>' +
                    '<div class="cmd-item-sub">' + l.sub + '</div></div></a>';
            });
        }
        results.innerHTML = html;
        currentItems = results.querySelectorAll('.cmd-item');
        if (window.lucide) lucide.createIcons();
    }

    function renderSearchResults(q, data) {
        var ql = q.toLowerCase();
        var navFiltered = NAV_LINKS.filter(function(l) { return l.title.toLowerCase().includes(ql) || l.sub.toLowerCase().includes(ql); });
        var html = '';
        if (data.drivers && data.drivers.length) {
            html += '<div class="cmd-section-header">Drivers</div>';
            data.drivers.forEach(function(d) {
                html += '<a class="cmd-item" href="/driver/' + d.id + '/edit">' +
                    '<div class="cmd-item-icon" style="background:#dcfce7;color:#059669;">' +
                    '<i data-lucide="user" style="width:16px;height:16px;"></i></div>' +
                    '<div><div class="cmd-item-title">' + escHtml(d.name) + '</div>' +
                    '<div class="cmd-item-sub">ID: ' + escHtml(d.driver_id || '') + (d.cnic ? ' · ' + escHtml(d.cnic) : '') + ' · ' + (d.status || '') + '</div></div></a>';
            });
        }
        if (data.vehicles && data.vehicles.length) {
            html += '<div class="cmd-section-header">Vehicles</div>';
            data.vehicles.forEach(function(v) {
                html += '<a class="cmd-item" href="/vehicle/' + v.id + '/edit">' +
                    '<div class="cmd-item-icon" style="background:#f3e8ff;color:#7c3aed;">' +
                    '<i data-lucide="truck" style="width:16px;height:16px;"></i></div>' +
                    '<div><div class="cmd-item-title">' + escHtml(v.vehicle_no) + '</div>' +
                    '<div class="cmd-item-sub">' + escHtml(v.model || '') + (v.vehicle_type ? ' · ' + escHtml(v.vehicle_type) : '') + '</div></div></a>';
            });
        }
        if (navFiltered.length) {
            html += '<div class="cmd-section-header">Pages</div>';
            navFiltered.forEach(function(l) {
                html += '<a class="cmd-item" href="' + l.href + '">' +
                    '<div class="cmd-item-icon" style="background:' + l.bg + ';color:' + l.color + ';">' +
                    '<i data-lucide="' + l.icon + '" style="width:16px;height:16px;"></i></div>' +
                    '<div><div class="cmd-item-title">' + l.title + '</div>' +
                    '<div class="cmd-item-sub">' + l.sub + '</div></div></a>';
            });
        }
        if (!html) html = '<div class="cmd-empty">No results for "' + escHtml(q) + '"</div>';
        results.innerHTML = html;
        currentItems = results.querySelectorAll('.cmd-item');
        if (window.lucide) lucide.createIcons();
    }

    function moveActive(dir) {
        if (!currentItems.length) return;
        if (activeIdx >= 0) currentItems[activeIdx].classList.remove('active');
        activeIdx = Math.max(0, Math.min(currentItems.length - 1, activeIdx + dir));
        currentItems[activeIdx].classList.add('active');
        currentItems[activeIdx].scrollIntoView({ block: 'nearest' });
    }

    function activateItem() {
        if (activeIdx >= 0 && currentItems[activeIdx]) {
            currentItems[activeIdx].click();
        } else if (currentItems.length) {
            currentItems[0].click();
        }
    }

    /* Close palette on link click */
    results.addEventListener('click', function(e) {
        var item = e.target.closest('.cmd-item');
        if (item) closeCmdPalette();
    });

    function escHtml(s) {
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
})();

/* ── Section separator ── */

/* ═══════════════════════════════════════════
   URDU / RTL LOCALIZATION  (i18n)
═══════════════════════════════════════════ */
(function() {
    var UR = {
        'Dashboard': 'ڈیش بورڈ',
        'Master Data': 'ماسٹر ڈیٹا',
        'Companies': 'کمپنیاں',
        'Projects': 'منصوبے',
        'Districts': 'اضلاع',
        'Vehicles': 'گاڑیاں',
        'Parking Stations': 'پارکنگ',
        'Designations': 'عہدے',
        'Employees': 'ملازمین',
        'Drivers': 'ڈرائیور',
        'Parties': 'فریقین',
        'Products': 'مصنوعات',
        'Assignments': 'تفویضات',
        'Project to Company': 'منصوبہ کمپنی کو',
        'District to Project': 'ضلع منصوبے کو',
        'Vehicle to District': 'گاڑی ضلع کو',
        'Vehicle to Parking': 'گاڑی پارکنگ کو',
        'Driver to Vehicle': 'ڈرائیور گاڑی کو',
        'Transfers': 'تبادلے',
        'Project Transfer': 'منصوبہ تبادلہ',
        'Vehicle Transfer': 'گاڑی تبادلہ',
        'Driver Transfer': 'ڈرائیور تبادلہ',
        'Workforce': 'افرادی قوت',
        'Resignation / Exit': 'استعفیٰ / اخراج',
        'Re-employment': 'دوبارہ ملازمت',
        'Penalties': 'جرمانے',
        'Attendance': 'حاضری',
        'Check In (GPS & Camera)': 'چیک ان',
        'Check Out (GPS & Camera)': 'چیک آؤٹ',
        'Missing Check IN': 'غیر حاضر چیک ان',
        'Missing Check out': 'غیر حاضر چیک آؤٹ',
        'Leave / Late / Half Day / Off': 'رخصت / دیر / نیم روز',
        'Bulk Off': 'اجتماعی غیر حاضری',
        'Attendance List': 'حاضری فہرست',
        'Task & Logbook': 'کام و لاگ بک',
        'Workbook Upload': 'ورک بک اپلوڈ',
        'Daily Task Report': 'روزانہ کام رپورٹ',
        'Red Task Justification': 'سرخ کام جواز',
        'Movement without Task': 'بغیر کام نقل و حرکت',
        'Logbook Covers': 'لاگ بک کور',
        'Finance': 'فنانس',
        'Payment Voucher': 'ادائیگی واؤچر',
        'Receipt Voucher': 'وصولی واؤچر',
        'Bank Entry': 'بینک اندراج',
        'Journal Voucher': 'جرنل واؤچر',
        'Future Dated Entries': 'مستقبل کے اندراجات',
        'Balance Sheet': 'بیلنس شیٹ',
        'Account Ledger': 'اکاؤنٹ لیجر',
        'Expense Management': 'اخراجات',
        'Fuel': 'ایندھن',
        'Oil & Lubricants': 'تیل و چکنائی',
        'Maintenance': 'دیکھ بھال',
        'Employee Expenses': 'ملازم اخراجات',
        'Reports & Analytics': 'رپورٹس و تجزیہ',
        'Report Centre': 'رپورٹ سینٹر',
        'Company Profile': 'کمپنی پروفائل',
        'Attendance Report': 'حاضری رپورٹ',
        'Document Expiry': 'دستاویز میعاد',
        'Vehicle Summary': 'گاڑی خلاصہ',
        'Project Summary': 'منصوبہ خلاصہ',
        'District Summary': 'ضلع خلاصہ',
        'Parking Utilization': 'پارکنگ استعمال',
        'Create Report with AI': 'AI رپورٹ',
        'Notifications': 'اطلاعات',
        'All Notifications': 'تمام اطلاعات',
        'Create Notification': 'اطلاع بنائیں',
        'My Reminders': 'میری یاددہانیاں',
        'Administration': 'انتظامیہ',
        'User Management': 'صارف انتظام',
        'Roles & Permissions': 'کردار و اجازت',
        'Setting': 'ترتیبات',
        'System Health': 'نظام صحت',
        'App Updates': 'ایپ اپ ڈیٹ',
        'Backup': 'بیک اپ',
        "What's New": 'کیا نیا ہے',
        'Logout': 'لاگ آؤٹ',
        'Home': 'ہوم',
        'Fleet': 'فلیٹ',
        'Tasks': 'کام',
        'Profile': 'پروفائل',
    };

    var _lang = localStorage.getItem('fleetLang') || 'en';

    function getTranslatableEls() {
        return Array.from(document.querySelectorAll(
            '.sidebar a span, .mobile-nav-item > span, .sidebar .dropdown-toggle span'
        ));
    }

    function applyUrdu() {
        getTranslatableEls().forEach(function(el) {
            var t = el.textContent.trim();
            if (!el.dataset.enText) el.dataset.enText = t;
            if (UR[t]) el.textContent = UR[t];
        });
        document.documentElement.setAttribute('dir', 'rtl');
        document.documentElement.setAttribute('lang', 'ur');
        var btn = document.getElementById('langBtnLabel');
        if (btn) btn.textContent = 'EN';
        _lang = 'ur';
        localStorage.setItem('fleetLang', 'ur');
        var di = document.getElementById('moreDrawerLangIcon'); if (di) di.textContent = 'EN';
        var dt = document.getElementById('moreDrawerLangText');  if (dt) dt.textContent = 'English';
    }

    function applyEnglish() {
        getTranslatableEls().forEach(function(el) {
            if (el.dataset.enText) el.textContent = el.dataset.enText;
        });
        document.documentElement.setAttribute('dir', 'ltr');
        document.documentElement.setAttribute('lang', 'en');
        var btn = document.getElementById('langBtnLabel');
        if (btn) btn.textContent = '\u0639\u0631';
        _lang = 'en';
        localStorage.setItem('fleetLang', 'en');
        var di = document.getElementById('moreDrawerLangIcon'); if (di) di.textContent = '\u0639\u0631';
        var dt = document.getElementById('moreDrawerLangText');  if (dt) dt.textContent = '\u0627\u0631\u062F\u0648';
    }

    window.toggleLang = function() {
        // Language toggle disabled - forcing English only
        applyEnglish();
    };

    /* ── Left sidebar (mobile / Capacitor): shared open/close ── */
    window.fleetOpenMobileSidebar = function() {
        var sidebar = document.getElementById('sidebar');
        var overlay = document.getElementById('sidebarOverlay');
        if (!sidebar) return;
        var legacyGpu = document.documentElement.classList.contains('legacy-android-gpu');
        if (legacyGpu) {
            var auroraBg = document.querySelector('.fm-aurora-bg');
            if (auroraBg) auroraBg.style.display = 'none';
        }
        sidebar.classList.add('mobile-open');
        document.body.classList.add('mobile-sidebar-open');
        document.body.classList.add('sidebar-open');
        if (overlay) {
            overlay.classList.add('show');
            overlay.setAttribute('aria-hidden', 'false');
            if (legacyGpu) {
                overlay.style.backdropFilter = 'none';
                overlay.style.webkitBackdropFilter = 'none';
                overlay.style.filter = 'none';
                overlay.style.backgroundColor = 'rgba(0,0,0,0.45)';
            }
        }
        document.body.style.overflow = 'hidden';
        var nav = sidebar.querySelector('.sb-drawer-nav');
        var active = sidebar.querySelector('.active-link');
        if (nav && active) {
            requestAnimationFrame(function() {
                try {
                    var top = active.offsetTop - nav.clientHeight * 0.25;
                    nav.scrollTop = Math.max(0, top);
                } catch (e) {}
            });
        }
    };
    window.fleetCloseMobileSidebar = function() {
        var sidebar = document.getElementById('sidebar');
        var overlay = document.getElementById('sidebarOverlay');
        if (sidebar) sidebar.classList.remove('mobile-open');
        document.body.classList.remove('mobile-sidebar-open');
        document.body.classList.remove('sidebar-open');
        if (overlay) {
            overlay.classList.remove('show');
            overlay.style.display = '';
            overlay.setAttribute('aria-hidden', 'true');
        }
        document.body.style.overflow = '';
    };
    window.fleetToggleMobileSidebar = function(forceOpen) {
        var sb = document.getElementById('sidebar');
        if (!sb) return;
        if (forceOpen === true) {
            window.fleetOpenMobileSidebar();
            return;
        }
        if (sb.classList.contains('mobile-open')) window.fleetCloseMobileSidebar();
        else window.fleetOpenMobileSidebar();
    };

    /* ── More Drawer (Mobile) ── */
    window.openMoreDrawer = function() {
        var _native = window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform();
        if (!_native && window.innerWidth >= 992) return;
        var overlay = document.getElementById('moreDrawerOverlay');
        var panel   = document.getElementById('moreDrawerPanel');
        if (!overlay || !panel) return;
        overlay.classList.add('open');
        panel.classList.add('open');
        var fabWrap = document.getElementById('mobileFabWrap');
        if (fabWrap) fabWrap.classList.add('fab-hidden-for-more-drawer');
        /* Close speed-dial if open so + doesn’t stay expanded behind drawer */
        var dial = document.getElementById('fabDialMenu');
        var fabBtn = document.getElementById('mobileFabBtn');
        var fabBd = document.getElementById('fabBackdrop');
        if (dial && dial.classList.contains('open')) {
            dial.classList.remove('open');
            if (fabBtn) fabBtn.classList.remove('open');
            if (fabBd) fabBd.classList.remove('show');
        }
        document.body.style.overflow = 'hidden';
        /* Lock the app-shell scroll container so content behind can't scroll */
        var _mc = document.getElementById('mainContent');
        if (_mc) _mc.style.overflowY = 'hidden';
        if (window.lucide) lucide.createIcons({ attrs: { 'stroke-width': 2 } });
    };

    window.closeMoreDrawer = function() {
        var overlay = document.getElementById('moreDrawerOverlay');
        var panel   = document.getElementById('moreDrawerPanel');
        if (overlay) overlay.classList.remove('open');
        if (panel)   panel.classList.remove('open');
        var fabWrap = document.getElementById('mobileFabWrap');
        if (fabWrap) fabWrap.classList.remove('fab-hidden-for-more-drawer');
        document.body.style.overflow = '';
        /* Restore app-shell scroll container */
        var _mc = document.getElementById('mainContent');
        if (_mc) _mc.style.overflowY = '';
    };

    /* ── Attend Action Sheet ── */
    window.openAttendSheet = function() {
        var sheet   = document.getElementById('attendSheet');
        var overlay = document.getElementById('attendSheetOverlay');
        if (!sheet) return;
        if (overlay) overlay.classList.add('open');
        sheet.style.opacity      = '1';
        sheet.style.pointerEvents = 'auto';
        sheet.style.transform    = 'translateX(-50%) translateY(0)';
    };
    window.closeAttendSheet = function() {
        var sheet   = document.getElementById('attendSheet');
        var overlay = document.getElementById('attendSheetOverlay');
        if (!sheet) return;
        if (overlay) overlay.classList.remove('open');
        sheet.style.opacity      = '0';
        sheet.style.pointerEvents = 'none';
        sheet.style.transform    = 'translateX(-50%) translateY(20px)';
    };
    /* Close attend sheet when tapping outside (overlay click handled in HTML) */
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') { closeAttendSheet(); closeMoreDrawer(); }
    });

    window.syncMoreLangLabel = function() {
        // Language toggle removed - English only
    };

    /* Swipe-down to close More drawer */
    (function() {
        var panel, startY = 0, dragging = false;
        document.addEventListener('DOMContentLoaded', function() {
            panel = document.getElementById('moreDrawerPanel');
            if (!panel) return;
            panel.addEventListener('touchstart', function(e) {
                startY = e.touches[0].clientY;
                dragging = true;
                panel.style.transition = 'none';
            }, { passive: true });
            panel.addEventListener('touchmove', function(e) {
                if (!dragging) return;
                var dy = e.touches[0].clientY - startY;
                if (dy > 0) panel.style.transform = 'translateY(' + dy + 'px)';
            }, { passive: true });
            panel.addEventListener('touchend', function(e) {
                if (!dragging) return;
                dragging = false;
                panel.style.transition = '';
                panel.style.transform = '';
                if (e.changedTouches[0].clientY - startY > 80) closeMoreDrawer();
            }, { passive: true });
        });
    })();

    /* Force English on load - disable Urdu */
    document.addEventListener('DOMContentLoaded', function() {
        // Clear any saved Urdu preference and force English
        localStorage.setItem('fleetLang', 'en');
        applyEnglish();
    });

    /* Block Urdu characters in ID-type fields */
    document.addEventListener('DOMContentLoaded', function() {
        var URDU_RE = /[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]/;
        var ID_PAT  = /driver_id|vehicle_no|cnic|license|id_no|plate|reg_no/i;
        document.querySelectorAll('input[type="text"], input[type="tel"]').forEach(function(inp) {
            var nm = (inp.name || inp.id || '').toLowerCase();
            if (!ID_PAT.test(nm)) return;
            inp.addEventListener('input', function() {
                if (URDU_RE.test(this.value)) {
                    this.value = this.value.replace(new RegExp('[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]', 'g'), '');
                    this.style.outline = '2px solid #ef4444';
                    var self = this;
                    setTimeout(function() { self.style.outline = ''; }, 1200);
                }
            });
        });
    });
})();

/* ── Section separator ── */

/* Tom Select fallback init — isolated from main script so errors there don't block this */
(function() {
    function _tsRunInit() {
        if (typeof TomSelect !== 'undefined' && typeof window.initSearchableDropdowns === 'function') {
            window.initSearchableDropdowns();
        }
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _tsRunInit);
    } else {
        _tsRunInit();
    }
})();

/* ── Section separator ── */

function _dtPrintOrPdf(btn) {
  var isNative = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());
  if (!isNative) { window.print(); return; }
  var doc = btn.ownerDocument || document;
  var body = doc.body;
  var el = body.querySelector('table') ? body : doc.getElementById('printContainer') || body;
  var origHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span style="width:14px;height:14px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;display:inline-block;animation:_bp_spin .7s linear infinite;vertical-align:middle;"></span> Generating...';
  var scr = doc.createElement('script');
  scr.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.2/html2pdf.bundle.min.js';
  scr.onload = function() {
    var toolbar = body.querySelector('.dt-print-toolbar');
    if (toolbar) toolbar.style.display = 'none';
    var h2p = (doc.defaultView || window).html2pdf || window.html2pdf;
    h2p().set({
      margin: [6,4,6,4], filename: 'Report.pdf',
      image: {type:'jpeg',quality:0.92},
      html2canvas: {scale:2,useCORS:true,logging:false},
      jsPDF: {unit:'mm',format:'a4',orientation:'landscape'},
      pagebreak: {mode:['css','legacy']}
    }).from(el).output('blob').then(function(blob) {
      if (toolbar) toolbar.style.display = '';
      btn.disabled = false; btn.innerHTML = origHtml;
      if (window.FleetBridge && window.FleetBridge.downloadBlob) {
        window.FleetBridge.downloadBlob(blob, 'Report.pdf');
      }
    }).catch(function() {
      if (toolbar) toolbar.style.display = '';
      btn.disabled = false; btn.innerHTML = origHtml;
    });
  };
  doc.head.appendChild(scr);
}
window._dtPrintCustomize = function(title, color, icon) {
  return function(win) {
    var doc = win.document;
    var $b = $(doc.body);
    $b.css({'font-family':'Inter,Segoe UI,system-ui,sans-serif','background':'#f8fafc','padding':'0','margin':'0'});
    var hdr = '<div style="background:linear-gradient(135deg,'+color+' 0%,'+color+'cc 100%);color:#fff;padding:16px 24px;border-radius:0 0 12px 12px;margin-bottom:16px;display:flex;align-items:center;gap:12px;">'
      +'<i class="bi bi-'+icon+'" style="font-size:1.4rem;opacity:0.9;"></i>'
      +'<div><div style="font-size:1.15rem;font-weight:700;">'+title+'</div>'
      +'<div style="font-size:0.78rem;opacity:0.85;">Generated: '+(function(){var d=new Date(Date.now()+_pktOffset);var dd=('0'+d.getUTCDate()).slice(-2);var mon=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getUTCMonth()];var h=d.getUTCHours(),m=('0'+d.getUTCMinutes()).slice(-2),ap=h>=12?'PM':'AM';h=h%12;if(!h)h=12;return dd+' '+mon+' '+d.getUTCFullYear()+', '+('0'+h).slice(-2)+':'+m+' '+ap+' PKT';})()+'</div></div></div>';
    var toolbar = '<div style="display:flex;gap:8px;padding:0 24px 12px;align-items:center;" class="dt-print-toolbar">'
      +'<button onclick="window.close()" style="background:#334155;color:#e2e8f0;border:none;border-radius:8px;padding:8px 18px;font-size:0.84rem;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:6px;"><i class="bi bi-arrow-left"></i> Close</button>'
      +'<button onclick="_dtPrintOrPdf(this)" style="background:#2563eb;color:#fff;border:none;border-radius:8px;padding:8px 18px;font-size:0.84rem;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:6px;box-shadow:0 2px 8px rgba(37,99,235,0.3);"><i class="bi bi-printer"></i> Print</button>'
      +'<button onclick="_dtPrintOrPdf(this)" style="background:#dc2626;color:#fff;border:none;border-radius:8px;padding:8px 18px;font-size:0.84rem;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:6px;box-shadow:0 2px 8px rgba(220,38,38,0.3);"><i class="bi bi-file-earmark-pdf"></i> Save as PDF</button>'
      +'<span style="margin-left:auto;color:#94a3b8;font-size:0.76rem;"><i class="bi bi-info-circle"></i> Use Ctrl+P → Save as PDF</span></div>';
    $b.prepend(toolbar);
    $b.prepend(hdr);
    var lnk = doc.createElement('link');
    lnk.rel='stylesheet'; lnk.href='https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css';
    doc.head.appendChild(lnk);
    var lnk2 = doc.createElement('link');
    lnk2.rel='stylesheet'; lnk2.href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap';
    doc.head.appendChild(lnk2);
    var sty = doc.createElement('style');
    sty.textContent = '@page{size:landscape;margin:6mm;}@media print{.dt-print-toolbar{display:none!important;}div[style*="border-radius"]{-webkit-print-color-adjust:exact;print-color-adjust:exact;}table{font-size:9px!important;margin:0!important;max-width:100%!important;width:100%!important;}table thead th{font-size:8px!important;padding:3px 5px!important;-webkit-print-color-adjust:exact;print-color-adjust:exact;}table tbody td{padding:3px 5px!important;font-size:9px!important;}table tbody tr:nth-child(even){-webkit-print-color-adjust:exact;print-color-adjust:exact;}}';
    doc.head.appendChild(sty);
    var $t = $b.find('table');
    $t.css({'width':'100%','border-collapse':'separate','border-spacing':'0','font-size':'0.78rem','margin':'0 24px','max-width':'calc(100% - 48px)','background':'#fff','border-radius':'10px','overflow':'hidden','box-shadow':'0 1px 4px rgba(0,0,0,0.06)','table-layout':'auto','word-break':'break-word'});
    $t.find('thead th').css({'background':color+'18','color':color,'font-size':'0.68rem','font-weight':'700','text-transform':'uppercase','letter-spacing':'0.04em','padding':'0.4rem 0.55rem','border-bottom':'2px solid '+color+'44','white-space':'nowrap'});
    $t.find('tbody td').css({'padding':'0.35rem 0.55rem','border-bottom':'1px solid #f1f5f9','color':'#374151','vertical-align':'middle','font-size':'0.76rem'});
    $t.find('tbody tr:nth-child(even)').css({'background':'#f8fafc'});
    var ftr = '<div style="text-align:center;padding:12px 24px;color:#94a3b8;font-size:0.72rem;border-top:1px solid #e5e7eb;margin-top:12px;">'+title+' · Fleet Management System</div>';
    $b.append(ftr);
  };
};

/* ── Section separator ── */

/* ── Global navigation shortcuts ────────────────────────────────────────
   Alt+F  → Add Fuel Expense
   Alt+O  → Add Oil Expense
   Alt+M  → Add Maintenance Expense
   Alt+T  → Add Workspace Transfer
   Alt+L  → Workspace Ledger
   (Only when command palette is NOT open and no modal/dialog is active) */
(function() {
    var SHORTCUTS = {
        'f': { path: '/expenses/fuel/add', keys: 'Alt+F', label: 'Add Fuel Expense' },
        'o': { path: '/oil-expense/add', keys: 'Alt+O', label: 'Add Oil Expense' },
        'm': { path: '/maintenance-expense/add', keys: 'Alt+M', label: 'Add Maintenance Expense' },
        't': { path: '/workspace/transfer/new', keys: 'Alt+T', label: 'Add Workspace Transfer' },
        'l': { path: '/workspace/ledger', keys: 'Alt+L', label: 'Workspace Ledger' },
    };
    window._appShortcuts = Object.keys(SHORTCUTS).map(function(k){ return SHORTCUTS[k]; });
    document.addEventListener('keydown', function(e) {
        if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
        var k = e.key.toLowerCase();
        if (!SHORTCUTS[k]) return;
        var palette = document.getElementById('cmdPalette');
        if (palette && palette.classList.contains('open')) return;
        var activeTag = document.activeElement ? document.activeElement.tagName : '';
        if (activeTag === 'INPUT' || activeTag === 'TEXTAREA' || activeTag === 'SELECT') return;
        if (document.querySelector('.modal.show')) return;
        e.preventDefault();
        window.location.href = SHORTCUTS[k].path;
    });
})();

/* ── Section separator ── */

(function fleetTaskEntryDisableLoadMoreGlobal() {
  function run() {
    var wrap = document.getElementById('taskEntryLoadMoreWrap');
    if (wrap) wrap.remove();
    document.querySelectorAll('#batchTable tbody tr.task-row[data-task-chunk-hidden="1"]').forEach(function(row) {
      row.setAttribute('data-task-chunk-hidden', '0');
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run);
  else run();
})();

/* ── Section separator ── */

(function() {
  /* Skip inactivity timer entirely on Capacitor mobile app */
  if (typeof window.Capacitor !== 'undefined') { return; }

  var TIMEOUT_MS = 15 * 60 * 1000;   // 15 minutes total
  var WARNING_MS = 14 * 60 * 1000;   // show warning at 14 minutes
  var _lastActivity = Date.now();
  var _warningShown = false;
  var _countdownInterval = null;

  function _resetTimer() {
    _lastActivity = Date.now();
    if (_warningShown) {
      _warningShown = false;
      document.getElementById('inactivity-warning').style.display = 'none';
      if (_countdownInterval) { clearInterval(_countdownInterval); _countdownInterval = null; }
    }
  }
  window.resetInactivityTimer = _resetTimer;

  ['mousemove','keydown','click','touchstart','scroll'].forEach(function(ev) {
    document.addEventListener(ev, _resetTimer, { passive: true });
  });

  function _showWarning(secsLeft) {
    _warningShown = true;
    var box = document.getElementById('inactivity-warning');
    box.style.display = 'flex';
    var cd = document.getElementById('inactivity-countdown');
    cd.textContent = secsLeft;
    if (_countdownInterval) clearInterval(_countdownInterval);
    _countdownInterval = setInterval(function() {
      secsLeft--;
      cd.textContent = secsLeft;
      if (secsLeft <= 0) { clearInterval(_countdownInterval); window.location.href = window.FleetConfig.urls.logout + '?inactivity=1'; }
    }, 1000);
  }

  setInterval(function() {
    var idle = Date.now() - _lastActivity;
    if (idle >= TIMEOUT_MS) {
      window.location.href = window.FleetConfig.urls.logout + '?inactivity=1';
    } else if (idle >= WARNING_MS && !_warningShown) {
      _showWarning(Math.round((TIMEOUT_MS - idle) / 1000));
    }
  }, 10000);
})();

/* ── Section separator ── */

(function() {
  if (window.fleetSessionSounds) {
    window.fleetSessionSounds.installGlobalFeedbackSounds();
  }
  var logoutPath = window.FleetConfig.urls.logout;
  document.addEventListener('click', function(e) {
    var link = e.target.closest('a[href]');
    if (!link) return;
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var href = link.getAttribute('href') || '';
    if (!href || href.indexOf('javascript:') === 0 || href.charAt(0) === '#') return;
    var url;
    try { url = new URL(href, window.location.origin); } catch (_) { return; }
    if (url.origin !== window.location.origin) return;
    if (url.pathname !== logoutPath) return;
    if (url.searchParams.get('inactivity') === '1') return;

    e.preventDefault();
    url.searchParams.set('pre_sound', '1');
    var navigate = function() { window.location.href = url.toString(); };
    if (window.fleetSessionSounds) {
      window.fleetSessionSounds.init();
      var hasNavigated = false;
      var onceNavigate = function() {
        if (hasNavigated) return;
        hasNavigated = true;
        navigate();
      };
      window.fleetSessionSounds
        .play('logout-manual')
        .catch(function() {})
        .then(function() { setTimeout(onceNavigate, 130); });
      setTimeout(onceNavigate, 520);
      return;
    }
    setTimeout(navigate, 260);
  }, true);
})();

/* ── GPS banner icon sync ── */

(function() {
  function syncGpsBannerIcons() {
    var banner = document.getElementById('fleetGpsPendingBanner');
    if (!banner) return;
    var state = banner.getAttribute('data-state') || 'hidden';
    var spin = banner.querySelector('[data-role="icon-spin"]');
    var icon = banner.querySelector('[data-role="icon-static"]');
    var isRetry = state === 'retrying';
    if (spin) spin.classList.toggle('d-none', !isRetry);
    if (icon) {
      icon.classList.toggle('d-none', isRetry);
      if (state === 'success') icon.className = 'bi bi-check-circle-fill';
      else if (state === 'pending' || state === 'retrying') icon.className = 'bi bi-exclamation-triangle-fill';
      else icon.className = 'bi bi-cloud-upload';
    }
  }
  document.addEventListener('fleet-gps-pending-changed', syncGpsBannerIcons);
  var obs = new MutationObserver(syncGpsBannerIcons);
  var b = document.getElementById('fleetGpsPendingBanner');
  if (b) obs.observe(b, { attributes: true, attributeFilter: ['data-state', 'class'] });
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', syncGpsBannerIcons);
  } else {
    syncGpsBannerIcons();
  }
})();

/* ── Lucide icons init ── */

if (window.lucide && typeof window.lucide.createIcons === 'function') {
    window.lucide.createIcons();
}