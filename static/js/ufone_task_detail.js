/**
 * Ufone Task Detail popup — Short vs Full view.
 * One VPS/DB fetch always stores full getTaskDetail (76 fields) + comments.
 * Short/Full only changes what is rendered from the same payload.
 */
(function (global) {
  'use strict';

  const EMPTY_VALUES = new Set(['', '0', 'None', 'null', '01 Jan 1900']);

  // Short Details — compact portal-style subset
  const SHORT_FIELDS = {
    general: [
      ['Task Id', ['_task_id', 'id', 'TaskId', 'task_id']],
      ['Task Create Date/Time', ['_date', 'CD', 'CreatedDate']],
      ['Received By', ['ReceivedBy', 'received_by']],
      ['Status', ['Status', 'status']],
      ['Closed By', ['ClosedByName', 'TaskClosedBy', 'task_closed_by', 'Closed_By']],
      ['END Date/Time', ['_end_datetime', 'CompletedDateTime', 'EndDate', 'EndTime', 'CompletedDate', 'completed_date']],
      ['Closing Remarks', ['ClosingRemarks', 'closing_remarks']],
    ],
    patient: [
      ['Phone', ['phone', 'Phone']],
      ['CLI', ['phone2', 'CLI', 'Cli']],
      ['Name', ['name', 'Name', 'patient_name']],
      ['EDD', ['DateDelivery', 'EDD', 'edd']],
      ['Address', ['address', 'Address']],
      ['Location', ['location', 'Location']],
      ['Clinical Details', ['ClinicalDetails', 'clinical_details']],
    ],
    facility: [
      ['Code', ['facility_code', 'FacilityCode']],
      ['Name', ['facility_name', 'FacilityName']],
      ['Incharge Name', ['InchargeName', 'incharge_name']],
      ['Incharge Phone', ['InchargePhone', 'incharge_phone']],
    ],
    ambulance: [
      ['Ambulance', ['Ambulance', 'amReg_No', 'ambulance']],
      ['Driver(8:00AM to 8:00PM)', ['_driver_day', 'Driver_Name', 'driver_name']],
      ['Driver(8:00PM to 8:00AM)', ['_driver_night', 'Driver_Name2']],
      ['Mobile', ['MobNo', 'Mobile', 'mobile']],
    ],
  };

  // Full Details — all getTaskDetail keys, grouped (transfer included)
  const FULL_FIELDS = {
    general: [
      ['Task Id', ['_task_id', 'id', 'TaskId', 'task_id']],
      ['Request From', ['RequestFrom']],
      ['Request For', ['RequestFor']],
      ['Received By', ['ReceivedBy']],
      ['Status', ['Status']],
      ['In Process', ['inProcess']],
      ['Task Create Date/Time', ['_date', 'CD', 'CreatedDate']],
      ['Created Time', ['CD_time', 'CreatedTime']],
      ['Closed By', ['ClosedByName']],
      ['END Date/Time', ['_end_datetime', 'CompletedDateTime', 'EndDate', 'EndTime']],
      ['End Date', ['EndDate']],
      ['Closing Remarks', ['ClosingRemarks']],
    ],
    patient: [
      ['Phone', ['phone']],
      ['CLI', ['phone2']],
      ['Name', ['name']],
      ['Husband Name', ['husband']],
      ['EDD', ['DateDelivery']],
      ['Pregnancy Month', ['PregnancyMonth']],
      ['Age of Child', ['AgeofChild']],
      ['Address', ['address']],
      ['House Color', ['HouseColor']],
      ['Door Color', ['DoorColor']],
      ['Nearest Landmark', ['NearestLandmark']],
      ['Location', ['location']],
      ['Clinical Details', ['ClinicalDetails']],
      ['Union Council', ['UnionCouncil', 'uc_name']],
      ['Tehsil', ['Tehsil', 'tehsil_name']],
      ['District', ['District', 'district_name']],
      ['Patient Loc Lat', ['PLocLat']],
      ['Patient Loc Lon', ['PLocLong']],
    ],
    facility: [
      ['Code', ['facility_code']],
      ['Name', ['facility_name']],
      ['Incharge Name', ['InchargeName']],
      ['Incharge Phone', ['InchargePhone']],
      ['Change Facility Comments', ['ChangeFacilityComments']],
    ],
    transfer1: [
      ['Is Transfer', ['isTransfer']],
      ['Facility Code 2', ['facility_code2']],
      ['Facility Name 2', ['facility_name2']],
      ['Incharge Name 2', ['InchargeName2']],
      ['Incharge Phone 2', ['InchargePhone2']],
      ['Transfer Date', ['Tr_CD']],
      ['Transfer Time', ['Tr_CD_time']],
      ['Transfer Clinical Details', ['Tr_ClinicalDetails']],
      ['Transfer By', ['TransferByName']],
      ['Doctor Detail', ['doctorDetail']],
    ],
    transfer2: [
      ['Is Transfer 2', ['isTransfer2']],
      ['Facility Code 3', ['facility_code3']],
      ['Facility Name 3', ['facility_name3']],
      ['Incharge Name 3', ['InchargeName3']],
      ['Incharge Phone 3', ['InchargePhone3']],
      ['Transfer Date 2', ['Tr_CD2']],
      ['Transfer Time 2', ['Tr_CD_time2']],
      ['Transfer Clinical Details 2', ['Tr_ClinicalDetails2']],
      ['Transfer By 2', ['TransferByName2']],
      ['Doctor Detail 2', ['doctorDetail2']],
    ],
    ambulance: [
      ['Ambulance', ['Ambulance', 'amReg_No']],
      ['Amb Id', ['ambId']],
      ['Amb SIM No', ['ambSIM_No']],
      ['Driver(8:00AM to 8:00PM)', ['_driver_day', 'Driver_Name']],
      ['Driver Cell Day', ['Driver_Cell']],
      ['Driver(8:00PM to 8:00AM)', ['_driver_night', 'Driver_Name2']],
      ['Driver Cell Night', ['Driver_Cell2']],
      ['Mobile', ['MobNo']],
      ['Distance', ['Distance']],
      ['Task Start Lat', ['taskStartLat']],
      ['Task Start Lon', ['taskStartLon']],
      ['Task End Lat', ['taskEndLat']],
      ['Task End Lon', ['taskEndLon']],
      ['Tracking Company', ['TrackingCompany']],
      ['UTrack No', ['UTrackNo']],
    ],
  };

  const FULL_SECTION_META = [
    ['general', 'General', 'bi-card-heading', true],
    ['patient', 'Patient Info', 'bi-person-vcard', false],
    ['facility', 'Facility Detail', 'bi-hospital', false],
    ['transfer1', 'Transfer 1', 'bi-arrow-left-right', false],
    ['transfer2', 'Transfer 2', 'bi-arrow-left-right', false],
    ['ambulance', 'Ambulance / Driver / GPS', 'bi-truck', false],
  ];

  let taskModalToken = 0;
  let lastPayload = null;
  let lastMode = 'short';
  let cfg = null;

  function _pick(detail, keys) {
    for (const k of keys) {
      const v = detail[k];
      if (v === null || v === undefined) continue;
      const s = String(v).trim();
      if (!EMPTY_VALUES.has(s)) return s;
    }
    return '';
  }

  function formatTaskId(raw) {
    const s = String(raw == null ? '' : raw).trim();
    if (!s) return '';
    if (/^PHF-/i.test(s)) return s.toUpperCase().replace(/^phf-/i, 'PHF-');
    const n = s.replace(/\D/g, '');
    return n ? ('PHF-' + n) : s;
  }

  function numericTaskId(raw) {
    const s = String(raw == null ? '' : raw).trim();
    const n = s.replace(/^PHF-/i, '').replace(/\D/g, '');
    return n || s;
  }

  function prepDetail(d) {
    const cd = _pick(d, ['CD', 'CreatedDate']);
    const ct = _pick(d, ['CD_time', 'CreatedTime']);
    d._date = [cd, ct].filter(Boolean).join(' ');
    // END Date/Time: prefer full CompletedDateTime; else EndDate + EndTime
    const endFull = _pick(d, ['CompletedDateTime', 'CompletedDate', 'completed_date']);
    const endDate = _pick(d, ['EndDate']);
    const endTime = _pick(d, ['EndTime']);
    if (endFull) {
      d._end_datetime = endFull;
    } else {
      d._end_datetime = [endDate, endTime].filter(Boolean).join(' ');
    }
    const dn = _pick(d, ['Driver_Name']);
    const dc = _pick(d, ['Driver_Cell']);
    d._driver_day = dn ? (dc ? `${dn} (${dc})` : dn) : '';
    const dn2 = _pick(d, ['Driver_Name2']);
    const dc2 = _pick(d, ['Driver_Cell2']);
    d._driver_night = dn2 ? (dc2 ? `${dn2} (${dc2})` : dn2) : '';
    d._task_id = formatTaskId(_pick(d, ['id', 'TaskId', 'task_id']));
    return d;
  }

  function _field(label, keys, d) {
    const v = _pick(d, keys);
    return `<div class="uf-frow"><label>${label}:</label><div class="field-value${v ? '' : ' empty'}">${v || '—'}</div></div>`;
  }

  function _section(title, icon, fields, d, generalGrid) {
    let html = `<h6><i class="bi ${icon} me-1"></i> ${title}</h6><hr>`;
    html += `<div class="uf-fgrid${generalGrid ? ' uf-general' : ''}">`;
    for (const [label, keys] of fields) {
      html += _field(label, keys, d);
    }
    html += '</div>';
    return html;
  }

  function _modeToggleHtml(mode) {
    const shortActive = mode === 'short' ? 'active' : '';
    const fullActive = mode === 'full' ? 'active' : '';
    return (
      `<div class="d-flex gap-2 mb-2 align-items-center flex-wrap">` +
      `<div class="btn-group btn-group-sm" role="group">` +
      `<button type="button" class="btn btn-outline-success uf-td-mode ${shortActive}" data-mode="short">Short Details</button>` +
      `<button type="button" class="btn btn-outline-success uf-td-mode ${fullActive}" data-mode="full">Full Details</button>` +
      `</div>` +
      `<span class="small text-muted">Same DB/VPS data — view only</span>` +
      `</div>`
    );
  }

  const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  /* Comment types that mark forward progress get the green dot in the mobile
     timeline; everything else stays blue. */
  const COMMENT_DONE_RE = /assign|complete|close|arriv|reach|deliver|handover|drop|confirm/i;

  function _escHtml(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /* Timestamps arrive in whatever shape Ufone sent. Normalise the two common
     ones to "01 Aug 2026, 22:13:14"; anything else is shown as-is. */
  function _commentWhen(raw) {
    const s = String(raw == null ? '' : raw).trim();
    if (!s) return '-';
    let m = s.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}:\d{2}(?::\d{2})?)/);
    if (m) return `${m[3]} ${MONTH_ABBR[+m[2] - 1]} ${m[1]}, ${m[4]}`;
    m = s.match(/^(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s+(\d{1,2}:\d{2}(?::\d{2})?)/);
    if (m) return `${m[1]}, ${m[2]}`;
    return s;
  }

  function _commentsHtml(data) {
    const comments = (data.comments && data.comments.length) ? data.comments : [];
    const heading = '<h6><i class="bi bi-chat-left-text me-1"></i> Task Comments</h6><hr>';
    if (!comments.length) {
      return heading + '<p class="text-muted small mb-0">No comments.</p>';
    }

    const rows = comments.map((c) => ({
      type: _escHtml(c.CommentType || c.comment_type || c.Comment_Type || '-'),
      text: _escHtml(c.Comments || c.comments || '-'),
      when: _escHtml(_commentWhen(c.CD || c.CreatedDate || c.Date || c.date_time)),
      who: _escHtml(c.CBName || c.CreatedBy || c.created_by || '-'),
      done: COMMENT_DONE_RE.test(c.CommentType || c.comment_type || c.Comment_Type || ''),
    }));

    let html = heading;

    // Desktop: table. data-mp-skip-cards keeps fleet_mobile.js from replacing
    // it with card markup and hiding it.
    html += '<div class="table-responsive uf-comments-table-wrap">';
    html += '<table class="table table-sm table-bordered align-middle uf-comments-table" data-mp-skip-cards="1">';
    html += '<thead class="table-light"><tr><th>Comment Type</th><th>Comments</th><th>Date/Time</th><th>Created By</th></tr></thead><tbody>';
    rows.forEach((r) => {
      html += `<tr><td>${r.type}</td><td>${r.text}</td><td>${r.when}</td><td>${r.who}</td></tr>`;
    });
    html += '</tbody></table></div>';

    // Phones: four columns never fit, so the same rows render as a timeline.
    html += '<div class="uf-ct-timeline">';
    rows.forEach((r) => {
      html += `<div class="uf-ct-item${r.done ? ' is-done' : ''}"><div class="uf-ct-box">` +
        `<div class="uf-ct-meta">` +
        `<div class="uf-ct-author"><span>${r.who}</span><span class="uf-ct-tag">${r.type}</span></div>` +
        `<span class="uf-ct-time">${r.when}</span>` +
        `</div><div class="uf-ct-text">${r.text}</div></div></div>`;
    });
    html += '</div>';

    return html;
  }

  function _coveredKeys(fieldGroups) {
    const used = new Set(['_task_id', '_date', '_driver_day', '_driver_night']);
    Object.values(fieldGroups).forEach((fields) => {
      fields.forEach(([, keys]) => keys.forEach((k) => used.add(k)));
    });
    return used;
  }

  function _otherFieldsHtml(d, covered) {
    const leftovers = Object.keys(d)
      .filter((k) => !covered.has(k) && !String(k).startsWith('_'))
      .sort();
    if (!leftovers.length) return '';
    let html = '<h6><i class="bi bi-list-ul me-1"></i> Other Fields</h6><hr>';
    html += '<div class="uf-fgrid">';
    leftovers.forEach((k) => {
      html += _field(k, [k], d);
    });
    html += '</div>';
    return html;
  }

  function renderTaskDetail(data, liveUpdating, mode) {
    if (!cfg) return;
    const body = document.getElementById('taskModalBody');
    if (!data || !data.detail || Object.keys(data.detail).length === 0) {
      body.innerHTML = '<p class="text-muted text-center py-5">No details found.</p>';
      return;
    }
    lastPayload = data;
    lastMode = mode === 'full' ? 'full' : 'short';

    const titleEl = cfg.taskModalEl.querySelector('.modal-title');
    if (titleEl) {
      titleEl.innerHTML = lastMode === 'full'
        ? '<i class="bi bi-info-circle me-1"></i> Task Detail — Full'
        : '<i class="bi bi-info-circle me-1"></i> Task Detail — Short';
    }

    const d = prepDetail(Object.assign({}, data.detail));
    let html = _modeToggleHtml(lastMode);

    if (liveUpdating) {
      html += '<div class="alert alert-light py-1 small mb-2"><span class="spinner-border spinner-border-sm me-2"></span>DB data shown — PK VPS se full detail / comments update ho raha hai...</div>';
    } else if (data.vps_skipped) {
      html += '<div class="alert alert-light py-1 small mb-2 text-muted"><i class="bi bi-database-check"></i> Closed task — DB cache (VPS skip)</div>';
    } else if (data.vps_refreshed) {
      html += '<div class="alert alert-light py-1 small mb-2 text-muted"><i class="bi bi-cloud-check"></i> Live from PK VPS (saved to DB)</div>';
    } else if (data.bridge_only) {
      html += '<div class="alert alert-light py-1 small mb-2 text-muted"><i class="bi bi-cloud-check"></i> PK VPS bridge data</div>';
    } else if (data.from_cache) {
      html += '<div class="alert alert-warning py-1 small mb-2"><i class="bi bi-clock-history"></i> Cached data (Ufone live server not responding)</div>';
    }

    if (lastMode === 'short') {
      html += '<div class="uf-fgrid uf-general mb-1">';
      SHORT_FIELDS.general.forEach(([label, keys]) => {
        html += _field(label, keys, d);
      });
      html += '</div>';
      html += _section('Patient Info', 'bi-person-vcard', SHORT_FIELDS.patient, d, false);
      html += _section('Facility Detail', 'bi-hospital', SHORT_FIELDS.facility, d, false);
      html += _section('Ambulance / Driver', 'bi-truck', SHORT_FIELDS.ambulance, d, false);
      const comments = (data.comments && data.comments.length) ? data.comments : [];
      if (comments.length) html += _commentsHtml(data);
    } else {
      FULL_SECTION_META.forEach(([key, title, icon, isGeneral]) => {
        const fields = FULL_FIELDS[key];
        if (!fields) return;
        if (key === 'general') {
          html += '<div class="uf-fgrid uf-general mb-1">';
          fields.forEach(([label, keys]) => {
            html += _field(label, keys, d);
          });
          html += '</div>';
        } else {
          html += _section(title, icon, fields, d, isGeneral);
        }
      });
      html += _otherFieldsHtml(d, _coveredKeys(FULL_FIELDS));
      html += _commentsHtml(data);
    }

    body.innerHTML = html;
  }

  async function openTaskDetail(id, mode) {
    if (!cfg) return;
    id = numericTaskId(id);
    if (!id) {
      document.getElementById('taskModalBody').innerHTML =
        '<p class="text-danger text-center">Invalid task id.</p>';
      return;
    }
    const token = ++taskModalToken;
    lastMode = mode === 'full' ? 'full' : 'short';
    const modal = bootstrap.Modal.getOrCreateInstance(cfg.taskModalEl);
    document.getElementById('taskModalBody').innerHTML =
      '<div class="text-center py-5"><div class="spinner-border text-primary"></div><p class="mt-2 text-muted">Loading...</p></div>';
    modal.show();

    // Always load/store full detail+comments once — Short/Full is display-only
    let hadCache = false;
    let needVps = true;
    let stage1Error = '';
    try {
      const res = await fetch('/ufone/task/' + id);
      const data = await res.json().catch(() => ({}));
      if (token !== taskModalToken) return;
      if (!res.ok) {
        stage1Error = data.error || ('HTTP ' + res.status);
      }
      needVps = data.needs_vps_refresh !== false;
      if (data.detail && Object.keys(data.detail).length) {
        hadCache = true;
        renderTaskDetail(data, needVps, lastMode);
        if (!needVps) return;
      }
    } catch (e) { /* fall through */ }

    try {
      const res = await fetch('/api/ufone/task/' + id + '/vps-refresh');
      const data = await res.json().catch(() => ({}));
      if (token !== taskModalToken) return;
      if (data.detail && Object.keys(data.detail).length) {
        renderTaskDetail(data, false, lastMode);
      } else if (!hadCache) {
        const why = data.error || data.warning || stage1Error || 'DB/VPS mein detail abhi nahi mili';
        document.getElementById('taskModalBody').innerHTML =
          `<p class="text-danger text-center">Task detail not available yet. Try again.</p>` +
          `<p class="text-muted text-center small">${why}</p>`;
      }
    } catch (e) {
      if (token === taskModalToken && !hadCache) {
        document.getElementById('taskModalBody').innerHTML =
          '<p class="text-danger text-center">Error loading details.</p>';
      }
    }
  }

  function initUfoneTaskDetail(options) {
    cfg = options || {};
    if (cfg.taskModalEl && cfg.taskModalEl.parentElement !== document.body) {
      document.body.appendChild(cfg.taskModalEl);
    }

    document.addEventListener('click', function (ev) {
      const modeBtn = ev.target.closest('.uf-td-mode');
      if (modeBtn && lastPayload) {
        ev.preventDefault();
        renderTaskDetail(lastPayload, false, modeBtn.getAttribute('data-mode'));
        return;
      }

      const viewBtn = ev.target.closest(cfg.viewBtnSelector || '.task-detail-btn');
      if (viewBtn) {
        ev.preventDefault();
        // Open Short by default; Full toggle is inside the detail modal
        openTaskDetail(numericTaskId(viewBtn.dataset.id), 'short');
      }
    });
  }

  global.UfoneTaskDetail = {
    init: initUfoneTaskDetail,
    open: openTaskDetail,
    numericTaskId: numericTaskId,
    formatTaskId: formatTaskId,
  };
})(window);
