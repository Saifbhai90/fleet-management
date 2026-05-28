/**
 * Boot individual tool page — dispatch to image / pdf / text engine.
 */
document.addEventListener('DOMContentLoaded', function () {
  var tool = window.TW_TOOL;
  var mount = document.getElementById('twToolMount');
  if (!tool || !mount) return;

  function run() {
    if (tool.engine === 'image' && window.TWImageEngine) {
      window.TWImageEngine.init(mount, tool);
    } else if (tool.engine === 'pdf' && window.TWPdfEngine) {
      window.TWPdfEngine.init(mount, tool);
    } else if (tool.engine === 'text' && window.TWTextEngine) {
      window.TWTextEngine.init(mount, tool);
    } else {
      mount.innerHTML = '<p class="tw-status error">Engine not loaded. Refresh the page.</p>';
    }
  }

  if (tool.engine === 'pdf') {
    var t = setInterval(function () {
      if (window.PDFLib && (window.jspdf || window.jsPDF)) {
        clearInterval(t);
        run();
      }
    }, 100);
    setTimeout(function () { clearInterval(t); run(); }, 8000);
  } else {
    run();
  }
});
