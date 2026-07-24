/**
 * Ufone Task Detail popup — Short vs Full view.
 * One VPS/DB fetch always stores full getTaskDetail (76 fields) + comments.
 * Short/Full only changes what is rendered from the same payload.
 */
(function (global) {
  'use strict';

  const EMPTY_VALUES = new Set(['', '0', 'None', 'null', '01 Jan 1900']);

  // Current pre-push popup fields (= Short Details)
  const SHORT_FIELDS = {
    general: [
      ['Task Id', ['_task_id', 'id', 'TaskId', 'task_id']],
      ['Request From', ['RequestFrom', 'request_from']],
      ['Date', ['_date', 'CD', 'CreatedDate']],
      ['Received By', ['ReceivedBy', 'received_by']],
      ['Status', ['Status', 'status']],
      ['Request For', ['RequestFor', 'request_for']],
      ['Closed By', ['ClosedByName', 'TaskClosedBy', 'task_closed_by', 'Closed_By']],
      ['End Time', ['EndTime', 'EndDate', 'CompletedDateTime', 'CompletedDate', 'completed_date']],
      ['Closing Remarks', ['ClosingRemarks', 'closing_remarks']],
    ],
    patient: [
      ['Phone', ['phone', 'Phone']],
      ['CLI', ['phone2', 'CLI', 'Cli']],
      ['Name', ['name', 'Name', 'patient_name']],
      ['Husband Name', ['husband', 'HusbandName', 'husband_name']],
      ['EDD', ['DateDelivery', 'EDD', 'edd']],
      ['Pregnancy Month', ['PregnancyMonth', 'pregnancy_month']],
      ['Age of Child', ['AgeofChild', 'age_of_child']],
      ['Address', ['address', 'Address']],
      ['House Color', ['HouseColor', 'house_color']],
      ['Door Color', ['DoorColor', 'door_color']],
      ['Nearest Landmark', ['NearestLandmark', 'nearest_landmark']],
      ['Location', ['location', 'Location']],
      ['Clinical Details', ['ClinicalDetails', 'clinical_details']],
      ['Union Council', ['UnionCouncil', 'uc_name', 'uc']],
      ['Tehsil', ['Tehsil', 'tehsil_name', 'tehsil']],
      ['District', ['District', 'district_name', 'district']],
    ],
    facility: [
      ['Code', ['facility_code', 'FacilityCode']],
      ['Name', ['facility_name', 'FacilityName']],
      ['Incharge Name', ['InchargeName', 'incharge_name']],
      ['Incharge Phone', ['InchargePhone', 'incharge_phone']],
      ['Change Facility Comments', ['ChangeFacilityComments', 'change_facility_comments']],
    ],
    ambulance: [
      ['Ambulance', ['Ambulance', 'amReg_No', 'ambulance']],
      ['Driver(8:00AM to 8:00PM)', ['_driver_day', 'Driver_Name', 'driver_name']],
      ['Driver(8:00PM to 8:00AM)', ['_driver_night', 'Driver_Name2']],
      ['Mobile', ['MobNo', 'Mobile', 'mobile']],
      ['Distance', ['Distance', 'distanceInKM', 'distance_in_km']],
      ['Task Start Lat', ['taskStartLat', 'task_start_lat']],
      ['Task Start Lon', ['taskStartLon', 'task_start_lon']],
      ['Task End Lat', ['taskEndLat', 'task_end_lat']],
      ['Task End Lon', ['taskEndLon', 'task_end_lon']],
      ['Tracking Company', ['TrackingCompany', 'tracking_company']],
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
      ['Date', ['_date', 'CD', 'CreatedDate']],
      ['Created Time', ['CD_time', 'CreatedTime']],
      ['Closed By', ['ClosedByName']],
      ['End Time', ['EndTime']],
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
  let pendingTaskId = null;
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

  function _commentsHtml(data) {
    const comments = (data.comments && data.comments.length) ? data.comments : [];
    if (!comments.length) {
      return '<h6><i class="bi bi-chat-left-text me-1"></i> Task Comments</h6><hr>' +
        '<p class="text-muted small mb-0">No comments.</p>';
    }
    let html = '<h6><i class="bi bi-chat-left-text me-1"></i> Task Comments</h6><hr>';
    html += '<div class="table-responsive"><table class="table table-sm table-bordered align-middle">';
    html += '<thead class="table-light"><tr><th>Comment Type</th><th>Comments</th><th>Date/Time</th><th>Created By</th></tr></thead><tbody>';
    comments.forEach((c) => {
      const ct = c.CommentType || c.comment_type || c.Comment_Type || '-';
      const cm = c.Comments || c.comments || '-';
      const dt = c.CD || c.CreatedDate || c.Date || c.date_time || '-';
      const cb = c.CBName || c.CreatedBy || c.created_by || '-';
      html += `<tr><td>${ct}</td><td>${cm}</td><td>${dt}</td><td>${cb}</td></tr>`;
    });
    html += '</tbody></table></div>';
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
    const token = ++taskModalToken;
    lastMode = mode === 'full' ? 'full' : 'short';
    const modal = bootstrap.Modal.getOrCreateInstance(cfg.taskModalEl);
    document.getElementById('taskModalBody').innerHTML =
      '<div class="text-center py-5"><div class="spinner-border text-primary"></div><p class="mt-2 text-muted">Loading...</p></div>';
    modal.show();

    // Always load/store full detail+comments once — Short/Full is display-only
    let hadCache = false;
    let needVps = true;
    try {
      const res = await fetch('/ufone/task/' + id);
      const data = await res.json();
      if (token !== taskModalToken) return;
      needVps = data.needs_vps_refresh !== false;
      if (data.detail && Object.keys(data.detail).length) {
        hadCache = true;
        renderTaskDetail(data, needVps, lastMode);
        if (!needVps) return;
      }
    } catch (e) { /* fall through */ }

    try {
      const res = await fetch('/api/ufone/task/' + id + '/vps-refresh');
      const data = await res.json();
      if (token !== taskModalToken) return;
      if (data.detail && Object.keys(data.detail).length) {
        renderTaskDetail(data, false, lastMode);
      } else if (!hadCache) {
        document.getElementById('taskModalBody').innerHTML =
          '<p class="text-danger text-center">Task detail not available yet. Try again.</p>';
      }
    } catch (e) {
      if (token === taskModalToken && !hadCache) {
        document.getElementById('taskModalBody').innerHTML =
          '<p class="text-danger text-center">Error loading details.</p>';
      }
    }
  }

  function showChoice(taskId) {
    pendingTaskId = numericTaskId(taskId);
    if (!cfg || !cfg.choiceModalEl) {
      openTaskDetail(pendingTaskId, 'short');
      return;
    }
    bootstrap.Modal.getOrCreateInstance(cfg.choiceModalEl).show();
  }

  function initUfoneTaskDetail(options) {
    cfg = options || {};
    if (cfg.taskModalEl && cfg.taskModalEl.parentElement !== document.body) {
      document.body.appendChild(cfg.taskModalEl);
    }
    if (cfg.choiceModalEl && cfg.choiceModalEl.parentElement !== document.body) {
      document.body.appendChild(cfg.choiceModalEl);
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
        showChoice(viewBtn.dataset.id);
      }
    });

    const shortBtn = document.getElementById('btnTaskDetailShort');
    const fullBtn = document.getElementById('btnTaskDetailFull');
    if (shortBtn) {
      shortBtn.addEventListener('click', function () {
        const id = pendingTaskId;
        const choice = cfg.choiceModalEl
          ? bootstrap.Modal.getOrCreateInstance(cfg.choiceModalEl)
          : null;
        if (choice) choice.hide();
        if (id) openTaskDetail(id, 'short');
      });
    }
    if (fullBtn) {
      fullBtn.addEventListener('click', function () {
        const id = pendingTaskId;
        const choice = cfg.choiceModalEl
          ? bootstrap.Modal.getOrCreateInstance(cfg.choiceModalEl)
          : null;
        if (choice) choice.hide();
        if (id) openTaskDetail(id, 'full');
      });
    }
  }

  global.UfoneTaskDetail = {
    init: initUfoneTaskDetail,
    open: openTaskDetail,
    numericTaskId: numericTaskId,
    formatTaskId: formatTaskId,
  };
})(window);
