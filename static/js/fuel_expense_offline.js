/**
 * Offline queue for Add/Edit Fuel Expense — IndexedDB + auto-sync on reconnect.
 */
(function (global) {
  'use strict';

  var DB_NAME = 'fleet_fuel_offline_v1';
  var DB_VERSION = 1;
  var STORE = 'pending_entries';

  function openDb() {
    return new Promise(function (resolve, reject) {
      if (!global.indexedDB) {
        reject(new Error('IndexedDB unavailable'));
        return;
      }
      var req = global.indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
        }
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error || new Error('IndexedDB open failed')); };
    });
  }

  function toast(msg) {
    try {
      if (global.FleetBridge && typeof global.FleetBridge._toast === 'function') {
        global.FleetBridge._toast(msg);
        return;
      }
    } catch (e) { /* ignore */ }
    try {
      var host = document.getElementById('fleetOfflineToastHost');
      if (!host) {
        host = document.createElement('div');
        host.id = 'fleetOfflineToastHost';
        host.className = 'fleet-notif-toast-host';
        document.body.appendChild(host);
      }
      var el = document.createElement('div');
      el.className = 'fleet-notif-toast';
      el.textContent = msg;
      host.appendChild(el);
      setTimeout(function () {
        el.classList.add('fleet-notif-toast--out');
        setTimeout(function () { el.remove(); }, 300);
      }, 4200);
    } catch (e2) { /* ignore */ }
  }

  function blobToArrayBuffer(blob) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(reader.result); };
      reader.onerror = function () { reject(reader.error); };
      reader.readAsArrayBuffer(blob);
    });
  }

  function arrayBufferToBlob(buf, type) {
    return new Blob([buf], { type: type || 'application/octet-stream' });
  }

  function serializeFormData(formData) {
    var fields = [];
    var files = [];
    var promises = [];
    formData.forEach(function (value, key) {
      if (value instanceof File) {
        promises.push(blobToArrayBuffer(value).then(function (buf) {
          files.push({
            key: key,
            name: value.name,
            type: value.type || 'application/octet-stream',
            buffer: buf,
          });
        }));
      } else {
        fields.push({ key: key, value: String(value) });
      }
    });
    return Promise.all(promises).then(function () {
      return { fields: fields, files: files };
    });
  }

  function rebuildFormData(payload) {
    var fd = new FormData();
    (payload.fields || []).forEach(function (row) {
      fd.append(row.key, row.value);
    });
    var filePromises = (payload.files || []).map(function (f) {
      var blob = arrayBufferToBlob(f.buffer, f.type);
      var file = new File([blob], f.name || 'upload', { type: f.type || 'application/octet-stream' });
      fd.append(f.key, file, file.name);
    });
    return Promise.all(filePromises).then(function () { return fd; });
  }

  function savePending(formEl, submitter) {
    if (!formEl) return Promise.reject(new Error('No form'));
    var url = formEl.getAttribute('action') || global.location.href;
    var fd = new FormData(formEl);
    if (submitter && submitter.name) {
      fd.append(submitter.name, submitter.value || '');
    }
    return serializeFormData(fd).then(function (payload) {
      var entry = {
        url: url,
        createdAt: new Date().toISOString(),
        payload: payload,
      };
      return openDb().then(function (db) {
        return new Promise(function (resolve, reject) {
          var tx = db.transaction(STORE, 'readwrite');
          tx.objectStore(STORE).add(entry);
          tx.oncomplete = function () { db.close(); resolve(entry); };
          tx.onerror = function () { db.close(); reject(tx.error); };
        });
      });
    }).then(function () {
      toast('No internet — fuel entry saved offline. It will sync automatically when you are back online.');
      if (global.navigator && global.navigator.serviceWorker && global.navigator.serviceWorker.ready) {
        global.navigator.serviceWorker.ready.then(function (reg) {
          if (reg.sync && typeof reg.sync.register === 'function') {
            reg.sync.register('fleet-fuel-sync').catch(function () {});
          }
        }).catch(function () {});
      }
    });
  }

  function listPending() {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, 'readonly');
        var req = tx.objectStore(STORE).getAll();
        req.onsuccess = function () { db.close(); resolve(req.result || []); };
        req.onerror = function () { db.close(); reject(req.error); };
      });
    });
  }

  function deletePending(id) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).delete(id);
        tx.oncomplete = function () { db.close(); resolve(); };
        tx.onerror = function () { db.close(); reject(tx.error); };
      });
    });
  }

  function syncOne(entry) {
    return rebuildFormData(entry.payload).then(function (fd) {
      return fetch(entry.url, {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
        redirect: 'follow',
      });
    });
  }

  function syncPending() {
    if (!global.navigator.onLine) return Promise.resolve(0);
    return listPending().then(function (rows) {
      if (!rows.length) return 0;
      var chain = Promise.resolve(0);
      rows.forEach(function (entry) {
        chain = chain.then(function (synced) {
          return syncOne(entry).then(function (resp) {
            if (resp && resp.ok) {
              return deletePending(entry.id).then(function () { return synced + 1; });
            }
            return synced;
          }).catch(function () { return synced; });
        });
      });
      return chain.then(function (count) {
        if (count > 0) {
          var msg = count === 1
            ? '1 pending fuel entry synced to live server successfully.'
            : (count + ' pending fuel entries synced to live server successfully.');
          toast(msg);
        }
        return count;
      });
    });
  }

  function submitWithOfflineFallback(formEl, submitter) {
    if (!formEl) return Promise.reject(new Error('No form'));
    var url = formEl.getAttribute('action') || global.location.href;
    var fd = new FormData(formEl);
    if (submitter && submitter.name) {
      fd.append(submitter.name, submitter.value || '');
    }
    if (!global.navigator.onLine) {
      return savePending(formEl, submitter);
    }
    return fetch(url, {
      method: 'POST',
      body: fd,
      credentials: 'same-origin',
      redirect: 'follow',
    }).then(function (resp) {
      if (resp.redirected && resp.url) {
        global.location.href = resp.url;
        return;
      }
      if (resp.ok) {
        global.location.reload();
        return;
      }
      return resp.text().then(function () {
        throw new Error('Save failed (' + resp.status + ')');
      });
    }).catch(function (err) {
      var offline = !global.navigator.onLine
        || (err && err.message && /failed to fetch|network|load/i.test(err.message));
      if (offline) {
        return savePending(formEl, submitter);
      }
      throw err;
    });
  }

  global.FuelExpenseOffline = {
    savePending: savePending,
    syncPending: syncPending,
    submitWithOfflineFallback: submitWithOfflineFallback,
    toast: toast,
  };

  global.addEventListener('online', function () {
    syncPending();
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      if (global.navigator.onLine) syncPending();
    });
  } else if (global.navigator.onLine) {
    syncPending();
  }

  if (global.navigator.serviceWorker) {
    global.navigator.serviceWorker.addEventListener('message', function (ev) {
      if (ev.data && ev.data.type === 'fleet-fuel-sync') syncPending();
    });
  }
})(window);
