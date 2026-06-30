/* ═══════════════════════════════════════════════════════════════
   Fleet Manager — Core JS (extracted from base.html)
   ═══════════════════════════════════════════════════════════════ */

/* Capacitor native: resizes-content shrinks the shell and lifts bottom nav above the keyboard app-wide. */
    (function fleetCapNativeViewportEarly() {
        try {
            var cap = window.Capacitor;
            if (!cap || !cap.isNativePlatform || !cap.isNativePlatform()) return;
            document.documentElement.classList.add('capacitor-native');
            var m = document.getElementById('metaViewport');
            if (!m) return;
            var c = m.getAttribute('content') || '';
            if (c.indexOf('resizes-content') !== -1) {
                m.setAttribute('content', c.replace('interactive-widget=resizes-content', 'interactive-widget=resizes-visual'));
            }
        } catch (e) {}
    })();

/* ── Section separator ── */

/* ═══════════════════════════════════════════════════════════════════
       initServerSearch  — HTML-over-the-wire AJAX live search
       Strategy: fetch full page, DOMParser to extract tbody +
       .table-footer, swap in-place, keep cursor focus.
       No backend changes required.
       ═══════════════════════════════════════════════════════════════════ */
    window.initServerSearch = function(elOrId, paramName) {
        var input = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
        if (!input) return;
        paramName = paramName || 'q';

        /* ── Pre-fill from current URL ── */
        var curVal = new URLSearchParams(window.location.search).get(paramName) || '';
        if (curVal) input.value = curVal;

        /* ── Build a DEDICATED wrapper around ONLY the input element.
             Never pollute the flex row that also holds "Per Page" / other siblings. ── */
        var wrapper;
        if (input.parentElement && input.parentElement.classList.contains('ss-wrap')) {
            wrapper = input.parentElement;           /* already wrapped — idempotent */
        } else {
            wrapper = document.createElement('div');
            wrapper.className = 'ss-wrap';
            /* Insert wrapper in place of input, then move input inside it */
            input.parentNode.insertBefore(wrapper, input);
            wrapper.appendChild(input);
        }
        /* Inject spinner once */
        if (!wrapper.querySelector('.ss-spinner')) {
            var spinner = document.createElement('span');
            spinner.className = 'ss-spinner';
            wrapper.appendChild(spinner);
        }
        var parent = wrapper;   /* all subsequent loading-class toggles target the wrapper */

        /* ── Build new search URL ── */
        function buildUrl(val) {
            var p = new URLSearchParams(window.location.search);
            if (val) { p.set(paramName, val); } else { p.delete(paramName); }
            p.set('page', '1');
            return window.location.pathname + '?' + p.toString();
        }

        /* ── AJAX swap: fetch → DOMParser → replace tbody + footer ── */
        var inFlight = null;
        function doSearch(val) {
            var url = buildUrl(val);

            /* Show spinner */
            if (parent) parent.classList.add('ss-loading');

            /* Abort previous in-flight fetch if still pending */
            if (inFlight) inFlight.abort();
            var ctrl = new AbortController();
            inFlight = ctrl;

            fetch(url, {
                signal: ctrl.signal,
                headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'text/html' }
            })
            .then(function(r) { return r.text(); })
            .then(function(html) {
                inFlight = null;

                var doc = new DOMParser().parseFromString(html, 'text/html');

                /* ── Replace <tbody> ── */
                var newTbody = doc.querySelector('table.table tbody, table tbody');
                var curTbody = document.querySelector('table.table tbody, table tbody');
                if (newTbody && curTbody) {
                    curTbody.innerHTML = newTbody.innerHTML;
                    /* Tiny fade-in on fresh rows */
                    curTbody.classList.remove('ss-updated');
                    void curTbody.offsetWidth;   /* force reflow */
                    curTbody.classList.add('ss-updated');
                }

                /* ── Replace .table-footer (pagination + count) ── */
                var newFoot = doc.querySelector('.table-footer');
                var curFoot = document.querySelector('.table-footer');
                if (newFoot && curFoot) {
                    curFoot.outerHTML = newFoot.outerHTML;
                }

                /* ── Push URL without reload ── */
                history.pushState({ ssVal: val, ssParam: paramName }, '', url);

                /* ── Restore focus + cursor at end ── */
                if (parent) parent.classList.remove('ss-loading');
                input.focus();
                var len = input.value.length;
                try { input.setSelectionRange(len, len); } catch(e) {}
            })
            .catch(function(err) {
                if (err && err.name === 'AbortError') return;  /* intentional abort */
                /* Network error or parse failure — fall back to normal navigation */
                if (parent) parent.classList.remove('ss-loading');
                window.location.href = url;
            });
        }

        /* ── Debounced input listener (300 ms) ── */
        var debounceTimer;
        input.addEventListener('input', function() {
            clearTimeout(debounceTimer);
            var val = this.value.trim();
            debounceTimer = setTimeout(function() { doSearch(val); }, 300);
        });

        /* ── Browser back/forward: restore search state ── */
        window.addEventListener('popstate', function(e) {
            if (e.state && e.state.ssParam === paramName) {
                input.value = e.state.ssVal || '';
                doSearch(e.state.ssVal || '');
            }
        });
    };

    // ── Global Multi-Word AND Search Helper ──
    window.fleetMultiWordMatch = function(text, query) {
        if (!query || !query.trim()) return true;
        var words = query.toLowerCase().split(/\s+/).filter(Boolean);
        var lower = (text || '').toLowerCase();
        for (var i = 0; i < words.length; i++) {
            if (lower.indexOf(words[i]) === -1) return false;
        }
        return true;
    };

    // ── Table Column Sort & Excel-like Filter ──
    (function(){
      var _styleInjected=false,_openDd=null,_openDdBtn=null;
      function _closeAllDd(){document.querySelectorAll('.ft-filter-dd,.ft-af-overlay').forEach(function(d){d.remove()});_openDd=null;_openDdBtn=null;}
      function _repositionDd(){if(!_openDd||!_openDdBtn)return;var r=_openDdBtn.getBoundingClientRect(),w=_openDd.offsetWidth,h=_openDd.offsetHeight,l=r.left,t=r.bottom+2;if(l+w>innerWidth-8)l=r.right-w;if(l<4)l=4;if(t+h>innerHeight-8)t=r.top-h-2;if(t<4)t=4;_openDd.style.left=l+'px';_openDd.style.top=t+'px';}
      addEventListener('scroll',_repositionDd,true);addEventListener('resize',_repositionDd);

      function _posSubmenu(parent,sub){
        sub.style.position='fixed';sub.style.display='block';sub.style.visibility='hidden';
        var pr=parent.getBoundingClientRect(),sw=sub.offsetWidth,sh=sub.offsetHeight;
        var left=pr.right+2,top=pr.top;
        if(left+sw>innerWidth-8)left=pr.left-sw-2;
        if(left<4)left=4;
        if(top+sh>innerHeight-8)top=innerHeight-8-sh;
        if(top<4)top=4;
        sub.style.left=left+'px';sub.style.top=top+'px';sub.style.visibility='';
      }

      function _openAutoFilterDlg(colName,isNum,existFilter,onApply){
        var overlay=document.createElement('div');overlay.className='ft-af-overlay';document.body.appendChild(overlay);
        var dlg=document.createElement('div');dlg.className='ft-af-dlg';overlay.appendChild(dlg);
        var hdr=document.createElement('div');hdr.className='ft-af-hdr';
        hdr.innerHTML='<span>Custom AutoFilter</span><span class="ft-af-close">&times;</span>';
        dlg.appendChild(hdr);
        var body=document.createElement('div');body.className='ft-af-body';dlg.appendChild(body);

        body.innerHTML='<div class="ft-af-label">Show rows where:</div><div class="ft-af-label fw-bold" style="margin-bottom:6px">'+colName+'</div>';
        var ops=isNum?[['eq','equals'],['neq','does not equal'],['gt','is greater than'],['gte','is greater than or equal to'],['lt','is less than'],['lte','is less than or equal to']]:
                      [['eq','equals'],['neq','does not equal'],['contains','contains'],['ncontains','does not contain'],['begins','begins with'],['ends','ends with']];
        var ef=existFilter||{};
        function mkRow(idx){
          var wrap=document.createElement('div');wrap.style.cssText='display:flex;gap:6px;align-items:center;margin-bottom:6px';
          var sel=document.createElement('select');sel.className='ft-af-sel';
          ops.forEach(function(o){var opt=document.createElement('option');opt.value=o[0];opt.textContent=o[1];sel.appendChild(opt)});
          var inp=document.createElement('input');inp.className='ft-af-inp';inp.type=isNum?'number':'text';inp.placeholder='Value';
          if(idx===0&&ef.op1){sel.value=ef.op1;inp.value=ef.val1||'';}
          if(idx===1&&ef.op2){sel.value=ef.op2;inp.value=ef.val2||'';}
          wrap.appendChild(sel);wrap.appendChild(inp);return{el:wrap,sel:sel,inp:inp};
        }
        var r1=mkRow(0);body.appendChild(r1.el);
        var modeDiv=document.createElement('div');modeDiv.style.cssText='display:flex;gap:12px;align-items:center;margin:6px 0;font-size:12px';
        var radAnd=document.createElement('input');radAnd.type='radio';radAnd.name='ft_af_mode';radAnd.value='and';radAnd.checked=!ef.mode||ef.mode==='and';
        var radOr=document.createElement('input');radOr.type='radio';radOr.name='ft_af_mode';radOr.value='or';if(ef.mode==='or')radOr.checked=true;
        var lbA=document.createElement('label');lbA.style.cssText='display:flex;align-items:center;gap:3px;cursor:pointer';lbA.appendChild(radAnd);lbA.appendChild(document.createTextNode('And'));
        var lbO=document.createElement('label');lbO.style.cssText='display:flex;align-items:center;gap:3px;cursor:pointer';lbO.appendChild(radOr);lbO.appendChild(document.createTextNode('Or'));
        modeDiv.appendChild(lbA);modeDiv.appendChild(lbO);body.appendChild(modeDiv);
        var r2=mkRow(1);body.appendChild(r2.el);

        if(!isNum){body.innerHTML+='<div style="margin-top:8px;font-size:10px;color:#888">Use ? to represent any single character<br>Use * to represent any series of characters</div>';}

        var foot=document.createElement('div');foot.className='ft-af-foot';
        var btnOk=document.createElement('button');btnOk.className='ft-af-ok';btnOk.textContent='OK';
        var btnCancel=document.createElement('button');btnCancel.className='ft-af-cancel';btnCancel.textContent='Cancel';
        foot.appendChild(btnOk);foot.appendChild(btnCancel);dlg.appendChild(foot);

        function close(){overlay.remove();}
        hdr.querySelector('.ft-af-close').onclick=close;
        btnCancel.onclick=close;
        overlay.addEventListener('click',function(e){if(e.target===overlay)close();});
        btnOk.onclick=function(){
          var result={op1:r1.sel.value,val1:r1.inp.value,op2:r2.sel.value,val2:r2.inp.value,mode:radAnd.checked?'and':'or',isNum:isNum};
          if(!r1.inp.value&&!r2.inp.value){onApply(null);}else{onApply(result);}
          close();
        };
        setTimeout(function(){r1.inp.focus();},50);
      }

      window.fleetTableEnhance=function(tableId){
        var tbl=document.getElementById(tableId);if(!tbl)return;
        if(tbl.dataset && tbl.dataset.ftEnhanced==='1')return;
        var thead=tbl.querySelector('thead');if(!thead)return;
        var ths=thead.querySelectorAll('th'),tbody=tbl.querySelector('tbody');if(!tbody)return;
        if(tbl.dataset)tbl.dataset.ftEnhanced='1';
        var _sortCol=-1,_sortAsc=true,_filters={},_numFilters={},_txtFilters={},_customFilters={};
        var _allRowsLoaded=false,_allRowsLoading=false,_allRowsCallbacks=[];
        var _initialPageHtml=tbody.innerHTML,_allRowsHtml='',_usingAllRows=false;
        var _clientPage=1;

        if(!_styleInjected){_styleInjected=true;var s=document.createElement('style');s.textContent=
          '.ft-sort{cursor:pointer;user-select:none;position:relative;padding-right:18px!important}'+
          '.ft-sort:after{content:"\\2195";position:absolute;right:2px;top:50%;transform:translateY(-50%);opacity:.2;font-size:.65rem}'+
          '.ft-sort.asc:after{content:"\\2191";opacity:.8;color:#0d6efd}.ft-sort.desc:after{content:"\\2193";opacity:.8;color:#0d6efd}'+
          '.ft-filter-wrap{position:relative;display:inline-block;margin-left:2px;vertical-align:middle}'+
          '.ft-filter-btn{cursor:pointer;font-size:9px;opacity:.3;vertical-align:middle;padding:1px;transition:all .15s}'+
          '.ft-filter-btn:hover{opacity:.85;color:#0d6efd;transform:scale(1.15)}.ft-filter-btn.active{opacity:1;color:#0d6efd}'+
          '.ft-filter-dd{position:fixed;z-index:99999;background:#fff;border:1px solid #bbb;border-radius:3px;box-shadow:0 4px 16px rgba(0,0,0,.25);min-width:190px;max-width:290px;font-size:12px;font-weight:normal;color:#222}'+
          '.ft-filter-dd .ft-dd-header{padding:4px 7px;border-bottom:1px solid #e0e0e0;display:flex;align-items:center;justify-content:space-between}'+
          '.ft-filter-dd .ft-dd-header span{font-weight:600;font-size:11px;color:#333}'+
          '.ft-filter-dd .ft-dd-clear{font-size:10px;color:#dc3545;cursor:pointer;text-decoration:underline;padding:0 2px}.ft-filter-dd .ft-dd-clear:hover{color:#a71d2a}'+
          '.ft-filter-dd .ft-dd-search{padding:5px 7px;border-bottom:1px solid #e0e0e0}'+
          '.ft-filter-dd .ft-dd-search input{width:100%;padding:3px 6px;border:1px solid #bbb;border-radius:2px;font-size:11px;outline:none}'+
          '.ft-filter-dd .ft-dd-search input:focus{border-color:#86b7fe;box-shadow:0 0 0 2px rgba(13,110,253,.12)}'+
          '.ft-filter-dd .ft-dd-toggle{padding:4px 7px;border-bottom:1px solid #e0e0e0;cursor:pointer;font-size:11px;color:#0d6efd;display:flex;align-items:center;gap:4px;user-select:none;position:relative}'+
          '.ft-filter-dd .ft-dd-toggle:hover{background:#f0f5ff}'+
          '.ft-filter-dd .ft-dd-submenu{position:fixed;z-index:100000;background:#fff;border:1px solid #bbb;border-radius:3px;box-shadow:0 4px 12px rgba(0,0,0,.2);min-width:180px;padding:4px 0;font-size:11px}'+
          '.ft-filter-dd .ft-dd-submenu .ft-sm-row{padding:4px 10px;cursor:pointer;color:#333}.ft-filter-dd .ft-dd-submenu .ft-sm-row:hover{background:#e8f0fe}'+
          '.ft-filter-dd .ft-dd-selall{padding:3px 7px;border-bottom:1px solid #e0e0e0;font-size:11px;color:#444}'+
          '.ft-filter-dd .ft-dd-selall label{cursor:pointer;margin:0;display:flex;align-items:center;gap:4px}'+
          '.ft-filter-dd .ft-dd-list{max-height:180px;overflow-y:auto;padding:1px 0}'+
          '.ft-filter-dd .ft-dd-list label{display:flex;align-items:center;gap:5px;padding:2px 7px;cursor:pointer;white-space:nowrap;margin:0;font-weight:normal}'+
          '.ft-filter-dd .ft-dd-list label:hover{background:#e8f0fe}'+
          '.ft-filter-dd .ft-dd-list input[type=checkbox]{margin:0;accent-color:#0d6efd}'+
          '.ft-filter-dd .ft-dd-foot{border-top:1px solid #e0e0e0;padding:5px 7px;display:flex;gap:6px;justify-content:flex-end}'+
          '.ft-filter-dd .ft-dd-foot button{font-size:11px;padding:2px 14px;border-radius:2px;cursor:pointer;border:1px solid #bbb;background:#fff}'+
          '.ft-filter-dd .ft-dd-foot button.ft-ok{background:#0d6efd;color:#fff;border-color:#0d6efd}.ft-filter-dd .ft-dd-foot button.ft-ok:hover{background:#0b5ed7}'+
          '.ft-filter-dd .ft-dd-foot button.ft-cancel:hover{background:#eee}'+
          '.ft-filter-dd .ft-dd-list::-webkit-scrollbar{width:6px}.ft-filter-dd .ft-dd-list::-webkit-scrollbar-thumb{background:#bbb;border-radius:3px}'+
          '.ft-af-overlay{position:fixed;inset:0;z-index:100001;background:rgba(0,0,0,.3);display:flex;align-items:center;justify-content:center}'+
          '.ft-af-dlg{background:#fff;border:1px solid #999;border-radius:4px;box-shadow:0 8px 32px rgba(0,0,0,.3);width:420px;max-width:95vw;font-size:12px;color:#222}'+
          '.ft-af-hdr{padding:8px 12px;background:#f0f0f0;border-bottom:1px solid #ccc;display:flex;justify-content:space-between;align-items:center;font-weight:600;font-size:13px}'+
          '.ft-af-close{cursor:pointer;font-size:18px;line-height:1;color:#666;padding:0 4px}.ft-af-close:hover{color:#000}'+
          '.ft-af-body{padding:12px 14px}'+
          '.ft-af-label{font-size:12px;color:#555;margin-bottom:2px}.ft-af-label.fw-bold{color:#222}'+
          '.ft-af-sel{padding:4px 6px;font-size:11px;border:1px solid #bbb;border-radius:2px;min-width:140px;outline:none}.ft-af-sel:focus{border-color:#86b7fe}'+
          '.ft-af-inp{padding:4px 6px;font-size:11px;border:1px solid #bbb;border-radius:2px;flex:1;outline:none;min-width:0}.ft-af-inp:focus{border-color:#86b7fe;box-shadow:0 0 0 2px rgba(13,110,253,.12)}'+
          '.ft-af-foot{padding:8px 14px;border-top:1px solid #ccc;display:flex;gap:8px;justify-content:flex-end}'+
          '.ft-af-ok{padding:5px 24px;font-size:12px;border:1px solid #0d6efd;background:#0d6efd;color:#fff;border-radius:3px;cursor:pointer}.ft-af-ok:hover{background:#0b5ed7}'+
          '.ft-af-cancel{padding:5px 18px;font-size:12px;border:1px solid #bbb;background:#fff;border-radius:3px;cursor:pointer}.ft-af-cancel:hover{background:#eee}';
          document.head.appendChild(s);
        }

        function _findPaginationHostForTable(tableEl){
          var n=tableEl;
          while(n&&n!==document.body){
            if(n.querySelector&&n.querySelector('.pagination')) return n;
            n=n.parentElement;
          }
          return null;
        }
        function _isPaginatedView(){return !!_findPaginationHostForTable(tbl)}
        function _useClientPaging(){return _isPaginatedView() && String(tbl.getAttribute('data-ft-no-client-paging')||'0')!=='1'}
        function _getPerPage(){
          try{
            var q=new URLSearchParams(window.location.search),v=parseInt(q.get('per_page')||'0',10);
            if(v>0)return v;
          }catch(_e){}
          try{
            var host=_findPaginationHostForTable(tbl)||document;
            var selectors=[
              'select[name="per_page"]',
              'select[id*="PerPage"]',
              'select[id*="perPage"]',
              'select[onchange*="per_page"]'
            ];
            for(var i=0;i<selectors.length;i++){
              var sel=host.querySelector(selectors[i]);
              if(!sel) continue;
              var sv=parseInt(sel.value||'0',10);
              if(sv>0) return sv;
            }
          }catch(_e2){}
          // Last safe fallback: current page row count (at least 10)
          return Math.max(10,getRows().length||0);
        }
        function _getPagerUl(){
          var host=_findPaginationHostForTable(tbl); if(!host) return null;
          return host.querySelector('.pagination');
        }
        function _bindPagerClicks(ul){
          if(!ul)return;
          ul.querySelectorAll('a.page-link[data-ft-page]').forEach(function(a){
            a.addEventListener('click',function(e){
              e.preventDefault();
              var p=parseInt(a.getAttribute('data-ft-page')||'1',10)||1;
              _clientPage=p;
              applyFilters();
            });
          });
        }
        function _renderClientPager(filteredCount){
          var ul=_getPagerUl(); if(!ul) return;
          if(!ul.dataset.ftOriginalHtml) ul.dataset.ftOriginalHtml=ul.innerHTML;
          if(!_hasAnyFilters()){
            ul.innerHTML=ul.dataset.ftOriginalHtml||ul.innerHTML;
            return;
          }
          var perPage=Math.max(1,_getPerPage());
          var pages=Math.max(1,Math.ceil(filteredCount/perPage));
          if(_clientPage>pages)_clientPage=pages;
          if(_clientPage<1)_clientPage=1;
          var h='';
          var prevDis=_clientPage<=1?' disabled':'';
          h+='<li class="page-item'+prevDis+'"><a class="page-link" href="#" data-ft-page="'+(_clientPage-1)+'"><i class="bi bi-chevron-left"></i></a></li>';
          var start=Math.max(1,_clientPage-2),end=Math.min(pages,_clientPage+2);
          if(start>1){h+='<li class="page-item"><a class="page-link" href="#" data-ft-page="1">1</a></li>';if(start>2)h+='<li class="page-item disabled"><span class="page-link">…</span></li>';}
          for(var p=start;p<=end;p++){
            h+='<li class="page-item'+(p===_clientPage?' active':'')+'"><a class="page-link" href="#" data-ft-page="'+p+'">'+p+'</a></li>';
          }
          if(end<pages){if(end<pages-1)h+='<li class="page-item disabled"><span class="page-link">…</span></li>';h+='<li class="page-item"><a class="page-link" href="#" data-ft-page="'+pages+'">'+pages+'</a></li>';}
          var nextDis=_clientPage>=pages?' disabled':'';
          h+='<li class="page-item'+nextDis+'"><a class="page-link" href="#" data-ft-page="'+(_clientPage+1)+'"><i class="bi bi-chevron-right"></i></a></li>';
          ul.innerHTML=h;
          _bindPagerClicks(ul);
        }
        function _extractPageCount(doc){
          var rt=doc.getElementById(tableId);
          if(!rt)return 1;
          var host=(function(tableEl){
            var n=tableEl;
            while(n&&n!==doc.body){
              if(n.querySelector&&n.querySelector('.pagination')) return n;
              n=n.parentElement;
            }
            return null;
          })(rt);
          if(!host)return 1;
          var links=Array.from(host.querySelectorAll('.pagination .page-link'));
          var max=1;
          links.forEach(function(a){
            var n=parseInt((a.textContent||'').trim(),10);
            if(!isNaN(n)&&n>max)max=n;
          });
          return max;
        }
        function _runAllRowsCallbacks(){while(_allRowsCallbacks.length){try{(_allRowsCallbacks.shift())()}catch(_e){}}}
        function _objHas(o){for(var k in o){if(Object.prototype.hasOwnProperty.call(o,k))return true;}return false}
        function _hasAnyFilters(){return _objHas(_filters)||_objHas(_numFilters)||_objHas(_txtFilters)||_objHas(_customFilters)}
        function _restorePageRows(){if(_usingAllRows){tbody.innerHTML=_initialPageHtml;_usingAllRows=false}}
        function _switchToAllRows(){if(!_usingAllRows&&_allRowsHtml){tbody.innerHTML=_allRowsHtml;_usingAllRows=true}}
        function _rowsFromHtml(html){if(!html)return[];var t=document.createElement('tbody');t.innerHTML=html;return Array.from(t.querySelectorAll('tr')).filter(function(r){return r.cells.length>1})}
        function _fleetFetchPageHtml(url) {
            return fetch(url, {credentials:'same-origin', redirect:'manual', cache:'no-store'}).then(function(r) {
                if (!r || r.type === 'opaqueredirect' || r.status === 0 || (r.status >= 300 && r.status < 400) || !r.ok) {
                    return '';
                }
                return r.text();
            }).catch(function() { return ''; });
        }

        function _ensureAllRowsLoaded(cb){
          if(cb)_allRowsCallbacks.push(cb);
          if(_allRowsLoaded||!_isPaginatedView()){_allRowsLoaded=true;_runAllRowsCallbacks();return}
          if(_allRowsLoading)return;
          _allRowsLoading=true;
          try{
            var u=new URL(window.location.href),parts=[];
            u.searchParams.set('page','1');
            _fleetFetchPageHtml(u.toString()).then(function(html){
              if(html){
                var doc=new DOMParser().parseFromString(html,'text/html');
                var rt=doc.getElementById(tableId),rb=rt?rt.querySelector('tbody'):null;
                if(rb) parts.push(rb.innerHTML||'');
                var pages=_extractPageCount(doc);
                if(pages<=1) return;
                var jobs=[];
                for(var p=2;p<=pages;p++){
                  var up=new URL(u.toString());up.searchParams.set('page',String(p));
                  jobs.push(_fleetFetchPageHtml(up.toString()).then(function(h){
                    if(!h) return;
                    var d=new DOMParser().parseFromString(h,'text/html');
                    var t=d.getElementById(tableId),b=t?t.querySelector('tbody'):null;
                    if(b) parts.push(b.innerHTML||'');
                  }));
                }
                return Promise.all(jobs);
              }
            }).catch(function(){}).finally(function(){
              _allRowsHtml=parts.join('');
              _allRowsLoading=false;_allRowsLoaded=true;_runAllRowsCallbacks();
              if(typeof window._fleetAfterFilter==='function')window._fleetAfterFilter();
              try{ window.dispatchEvent(new CustomEvent('fleet:after-filter')); }catch(_e){}
            });
          }catch(_e){
            _allRowsLoading=false;_allRowsLoaded=true;_runAllRowsCallbacks();
          }
        }
        function getRows(){return Array.from(tbody.querySelectorAll('tr')).filter(function(r){return r.cells.length>1})}
        function getCellVal(r,ci){var c=r.cells[ci];return c?(c.textContent||'').trim():''}
        function _ensureRowSeq(rowsIn){
          (rowsIn||getRows()).forEach(function(r,idx){
            if(!r.dataset.ftRowSeq){r.dataset.ftRowSeq=String(idx)}
          })
        }
        function dateVal(s){
          var t=(s||'').trim();
          if(!t||t==='-')return null;
          var m=t.match(/^(\d{2})[-\/](\d{2})[-\/](\d{4})$/);
          if(m){
            var d=parseInt(m[1],10),mo=parseInt(m[2],10),y=parseInt(m[3],10);
            var dt=new Date(y,mo-1,d);
            if(dt&&dt.getFullYear()===y&&dt.getMonth()===(mo-1)&&dt.getDate()===d)return dt.getTime();
          }
          var m2=t.match(/^(\d{4})[-\/](\d{2})[-\/](\d{2})$/);
          if(m2){
            var y2=parseInt(m2[1],10),mo2=parseInt(m2[2],10),d2=parseInt(m2[3],10);
            var dt2=new Date(y2,mo2-1,d2);
            if(dt2&&dt2.getFullYear()===y2&&dt2.getMonth()===(mo2-1)&&dt2.getDate()===d2)return dt2.getTime();
          }
          return null;
        }
        function numVal(s){return parseFloat((s||'').replace(/[,%]/g,''))}
        function _colIsNumeric(ci,rowsIn){var rows=rowsIn||getRows(),nums=0,tot=0;rows.forEach(function(r){var v=getCellVal(r,ci);if(v===''||v==='-')return;tot++;if(!isNaN(numVal(v)))nums++});return tot>0&&nums/tot>=0.6}

        ths.forEach(function(th,ci){
          if(th.classList.contains('no-ft-filter')) return;
          var colIdx = th.hasAttribute('data-ft-col') ? parseInt(th.getAttribute('data-ft-col'), 10) : ci;
          th.classList.add('ft-sort');
          var wrap=document.createElement('span');wrap.className='ft-filter-wrap';
          var fbtn=document.createElement('i');fbtn.className='bi bi-funnel-fill ft-filter-btn';fbtn.title='Filter';
          wrap.appendChild(fbtn);th.appendChild(wrap);
          var _openSub=null;

          th.addEventListener('click',function(e){
            if(e.target.closest('.ft-filter-wrap'))return;
            if(_sortCol===colIdx){_sortAsc=!_sortAsc}else{_sortCol=colIdx;_sortAsc=true}
            ths.forEach(function(h){h.classList.remove('asc','desc')});th.classList.add(_sortAsc?'asc':'desc');
            var rows=getRows();_ensureRowSeq(rows);rows.sort(function(a,b){
              var va=getCellVal(a,colIdx),vb=getCellVal(b,colIdx),da=dateVal(va),db=dateVal(vb),cmp=0;
              if(da!==null&&db!==null){cmp=_sortAsc?da-db:db-da}
              else{
                var na=numVal(va),nb=numVal(vb);
                if(!isNaN(na)&&!isNaN(nb))cmp=_sortAsc?na-nb:nb-na;
                else cmp=_sortAsc?va.localeCompare(vb):vb.localeCompare(va);
              }
              if(cmp!==0)return cmp;
              var sa=parseInt(a.dataset.ftRowSeq||'0',10),sb=parseInt(b.dataset.ftRowSeq||'0',10);
              return sa-sb;
            });
            rows.forEach(function(r){tbody.appendChild(r)});
            if(_hasAnyFilters())applyFilters();
          });

          fbtn.addEventListener('click',function(e){
            e.stopPropagation();_closeAllDd();
            if(!_allRowsLoaded&&_isPaginatedView()){
              _ensureAllRowsLoaded(function(){setTimeout(function(){fbtn.click();},0)});
              return;
            }
            var dd=document.createElement('div');dd.className='ft-filter-dd';
            dd.addEventListener('wheel',function(ev){ev.stopPropagation()});
            document.body.appendChild(dd);_openDd=dd;_openDdBtn=fbtn;

            var vals={},rows=_allRowsHtml?_rowsFromHtml(_allRowsHtml):getRows();
            rows.forEach(function(r){var v=getCellVal(r,colIdx);vals[v]=true});
            var sorted=Object.keys(vals).sort(function(a,b){var na=numVal(a),nb=numVal(b);if(!isNaN(na)&&!isNaN(nb))return na-nb;return a.localeCompare(b)});
            var activeSet=_filters[colIdx]||null,isNumCol=_colIsNumeric(colIdx,rows);
            var colName=(th.childNodes[0]?th.childNodes[0].textContent.trim():'');

            var headerDiv=document.createElement('div');headerDiv.className='ft-dd-header';
            var headerTitle=document.createElement('span');headerTitle.textContent='Filter: '+colName;headerDiv.appendChild(headerTitle);
            var hasFilter=!!_filters[colIdx]||!!_numFilters[colIdx]||!!_txtFilters[colIdx]||!!_customFilters[colIdx];
            if(hasFilter){var clr=document.createElement('span');clr.className='ft-dd-clear';clr.textContent='Clear Filter';clr.addEventListener('click',function(ev){ev.stopPropagation();delete _filters[colIdx];delete _numFilters[colIdx];delete _txtFilters[colIdx];delete _customFilters[colIdx];fbtn.classList.remove('active');applyFilters();dd.remove()});headerDiv.appendChild(clr)}
            dd.appendChild(headerDiv);

            var searchDiv=document.createElement('div');searchDiv.className='ft-dd-search';
            var searchInp=document.createElement('input');searchInp.type='text';searchInp.placeholder='Search...';
            searchDiv.appendChild(searchInp);dd.appendChild(searchDiv);

            // --- Number Filters OR Text Filters toggle ---
            var toggleDiv=document.createElement('div');toggleDiv.className='ft-dd-toggle';
            toggleDiv.innerHTML=isNumCol?'<i class="bi bi-123"></i> Number Filters <i class="bi bi-chevron-right" style="margin-left:auto;font-size:8px"></i>':
              '<i class="bi bi-fonts"></i> Text Filters <i class="bi bi-chevron-right" style="margin-left:auto;font-size:8px"></i>';
            dd.appendChild(toggleDiv);

            toggleDiv.addEventListener('click',function(ev){
              ev.stopPropagation();
              if(_openSub){_openSub.remove();_openSub=null;return}
              var sub=document.createElement('div');sub.className='ft-dd-submenu';_openSub=sub;
              var items=isNumCol?[{k:'eq',l:'Equals...'},{k:'neq',l:'Does Not Equal...'},{k:'gt',l:'Greater Than...'},{k:'gte',l:'Greater Than Or Equal To...'},{k:'lt',l:'Less Than...'},{k:'lte',l:'Less Than Or Equal To...'},{k:'between',l:'Between...'},{k:'top10',l:'Top 10...'},{k:'above',l:'Above Average'},{k:'below',l:'Below Average'},{k:'custom',l:'Custom Filter...'}]:
                [{k:'eq',l:'Equals...'},{k:'neq',l:'Does Not Equal...'},{k:'begins',l:'Begins With...'},{k:'ends',l:'Ends With...'},{k:'contains',l:'Contains...'},{k:'ncontains',l:'Does Not Contain...'},{k:'custom',l:'Custom Filter...'}];
              items.forEach(function(it){
                var row=document.createElement('div');row.className='ft-sm-row';row.textContent=it.l;
                row.addEventListener('click',function(ev2){
                  ev2.stopPropagation();sub.remove();_openSub=null;
                  if(it.k==='custom'){
                    _openAutoFilterDlg(colName,isNumCol,_customFilters[colIdx],function(result){
                      if(result){_customFilters[colIdx]=result}else{delete _customFilters[colIdx]}
                      fbtn.classList.toggle('active',!!_filters[colIdx]||!!_numFilters[colIdx]||!!_txtFilters[colIdx]||!!_customFilters[colIdx]);
                      applyFilters();
                    });dd.remove();_openDd=null;_openDdBtn=null;
                  } else if(it.k==='above'||it.k==='below'){
                    var allNums=[];rows.forEach(function(r){var n=numVal(getCellVal(r,colIdx));if(!isNaN(n))allNums.push(n)});
                    var avg=allNums.length?allNums.reduce(function(a,b){return a+b},0)/allNums.length:0;
                    _numFilters[colIdx]={type:it.k,val1:avg};fbtn.classList.add('active');applyFilters();dd.remove();_openDd=null;_openDdBtn=null;
                  } else if(it.k==='top10'){
                    var n=prompt('Show Top N rows:','10');if(n&&!isNaN(parseInt(n))){_numFilters[colIdx]={type:'top10',val1:parseInt(n)};fbtn.classList.add('active');applyFilters()}
                    dd.remove();_openDd=null;_openDdBtn=null;
                  } else if(it.k==='between'){
                    _openAutoFilterDlg(colName,true,{op1:'gte',val1:'',op2:'lte',val2:'',mode:'and'},function(result){
                      if(result){_customFilters[colIdx]=result}else{delete _customFilters[colIdx]}
                      fbtn.classList.toggle('active',!!_filters[colIdx]||!!_numFilters[colIdx]||!!_txtFilters[colIdx]||!!_customFilters[colIdx]);applyFilters();
                    });dd.remove();_openDd=null;_openDdBtn=null;
                  } else {
                    _openAutoFilterDlg(colName,isNumCol,{op1:it.k,val1:'',mode:'and'},function(result){
                      if(result){_customFilters[colIdx]=result}else{delete _customFilters[colIdx]}
                      fbtn.classList.toggle('active',!!_filters[colIdx]||!!_numFilters[colIdx]||!!_txtFilters[colIdx]||!!_customFilters[colIdx]);applyFilters();
                    });dd.remove();_openDd=null;_openDdBtn=null;
                  }
                });sub.appendChild(row);
              });
              dd.appendChild(sub);
              _posSubmenu(toggleDiv,sub);
            });

            // --- Select All + value list ---
            var selAllDiv=document.createElement('div');selAllDiv.className='ft-dd-selall';
            var selAllLbl=document.createElement('label');var selAllCb=document.createElement('input');selAllCb.type='checkbox';selAllCb.checked=!activeSet;
            selAllLbl.appendChild(selAllCb);selAllLbl.appendChild(document.createTextNode(' (Select All)'));selAllDiv.appendChild(selAllLbl);dd.appendChild(selAllDiv);
            var listDiv=document.createElement('div');listDiv.className='ft-dd-list';dd.appendChild(listDiv);
            function buildItems(ft){listDiv.innerHTML='';var f=(ft||'').toLowerCase();sorted.forEach(function(v){if(f&&(v||'').toLowerCase().indexOf(f)===-1)return;var lbl=document.createElement('label');var cb=document.createElement('input');cb.type='checkbox';cb.value=v;cb.checked=!activeSet||activeSet.has(v);lbl.appendChild(cb);lbl.appendChild(document.createTextNode(v||'(Blanks)'));listDiv.appendChild(lbl)})}
            buildItems('');searchInp.addEventListener('input',function(){buildItems(this.value)});
            selAllCb.addEventListener('change',function(){listDiv.querySelectorAll('input[type=checkbox]').forEach(function(c){c.checked=this.checked}.bind(this))});

            var footDiv=document.createElement('div');footDiv.className='ft-dd-foot';
            var btnOk=document.createElement('button');btnOk.className='ft-ok';btnOk.textContent='OK';
            var btnCancel=document.createElement('button');btnCancel.className='ft-cancel';btnCancel.textContent='Cancel';
            footDiv.appendChild(btnOk);footDiv.appendChild(btnCancel);dd.appendChild(footDiv);

            btnCancel.addEventListener('click',function(ev){ev.stopPropagation();dd.remove();_openDd=null;_openDdBtn=null});
            btnOk.addEventListener('click',function(ev){
              ev.stopPropagation();
              var sel=new Set();listDiv.querySelectorAll('input[type=checkbox]:checked').forEach(function(c){sel.add(c.value)});
              if(sel.size===sorted.length||sel.size===0){delete _filters[colIdx]}else{_filters[colIdx]=sel}
              fbtn.classList.toggle('active',!!_filters[colIdx]||!!_numFilters[colIdx]||!!_txtFilters[colIdx]||!!_customFilters[colIdx]);
              applyFilters();dd.remove();_openDd=null;_openDdBtn=null;
            });

            var rect=fbtn.getBoundingClientRect();dd.style.visibility='hidden';dd.style.display='block';
            var ddW=dd.offsetWidth,ddH=dd.offsetHeight,posLeft=rect.left,posTop=rect.bottom+2;
            if(posLeft+ddW>innerWidth-8)posLeft=rect.right-ddW;if(posLeft<4)posLeft=4;
            if(posTop+ddH>innerHeight-8)posTop=rect.top-ddH-2;if(posTop<4)posTop=4;
            dd.style.left=posLeft+'px';dd.style.top=posTop+'px';dd.style.visibility='';
            setTimeout(function(){searchInp.focus()},30);
          });
        });

        function _matchCustom(op,cellVal,filterVal,isNum){
          if(isNum){var n=numVal(cellVal),v=parseFloat(filterVal);if(isNaN(n)||isNaN(v))return false;
            if(op==='eq')return n===v;if(op==='neq')return n!==v;if(op==='gt')return n>v;if(op==='gte')return n>=v;if(op==='lt')return n<v;if(op==='lte')return n<=v;return true;
          }
          var cv=(cellVal||'').toLowerCase(),fv=(filterVal||'').toLowerCase();
          if(op==='eq')return cv===fv;if(op==='neq')return cv!==fv;
          if(op==='contains')return cv.indexOf(fv)!==-1;if(op==='ncontains')return cv.indexOf(fv)===-1;
          if(op==='begins')return cv.indexOf(fv)===0;if(op==='ends')return cv.length>=fv.length&&cv.substring(cv.length-fv.length)===fv;
          if(fv.indexOf('*')!==-1||fv.indexOf('?')!==-1){var re=new RegExp('^'+fv.replace(/[.+^${}()|[\]\\]/g,'\\$&').replace(/\*/g,'.*').replace(/\?/g,'.')+'$','i');return re.test(cv)}
          return cv===fv;
        }

        function _customFilterPass(ci,cellVal){
          var cf=_customFilters[ci];if(!cf)return true;
          var p1=cf.val1?_matchCustom(cf.op1,cellVal,cf.val1,cf.isNum):true;
          var p2=cf.val2?_matchCustom(cf.op2,cellVal,cf.val2,cf.isNum):true;
          return cf.mode==='or'?(p1||p2):(p1&&p2);
        }

        function _numFilterPass(ci,cellVal){
          var nf=_numFilters[ci];if(!nf)return true;var n=numVal(cellVal);if(isNaN(n))return false;
          switch(nf.type){case 'eq':return n===nf.val1;case 'neq':return n!==nf.val1;case 'gt':return n>nf.val1;case 'gte':return n>=nf.val1;case 'lt':return n<nf.val1;case 'lte':return n<=nf.val1;case 'between':return n>=nf.val1&&n<=nf.val2;case 'above':return n>nf.val1;case 'below':return n<nf.val1;default:return true}
        }

        function applyFilters(){
          if(!_hasAnyFilters()){
            _restorePageRows();
            // Non-paginated tables keep current tbody; make sure previously hidden rows are visible again.
            if(!_usingAllRows){getRows().forEach(function(r){r.style.display='';r.setAttribute('data-ft-match','1');})}
            _clientPage=1;
            if(_useClientPaging())_renderClientPager(getRows().length);
            if(typeof window._fleetAfterFilter==='function')window._fleetAfterFilter();
            try{ window.dispatchEvent(new CustomEvent('fleet:after-filter')); }catch(_e){}
            return
          }
          if(_allRowsHtml)_switchToAllRows();
          var rows=getRows(),top10Sets={};
          var matchedRows=[];
          for(var ci in _numFilters){if(_numFilters[ci].type==='top10'){var n=_numFilters[ci].val1||10,pairs=[];rows.forEach(function(r,i){var v=numVal(getCellVal(r,parseInt(ci)));if(!isNaN(v))pairs.push({idx:i,val:v})});pairs.sort(function(a,b){return b.val-a.val});var s=new Set();pairs.slice(0,n).forEach(function(p){s.add(p.idx)});top10Sets[ci]=s}}
          rows.forEach(function(r,ri){
            var show=true;
            for(var ci in _filters){if(!_filters[ci].has(getCellVal(r,parseInt(ci)))){show=false;break}}
            if(show){for(var ci in _numFilters){var nf=_numFilters[ci];if(nf.type==='top10'){if(!top10Sets[ci]||!top10Sets[ci].has(ri)){show=false;break}}else{if(!_numFilterPass(parseInt(ci),getCellVal(r,parseInt(ci)))){show=false;break}}}}
            if(show){for(var ci in _customFilters){if(!_customFilterPass(parseInt(ci),getCellVal(r,parseInt(ci)))){show=false;break}}}
            r.setAttribute('data-ft-match',show?'1':'0');
            if(show) matchedRows.push(r);
            r.style.display='none';
          });
          var totalMatched=matchedRows.length;
          if(_useClientPaging()){
            var perPage=Math.max(1,_getPerPage());
            var totalPages=Math.max(1,Math.ceil(totalMatched/perPage));
            if(_clientPage>totalPages)_clientPage=totalPages;
            if(_clientPage<1)_clientPage=1;
            var start=(_clientPage-1)*perPage,end=start+perPage;
            matchedRows.slice(start,end).forEach(function(r){r.style.display='';});
            _renderClientPager(totalMatched);
          }else{
            matchedRows.forEach(function(r){r.style.display='';});
          }
          if(typeof window._fleetAfterFilter==='function')window._fleetAfterFilter();
          try{ window.dispatchEvent(new CustomEvent('fleet:after-filter')); }catch(_e){}
        }
        document.addEventListener('click',function(e){if(!e.target.closest('.ft-filter-dd')&&!e.target.closest('.ft-filter-btn')&&!e.target.closest('.ft-af-overlay'))_closeAllDd()});
      };

      window.fleetEnhanceAllListTables=function(root){
        var scope=root&&root.querySelectorAll?root:document;
        var seq=0;
        scope.querySelectorAll('table').forEach(function(tbl){
          if(tbl.classList.contains('no-fleet-filter')||tbl.getAttribute('data-ft-ignore')==='1')return;
          if(tbl.dataset&&tbl.dataset.ftEnhanced==='1')return;
          var thead=tbl.querySelector('thead'),tbody=tbl.querySelector('tbody');
          if(!thead||!tbody)return;
          if(thead.querySelectorAll('th').length<2)return;
          // Skip only truly editable grids, not list tables that contain hidden inputs (e.g. CSRF in row forms).
          if(tbody.querySelector('input:not([type="hidden"]),select,textarea,[contenteditable="true"]'))return;
          if(!tbl.id){seq+=1;tbl.id='ft_auto_tbl_'+seq;}
          window.fleetTableEnhance(tbl.id);
        });
      };

      if(document.readyState==='loading'){
        document.addEventListener('DOMContentLoaded',function(){window.fleetEnhanceAllListTables(document)});
      }else{
        window.fleetEnhanceAllListTables(document);
      }

      function _parseNum(v){
        var s=String(v==null?'':v).replace(/[,%\s]/g,'').replace(/[^\d.\-]/g,'');
        var n=parseFloat(s);
        return isNaN(n)?0:n;
      }
      function _fmtNum(n){
        var x=(isNaN(n)||!isFinite(n))?0:n;
        try{return x.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
        catch(_e){return (Math.round(x*100)/100).toFixed(2);}
      }
      function _sumVisibleCol(rows,colIdx){
        var t=0;
        rows.forEach(function(r){
          var c=r.cells[colIdx];
          if(!c)return;
          t+=_parseNum(c.textContent||c.innerText||'');
        });
        return t;
      }
      window.fleetRefreshAutoTotals=function(root){
        var scope=(root&&root.querySelectorAll)?root:document;
        scope.querySelectorAll('table[data-ft-auto-totals="1"]').forEach(function(tbl){
          var tbody=tbl.querySelector('tbody'); if(!tbody) return;
          var allRows=Array.from(tbody.querySelectorAll('tr')).filter(function(r){return r.cells&&r.cells.length>1;});
          var visibleRows=allRows.filter(function(r){return r.style.display!=='none';});
          var matchedRows=allRows.filter(function(r){return r.getAttribute('data-ft-match')==='1';});
          var hasActiveFilter=!!tbl.querySelector('.ft-filter-btn.active');
          var totalRecords=parseInt(tbl.getAttribute('data-ft-total-records')||'0',10)||0;
          var allRowsLoaded=totalRecords>0?allRows.length>=totalRecords:false;

          tbl.querySelectorAll('[data-ft-visible-col]').forEach(function(cell){
            var ci=parseInt(cell.getAttribute('data-ft-visible-col')||'-1',10);
            if(ci<0)return;
            cell.textContent=_fmtNum(_sumVisibleCol(visibleRows,ci));
          });
          tbl.querySelectorAll('[data-ft-total-col]').forEach(function(cell){
            var ci=parseInt(cell.getAttribute('data-ft-total-col')||'-1',10);
            if(ci<0)return;
            if(allRowsLoaded&&hasActiveFilter){
              cell.textContent=_fmtNum(_sumVisibleCol((matchedRows.length?matchedRows:visibleRows),ci));
            }else{
              var base=_parseNum(cell.getAttribute('data-ft-base')||'0');
              cell.textContent=_fmtNum(base);
            }
          });
        });
      };
      window.fleetRefreshRecordMeta=function(root){
        var scope=(root&&root.querySelectorAll)?root:document;
        function _findMetaHost(tableEl){
          var n=tableEl;
          while(n&&n!==document.body){
            if(
              (n.querySelector&&n.querySelector('.pagination')) ||
              (n.querySelector&&n.querySelector('.table-footer')) ||
              (n.classList&&n.classList.contains('card'))
            ){
              return n;
            }
            n=n.parentElement;
          }
          return tableEl.parentElement;
        }
        function _findCounterEl(host){
          if(!host||!host.querySelectorAll) return null;
          var candidates=Array.from(host.querySelectorAll('.table-footer small.text-muted, .card-footer small.text-muted, .table-footer .text-muted, .card-footer .text-muted'));
          if(!candidates.length) return null;
          var withShowing=candidates.find(function(el){return /showing/i.test((el.textContent||''));});
          return withShowing||candidates[0];
        }
        scope.querySelectorAll('table').forEach(function(tbl){
          if(!(tbl.dataset&&tbl.dataset.ftEnhanced==='1')) return;
          var tbody=tbl.querySelector('tbody'); if(!tbody) return;
          var allRows=Array.from(tbody.querySelectorAll('tr')).filter(function(r){return r.cells&&r.cells.length>1;});
          var visibleRows=allRows.filter(function(r){return r.style.display!=='none';});
          var matchedRows=allRows.filter(function(r){return r.getAttribute('data-ft-match')==='1';});
          var hasActiveFilter=!!tbl.querySelector('.ft-filter-btn.active');
          var isFiltered=hasActiveFilter || (matchedRows.length>0 && matchedRows.length!==allRows.length);
          var host=_findMetaHost(tbl); if(!host) return;
          var counter=_findCounterEl(host);
          var totalRecords=parseInt(tbl.getAttribute('data-ft-total-records')||'0',10)||allRows.length;

          if(counter){
            if(!counter.dataset.ftOriginalHtml) counter.dataset.ftOriginalHtml=counter.innerHTML;
            if(isFiltered){
              var shownPage=visibleRows.length;
              var shownAll=matchedRows.length;
              var start=(shownPage>0)?(matchedRows.indexOf(visibleRows[0])+1):0;
              var end=(shownPage>0)?(start+shownPage-1):0;
              counter.innerHTML='<i class="bi bi-list-ul me-1"></i>Showing '+start+' to '+end+' of '+shownAll+' entries (filtered from '+totalRecords+')';
            }else if(counter.dataset.ftOriginalHtml){
              counter.innerHTML=counter.dataset.ftOriginalHtml;
            }
          }
        });
      };
      function _csvEscape(v){
        var s=String(v==null?'':v).replace(/\r?\n/g,' ').trim();
        if(/[",]/.test(s)) return '"'+s.replace(/"/g,'""')+'"';
        return s;
      }
      function _tableToCsv(tbl){
        var lines=[];
        var headers=Array.from(tbl.querySelectorAll('thead th')).map(function(th){
          var h=th.cloneNode(true);
          h.querySelectorAll('.ft-filter-wrap').forEach(function(n){n.remove();});
          return _csvEscape(h.textContent||'');
        });
        if(headers.length) lines.push(headers.join(','));
        var rows=Array.from(tbl.querySelectorAll('tbody tr')).filter(function(r){
          if(!(r.cells&&r.cells.length>0))return false;
          var m=r.getAttribute('data-ft-match');
          if(m==='1')return true;
          return r.style.display!=='none';
        });
        rows.forEach(function(r){
          var row=Array.from(r.cells).map(function(c){return _csvEscape(c.textContent||'');});
          lines.push(row.join(','));
        });
        var footRows=Array.from(tbl.querySelectorAll('tfoot tr')).filter(function(r){return r.cells&&r.cells.length>0;});
        if(footRows.length){
          lines.push('');
          footRows.forEach(function(r){
            var row=Array.from(r.cells).map(function(c){return _csvEscape(c.textContent||'');});
            lines.push(row.join(','));
          });
        }
        return lines.join('\n');
      }
      function _openFilteredPrint(tbl){
        var headerHtml='<h3 style="margin:0 0 10px 0;font-family:Arial,sans-serif;">'+(document.title||'Filtered Preview')+'</h3>';
        var t=tbl.cloneNode(true);
        var tb=t.querySelector('tbody');
        if(tb){
          var vis=Array.from(tbl.querySelectorAll('tbody tr')).filter(function(r){
            var m=r.getAttribute('data-ft-match');
            if(m==='1')return true;
            return r.style.display!=='none';
          });
          tb.innerHTML='';
          vis.forEach(function(r){tb.appendChild(r.cloneNode(true));});
        }
        var w=window.open('','_blank');
        if(!w) return;
        w.document.open();
        w.document.write('<!doctype html><html><head><meta charset="utf-8"><title>Print Preview</title>'+
          '<style>body{font-family:Arial,sans-serif;padding:14px}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #999;padding:6px}thead th{background:#f3f3f3}tfoot td{font-weight:700;background:#fafafa}</style>'+
          '</head><body>'+headerHtml+t.outerHTML+'</body></html>');
        w.document.close();
        w.focus();
        w.print();
      }
      function _getFirstFilteredEnhancedTable(){
        var tables=Array.from(document.querySelectorAll('table')).filter(function(tbl){
          return tbl.dataset&&tbl.dataset.ftEnhanced==='1'&&!!tbl.querySelector('.ft-filter-btn.active');
        });
        return tables.length?tables[0]:null;
      }
      document.addEventListener('click',function(e){
        var a=e.target.closest('a[href]');
        if(!a) return;
        var href=(a.getAttribute('href')||'').toLowerCase();
        var title=((a.getAttribute('title')||'')+' '+(a.textContent||'')).toLowerCase();
        var isPrint=href.indexOf('_print')!==-1 || title.indexOf('print')!==-1 || title.indexOf('preview')!==-1;
        var isExport=href.indexOf('_export')!==-1 || title.indexOf('export')!==-1;
        if(!isPrint && !isExport) return;
        var tbl=_getFirstFilteredEnhancedTable();
        if(!tbl) return;
        if(isPrint){
          e.preventDefault();
          _openFilteredPrint(tbl);
          return;
        }
        if(isExport){
          e.preventDefault();
          var csv=_tableToCsv(tbl);
          var blob=new Blob([csv],{type:'text/csv;charset=utf-8;'});
          var url=URL.createObjectURL(blob);
          var dl=document.createElement('a');
          var d=new Date();
          var fname='filtered_export_'+d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')+'.csv';
          dl.href=url; dl.download=fname; document.body.appendChild(dl); dl.click(); dl.remove();
          setTimeout(function(){URL.revokeObjectURL(url);},1000);
        }
      },true);
      window.addEventListener('fleet:after-filter',function(){window.fleetRefreshAutoTotals(document);});
      window.addEventListener('fleet:after-filter',function(){window.fleetRefreshRecordMeta(document);});
      if(document.readyState==='loading'){
        document.addEventListener('DOMContentLoaded',function(){window.fleetRefreshAutoTotals(document);window.fleetRefreshRecordMeta(document);});
      }else{
        window.fleetRefreshAutoTotals(document);
        window.fleetRefreshRecordMeta(document);
      }
    })();

    // ── Reusable Category Multi-Select (body-appended, searchable, badges) ──
    window._catMultiSelect = function(btnId, hiddenId, cats, preSelected){
        var btn = document.getElementById(btnId);
        var hidden = document.getElementById(hiddenId);
        if(!btn || !hidden) return;

        var catColors = {Fuel:'#0d6efd',Maintenance:'#dc3545',Oil:'#198754',Salary:'#6f42c1',
            'Saman/Purchase':'#fd7e14','Cash Advance':'#20c997',Distribution:'#0dcaf0',
            General:'#6c757d',Other:'#adb5bd'};
        function _color(v){return catColors[v]||'#6c757d';}

        var dd = document.createElement('div');
        dd.className = '_cms-dd';
        dd.style.cssText = 'display:none;position:fixed;z-index:100000;background:#fff;border:1px solid #ccc;border-radius:8px;box-shadow:0 10px 36px rgba(0,0,0,.22);width:240px;padding:0;font-family:inherit;';

        var header = document.createElement('div');
        header.style.cssText = 'padding:8px 10px 6px;border-bottom:1px solid #eee;';
        var searchBox = document.createElement('input');
        searchBox.type = 'text'; searchBox.placeholder = '\uD83D\uDD0D Search categories...';
        searchBox.style.cssText = 'width:100%;border:1px solid #ddd;padding:5px 10px;font-size:.8rem;outline:none;box-sizing:border-box;border-radius:4px;background:#f8f9fa;';
        searchBox.addEventListener('focus',function(){searchBox.style.borderColor='#86b7fe';searchBox.style.background='#fff';});
        searchBox.addEventListener('blur',function(){searchBox.style.borderColor='#ddd';searchBox.style.background='#f8f9fa';});
        header.appendChild(searchBox);
        dd.appendChild(header);

        var listWrap = document.createElement('div');
        listWrap.style.cssText = 'max-height:220px;overflow-y:auto;padding:2px 0;';
        dd.appendChild(listWrap);

        var selAllCb = document.createElement('input');
        selAllCb.type = 'checkbox'; selAllCb.checked = false;
        selAllCb.style.cssText = 'accent-color:#0d6efd;width:15px;height:15px;cursor:pointer;';
        var selAllLbl = document.createElement('label');
        selAllLbl.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 12px;cursor:pointer;font-size:.82rem;font-weight:600;border-bottom:1px solid #eee;margin:0;color:#333;';
        selAllLbl.appendChild(selAllCb);
        selAllLbl.appendChild(document.createTextNode('Select All'));
        listWrap.appendChild(selAllLbl);

        var footer = document.createElement('div');
        footer.style.cssText = 'padding:6px 10px;border-top:1px solid #eee;display:flex;justify-content:space-between;align-items:center;';
        var countSpan = document.createElement('span');
        countSpan.style.cssText = 'font-size:.75rem;color:#888;';
        var clearBtn = document.createElement('button');
        clearBtn.type = 'button';
        clearBtn.textContent = 'Clear All';
        clearBtn.style.cssText = 'border:none;background:none;color:#dc3545;font-size:.75rem;cursor:pointer;padding:2px 6px;border-radius:3px;';
        clearBtn.addEventListener('mouseenter',function(){clearBtn.style.background='#fee2e2';});
        clearBtn.addEventListener('mouseleave',function(){clearBtn.style.background='none';});
        footer.appendChild(countSpan);
        footer.appendChild(clearBtn);
        dd.appendChild(footer);
        document.body.appendChild(dd);

        var cbs = [];
        var labels = [];
        cats.forEach(function(pair){
            var val = pair[0], lbl = pair[1], col = _color(val);
            var cb = document.createElement('input');
            cb.type = 'checkbox'; cb.value = val;
            cb.style.cssText = 'accent-color:'+col+';width:15px;height:15px;cursor:pointer;flex-shrink:0;';
            if(preSelected.indexOf(val) >= 0) cb.checked = true;
            var dot = document.createElement('span');
            dot.style.cssText = 'width:8px;height:8px;border-radius:50%;background:'+col+';flex-shrink:0;';
            var txt = document.createElement('span');
            txt.textContent = lbl;
            txt.style.cssText = 'flex:1;';
            var label = document.createElement('label');
            label.style.cssText = 'display:flex;align-items:center;gap:8px;padding:5px 12px;cursor:pointer;font-size:.82rem;margin:0;transition:background .12s;';
            label.setAttribute('data-search', lbl.toLowerCase());
            label.appendChild(cb); label.appendChild(dot); label.appendChild(txt);
            label.addEventListener('mouseenter',function(){label.style.background='#f0f4ff';});
            label.addEventListener('mouseleave',function(){label.style.background='';});
            listWrap.appendChild(label);
            cbs.push(cb); labels.push(label);
        });

        function updateBtn(){
            var checked = [];
            cbs.forEach(function(c){ if(c.checked) checked.push(c.value); });
            hidden.value = checked.join(',');
            var total = cbs.length, cnt = checked.length;
            countSpan.textContent = cnt ? cnt+' of '+total+' selected' : 'None selected';

            btn.innerHTML = '';
            if(cnt === 0){
                btn.textContent = '-- All Categories --';
                hidden.value = '';
                selAllCb.checked = false;
                selAllCb.indeterminate = false;
            } else if(cnt === total){
                btn.textContent = '-- All Categories --';
                hidden.value = '';
                selAllCb.checked = true;
                selAllCb.indeterminate = false;
            } else {
                selAllCb.checked = false;
                selAllCb.indeterminate = true;
                checked.forEach(function(v, i){
                    var badge = document.createElement('span');
                    badge.textContent = v;
                    badge.style.cssText = 'display:inline-block;background:'+_color(v)+';color:#fff;padding:1px 6px;border-radius:3px;font-size:.7rem;margin-right:3px;line-height:1.4;';
                    btn.appendChild(badge);
                });
            }
        }

        selAllCb.addEventListener('change', function(){
            var target = selAllCb.checked;
            var visible = labels.filter(function(l){return l.style.display !== 'none';});
            visible.forEach(function(l){l.querySelector('input').checked = target;});
            updateBtn();
        });
        cbs.forEach(function(c){ c.addEventListener('change', updateBtn); });

        clearBtn.addEventListener('click', function(e){
            e.stopPropagation();
            cbs.forEach(function(c){c.checked = false;});
            selAllCb.checked = false; selAllCb.indeterminate = false;
            updateBtn();
        });

        searchBox.addEventListener('input', function(){
            var q = searchBox.value.toLowerCase().trim();
            labels.forEach(function(l){
                l.style.display = !q || l.getAttribute('data-search').indexOf(q) >= 0 ? '' : 'none';
            });
        });

        var open = false;
        function posDD(){
            var r = btn.getBoundingClientRect();
            dd.style.left = r.left + 'px';
            dd.style.top = (r.bottom + 3) + 'px';
            dd.style.width = Math.max(r.width, 240) + 'px';
        }
        function showDD(){
            open = true; dd.style.display = 'block';
            posDD(); searchBox.value = '';
            labels.forEach(function(l){l.style.display = '';});
            requestAnimationFrame(function(){ searchBox.focus(); });
        }
        function hideDD(){ open = false; dd.style.display = 'none'; }

        btn.addEventListener('click', function(e){ e.stopPropagation(); open ? hideDD() : showDD(); });
        dd.addEventListener('click', function(e){ e.stopPropagation(); });
        dd.addEventListener('mousedown', function(e){ e.stopPropagation(); });
        document.addEventListener('click', function(e){ if(open && !dd.contains(e.target) && e.target !== btn) hideDD(); });
        window.addEventListener('scroll', function(){ if(open) posDD(); }, true);
        window.addEventListener('resize', function(){ if(open) posDD(); });

        updateBtn();
    };

    // ── Print & Export (all pages) ──
    window.fleetPrintExport = function(tableId, title, csvFilename, excelConfig) {
        var printBtn = document.getElementById('btnPrintReport');
        var exportBtn = document.getElementById('btnExportReport');
        if (!printBtn && !exportBtn) return;
        if (printBtn && !printBtn._fleetOrigHtml) printBtn._fleetOrigHtml = printBtn.innerHTML;
        if (exportBtn && !exportBtn._fleetOrigHtml) exportBtn._fleetOrigHtml = exportBtn.innerHTML;
        function _restorePrint() {
            if (printBtn) printBtn.innerHTML = printBtn._fleetOrigHtml || '<i class="bi bi-eye me-1"></i>Print / Preview';
        }
        function _restoreExport() {
            if (exportBtn) exportBtn.innerHTML = exportBtn._fleetOrigHtml || '<i class="bi bi-file-earmark-excel me-1"></i>Export';
        }

        function _allPagesUrl() {
            var u = new URLSearchParams(window.location.search);
            u.set('per_page', '99999'); u.set('page', '1');
            return window.location.pathname + '?' + u.toString();
        }

        function _hasClientSideTableFiltering(tbl) {
            if (!tbl) return false;
            if (tbl.querySelector('.ft-filter-btn.active')) return true;
            return !!tbl.querySelector('tbody tr[style*="display: none"]');
        }

        function _countFleetTableDataRows(tbl) {
            if (!tbl) return 0;
            var n = 0;
            tbl.querySelectorAll('tbody tr').forEach(function(tr) {
                if (tr.querySelector('td[colspan]')) return;
                if (tr.classList.contains('ft-upload-expand-row')) return;
                if (tr.classList.contains('no-print')) return;
                n += 1;
            });
            return n;
        }

        function _tableNeedsAllPagesFetch(tbl) {
            if (!tbl) return false;
            var attrTotal = tbl.getAttribute('data-fleet-pagination-total');
            if (attrTotal != null && attrTotal !== '') {
                var totalFromAttr = parseInt(String(attrTotal).replace(/,/g, ''), 10) || 0;
                return totalFromAttr > _countFleetTableDataRows(tbl);
            }
            var showingEl = document.querySelector('.card-footer small.text-muted');
            if (showingEl) {
                var totalMatch = showingEl.textContent.match(/of\s+([\d,]+)/i);
                var rangeMatch = showingEl.textContent.match(/([\d,]+)\s*[–-]\s*([\d,]+)/);
                if (totalMatch && rangeMatch) {
                    var total = parseInt(totalMatch[1].replace(/,/g, ''), 10) || 0;
                    var lo = parseInt(rangeMatch[1].replace(/,/g, ''), 10) || 0;
                    var hi = parseInt(rangeMatch[2].replace(/,/g, ''), 10) || 0;
                    if (total > Math.max(0, hi - lo + 1)) return true;
                }
            }
            var pager = document.querySelector('.pagination');
            return !!(pager && pager.querySelectorAll('.page-item').length > 3);
        }

        function _fetchAllTable(cb) {
            var localTbl = document.getElementById(tableId);
            var needsAllPages = _tableNeedsAllPagesFetch(localTbl);
            if (!needsAllPages) {
                cb(localTbl);
                return;
            }
            var url = _allPagesUrl();
            fetch(url, {credentials:'same-origin', redirect:'manual', cache:'no-store'}).then(function(r) {
                if (!r || r.type === 'opaqueredirect' || r.status === 0 || (r.status >= 300 && r.status < 400) || !r.ok) {
                    cb(localTbl);
                    return;
                }
                return r.text();
            }).then(function(html) {
                if (!html) return;
                var parser = new DOMParser();
                var doc = parser.parseFromString(html, 'text/html');
                var remoteTbl = doc.getElementById(tableId);
                if (remoteTbl) { cb(remoteTbl); } else { cb(localTbl); }
            }).catch(function(){ cb(localTbl); });
        }

        function _cleanTable(tbl) {
            var clone = tbl.cloneNode(true);
            clone.querySelectorAll('.ft-filter-wrap').forEach(function(el){ el.remove(); });
            clone.querySelectorAll('thead tr.mwo-search-row').forEach(function(el){ el.remove(); });
            clone.querySelectorAll('tbody tr').forEach(function(r){
                if (r.style.display === 'none') r.remove();
                else if (r.classList.contains('ft-upload-expand-row') || r.classList.contains('no-print')) r.remove();
            });
            clone.querySelectorAll('.btn, button, a.btn').forEach(function(el){ el.closest('td') && el.closest('td').remove(); });
            clone.querySelectorAll('th[style], td[style]').forEach(function(el){ el.removeAttribute('style'); });
            clone.querySelectorAll('a').forEach(function(a){
                var td = a.closest('td');
                if (td) td.textContent = (a.textContent || '').trim() || '-';
            });
            clone.querySelectorAll('input, select, textarea').forEach(function(el){
                var span = document.createElement('span');
                if (el.tagName === 'SELECT') {
                    span.textContent = (el.options[el.selectedIndex] && el.options[el.selectedIndex].textContent || '').trim() || '-';
                } else {
                    span.textContent = (el.value || '').trim() || '-';
                }
                el.replaceWith(span);
            });
            // Remove Edit/Actions columns and their corresponding cells
            var ths = clone.querySelectorAll('thead th');
            var indicesToRemove = [];
            clone.querySelectorAll('thead th').forEach(function(th, index){
                var t = th.textContent.trim();
                if (th.classList.contains('no-export') || t === 'Edit' || t === 'Actions' || t === 'Action'){
                    indicesToRemove.push(index);
                    th.remove();
                }
            });
            // Remove corresponding td cells in each row
            clone.querySelectorAll('tbody tr, tfoot tr').forEach(function(row){
                var cells = row.querySelectorAll('td, th');
                // Remove cells from right to left to avoid index shift
                for(var i = indicesToRemove.length - 1; i >= 0; i--){
                    if(cells[indicesToRemove[i]]){
                        cells[indicesToRemove[i]].remove();
                    }
                }
            });
            return clone;
        }

        function _fleetBaseFilename() {
            var base = (csvFilename || 'export.csv').replace(/\.(csv|xlsx|pdf)$/i, '');
            return base || 'export';
        }

        function _fleetDownloadBlob(blob, filename) {
            if (window.FleetBridge && typeof window.FleetBridge.downloadBlob === 'function') {
                return window.FleetBridge.downloadBlob(blob, filename);
            }
            var a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            setTimeout(function() {
                document.body.removeChild(a);
                URL.revokeObjectURL(a.href);
            }, 400);
            return Promise.resolve();
        }

        function _fleetLoadScript(src) {
            return new Promise(function(resolve, reject) {
                var existing = document.querySelector('script[data-fleet-src="' + src + '"]');
                if (existing) {
                    if (existing.getAttribute('data-fleet-loaded') === '1') {
                        resolve();
                        return;
                    }
                    existing.addEventListener('load', function() { resolve(); });
                    existing.addEventListener('error', function() { reject(new Error('Script load failed')); });
                    return;
                }
                var scr = document.createElement('script');
                scr.src = src;
                scr.setAttribute('data-fleet-src', src);
                scr.onload = function() {
                    scr.setAttribute('data-fleet-loaded', '1');
                    resolve();
                };
                scr.onerror = function() { reject(new Error('Script load failed')); };
                document.head.appendChild(scr);
            });
        }

        function _fleetTableToCsvBlob(clone) {
            var headers = [];
            clone.querySelectorAll('thead th').forEach(function(th) {
                headers.push('"' + th.textContent.trim().replace(/"/g, '""') + '"');
            });
            var csvRows = [headers.join(',')];
            clone.querySelectorAll('tbody tr').forEach(function(tr) {
                if (tr.cells.length <= 1) return;
                var cells = [];
                tr.querySelectorAll('td').forEach(function(td) {
                    cells.push('"' + td.textContent.trim().replace(/"/g, '""') + '"');
                });
                csvRows.push(cells.join(','));
            });
            var foot = clone.querySelector('tfoot tr');
            if (foot) {
                var fc = [];
                foot.querySelectorAll('td').forEach(function(td) {
                    fc.push('"' + td.textContent.trim().replace(/"/g, '""') + '"');
                });
                csvRows.push(fc.join(','));
            }
            return new Blob(['\uFEFF' + csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' });
        }

        function _fleetTableToAoa(clone) {
            var aoa = [];
            var headerRow = [];
            clone.querySelectorAll('thead th').forEach(function(th) {
                headerRow.push(th.textContent.trim());
            });
            if (headerRow.length) aoa.push(headerRow);
            clone.querySelectorAll('tbody tr').forEach(function(tr) {
                if (tr.cells.length <= 1) return;
                var row = [];
                tr.querySelectorAll('td').forEach(function(td) {
                    row.push(td.textContent.trim());
                });
                if (row.length) aoa.push(row);
            });
            var foot = clone.querySelector('tfoot tr');
            if (foot) {
                var footRow = [];
                foot.querySelectorAll('td, th').forEach(function(td) {
                    footRow.push(td.textContent.trim());
                });
                if (footRow.length) aoa.push(footRow);
            }
            return aoa;
        }

        function _fleetExportCsv(clone) {
            return _fleetDownloadBlob(_fleetTableToCsvBlob(clone), _fleetBaseFilename() + '.csv');
        }

        function _tryParseNumber(str) {
            if (str === null || str === undefined) return null;
            str = String(str).trim();
            if (str === '' || str === '-') return null;
            str = str.replace(/,/g, '');
            var n = parseFloat(str);
            if (!isNaN(n) && isFinite(n)) return n;
            return null;
        }

        function _parseDateToObj(str) {
            if (!str) return null;
            str = String(str).trim();
            if (!str || str === '-') return null;
            var m = str.match(/^(\d{1,2})-(\d{1,2})-(\d{4})$/);
            if (m) return new Date(parseInt(m[3], 10), parseInt(m[2], 10) - 1, parseInt(m[1], 10));
            return null;
        }

        function _fleetTableToAoaExcel(clone, config) {
            var aoa = _fleetTableToAoa(clone);
            if (!config || !aoa || aoa.length < 2) return aoa;
            var headers = aoa[0];
            var footerRow = null;
            var dataRows = [];
            for (var i = 1; i < aoa.length; i++) {
                if (i === aoa.length - 1 && aoa[i].length < headers.length) footerRow = aoa[i];
                else dataRows.push(aoa[i]);
            }
            var newIndices = [];
            if (config.columnOrder && config.columnOrder.length) {
                config.columnOrder.forEach(function(colName) {
                    var idx = headers.indexOf(colName);
                    if (idx >= 0) newIndices.push(idx);
                });
                headers.forEach(function(_, idx) {
                    if (newIndices.indexOf(idx) < 0) newIndices.push(idx);
                });
            } else {
                newIndices = headers.map(function(_, i) { return i; });
            }
            var numberColNewIdx = [];
            var dateColNewIdx = [];
            if (config.numberColumns) {
                config.numberColumns.forEach(function(colName) {
                    var origIdx = headers.indexOf(colName);
                    if (origIdx >= 0) { var ni = newIndices.indexOf(origIdx); if (ni >= 0) numberColNewIdx.push(ni); }
                });
            }
            if (config.dateColumns) {
                config.dateColumns.forEach(function(colName) {
                    var origIdx = headers.indexOf(colName);
                    if (origIdx >= 0) { var ni = newIndices.indexOf(origIdx); if (ni >= 0) dateColNewIdx.push(ni); }
                });
            }
            var newHeaders = newIndices.map(function(idx) { return headers[idx]; });
            var newAoa = [newHeaders];
            dataRows.forEach(function(row) {
                var newRow = newIndices.map(function(idx) { return row[idx] !== undefined ? row[idx] : ''; });
                numberColNewIdx.forEach(function(ci) {
                    var num = _tryParseNumber(newRow[ci]);
                    if (num !== null) newRow[ci] = num;
                });
                dateColNewIdx.forEach(function(ci) {
                    var dt = _parseDateToObj(newRow[ci]);
                    if (dt) newRow[ci] = dt;
                });
                newAoa.push(newRow);
            });
            if (footerRow) newAoa.push(footerRow);
            return newAoa;
        }

        function _setExcelDateFormats(ws, aoa, dateColumnNames) {
            if (!ws || !aoa || !aoa.length || !window.XLSX) return;
            var headers = aoa[0];
            var dateColIndices = [];
            dateColumnNames.forEach(function(colName) {
                var idx = headers.indexOf(colName);
                if (idx >= 0) dateColIndices.push(idx);
            });
            for (var r = 1; r < aoa.length; r++) {
                dateColIndices.forEach(function(ci) {
                    var addr = window.XLSX.utils.encode_cell({ r: r, c: ci });
                    var cell = ws[addr];
                    if (cell && cell.v != null) cell.z = 'dd-mmm-yy';
                });
            }
        }

        function _fleetExportExcel(clone) {
            var serverUrl = exportBtn && exportBtn.getAttribute('data-export-url');
            if (serverUrl) {
                var qs = new URLSearchParams(window.location.search || '');
                qs.delete('page');
                qs.delete('per_page');
                window.location.href = serverUrl + (qs.toString() ? ('?' + qs.toString()) : '');
                return Promise.resolve();
            }
            return _fleetLoadScript('https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.17.0/xlsx.full.min.js').then(function() {
                if (!window.XLSX) throw new Error('Excel library not available');
                var aoa = excelConfig ? _fleetTableToAoaExcel(clone, excelConfig) : _fleetTableToAoa(clone);
                var ws = window.XLSX.utils.aoa_to_sheet(aoa, { cellDates: true });
                if (excelConfig && excelConfig.dateColumns) _setExcelDateFormats(ws, aoa, excelConfig.dateColumns);
                var wb = window.XLSX.utils.book_new();
                window.XLSX.utils.book_append_sheet(wb, ws, (title || 'Report').substring(0, 31));
                var out = window.XLSX.write(wb, { bookType: 'xlsx', type: 'array' });
                return _fleetDownloadBlob(new Blob([out], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }), _fleetBaseFilename() + '.xlsx');
            });
        }

        function _fleetExportPdf(clone) {
            return _fleetLoadScript('https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.2/html2pdf.bundle.min.js').then(function() {
                var wrap = document.createElement('div');
                wrap.style.cssText = 'padding:12px;font-family:Arial,sans-serif;background:#fff;';
                var h3 = document.createElement('h3');
                h3.textContent = title || 'Report';
                h3.style.cssText = 'text-align:center;margin:0 0 12px;font-size:16px;';
                wrap.appendChild(h3);
                wrap.appendChild(clone);
                var pdfName = _fleetBaseFilename() + '.pdf';
                var h2p = window.html2pdf;
                if (!h2p) throw new Error('PDF library not available');
                return h2p().set({
                    margin: [6, 4, 6, 4],
                    filename: pdfName,
                    image: { type: 'jpeg', quality: 0.92 },
                    html2canvas: { scale: 2, useCORS: true, logging: false },
                    jsPDF: { unit: 'mm', format: 'a4', orientation: 'landscape' },
                    pagebreak: { mode: ['css', 'legacy'] }
                }).from(wrap).output('blob').then(function(blob) {
                    return _fleetDownloadBlob(blob, pdfName);
                });
            });
        }

        var _fleetExportMenuEl = null;
        function _closeFleetExportMenu() {
            if (_fleetExportMenuEl) {
                _fleetExportMenuEl.remove();
                _fleetExportMenuEl = null;
            }
        }

        function _showFleetExportMenu(anchorBtn) {
            _closeFleetExportMenu();
            if (!document.getElementById('fleet-export-menu-style')) {
                var st = document.createElement('style');
                st.id = 'fleet-export-menu-style';
                st.textContent =
                    '.fleet-export-menu{position:fixed;z-index:100060;min-width:168px;background:#fff;border:1px solid #dee2e6;border-radius:8px;box-shadow:0 10px 28px rgba(15,23,42,.18);padding:4px 0;overflow:hidden;}' +
                    '.fleet-export-menu button{display:flex;align-items:center;gap:8px;width:100%;border:0;background:transparent;padding:8px 14px;font-size:.82rem;color:#1e293b;text-align:left;cursor:pointer;}' +
                    '.fleet-export-menu button:hover{background:#f1f5f9;}' +
                    '.fleet-export-menu button .bi{font-size:1rem;width:18px;text-align:center;}';
                document.head.appendChild(st);
            }
            var menu = document.createElement('div');
            menu.className = 'fleet-export-menu';
            menu.setAttribute('role', 'menu');
            [
                { format: 'excel', icon: 'bi-file-earmark-excel', label: 'Excel', color: '#157347' },
                { format: 'pdf', icon: 'bi-file-earmark-pdf', label: 'PDF', color: '#dc3545' },
                { format: 'csv', icon: 'bi-filetype-csv', label: '.csv file', color: '#0d6efd' }
            ].forEach(function(opt) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.setAttribute('data-fleet-export-format', opt.format);
                btn.innerHTML = '<i class="bi ' + opt.icon + '" style="color:' + opt.color + '"></i><span>' + opt.label + '</span>';
                btn.addEventListener('click', function(ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    _runFleetExport(opt.format);
                });
                menu.appendChild(btn);
            });
            document.body.appendChild(menu);
            _fleetExportMenuEl = menu;
            var rect = anchorBtn.getBoundingClientRect();
            var left = rect.left;
            var top = rect.bottom + 4;
            if (left + menu.offsetWidth > window.innerWidth - 8) left = rect.right - menu.offsetWidth;
            if (top + menu.offsetHeight > window.innerHeight - 8) top = rect.top - menu.offsetHeight - 4;
            menu.style.left = Math.max(8, left) + 'px';
            menu.style.top = Math.max(8, top) + 'px';
        }

        function _runFleetExport(format) {
            _closeFleetExportMenu();
            if (!exportBtn) return;
            var serverUrl = exportBtn.getAttribute('data-export-url');
            if (format === 'excel' && serverUrl) {
                exportBtn.disabled = true;
                exportBtn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Loading...';
                _fleetExportExcel(null);
                setTimeout(function() { exportBtn.disabled = false; _restoreExport(); }, 1500);
                return;
            }
            exportBtn.disabled = true;
            exportBtn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Loading...';
            _fetchAllTable(function(tbl) {
                if (!tbl) {
                    exportBtn.disabled = false;
                    _restoreExport();
                    return;
                }
                var clone = _cleanTable(tbl);
                var job;
                if (format === 'excel') job = _fleetExportExcel(clone);
                else if (format === 'pdf') job = _fleetExportPdf(clone);
                else job = _fleetExportCsv(clone);
                Promise.resolve(job).catch(function(err) {
                    alert((err && err.message) ? err.message : 'Export failed. Please try again.');
                }).finally(function() {
                    exportBtn.disabled = false;
                    _restoreExport();
                });
            });
        }

        if (!window._fleetExportMenuDocBound) {
            window._fleetExportMenuDocBound = true;
            document.addEventListener('click', function(e) {
                if (!e.target.closest('.fleet-export-menu') && !e.target.closest('#btnExportReport')) {
                    _closeFleetExportMenu();
                }
            });
            document.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') _closeFleetExportMenu();
            });
        }

        var _fleetPreviewCss =
            '@page{size:A4 landscape;margin:8mm;}' +
            'body{font-family:Arial,sans-serif;font-size:10px;margin:0;padding:8px 12px;}' +
            '.toolbar{position:sticky;top:0;z-index:99;background:#1e293b;color:#fff;padding:8px 16px;display:flex;align-items:center;justify-content:space-between;gap:10px;border-radius:0 0 6px 6px;box-shadow:0 2px 8px rgba(0,0,0,.2);margin:-8px -12px 12px;}' +
            '.toolbar h4{margin:0;font-size:14px;font-weight:600;}' +
            '.toolbar button{padding:5px 16px;border:none;border-radius:4px;font-size:12px;font-weight:600;cursor:pointer;}' +
            '.btn-p{background:#3b82f6;color:#fff;}.btn-p:hover{background:#2563eb;}' +
            '.btn-c{background:#64748b;color:#fff;margin-left:6px;}.btn-c:hover{background:#475569;}' +
            'h3{text-align:center;margin:6px 0 10px;font-size:14px;}' +
            'table{width:100%;border-collapse:collapse;table-layout:auto;}' +
            'th,td{border:1px solid #555;padding:3px 5px;text-align:left;vertical-align:top;}' +
            'th:not(.rpt-wrap-cell):not(.rpt-head-wrap),td:not(.rpt-wrap-cell){white-space:nowrap;}' +
            'th.rpt-compact,td.rpt-compact{width:1%;white-space:nowrap;}' +
            'th.rpt-head-wrap{white-space:normal!important;width:1%;max-width:6.5em;line-height:1.2;font-size:8px;text-align:center;vertical-align:middle;}' +
            'td.rpt-head-wrap{text-align:center;white-space:nowrap;width:1%;}' +
            'th.rpt-num-cell,td.rpt-num-cell{text-align:right;white-space:nowrap;width:1%;}' +
            'th.rpt-wrap-cell,td.rpt-wrap-cell{white-space:normal!important;word-wrap:break-word;overflow-wrap:break-word;hyphens:auto;width:auto;}' +
            'th{background:#e9ecef;font-size:9px;}' +
            'tfoot td{font-weight:bold;background:#f8f9fa;}' +
            '.text-end{text-align:right;}.text-center{text-align:center;}' +
            '.text-danger{color:#dc3545;}.fw-bold{font-weight:700;}.fw-medium{font-weight:500;}' +
            '@media print{.toolbar{display:none!important;}}';

        function _removeFleetPrintPreviewOverlay() {
            var ex = document.getElementById('_fleetPrintPreviewRoot');
            if (ex) ex.remove();
        }

        /** Same-window preview: Close removes overlay and returns to the report (native app / popup-blocked). */
        function _openFleetPrintPreviewOverlay(titleText, clone) {
            _removeFleetPrintPreviewOverlay();
            var root = document.createElement('div');
            root.id = '_fleetPrintPreviewRoot';
            root.style.cssText = 'position:fixed;inset:0;z-index:100000;background:#fff;overflow:auto;-webkit-overflow-scrolling:touch;';
            var styleEl = document.createElement('style');
            styleEl.textContent = _fleetPreviewCss;
            root.appendChild(styleEl);
            var bar = document.createElement('div');
            bar.className = 'toolbar';
            var h4 = document.createElement('h4');
            h4.textContent = titleText;
            var btnWrap = document.createElement('div');
            var cbtn = document.createElement('button');
            cbtn.type = 'button';
            cbtn.className = 'btn-c';
            cbtn.innerHTML = '&#10005; Close';
            cbtn.addEventListener('click', function() { _removeFleetPrintPreviewOverlay(); });
            btnWrap.appendChild(cbtn);
            bar.appendChild(h4);
            bar.appendChild(btnWrap);
            root.appendChild(bar);
            var inner = document.createElement('div');
            inner.style.cssText = 'padding:8px 12px;';
            var h3 = document.createElement('h3');
            h3.textContent = titleText;
            inner.appendChild(h3);
            inner.appendChild(clone);
            root.appendChild(inner);
            document.body.appendChild(root);
        }

        if (printBtn) {
            printBtn.addEventListener('click', function() {
                printBtn.disabled = true; printBtn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Loading...';
                _fetchAllTable(function(tbl) {
                    if (!tbl) { printBtn.disabled = false; _restorePrint(); return; }
                    var clone = _cleanTable(tbl);
                    var isNativeApp = !!(window.FleetBridge && window.FleetBridge.isNative);
                    if (isNativeApp) {
                        _openFleetPrintPreviewOverlay(title, clone);
                        printBtn.disabled = false; _restorePrint();
                        return;
                    }
                    var w = window.open('', '_blank');
                    if (!w || typeof w.document === 'undefined' || !w.document) {
                        _openFleetPrintPreviewOverlay(title, clone);
                        printBtn.disabled = false; _restorePrint();
                        return;
                    }
                    try {
                        w.document.write('<!DOCTYPE html><html><head><title>' + title + '</title>');
                        w.document.write('<style>' + _fleetPreviewCss + '</style></head><body>');
                        w.document.write('<div class="toolbar"><h4>' + title + '</h4><div>');
                        w.document.write('<button class="btn-p" onclick="window.print()">&#128438; Print</button>');
                        w.document.write('<button class="btn-c" onclick="window.close()">&#10005; Close</button>');
                        w.document.write('</div></div>');
                        w.document.write('<h3>' + title + '</h3>');
                        w.document.write(clone.outerHTML);
                        w.document.write('</body></html>');
                        w.document.close();
                        w.focus();
                    } catch (e) {
                        try { if (w && !w.closed) w.close(); } catch (e2) {}
                        _openFleetPrintPreviewOverlay(title, clone);
                    }
                    printBtn.disabled = false; _restorePrint();
                });
            });
        }
        if (exportBtn) {
            if (exportBtn.dataset.fleetExportMenuBound !== '1') {
                exportBtn.dataset.fleetExportMenuBound = '1';
                exportBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    if (_fleetExportMenuEl) {
                        _closeFleetExportMenu();
                        return;
                    }
                    _showFleetExportMenu(exportBtn);
                });
            }
        }
    };

/* ── Section separator ── */

/* ── Block with Jinja2 statements, kept inline in base.html ── */

/* ═══════════════════════════════════════════════════════════════
   Mega block: Activity logging, clock, diagnostics, sidebar, FCM, etc.
   (extracted from base.html inline script)
   ═══════════════════════════════════════════════════════════════ */

// ─── Activity logging: device ID + geolocation (one-time permission, background updates) ───
    // Public API:
    //   getOrCreateDeviceId() - returns UUID from localStorage (creates and saves if missing).
    //   logActivity(actionName) - sends POST to backend with device_id, action, and latest lat/lng/accuracy.
    //   data-log-action="Button Click: Save" on any element - clicking it will call logActivity(attr value).
    // Location is requested ONLY ONCE per session (sessionStorage); then watchPosition keeps coords updated (enableHighAccuracy: true).
    (function() {
        var STORAGE_KEY = 'deviceId';
        var GEO_SESSION_KEY = 'activityLogGeoRequested';

        function generateUUID() {
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
        }

        function getOrCreateDeviceId() {
            try {
                var id = localStorage.getItem(STORAGE_KEY);
                if (id && id.length > 0) return id;
                id = generateUUID();
                localStorage.setItem(STORAGE_KEY, id);
                return id;
            } catch (e) { return null; }
        }

        window.getOrCreateDeviceId = getOrCreateDeviceId;
        window.__lastPosition = null;
        window.__geoWatchId = null;
        window.__positionLogged = false;

        function onPositionUpdate(p) {
            window.__lastPosition = { latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy: p.coords.accuracy };
            if (!window.__positionLogged && typeof window.logActivity === 'function') {
                window.__positionLogged = true;
                window.logActivity('Location acquired');
            }
        }

        function startGeolocationOnce() {
            // On native app with insecure origin (HTTP local IP), use Capacitor Geolocation plugin instead of browser API
            var _isNativeApp = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());
            var _capGeo = _isNativeApp && window.Capacitor.Plugins && window.Capacitor.Plugins.Geolocation;
            if (_capGeo) {
                // Native plugin — no secure-origin restriction
                if (sessionStorage.getItem(GEO_SESSION_KEY)) return;
                _capGeo.getCurrentPosition({ enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 })
                    .then(function(p) {
                        sessionStorage.setItem(GEO_SESSION_KEY, '1');
                        onPositionUpdate(p);
                    })
                    .catch(function() { try { sessionStorage.setItem(GEO_SESSION_KEY, '1'); } catch(e) {} });
                return;
            }
            if (!navigator.geolocation) return;
            // Browser location sirf HTTPS ya localhost par allow karta hai. HTTP (e.g. 192.168.x.x) par na popup aata hai na Allow enable hota.
            if (typeof window.isSecureContext !== 'undefined' && !window.isSecureContext) {
                try { sessionStorage.setItem(GEO_SESSION_KEY, '1'); } catch (e) {}
                return;
            }
            if (sessionStorage.getItem(GEO_SESSION_KEY)) {
                navigator.geolocation.getCurrentPosition(
                    function(p) {
                        onPositionUpdate(p);
                    },
                    function() {},
                    { enableHighAccuracy: true, maximumAge: 60000, timeout: 10000 }
                );
                if (!window.__geoWatchId) {
                    window.__geoWatchId = navigator.geolocation.watchPosition(
                        function(p) { onPositionUpdate(p); },
                        function() {},
                        { enableHighAccuracy: true, maximumAge: 5000, timeout: 10000 }
                    );
                }
                return;
            }
            navigator.geolocation.getCurrentPosition(
                function(p) {
                    sessionStorage.setItem(GEO_SESSION_KEY, '1');
                    onPositionUpdate(p);
                    if (!window.__geoWatchId) {
                        window.__geoWatchId = navigator.geolocation.watchPosition(
                            function(pos) { onPositionUpdate(pos); },
                            function() {},
                            { enableHighAccuracy: true, maximumAge: 5000, timeout: 10000 }
                        );
                    }
                },
                function() { sessionStorage.setItem(GEO_SESSION_KEY, '1'); },
                { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 }
            );
        }

        window.logActivity = function(actionName) {
            var deviceId = getOrCreateDeviceId();
            var pos = window.__lastPosition || null;
            var payload = {
                action: (actionName || 'Activity').substring(0, 200),
                device_id: deviceId || ''
            };
            if (pos) {
                payload.latitude = pos.latitude;
                payload.longitude = pos.longitude;
                payload.accuracy = pos.accuracy;
            }
            var csrfEl = document.querySelector('meta[name="csrf-token"]');
            var headers = { 'Content-Type': 'application/json' };
            if (csrfEl && csrfEl.getAttribute('content')) headers['X-CSRFToken'] = csrfEl.getAttribute('content');
            fetch(window.FleetConfig.urls.api_log_activity, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(payload),
                credentials: 'same-origin'
            }).catch(function() {});
        };

        window.__lastPosition = null;
        window.__geoWatchId = null;
        window.__positionLogged = false;

        document.addEventListener('DOMContentLoaded', function() {
            startGeolocationOnce();
            // Optional: log activity when elements with data-log-action are clicked
            document.body.addEventListener('click', function(e) {
                var el = e.target.closest('[data-log-action]');
                if (el && typeof window.logActivity === 'function') {
                    var action = (el.getAttribute('data-log-action') || '').trim();
                    if (action) window.logActivity(action);
                }
            }, true);
        });
    })();

    (function() {
        var s = document.createElement('script');
        s.src = window.FleetConfig.urls.static;
        s.onload = function() {
            if (typeof window.fleetInitClientDiagnostics === 'function') {
                window.fleetInitClientDiagnostics(
                    window.FleetConfig.urls.api_client_diagnostics,
                    window.FleetConfig.csrfToken
                );
            }
        };
        document.head.appendChild(s);
    })();

    // Global District datalist for typeahead
    // (Used by inputs with list="districtOptions")
    // Render options once here so all forms can reuse.
    document.addEventListener("DOMContentLoaded", function() {
        var existing = document.getElementById("districtOptions");
        if (!existing) {
            var dl = document.createElement("datalist");
            dl.id = "districtOptions";
            /* District datalist populated from FleetConfig */
            if (window.FleetConfig && window.FleetConfig.allDistricts) {
                window.FleetConfig.allDistricts.forEach(function(dName) {
                    var opt = document.createElement('option');
                    opt.value = dName;
                    dl.appendChild(opt);
                });
            }
            document.body.appendChild(dl);
        }
    });

    // ── Top Progress Bar (page navigation indicator) ─────────────────────
    (function() {
        var bar = document.getElementById('topLoadBar');
        if (!bar) return;

        function tlbStart() {
            bar.classList.remove('tlb-done');
            bar.style.transition = 'none';
            bar.style.width = '0%';
            void bar.offsetWidth; // force reflow
            bar.classList.add('tlb-loading');
        }
        function tlbFinish() {
            bar.classList.remove('tlb-loading');
            bar.classList.add('tlb-done');
            setTimeout(function() {
                bar.classList.remove('tlb-done');
                bar.style.width = '0%';
            }, 650);
        }

        // Start immediately (page is arriving)
        tlbStart();
        // Finish when DOM is ready
        document.addEventListener('DOMContentLoaded', tlbFinish);

        // Re-start on any navigating link click
        document.addEventListener('click', function(e) {
            var a = e.target.closest('a[href]');
            if (!a) return;
            var href = a.getAttribute('href') || '';
            // Skip: hash-only, javascript:, new-tab, BS toggles, API
            if (!href || href === '#' || href.charAt(0) === '#' ||
                href.indexOf('javascript') === 0 || a.target === '_blank' ||
                a.getAttribute('data-bs-toggle') || href.indexOf('/api/') === 0) return;
            tlbStart();
        }, true);

        // Catch form submissions
        document.addEventListener('submit', tlbStart, true);
    })();

    // Sidebar Toggle + Workspace lock behavior
    function toggleSidebar() {
        var sb = document.getElementById("sidebar");
        var mc = document.getElementById("mainContent");
        if (!sb || !mc) return;
        if (sessionStorage.getItem("isWorkspaceModeActive") === "1") {
            // Workspace mode lock: keep sidebar collapsed.
            sb.classList.add("collapsed");
            mc.classList.add("expanded");
            document.cookie = "workspace_sidebar_open=0; path=/; max-age=31536000; SameSite=Lax";
            return;
        }
        sb.classList.toggle("collapsed");
        mc.classList.toggle("expanded");
        if (sb.classList.contains("collapsed")) {
            document.cookie = "workspace_sidebar_open=0; path=/; max-age=31536000; SameSite=Lax";
        } else {
            document.cookie = "workspace_sidebar_open=1; path=/; max-age=31536000; SameSite=Lax";
        }
    }

    // Workspace sidebar mode lock:
    // - Entering workspace => force collapsed, keep locked.
    // - Navigating to any other left-main menu => unlock and expand.
    document.addEventListener('DOMContentLoaded', function() {
        var isWorkspacePage = (window.FleetConfig && window.FleetConfig.workspaceOpen) || false;
        var WORKSPACE_MODE_KEY = "isWorkspaceModeActive";
        var sb = document.getElementById('sidebar');
        var mc = document.getElementById('mainContent');
        var wsEntry = document.getElementById('workspaceSidebarEntry');

        function forceCollapsedSidebar() {
            if (window.innerWidth >= 992 && sb && mc) {
                sb.classList.add('collapsed');
                mc.classList.add('expanded');
            }
            document.cookie = "workspace_sidebar_open=0; path=/; max-age=31536000; SameSite=Lax";
        }

        function forceExpandedSidebar() {
            if (window.innerWidth >= 992 && sb && mc) {
                sb.classList.remove('collapsed');
                mc.classList.remove('expanded');
            }
            document.cookie = "workspace_sidebar_open=1; path=/; max-age=31536000; SameSite=Lax";
        }

        if (isWorkspacePage) {
            sessionStorage.setItem(WORKSPACE_MODE_KEY, "1");
            forceCollapsedSidebar();
        } else {
            sessionStorage.removeItem(WORKSPACE_MODE_KEY);
        }

        if (!wsEntry) return;

        wsEntry.addEventListener('click', function(e) {
            // Keep browser default behavior for modified clicks/new-tab actions.
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
            sessionStorage.setItem(WORKSPACE_MODE_KEY, "1");
            forceCollapsedSidebar();
            // Navigate explicitly after cookie write so next page always receives collapsed state.
            var href = wsEntry.getAttribute('href');
            if (href) {
                e.preventDefault();
                setTimeout(function() { window.location.href = href; }, 20);
            }
        });

        // Leaving workspace through left sidebar main menus should unlock and re-open.
        document.querySelectorAll('#sidebar a[href]').forEach(function(link){
            if (link.id === 'workspaceSidebarEntry') return;
            link.addEventListener('click', function(e){
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
                var href = link.getAttribute('href') || '';
                if (!href || href.indexOf('javascript:') === 0) return;
                sessionStorage.removeItem(WORKSPACE_MODE_KEY);
                forceExpandedSidebar();
            });
        });

        // Parent dropdown/menu toggles must also break lock and expand sidebar.
        document.querySelectorAll('#sidebar a.dropdown-toggle, #sidebar .sb-sub-toggle').forEach(function(toggleEl){
            toggleEl.addEventListener('click', function(e){
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
                if (toggleEl.id === 'workspaceSidebarEntry') return;
                sessionStorage.removeItem(WORKSPACE_MODE_KEY);
                forceExpandedSidebar();
            });
        });
    });

    // Live Clock — Pakistan Server Time (PKT)
    var _pktOffset = (function(){
        var serverISO = window.FleetConfig.serverPkNow;
        var serverMs = new Date(serverISO).getTime();
        var browserMs = Date.now();
        return serverMs - browserMs;
    })();
    function updateDateTime() {
        var now = new Date(Date.now() + _pktOffset);
        /* Same instant as server clock sync; format in Asia/Karachi (not UTC getters — those wrongly showed UTC as "PKT"). */
        var parts = new Intl.DateTimeFormat('en-US', {
            timeZone: 'Asia/Karachi',
            weekday: 'short',
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true,
            hourCycle: 'h12'
        }).formatToParts(now);
        var map = {};
        for (var i = 0; i < parts.length; i++) {
            var p = parts[i];
            if (p.type !== 'literal') map[p.type] = p.value;
        }
        var dateStr = map.weekday + ', ' + map.month + ' ' + map.day + ', ' + map.year;
        var ap = (map.dayPeriod || '').toUpperCase();
        var timeStr = map.hour + ':' + map.minute + ':' + map.second + ' ' + ap;
        var el = document.getElementById("liveDateTime");
        if(el) el.innerHTML = '<i class="bi bi-calendar3 me-1"></i> ' + dateStr + ' | <i class="bi bi-clock me-1"></i> ' + timeStr + ' PKT';
    }
    setInterval(updateDateTime, 1000);
    updateDateTime();

    /** Minutes since midnight (0–1439) in Asia/Karachi — matches Attendance Time Control HH:MM windows + server skew. */
    window.pktMinutesFromMidnight = function(d) {
        var parts = new Intl.DateTimeFormat('en-GB', {
            timeZone: 'Asia/Karachi',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        }).formatToParts(d);
        var h = 0, m = 0;
        for (var i = 0; i < parts.length; i++) {
            if (parts[i].type === 'hour') h = parseInt(parts[i].value, 10) || 0;
            if (parts[i].type === 'minute') m = parseInt(parts[i].value, 10) || 0;
        }
        return h * 60 + m;
    };
    /** DD-MM-YYYY + hh:mm:ss AM/PM + weekday in Asia/Karachi for GPS+Camera photo overlay (not UTC). */
    window.pktOverlayDateTimeStrings = function(d) {
        var parts = new Intl.DateTimeFormat('en-US', {
            timeZone: 'Asia/Karachi',
            weekday: 'short',
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true,
            hourCycle: 'h12'
        }).formatToParts(d);
        var map = {};
        for (var i = 0; i < parts.length; i++) {
            if (parts[i].type !== 'literal') map[parts[i].type] = parts[i].value;
        }
        var ap = (map.dayPeriod || '').toUpperCase();
        var dateStr = map.day + '-' + map.month + '-' + map.year;
        var timeStr = map.hour + ':' + map.minute + ':' + map.second + ' ' + ap;
        return {
            dateStr: dateStr,
            timeStr: timeStr,
            weekdayShort: map.weekday || '',
            dateTimeDisplay: (map.weekday ? map.weekday + ', ' : '') + dateStr + ' ' + timeStr + ' PKT'
        };
    };

    function pktCanvasRoundRect(ctx, x, y, rw, rh, radius) {
        var r = Math.max(0, Math.min(radius, rw / 2, rh / 2));
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + rw, y, x + rw, y + rh, r);
        ctx.arcTo(x + rw, y + rh, x, y + rh, r);
        ctx.arcTo(x, y + rh, x, y, r);
        ctx.arcTo(x, y, x + rw, y, r);
        ctx.closePath();
    }

    /** ISO 3166-1 alpha-2 → flag emoji (e.g. PK → 🇵🇰). */
    window.fleetCountryCodeToFlagEmoji = function(code) {
        var c = String(code || '').trim().toUpperCase();
        if (c.length !== 2 || c.charCodeAt(0) < 65 || c.charCodeAt(0) > 90 || c.charCodeAt(1) < 65 || c.charCodeAt(1) > 90) {
            return '';
        }
        return String.fromCodePoint(0x1F1E6 + c.charCodeAt(0) - 65, 0x1F1E6 + c.charCodeAt(1) - 65);
    };

    /** Attendance stamp rows: title, time, project·vehicle·driver, district·country·flag, GPS. */
    window.fleetBuildAttendanceStampLines = function(opts) {
        opts = opts || {};
        var prefix = (opts.line1Prefix != null && opts.line1Prefix !== '') ? String(opts.line1Prefix) : 'GPS+Cam';
        var now = new Date(Date.now() + (typeof _pktOffset !== 'undefined' ? _pktOffset : 0));
        var _od = (typeof pktOverlayDateTimeStrings === 'function')
            ? pktOverlayDateTimeStrings(now)
            : { dateStr: '--', timeStr: '--', dateTimeDisplay: '--' };
        var stampLines = [];
        stampLines.push({ text: prefix, scale: 1.0 });
        stampLines.push({ text: _od.dateTimeDisplay || (_od.dateStr + ' ' + _od.timeStr), scale: 0.9, fitWidth: true });
        var projectName = opts.projectName ? String(opts.projectName).trim() : '';
        var vehicleNo = opts.vehicleNo ? String(opts.vehicleNo).trim() : '';
        var driverName = opts.driverName ? String(opts.driverName).trim() : '';
        if (projectName || vehicleNo || driverName) {
            var pvd = '';
            if (projectName) pvd += 'Project: ' + projectName;
            if (vehicleNo) {
                if (pvd) pvd += '   \u00b7   ';
                pvd += 'Vehicle: ' + vehicleNo;
            }
            if (driverName) {
                if (pvd) pvd += '   \u00b7   ';
                pvd += 'Driver: ' + driverName;
            }
            stampLines.push({ text: pvd, scale: 0.78, fitWidth: true });
        }
        var districtName = opts.districtName ? String(opts.districtName).trim() : '';
        var countryName = opts.countryName ? String(opts.countryName).trim() : '';
        var countryFlag = opts.countryFlag ? String(opts.countryFlag).trim() : '';
        if (!countryFlag && opts.countryCode) {
            countryFlag = window.fleetCountryCodeToFlagEmoji(opts.countryCode);
        }
        if (districtName || countryName || countryFlag) {
            var geo = '';
            if (districtName) geo += 'District: ' + districtName;
            if (countryName || countryFlag) {
                if (geo) geo += '   \u00b7   ';
                if (countryFlag) geo += countryFlag + ' ';
                if (countryName) geo += countryName;
            }
            stampLines.push({ text: geo.trim(), scale: 0.82, fitWidth: true });
        }
        var lat = opts.lat;
        var lng = opts.lng;
        var accuracyM = opts.accuracyMeters;
        var latLngText = null;
        if (lat != null && lng != null && !isNaN(lat) && !isNaN(lng)) {
            latLngText = 'Lat ' + Number(lat).toFixed(6) + '\u00b0   Long ' + Number(lng).toFixed(6) + '\u00b0';
        }
        var accText = null;
        if (accuracyM != null && !isNaN(accuracyM) && isFinite(accuracyM)) {
            accText = 'Acc ~' + Math.round(Number(accuracyM)) + ' m';
        }
        if (latLngText && accText) {
            stampLines.push({ text: latLngText + '   \u00b7   ' + accText, scale: 0.8, fitWidth: true });
        } else if (latLngText) {
            stampLines.push({ text: latLngText, scale: 0.82, fitWidth: true });
        } else if (accText) {
            stampLines.push({ text: accText, scale: 0.8, fitWidth: true });
        }
        var maxRows = opts.maxRows != null ? Number(opts.maxRows) : 5;
        if (maxRows > 0 && stampLines.length > maxRows) {
            while (stampLines.length > maxRows) {
                var tail = stampLines.pop();
                var prev = stampLines.pop();
                stampLines.push({
                    text: prev.text + '   \u00b7   ' + tail.text,
                    scale: Math.min(prev.scale, tail.scale),
                    fitWidth: true
                });
            }
        }
        return stampLines;
    };

    /** Bottom-centre GPS stamp for captured photos. opts: line1Prefix, lat, lng, accuracyMeters, sizeScale, vehicleNo, driverName, maxRows, compactHeight. */
    window.pktDrawReadableGpsStamp = function(ctx, w, h, opts) {
        opts = opts || {};
        var sizeScale = (opts.sizeScale != null && Number(opts.sizeScale) > 0) ? Number(opts.sizeScale) : 1;
        var prefix = (opts.line1Prefix != null && opts.line1Prefix !== '') ? String(opts.line1Prefix) : 'GPS+Cam';
        var lat = opts.lat;
        var lng = opts.lng;
        var accuracyM = opts.accuracyMeters;
        var stampLines;
        if (opts.attendanceStamp && typeof window.fleetBuildAttendanceStampLines === 'function') {
            stampLines = window.fleetBuildAttendanceStampLines(opts);
        } else {
        var now = new Date(Date.now() + (typeof _pktOffset !== 'undefined' ? _pktOffset : 0));
        var _od = (typeof pktOverlayDateTimeStrings === 'function')
            ? pktOverlayDateTimeStrings(now)
            : { dateStr: '--', timeStr: '--', dateTimeDisplay: '--' };
        stampLines = [];
        stampLines.push({ text: prefix, scale: 1.0 });
        stampLines.push({ text: _od.dateTimeDisplay || (_od.dateStr + ' ' + _od.timeStr), scale: 0.88 });
        var vehicleNo = opts.vehicleNo ? String(opts.vehicleNo).trim() : '';
        var driverName = opts.driverName ? String(opts.driverName).trim() : '';
        if (vehicleNo || driverName) {
            var vdText = '';
            if (vehicleNo) vdText += 'Vehicle: ' + vehicleNo;
            if (driverName) {
                if (vdText) vdText += '   \u00b7   ';
                vdText += 'Driver: ' + driverName;
            }
            stampLines.push({ text: vdText, scale: 0.72, fitWidth: true });
        }
        var latLngText = null;
        if (lat != null && lng != null && !isNaN(lat) && !isNaN(lng)) {
            latLngText = 'Lat ' + Number(lat).toFixed(6) + '\u00b0   Long ' + Number(lng).toFixed(6) + '\u00b0';
        }
        var accText = null;
        if (accuracyM != null && !isNaN(accuracyM) && isFinite(accuracyM)) {
            accText = 'Acc ~' + Math.round(Number(accuracyM)) + ' m';
        }
        if (latLngText && accText) {
            stampLines.push({ text: latLngText + '   \u00b7   ' + accText, scale: 0.78 });
        } else if (latLngText) {
            stampLines.push({ text: latLngText, scale: 0.82 });
        } else if (accText) {
            stampLines.push({ text: accText, scale: 0.78 });
        }
        var maxRows = opts.maxRows != null ? Number(opts.maxRows) : 0;
        if (maxRows > 0 && stampLines.length > maxRows) {
            while (stampLines.length > maxRows) {
                var tail = stampLines.pop();
                var prev = stampLines.pop();
                stampLines.push({
                    text: prev.text + '   \u00b7   ' + tail.text,
                    scale: Math.min(prev.scale, tail.scale)
                });
            }
        }
        }
        var fullBleed = !!opts.fullBleed;
        var fixedLayout = !!opts.fixedStampLayout;
        var compact = !!opts.compactHeight;
        if (fixedLayout && opts.fitAllStampRows) {
            for (var fxi = 0; fxi < stampLines.length; fxi++) {
                stampLines[fxi].fitWidth = true;
            }
        }
        var padBottom;
        var padSide;
        var innerPadX;
        var innerPadY;
        var lineGap;
        var cornerR;
        var maxBoxW;
        var minFont;
        var maxFont;
        var baseFont;
        var fontFamily = 'system-ui, "Segoe UI", Arial, sans-serif';
        if (fixedLayout) {
            padBottom = opts.padBottom != null ? opts.padBottom : 6;
            padSide = opts.padSide != null ? opts.padSide : 6;
            innerPadX = opts.innerPadX != null ? opts.innerPadX : 14;
            innerPadY = opts.innerPadY != null ? opts.innerPadY : 10;
            lineGap = opts.lineGap != null ? opts.lineGap : 5;
            cornerR = opts.cornerR != null ? opts.cornerR : 10;
            maxBoxW = Math.max(1, w - 2 * padSide);
            baseFont = opts.baseFontPx != null ? Number(opts.baseFontPx) : 28;
            minFont = opts.minFontPx != null ? Number(opts.minFontPx) : 12;
            maxFont = baseFont;
        } else {
            padBottom = fullBleed
                ? (opts.padBottom != null ? opts.padBottom : (compact ? 4 : 6))
                : Math.round(Math.min(32, Math.max(16, h * 0.04)) * sizeScale);
            padSide = fullBleed
                ? (opts.padSide != null ? opts.padSide : (compact ? 6 : 8))
                : Math.round(Math.min(24, Math.max(10, w * 0.028)) * sizeScale);
            innerPadX = Math.round((compact ? 14 : 20) * sizeScale);
            innerPadY = Math.round((compact ? 10 : 16) * sizeScale);
            lineGap = Math.round((compact ? 5 : 8) * sizeScale);
            cornerR = fullBleed ? Math.round(10 * Math.min(sizeScale, 2)) : Math.round(12 * sizeScale);
            maxBoxW = fullBleed ? Math.max(1, w - 2 * padSide) : Math.max(Math.round(160 * sizeScale), w - 2 * padSide);
            var fontDivisor = 20 / sizeScale;
            minFont = Math.round(20 * sizeScale);
            maxFont = Math.round(40 * sizeScale);
            baseFont = Math.max(minFont, Math.min(maxFont, Math.floor(w / fontDivisor)));
        }

        function measureBlock(fs) {
            var maxW = 0;
            for (var i = 0; i < stampLines.length; i++) {
                var fsLine = Math.max(Math.round(14 * sizeScale), Math.round(fs * stampLines[i].scale));
                ctx.font = 'bold ' + fsLine + 'px ' + fontFamily;
                maxW = Math.max(maxW, ctx.measureText(stampLines[i].text).width);
            }
            return maxW + 2 * innerPadX;
        }

        var minShrink = fixedLayout ? minFont : Math.round(14 * sizeScale);
        if (!fixedLayout) {
            while (baseFont > minShrink && measureBlock(baseFont) > maxBoxW) baseFont -= 1;
        }

        var lineHeights = [];
        var totalH = innerPadY * 2;
        for (var j = 0; j < stampLines.length; j++) {
            var fsMin = fixedLayout ? minFont : Math.round(14 * sizeScale);
            var fsJ = Math.max(fsMin, Math.round(baseFont * stampLines[j].scale));
            lineHeights.push(fsJ);
            totalH += fsJ;
            if (j < stampLines.length - 1) totalH += lineGap;
        }
        var boxW = fullBleed ? maxBoxW : Math.min(maxBoxW, Math.ceil(measureBlock(baseFont)));
        var maxTextW = boxW - 2 * innerPadX;
        var minFitFont = fixedLayout ? minFont : Math.round(12 * sizeScale);
        for (var fj = 0; fj < stampLines.length; fj++) {
            if (!stampLines[fj].fitWidth) continue;
            var fsFit = lineHeights[fj];
            ctx.font = 'bold ' + fsFit + 'px ' + fontFamily;
            while (fsFit > minFitFont && ctx.measureText(stampLines[fj].text).width > maxTextW) {
                fsFit -= 1;
                ctx.font = 'bold ' + fsFit + 'px ' + fontFamily;
            }
            if (fsFit !== lineHeights[fj]) {
                totalH -= lineHeights[fj] - fsFit;
                lineHeights[fj] = fsFit;
            }
        }
        var boxH = totalH;
        var x = fullBleed ? padSide : Math.round((w - boxW) / 2);
        var y = Math.round(h - boxH - padBottom);
        /* Semi-transparent panel: photo behind remains visible; text stays readable via outline. */
        ctx.fillStyle = 'rgba(0,0,0,0.55)';
        pktCanvasRoundRect(ctx, x, y, boxW, boxH, cornerR);
        ctx.fill();
        ctx.strokeStyle = 'rgba(255,255,255,0.72)';
        ctx.lineWidth = Math.max(2, Math.round(baseFont / 12));
        pktCanvasRoundRect(ctx, x, y, boxW, boxH, cornerR);
        ctx.stroke();
        ctx.textBaseline = 'top';
        ctx.lineJoin = 'round';
        var cy = y + innerPadY;
        for (var k = 0; k < stampLines.length; k++) {
            ctx.font = 'bold ' + lineHeights[k] + 'px ' + fontFamily;
            var tx = x + innerPadX;
            var outline = Math.max(2, Math.round(lineHeights[k] / 12));
            ctx.strokeStyle = 'rgba(0,0,0,0.88)';
            ctx.lineWidth = outline;
            ctx.strokeText(stampLines[k].text, tx, cy);
            ctx.fillStyle = '#ffffff';
            ctx.fillText(stampLines[k].text, tx, cy);
            cy += lineHeights[k] + (k < stampLines.length - 1 ? lineGap : 0);
        }
    };

    window.fleetJpegDataUrlMaxSide = function(canvas, maxSide, quality) {
        maxSide = maxSide || 1280;
        quality = (quality === undefined || quality === null) ? 0.88 : quality;
        var w = canvas.width;
        var h = canvas.height;
        if (!w || !h) return canvas.toDataURL('image/jpeg', quality);
        if (w <= maxSide && h <= maxSide) return canvas.toDataURL('image/jpeg', quality);
        var scale = maxSide / Math.max(w, h);
        var nw = Math.max(1, Math.round(w * scale));
        var nh = Math.max(1, Math.round(h * scale));
        var tmp = document.createElement('canvas');
        tmp.width = nw;
        tmp.height = nh;
        tmp.getContext('2d').drawImage(canvas, 0, 0, nw, nh);
        return tmp.toDataURL('image/jpeg', quality);
    };

    /** Legacy odometer scale (unused when fleetStampAttendancePhoto + fixed frame is used). */
    window.FLEET_ODOMETER_STAMP_SCALE = 2.5;
    window.FLEET_ATTENDANCE_STAMP_SCALE = 5.5;
    /** Fixed attendance output frame (portrait 3:4). Photo: contain fit, no crop. Stamp: overlay, fixed px font. */
    window.FLEET_ATTENDANCE_FRAME_W = 1080;
    window.FLEET_ATTENDANCE_FRAME_H = 1440;
    window.FLEET_ATTENDANCE_USE_FIXED_FRAME = true;
    window.FLEET_ATTENDANCE_STAMP_BASE_FONT = 44;
    window.FLEET_ATTENDANCE_COUNTRY_NAME = 'Pakistan';
    window.FLEET_ATTENDANCE_COUNTRY_CODE = 'PK';

    /** Average border colour for letterbox fill (avoids black side bars). */
    window.fleetSampleImageBorderColor = function(img, iw, ih) {
        var tmp = document.createElement('canvas');
        tmp.width = iw;
        tmp.height = ih;
        var t = tmp.getContext('2d');
        t.drawImage(img, 0, 0, iw, ih);
        var bands = [
            t.getImageData(0, 0, iw, 1),
            t.getImageData(0, Math.max(0, ih - 1), iw, 1),
            t.getImageData(0, 0, 1, ih),
            t.getImageData(Math.max(0, iw - 1), 0, 1, ih)
        ];
        var r = 0;
        var g = 0;
        var b = 0;
        var n = 0;
        for (var bi = 0; bi < bands.length; bi++) {
            var d = bands[bi].data;
            for (var i = 0; i < d.length; i += 4) {
                r += d[i];
                g += d[i + 1];
                b += d[i + 2];
                n++;
            }
        }
        if (!n) return '#1a1a1a';
        return 'rgb(' + Math.round(r / n) + ',' + Math.round(g / n) + ',' + Math.round(b / n) + ')';
    };

    /**
     * Fit full camera image into fixed frame (contain, no crop). Letterbox uses edge colour, not black bars.
     */
    window.fleetComposeAttendanceFixedFrame = function(dataUrl) {
        return new Promise(function(resolve, reject) {
            if (!dataUrl) {
                reject(new Error('No photo'));
                return;
            }
            var frameW = window.FLEET_ATTENDANCE_FRAME_W || 1080;
            var frameH = window.FLEET_ATTENDANCE_FRAME_H || 1440;
            var img = new Image();
            img.onload = function() {
                var iw = img.naturalWidth || img.width;
                var ih = img.naturalHeight || img.height;
                if (!iw || !ih) {
                    reject(new Error('Invalid image'));
                    return;
                }
                var scale = Math.min(frameW / iw, frameH / ih);
                var dw = Math.max(1, Math.round(iw * scale));
                var dh = Math.max(1, Math.round(ih * scale));
                var dx = Math.round((frameW - dw) / 2);
                var dy = Math.round((frameH - dh) / 2);
                var canvas = document.createElement('canvas');
                canvas.width = frameW;
                canvas.height = frameH;
                var ctx = canvas.getContext('2d');
                ctx.fillStyle = window.fleetSampleImageBorderColor(img, iw, ih);
                ctx.fillRect(0, 0, frameW, frameH);
                ctx.drawImage(img, dx, dy, dw, dh);
                resolve(canvas);
            };
            img.onerror = function() { reject(new Error('Image load failed')); };
            img.src = dataUrl;
        });
    };

    /** Drop "(Type)" suffix from vehicle/driver select option text. */
    window.fleetStripSelectOptionLabel = function(label) {
        var s = String(label || '').trim();
        var paren = s.indexOf('(');
        if (paren > 0) s = s.slice(0, paren).trim();
        return s;
    };

    /** Project, district, vehicle, driver, country for attendance stamp (check-in/out pages). */
    window.fleetGetAttendanceStampContext = function() {
        var strip = (typeof window.fleetStripSelectOptionLabel === 'function')
            ? window.fleetStripSelectOptionLabel
            : function(l) { return String(l || '').trim(); };
        var projectName = '';
        var districtName = '';
        var vehicleNo = '';
        var driverName = '';
        var pSel = document.getElementById('projectSelect');
        var dSelDist = document.getElementById('districtSelect');
        var vSel = document.getElementById('vehicleSelect');
        var dSel = document.getElementById('driverSelect');
        if (pSel && pSel.selectedIndex >= 0) {
            var pOpt = pSel.options[pSel.selectedIndex];
            if (pOpt && pOpt.value) projectName = strip(pOpt.textContent);
        }
        if (dSelDist && dSelDist.selectedIndex >= 0) {
            var distOpt = dSelDist.options[dSelDist.selectedIndex];
            if (distOpt && distOpt.value) districtName = strip(distOpt.textContent);
        }
        if (vSel && vSel.selectedIndex >= 0) {
            var vOpt = vSel.options[vSel.selectedIndex];
            if (vOpt && vOpt.value) vehicleNo = strip(vOpt.textContent);
        }
        if (dSel && dSel.selectedIndex >= 0) {
            var dOpt = dSel.options[dSel.selectedIndex];
            if (dOpt && dOpt.value) driverName = strip(dOpt.textContent);
        }
        var countryName = window.FLEET_ATTENDANCE_COUNTRY_NAME || 'Pakistan';
        var countryCode = window.FLEET_ATTENDANCE_COUNTRY_CODE || 'PK';
        return {
            projectName: projectName,
            districtName: districtName,
            vehicleNo: vehicleNo,
            driverName: driverName,
            countryName: countryName,
            countryCode: countryCode,
            countryFlag: window.fleetCountryCodeToFlagEmoji(countryCode)
        };
    };

    /** @deprecated use fleetGetAttendanceStampContext */
    window.fleetGetAttendanceStampVehicleDriver = function() {
        var c = window.fleetGetAttendanceStampContext();
        return { vehicleNo: c.vehicleNo, driverName: c.driverName };
    };

    /** Project / district / vehicle for Odoo meter stamp on New Task Entry (same rows as check-out stamp). */
    window.fleetGetOdometerStampContext = function(rowId) {
        var strip = (typeof window.fleetStripSelectOptionLabel === 'function')
            ? window.fleetStripSelectOptionLabel
            : function(l) { return String(l || '').trim(); };
        var projectName = '';
        var districtName = '';
        var vehicleNo = '';
        var pSel = document.getElementById('projectSelect');
        var pLock = document.getElementById('projectSelectLocked');
        if (pLock && pLock.textContent) {
            projectName = strip(pLock.textContent);
        } else if (pSel && pSel.selectedIndex >= 0) {
            var pOpt = pSel.options[pSel.selectedIndex];
            if (pOpt && pOpt.value && pOpt.value !== '0') projectName = strip(pOpt.textContent);
        }
        var dSel = document.getElementById('districtSelect');
        var dLock = document.getElementById('districtSelectLocked');
        if (dLock && dLock.textContent) {
            districtName = strip(dLock.textContent);
        } else if (dSel && dSel.selectedIndex >= 0) {
            var dOpt = dSel.options[dSel.selectedIndex];
            if (dOpt && dOpt.value && dOpt.value !== '0') districtName = strip(dOpt.textContent);
        }
        if (rowId != null && rowId !== '') {
            var tr = document.querySelector('.task-row[data-vehicle-id="' + rowId + '"]');
            if (tr) {
                vehicleNo = strip(tr.getAttribute('data-vehicle') || '');
                if (!districtName) districtName = strip(tr.getAttribute('data-district') || '');
            }
        }
        var countryName = window.FLEET_ATTENDANCE_COUNTRY_NAME || 'Pakistan';
        var countryCode = window.FLEET_ATTENDANCE_COUNTRY_CODE || 'PK';
        return {
            projectName: projectName,
            districtName: districtName,
            vehicleNo: vehicleNo,
            driverName: '',
            countryName: countryName,
            countryCode: countryCode,
            countryFlag: window.fleetCountryCodeToFlagEmoji(countryCode)
        };
    };
    /** false = system camera (production). true = in-app CameraPreview (see docs/archive/). */
    window.FLEET_ATTENDANCE_USE_INAPP_PREVIEW = false;
    window.FLEET_ATTENDANCE_CAPTURE_MAX_SIDE = 2048;
    window.FLEET_ATTENDANCE_CAPTURE_QUALITY = 0.92;

    /** Read JPEG EXIF orientation (1–8). Returns 1 if missing. */
    window.fleetReadJpegExifOrientation = function(dataUrl) {
        try {
            var b64 = dataUrl.indexOf(',') >= 0 ? dataUrl.split(',')[1] : dataUrl;
            var bin = atob(b64);
            var len = Math.min(bin.length, 65536);
            var dv = new DataView(new ArrayBuffer(len));
            for (var i = 0; i < len; i++) dv.setUint8(i, bin.charCodeAt(i));
            if (len < 4 || dv.getUint8(0) !== 0xFF || dv.getUint8(1) !== 0xD8) return 1;
            var off = 2;
            while (off + 4 < len) {
                if (dv.getUint8(off) !== 0xFF) break;
                var marker = dv.getUint8(off + 1);
                if (marker === 0xD8 || marker === 0xD9) break;
                var segLen = dv.getUint16(off + 2, false);
                if (marker === 0xE1 && off + 10 < len) {
                    if (dv.getUint32(off + 4, false) === 0x45786966) {
                        var tiff = off + 10;
                        var le = dv.getUint16(tiff, false) === 0x4949;
                        var ifd = tiff + dv.getUint32(tiff + 4, !le);
                        var entries = dv.getUint16(ifd, !le);
                        for (var e = 0; e < entries; e++) {
                            var ent = ifd + 2 + e * 12;
                            if (dv.getUint16(ent, !le) === 0x0112) {
                                return dv.getUint16(ent + 8, !le) || 1;
                            }
                        }
                    }
                }
                off += 2 + segLen;
            }
        } catch (e) { /* ignore */ }
        return 1;
    };

    window.fleetRotateDataUrl = function(dataUrl, degrees) {
        return new Promise(function(resolve, reject) {
            if (!degrees || degrees % 360 === 0) {
                resolve(dataUrl);
                return;
            }
            var img = new Image();
            img.onload = function() {
                var w = img.naturalWidth || img.width;
                var h = img.naturalHeight || img.height;
                if (!w || !h) {
                    reject(new Error('Invalid image'));
                    return;
                }
                var rad = degrees * Math.PI / 180;
                var swap = (degrees === 90 || degrees === 270);
                var canvas = document.createElement('canvas');
                canvas.width = swap ? h : w;
                canvas.height = swap ? w : h;
                var ctx = canvas.getContext('2d');
                ctx.translate(canvas.width / 2, canvas.height / 2);
                ctx.rotate(rad);
                ctx.drawImage(img, -w / 2, -h / 2, w, h);
                resolve(canvas.toDataURL('image/jpeg', 0.95));
            };
            img.onerror = function() { reject(new Error('Image load failed')); };
            img.src = dataUrl;
        });
    };

    /** EXIF orientation tag → clockwise correction degrees (canvas), or 0 if none. */
    window.fleetExifToRotationDegrees = function(exif) {
        if (exif === 3) return 180;
        if (exif === 6) return 90;
        if (exif === 8) return 270;
        return 0;
    };

    /** Close Tom Select menus and block body dropdowns while attendance modal is open. */
    window.fleetSetAttendanceModalOpen = function(open) {
        document.body.classList.toggle('fleet-attnd-modal-open', !!open);
        if (!open) return;
        document.querySelectorAll('body > .ts-dropdown').forEach(function(el) {
            el.style.display = 'none';
        });
        document.querySelectorAll('.gps-attendance-page select.search-select').forEach(function(sel) {
            if (sel.tomselect && typeof sel.tomselect.close === 'function') {
                try { sel.tomselect.close(); } catch (e) { /* ignore */ }
            }
        });
    };

    /** Toggle full-screen camera chrome (hide app shell; show only #cameraModal). */
    window.fleetSetAttendanceCameraChrome = function(active) {
        document.documentElement.classList.toggle('fleet-attnd-camera-active', !!active);
        document.body.classList.toggle('fleet-attnd-camera-active', !!active);
        document.querySelectorAll('body > .ts-dropdown').forEach(function(el) {
            el.style.display = active ? 'none' : '';
        });
    };

    /**
     * Portrait selfie orientation.
     * fromCameraPreview: live preview is already upright — only apply EXIF correction (never blind 180°).
     * Other sources: EXIF + 90° when landscape buffer on portrait phone.
     */
    window.fleetNormalizeSelfieOrientation = function(dataUrl, opts) {
        opts = opts || {};
        return new Promise(function(resolve, reject) {
            if (!dataUrl) {
                reject(new Error('No photo'));
                return;
            }
            var exif = window.fleetReadJpegExifOrientation(dataUrl);
            var deg = window.fleetExifToRotationDegrees(exif);
            if (opts.fromCameraPreview) {
                if (deg === 0) {
                    resolve(dataUrl);
                    return;
                }
                window.fleetRotateDataUrl(dataUrl, deg).then(resolve).catch(reject);
                return;
            }
            var hadExifRotate = deg !== 0;
            var afterExif = hadExifRotate
                ? window.fleetRotateDataUrl(dataUrl, deg)
                : Promise.resolve(dataUrl);
            afterExif.then(function(url) {
                var img = new Image();
                img.onload = function() {
                    var w = img.naturalWidth || img.width;
                    var h = img.naturalHeight || img.height;
                    if (!w || !h) {
                        reject(new Error('Invalid image'));
                        return;
                    }
                    var portraitScreen = (window.innerHeight || 0) >= (window.innerWidth || 0);
                    if (!opts.rearCamera && !hadExifRotate && portraitScreen && w > h) {
                        window.fleetRotateDataUrl(url, 90).then(resolve).catch(reject);
                        return;
                    }
                    resolve(url);
                };
                img.onerror = function() { reject(new Error('Image load failed')); };
                img.src = url;
            }).catch(reject);
        });
    };

    window.fleetPreviewViewportRect = function(viewportEl) {
        var rect = viewportEl.getBoundingClientRect();
        var vv = window.visualViewport;
        var top = rect.top + (vv ? vv.offsetTop : 0);
        var left = rect.left + (vv ? vv.offsetLeft : 0);
        return {
            x: Math.max(0, Math.round(left)),
            y: Math.max(0, Math.round(top)),
            width: Math.max(1, Math.round(rect.width)),
            height: Math.max(1, Math.round(rect.height))
        };
    };

    /** Stamp GPS overlay on a photo from native camera; returns { dataUrl, timeStr }. */
    window.fleetStampAttendancePhoto = function(dataUrl, canvasEl, stampOpts) {
        stampOpts = stampOpts || {};
        var stampScale = (stampOpts.sizeScale != null && Number(stampOpts.sizeScale) > 0)
            ? Number(stampOpts.sizeScale)
            : (window.FLEET_ATTENDANCE_STAMP_SCALE || 1);
        var maxSide = stampOpts.maxSide || window.FLEET_ATTENDANCE_CAPTURE_MAX_SIDE || 2048;
        var quality = stampOpts.quality != null ? stampOpts.quality : (window.FLEET_ATTENDANCE_CAPTURE_QUALITY || 0.92);
        var orientOpts = stampOpts.fromCameraPreview ? { fromCameraPreview: true } : {};
        if (stampOpts.rearCamera) orientOpts.rearCamera = true;
        var useFixedFrame = stampOpts.useFixedFrame != null
            ? !!stampOpts.useFixedFrame
            : (window.FLEET_ATTENDANCE_USE_FIXED_FRAME !== false);
        return window.fleetNormalizeSelfieOrientation(dataUrl, orientOpts).then(function(uprightUrl) {
            var framedP = (useFixedFrame && typeof window.fleetComposeAttendanceFixedFrame === 'function')
                ? window.fleetComposeAttendanceFixedFrame(uprightUrl)
                : new Promise(function(resolve, reject) {
                    if (!uprightUrl) {
                        reject(new Error('No photo'));
                        return;
                    }
                    var img = new Image();
                    img.onload = function() {
                        var w = img.naturalWidth || img.width;
                        var h = img.naturalHeight || img.height;
                        if (!w || !h) {
                            reject(new Error('Invalid image'));
                            return;
                        }
                        var canvas = document.createElement('canvas');
                        canvas.width = w;
                        canvas.height = h;
                        canvas.getContext('2d').drawImage(img, 0, 0, w, h);
                        resolve(canvas);
                    };
                    img.onerror = function() { reject(new Error('Image load failed')); };
                    img.src = uprightUrl;
                });
            return framedP.then(function(framedCanvas) {
                return new Promise(function(resolve, reject) {
                    if (!framedCanvas || !framedCanvas.width || !framedCanvas.height) {
                        reject(new Error('Invalid image'));
                        return;
                    }
                    var canvas = canvasEl || framedCanvas;
                    if (canvasEl && canvasEl !== framedCanvas) {
                        canvas.width = framedCanvas.width;
                        canvas.height = framedCanvas.height;
                        canvas.getContext('2d').drawImage(framedCanvas, 0, 0);
                    }
                    var w = canvas.width;
                    var h = canvas.height;
                    var ctx = canvas.getContext('2d');
                    if (typeof window.pktDrawReadableGpsStamp === 'function') {
                        var stampDrawOpts = {
                            line1Prefix: stampOpts.line1Prefix || 'GPS+Cam',
                            lat: stampOpts.lat,
                            lng: stampOpts.lng,
                            accuracyMeters: stampOpts.accuracyMeters,
                            projectName: stampOpts.projectName,
                            districtName: stampOpts.districtName,
                            countryName: stampOpts.countryName,
                            countryCode: stampOpts.countryCode,
                            countryFlag: stampOpts.countryFlag,
                            vehicleNo: stampOpts.vehicleNo,
                            driverName: stampOpts.driverName,
                            attendanceStamp: true,
                            maxRows: 5,
                            fullBleed: true,
                            compactHeight: true,
                            padBottom: 8,
                            padSide: 6
                        };
                        if (useFixedFrame) {
                            stampDrawOpts.fixedStampLayout = true;
                            stampDrawOpts.fitAllStampRows = true;
                            stampDrawOpts.baseFontPx = window.FLEET_ATTENDANCE_STAMP_BASE_FONT || 44;
                            stampDrawOpts.innerPadX = 16;
                            stampDrawOpts.innerPadY = 12;
                            stampDrawOpts.lineGap = 6;
                            stampDrawOpts.minFontPx = 14;
                        } else {
                            stampDrawOpts.sizeScale = stampScale;
                            stampDrawOpts.padBottom = 4;
                        }
                        window.pktDrawReadableGpsStamp(ctx, w, h, stampDrawOpts);
                    }
                    var nowCap = new Date(Date.now() + (typeof _pktOffset !== 'undefined' ? _pktOffset : 0));
                    var _odCap = (typeof pktOverlayDateTimeStrings === 'function')
                        ? pktOverlayDateTimeStrings(nowCap)
                        : { timeStr: nowCap.getHours().toString().padStart(2, '0') + ':' + nowCap.getMinutes().toString().padStart(2, '0') + ':' + nowCap.getSeconds().toString().padStart(2, '0') };
                    resolve({
                        dataUrl: window.fleetJpegDataUrlMaxSide(canvas, maxSide, quality),
                        timeStr: _odCap.timeStr
                    });
                });
            });
        });
    };

    window.fleetGetCameraPreviewPlugin = function() {
        if (!window.Capacitor || !window.Capacitor.Plugins) return null;
        return window.Capacitor.Plugins.CameraPreview || null;
    };

    window.fleetIsNativeAndroid = function() {
        return !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform()
            && /android/i.test(navigator.userAgent || ''));
    };

    window._fleetAttendancePreviewActive = false;
    window._fleetAttendancePreviewTimer = null;

    window.fleetFormatLiveGpsStampHtml = function(stampOpts) {
        stampOpts = stampOpts || {};
        var rows;
        if (typeof window.fleetBuildAttendanceStampLines === 'function') {
            var buildOpts = {
                line1Prefix: stampOpts.line1Prefix || 'GPS+Cam',
                lat: stampOpts.lat,
                lng: stampOpts.lng,
                accuracyMeters: stampOpts.accuracyMeters,
                projectName: stampOpts.projectName,
                districtName: stampOpts.districtName,
                countryName: stampOpts.countryName,
                countryCode: stampOpts.countryCode,
                countryFlag: stampOpts.countryFlag,
                vehicleNo: stampOpts.vehicleNo,
                driverName: stampOpts.driverName,
                maxRows: 5
            };
            rows = window.fleetBuildAttendanceStampLines(buildOpts);
        } else {
            rows = [{ text: stampOpts.line1Prefix || 'GPS+Cam' }];
        }
        return rows.map(function(row) {
            return '<div class="fleet-live-gps-line">' + String(row.text).replace(/&/g, '&amp;').replace(/</g, '&lt;') + '</div>';
        }).join('');
    };

    window.fleetStopAttendancePreview = function() {
        if (window._fleetAttendancePreviewTimer) {
            clearInterval(window._fleetAttendancePreviewTimer);
            window._fleetAttendancePreviewTimer = null;
        }
        window.fleetSetAttendanceCameraChrome(false);
        var cp = window.fleetGetCameraPreviewPlugin();
        var stopP = Promise.resolve();
        if (cp && window._fleetAttendancePreviewActive && typeof cp.stop === 'function') {
            stopP = cp.stop().catch(function() {});
        }
        window._fleetAttendancePreviewActive = false;
        return stopP;
    };

    window.fleetStartAttendancePreview = function(viewportEl, liveStampEl, stampOpts, isRetry) {
        var cp = window.fleetGetCameraPreviewPlugin();
        if (!cp || !window.fleetIsNativeAndroid() || !viewportEl) {
            return Promise.reject(new Error('NO_PREVIEW'));
        }
        return window.fleetStopAttendancePreview().then(function() {
            var r = window.fleetPreviewViewportRect(viewportEl);
            if ((r.width < 80 || r.height < 120) && !isRetry) {
                return new Promise(function(res, rej) {
                    window.setTimeout(function() {
                        window.fleetStartAttendancePreview(viewportEl, liveStampEl, stampOpts, true).then(res).catch(rej);
                    }, 450);
                });
            }
            window.fleetSetAttendanceCameraChrome(true);
            return cp.start({
                position: 'front',
                x: r.x,
                y: r.y,
                width: r.width,
                height: r.height,
                toBack: true,
                disableAudio: true,
                enableZoom: false,
                lockAndroidOrientation: true,
                disableExifHeaderStripping: true
            }).then(function() {
                if (typeof cp.setOpacity === 'function') {
                    try { cp.setOpacity({ opacity: 1 }); } catch (e) { /* optional */ }
                }
                window._fleetAttendancePreviewActive = true;
            }).catch(function(err) {
                window.fleetSetAttendanceCameraChrome(false);
                throw err;
            });
        });
    };

    /** Stop preview, pause, then restart (retake / retry without re-opening modal). */
    window.fleetRestartAttendancePreview = function(viewportEl, stampOpts) {
        return window.fleetStopAttendancePreview().then(function() {
            return new Promise(function(resolve) {
                window.setTimeout(resolve, 300);
            });
        }).then(function() {
            return window.fleetStartAttendancePreview(viewportEl, null, stampOpts);
        });
    };

    window.fleetCaptureAttendancePreviewPhoto = function() {
        var cp = window.fleetGetCameraPreviewPlugin();
        if (!cp || !window._fleetAttendancePreviewActive) {
            return Promise.reject(new Error('Preview not started'));
        }
        return cp.capture({ quality: 95 }).then(function(res) {
            return window.fleetStopAttendancePreview().then(function() {
                if (!res || !res.value) throw new Error('No photo captured');
                var b64 = res.value;
                if (b64.indexOf('data:') !== 0) b64 = 'data:image/jpeg;base64,' + b64;
                return b64;
            });
        });
    };

    window.fleetTakeCameraXFrontPhoto = function(stampOpts) {
        stampOpts = stampOpts || {};
        var frontPlg = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.AttendanceFrontCamera;
        if (!frontPlg || typeof frontPlg.capture !== 'function') {
            return Promise.reject(new Error('Camera not available'));
        }
        var opts = {};
        if (stampOpts.line1Prefix) opts.line1Prefix = stampOpts.line1Prefix;
        if (stampOpts.lat != null) opts.lat = stampOpts.lat;
        if (stampOpts.lng != null) opts.lng = stampOpts.lng;
        if (stampOpts.accuracyMeters != null) opts.accuracyMeters = stampOpts.accuracyMeters;
        return frontPlg.capture(opts).then(function(res) {
            if (!res || !res.base64) throw new Error('No photo captured');
            var b64 = res.base64;
            if (b64.indexOf('data:') !== 0) b64 = 'data:image/jpeg;base64,' + b64;
            return window.fleetNormalizeSelfieOrientation(b64);
        });
    };

    /**
     * System camera only — no gallery. Uses Capacitor Camera (FRONT, saveToGallery: false).
     * Requires FleetBridge (loaded after this script block on native).
     */
    window.fleetTakeSystemCameraPhoto = function(quality) {
        if (window.FleetBridge && typeof window.FleetBridge.takeSelfie === 'function') {
            var q = (quality != null && quality >= 1 && quality <= 100)
                ? quality
                : Math.round((window.FLEET_ATTENDANCE_CAPTURE_QUALITY || 0.92) * 100);
            return window.FleetBridge.takeSelfie({ quality: q });
        }
        var Cam = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Camera;
        if (!Cam || typeof Cam.getPhoto !== 'function') {
            return Promise.reject(new Error('Camera not available'));
        }
        var q2 = (quality != null && quality >= 1 && quality <= 100)
            ? quality
            : Math.round((window.FLEET_ATTENDANCE_CAPTURE_QUALITY || 0.92) * 100);
        return Cam.getPhoto({
            quality: q2,
            allowEditing: false,
            resultType: 'base64',
            source: 'CAMERA',
            direction: 'FRONT',
            saveToGallery: false
        }).then(function(photo) {
            if (!photo || !photo.base64String) throw new Error('No photo captured');
            return 'data:image/jpeg;base64,' + photo.base64String;
        });
    };

    /** Front capture: system camera (default) or archived in-app preview when FLEET_ATTENDANCE_USE_INAPP_PREVIEW. */
    window.fleetTakeNativeFrontPhoto = function(stampOpts) {
        stampOpts = stampOpts || {};
        if (window.FLEET_ATTENDANCE_USE_INAPP_PREVIEW) {
            if (window.fleetIsNativeAndroid()) {
                return window.fleetTakeCameraXFrontPhoto(stampOpts);
            }
            if (window.FleetBridge && typeof window.FleetBridge.takeAttendanceSelfie === 'function') {
                return window.FleetBridge.takeAttendanceSelfie();
            }
            return Promise.reject(new Error('Camera not available'));
        }
        return window.fleetTakeSystemCameraPhoto();
    };

    window.fleetIsCameraCancelled = function(err) {
        if (!err) return true;
        if (err.code === 'cancelled') return true;
        var msg = (err.message || String(err)).toLowerCase();
        return msg.indexOf('cancel') >= 0 || msg.indexOf('no image') >= 0 || msg.indexOf('no file') >= 0 || msg.indexOf('user denied') >= 0;
    };

    // Live connection status + network speed (left of navbar, after logo)
    (function() {
        var _netTimer = null;
        function _signalLevel(mbps, rttMs) {
            if (mbps >= 6 && rttMs <= 120) return 4;
            if (mbps >= 3 && rttMs <= 220) return 3;
            if (mbps >= 1 && rttMs <= 450) return 2;
            if (mbps > 0) return 1;
            return 0;
        }
        function _connState(mbps, rttMs, online) {
            if (!online) return 'offline';
            var level = _signalLevel(mbps, rttMs);
            if (level <= 1 || mbps < 0.85 || rttMs > 520) return 'slow';
            return 'online';
        }
        function _updateConnStatus(state) {
            var pill = document.getElementById('liveConnStatus');
            var icon = document.getElementById('liveConnStatusIcon');
            var text = document.getElementById('liveConnStatusText');
            if (!pill) return;
            pill.setAttribute('data-state', state);
            var map = {
                online: { icon: 'bi-wifi', label: 'Online' },
                offline: { icon: 'bi-wifi-off', label: 'Offline' },
                slow: { icon: 'bi-exclamation-triangle', label: 'Network slow' },
                checking: { icon: 'bi-arrow-repeat', label: 'Checking' }
            };
            var cfg = map[state] || map.checking;
            if (icon) icon.className = 'bi ' + cfg.icon;
            if (text) text.textContent = cfg.label;
        }
        function _updateNetUI(mbps, rttMs, online) {
            var icon = document.getElementById('liveNetworkSignalIcon');
            var speedEl = document.getElementById('liveNetworkSpeedText');
            var level = online ? _signalLevel(mbps, rttMs) : 0;
            if (icon) {
                icon.className = 'bi bi-reception-' + level;
                icon.classList.remove('text-success', 'text-warning', 'text-danger', 'text-secondary');
                icon.classList.add(
                    !online ? 'text-danger' :
                    (level >= 3 ? 'text-success' : (level === 2 ? 'text-warning' : 'text-danger'))
                );
            }
            if (speedEl) {
                if (!online) {
                    speedEl.textContent = 'No connection';
                } else {
                    var rttLabel = isFinite(rttMs) ? (' · ' + Math.round(rttMs) + 'ms') : '';
                    speedEl.textContent = (isFinite(mbps) ? mbps.toFixed(2) : '--') + ' Mbps' + rttLabel;
                }
            }
            _updateConnStatus(_connState(mbps, rttMs, online));
        }
        function _sampleNetwork() {
            if (!navigator.onLine) {
                _updateNetUI(0, 999, false);
                return;
            }
            var start = performance.now();
            fetch('/network-probe?kb=24&t=' + Date.now(), { cache: 'no-store' })
                .then(function(r) {
                    if (!r.ok) throw new Error('probe failed');
                    return r.text();
                })
                .then(function(txt) {
                    var elapsedSec = Math.max((performance.now() - start) / 1000, 0.001);
                    var bytes = (txt || '').length;
                    var mbps = (bytes * 8) / (elapsedSec * 1000 * 1000);
                    var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
                    var rtt = (conn && conn.rtt) ? conn.rtt : (performance.now() - start);
                    _updateNetUI(mbps, rtt, true);
                })
                .catch(function() {
                    _updateNetUI(0, 999, false);
                });
        }
        function _startNetworkTicker() {
            if (!document.getElementById('liveNetworkHealth')) return;
            _updateConnStatus('checking');
            _sampleNetwork();
            if (_netTimer) clearInterval(_netTimer);
            _netTimer = setInterval(_sampleNetwork, 12000);
        }
        window.addEventListener('online', function() {
            _updateConnStatus('checking');
            _sampleNetwork();
        });
        window.addEventListener('offline', function() {
            _updateNetUI(0, 999, false);
        });
        document.addEventListener('DOMContentLoaded', _startNetworkTicker);
        if (document.readyState !== 'loading') _startNetworkTicker();
    })();

    // Auto-close Alerts (sirf flash-message ke andar wale alerts)
    setTimeout(function() {
        $(".flash-message .alert").fadeOut('slow');
    }, 5000);

    // Backend search auto-submit (for forms with class="auto-search-form")
    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('form.auto-search-form input[name="search"]').forEach(function (input) {
            var timer;
            input.addEventListener('input', function () {
                clearTimeout(timer);
                var form = input.form;
                if (!form) return;
                timer = setTimeout(function () {
                    // Only trigger when user stopped typing for a bit
                    // and either search has at least 2 chars or is fully cleared.
                    var val = (input.value || '').trim();
                    if (val.length === 1) return;

                    // reset page to 1 on new search
                    var pageField = form.querySelector('input[name="page"]');
                    if (!pageField) {
                        pageField = document.createElement('input');
                        pageField.type = 'hidden';
                        pageField.name = 'page';
                        form.appendChild(pageField);
                    }
                    pageField.value = '1';
                    form.submit();
                }, 500); // 0.5s debounce
            });
        });
        // Always keep initial focus on the first search box
        var firstSearch = document.querySelector('form.auto-search-form input[name=\"search\"]');
        if (firstSearch) {
            firstSearch.focus();
            // Move caret to end of existing text
            var val = firstSearch.value;
            firstSearch.setSelectionRange(val.length, val.length);
        }
    });

    function _fleetEnterTabSkip(el) {
        return !!(el && el.classList && el.classList.contains('fleet-enter-skip'));
    }

    function _fleetNextEnterFocus(all, idx) {
        for (var i = idx + 1; i < all.length; i++) {
            if (_fleetEnterTabSkip(all[i])) continue;
            return all[i];
        }
        return null;
    }

    function _fleetFocusField(el) {
        if (!el) return;
        if (el.tagName === 'SELECT' && el.tomselect) {
            el.tomselect.focus();
            return;
        }
        el.focus();
        if (el.tagName !== 'BUTTON' && typeof el.select === 'function') {
            try { el.select(); } catch(x) {}
        }
    }

    // ── kickFocusToNext: document-wide focus-jump utility ──────────────────
    // Searches the ENTIRE document (not just the parent form) so it works
    // regardless of how fields are nested. Only truly visible elements are
    // considered (offsetParent !== null).
    function kickFocusToNext(currentEl) {
        var all = Array.from(document.querySelectorAll(
            'input:not([type="hidden"]):not([disabled]):not([readonly]), ' +
            'select:not([disabled]), ' +
            'textarea:not([disabled]):not([readonly]), ' +
            'button[type="submit"], ' +
            '[tabindex]:not([tabindex="-1"])'
        )).filter(function(f) {
            if (f.tabIndex < 0) return false;
            return f.offsetParent !== null;
        });
        var idx = all.indexOf(currentEl);
        if (idx < 0) return;
        var next = _fleetNextEnterFocus(all, idx);
        if (!next) return;
        _fleetFocusField(next);
    }

    // ── Tom Select: Global Searchable Dropdowns ────────────────────────────
    // Defined at global script scope (NOT inside jQuery ready) so the function
    // is available immediately — the content block fields are already in
    // the DOM here because the content block renders above the scripts.
    function _tsMoveFocus(origSelect) {
        var form = origSelect.closest('form');
        if (!form) return;
        var all = Array.from(form.querySelectorAll(
            'input:not([type="hidden"]):not([disabled]):not([readonly]), ' +
            'select:not([disabled]), ' +
            'textarea:not([disabled]):not([readonly]), ' +
            'button[type="submit"]'
        ));
        // Build focusable list: TS-managed selects included by .tomselect check,
        // everything else must be visible in layout (offsetParent !== null)
        var focusable = all.filter(function(f) {
            if (f.tagName === 'SELECT' && f.tomselect) return true;
            return f.offsetParent !== null;
        });
        var idx = focusable.indexOf(origSelect);
        if (idx < 0) return;
        // Walk forward to find the next truly visible/focusable candidate
        for (var i = idx + 1; i < focusable.length; i++) {
            var candidate = focusable[i];
            if (candidate.tagName === 'SELECT' && candidate.tomselect) {
                // Let TS handle opening via its own focus listener
                setTimeout(function(n) { n.tomselect.focus(); }, 30, candidate);
                return;
            }
            if (candidate.offsetParent !== null) {
                candidate.focus();
                return;
            }
        }
    }

    function _emptyStateHTML(labelHTML) {
        return '<div class="ts-empty-state">' +
            '<span class="ts-empty-icon"><i class="bi bi-info-circle"></i></span>' +
            '<span class="ts-empty-label">' + labelHTML + '</span>' +
            '<span class="ts-empty-hint">Try a different filter or check your selection</span>' +
            '</div>';
    }

    /** Viewport-fixed Tom Select placement (works when #mainContent scrolls, not window). */
    window.fleetPositionTomSelectDropdown = function(ts) {
        if (!ts || !ts.control || !ts.dropdown) return;
        var control = ts.control;
        var dropdown = ts.dropdown;
        var content = ts.dropdown_content;
        var rect = control.getBoundingClientRect();
        if (!rect.width && !rect.height) return;

        var vv = window.visualViewport;
        var vpTop = (vv && vv.offsetTop) || 0;
        var vpLeft = (vv && vv.offsetLeft) || 0;
        var vpHeight = (vv && vv.height) || window.innerHeight;
        var vpWidth = (vv && vv.width) || window.innerWidth;
        var gap = 4;
        var edge = 8;
        var prefMax = 240;

        var width = Math.max(rect.width, 160);
        var left = rect.left;
        if (left + width > vpLeft + vpWidth - edge) {
            left = Math.max(vpLeft + edge, vpLeft + vpWidth - width - edge);
        }
        if (left < vpLeft + edge) left = vpLeft + edge;

        var spaceBelow = vpTop + vpHeight - rect.bottom - edge;
        var spaceAbove = rect.top - vpTop - edge;
        var openBelow = spaceBelow >= 100 || spaceBelow >= spaceAbove;

        dropdown.style.position = 'fixed';
        dropdown.style.left = left + 'px';
        dropdown.style.width = width + 'px';
        dropdown.style.margin = '0';
        dropdown.style.right = 'auto';
        dropdown.style.bottom = 'auto';

        if (openBelow) {
            var maxBelow = Math.min(prefMax, Math.max(72, spaceBelow - gap));
            if (content) content.style.maxHeight = maxBelow + 'px';
            dropdown.style.top = (rect.bottom + gap) + 'px';
            return;
        }

        var maxAbove = Math.min(prefMax, Math.max(72, spaceAbove - gap));
        if (content) content.style.maxHeight = maxAbove + 'px';
        dropdown.style.visibility = 'hidden';
        dropdown.style.display = 'block';
        var dropdownHeight = dropdown.offsetHeight || maxAbove;
        var top = rect.top - gap - dropdownHeight;
        if (top < vpTop + edge) top = vpTop + edge;
        if (top + dropdownHeight > rect.top - gap) {
            top = Math.max(vpTop + edge, rect.top - gap - dropdownHeight);
        }
        dropdown.style.top = top + 'px';
        dropdown.style.visibility = '';
    };

    window.initSearchableDropdowns = function(scope) {
        if (typeof TomSelect === 'undefined') return;
        var root = scope || document;
        var selector = 'select.search-select, select.tom-select, .tom-select';
        root.querySelectorAll(selector).forEach(function(el) {
            if (el.tomselect) return;
            if (el.tagName && el.tagName.toLowerCase() !== 'select') return;
            try {
                // ── Detect placeholder option ─────────────────────────────────
                // Treat the first option as a placeholder if its value is '' or
                // '0' (WTForms integer-coerced fields) AND its text looks like a
                // prompt (starts with '--', 'Select', 'All', 'Choose', 'No ').
                var phValue = null;
                var placeholder = 'Select...';
                var _removeFromList = false; // true only for pure prompts, not filter 'All...' options
                if (el.options.length > 0) {
                    var _fo  = el.options[0];
                    var _fv  = _fo.value;
                    var _ft  = (_fo.text || '').trim();
                    if ((_fv === '' || _fv === '0') &&
                        /^(--|select|all[\s(]|choose|pick|no\s)/i.test(_ft)) {
                        placeholder = _ft.replace(/^[-\s]+/, '').replace(/[-\s]+$/, '').trim() || 'Select...';
                        phValue = _fv;
                        // 'All Projects', 'All Districts' etc. are valid filter resets —
                        // keep them in the dropdown list so the user can click them.
                        // Only remove pure prompt options ('-- Select --', 'Select...') 
                        // that contain no 'All' word.
                        _removeFromList = !/\ball\b/i.test(_ft);
                    }
                }

                // Capture whether this field has no real selection BEFORE TomSelect
                // mutates el.value (it may auto-select the first non-empty option
                // when allowEmptyOption:false is set).
                var _hadNoValue = !el.value || el.value === '' || el.value === '0';

                // ── Smart "No Results" field-name detection ─────────────────────
                var _emptyLabel = (function() {
                    var raw = '';
                    // 1. Explicit <label for="id">
                    if (el.id) {
                        var lbl = document.querySelector('label[for="' + el.id + '"]');
                        if (lbl) raw = lbl.textContent;
                    }
                    // 2. Nearest .step-label, label, or legend in parent containers
                    if (!raw && el.closest) {
                        var wrap = el.closest('.col-md-6,.col-md-4,.col-md-3,.col-md-12,.col-md-2,.mb-3,.form-group');
                        if (wrap) {
                            var near = wrap.querySelector('.step-label, label, legend');
                            if (near) raw = near.textContent;
                        }
                    }
                    // 3. Fall back to the placeholder text
                    if (!raw) raw = placeholder;
                    // Strip leading icons / punctuation / prompt words
                    raw = raw.replace(/[*:\u2460-\u2473\u24B6-\u24CF]/g, '')  // asterisks, circled numbers
                             .replace(/\b(select|all|choose|pick)\s+/gi, '')
                             .replace(/^[-\s\d.]+|[-\s]+$/g, '')
                             .trim();
                    return raw || 'option';
                })();
                var _emptyLabelCap = _emptyLabel.charAt(0).toUpperCase() + _emptyLabel.slice(1);

                /* Always attach dropdown to body — card-body parent clips/hides list while typing on mobile;
                 * visualViewport handlers below avoid closing while keyboard is adjusting (see scroll helpers). */
                var ts = new TomSelect(el, {
                    create: el.classList.contains('create-mode'),
                    allowEmptyOption: false,
                    openOnFocus: false,
                    selectOnTab: true,
                    maxOptions: 300,
                    dropdownParent: 'body',
                    placeholder: placeholder,
                    onFocus: function() {
                        // Ghost-focus guard: if returning from camera, forcefully blur
                        if (window._isReturningFromCamera) {
                            try { this.blur(); } catch (e) {}
                            try { this.close(); } catch (e) {}
                        }
                    },
                    onBeforeOpen: function() {
                        // Silent shield: strictly prevent dropdown from even trying to open
                        if (window._isShieldActive) {
                            return false;
                        }
                    },
                    render: {
                        /* Triggered by TomSelect when a text search finds nothing */
                        no_results: function(data, escape) {
                            var hint = data.input
                                ? 'No match for &ldquo;' + escape(data.input) + '&rdquo;'
                                : 'No ' + escape(_emptyLabelCap) + ' available';
                            return _emptyStateHTML(hint);
                        }
                    },
                    onInitialize: function() {
                        // Native TS hook — runs after TS has fully built its DOM.
                        // If the select had no real value, clear any auto-selection
                        // and guarantee the placeholder div is rendered and visible.
                        var _self = this;
                        var _val = _self.getValue();
                        if (!_val || _val === '' || _val === '0') {
                            try { _self.clear(true); } catch(e) {}
                            _self.wrapper.classList.remove('has-items');
                            var ph = _self.control.querySelector('.placeholder');
                            if (ph) {
                                ph.style.display     = 'block';
                                ph.style.visibility  = 'visible';
                                ph.style.color       = '#6c757d';
                            }
                        }
                    }
                });

                // Remove pure-prompt placeholders ('-- Select Company --') from list;
                // keep 'All ...' options (filter resets) so user can click them.
                if (phValue !== null && _removeFromList) {
                    try { ts.removeOption(phValue); } catch(e) {}
                    ts.refreshOptions(false);
                    if (_hadNoValue) {
                        ts.wrapper.classList.remove('has-items');
                    }
                }

                // ── Bulletproof empty-state: inject message whenever dropdown
                //    opens and there are literally zero options to display.
                //    TomSelect's render.no_results only fires during a text search;
                //    this covers the "options list is empty on open" case too.
                ts.positionDropdown = function() {
                    window.fleetPositionTomSelectDropdown(ts);
                };

                ts.on('dropdown_open', function() {
                    if (typeof window.fleetTomSelectDropdownOpened === 'function') {
                        window.fleetTomSelectDropdownOpened();
                    }
                    requestAnimationFrame(function() {
                        window.fleetPositionTomSelectDropdown(ts);
                        var dc = ts.dropdown_content;
                        if (!dc) return;
                        dc.querySelectorAll('.ts-empty-forced').forEach(function(n){ n.remove(); });
                        var hasVisible = dc.querySelector('.option, .optgroup-header, [data-value]');
                        if (!hasVisible) {
                            var div = document.createElement('div');
                            div.className = 'ts-empty-state ts-empty-forced';
                            var lbl = ts.inputValue()
                                ? 'No match for &ldquo;' + ts.inputValue() + '&rdquo;'
                                : 'No ' + _emptyLabelCap + ' available';
                            div.innerHTML = _emptyStateHTML(lbl);
                            dc.appendChild(div);
                        }
                        requestAnimationFrame(function() {
                            window.fleetPositionTomSelectDropdown(ts);
                        });
                    });
                });

                ts.on('dropdown_close', function() {
                    if (typeof window.fleetTomSelectDropdownClosed === 'function') {
                        window.fleetTomSelectDropdownClosed();
                    }
                });

                // ── Highlight-and-Overwrite (SAP/Excel-style) ─────────────────
                ts._justSelected   = false;
                ts._overwriteReady = false;

                function _setOverwriteReady(on) {
                    ts._overwriteReady = on;
                    if (on) {
                        ts.control.classList.add('ts-overwrite-ready');
                    } else {
                        ts.control.classList.remove('ts-overwrite-ready');
                    }
                }

                ts.on('focus', function() {
                    if (ts._wsSilentFill || window._wsOcrIsUpdating) return;
                    // _justSelected guards against re-opening immediately after
                    // the user confirms a selection (TS internally refocuses then).
                    if (ts._justSelected) {
                        ts._justSelected = false; // consume the flag
                        _setOverwriteReady(false);
                        return;
                    }
                    // Open the dropdown immediately (no visual delay).
                    if (!ts.isOpen) ts.open();
                    // Apply the blue highlight slightly deferred so TS's own
                    // focus routine has settled — fixes Shift+Tab first-attempt miss.
                    setTimeout(function() {
                        if (!ts.wrapper.classList.contains('focus')) return; // blurred already
                        if (ts.getValue()) {
                            _setOverwriteReady(true);
                        } else {
                            _setOverwriteReady(false);
                        }
                    }, 15);
                });

                ts.on('blur', function() {
                    _setOverwriteReady(false);
                    // CRITICAL: clear _justSelected on every blur so that
                    // Shift+Tab or any re-entry highlights on the FIRST return.
                    ts._justSelected = false;
                });

                ts.on('item_add', function() {
                    ts._justSelected = true;
                    _setOverwriteReady(false);
                    if (ts._wsSilentFill || window._wsOcrIsUpdating) return;
                    // TS internally refocuses control_input after selection;
                    // keep _justSelected true through that synthetic focus so
                    // we don't re-open the dropdown.
                    // Only refocus when the user was actually interacting with
                    // THIS select — programmatic setValue() (e.g. slip OCR
                    // auto-fill) must never steal focus from the user's field.
                    var _wasFocused = ts.isFocused || ts.wrapper.classList.contains('focus');
                    setTimeout(function() {
                        ts._justSelected = true;
                        if (_wasFocused && !ts._wsSilentFill && !window._wsOcrIsUpdating) {
                            ts.control_input.focus();
                        }
                    }, 0);
                });

                ts.on('item_remove', function() {
                    _setOverwriteReady(false);
                    if (!ts.isOpen) ts.open();
                });

                // Store references for Enter-to-tab capture listener
                ts.control_input._tsOrigSelect = el;
                ts.control_input._ts = ts;

                // ── Keydown: overwrite-on-type + Backspace + Enter-to-tab ──────
                ts.control_input.addEventListener('keydown', function(e) {
                    if (ts._overwriteReady) {
                        if (e.key === 'Backspace') {
                            e.preventDefault();
                            ts.clear(true);
                            _setOverwriteReady(false);
                            if (!ts.isOpen) ts.open();
                            return;
                        }
                        if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
                            // Printable key: clear item, stay out of overwrite mode,
                            // let the character fall through into the search input naturally
                            ts.clear(true);
                            _setOverwriteReady(false);
                            if (!ts.isOpen) ts.open();
                            // Do NOT preventDefault — char goes into control_input
                        }
                    }
                    // Enter-to-tab: when dropdown is already closed
                    if (e.key === 'Enter' && !ts.isOpen) {
                        e.preventDefault();
                        e.stopImmediatePropagation();
                        _tsMoveFocus(el);
                    }
                }, true);

            } catch(ex) {
                console.warn('[TomSelect] init failed:', (el.name || el.id), ex);
            }
        });
    };

    // Safe global helper: page-specific scripts can call this any time.
    window.FleetInitSelectors = function(scope) {
        if (typeof TomSelect === 'undefined') {
            console.warn('[FleetInitSelectors] TomSelect not loaded — dropdowns will fall back to native selects');
            return;
        }
        console.log('[FleetInitSelectors] Triggered', scope ? '(scoped)' : '(global)');
        window.initSearchableDropdowns(scope);
    };

    function _fleetBootSelectors() {
        // Initialize all static selects on the page
        window.FleetInitSelectors();

        // Re-init for any dynamically added .search-select / .tom-select elements
        if (typeof MutationObserver !== 'undefined' && document.body) {
            (new MutationObserver(function(muts) {
                muts.forEach(function(m) {
                    m.addedNodes.forEach(function(node) {
                        if (node.nodeType !== 1) return;
                        if (node.querySelector && node.querySelector('select.search-select, select.tom-select, .tom-select')) {
                            window.initSearchableDropdowns(node);
                        }
                    });
                });
            })).observe(document.body, { childList: true, subtree: true });
        }
    }

    if (document.readyState !== 'loading') {
        _fleetBootSelectors();
    } else {
        document.addEventListener('DOMContentLoaded', _fleetBootSelectors);
    }

    /* Keep body-attached Tom Select menus aligned while scroll / layout shifts. */
    (function() {
        var _tsRepositionScheduled = false;
        var _tsLayoutMo = null;
        var _tsLayoutWatchStarted = false;

        window.fleetRepositionOpenTomSelects = function() {
            if (_tsRepositionScheduled) return;
            _tsRepositionScheduled = true;
            requestAnimationFrame(function() {
                _tsRepositionScheduled = false;
                try {
                    document.querySelectorAll('select.search-select, select.tom-select, .tom-select').forEach(function(sel) {
                        var t = sel.tomselect;
                        if (t && t.isOpen) window.fleetPositionTomSelectDropdown(t);
                    });
                } catch (e) {}
            });
        };

        function _startTomSelectLayoutWatch() {
            if (_tsLayoutWatchStarted) return;
            _tsLayoutWatchStarted = true;
            if (_tsLayoutMo) return;
            var root = document.getElementById('mainContent') || document.body;
            if (!root || typeof MutationObserver === 'undefined') return;
            _tsLayoutMo = new MutationObserver(function() {
                window.fleetRepositionOpenTomSelects();
            });
            _tsLayoutMo.observe(root, {
                childList: true,
                subtree: true,
                characterData: true,
                attributes: true,
                attributeFilter: ['class', 'style', 'hidden']
            });
        }

        function _stopTomSelectLayoutWatch() {
            if (!_tsLayoutMo) return;
            _tsLayoutMo.disconnect();
            _tsLayoutMo = null;
        }

        window.fleetTomSelectDropdownOpened = function() {
            _startTomSelectLayoutWatch();
        };

        window.fleetTomSelectDropdownClosed = function() {
            requestAnimationFrame(function() {
                var anyOpen = false;
                try {
                    document.querySelectorAll('select.search-select, select.tom-select, .tom-select').forEach(function(sel) {
                        if (sel.tomselect && sel.tomselect.isOpen) anyOpen = true;
                    });
                } catch (e) {}
                if (!anyOpen) _stopTomSelectLayoutWatch();
            });
        };

        window.addEventListener('resize', window.fleetRepositionOpenTomSelects, { passive: true });
        window.addEventListener('scroll', window.fleetRepositionOpenTomSelects, true);
        if (window.visualViewport) {
            window.visualViewport.addEventListener('resize', window.fleetRepositionOpenTomSelects, { passive: true });
            window.visualViewport.addEventListener('scroll', window.fleetRepositionOpenTomSelects, { passive: true });
        }

        function _attachMainContentScroll() {
            var mc = document.getElementById('mainContent');
            if (mc) {
                mc.addEventListener('scroll', window.fleetRepositionOpenTomSelects, { passive: true });
            }
        }
        if (document.readyState !== 'loading') {
            _attachMainContentScroll();
        } else {
            document.addEventListener('DOMContentLoaded', _attachMainContentScroll);
        }
    })();

    // onInitialize hook inside TomSelect handles placeholder — no setInterval needed.

    // Initialize Components
    $(document).ready(function() {
        // ── Global Smart Date Fields — Total Isolation ──
        window._smartDateRawInputs = {};

        window.robustParse = function(input) {
            if (!input) return null;
            var raw = input.toLowerCase().trim();
            var d, m, y;
            var months = {jan:'01',feb:'02',mar:'03',apr:'04',may:'05',jun:'06',
                          jul:'07',aug:'08',sep:'09',oct:'10',nov:'11',dec:'12'};

            // Case A: 8-digit pure numeric  e.g. 03031997
            if (/^\d{8}$/.test(raw)) {
                d = raw.substring(0, 2); m = raw.substring(2, 4); y = raw.substring(4, 8);

            // Case B: 6-digit pure numeric  e.g. 030397
            } else if (/^\d{6}$/.test(raw)) {
                d = raw.substring(0, 2); m = raw.substring(2, 4); y = raw.substring(4, 6);

            // Case C: Text month  e.g. 03-mar-1997, 3/mar/97, 03 march 1997
            } else if (/[a-z]/.test(raw)) {
                var tokens = raw.split(/[^a-z0-9]+/).filter(function(x){ return x.length > 0; });
                var numParts = []; var monthPart = null;
                for (var i = 0; i < tokens.length; i++) {
                    var tk = tokens[i];
                    var mk = tk.replace(/[^a-z]/g, '').substring(0, 3);
                    if (mk && months[mk]) {
                        monthPart = months[mk];
                    } else {
                        var digits = tk.replace(/[^0-9]/g, '');
                        if (digits) numParts.push(digits);
                    }
                }
                if (monthPart && numParts.length >= 2) {
                    d = numParts[0]; m = monthPart; y = numParts[1];
                }

            // Case D: Numeric with separators  e.g. 03-03-1997, 03/03/1997
            } else {
                var parts2 = raw.split(/[^0-9]+/).filter(function(x){ return x.length > 0; });
                if (parts2.length === 3) {
                    d = parts2[0]; m = parts2[1]; y = parts2[2];
                }
            }

            if (!d || !m || !y) return null;
            d = d.replace(/[^0-9]/g, ''); y = y.replace(/[^0-9]/g, '');
            if (!d || !m || !y || isNaN(parseInt(d)) || isNaN(parseInt(y))) return null;
            if (d.length === 1) d = '0' + d;
            if (typeof m === 'string' && m.length === 1) m = '0' + m;
            if (y.length === 2) { y = (parseInt(y) < 50) ? '20' + y : '19' + y; }
            if (d.length > 2 || y.length !== 4) return null;
            var di = parseInt(d), mi = parseInt(m);
            if (di < 1 || di > 31 || mi < 1 || mi > 12) return null;
            return d + '-' + m + '-' + y;
        };

        window.initSmartDateFields = function(selector) {
            document.querySelectorAll(selector).forEach(function(el) {
                if (el._smartDateInit) return;
                el._smartDateInit = true;

                // WTForms 3.x renders DateField as type="date" — browser rejects DD-MM-YYYY.
                // Force type="text" and recover original value from HTML attribute.
                var attrVal = el.getAttribute('value') || '';
                if (el.type === 'date') el.type = 'text';
                var existingVal = (el.value || attrVal || '').trim();
                if (/^\d{4}-\d{2}-\d{2}$/.test(existingVal)) {
                    var p = existingVal.split('-');
                    existingVal = p[2] + '-' + p[1] + '-' + p[0];
                }
                el.value = existingVal;

                var fp = flatpickr(el, {
                    dateFormat: "d-m-Y",
                    allowInput: true,
                    clickOpens: true
                });
                if (existingVal && fp) {
                    fp.setDate(existingVal, false);
                    el.value = existingVal;
                }

                // ── Total Isolation: block Flatpickr from seeing keyboard events ──
                el.addEventListener('keydown', function(e) { e.stopPropagation(); }, true);
                el.addEventListener('input', function(e) {
                    e.stopPropagation();
                    window._smartDateRawInputs[el.id || el.name] = e.target.value;
                }, true);

                // ── Fresh state on every focus ──
                el.addEventListener('focus', function() {
                    window._smartDateRawInputs[el.id || el.name] = '';
                }, true);

                // ── Last Word: setTimeout(20) so we override after Flatpickr finishes ──
                el.addEventListener('blur', function(e) {
                    e.stopImmediatePropagation();
                    var key = el.id || el.name;
                    var typedValue = (window._smartDateRawInputs[key] || '').trim();

                    setTimeout(function() {
                        // Nothing typed → leave as-is (calendar pick or pre-filled)
                        if (!typedValue) return;
                        // Already correct DD-MM-YYYY → just sync Flatpickr
                        if (/^\d{2}-\d{2}-\d{4}$/.test(typedValue)) {
                            if (el._flatpickr) {
                                el._flatpickr.setDate(typedValue, false);
                                el.value = typedValue;
                            }
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                            return;
                        }
                        var formatted = window.robustParse(typedValue);
                        if (formatted) {
                            if (el._flatpickr) {
                                el._flatpickr.setDate(formatted, false);
                                el.value = formatted;
                            }
                            window._smartDateRawInputs[key] = formatted;
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                        } else {
                            // No-Alert: clear + red border flash
                            if (el._flatpickr) el._flatpickr.clear();
                            el.value = '';
                            window._smartDateRawInputs[key] = '';
                            el.style.borderColor = '#dc3545';
                            el.style.boxShadow = '0 0 0 0.2rem rgba(220,53,69,0.25)';
                            setTimeout(function() {
                                el.style.borderColor = '';
                                el.style.boxShadow = '';
                            }, 1500);
                        }
                    }, 20);
                }, true);
            });
        };

        window.initSmartDateFields('.datepicker');

        // MutationObserver: catch .datepicker fields added dynamically or inside hidden tabs
        var _sdObs = new MutationObserver(function(mutations) {
            mutations.forEach(function(m) {
                m.addedNodes.forEach(function(node) {
                    if (node.nodeType !== 1) return;
                    if (node.classList && node.classList.contains('datepicker')) {
                        window.initSmartDateFields('.datepicker');
                    } else if (node.querySelectorAll) {
                        var inner = node.querySelectorAll('.datepicker');
                        if (inner.length) window.initSmartDateFields('.datepicker');
                    }
                });
            });
        });
        _sdObs.observe(document.body, { childList: true, subtree: true });

        window.fleetResetFilterFormButtons = function() {
            document.querySelectorAll('#filterForm button[type="submit"]').forEach(function(btn) {
                btn.disabled = false;
                btn.classList.remove('btn-loading');
                if (btn.dataset.fleetSubmitHtml) {
                    btn.innerHTML = btn.dataset.fleetSubmitHtml;
                }
            });
        };

        window.fleetIsDashboardNavUrl = function(href) {
            if (!href || href === '#') return true;
            if (href.indexOf('javascript:') === 0) return true;
            try {
                var p = new URL(href, window.location.origin).pathname.replace(/\/+$/, '') || '/';
                return p === '/' || p === '/dashboard';
            } catch (err) {
                return href === '/' || href.indexOf('/dashboard') >= 0;
            }
        };

        window.fleetResolveNavBackHref = function(el) {
            var href = (el && el.getAttribute('data-fleet-nav-back-href')) || (el && el.getAttribute('href'));
            if (href && !window.fleetIsDashboardNavUrl(href)) return href;
            var hubSlug = (el && el.getAttribute('data-hub-slug')) || '';
            if (hubSlug) {
                href = '/hub/' + hubSlug;
                if (!window.fleetIsDashboardNavUrl(href)) return href;
            }
            var nf = (el && el.getAttribute('data-nav-from')) || '';
            if (nf === 'reports') {
                href = window.FleetConfig.urls.reports_index;
                if (!window.fleetIsDashboardNavUrl(href)) return href;
            }
            return null;
        };

        window.fleetPersistNavBack = function(href, navFrom, scope) {
            try {
                if (href && !window.fleetIsDashboardNavUrl(href)) {
                    sessionStorage.setItem('fleet_nav_back_href', href);
                }
                if (navFrom) sessionStorage.setItem('fleet_nav_from', navFrom);
                if (scope) sessionStorage.setItem('fleet_nav_back_scope', scope);
            } catch (err) { /* private mode */ }
        };

        window.fleetNavigateBack = function(e, el) {
            if (e) {
                e.preventDefault();
                e.stopPropagation();
            }
            window.fleetResetFilterFormButtons();
            document.querySelectorAll('.btn-loading').forEach(function(b) {
                b.disabled = false;
                b.classList.remove('btn-loading');
            });
            var href = window.fleetResolveNavBackHref(el);
            if (href) {
                window.location.assign(href);
                return false;
            }
            window.location.assign(window.FleetConfig.urls.reports_index);
            return false;
        };

        document.addEventListener('DOMContentLoaded', function() {
            if (document.body.getAttribute('data-fleet-page') === 'dashboard') {
                try {
                    sessionStorage.removeItem('fleet_nav_back_href');
                    sessionStorage.removeItem('fleet_nav_back_scope');
                } catch (err) {}
            }
            var btn = document.querySelector('[data-fleet-nav-back="1"]');
            if (!btn) return;
            var href = btn.getAttribute('data-fleet-nav-back-href') || btn.getAttribute('href');
            var nf = btn.getAttribute('data-nav-from') || '';
            var scope = document.body.getAttribute('data-fleet-endpoint') || '';
            if (!href || window.fleetIsDashboardNavUrl(href)) {
                href = window.fleetResolveNavBackHref(btn);
            }
            if (href) window.fleetPersistNavBack(href, nf, scope);
        });

        // ── Loading spinner on filter form submit ──
        document.addEventListener('submit', function(e) {
            var form = e.target;
            if (!form || form.id !== 'filterForm') return;
            var btn = form.querySelector('button[type="submit"]');
            if (btn && !btn.disabled) {
                if (!btn.dataset.fleetSubmitHtml) {
                    btn.dataset.fleetSubmitHtml = btn.innerHTML;
                }
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Loading...';
            }
        });

        // ── Global Enter-to-Tab (Window-Capture) ──
        var _enterGuard = 0;
        window.addEventListener('keydown', function(e) {
            if (e.key !== 'Enter' && e.keyCode !== 13) return;
            var el = e.target;
            if (!el) return;
            var tag = el.tagName.toLowerCase();

            // ── Tom Select: intercepted BEFORE any other listener ──────────
            if (el.closest && el.closest('.ts-control')) {
                var tsInst = el._ts;
                if (tsInst) {
                    if (tsInst.isOpen) return; // 1st Enter: let TS select the highlighted item
                    // 2nd Enter: dropdown is CLOSED — aggressively move focus
                    e.preventDefault();
                    e.stopImmediatePropagation();
                    kickFocusToNext(el);
                    return;
                }
                return; // inside TS wrapper but no _ts ref — let TS handle
            }

            // Textarea without Ctrl: allow normal newline
            if (tag === 'textarea' && !e.ctrlKey && !e.shiftKey) return;

            // Only act on form fields
            if (tag !== 'input' && tag !== 'select' && tag !== 'textarea') return;

            // Submit button: allow form submission
            if (tag === 'button' || (tag === 'input' && el.type === 'submit')) return;

            // Find parent form
            var form = el.closest('form');
            if (!form) return;

            // Bulletproof focusable list
            var focusable = Array.prototype.slice.call(
                form.querySelectorAll('input, select, textarea, button, [tabindex]')
            ).filter(function(f) {
                if (f.type === 'hidden') return false;
                if (f.disabled || f.readOnly) return false;
                if (f.hasAttribute('tabindex') && f.tabIndex < 0) return false;
                if (f.offsetParent === null) return false;
                try { if (getComputedStyle(f).visibility === 'hidden') return false; } catch(x) {}
                return true;
            });

            var idx = focusable.indexOf(el);
            var nextEl = null;
            if (idx !== -1) {
                for (var j = idx + 1; j < focusable.length; j++) {
                    if (_fleetEnterTabSkip(focusable[j])) continue;
                    nextEl = focusable[j];
                    break;
                }
            }

            // Last element or no next → allow form submit
            if (!nextEl) return;
            // If next is submit button, allow form submit
            var nextTag = nextEl.tagName.toLowerCase();
            if (nextTag === 'button' || (nextTag === 'input' && nextEl.type === 'submit')) {
                // Move focus to the submit button but don't block
                e.preventDefault();
                e.stopImmediatePropagation();
                nextEl.focus();
                return;
            }

            // ── KILL SWITCH: block form submission ──
            e.preventDefault();
            e.stopImmediatePropagation();

            // 200ms ghost guard: ignore rapid duplicate Enter events
            var now = Date.now();
            if (now - _enterGuard < 200) return;
            _enterGuard = now;

            // Datepicker: blur lets flatpickr finish formatting, then kick focus
            if (el.classList && el.classList.contains('datepicker')) {
                el.blur();
                setTimeout(function() { kickFocusToNext(el); }, 50);
            } else {
                el.blur();
                _fleetFocusField(nextEl);
            }
        }, true);


        // ── CNIC Mask (.cnic-mask): auto-formats XXXXX-XXXXXXX-X, max 13 digits ──
        function _applyCnicMask(el) {
            var digits = (el.value || '').replace(/\D/g, '').slice(0, 13);
            var v = digits.match(/(\d{0,5})(\d{0,7})(\d{0,1})/);
            el.value = !v[2] ? v[1] : v[1] + '-' + v[2] + (v[3] ? '-' + v[3] : '');
        }
        $(document).on('input', '.cnic-mask', function() { _applyCnicMask(this); });
        $(document).on('blur',  '.cnic-mask', function() { _applyCnicMask(this); });
        $(document).on('keydown', '.cnic-mask', function(e) {
            var allow = [8, 9, 13, 27, 46, 35, 36, 37, 38, 39, 40];
            if (allow.indexOf(e.keyCode) !== -1) return;
            if ((e.ctrlKey || e.metaKey) && [65, 67, 86, 88, 90].indexOf(e.keyCode) !== -1) return;
            if (!/^\d$/.test(e.key)) e.preventDefault();
        });

        // ── Phone Mask (.phone-format, .phone-mask): XXXX-XXXXXXX, max 11 digits ──
        function _applyPhoneMask(el) {
            var digits = (el.value || '').replace(/\D/g, '').slice(0, 11);
            el.value = digits.length > 4 ? digits.slice(0, 4) + '-' + digits.slice(4) : digits;
        }
        $(document).on('input', '.phone-format, .phone-mask', function() { _applyPhoneMask(this); });
        $(document).on('blur',  '.phone-format, .phone-mask', function() { _applyPhoneMask(this); });
        $(document).on('keydown', '.phone-format, .phone-mask', function(e) {
            var allow = [8, 9, 13, 27, 46, 35, 36, 37, 38, 39, 40];
            if (allow.indexOf(e.keyCode) !== -1) return;
            if ((e.ctrlKey || e.metaKey) && [65, 67, 86, 88, 90].indexOf(e.keyCode) !== -1) return;
            if (!/^\d$/.test(e.key)) e.preventDefault();
        });

        // Realtime search on list tables: as user types, rows filter instantly
        $("[data-realtime-table]").each(function() {
            var $input = $(this);
            var tableId = $input.data("realtime-table");
            var $table = $("#" + tableId);
            if (!$table.length) return;
            var $rows = $table.find("tbody tr");

            function applyFilter() {
                var q = ($input.val() || "").toString().trim();
                if (!q) {
                    $rows.show();
                    return;
                }
                $rows.each(function() {
                    var $row = $(this);
                    $row.toggle(window.fleetMultiWordMatch($row.text(), q));
                });
            }

            $input.on("input", applyFilter);

            // Prevent full form submit when pressing Enter in search box
            $input.on("keydown", function(e) {
                if (e.key === "Enter") {
                    e.preventDefault();
                }
            });
        });
    });

    // Move focus to next field on Enter (within forms)
    document.addEventListener("keydown", function(event) {
        if (event.key === "Enter") {
            const target = event.target;

            // Skip Tom Select inputs entirely — window capture listener above handles them
            if (target.closest && target.closest('.ts-control')) return;

            // Skip datepicker fields — window capture listener handles blur + flatpickr formatting
            if (target.classList && target.classList.contains('datepicker')) return;


            // Check if the target is an input, select, or textarea within a form
            if (target.tagName === "INPUT" || target.tagName === "SELECT" || target.tagName === "TEXTAREA") {
                const form = target.form;
                if (form) {
                    event.preventDefault(); // Prevent default form submission

                    const focusableElements = Array.from(form.querySelectorAll(
                        "input:not([type=\"hidden\"]):not([readonly]):not([disabled]), select:not([readonly]):not([disabled]), textarea:not([readonly]):not([disabled])"
                    )).filter(
                        el => el.offsetWidth > 0 && el.offsetHeight > 0
                    );

                    const currentElementIndex = focusableElements.indexOf(target);
                    if (currentElementIndex > -1) {
                        let nextElement = focusableElements[currentElementIndex + 1];
                        
                        // Skip disabled
                        while(nextElement && nextElement.disabled) {
                            nextElement = focusableElements[focusableElements.indexOf(nextElement) + 1];
                        }

                        if (nextElement) {
                            nextElement.focus();
                        } else {
                            const submitButton = form.querySelector("button[type=\"submit\"], input[type=\"submit\"]");
                            if (submitButton) {
                                submitButton.click();
                            }
                        }
                    }
                }
            } else if (target.tagName === "BUTTON" && target.type !== "button" && !target.disabled) {
                event.preventDefault(); 
                target.click();
            }
        }
    });

    // ─── Guide Chatbot (Forms & Reports Q&A) ───
    (function() {
        var panel = document.getElementById("guideChatPanel");
        var toggle = document.getElementById("guideChatToggle");
        var closeBtn = document.getElementById("guideChatClose");
        var messagesEl = document.getElementById("guideChatMessages");
        var inputEl = document.getElementById("guideChatInput");
        var sendBtn = document.getElementById("guideChatSend");
        if (!panel || !toggle) return;

        var guideQA = [
            { keys: ["form", "forms", "kaise", "add", "create", "banaye"], cat: "forms",
              text: "<strong>Forms in this app:</strong><br>• Company, District, Project, Vehicle, Driver, Parking<br>• Fuel / Oil / Maintenance Expense<br>• Party, Product Name (Master)<br>• Driver Transfer, Vehicle Transfer, Assign Driver to Vehicle, Assign Vehicle to District/Parking<br>• Penalty, Red Task, Task Reports, Driver Attendance<br><br>Use the sidebar to open the list page, then click <strong>Add</strong> or <strong>Edit</strong>." },
            { keys: ["driver", "add driver", "driver form", "driver kaise"], cat: "forms",
              text: "<strong>Add Driver:</strong> Sidebar → Drivers → Add Driver. Fill Driver ID, Name, CNIC, License, Phone (format 0300-1112346), Emergency No, Post, etc. Save." },
            { keys: ["vehicle", "add vehicle", "vehicle form", "vehicle kaise"], cat: "forms",
              text: "<strong>Add Vehicle:</strong> Sidebar → Vehicles → Add Vehicle. Enter Vehicle No, Model, Type, Engine/Chassis No, Vehicle Phone. Save." },
            { keys: ["company", "add company", "company form"], cat: "forms",
              text: "<strong>Add Company:</strong> Sidebar → Companies (or Dashboard → Add Company). Enter name, address, mobile (0300-1112346), phone, email. Save." },
            { keys: ["district", "add district", "district form"], cat: "forms",
              text: "<strong>Add District:</strong> Sidebar → Districts (or Dashboard → Add District). Enter district name and save." },
            { keys: ["project", "add project", "project form"], cat: "forms",
              text: "<strong>Add Project:</strong> Sidebar → Projects → Add. Enter name, start date, status (Active/Inactive). Save." },
            { keys: ["parking", "add parking", "parking station"], cat: "forms",
              text: "<strong>Add Parking:</strong> Sidebar → Parking → Add. Enter station name and capacity. Save." },
            { keys: ["fuel", "fuel expense", "petrol", "diesel"], cat: "forms",
              text: "<strong>Fuel Expense:</strong> Sidebar → Expenses → Fuel Expense. Select District, Project, Vehicle, Date, Meter Reading, Product, Qty, Price. Amount is auto. You can add multiple lines." },
            { keys: ["oil", "oil expense", "oil change"], cat: "forms",
              text: "<strong>Oil Expense:</strong> Sidebar → Expenses → Oil. Select District, Project, Vehicle, Date, meter readings. Add product lines with Payment Type (Cash/Credit), Purchase Qty, Used Qty, Price. Amount and Balance are calculated." },
            { keys: ["maintenance", "maintenance expense", "repair"], cat: "forms",
              text: "<strong>Maintenance:</strong> Sidebar → Expenses → Maintenance. District, Project, Vehicle, Date, Meter Reading. Add products with Qty, Price (Amount auto). Remarks and photos allowed." },
            { keys: ["transfer", "driver transfer", "vehicle transfer"], cat: "forms",
              text: "<strong>Transfers:</strong> Sidebar has Driver Transfer and Vehicle Transfer. Use these to move a driver or vehicle from one project/district to another. Fill date, from/to location, and save." },
            { keys: ["assign driver", "assign vehicle", "driver assign", "vehicle assign"], cat: "forms",
              text: "<strong>Assign:</strong> Sidebar → Assign Driver to Vehicle, or Assign Vehicle to District/Parking. Select project, district, vehicle/driver and save the assignment." },
            { keys: ["penalty", "penalty record"], cat: "forms",
              text: "<strong>Penalty:</strong> Sidebar → Penalty Record. Add penalty for a driver with date, amount, reason. List and filter from the same section." },
            { keys: ["red task", "red task form"], cat: "forms",
              text: "<strong>Red Task:</strong> Sidebar → Red Task. Add and list red tasks linked to project/driver/vehicle as per your workflow." },
            { keys: ["task report", "task report upload", "logbook"], cat: "forms",
              text: "<strong>Task Reports:</strong> Sidebar → Task Reports. List, add new, or upload emergency/mileage reports. Use filters by date and project." },
            { keys: ["attendance", "driver attendance", "mark attendance"], cat: "forms",
              text: "<strong>Driver Attendance:</strong> Sidebar → Driver Attendance. Mark or view daily attendance (check-in/check-out) for drivers." },
            { keys: ["product", "product name", "master product"], cat: "forms",
              text: "<strong>Product Name (Master):</strong> Sidebar → Master → Products Name. Add products used in Fuel, Oil, or Maintenance. You can select in which form(s) each product is used." },
            { keys: ["party", "party form"], cat: "forms",
              text: "<strong>Party:</strong> Sidebar → Party. Add and list parties (e.g. for fuel or other expenses)." },
            { keys: ["report", "reports", "report kya", "kaun si", "reports section"], cat: "reports",
              text: "<strong>Available Reports:</strong> Company Profile, Project Summary, District Summary, Vehicle Summary, Vehicle Profile, License/CNIC Expiry, Parking Utilization, Driver Attendance. Plus <strong>Create report with AI</strong> for custom temp reports. Sidebar → Reports." },
            { keys: ["expiry", "license expiry", "cnic expiry", "document expiry"], cat: "reports",
              text: "<strong>License/CNIC Expiry:</strong> Sidebar → Reports → License / CNIC Expiry. Shows drivers with documents expiring in the selected number of days." },
            { keys: ["attendance report", "attendance summary"], cat: "reports",
              text: "<strong>Attendance Report:</strong> Sidebar → Reports → Attendance Report. Monthly driver attendance summary. Filter by date range." },
            { keys: ["custom report", "apni report", "ai report", "khud report", "temp report"], cat: "reports",
              text: "<strong>Custom report:</strong> Go to Reports → <strong>Create report with AI</strong>. Describe what you need (e.g. drivers, vehicles, projects, expiry). A temporary report opens; close it when done—nothing is saved." },
            { keys: ["shortcut", "shortcuts", "short key", "keyboard shortcut", "hotkey"], cat: "general",
              text: (function() {
                var list = (window._appShortcuts || [
                  { keys: "Alt+F", label: "Add Fuel Expense" },
                  { keys: "Alt+O", label: "Add Oil Expense" },
                  { keys: "Alt+M", label: "Add Maintenance Expense" },
                  { keys: "Alt+T", label: "Add Workspace Transfer" },
                  { keys: "Alt+L", label: "Workspace Ledger" }
                ]);
                var lines = list.map(function(it){ return "• <kbd>" + it.keys + "</kbd> → " + it.label; });
                return "<strong>Keyboard Shortcuts:</strong><br>" + lines.join("<br>") + "<br><br>Note: Shortcut tab kaam nahi karta jab input field, command palette, ya modal open ho.";
              })() },
            { keys: ["dashboard", "home", "main page"], cat: "general",
              text: "<strong>Dashboard:</strong> Shows counts (Companies, Projects, Districts, Vehicles, Parking, Drivers) and <strong>Notifications</strong> (e.g. document expiry). Use the cards to jump to each section." },
            { keys: ["notification", "notifications", "alert", "bell"], cat: "general",
              text: "<strong>Notifications:</strong> Shown on the Dashboard. They can include document expiry reminders or other alerts. Click <strong>View</strong> to open the linked report, or ✓ to mark as read." },
            { keys: ["mobile", "phone", "format", "0300", "number format"], cat: "forms",
              text: "<strong>Mobile format:</strong> In Driver, Company, and Vehicle forms, enter phone as 03001112346—when you leave the field it will auto-format to 0300-1112346." },
            { keys: ["hello", "hi", "help", "start", "hey"], cat: "greet",
              text: "Hi! I'm the app guide. Ask about <strong>Forms</strong> (e.g. how to add driver, vehicle, fuel, company) or <strong>Reports</strong> (what reports exist, expiry, attendance, AI report)." },
            { keys: ["thank", "thanks", "bye"], cat: "greet",
              text: "You're welcome! Ask anytime if you need help with forms or reports." }
        ];

        function getReply(msg) {
            if (!msg || !msg.trim()) return "Please type a short question about Forms or Reports.";
            var m = msg.toLowerCase().trim();
            for (var i = 0; i < guideQA.length; i++) {
                for (var j = 0; j < guideQA[i].keys.length; j++) {
                    if (m.indexOf(guideQA[i].keys[j]) !== -1) return guideQA[i].text;
                }
            }
            return "I can guide you on <strong>Forms</strong> (Company, Driver, Vehicle, Fuel, Oil, Maintenance, etc.) and <strong>Reports</strong> (Project Summary, Expiry, Attendance, etc.). Try: \"How to add driver?\" or \"What reports are there?\"";
        }

        function addMsg(html, isUser) {
            var div = document.createElement("div");
            div.className = "mb-2 " + (isUser ? "text-end" : "");
            var bubble = document.createElement("div");
            bubble.className = "d-inline-block p-2 rounded " + (isUser ? "bg-primary text-white" : "bg-light");
            bubble.style.maxWidth = "90%";
            bubble.innerHTML = isUser ? ("You: " + html) : html;
            div.appendChild(bubble);
            messagesEl.appendChild(div);
            messagesEl.scrollTop = messagesEl.scrollHeight;
        }

        function send() {
            var val = (inputEl && inputEl.value) ? inputEl.value.trim() : "";
            if (!val) return;
            addMsg(val.replace(/</g, "&lt;"), true);
            if (inputEl) inputEl.value = "";
            addMsg(getReply(val), false);
        }

        toggle.addEventListener("click", function() {
            panel.classList.toggle("d-none");
            if (!panel.classList.contains("d-none") && inputEl) inputEl.focus();
        });
        if (closeBtn) closeBtn.addEventListener("click", function() { panel.classList.add("d-none"); });
        if (sendBtn) sendBtn.addEventListener("click", send);
        if (inputEl) inputEl.addEventListener("keydown", function(e) { if (e.key === "Enter") send(); });
        $(document).on("click", ".guide-chip", function() {
            var t = $(this).text().trim();
            if (inputEl) inputEl.value = t;
            send();
        });
    })();

    // ── Pull-to-Refresh (dashboard only) ──────────────────────────────────
    (function() {
        if (!('ontouchstart' in window)) return;
        // Only enable PTR on dashboard page
        var _path = window.location.pathname.replace(/\/$/, '') || '/';
        var _isDash = (_path === '' || _path === '/' || _path === '/dashboard');
        if (!_isDash) return;
        var bar = document.getElementById('pullRefreshBar');
        var overlay = document.getElementById('ptrOverlay');
        var ptrText = document.getElementById('ptrText');
        var startY = 0, pulling = false, threshold = 120, triggered = false;
        var _blocked = ['#sidebar', '.more-drawer-panel', '#moreDrawerPanel', '#attendSheet', '.modal', '.offcanvas'];
        document.addEventListener('touchstart', function(e) {
            // Ignore touches that start inside sidebar, drawers, modals
            var t = e.target;
            for (var i = 0; i < _blocked.length; i++) {
                if (t.closest && t.closest(_blocked[i])) return;
            }
            var _mc = document.getElementById('mainContent');
            var _top = _mc ? _mc.scrollTop : window.scrollY;
            if (_top === 0) { startY = e.touches[0].clientY; pulling = true; triggered = false; }
        }, { passive: true });
        document.addEventListener('touchmove', function(e) {
            if (!pulling) return;
            var dist = e.touches[0].clientY - startY;
            if (dist <= 0) return;
            var capped = Math.min(dist, threshold * 1.6);
            if (bar) { bar.style.transform = 'scaleX(' + (capped / threshold) + ')'; bar.style.transition = 'none'; }
            if (overlay) {
                overlay.classList.add('ptr-visible');
                if (capped >= threshold) {
                    overlay.classList.add('ptr-releasing');
                    if (ptrText) ptrText.textContent = 'Release to refresh';
                } else {
                    overlay.classList.remove('ptr-releasing');
                    if (ptrText) ptrText.textContent = 'Pull down to refresh';
                }
            }
        }, { passive: true });
        document.addEventListener('touchend', function(e) {
            if (!pulling) return;
            pulling = false;
            var dist = e.changedTouches[0].clientY - startY;
            if (bar) { bar.style.transition = 'transform 0.3s'; bar.style.transform = 'scaleX(0)'; }
            if (overlay) {
                if (dist >= threshold && !triggered) {
                    triggered = true;
                    if (ptrText) ptrText.textContent = 'Refreshing…';
                    setTimeout(function() { window.fleetHardReload(); }, 300);
                } else {
                    overlay.classList.remove('ptr-visible', 'ptr-releasing');
                    if (ptrText) ptrText.textContent = 'Pull down to refresh';
                }
            }
        }, { passive: true });
    })();

    // ── Capacitor Native Bridge ────────────────────────────────────────────
    // Detects if running inside Capacitor (native Android/iOS app) and exposes
    // FleetBridge.getGPS() / FleetBridge.takeSelfie() / FleetBridge.requestPushPermission()
    window.FleetBridge = (function() {
        var _isNative = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());

        if (_isNative) {
            document.documentElement.classList.add('capacitor-native');
            document.body.classList.add('capacitor-native');
            var _vpMeta = document.getElementById('metaViewport');
            if (_vpMeta) {
                var _vpContent = _vpMeta.getAttribute('content') || '';
                if (_vpContent.indexOf('resizes-content') !== -1) {
                    _vpMeta.setAttribute('content', _vpContent.replace(
                        'interactive-widget=resizes-content',
                        'interactive-widget=resizes-visual'
                    ));
                }
            }
        }

        /* ── Permission Alert (Toast or styled modal) ─────────────────── */
        function _showPermissionAlert(permName, message) {
            if (_isNative && window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Toast) {
                window.Capacitor.Plugins.Toast.show({ text: message, duration: 'long', position: 'bottom' });
                return;
            }
            var overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:99999;display:flex;align-items:center;justify-content:center;padding:20px;';
            var box = document.createElement('div');
            box.style.cssText = 'background:#fff;border-radius:14px;padding:24px 20px;max-width:340px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.25);font-family:system-ui,sans-serif;';
            box.innerHTML =
                '<div style="font-size:1.05rem;font-weight:700;color:#1e293b;margin-bottom:10px;">&#9888;&#65039; ' + permName + ' Permission Required</div>' +
                '<div style="font-size:0.88rem;color:#475569;line-height:1.6;margin-bottom:20px;">' + message + '</div>' +
                '<button style="width:100%;padding:13px;background:#0f172a;color:#fff;border:none;border-radius:9px;font-size:0.95rem;font-weight:600;cursor:pointer;letter-spacing:0.02em;">Understood</button>';
            overlay.appendChild(box);
            document.body.appendChild(overlay);
            box.querySelector('button').addEventListener('click', function() { document.body.removeChild(overlay); });
        }

        /* ── GPS with permission gate ────────────────────────────────────── */
        function getGPS() {
            return new Promise(function(resolve, reject) {
                if (_isNative && window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Geolocation) {
                    var Geo = window.Capacitor.Plugins.Geolocation;
                    Geo.checkPermissions().then(function(status) {
                        var state = (status.location || status.coarseLocation || 'prompt');
                        if (state === 'granted') {
                            return Geo.getCurrentPosition({ enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
                        } else {
                            return Geo.requestPermissions({ permissions: ['location', 'coarseLocation'] }).then(function(res) {
                                var granted = (res.location === 'granted' || res.coarseLocation === 'granted');
                                if (granted) {
                                    return Geo.getCurrentPosition({ enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
                                } else {
                                    _showPermissionAlert('Location', 'Location permission is required. Please go to Settings → Apps → Fleet Manager → Permissions and enable Location to allow check-in.');
                                    throw { code: 'location_denied' };
                                }
                            });
                        }
                    }).then(function(pos) {
                        resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy: pos.coords.accuracy });
                    }).catch(reject);
                } else if (!_isNative && 'geolocation' in navigator) {
                    // Browser only — never use navigator.geolocation on native app (fails on HTTP origins)
                    navigator.geolocation.getCurrentPosition(
                        function(pos) { resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy: pos.coords.accuracy }); },
                        reject,
                        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
                    );
                } else {
                    reject(new Error('Geolocation not available — native GPS plugin missing'));
                }
            });
        }

        /* ── Camera with permission gate ──────────────────────────────────── */
        function _capacitorCameraPhoto(quality) {
            var Cam = window.Capacitor.Plugins.Camera;
            var q = (quality != null && quality >= 1 && quality <= 100) ? quality : 70;
            var opts = {
                quality: q,
                allowEditing: false,
                resultType: 'base64',
                source: 'CAMERA',
                direction: 'FRONT',
                saveToGallery: false
            };
            return Cam.checkPermissions().then(function(status) {
                var state = (status.camera || 'prompt');
                if (state === 'granted') {
                    return Cam.getPhoto(opts);
                }
                return Cam.requestPermissions({ permissions: ['camera'] }).then(function(res) {
                    if (res.camera === 'granted') {
                        return Cam.getPhoto(opts);
                    }
                    _showPermissionAlert('Camera', 'Camera permission is required to take attendance selfies. Please go to Settings → Apps → Fleet Manager → Permissions and enable Camera.');
                    throw { code: 'camera_denied' };
                });
            }).then(function(photo) {
                return 'data:image/jpeg;base64,' + photo.base64String;
            });
        }

        function takeSelfie(opts) {
            opts = opts || {};
            var quality = opts.quality != null ? opts.quality : 70;
            return new Promise(function(resolve, reject) {
                if (_isNative && window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Camera) {
                    _capacitorCameraPhoto(quality).then(resolve).catch(reject);
                    return;
                }
                var input = document.createElement('input');
                input.type = 'file';
                input.accept = 'image/*';
                input.capture = 'user';
                input.onchange = function() {
                    var file = input.files && input.files[0];
                    if (!file) {
                        reject({ code: 'cancelled', message: 'No file selected' });
                        return;
                    }
                    var reader = new FileReader();
                    reader.onload = function(e) { resolve(e.target.result); };
                    reader.onerror = reject;
                    reader.readAsDataURL(file);
                };
                input.click();
            });
        }

        /** GPS attendance: phone built-in front camera (not gallery). */
        function takeAttendanceSelfie() {
            return takeSelfie({ quality: 88 });
        }

        /* ── Proactive permission warm-up (call once on app init) ────────── */
        function initPermissions() {
            if (!_isNative || !window.Capacitor || !window.Capacitor.Plugins) return Promise.resolve();
            var jobs = [];
            var Geo = window.Capacitor.Plugins.Geolocation;
            var Cam = window.Capacitor.Plugins.Camera;
            if (Geo) {
                jobs.push(Geo.checkPermissions().then(function(s) {
                    var state = (s.location || s.coarseLocation || 'prompt');
                    if (state !== 'granted') {
                        return Geo.requestPermissions({ permissions: ['location', 'coarseLocation'] });
                    }
                }).catch(function() {}));
            }
            if (Cam) {
                jobs.push(Cam.checkPermissions().then(function(s) {
                    if ((s.camera || 'prompt') !== 'granted') {
                        return Cam.requestPermissions({ permissions: ['camera'] });
                    }
                }).catch(function() {}));
            }
            return Promise.all(jobs);
        }

        var _deviceUniqueId = null;

        function _getDeviceUniqueId() {
            if (_deviceUniqueId) return Promise.resolve(_deviceUniqueId);
            if (_isNative && window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Device) {
                return window.Capacitor.Plugins.Device.getId().then(function(info) {
                    _deviceUniqueId = info.identifier || info.uuid || null;
                    return _deviceUniqueId;
                }).catch(function() { return null; });
            }
            return Promise.resolve(null);
        }

        function _sendTokenToServer(token) {
            _fcmDebug('_sendTokenToServer called, token=' + (token ? token.substring(0, 20) + '...' : 'NULL'));
            _getDeviceUniqueId().then(function(devId) {
                _fcmDebug('DeviceId=' + (devId || 'NULL'));
                var deviceInfo = navigator.userAgent.substring(0, 200);
                var payload = { token: token, device_info: deviceInfo };
                if (devId) payload.device_unique_id = devId;
                var csrfToken = (document.querySelector('meta[name=csrf-token]') || {}).content || '';
                _fcmDebug('Sending to /api/register-fcm-token... CSRF=' + (csrfToken ? 'yes' : 'NO'));
                fetch('/api/register-fcm-token', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                    credentials: 'include',
                    body: JSON.stringify(payload)
                }).then(function(r) {
                    _fcmDebug('Server response status: ' + r.status);
                    return r.json();
                }).then(function(d) {
                    _fcmDebug('Server result: ' + JSON.stringify(d));
                }).catch(function(e) { _fcmDebug('Token registration FAILED: ' + e); });
            }).catch(function(e) { _fcmDebug('DeviceId ERROR: ' + e); });
        }

        function _fcmDebug() {}

        function _setupPushListeners() {
            _fcmDebug('_setupPushListeners called. isNative=' + _isNative);
            if (!_isNative) { _fcmDebug('NOT native, skipping.'); return; }
            if (!window.Capacitor || !window.Capacitor.Plugins) { _fcmDebug('No Capacitor.Plugins'); return; }
            if (!window.Capacitor.Plugins.PushNotifications) { _fcmDebug('PushNotifications plugin NOT found!'); return; }
            _fcmDebug('PushNotifications plugin available.');

            var Push = window.Capacitor.Plugins.PushNotifications;
            Push.addListener('registration', function(token) {
                _tokenReceived = true;
                _fcmDebug('TOKEN received: ' + (token.value ? token.value.substring(0, 30) + '...' : 'EMPTY'));
                _sendTokenToServer(token.value);
            });
            Push.addListener('registrationError', function(err) {
                _fcmDebug('REGISTRATION ERROR: ' + JSON.stringify(err));
            });
            Push.addListener('pushNotificationReceived', function(notification) {
                // foreground notification received
                if (notification.title) {
                    _toast(notification.title + (notification.body ? ': ' + notification.body : ''));
                }
            });
            Push.addListener('pushNotificationActionPerformed', function(action) {
                // notification tapped
                var data = (action.notification && action.notification.data) || {};
                if (data.link) { window.location.href = data.link; }
            });
        }
        _setupPushListeners();

        // Native fallback: receives token directly from Java when GMS proxy blocks getToken()
        window._onNativeFcmToken = function(token) {
            _fcmDebug('NATIVE DIRECT TOKEN received: ' + (token ? token.substring(0, 30) + '...' : 'EMPTY'));
            if (token && !_tokenReceived) {
                _tokenReceived = true;
                _sendTokenToServer(token);
            }
        };

        // Banking-style fallback: called when FCM is completely blocked and polling mode activates.
        // fisId = Firebase Installation ID used as temporary device identifier.
        window._onFcmFallbackMode = function(fisId) {
            _fcmDebug('POLLING FALLBACK activated. FIS ID: ' + (fisId || 'NONE'));
            _fcmDebug('Push notifications unavailable — server polling active every 2 min');
            if (fisId && !_tokenReceived) {
                _tokenReceived = true;
                var fisToken = 'fis:' + fisId;
                _sendTokenToServer(fisToken);
                // Retry registration after 10s in case session wasn't ready
                setTimeout(function() { _sendTokenToServer(fisToken); }, 10000);
                // Store FIS ID in localStorage for future reference
                try { localStorage.setItem('fleet_fis_id', fisId); } catch(e) {}
            }
        };

        var _tokenReceived = false;

        function _retryRegister(attempt) {
            if (_tokenReceived || attempt > 5) {
                if (!_tokenReceived && attempt > 5) _fcmDebug('All 5 retry attempts exhausted — token never arrived.');
                return;
            }
            var delay = attempt * 10000;
            _fcmDebug('Retry #' + attempt + ' — re-calling register() in ' + (delay/1000) + 's...');
            setTimeout(function() {
                if (_tokenReceived) return;
                _fcmDebug('Retry #' + attempt + ' — calling register() now');
                try {
                    window.Capacitor.Plugins.PushNotifications.register()
                        .then(function() { _fcmDebug('Retry #' + attempt + ' register() resolved'); })
                        .catch(function(e) { _fcmDebug('Retry #' + attempt + ' register() rejected: ' + JSON.stringify(e)); });
                } catch(e) { _fcmDebug('Retry #' + attempt + ' register() threw: ' + e); }
                _retryRegister(attempt + 1);
            }, delay);
        }

        function requestPushPermission() {
            return new Promise(function(resolve) {
                _fcmDebug('requestPushPermission called');
                if (_isNative && window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.PushNotifications) {
                    _fcmDebug('Requesting permissions...');
                    window.Capacitor.Plugins.PushNotifications.requestPermissions().then(function(result) {
                        _fcmDebug('Permission result: ' + result.receive);
                        if (result.receive === 'granted') {
                            _fcmDebug('GRANTED! Calling register()...');
                            try {
                                window.Capacitor.Plugins.PushNotifications.register()
                                    .then(function() { _fcmDebug('register() resolved OK'); })
                                    .catch(function(e) { _fcmDebug('register() REJECTED: ' + JSON.stringify(e)); });
                            } catch(regErr) {
                                _fcmDebug('register() THREW: ' + regErr);
                            }
                            _retryRegister(1);
                        } else {
                            _fcmDebug('NOT GRANTED: ' + result.receive);
                        }
                        resolve(result.receive === 'granted');
                    }).catch(function(e) { _fcmDebug('Permission ERROR: ' + JSON.stringify(e)); resolve(false); });
                } else {
                    if ('Notification' in window) {
                        Notification.requestPermission().then(function(p) { resolve(p === 'granted'); });
                    } else {
                        resolve(false);
                    }
                }
            });
        }

        /* ── In-App Update System ──────────────────────────────────────── */
        function _compareVersions(a, b) {
            var pa = (a || '0').split('.').map(Number);
            var pb = (b || '0').split('.').map(Number);
            for (var i = 0; i < Math.max(pa.length, pb.length); i++) {
                var na = pa[i] || 0, nb = pb[i] || 0;
                if (na < nb) return -1;
                if (na > nb) return 1;
            }
            return 0;
        }

        /* Populate version badge + update status next to sidebar button (runs on every page) */
        (function() {
            if (!_isNative) return;
            var AppP = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.App;
            if (!AppP || typeof AppP.getInfo !== 'function') return;

            function _populateNavbar(version, latestVersion) {
                console.log('[NavbarVersion] _populateNavbar called: v=' + version + ' latest=' + latestVersion);

                /* Version badge */
                var curEl = document.getElementById('navCurrentVersion');
                if (curEl) curEl.textContent = 'v' + version;

                /* Status elements */
                var statusEl = document.getElementById('navStatusText');
                var statusDot = document.getElementById('statusDot');
                var updateLine = document.getElementById('updateLine');
                var newVerEl = document.getElementById('navNewVersion');

                if (!latestVersion || latestVersion === '0.0.0' || _compareVersions(version, latestVersion) >= 0) {
                    /* Up to date */
                    if (statusEl) { statusEl.textContent = 'Latest Version'; statusEl.style.color = '#475569'; }
                    if (statusDot) {
                        statusDot.style.background = '#10b981';
                        statusDot.style.animation = 'none';
                    }
                    if (updateLine) updateLine.style.display = 'none';
                    console.log('[NavbarVersion] Status: LATEST');
                } else {
                    /* Update available */
                    if (statusEl) { statusEl.textContent = 'Downloading Update...'; statusEl.style.color = '#f59e0b'; }
                    if (statusDot) {
                        statusDot.style.background = '#f59e0b';
                        statusDot.style.animation = 'pulse 1.5s infinite';
                    }
                    if (updateLine) updateLine.style.display = 'flex';
                    if (newVerEl) newVerEl.textContent = 'v' + latestVersion;
                    console.log('[NavbarVersion] Status: DOWNLOADING (v' + latestVersion + ')');
                }

                /* Old navbar brand badge (if exists on non-dashboard pages) */
                var vEl = document.getElementById('navAppVersion');
                if (vEl) { vEl.textContent = 'v' + version; vEl.style.display = 'inline'; }

                /* Old pill if present */
                var pill = document.getElementById('navUpdateStatusPill');
                if (pill) {
                    pill.style.display = 'inline-flex';
                    var pillIcon = document.getElementById('navUpdateStatusIcon');
                    var pillTxt = document.getElementById('navUpdateStatusText');
                    if (!latestVersion || latestVersion === '0.0.0' || _compareVersions(version, latestVersion) >= 0) {
                        if (pillIcon) pillIcon.className = 'bi bi-check-circle-fill';
                        if (pillTxt) pillTxt.textContent = 'v' + version + ' — Latest';
                        pill.style.color = '#22c55e';
                    } else {
                        if (pillIcon) pillIcon.className = 'bi bi-arrow-repeat';
                        if (pillTxt) pillTxt.textContent = 'v' + version + ' → v' + latestVersion;
                        pill.style.color = '#f97316';
                    }
                }
            }

            function _runVersionCheck() {
                console.log('[NavbarVersion] Version check started');
                AppP.getInfo().then(function(info) {
                    var currentVersion = info.version || info.build || '0.0.0';
                    if (!currentVersion || currentVersion === '0.0.0') return;
                    fetch('/api/app/check-update', { credentials: 'include' })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            _populateNavbar(currentVersion, data.latest_version || '0.0.0');
                        })
                        .catch(function() {
                            _populateNavbar(currentVersion, '0.0.0');
                        });
                }).catch(function(e) { console.warn('[NavbarVersion] App.getInfo failed:', e); });
            }

            /* Run immediately + retry after 500ms for late-rendered navbar */
            _runVersionCheck();
            setTimeout(_runVersionCheck, 500);
            setTimeout(_runVersionCheck, 2000);
        })();

        function _checkForAppUpdate() {
            if (!_isNative) { return; }

            // Report current version to server (for admin stats)
            _reportDeviceVersion();

            // New apps (v2.0.8+): Java handles auto-update via FleetAutoUpdateManager
            if (window._fleetNative && typeof window._fleetNative.checkForUpdate === 'function') {
                try { window._fleetNative.checkForUpdate(); } catch (e) { console.warn('[Update] Java check failed:', e); }
                return;
            }
            // Old apps (v1.9.x): JS fallback — check server for update, show persistent banner
            console.log('[Update] Java bridge not found, using JS fallback');

            // Restore banner from localStorage if update is pending (survives page navigation)
            var savedUpdate = localStorage.getItem('_fleetPendingUpdate');
            if (savedUpdate) {
                try {
                    var savedData = JSON.parse(savedUpdate);
                    _showUpdateBanner(savedData);
                } catch (e) { localStorage.removeItem('_fleetPendingUpdate'); }
            }

            // Always re-check server for latest update info
            fetch('/api/app/check-update', { credentials: 'include' })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data && data.latest_version && data.latest_version !== '0.0.0' && data.apk_url) {
                        var AppP = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.App;
                        if (AppP && typeof AppP.getInfo === 'function') {
                            AppP.getInfo().then(function(info) {
                                var cur = info.version || '0.0.0';
                                if (_compareVersions(cur, data.latest_version) < 0) {
                                    // Store in localStorage for persistence across pages
                                    localStorage.setItem('_fleetPendingUpdate', JSON.stringify(data));
                                    _showUpdateBanner(data);
                                } else {
                                    // Up to date — clear any pending update
                                    localStorage.removeItem('_fleetPendingUpdate');
                                    var existing = document.getElementById('appUpdateBanner');
                                    if (existing) existing.remove();
                                }
                            }).catch(function() {
                                localStorage.setItem('_fleetPendingUpdate', JSON.stringify(data));
                                _showUpdateBanner(data);
                            });
                        } else {
                            localStorage.setItem('_fleetPendingUpdate', JSON.stringify(data));
                            _showUpdateBanner(data);
                        }
                    }
                })
                .catch(function(e) { console.warn('[Update] JS fallback check failed:', e); });
        }

        function _sendVersionToServer(version, platform) {
            // Centralised POST — always fires (with error logging, never silent swallow).
            fetch('/api/app/report-version', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ version: version, platform: platform })
            }).catch(function(err) {
                console.warn('[reportVersion] POST failed:', err);
            });
        }

        function _reportDeviceVersion() {
            try {
                // 1. Prefer Java native bridge — 100% reliable (reads PackageManager directly,
                //    not via Capacitor proxy which can race/fail during early bridge init).
                if (window._fleetNative && typeof window._fleetNative.getAppVersion === 'function') {
                    var v = null;
                    try { v = window._fleetNative.getAppVersion(); } catch (e) { v = null; }
                    if (v) { _sendVersionToServer(v, 'mobile'); return; }
                }

                var AppP = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.App;

                // 2. Native app but Capacitor App plugin missing entirely → still report (don't lose the user).
                if (_isNative && (!AppP || typeof AppP.getInfo !== 'function')) {
                    console.warn('[reportVersion] native app, App plugin unavailable — reporting fallback');
                    _sendVersionToServer('mobile-unknown', 'mobile');
                    return;
                }

                // 3. Desktop/web — report as 'web' so admin can see online web users
                if (!_isNative) {
                    _sendVersionToServer('web', 'web');
                    return;
                }

                // 4. Native app + Capacitor App plugin — try getInfo() with retries (bridge may not be ready).
                var attempts = 0;
                function tryGetInfo() {
                    attempts++;
                    AppP.getInfo().then(function(info) {
                        var version = (info && info.version) || '0.0.0';
                        if (!version || version === '0.0.0') {
                            if (attempts < 3) { setTimeout(tryGetInfo, 1500); return; }
                            console.warn('[reportVersion] getInfo returned empty — reporting fallback');
                            _sendVersionToServer('mobile-unknown', 'mobile');
                            return;
                        }
                        _sendVersionToServer(version, 'mobile');
                    }).catch(function(err) {
                        if (attempts < 3) {
                            console.warn('[reportVersion] getInfo attempt ' + attempts + ' failed, retrying:', err);
                            setTimeout(tryGetInfo, 1500);
                        } else {
                            console.warn('[reportVersion] getInfo failed after retries — reporting fallback:', err);
                            _sendVersionToServer('mobile-unknown', 'mobile');
                        }
                    });
                }
                tryGetInfo();
            } catch (e) {
                console.warn('[reportVersion] outer error:', e);
                _sendVersionToServer('mobile-unknown', 'mobile');
            }
        }

        function _showUpdateBanner(data) {
            var existing = document.getElementById('appUpdateBanner');
            if (existing) existing.remove();

            // Check if APK was already downloaded — show Install directly
            var downloadedUri = localStorage.getItem('_fleetDownloadedApkUri');
            var downloadedFname = localStorage.getItem('_fleetDownloadedApkFname');
            var downloadedVersion = localStorage.getItem('_fleetDownloadedApkVersion');

            if (downloadedUri && downloadedFname && downloadedVersion === data.latest_version) {
                // APK already downloaded for this version — show Install button
                var banner2 = document.createElement('div');
                banner2.id = 'appUpdateBanner';
                banner2.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:linear-gradient(135deg,#065f46,#10b981);color:#fff;padding:14px 16px;display:flex;align-items:center;gap:12px;font-family:system-ui;font-size:14px;box-shadow:0 4px 20px rgba(0,0,0,0.3);';
                banner2.innerHTML = '<div style="flex:1"><strong>Update Ready v' + data.latest_version + '!</strong><br><span style="font-size:12px;opacity:0.9">Tap Install to apply the update</span></div>' +
                    '<button id="apkInstallBtn" style="background:#fff;color:#065f46;border:none;border-radius:8px;padding:10px 22px;font-weight:700;font-size:14px;cursor:pointer">Install</button>' +
                    (data.force_update ? '' : '<button id="appUpdateDismiss" style="background:transparent;border:none;color:#fff;font-size:20px;cursor:pointer;padding:4px 8px;opacity:0.7">&times;</button>');
                document.body.appendChild(banner2);

                document.getElementById('apkInstallBtn').addEventListener('click', function() {
                    _openInstaller(downloadedUri, downloadedFname, banner2);
                });
                var dismiss2 = document.getElementById('appUpdateDismiss');
                if (dismiss2) {
                    dismiss2.addEventListener('click', function() {
                        banner2.remove();
                    });
                }
                return;
            }

            // Check if download is in progress — show downloading state
            var dlState = localStorage.getItem('_fleetDownloadState');
            if (dlState) {
                try {
                    var state = JSON.parse(dlState);
                    if (state.version === data.latest_version) {
                        // Show downloading banner (will restart download but user sees progress)
                        _downloadAndInstallApk(data, null, true);
                        return;
                    }
                } catch (e) { localStorage.removeItem('_fleetDownloadState'); }
            }

            var banner = document.createElement('div');
            banner.id = 'appUpdateBanner';
            banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:linear-gradient(135deg,#1e40af,#3b82f6);color:#fff;padding:14px 16px;display:flex;align-items:center;gap:12px;font-family:system-ui;font-size:14px;box-shadow:0 4px 20px rgba(0,0,0,0.3);';
            banner.innerHTML = '<div style="flex:1"><strong>New Update v' + data.latest_version + '</strong><br><span style="font-size:12px;opacity:0.85">Tap Update to download and install</span></div>' +
                '<button id="appUpdateBtn" style="background:#fff;color:#1e40af;border:none;border-radius:8px;padding:8px 18px;font-weight:700;font-size:13px;cursor:pointer;white-space:nowrap">Update</button>' +
                (data.force_update ? '' : '<button id="appUpdateDismiss" style="background:transparent;border:none;color:#fff;font-size:20px;cursor:pointer;padding:4px 8px;opacity:0.7">&times;</button>');

            document.body.appendChild(banner);

            document.getElementById('appUpdateBtn').addEventListener('click', function() {
                _downloadAndInstallApk(data, banner, false);
            });
            var dismiss = document.getElementById('appUpdateDismiss');
            if (dismiss) {
                dismiss.addEventListener('click', function() {
                    // Only dismiss for 30 seconds, then re-show (non-force updates)
                    localStorage.removeItem('_fleetPendingUpdate');
                    banner.remove();
                    setTimeout(function() { _checkForAppUpdate(); }, 30000);
                });
            }
        }

        function _apkLooksValid(blob, expectedBytes) {
            if (!blob || blob.size < 500000) return false;
            if (expectedBytes > 0 && blob.size < expectedBytes * 0.9) return false;
            return true;
        }

        function _validateApkBlobHeader(blob) {
            return blob.slice(0, 2).arrayBuffer().then(function(buf) {
                var v = new Uint8Array(buf);
                if (v.length < 2 || v[0] !== 0x50 || v[1] !== 0x4B) {
                    throw new Error('Downloaded file is not a valid APK');
                }
            });
        }

        function _downloadAndInstallApk(data, banner, isResuming) {
            var FleetDl = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.FleetApkDownload;
            var fname = data.apk_filename || 'fleet-manager-update.apk';

            // Mark download as in-progress in localStorage
            localStorage.setItem('_fleetDownloadState', JSON.stringify({
                version: data.latest_version,
                fname: fname,
                startedAt: Date.now()
            }));

            // Create banner if not provided (e.g. after refresh)
            if (!banner) {
                var existing = document.getElementById('appUpdateBanner');
                if (existing) existing.remove();
                banner = document.createElement('div');
                banner.id = 'appUpdateBanner';
                banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:linear-gradient(135deg,#1e40af,#3b82f6);color:#fff;padding:14px 16px;display:flex;align-items:center;gap:12px;font-family:system-ui;font-size:14px;box-shadow:0 4px 20px rgba(0,0,0,0.3);';
                document.body.appendChild(banner);
            }

            banner.innerHTML = '<div style="flex:1">' +
                '<div style="margin-bottom:6px;font-weight:600">' + (isResuming ? 'Resuming download v' : 'Downloading v') + data.latest_version + '...</div>' +
                '<div style="background:rgba(255,255,255,0.25);border-radius:6px;height:8px;overflow:hidden">' +
                '<div id="apkProgressBar" style="background:#fff;height:100%;width:0%;border-radius:6px;transition:width 0.3s"></div></div>' +
                '<div id="apkProgressText" style="font-size:11px;opacity:0.8;margin-top:4px">Starting download...</div>' +
                '</div>';

            if (FleetDl && typeof FleetDl.download === 'function') {
                var txtNative = document.getElementById('apkProgressText');
                if (txtNative) txtNative.textContent = 'Downloading via system (reliable)...';
                FleetDl.download({ url: data.apk_url, filename: fname })
                    .then(function(res) {
                        if (!res || !res.uri) throw new Error('Download incomplete');
                        // Save downloaded URI for resume after refresh
                        localStorage.setItem('_fleetDownloadedApkUri', res.uri);
                        localStorage.setItem('_fleetDownloadedApkFname', fname);
                        localStorage.setItem('_fleetDownloadedApkVersion', data.latest_version);
                        localStorage.removeItem('_fleetDownloadState');
                        _showInstallPrompt(res.uri, fname, banner, true);
                    })
                    .catch(function(err) {
                        console.error('[Update] Native download failed:', err);
                        localStorage.removeItem('_fleetDownloadState');
                        banner.innerHTML = '<div style="flex:1;color:#fca5a5">Download failed. Check connection or install APK manually from Downloads.</div>';
                        setTimeout(function() { banner.remove(); }, 7000);
                    });
                return;
            }

            var Filesystem = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Filesystem;
            var FileOpener = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.FileOpener;
            if (!Filesystem || !FileOpener) { alert('Update plugins not available.'); return; }

            var xhr = new XMLHttpRequest();
            xhr.open('GET', data.apk_url, true);
            xhr.responseType = 'blob';
            xhr.onprogress = function(e) {
                if (e.lengthComputable) {
                    var pct = Math.round((e.loaded / e.total) * 100);
                    var bar = document.getElementById('apkProgressBar');
                    var txt = document.getElementById('apkProgressText');
                    if (bar) bar.style.width = pct + '%';
                    if (txt) txt.textContent = pct + '% (' + (e.loaded / 1048576).toFixed(1) + ' MB / ' + (e.total / 1048576).toFixed(1) + ' MB)';
                }
            };
            xhr.onload = function() {
                if (xhr.status !== 200) {
                    localStorage.removeItem('_fleetDownloadState');
                    banner.innerHTML = '<div style="flex:1;color:#fca5a5">Download failed (HTTP ' + xhr.status + '). Please try again later.</div>';
                    setTimeout(function() { banner.remove(); }, 5000);
                    return;
                }
                var blob = xhr.response;
                var expectedBytes = data.file_size_bytes || 0;
                if (!_apkLooksValid(blob, expectedBytes)) {
                    localStorage.removeItem('_fleetDownloadState');
                    banner.innerHTML = '<div style="flex:1;color:#fca5a5">Invalid or incomplete APK download. Admin se sahi file upload karein.</div>';
                    setTimeout(function() { banner.remove(); }, 7000);
                    return;
                }
                var txtEl = document.getElementById('apkProgressText');
                if (txtEl) txtEl.textContent = 'Saving file...';

                _validateApkBlobHeader(blob).then(function() {
                    return _blobToBase64(blob);
                }).then(function(base64) {
                    var savePath = 'Download/' + fname;
                    return Filesystem.writeFile({
                        path: savePath,
                        data: base64,
                        directory: 'EXTERNAL',
                        recursive: true
                    }).then(function() {
                        return Filesystem.getUri({ path: savePath, directory: 'EXTERNAL' });
                    });
                }).then(function(uriResult) {
                    // Save downloaded URI for resume after refresh
                    localStorage.setItem('_fleetDownloadedApkUri', uriResult.uri);
                    localStorage.setItem('_fleetDownloadedApkFname', fname);
                    localStorage.setItem('_fleetDownloadedApkVersion', data.latest_version);
                    localStorage.removeItem('_fleetDownloadState');
                    _showInstallPrompt(uriResult.uri, fname, banner, false);
                }).catch(function(err) {
                    console.error('[Update] Save failed:', err);
                    localStorage.removeItem('_fleetDownloadState');
                    banner.innerHTML = '<div style="flex:1;color:#fca5a5">Save failed (file too large?). Install manually from PC/USB.</div>';
                    setTimeout(function() { banner.remove(); }, 7000);
                });
            };
            xhr.onerror = function() {
                localStorage.removeItem('_fleetDownloadState');
                banner.innerHTML = '<div style="flex:1;color:#fca5a5">Download failed. Check your connection.</div>';
                setTimeout(function() { banner.remove(); }, 5000);
            };
            xhr.send();
        }

        function _showInstallPrompt(fileUri, fname, banner, useNativeInstaller) {
            var FileOpener = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.FileOpener;
            var FleetDl = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.FleetApkDownload;
            banner.style.background = 'linear-gradient(135deg,#065f46,#10b981)';
            banner.innerHTML = '<div style="flex:1"><strong>Update Ready!</strong><br><span style="font-size:12px;opacity:0.9">Tap Install to apply the update</span></div>' +
                '<button id="apkInstallBtn" style="background:#fff;color:#065f46;border:none;border-radius:8px;padding:10px 22px;font-weight:700;font-size:14px;cursor:pointer">Install</button>';
            document.getElementById('apkInstallBtn').addEventListener('click', function() {
                _openInstaller(fileUri, fname, banner, useNativeInstaller);
            });
        }

        function _openInstaller(fileUri, fname, banner, useNativeInstaller) {
            var FileOpener = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.FileOpener;
            var FleetDl = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.FleetApkDownload;
            var openP;
            if (useNativeInstaller && FleetDl && typeof FleetDl.openInstaller === 'function') {
                openP = FleetDl.openInstaller({ uri: fileUri });
            } else if (FileOpener) {
                openP = FileOpener.open({ filePath: fileUri, contentType: 'application/vnd.android.package-archive' });
            } else {
                alert('Installer not available. Open Downloads folder and tap ' + fname);
                return;
            }
            openP.then(function() {})
                .catch(function(err) {
                    console.error('[Update] Install open failed:', err);
                    alert('Installer open nahi hua. Downloads folder se ' + fname + ' manually install karein.');
                });
        }

        function _toast(msg) {
            if (window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Toast) {
                window.Capacitor.Plugins.Toast.show({ text: msg, duration: 'short', position: 'bottom' });
            }
        }

        function _blobToBase64(blob) {
            return new Promise(function(resolve, reject) {
                var reader = new FileReader();
                reader.onloadend = function() {
                    var result = reader.result;
                    var base64 = result.substring(result.indexOf(',') + 1);
                    resolve(base64);
                };
                reader.onerror = reject;
                reader.readAsDataURL(blob);
            });
        }

        /**
         * Download a Blob reliably in Capacitor WebView + all browsers.
         * Desktop: normal <a download> click.
         * Mobile/WebView: Capacitor Filesystem plugin writes file to Downloads,
         * then shows a toast notification.
         */
        function downloadBlob(blob, filename, options) {
            var fname = filename || 'download';
            options = options || {};
            var onProgress = typeof options.onProgress === 'function' ? options.onProgress : null;
            function report(phase, pct, detail) {
                if (onProgress) onProgress(phase, pct, detail || '');
            }

            if (!_isNative) {
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = url; a.download = fname;
                document.body.appendChild(a); a.click();
                setTimeout(function() { document.body.removeChild(a); URL.revokeObjectURL(url); }, 2000);
                report('done', 100, 'Download started');
                return Promise.resolve();
            }

            report('saving', 12, 'Saving file...');
            var Filesystem = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Filesystem;
            var Share = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Share;
            if (!Filesystem) {
                console.error('Filesystem plugin not available');
                _toast('Download not available. Please update the app.');
                report('error', 0, 'Filesystem not available');
                return Promise.reject(new Error('Filesystem not available'));
            }

            function openShareSheet(result) {
                report('saved', 78, 'File saved');
                if (!Share) {
                    _toast('Saved to Downloads: ' + fname);
                    report('done', 100, 'Saved to Downloads');
                    return Promise.resolve(result);
                }
                report('sharing', 92, 'Opening share...');
                return Share.share({
                    title: fname,
                    text: 'File saved: ' + fname,
                    url: result.uri,
                    dialogTitle: 'Share / Open ' + fname
                }).then(function() {
                    report('done', 100, 'Complete');
                    return result;
                }).catch(function(shareErr) {
                    if (shareErr && shareErr.message && String(shareErr.message).toLowerCase().indexOf('cancel') >= 0) {
                        report('done', 100, 'Saved — share cancelled');
                        return result;
                    }
                    _toast('Saved to Downloads: ' + fname);
                    report('done', 100, 'Saved to Downloads');
                    return result;
                });
            }

            return _blobToBase64(blob).then(function(base64data) {
                report('saving', 35, 'Writing to Downloads...');
                return Filesystem.writeFile({
                    path: 'Download/' + fname,
                    data: base64data,
                    directory: 'EXTERNAL',
                    recursive: true
                });
            }).then(function(result) {
                return openShareSheet(result);
            }).catch(function(err) {
                console.error('Filesystem write failed:', err);
                _toast('Trying alternative save...');
                report('saving', 45, 'Trying alternative save...');
                return _blobToBase64(blob).then(function(b64) {
                    return Filesystem.writeFile({
                        path: fname,
                        data: b64,
                        directory: 'DATA',
                        recursive: true
                    });
                }).then(function(result) {
                    return openShareSheet(result);
                });
            }).catch(function(err2) {
                console.error('All save attempts failed:', err2);
                _toast('Save failed. Please try again.');
                report('error', 0, 'Save failed');
                return Promise.reject(err2);
            });
        }

        /**
         * Open a blob/URL for viewing — Desktop: new tab.
         * Mobile: if blob object passed, upload then navigate. Otherwise navigate to URL.
         */
        function openBlobUrl(blobUrlOrBlob, fallbackUrl, filename) {
            if (!_isNative) {
                var url = (blobUrlOrBlob instanceof Blob) ? URL.createObjectURL(blobUrlOrBlob) : blobUrlOrBlob;
                var win = window.open(url, '_blank');
                if (!win && fallbackUrl) window.open(fallbackUrl, '_blank');
                return Promise.resolve();
            }
            if (blobUrlOrBlob instanceof Blob) {
                return downloadBlob(blobUrlOrBlob, filename || 'preview.pdf');
            }
            window.location.href = blobUrlOrBlob;
            return Promise.resolve();
        }

        return {
            isNative: _isNative, getGPS: getGPS, takeSelfie: takeSelfie, takeAttendanceSelfie: takeAttendanceSelfie,
            requestPushPermission: requestPushPermission, initPermissions: initPermissions,
            showPermissionAlert: _showPermissionAlert,
            downloadBlob: downloadBlob, openBlobUrl: openBlobUrl, _toast: _toast,
            checkForAppUpdate: _checkForAppUpdate,
            reportDeviceVersion: _reportDeviceVersion
        };
    })();

    // Expose getGPS on window for attendance templates that check window.getGPS
    if (window.FleetBridge && typeof window.FleetBridge.getGPS === 'function') {
        window.getGPS = window.FleetBridge.getGPS;
    }

    /** Scroll focused field into visible area above keyboard (Capacitor / mobile). */
    window.fleetScrollFieldIntoView = function fleetScrollFieldIntoView(el) {
        if (!el || typeof el.scrollIntoView !== 'function') return;
        var run = function() {
            try {
                el.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
            } catch (e) {
                el.scrollIntoView(true);
            }
        };
        setTimeout(run, 100);
        setTimeout(run, 350);
    };

    /** Hide bottom nav app-wide while keyboard is open (Capacitor native). */
    window.fleetSetupKeyboardBottomNav = function fleetSetupKeyboardBottomNav() {
        if (!window.FleetBridge || !window.FleetBridge.isNative) return;
        if (window._fleetKeyboardNavReady) return;
        window._fleetKeyboardNavReady = true;

        var maxInnerH = window.innerHeight || 0;

        function isFormField(el) {
            if (!el || el.nodeType !== 1) return false;
            if (el.closest && el.closest('.mobile-bottom-nav, .more-drawer-panel, .more-drawer-overlay')) return false;
            var tag = el.tagName;
            if (tag === 'TEXTAREA') return true;
            if (tag === 'SELECT') return true;
            if (tag === 'INPUT') {
                var t = (el.type || 'text').toLowerCase();
                return t !== 'checkbox' && t !== 'radio' && t !== 'button' &&
                    t !== 'submit' && t !== 'reset' && t !== 'file' &&
                    t !== 'hidden' && t !== 'image';
            }
            if (el.isContentEditable) return true;
            if (el.closest && el.closest('.ts-wrapper')) return true;
            return false;
        }

        function keyboardLikelyOpen() {
            var active = document.activeElement;
            if (isFormField(active)) return true;
            var shrink = maxInnerH - (window.innerHeight || 0);
            if (shrink > 80) return true;
            var vv = window.visualViewport;
            if (vv) {
                var gap = Math.max(0, (window.innerHeight || 0) - vv.height - (vv.offsetTop || 0));
                if (gap > 60) return true;
            }
            return false;
        }

        function applyNavKeyboardState(open) {
            document.documentElement.classList.toggle('fleet-keyboard-open', open);
            document.body.classList.toggle('fleet-keyboard-open', open);
            var nav = document.getElementById('mobileBottomNav');
            if (nav) {
                nav.classList.toggle('fleet-nav-keyboard-hidden', open);
                if (open) {
                    nav.style.setProperty('display', 'none', 'important');
                } else {
                    nav.style.removeProperty('display');
                }
            }
            document.querySelectorAll('.mobile-fab-wrap').forEach(function(fab) {
                fab.style.display = open ? 'none' : '';
            });
        }

        function syncNavForKeyboard() {
            var h = window.innerHeight || 0;
            if (!keyboardLikelyOpen() && h >= maxInnerH - 40) {
                maxInnerH = Math.max(maxInnerH, h);
            }
            applyNavKeyboardState(keyboardLikelyOpen());
        }

        document.addEventListener('focusin', function(e) {
            syncNavForKeyboard();
            if (isFormField(e.target) && window.fleetScrollFieldIntoView) {
                window.fleetScrollFieldIntoView(e.target);
            }
        }, true);
        document.addEventListener('focusout', function() {
            setTimeout(syncNavForKeyboard, 200);
        }, true);
        window.addEventListener('resize', syncNavForKeyboard, { passive: true });
        window.addEventListener('orientationchange', function() {
            maxInnerH = window.innerHeight || maxInnerH;
            setTimeout(syncNavForKeyboard, 300);
        }, { passive: true });
        var vv = window.visualViewport;
        if (vv) {
            vv.addEventListener('resize', syncNavForKeyboard, { passive: true });
            vv.addEventListener('scroll', syncNavForKeyboard, { passive: true });
        }
        syncNavForKeyboard();
    };

    if (window.FleetBridge && window.FleetBridge.isNative) {
        window.fleetSetupKeyboardBottomNav();
    }

    // ── Native: fix target=_blank, window.open, window.print, download links ──
    if (window.FleetBridge && window.FleetBridge.isNative) {
        document.addEventListener('DOMContentLoaded', function() {
            document.querySelectorAll('a[target="_blank"]').forEach(function(a) {
                a.removeAttribute('target');
            });
            document.addEventListener('click', function(e) {
                var link = e.target.closest('a[href]');
                if (!link) return;
                var href = link.getAttribute('href') || '';
                var isExport = /export|\.xlsx|\.csv|\.xls/i.test(href);
                var isDownload = link.hasAttribute('download');
                if (!isExport && !isDownload) return;
                if (!href.startsWith('/') && !href.startsWith(window.location.origin)) return;
                e.preventDefault();
                e.stopPropagation();
                var fullUrl = href.startsWith('/') ? window.location.origin + href : href;
                var guessName = href.split('/').pop().split('?')[0] || 'export.xlsx';
                if (!/\.\w+$/.test(guessName)) guessName += '.xlsx';
                link.style.opacity = '0.6';
                link.style.pointerEvents = 'none';
                window.FleetBridge._toast('Downloading export...');
                fetch(fullUrl, { credentials: 'include' })
                    .then(function(r) {
                        var cd = r.headers.get('Content-Disposition') || '';
                        var m = cd.match(/filename[^;=\n]*=\s*["']?([^"';\n]+)/);
                        if (m) guessName = m[1];
                        return r.blob();
                    })
                    .then(function(blob) {
                        link.style.opacity = '';
                        link.style.pointerEvents = '';
                        return window.FleetBridge.downloadBlob(blob, guessName);
                    })
                    .catch(function(err) {
                        link.style.opacity = '';
                        link.style.pointerEvents = '';
                        console.error('Export download failed:', err);
                        alert('Export failed. Please try again.');
                    });
            }, true);
        });
        var _origWindowOpen = window.open;
        window.open = function(url, target, features) {
            if (url && typeof url === 'string' && !url.startsWith('blob:') && !url.startsWith('data:')) {
                if (url.startsWith('/') || url.startsWith(window.location.origin)) {
                    window.location.href = url;
                    return null;
                }
            }
            return _origWindowOpen.call(window, url, target, features);
        };

        var _origPrint = window.print.bind(window);
        window.print = function() {
            var el = document.getElementById('printContainer') || document.querySelector('.main-content') || document.body;
            var ov = document.createElement('div');
            ov.style.cssText = 'position:fixed;inset:0;z-index:99998;background:rgba(30,58,138,.82);backdrop-filter:blur(3px);display:flex;align-items:center;justify-content:center;';
            ov.innerHTML = '<div style="text-align:center;color:#fff;"><div style="width:44px;height:44px;margin:0 auto 12px;border:3px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:_bp_spin .7s linear infinite;"></div><div style="font-weight:600;">Generating PDF...</div></div>';
            if (!document.getElementById('_bp_spin_kf')) {
                var kf = document.createElement('style');
                kf.id = '_bp_spin_kf';
                kf.textContent = '@keyframes _bp_spin{to{transform:rotate(360deg)}}';
                document.head.appendChild(kf);
            }
            document.body.appendChild(ov);
            var title = document.title.replace(/[^a-zA-Z0-9_ -]/g,'') || 'Report';
            var fname = title.replace(/\s+/g,'_') + '.pdf';
            var scr = document.createElement('script');
            scr.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.2/html2pdf.bundle.min.js';
            scr.onload = function() {
                html2pdf().set({
                    margin:[6,4,6,4], filename:fname,
                    image:{type:'jpeg',quality:0.92},
                    html2canvas:{scale:2,useCORS:true,logging:false},
                    jsPDF:{unit:'mm',format:'a4',orientation:'landscape'},
                    pagebreak:{mode:['css','legacy']}
                }).from(el).output('blob').then(function(blob) {
                    if(ov.parentNode) ov.parentNode.removeChild(ov);
                    window.FleetBridge.downloadBlob(blob, fname);
                }).catch(function() {
                    if(ov.parentNode) ov.parentNode.removeChild(ov);
                    alert('PDF generation failed.');
                });
            };
            scr.onerror = function() {
                if(ov.parentNode) ov.parentNode.removeChild(ov);
                alert('Could not load PDF library.');
            };
            document.head.appendChild(scr);
        };
    }

    // ── Native App UI Enhancements (Capacitor context) ────────────────────
    if (window.FleetBridge && window.FleetBridge.isNative) {
        document.addEventListener('DOMContentLoaded', function() {

            // 0. Build Native App Shell ─────────────────────────────────────
            //    DOM structure after this IIFE:
            //      #appNativeShell (position:fixed, overflow:hidden)
            //        ├── #moreDrawerOverlay  (position:absolute, z-index:50)
            //        ├── #moreDrawerPanel    (position:absolute, z-index:51)
            //        │     closed = translateY(100%) → clipped by shell overflow:hidden
            //        │     open   = translateY(0)    → visible above nav
            //        ├── #mainContent        (flex:1, overflow-y:auto)
            //        └── #mobileBottomNav    (flex:0 0 auto)
            //
            //    Result: NOTHING in the shell uses position:fixed, so WebView
            //    fixed-position quirks CANNOT affect any of these elements.
            (function() {
                var mc      = document.getElementById('mainContent');
                var nav     = document.getElementById('mobileBottomNav');
                var mOverlay = document.getElementById('moreDrawerOverlay');
                var mPanel   = document.getElementById('moreDrawerPanel');
                if (!mc || !nav) return;

                var shell = document.createElement('div');
                shell.id  = 'appNativeShell';
                mc.parentNode.insertBefore(shell, mc);

                // Drawer goes in first (absolute, above content via z-index)
                if (mOverlay) shell.appendChild(mOverlay);
                if (mPanel)   shell.appendChild(mPanel);
                // Scrollable content area
                shell.appendChild(mc);
                // Bottom nav — always last flex child, never scrolls
                shell.appendChild(nav);

                // Force-closed on load + block touchmove scroll-through
                if (mOverlay) {
                    mOverlay.classList.remove('open');
                    mOverlay.addEventListener('touchmove', function(e) {
                        e.preventDefault();
                    }, { passive: false });
                }
                if (mPanel) mPanel.classList.remove('open');
            })();

            // 1. Hide web-only elements
            var guideWrap = document.getElementById('guideChatbotWrap');
            if (guideWrap) guideWrap.style.display = 'none';

            // FCM debug panel removed — production mode

            // 1b. Auto-request push notification permission on native app
            /* FCM permission request — only for logged-in users */
            if (window.FleetConfig && window.FleetConfig.userId) {
                setTimeout(function() {
                    window.FleetBridge.requestPushPermission();
                }, 2000);
            }

            // 1c. In-App Update Check (native only) — runs on every page for persistent banner
            setTimeout(function() { window.FleetBridge.checkForAppUpdate(); }, 3000);

            // 2. Auto-hide navbar on scroll down, show on scroll up (native feel)
            //    In Capacitor: body is fixed, so we listen on #mainContent (the scroll container)
            var navbar = document.querySelector('.navbar');
            var lastScroll = 0;
            var scrollThreshold = 60;
            var navHideTimer = null;
            var scrollEl = document.getElementById('mainContent') || window;
            function onNativeScroll() {
                var current = scrollEl === window ? window.scrollY : scrollEl.scrollTop;
                if (current <= 10) {
                    if (navbar) navbar.classList.remove('nav-hidden');
                    lastScroll = 0;
                    return;
                }
                if (current > lastScroll && current > scrollThreshold) {
                    if (navbar) navbar.classList.add('nav-hidden');
                } else if (current < lastScroll) {
                    if (navbar) navbar.classList.remove('nav-hidden');
                }
                lastScroll = current;
                clearTimeout(navHideTimer);
                navHideTimer = setTimeout(function() {
                    if (navbar) navbar.classList.remove('nav-hidden');
                }, 2000);
            }
            scrollEl.addEventListener('scroll', onNativeScroll, { passive: true });

            // 3. Mark active bottom nav item based on current URL
            var path = window.location.pathname;
            document.querySelectorAll('.mobile-nav-item').forEach(function(el) {
                var href = el.getAttribute('href') || '';
                if (href && path.indexOf(href) === 0) {
                    el.classList.add('active');
                } else {
                    el.classList.remove('active');
                }
            });

            // 4. Native tap ripple feedback on buttons and nav (not cards — see mobile_perfect.css)
            document.querySelectorAll('.btn, .mobile-nav-item').forEach(function(el) {
                el.addEventListener('touchstart', function() {
                    this.style.transition = 'opacity 0.1s, transform 0.1s';
                    this.style.opacity = '0.82';
                    this.style.transform = (this.style.transform || '') + ' scale(0.97)';
                }, { passive: true });
                el.addEventListener('touchend', function() {
                    this.style.opacity = '1';
                    this.style.transform = this.style.transform.replace(' scale(0.97)', '').replace('scale(0.97)', '').trim();
                }, { passive: true });
                el.addEventListener('touchcancel', function() {
                    this.style.opacity = '1';
                    this.style.transform = this.style.transform.replace(' scale(0.97)', '').replace('scale(0.97)', '').trim();
                }, { passive: true });
            });

            // 5b. Haptic feedback on primary buttons and form submit
            var _haptics = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Haptics;
            if (_haptics) {
                document.addEventListener('click', function(e) {
                    var t = e.target;
                    var btn = t.closest('.btn-primary, .btn-success, .btn-danger, [type="submit"]');
                    if (btn) {
                        _haptics.impact({ style: 'LIGHT' }).catch(function() {});
                    }
                });
                document.addEventListener('submit', function() {
                    _haptics.impact({ style: 'MEDIUM' }).catch(function() {});
                }, true);
            }

            // 5. Prevent double-tap zoom on buttons/links (native feel)
            var lastTap = 0;
            document.addEventListener('touchend', function(e) {
                var now = Date.now();
                if (now - lastTap < 300) {
                    if (e.target.closest('#mobileMenuBtn, #sidebarToggleMobile, #sidebar, #sidebarOverlay, .sidebar, .more-drawer-panel, .more-drawer-item')) {
                        lastTap = now;
                        return;
                    }
                    if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON' || e.target.closest('.btn')) {
                        e.preventDefault();
                    }
                }
                lastTap = now;
            });

        });
    }

    // ── Report device app version to server (for admin stats) — ALL users, ALL devices ──
    if (window.FleetConfig && window.FleetConfig.userId && window.FleetBridge && typeof window.FleetBridge.reportDeviceVersion === 'function') {
        setTimeout(function() { window.FleetBridge.reportDeviceVersion(); }, 1500);
    }

    // ── Service Worker: PWA browser only — never cache Capacitor WebView HTML ──
    (function fleetServiceWorkerPolicy() {
        if (!('serviceWorker' in navigator)) return;
        var isNative = window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform();
        if (isNative) {
            navigator.serviceWorker.getRegistrations().then(function(regs) {
                regs.forEach(function(reg) { reg.unregister(); });
            }).catch(function() {});
            if (window.caches && caches.keys) {
                caches.keys().then(function(keys) {
                    keys.forEach(function(k) { caches.delete(k); });
                }).catch(function() {});
            }
            return;
        }
        window.addEventListener('load', function() {
            navigator.serviceWorker.register('/sw.js?v=6', { scope: '/', updateViaCache: 'none' }).catch(function() {});
        });
    })();

    window.fleetHardReload = function fleetHardReload() {
        if (window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform()) {
            try {
                var u = new URL(window.location.href);
                u.searchParams.set('_fleet_r', String(Date.now()));
                window.location.replace(u.toString());
                return;
            } catch (e) {}
        }
        window.location.reload();
    };

    // ── Mobile Input Enhancements ─────────────────────────────────────────
    (function() {
        var _cap = window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform();
        if (window.innerWidth > 768 && !_cap) return;
        document.querySelectorAll('input[type="text"]').forEach(function(el) {
            var name = (el.name || el.id || '').toLowerCase();
            if (/phone|mobile|contact|cell/.test(name)) {
                el.setAttribute('inputmode', 'tel');
            } else if (/cnic|nic|id_no|id_number/.test(name)) {
                el.setAttribute('inputmode', 'numeric');
                el.setAttribute('pattern', '[0-9-]*');
            } else if (/amount|price|cost|liters|km|quantity|fuel/.test(name)) {
                el.setAttribute('inputmode', 'decimal');
            }
        });
        document.querySelectorAll('input[type="number"]').forEach(function(el) {
            el.setAttribute('inputmode', 'decimal');
        });
    })();

    // ── Lucide Icons Init ──────────────────────────────────────────────────
    if (window.lucide) { lucide.createIcons(); }

    // ── Top Loading Bar (shows on internal navigation) ─────────────────────
    (function() {
        var bar = document.getElementById('topLoadBar');
        if (!bar) return;
        document.addEventListener('click', function(e) {
            var a = e.target.closest('a[href]');
            if (!a) return;
            var href = a.getAttribute('href') || '';
            if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey) return;
            if (href.startsWith('#') || href.startsWith('javascript') || a.getAttribute('target') === '_blank') return;
            bar.classList.add('active');
        });
        window.addEventListener('pageshow', function() { bar.classList.remove('active'); });
    })();

    // Table → Mobile Cards: handled by "MOBILE PERFECT" script + mobile_perfect.css below

    // ── FAB Speed-Dial Toggle (with backdrop) ─────────────────────────────
    (function() {
        var fabBtn = document.getElementById('mobileFabBtn');
        var dialMenu = document.getElementById('fabDialMenu');
        var backdrop = document.getElementById('fabBackdrop');
        if (!fabBtn || !dialMenu) return;
        function openDial() {
            dialMenu.classList.add('open');
            fabBtn.classList.add('open');
            if (backdrop) backdrop.classList.add('show');
            if (window.lucide) lucide.createIcons();
        }
        function closeDial() {
            dialMenu.classList.remove('open');
            fabBtn.classList.remove('open');
            if (backdrop) backdrop.classList.remove('show');
        }
        fabBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            dialMenu.classList.contains('open') ? closeDial() : openDial();
        });
        if (backdrop) backdrop.addEventListener('click', closeDial);
        document.addEventListener('click', function(e) {
            if (dialMenu.classList.contains('open') && !e.target.closest('#mobileFabWrap')) {
                closeDial();
            }
        });
    })();

    // ── Mobile Hamburger + navbar toggle → Sidebar ────────────────────────
    (function() {
        var btn = document.getElementById('mobileMenuBtn');
        var navBtn = document.getElementById('sidebarToggleMobile');
        var sidebar = document.getElementById('sidebar');
        var overlay = document.getElementById('sidebarOverlay');
        if (!sidebar) return;

        function closeSB() { window.fleetCloseMobileSidebar(); }
        function openSB() {
            window.fleetOpenMobileSidebar();
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
        }

        if (btn) {
            btn.addEventListener('click', function() {
                window.fleetToggleMobileSidebar();
            });
        }
        if (navBtn) {
            navBtn.addEventListener('click', function() {
                window.fleetToggleMobileSidebar();
            });
        }

        if (overlay) overlay.addEventListener('click', closeSB);

        /* Mobile drawer: faster menus — skip closing other top-level sections first */
        function tuneMobileSidebarMenus() {
            var native = document.documentElement.classList.contains('capacitor-native');
            var mobile = native || window.innerWidth < 992;
            sidebar.querySelectorAll('#sidebarAccordion > div > .collapse').forEach(function(el) {
                var parent = el.getAttribute('data-bs-parent');
                var saved = el.getAttribute('data-sb-parent');
                if (mobile) {
                    if (parent === '#sidebarAccordion') {
                        el.setAttribute('data-sb-parent', parent);
                        el.removeAttribute('data-bs-parent');
                    }
                } else if (saved) {
                    el.setAttribute('data-bs-parent', saved);
                    el.removeAttribute('data-sb-parent');
                }
            });
        }
        tuneMobileSidebarMenus();
        window.addEventListener('resize', tuneMobileSidebarMenus);

        sidebar.querySelectorAll('a').forEach(function(a) {
            a.addEventListener('click', function(e) {
                var isToggle = a.getAttribute('data-bs-toggle') === 'collapse';
                if (isToggle) {
                    e.preventDefault();
                    return;
                }
                var native = document.documentElement.classList.contains('capacitor-native');
                if (native || window.innerWidth < 992) closeSB();
            });
        });

        window.addEventListener('resize', function() {
            if (window.innerWidth >= 992) closeSB();
        });
    })();

    // ══════════════════════════════════════════════════════════════════════
    //  NATIVE MOBILE FEATURES  (all guarded by Capacitor.isNativePlatform)
    // ══════════════════════════════════════════════════════════════════════

    // ── 0. Banking-Style Biometric T&C Setup (after first manual login) ────
    (function() {
        if (!window.Capacitor || !window.Capacitor.isNativePlatform()) return;
        if (sessionStorage.getItem('fleet_bio_setup') !== '1') return;
        sessionStorage.removeItem('fleet_bio_setup');

        var bioPlugin = window.Capacitor.Plugins && window.Capacitor.Plugins.BiometricAuth;
        if (!bioPlugin) return;

        /* Only show T&C if biometrics are actually available on this device */
        bioPlugin.checkBiometry().then(function(info) {
            var avail = info && (info.strongBiometryIsAvailable || info.biometryIsAvailable || info.isAvailable);
            if (!avail) return;

            var overlay = document.getElementById('bioSetupOverlay');
            if (!overlay) return;
            overlay.style.display = 'flex';

            document.getElementById('bioSetupAccept').addEventListener('click', function() {
                var btn = document.getElementById('bioSetupAccept');
                if (btn) { btn.disabled = true; btn.textContent = 'Setting up…'; }

                /* Step 1: Get HMAC token from server */
                fetch('/auth/biometric-token', { credentials: 'same-origin' })
                    .then(function(r) { return r.json(); })
                    .then(function(d) {
                        if (!d.ok) throw new Error('token_failed');
                        /* Step 2: Verify fingerprint (triggers Android dialog) */
                        return bioPlugin.authenticate({
                            reason: 'Confirm your fingerprint to enable biometric login',
                            cancelTitle: 'Cancel',
                            allowDeviceCredential: false,
                            iosFallbackTitle: 'Cancel'
                        }).then(function() {
                            /* Fingerprint confirmed — store all credentials */
                            localStorage.setItem('fleet_bio_enabled', '1');
                            localStorage.setItem('fleet_bio_token',   d.token);
                            localStorage.setItem('fleet_bio_user',    d.username);
                            localStorage.setItem('fleet_bio_name',    d.display_name || d.username);
                            overlay.style.display = 'none';
                        });
                    }).catch(function() {
                        /* Fingerprint cancelled or failed — still hide overlay */
                        overlay.style.display = 'none';
                        if (btn) { btn.disabled = false; btn.textContent = 'Accept & Enable Biometric Login'; }
                    });
            });

            document.getElementById('bioSetupSkip').addEventListener('click', function() {
                overlay.style.display = 'none';
            });
        }).catch(function() {});
    })();

    // ── 1. Status Bar color to match app theme ────────────────────────────
    (function() {
        if (!window.Capacitor || !window.Capacitor.isNativePlatform()) return;
        document.addEventListener('DOMContentLoaded', function() {
            var SB = window.Capacitor.Plugins && window.Capacitor.Plugins.StatusBar;
            if (!SB) return;
            SB.setBackgroundColor({ color: '#0f172a' }).catch(function(){});
            SB.setStyle({ style: 'DARK' }).catch(function(){});
            SB.setOverlaysWebView({ overlay: false }).catch(function(){});
        });
    })();

    // ── 2. Android / iOS Back Button Handler ──────────────────────────────
    (function() {
        if (!window.Capacitor || !window.Capacitor.isNativePlatform()) return;
        var AppPlugin = window.Capacitor.Plugins && window.Capacitor.Plugins.App;
        if (!AppPlugin) return;

        var backPressCount = 0;
        var backPressTimer = null;
        var DASHBOARD_PATHS = ['/', '/dashboard', '/dashboard/'];

        function isOnDashboard() {
            var p = window.location.pathname.replace(/\/$/, '') || '/';
            return DASHBOARD_PATHS.indexOf(p) !== -1;
        }

        function showExitToast(msg) {
            var old = document.getElementById('nativeToast');
            if (old) old.remove();
            var t = document.createElement('div');
            t.id = 'nativeToast';
            t.textContent = msg || 'Press back again to exit';
            t.style.cssText = [
                'position:fixed;bottom:90px;left:50%;transform:translateX(-50%)',
                'background:#1e293b;color:#f8fafc;padding:11px 24px',
                'border-radius:28px;font-size:0.82rem;font-weight:600',
                'z-index:9999;box-shadow:0 4px 20px rgba(0,0,0,0.35)',
                'letter-spacing:0.02em;pointer-events:none;white-space:nowrap'
            ].join(';');
            document.body.appendChild(t);
            setTimeout(function() { if (t.parentNode) t.remove(); }, 2300);
        }

        function tryCloseOverlay() {
            // Lock overlays: MUST NOT be dismissed by back button
            var bioLock = document.getElementById('bioLockOverlay');
            var pinLock = document.getElementById('pinLockOverlay');
            if ((bioLock && bioLock.style.display === 'flex') ||
                (pinLock && pinLock.style.display === 'flex')) {
                return true; // swallow back press — user must authenticate
            }
            // Bootstrap modals
            var modals = document.querySelectorAll('.modal.show');
            if (modals.length) {
                var m = modals[modals.length - 1];
                var inst = window.bootstrap && bootstrap.Modal ? bootstrap.Modal.getInstance(m) : null;
                if (inst) { inst.hide(); return true; }
            }
            // FAB dial
            var dial = document.getElementById('fabDialMenu');
            if (dial && dial.classList.contains('open')) {
                dial.classList.remove('open');
                var fabBtn = document.getElementById('mobileFabBtn');
                if (fabBtn) fabBtn.classList.remove('open');
                var bd = document.getElementById('fabBackdrop');
                if (bd) bd.classList.remove('show');
                return true;
            }
            // More drawer (bottom sheet)
            var moreOv = document.getElementById('moreDrawerOverlay');
            if (moreOv && moreOv.classList.contains('open') && window.closeMoreDrawer) {
                window.closeMoreDrawer();
                return true;
            }
            // Attend sheet
            var attOv = document.getElementById('attendSheetOverlay');
            if (attOv && attOv.classList.contains('open') && window.closeAttendSheet) {
                window.closeAttendSheet();
                return true;
            }
            // Mobile sidebar
            var sb = document.getElementById('sidebar');
            if (sb && sb.classList.contains('mobile-open')) {
                if (window.fleetCloseMobileSidebar) window.fleetCloseMobileSidebar();
                else {
                    sb.classList.remove('mobile-open');
                    var ov = document.getElementById('sidebarOverlay');
                    if (ov) {
                        ov.classList.remove('show');
                        ov.style.display = '';
                    }
                }
                return true;
            }
            return false;
        }

        AppPlugin.addListener('backButton', function() {
            // Priority 1 — close any open overlay / modal
            if (tryCloseOverlay()) return;

            // Priority 2 — double-tap to exit from dashboard
            if (isOnDashboard()) {
                backPressCount++;
                if (backPressCount >= 2) {
                    clearTimeout(backPressTimer);
                    AppPlugin.exitApp();
                } else {
                    showExitToast('Press back again to exit');
                    backPressTimer = setTimeout(function() { backPressCount = 0; }, 2300);
                }
                return;
            }

            // Priority 3 — normal history back (NEVER exits from a form)
            if (window.history.length > 1) {
                window.history.back();
            } else {
                window.location.href = '/dashboard';
            }
        });
    })();

    // ── 3. No Internet Connection Banner ──────────────────────────────────
    (function() {
        var banner = document.getElementById('no-internet-banner');
        if (!banner) return;
        function update() {
            if (!navigator.onLine) {
                banner.classList.add('show');
                if (window.lucide) lucide.createIcons();
            } else {
                banner.classList.remove('show');
            }
        }
        window.addEventListener('offline', update);
        window.addEventListener('online',  update);
        update();
    })();

    // ── 4. Form Submit: Loading Spinner + Prevent Double Submit ───────────
    (function() {
        document.addEventListener('submit', function(e) {
            var form = e.target;
            if (!form || form.tagName !== 'FORM') return;
            if (form.dataset.noSpinner === '1') return;
            form.querySelectorAll('button[type="submit"]').forEach(function(btn) {
                // Inject spinner if not present
                if (!btn.querySelector('.btn-spinner')) {
                    var sp = document.createElement('span');
                    sp.className = 'btn-spinner';
                    btn.insertBefore(sp, btn.firstChild);
                }
                btn.classList.add('btn-loading');
            });
            // Safety: re-enable after 8 s (server timeout guard)
            setTimeout(function() {
                form.querySelectorAll('.btn-loading').forEach(function(b) {
                    b.classList.remove('btn-loading');
                });
            }, 8000);
        }, true);

        // Restore after back/forward (bfcache) — fixes stuck View "Loading…" on filter pages
        window.addEventListener('pageshow', function() {
            if (window.fleetResetFilterFormButtons) {
                window.fleetResetFilterFormButtons();
            }
            document.querySelectorAll('.btn-loading').forEach(function(b) {
                b.disabled = false;
                b.classList.remove('btn-loading');
            });
        });
    })();

    // ── 5a. WEB: 30-min Inactivity Auto-Logout ────────────────────────────
    (function() {
        if (window.Capacitor && window.Capacitor.isNativePlatform()) return; // mobile handles its own lock
        var TIMEOUT_MS   = 30 * 60 * 1000; // 30 min
        var WARN_MS      = 28 * 60 * 1000; // warn 2 min before
        var warned       = false;
        var warnTimer    = null;
        var logoutTimer  = null;

        function resetTimer() {
            clearTimeout(warnTimer);
            clearTimeout(logoutTimer);
            warned = false;
            var existingWarn = document.getElementById('inactivityWarnBanner');
            if (existingWarn) existingWarn.remove();

            warnTimer = setTimeout(function() {
                if (warned) return;
                warned = true;
                // Show 2-min warning banner
                var b = document.createElement('div');
                b.id = 'inactivityWarnBanner';
                b.innerHTML = '<i class="bi bi-clock" style="font-size:1rem;"></i> Aap 2 minute mein automatically logout ho jaenge. Koi bhi button dabayein.';
                b.style.cssText = 'position:fixed;bottom:70px;left:50%;transform:translateX(-50%);background:#f59e0b;color:#1c1917;padding:10px 20px;border-radius:12px;font-size:0.8rem;font-weight:700;z-index:8888;box-shadow:0 4px 16px rgba(0,0,0,0.2);white-space:nowrap;pointer-events:none;';
                document.body.appendChild(b);
            }, WARN_MS);

            logoutTimer = setTimeout(function() {
                window.location.href = '/logout?inactivity=1';
            }, TIMEOUT_MS);
        }

        ['mousemove','mousedown','keydown','touchstart','scroll','click'].forEach(function(ev) {
            document.addEventListener(ev, resetTimer, { passive: true });
        });
        resetTimer();
    })();

    // ── 5a2. Post-Camera Dropdown Lock — prevents ghost-focus auto-open ──
    window._isReturningFromCamera = false;
    var _cameraLockTimer = null;

    function _fleetTriggerCameraLock() {
        window._isReturningFromCamera = true;
        if (_cameraLockTimer) clearTimeout(_cameraLockTimer);
        _cameraLockTimer = setTimeout(function() {
            window._isReturningFromCamera = false;
        }, 2000);
    }

    function _fleetCloseAllTomSelects() {
        var active = document.activeElement;
        if (active && (active.tagName === 'SELECT' || (active.classList && active.classList.contains('ts-control')))) {
            try { active.blur(); } catch (e) {}
        }
        document.querySelectorAll('select.search-select, select.tom-select').forEach(function(sel) {
            if (sel.tomselect) {
                try { sel.tomselect.close(); } catch (e) {}
                try { sel.tomselect.blur && sel.tomselect.blur(); } catch (e) {}
            }
        });
    }
    window._fleetCloseAllTomSelects = _fleetCloseAllTomSelects;

    // Repeated blur sweep — catches delayed ghost-focus events at 100ms, 500ms, 1000ms
    function _fleetCameraReturnSweep() {
        _fleetCloseAllTomSelects();
        setTimeout(_fleetCloseAllTomSelects, 100);
        setTimeout(_fleetCloseAllTomSelects, 500);
        setTimeout(_fleetCloseAllTomSelects, 1000);
    }

    // Window focus event — fires when WebView regains focus after camera/file picker
    // Only on native mobile (Capacitor) — desktop Alt+Tab should NOT blur focused fields
    window.addEventListener('focus', function() {
        if (!window.Capacitor || !window.Capacitor.isNativePlatform) return;
        if (!window.Capacitor.isNativePlatform()) return;
        _fleetTriggerCameraLock();
        _fleetCameraReturnSweep();
    });

    // visibilitychange — fires when WebView tab becomes visible again
    // Only on native mobile (Capacitor) — desktop Alt+Tab should NOT blur focused fields
    document.addEventListener('visibilitychange', function() {
        if (document.visibilityState !== 'visible') return;
        if (!window.Capacitor || !window.Capacitor.isNativePlatform) return;
        if (!window.Capacitor.isNativePlatform()) return;
        _fleetTriggerCameraLock();
        _fleetCameraReturnSweep();
    });

    // Global Bootstrap modal dismiss listener — silent shield prevents any dropdown flicker
    window._isShieldActive = false;
    document.addEventListener('hide.bs.modal', function() {
        // Activate shield immediately at the START of modal hide animation
        document.body.classList.add('ts-no-open');
        window._isShieldActive = true;
        _fleetTriggerCameraLock();
        try { document.activeElement && document.activeElement.blur(); } catch (e) {}
        _fleetCloseAllTomSelects();
    });
    document.addEventListener('hidden.bs.modal', function() {
        // Keep shield active through focus restoration, then remove after 1000ms
        setTimeout(_fleetCloseAllTomSelects, 50);
        setTimeout(_fleetCloseAllTomSelects, 300);
        setTimeout(function() {
            document.body.classList.remove('ts-no-open');
            window._isShieldActive = false;
        }, 1000);
    });

    // ── 5b. MOBILE: Biometric / PIN Lock on App Resume ────────────────────
    (function() {
        if (!window.Capacitor || !window.Capacitor.isNativePlatform()) return;

        var AppPlugin = window.Capacitor.Plugins && window.Capacitor.Plugins.App;
        var bioPlugin = window.Capacitor.Plugins && window.Capacitor.Plugins.BiometricAuth;
        if (!AppPlugin) return;

        var BIO_KEY   = 'fleet_bio_enabled';
        var TOKEN_KEY = 'fleet_bio_token';
        var USER_KEY  = 'fleet_bio_user';
        var PIN_KEY   = 'fleet_pin_hash';
        var PIN_SET_KEY = 'fleet_pin_set';

        var bioOverlay = document.getElementById('bioLockOverlay');
        var pinOverlay = document.getElementById('pinLockOverlay');
        var bioLockBtn = document.getElementById('bioLockBtn');
        var bioUsePIN  = document.getElementById('bioLockUsePIN');
        var isLocked   = false;

        /* ── SHA-256 (tiny pure-JS, no external dep needed) ── */
        function sha256hex(str) {
            /* Use SubtleCrypto when available (all modern browsers/Capacitor) */
            var enc = new TextEncoder();
            return crypto.subtle.digest('SHA-256', enc.encode(str)).then(function(buf) {
                return Array.from(new Uint8Array(buf)).map(function(b) {
                    return b.toString(16).padStart(2, '0');
                }).join('');
            });
        }

        /* ── PIN UI ── */
        var pinBuffer = '';
        var pinMode   = 'verify'; // 'set' or 'verify'
        var pinFirst  = '';

        function updateDots() {
            var dots = document.querySelectorAll('#pinDots .pin-dot');
            dots.forEach(function(d, i) { d.classList.toggle('filled', i < pinBuffer.length); });
        }

        function shakeOverlay() {
            var o = document.getElementById('pinDots');
            if (!o) return;
            o.style.animation = 'none';
            setTimeout(function() { o.style.animation = 'pinShake 0.4s ease'; }, 10);
        }

        function pinDigit(v) {
            if (pinBuffer.length >= 4) return;
            pinBuffer += v;
            updateDots();
            if (pinBuffer.length === 4) {
                setTimeout(function() { submitPIN(); }, 80);
            }
        }

        function pinDel() {
            pinBuffer = pinBuffer.slice(0, -1);
            updateDots();
        }

        function submitPIN() {
            var entered = pinBuffer;
            pinBuffer = '';
            updateDots();
            sha256hex(entered).then(function(hash) {
                if (pinMode === 'set') {
                    if (!pinFirst) {
                        pinFirst = hash;
                        var title = document.getElementById('pinLockTitle');
                        var sub   = document.getElementById('pinLockSub');
                        if (title) title.textContent = 'Confirm PIN';
                        if (sub)   sub.textContent   = 'Enter the same PIN again';
                    } else {
                        if (hash === pinFirst) {
                            localStorage.setItem(PIN_KEY, hash);
                            localStorage.setItem(PIN_SET_KEY, '1');
                            hidePINOverlay();
                            hideBioOverlay();
                        } else {
                            pinFirst = '';
                            var errEl = document.getElementById('pinErrMsg');
                            if (errEl) errEl.textContent = 'PINs did not match. Try again.';
                            shakeOverlay();
                            setTimeout(function() { if (errEl) errEl.textContent = ''; }, 2000);
                            var title2 = document.getElementById('pinLockTitle');
                            var sub2   = document.getElementById('pinLockSub');
                            if (title2) title2.textContent = 'Set a 4-digit PIN';
                            if (sub2)   sub2.textContent   = 'Enter a new PIN to unlock the app';
                        }
                    }
                } else {
                    var stored = localStorage.getItem(PIN_KEY);
                    if (stored && hash === stored) {
                        hidePINOverlay();
                        hideBioOverlay();
                    } else {
                        var errEl2 = document.getElementById('pinErrMsg');
                        if (errEl2) errEl2.textContent = 'Incorrect PIN. Try again.';
                        shakeOverlay();
                        setTimeout(function() { if (errEl2) errEl2.textContent = ''; }, 2000);
                    }
                }
            }).catch(function() {});
        }

        /* Wire numpad */
        var numpad = document.getElementById('pinNumpad');
        if (numpad) {
            numpad.addEventListener('click', function(e) {
                var key = e.target.closest('.pin-key');
                if (!key) return;
                if (key.id === 'pinKeyDel') { pinDel(); return; }
                if (key.id === 'pinKeyBio') { hidePINOverlay(); triggerBioLock(); return; }
                var v = key.getAttribute('data-v');
                if (v !== null && v !== '') pinDigit(v);
            });
        }

        /* ── Show/Hide helpers ── */
        function showBioOverlay() {
            isLocked = true;
            if (bioOverlay) bioOverlay.style.display = 'flex';
        }
        function hideBioOverlay() {
            isLocked = false;
            if (bioOverlay) bioOverlay.style.display = 'none';
        }
        function showPINOverlay(mode) {
            pinMode   = mode || 'verify';
            pinBuffer = '';
            pinFirst  = '';
            updateDots();
            var title = document.getElementById('pinLockTitle');
            var sub   = document.getElementById('pinLockSub');
            var err   = document.getElementById('pinErrMsg');
            if (err) err.textContent = '';
            if (mode === 'set') {
                if (title) title.textContent = 'Set a 4-digit PIN';
                if (sub)   sub.textContent   = 'Choose a PIN to unlock the app';
                var biobtn = document.getElementById('pinKeyBio');
                if (biobtn) biobtn.style.display = 'none';
            } else {
                if (title) title.textContent = 'Enter PIN';
                if (sub)   sub.textContent   = 'Enter your 4-digit PIN to unlock';
            }
            if (pinOverlay) pinOverlay.style.display = 'flex';
        }
        function hidePINOverlay() {
            if (pinOverlay) pinOverlay.style.display = 'none';
        }

        /* ── Core: trigger biometric auth ── */
        function triggerBioLock() {
            if (!bioPlugin) { fallbackToPin(); return; }
            bioPlugin.checkBiometry().then(function(info) {
                var avail = info && (info.strongBiometryIsAvailable || info.biometryIsAvailable || info.isAvailable);
                if (!avail) { fallbackToPin(); return; }
                showBioOverlay();
                bioPlugin.authenticate({
                    reason: 'Verify your identity to open Fleet Manager',
                    cancelTitle: 'Use PIN',
                    allowDeviceCredential: false,
                    iosFallbackTitle: 'Use PIN'
                }).then(function() {
                    hideBioOverlay();
                }).catch(function(err) {
                    if (err && (err.code === 'biometricCanceled' || err.code === 10)) {
                        /* User tapped "Use PIN" */
                        fallbackToPin();
                    } else {
                        fallbackToPin();
                    }
                });
            }).catch(function() { fallbackToPin(); });
        }

        function fallbackToPin() {
            var pinSet = localStorage.getItem(PIN_SET_KEY) === '1';
            if (pinSet) {
                showPINOverlay('verify');
            } else {
                showPINOverlay('set');
            }
        }

        /* "Use PIN instead" link on bio overlay */
        if (bioUsePIN) {
            bioUsePIN.addEventListener('click', function() {
                hideBioOverlay();
                fallbackToPin();
            });
        }

        /* Bio lock button: retry biometric */
        if (bioLockBtn) {
            bioLockBtn.addEventListener('click', function() {
                if (!bioPlugin) { fallbackToPin(); return; }
                bioPlugin.authenticate({
                    reason: 'Verify your identity to open Fleet Manager',
                    cancelTitle: 'Use PIN',
                    allowDeviceCredential: false,
                    iosFallbackTitle: 'Use PIN'
                }).then(function() {
                    hideBioOverlay();
                }).catch(function() { fallbackToPin(); });
            });
        }

        /* ── Bio/PIN lock on app resume (full login only on cold start via /mobile-init) ── */
        var _firstActivation = true;

        AppPlugin.addListener('appStateChange', function(state) {
            if (state && !state.isActive) {
                return;
            }

            // ── Close all TomSelect dropdowns on app resume (fixes auto-open after camera return) ──
            _fleetTriggerCameraLock();
            _fleetCameraReturnSweep();

            if (_firstActivation) { _firstActivation = false; return; }

            var hasBio = localStorage.getItem(BIO_KEY) === '1' && localStorage.getItem(TOKEN_KEY);
            if (hasBio) {
                triggerBioLock();
            } else {
                var pinSet = localStorage.getItem(PIN_SET_KEY) === '1';
                if (pinSet) { isLocked = true; fallbackToPin(); }
            }
        });

        /* Shake CSS */
        var style = document.createElement('style');
        style.textContent = '@keyframes pinShake{0%,100%{transform:translateX(0)}20%{transform:translateX(-8px)}40%{transform:translateX(8px)}60%{transform:translateX(-5px)}80%{transform:translateX(5px)}}';
        document.head.appendChild(style);
    })();

    // ── 5c. MOBILE: Back Button must NOT dismiss lock overlays ────────────
    // (This guard is injected AFTER section 2's AppPlugin listener; the
    //  tryCloseOverlay() fn above is patched to return true for lock overlays)
    (function() {
        if (!window.Capacitor || !window.Capacitor.isNativePlatform()) return;
        var _orig = window._tryCloseOverlay || null;
        /* Override: if lock overlay visible → swallow back press */
        var bioO = document.getElementById('bioLockOverlay');
        var pinO = document.getElementById('pinLockOverlay');
        document.addEventListener('__backButton__', function() {}, false);
        // Patch the existing tryCloseOverlay by hooking into it via a sentinel DOM check
        // The back button handler in section 2 calls tryCloseOverlay().
        // We add a check at the START of tryCloseOverlay by injecting a <meta> flag.
        // Simpler approach: add the lock overlay check via the existing section-2 tryCloseOverlay.
        // Since we can't easily monkey-patch it, we rely on the overlay z-index > 9999
        // and the handler below that runs FIRST by being added to the same event stream.
        var AppPlugin = window.Capacitor.Plugins && window.Capacitor.Plugins.App;
        if (!AppPlugin) return;
        AppPlugin.addListener('backButton', function(ev) {
            var bioVisible = bioO && bioO.style.display === 'flex';
            var pinVisible = pinO && pinO.style.display === 'flex';
            if (bioVisible || pinVisible) {
                /* Swallow — user MUST authenticate, cannot back out of the lock */
                return;
            }
        });
    })();

    // ── 5. Native Sticky Submit Buttons (Thumb Zone) ─────────────────────
    (function() {
        if (!window.Capacitor || !window.Capacitor.isNativePlatform()) return;
        document.addEventListener('DOMContentLoaded', function() {
            var content = document.querySelector('.main-content');
            if (!content) return;
            content.querySelectorAll('form').forEach(function(form) {
                // Skip nav/fab forms
                if (form.closest('.mobile-bottom-nav, .mobile-fab-wrap, .navbar, #sidebar')) return;
                // Skip inline delete/action forms inside table rows (e.g. delete buttons in list views)
                if (form.closest('tr, td, thead, tbody, table')) return;
                if (form.style.display === 'inline') return;
                // Skip filter / search forms: these use GET and the submit button (e.g. "Load Vehicles")
                // sits inline next to fields. Pinning it to the thumb zone made it float OVER the
                // adjacent field. The thumb-zone sticky bar is only for primary data-entry (POST) submits.
                if ((form.getAttribute('method') || 'get').toLowerCase() === 'get') return;
                // Explicit opt-out for any form that should never get a sticky submit bar.
                if (form.matches('.no-sticky-submit, [data-no-sticky]') ||
                    form.closest('.no-sticky-submit, [data-no-sticky]')) return;
                // Find last .d-grid that contains a submit button
                var grids = form.querySelectorAll('.d-grid');
                var target = null;
                for (var i = grids.length - 1; i >= 0; i--) {
                    if (grids[i].querySelector('button[type="submit"]')) {
                        target = grids[i];
                        break;
                    }
                }
                if (!target) {
                    // Fallback: parent of last submit button
                    var btns = form.querySelectorAll('button[type="submit"]');
                    if (btns.length) target = btns[btns.length - 1].parentElement;
                }
                // Never pin an inline grid column — it would overlap sibling fields in the same row.
                if (target && target.matches('[class*="col-"]') &&
                    target.closest('.row') &&
                    target.closest('.row').querySelectorAll('[class*="col-"]').length > 1) return;
                if (target) target.classList.add('native-submit-sticky');
            });
        });
    })();