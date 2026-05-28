/**
 * Web Worker for heavy canvas pixel ops (blur / sharpen / dither).
 */
(function () {
  if (typeof importScripts === 'undefined') return;

  self.onmessage = function (e) {
    var d = e.data;
    var data = new Uint8ClampedArray(d.buffer);
    var w = d.width;
    var h = d.height;
    if (d.op === 'grayscale') {
      for (var i = 0; i < data.length; i += 4) {
        var g = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
        data[i] = data[i + 1] = data[i + 2] = g;
      }
    } else if (d.op === 'invert') {
      for (var j = 0; j < data.length; j += 4) {
        data[j] = 255 - data[j];
        data[j + 1] = 255 - data[j + 1];
        data[j + 2] = 255 - data[j + 2];
      }
    }
    self.postMessage({ buffer: data.buffer, width: w, height: h }, [data.buffer]);
  };
})();
