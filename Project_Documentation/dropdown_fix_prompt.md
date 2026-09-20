# Cursor Prompt — Searchable Dropdown Fixes (Fleet Manager)

> Ye file Cursor/ai agent ko dene ke liye hai. Kamzor AI ho to poora prompt ek saath na do —
> pehle "Background + Global Rules + Phase 0" paste karein, report aane par Phase 1, phir Phase 2.

---

```text
# TASK: Fix searchable-dropdown issues in the Fleet Manager codebase

You are working in a Flask + Jinja2 + Bootstrap 5 web app ("Fleet Manager") that also runs
inside a Capacitor Android WebView. Platform: Windows, Git Bash. Work step by step,
one PHASE at a time. Do NOT skip ahead. Do NOT commit or push unless I ask.

============================================================
BACKGROUND (read this so you understand the system)
============================================================
- Almost every dropdown on every page is a <select class="form-select search-select">.
- static/js/core/fleet_core.js contains window.initSearchableDropdowns(scope)
  (~line 4415). It converts every .search-select into a Tom Select
  (vendor library, loaded in templates/base.html ~line 104).
- Helpers you MUST use (already exist in fleet_core.js):
    window.fleetFillSelect(sel, options, cfg)      -> repopulate a TS-wrapped select
    window.fleetFillSelectFromHtml(sel, html, cfg) -> same, from an options HTML string
    window.fleetFillSelectRows(sel, rows, valueKey, textKey, cfg)
    window.fleetSetSelectValue(sel, val, silent)   -> set value without popping the list
    window.fleetBeginCascade(sel) / fleetEndCascade(sel)
- IMPORTANT CACHE RULE: every file under static/ is included with a ?v=NNN query
  parameter (e.g. in templates/base.html). Browsers cache these files forever.
  AFTER EDITING ANY static/ FILE you MUST bump its ?v= number wherever it is
  included. Find the includes with:  rg -n "<filename>" templates/
  A fix that is not cache-bumped is NOT deployed to phones. Treat forgetting this
  as a failed task.

============================================================
GLOBAL RULES (obey all of them)
============================================================
1. PHASES: Do Phase 0 completely, then STOP and give me a report. Wait for my
   confirmation before starting Phase 1. Same for Phase 2.
2. READ BEFORE EDIT: Line numbers below were correct when written but may have
   drifted. If a line doesn't match, find the code by the quoted snippet or by
   searching with rg. NEVER guess — if you cannot find the code described,
   SKIP that task and report it instead of improvising.
3. MINIMAL CHANGES: Only change what each task says. No extra refactoring,
   no reformatting, no "improvements" you noticed along the way.
4. Match the existing code style (the core JS files are plain ES5-style JS:
   function() {}, var, no arrow functions inside fleet_core.js).
5. After editing any JS file, run:  node --check <file>   (if node exists).
   If node is missing, carefully re-read your diff instead.
6. Some tasks touch <script> blocks inside .html templates (Jinja). Keep Jinja
   syntax intact. Templates are NOT cache-pinned, so no ?v= needed for them,
   but if a task edits static/ files, bump their ?v= (see cache rule above).
7. Do NOT touch anything in tools/, Project_Documentation/, static/vendor/,
   static/fleet_personal_pc/.
8. FINAL REPORT FORMAT per phase: for each task — [DONE file:line] or
   [SKIPPED file:line reason]. Then run the phase's Verification commands and
   paste their output.

============================================================
PHASE 0 — QUICK WINS (all are small, safe, independent)
============================================================

TASK 0.1 — Broken project cascade (options never refresh)
File: templates/task_report_vehicle_period_detail.html (~lines 346-363)
Find: a district-change listener that rebuilds the Project filter with raw
      innerHTML, something like:
      projectSelect.innerHTML = ... (an options string built in a loop)
Problem: #taskReportProjectSelect is already a Tom Select (class search-select).
      Changing select.innerHTML under Tom Select does NOTHING visible — the
      dropdown keeps showing stale options.
Fix: keep building the same options HTML string, but instead of assigning it to
      projectSelect.innerHTML, call:
        window.fleetFillSelectFromHtml(projectSelect, htmlString);
      If the old code also set a selected value afterwards, pass it as
      { selected: '<value>' } in the cfg argument instead.
Verify: rg -n "innerHTML" templates/task_report_vehicle_period_detail.html
      — the project select must no longer be assigned innerHTML directly.

TASK 0.2 — Missing search-select class (these filters should be searchable)
Add class "search-select" (keep all existing classes, e.g. "form-select") to:
  a) templates/report_expiry.html        ~lines 251, 260, 268
     (exProjectSelect, exDistrictSelect, exVehicleSelect)
  b) templates/report_parking_utilization.html ~lines 271, 280, 289, 297
     (puProjectSelect, puDistrictSelect, puVehicleSelect, puParkingSelect)
  c) templates/finance/fund_transfers_list.html ~lines 56, 65
     (district_id, project_id filter selects)
  d) templates/vehicle_transfer_edit.html ~lines 66, 71
     (new_district_id, new_parking_id)
  e) templates/assign_project_to_district_edit.html ~lines 33-34
     — this one is Jinja: {{ form.project_id() }} / {{ form.district_id() }}
     rendered with NO class args. Change to:
        {{ form.project_id(class="form-select search-select") }}
        {{ form.district_id(class="form-select search-select") }}
Verify: rg -c "search-select" on each of the 5 files — counts must increase.

TASK 0.3 — Delete dead z-index CSS (dropdown is attached to <body>, these
selectors can never match — they are noise that confuses future edits)
Delete ONLY the .ts-dropdown z-index override rules inside these files
(keep everything else in the <style> block):
  a) templates/driver_attendance_mark.html            ~line 11
     (rule like: .mark-att-filter .ts-dropdown { z-index: 9999 !important })
  b) templates/driver_attendance_pending.html         ~line 10
  c) templates/driver_attendance_missing_checkout.html ~line 10
  d) templates/driver_attendance_bulk_off.html        ~line 10
  e) templates/task_report_new.html                   ~lines 418-424
     (rule like: .ts-dropdown { z-index: 3000 !important })
  f) templates/ufone/dashboard.html                   ~lines 200-212
     — careful: inside .uf-filterbar rules, delete ONLY the .ts-dropdown rules,
     KEEP the .ts-control rules.
Verify: rg -n "ts-dropdown" on those 6 files — only deleted/kept as specified.

TASK 0.4 — Stale display when a suggestion sets party type
File: templates/workspace/party_form.html (~lines 141-148)
Find: code that sets the party_type select via a native selectedIndex loop and
      then dispatchEvent(new Event('input')).
Problem: the select is Tom Select-wrapped; a raw input event does not update the
      TS display, so the visible label goes stale.
Fix: replace the selectedIndex loop + dispatch with:
        if (window.fleetSetSelectValue) {
            window.fleetSetSelectValue(<typeSelectElement>, <value>, true);
        } else { <keep the old code as fallback> }
      and, IF the page has change listeners on that select that must run,
      dispatch a plain 'change' event after the call
      (typeSelect.dispatchEvent(new Event('change'))).
      Check first what the old 'input' dispatch was triggering and make sure the
      same behavior still happens.

TASK 0.5 — Delete calls to a function that does not exist
Files: templates/workspace/journal_voucher_form.html (~lines 174-176)
       templates/finance/journal_voucher_form.html  (~lines 152-154)
Find: inside an addLine()-style function, an if-block calling
      window.initSearchSelect(...) — this function is defined NOWHERE in the
      repo (dynamic rows are initialized by a MutationObserver instead).
Fix: delete just that dead if-block (2-3 lines). Keep everything else.

TASK 0.6 — Phase 0 cache/verify sweep
- No static/ files are edited in Phase 0, so no ?v= bumps needed.
- Run and paste output:
    rg -n "fleetFillSelectFromHtml" templates/task_report_vehicle_period_detail.html
    rg -c "search-select" templates/report_expiry.html templates/report_parking_utilization.html templates/finance/fund_transfers_list.html templates/vehicle_transfer_edit.html templates/assign_project_to_district_edit.html
    rg -n "initSearchSelect" templates/
  (the last one must return no matches)

============================================================
PHASE 1 — SAFETY & CONSISTENCY (core JS edits — bump ?v= once at the end)
============================================================

TASK 1.1 — Failsafe so selects can never become invisible
File: templates/base.html (~lines 105-115)
Find: the "Safety net" IIFE — it unhides .search-selects only when
      `typeof TomSelect === 'undefined'`.
Problem: if the vendor lib loads but fleet_core.js fails to load/execute,
      the safety net exits early and CSS (select.search-select{display:none})
      hides every dropdown forever.
Fix: KEEP the existing immediate check, and ADD a one-time delayed sweep:
      on DOMContentLoaded, setTimeout(3000) then:
        document.querySelectorAll('select.search-select').forEach(function(sel){
            if (!sel.tomselect) { sel.style.display = ''; sel.classList.remove('search-select'); }
        });
      (This runs once; dynamically added selects afterwards are unaffected.
      If TomSelect is already undefined, the existing early code already handled it.)

TASK 1.2 — Remove duplicate inputmode setter (numeric-keyboard risk)
File: static/js/core/fleet_core.js (~lines 6975-6994)
Find: an IIFE starting with a comment like "── Mobile Input Enhancements ──"
      that sets inputmode on inputs by matching their name against
      /phone|mobile|.../, /cnic|.../, /amount|...|fuel/ etc.
Problem: static/js/core/fleet_mobile.js already does this job BETTER — it has an
      explicit guard that keeps Tom Select search inputs on the TEXT keyboard
      (see fleet_mobile.js ~lines 21-24). The fleet_core copy lacks that guard.
Fix: delete the whole fleet_core IIFE. Do NOT touch fleet_mobile.js.
Verify: rg -n "Mobile Input Enhancements" static/js/core/ → only fleet_mobile.js
      mention (in a comment) may remain.

TASK 1.3 — Proper multi-select behavior in the global init
File: static/js/core/fleet_core.js, inside window.initSearchableDropdowns
      (~lines 4415-4730)
Problem: a <select multiple class="search-select"> (exists today on
      templates/oil_change_alert_report.html ~line 75, name="status") gets the
      single-select config: closeAfterSelect:true closes the list after EVERY
      pick, making multi-select painful.
Fix (4 small edits inside initSearchableDropdowns):
      a) before `var ts = new TomSelect(el, {` add:
             var _isMulti = !!el.multiple;
      b) in the config object: closeAfterSelect: !_isMulti,
      c) at the very top of the `ts.on('item_add', function(){...})` handler add:
             if (_isMulti) { return; }
         (multi keeps the list open; TS handles focus itself)
      d) change the lockAfterPick line to:
             var lockAfterPick = !_isMulti && (isFilterSelect || _fleetTsIsCoarsePointer());
      Verify: rg -n "_isMulti" static/js/core/fleet_core.js  → 4 hits.

TASK 1.4 — Column-filter dropdown must not float detached while scrolling
File: static/js/core/fleet_core.js (~line 640, inside the fleetTableEnhance area)
Find: document.addEventListener('click', function(e){ ... _closeAllDd() ... });
Fix: ADD right after it:
        window.addEventListener('scroll', function(e){
            if (!_openDd) return;
            if (_openDd.contains(e.target)) return;   // scrolling inside the list is fine
            _closeAllDd();
        }, true);

TASK 1.5 — Category multi-select popover vs on-screen keyboard
File: static/js/core/fleet_core.js (~lines 989-994, function posDD inside
      window._catMultiSelect)
Problem: dd.style.top = r.bottom + 3 can land under the Android keyboard
      (visualViewport is smaller than window.innerHeight).
Fix: in posDD, after computing r, clamp using the visual viewport:
        var vvH = (window.visualViewport && window.visualViewport.height) || window.innerHeight;
        var ddH = dd.offsetHeight || 260;
        var top = r.bottom + 3;
        if (top + ddH > vvH - 8) top = Math.max(8, r.top - ddH - 3);
        if (top + ddH > vvH - 8) top = Math.max(8, vvH - ddH - 8);
        dd.style.top = top + 'px';
      (replace the old dd.style.top assignment; keep the left/width lines).

TASK 1.6 — Screen readers: announce the field name
File: static/js/core/fleet_core.js, inside initSearchableDropdowns, in the
      onInitialize handler (~lines 4515-4531).
Fix: add at the end of onInitialize:
        if (_self.control_input && !_self.control_input.getAttribute('aria-label')) {
            _self.control_input.setAttribute('aria-label', placeholder);
        }
      (the `placeholder` variable is already in scope from the top of the loop).

TASK 1.7 — Phase 1 cache bump + verification (after ALL Phase 1 edits)
- BUMP the ?v= number of static/js/core/fleet_core.js everywhere it is included
  (find with: rg -n "fleet_core.js" templates/).
- Run and paste output:
    node --check static/js/core/fleet_core.js
    rg -n "_isMulti|contains\(e.target\)|aria-label" static/js/core/fleet_core.js | head
    rg -n "fleet_core.js" templates/   (confirm the ?v= number increased)

============================================================
PHASE 2 — DEDUPLICATION (bigger changes; do NOT start without my confirmation)
============================================================

TASK 2.1 — Convert free-text district datalists to the standard searchable select
Fields (all use list="districtOptions" today, storing the district NAME as text):
      templates/driver_form.html   ~582 (driver_district), ~641 (issue_district)
      templates/employee_form.html ~118 (district)
      templates/company_form.html  ~48 (district)
      templates/parking_form.html  ~48 (district)
STEPS for each field:
   1. First confirm the template context has the district list: base.html uses
      `all_districts` (rg -n "all_districts" templates/base.html and the Python
      context processor that provides it). If a form's template does not receive
      it, SKIP that form and report.
   2. Replace the <input ... list="districtOptions" ...> with:
        <select class="form-select search-select" id="<same id>" name="<same name>"
          <keep required / any other attrs>>
          <option value="0">-- Select District --</option>
          {% for d in all_districts %}
            <option value="{{ d.name }}" {% if <current value> == d.name %}selected{% endif %}>{{ d.name }}</option>
          {% endfor %}
        </select>
      CRITICAL: option VALUE must remain the district NAME string (that is what
      the server stores today) — do NOT switch to IDs.
   3. On edit forms, if the stored value is not in the list (legacy typo), add
      one extra <option> for it so the old data still displays.

TASK 2.2 — Unify the duplicated fuel cascade logic (careful — 1:1 move only)
Files: templates/fuel_expense_form.html (cascade/payment/pump JS ~lines 2854-2905,
      3155-3157) and templates/_fuel_expense_form_logic.html (~lines 1673-1683,
      1976-1978).
STEPS:
   1. Diff the two blocks. Extract ONLY the parts that are identical into a new
      file: static/js/fuel_expense_cascade.js (same ES5 style).
   2. Include it from BOTH templates with ?v=1001.
   3. Keep any page-specific differences inline. If more than ~30% differs,
      STOP and report instead of forcing the merge.
   4. Test note: both the desktop form and the mobile form must still cascade
      District→Project→Vehicle→Pump.

TASK 2.3 — Shared WhatsApp approval modal (3 copies → 1 partial)
Copies: templates/oil_expense_list.html (~361-390),
        templates/maintenance_expense_list.html (~324-351),
        templates/maintenance_work_order_list.html (~296-324).
Each has the same structure: modal with Driver select, Payment/Type select,
Location input + datalist — but DIFFERENT element ids (oilApproval*,
maintApproval*, mwoApproval*).
STEPS: create templates/partials/whatsapp_approval_modal.html that takes a
      prefix variable via Jinja ({% include with ... %} or {% set %} + macro),
      generate the SAME ids as today (so each page's existing JS keeps working),
      replace the 3 inline copies with the include. Do NOT change any page JS.
      If the 3 copies differ structurally (not just ids), STOP and report.

============================================================
PHASE 3 — LATER (do NOT do any of this now; listed for the future)
============================================================
- Declarative cascade attributes (data-cascade-child / data-cascade-url) in
  initSearchableDropdowns + migrating ~25 pages' hand-written cascade JS.
- Standard cascade API endpoint (GET /api/cascade/<entity>?parent=...).
- Playwright-style golden test suite: open→search→pick, cascade freshness,
  text-keyboard guard, camera-resume no-auto-open, modal z-index, >300 option
  truncation hint — run at 1280px, 390px, and Capacitor WebView.
- Lazy-init per-row Tom Selects in big grids (unexecuted_task_report,
  driver_attendance_mark) for low-end Androids.
- Build pipeline with content-hashed assets to replace manual ?v= bumping.

============================================================
END OF PROMPT — start with Phase 0 now.
============================================================
```
