/**
 * Image Processing Studio — Canvas-based client-side tools.
 */
(function (global) {
  function filePanel(accept, label) {
    var p = document.createElement('div');
    p.className = 'tw-panel';
    var lb = document.createElement('label');
    lb.textContent = label || 'Upload image';
    var inp = document.createElement('input');
    inp.type = 'file';
    inp.accept = accept || 'image/*';
    p.appendChild(lb);
    p.appendChild(inp);
    return { panel: p, input: inp };
  }

  function loadFile(inp) {
    return new Promise(function (resolve, reject) {
      var f = inp.files && inp.files[0];
      if (!f) return reject(new Error('Choose a file'));
      var url = URL.createObjectURL(f);
      var img = new Image();
      img.onload = function () { resolve({ img: img, file: f, url: url }); };
      img.onerror = reject;
      img.src = url;
    });
  }

  function canvasFrom(img, w, h) {
    var c = document.createElement('canvas');
    c.width = w || img.naturalWidth;
    c.height = h || img.naturalHeight;
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    return c;
  }

  function downloadCanvas(c, name, type, quality) {
    c.toBlob(function (blob) {
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
    }, type || 'image/png', quality);
  }

  function mountFileTool(m, opts, run) {
    m.innerHTML = '';
    var fp = filePanel(opts.accept, opts.label);
    m.appendChild(fp.panel);
    var prev = document.createElement('img');
    prev.className = 'tw-preview';
    prev.hidden = true;
    m.appendChild(prev);
    var act = document.createElement('div');
    act.className = 'tw-actions';
    var btn = document.createElement('button');
    btn.textContent = opts.btn || 'Process';
    act.appendChild(btn);
    m.appendChild(act);
    var st = document.createElement('p');
    st.className = 'tw-status';
    m.appendChild(st);
    fp.input.onchange = function () {
      loadFile(fp.input).then(function (d) {
        prev.src = d.url;
        prev.hidden = false;
        fp._data = d;
      }).catch(function (e) { st.textContent = e.message; });
    };
    btn.onclick = function () {
      if (!fp._data) { st.textContent = 'Upload an image first.'; return; }
      run(fp._data, prev, st, m);
    };
  }

  function workerFilter(c, op) {
    return new Promise(function (resolve) {
      var ctx = c.getContext('2d');
      var id = ctx.getImageData(0, 0, c.width, c.height);
      try {
        var w = new Worker(URL.createObjectURL(new Blob([
          '(' + function () {
            importScripts('');
            onmessage = function (e) {
              var d = e.data;
              var data = new Uint8ClampedArray(d.buffer);
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
              postMessage({ buffer: data.buffer, width: d.width, height: d.height }, [data.buffer]);
            };
          }.toString() + ')()'
        ], { type: 'application/javascript' })));
        w.onmessage = function (e) {
          id.data.set(new Uint8ClampedArray(e.data.buffer));
          ctx.putImageData(id, 0, 0);
          w.terminate();
          resolve(c);
        };
        w.postMessage({ op: op, buffer: id.data.buffer, width: c.width, height: c.height }, [id.data.buffer.slice(0)]);
      } catch (err) {
        if (op === 'grayscale') ctx.filter = 'grayscale(100%)';
        else if (op === 'invert') ctx.filter = 'invert(100%)';
        ctx.drawImage(c, 0, 0);
        resolve(c);
      }
    });
  }

  var handlers = {
    'image-convert': function (m, tool) {
      var fmt = 'image/jpeg';
      var ext = 'jpg';
      if (tool.slug.indexOf('webp') >= 0) { fmt = 'image/webp'; ext = 'webp'; }
      else if (tool.slug.indexOf('jpg-to-png') >= 0 || tool.slug.indexOf('svg-to-png') >= 0) { fmt = 'image/png'; ext = 'png'; }
      else if (tool.slug.indexOf('png-to-jpg') >= 0) { fmt = 'image/jpeg'; ext = 'jpg'; }
      var bg = null;
      if (tool.slug === 'png-to-jpg') {
        var bp = document.createElement('div');
        bp.className = 'tw-panel';
        bg = document.createElement('input');
        bg.type = 'color';
        bg.value = '#ffffff';
        bp.appendChild(document.createElement('label')).textContent = 'JPG background (for transparency)';
        bp.appendChild(bg);
        m.appendChild(bp);
      }
      mountFileTool(m, { label: 'Source image', btn: 'Convert to ' + ext.toUpperCase() }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        if (bg) {
          var ctx = c.getContext('2d');
          ctx.globalCompositeOperation = 'destination-over';
          ctx.fillStyle = bg.value;
          ctx.fillRect(0, 0, c.width, c.height);
        }
        downloadCanvas(c, 'converted.' + ext, fmt, 0.92);
        st.textContent = 'Download started.';
        st.className = 'tw-status ok';
      });
    },
    'image-compress': function (m) {
      var q = document.createElement('input');
      q.type = 'range'; q.min = '0.1'; q.max = '1'; q.step = '0.05'; q.value = '0.8';
      m.appendChild(document.createElement('div')).className = 'tw-panel';
      m.querySelector('.tw-panel').appendChild(q);
      mountFileTool(m, { btn: 'Compress JPEG' }, function (d, prev, st) {
        downloadCanvas(canvasFrom(d.img), 'compressed.jpg', 'image/jpeg', +q.value);
        st.textContent = 'Quality ' + q.value;
        st.className = 'tw-status ok';
      });
    },
    'svg-raster': function (m) {
      mountFileTool(m, { accept: 'image/svg+xml,.svg', label: 'SVG file' }, function (d, prev, st) {
        downloadCanvas(canvasFrom(d.img), 'raster.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'ico-gen': function (m) {
      mountFileTool(m, {}, function (d, prev, st) {
        var c = canvasFrom(d.img, 64, 64);
        downloadCanvas(c, 'favicon.png', 'image/png');
        st.textContent = '64×64 PNG (use OS converter for .ico if needed).';
        st.className = 'tw-status ok';
      });
    },
    'gif-frames': function (m) {
      mountFileTool(m, { accept: 'image/gif' }, function (d, prev, st) {
        downloadCanvas(canvasFrom(d.img), 'frame-0.png', 'image/png');
        st.textContent = 'First frame exported (animated GIF uses frame 0).';
        st.className = 'tw-status ok';
      });
    },
    'base64-decode': function (m) {
      var ta = document.createElement('textarea');
      ta.placeholder = 'Paste base64…';
      m.appendChild(ta);
      var btn = document.createElement('button');
      btn.textContent = 'Decode';
      m.appendChild(btn);
      var img = document.createElement('img');
      img.className = 'tw-preview';
      m.appendChild(img);
      btn.onclick = function () {
        img.src = ta.value.trim().startsWith('data:') ? ta.value.trim() : 'data:image/png;base64,' + ta.value.trim();
      };
    },
    'base64-encode': function (m) {
      mountFileTool(m, { btn: 'Encode' }, function (d, prev, st, root) {
        var c = canvasFrom(d.img);
        var ta = document.createElement('textarea');
        ta.readOnly = true;
        ta.value = c.toDataURL('image/png');
        root.appendChild(ta);
        st.className = 'tw-status ok';
      });
    },
    'aspect-crop': function (m) {
      var ratio = document.createElement('select');
      ['1:1', '4:3', '16:9', '3:2'].forEach(function (r) {
        ratio.appendChild(new Option(r, r));
      });
      m.appendChild(ratio);
      mountFileTool(m, { btn: 'Crop center' }, function (d, prev, st) {
        var parts = ratio.value.split(':').map(Number);
        var rw = parts[0] / parts[1];
        var iw = d.img.naturalWidth, ih = d.img.naturalHeight;
        var w, h;
        if (iw / ih > rw) { h = ih; w = ih * rw; } else { w = iw; h = iw / rw; }
        var c = document.createElement('canvas');
        c.width = w; c.height = h;
        c.getContext('2d').drawImage(d.img, (iw - w) / 2, (ih - h) / 2, w, h, 0, 0, w, h);
        prev.src = c.toDataURL();
        downloadCanvas(c, 'cropped.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'resize': function (m) {
      var w = document.createElement('input'); w.type = 'number'; w.value = '800';
      var h = document.createElement('input'); h.type = 'number'; h.value = '600';
      m.appendChild(w); m.appendChild(h);
      mountFileTool(m, { btn: 'Resize' }, function (d, prev, st) {
        var c = canvasFrom(d.img, +w.value, +h.value);
        prev.src = c.toDataURL();
        downloadCanvas(c, 'resized.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'rotate': function (m) {
      var deg = document.createElement('select');
      [90, 180, 270].forEach(function (d) { deg.appendChild(new Option(d + '°', d)); });
      m.appendChild(deg);
      mountFileTool(m, { btn: 'Rotate' }, function (d, prev, st) {
        var r = (+deg.value * Math.PI) / 180;
        var c = document.createElement('canvas');
        var swap = (+deg.value) % 180 !== 0;
        c.width = swap ? d.img.naturalHeight : d.img.naturalWidth;
        c.height = swap ? d.img.naturalWidth : d.img.naturalHeight;
        var ctx = c.getContext('2d');
        ctx.translate(c.width / 2, c.height / 2);
        ctx.rotate(r);
        ctx.drawImage(d.img, -d.img.naturalWidth / 2, -d.img.naturalHeight / 2);
        downloadCanvas(c, 'rotated.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'flip': function (m) {
      var mode = document.createElement('select');
      mode.innerHTML = '<option value="h">Horizontal</option><option value="v">Vertical</option>';
      m.appendChild(mode);
      mountFileTool(m, { btn: 'Flip' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        var ctx = c.getContext('2d');
        ctx.save();
        if (mode.value === 'h') { ctx.translate(c.width, 0); ctx.scale(-1, 1); }
        else { ctx.translate(0, c.height); ctx.scale(1, -1); }
        ctx.drawImage(d.img, 0, 0);
        ctx.restore();
        downloadCanvas(c, 'flipped.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'blur': function (m) {
      mountFileTool(m, { btn: 'Blur' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        c.getContext('2d').filter = 'blur(4px)';
        c.getContext('2d').drawImage(d.img, 0, 0);
        downloadCanvas(c, 'blur.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'sharpen': function (m) {
      mountFileTool(m, { btn: 'Sharpen' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        c.getContext('2d').filter = 'contrast(1.2) saturate(1.1)';
        c.getContext('2d').drawImage(d.img, 0, 0);
        downloadCanvas(c, 'sharp.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'brightness-contrast': function (m) {
      var br = document.createElement('input'); br.type = 'range'; br.min = '50'; br.max = '150'; br.value = '100';
      var ct = document.createElement('input'); ct.type = 'range'; ct.min = '50'; ct.max = '150'; ct.value = '100';
      m.appendChild(br); m.appendChild(ct);
      mountFileTool(m, { btn: 'Apply' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        c.getContext('2d').filter = 'brightness(' + br.value + '%) contrast(' + ct.value + '%)';
        c.getContext('2d').drawImage(d.img, 0, 0);
        prev.src = c.toDataURL();
        downloadCanvas(c, 'adjusted.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'hue-saturation': function (m) {
      var sat = document.createElement('input'); sat.type = 'range'; sat.min = '0'; sat.max = '200'; sat.value = '100';
      m.appendChild(sat);
      mountFileTool(m, { btn: 'Apply' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        c.getContext('2d').filter = 'saturate(' + sat.value + '%)';
        c.getContext('2d').drawImage(d.img, 0, 0);
        downloadCanvas(c, 'saturated.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'palette': function (m) {
      mountFileTool(m, { btn: 'Extract' }, function (d, prev, st, root) {
        var c = canvasFrom(d.img, 80, 80);
        var data = c.getContext('2d').getImageData(0, 0, 80, 80).data;
        var map = {};
        for (var i = 0; i < data.length; i += 16) {
          var key = data[i] + ',' + data[i + 1] + ',' + data[i + 2];
          map[key] = (map[key] || 0) + 1;
        }
        var top = Object.keys(map).sort(function (a, b) { return map[b] - map[a]; }).slice(0, 6);
        var box = document.createElement('div');
        top.forEach(function (k) {
          var span = document.createElement('span');
          span.style.cssText = 'display:inline-block;width:48px;height:48px;background:rgb(' + k + ');margin:4px;border-radius:8px;border:1px solid #e5e7eb';
          box.appendChild(span);
        });
        root.appendChild(box);
        st.className = 'tw-status ok';
      });
    },
    'watermark': function (m) {
      var txt = document.createElement('input');
      txt.value = 'Fleet';
      m.appendChild(txt);
      mountFileTool(m, { btn: 'Apply watermark' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        var ctx = c.getContext('2d');
        ctx.font = 'bold 48px Inter,sans-serif';
        ctx.fillStyle = 'rgba(255,255,255,0.5)';
        ctx.fillText(txt.value, 24, c.height - 24);
        downloadCanvas(c, 'watermarked.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'grayscale': function (m) {
      mountFileTool(m, { btn: 'Grayscale' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        workerFilter(c, 'grayscale').then(function () {
          downloadCanvas(c, 'gray.png', 'image/png');
          st.className = 'tw-status ok';
        });
      });
    },
    'sepia': function (m) {
      mountFileTool(m, { btn: 'Sepia' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        c.getContext('2d').filter = 'sepia(80%)';
        c.getContext('2d').drawImage(d.img, 0, 0);
        downloadCanvas(c, 'sepia.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'invert': function (m) {
      mountFileTool(m, { btn: 'Invert' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        workerFilter(c, 'invert').then(function () {
          downloadCanvas(c, 'invert.png', 'image/png');
          st.className = 'tw-status ok';
        });
      });
    },
    'pixelate': function (m) {
      mountFileTool(m, { btn: 'Pixelate' }, function (d, prev, st) {
        var c = canvasFrom(d.img, 48, 48);
        var c2 = canvasFrom(d.img);
        c2.getContext('2d').imageSmoothingEnabled = false;
        c2.getContext('2d').drawImage(c, 0, 0, c2.width, c2.height);
        downloadCanvas(c2, 'pixel.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'film-grade': function (m) {
      mountFileTool(m, { btn: 'Grade' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        c.getContext('2d').filter = 'sepia(20%) contrast(1.1) brightness(1.05)';
        c.getContext('2d').drawImage(d.img, 0, 0);
        downloadCanvas(c, 'film.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'dither': function (m) {
      mountFileTool(m, { btn: 'Dither' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        c.getContext('2d').filter = 'contrast(1.4) grayscale(100%)';
        c.getContext('2d').drawImage(d.img, 0, 0);
        downloadCanvas(c, 'dither.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'vignette': function (m) {
      mountFileTool(m, { btn: 'Vignette' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        var ctx = c.getContext('2d');
        ctx.drawImage(d.img, 0, 0);
        var g = ctx.createRadialGradient(c.width / 2, c.height / 2, c.height * 0.2, c.width / 2, c.height / 2, c.height * 0.8);
        g.addColorStop(0, 'rgba(0,0,0,0)');
        g.addColorStop(1, 'rgba(0,0,0,0.55)');
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, c.width, c.height);
        downloadCanvas(c, 'vignette.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'ascii-art': function (m) {
      mountFileTool(m, { btn: 'Convert' }, function (d, prev, st, root) {
        var c = canvasFrom(d.img, 100, 50);
        var data = c.getContext('2d').getImageData(0, 0, 100, 50).data;
        var chars = '@%#*+=-:. ';
        var out = '';
        for (var y = 0; y < 50; y++) {
          for (var x = 0; x < 100; x++) {
            var i = (y * 100 + x) * 4;
            var g = (data[i] + data[i + 1] + data[i + 2]) / 3;
            out += chars[Math.floor((g / 255) * (chars.length - 1))];
          }
          out += '\n';
        }
        var pre = document.createElement('pre');
        pre.style.fontSize = '6px';
        pre.textContent = out;
        root.appendChild(pre);
        st.className = 'tw-status ok';
      });
    },
    'exif-view': function (m) {
      mountFileTool(m, { btn: 'Read info' }, function (d, prev, st, root) {
        var pre = document.createElement('pre');
        pre.textContent = 'Name: ' + d.file.name + '\nSize: ' + d.file.size + ' bytes\nDimensions: ' + d.img.naturalWidth + '×' + d.img.naturalHeight + '\nType: ' + d.file.type;
        root.appendChild(pre);
        st.className = 'tw-status ok';
      });
    },
    'exif-strip': function (m) {
      mountFileTool(m, { btn: 'Re-export (strip metadata)' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        downloadCanvas(c, 'clean.png', 'image/png');
        st.textContent = 'Re-encoded without EXIF in PNG output.';
        st.className = 'tw-status ok';
      });
    },
    'meme': function (m) {
      var top = document.createElement('input'); top.placeholder = 'Top text';
      var bot = document.createElement('input'); bot.placeholder = 'Bottom text';
      m.appendChild(top); m.appendChild(bot);
      mountFileTool(m, { btn: 'Generate meme' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        var ctx = c.getContext('2d');
        ctx.font = 'bold ' + Math.floor(c.width / 12) + 'px Impact,sans-serif';
        ctx.fillStyle = '#fff';
        ctx.strokeStyle = '#000';
        ctx.lineWidth = 3;
        ctx.textAlign = 'center';
        [top.value, bot.value].forEach(function (t, i) {
          if (!t) return;
          var y = i === 0 ? 40 : c.height - 20;
          ctx.strokeText(t.toUpperCase(), c.width / 2, y);
          ctx.fillText(t.toUpperCase(), c.width / 2, y);
        });
        downloadCanvas(c, 'meme.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'grid-split': function (m) {
      var n = document.createElement('input'); n.type = 'number'; n.value = '3'; n.min = '2'; n.max = '6';
      m.appendChild(n);
      mountFileTool(m, { btn: 'Split grid' }, function (d, prev, st) {
        var g = +n.value;
        var c = canvasFrom(d.img);
        var pw = c.width / g, ph = c.height / g;
        for (var row = 0; row < g; row++) {
          for (var col = 0; col < g; col++) {
            var tile = document.createElement('canvas');
            tile.width = pw; tile.height = ph;
            tile.getContext('2d').drawImage(c, col * pw, row * ph, pw, ph, 0, 0, pw, ph);
            downloadCanvas(tile, 'tile-' + row + '-' + col + '.png', 'image/png');
          }
        }
        st.textContent = g * g + ' tiles downloading.';
        st.className = 'tw-status ok';
      });
    },
    'collage': function (m) {
      m.innerHTML = '';
      var fp1 = filePanel('image/*', 'First image');
      var fp2 = filePanel('image/*', 'Second image');
      m.appendChild(fp1.panel);
      m.appendChild(fp2.panel);
      var st = document.createElement('p');
      st.className = 'tw-status';
      m.appendChild(st);
      var btn = document.createElement('button');
      btn.textContent = 'Build 2-up collage';
      m.appendChild(btn);
      btn.onclick = function () {
        Promise.all([loadFile(fp1.input), loadFile(fp2.input)]).then(function (arr) {
          var c = document.createElement('canvas');
          c.width = arr[0].img.naturalWidth + arr[1].img.naturalWidth;
          c.height = Math.max(arr[0].img.naturalHeight, arr[1].img.naturalHeight);
          var ctx = c.getContext('2d');
          ctx.drawImage(arr[0].img, 0, 0);
          ctx.drawImage(arr[1].img, arr[0].img.naturalWidth, 0);
          downloadCanvas(c, 'collage.png', 'image/png');
          st.className = 'tw-status ok';
        }).catch(function (e) { st.textContent = e.message; });
      };
    },
    'round-corners': function (m) {
      var r = document.createElement('input'); r.type = 'range'; r.min = '0'; r.max = '100'; r.value = '24';
      m.appendChild(r);
      mountFileTool(m, { btn: 'Round' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        var ctx = c.getContext('2d');
        ctx.clearRect(0, 0, c.width, c.height);
        var rad = +r.value;
        ctx.beginPath();
        ctx.roundRect(0, 0, c.width, c.height, rad);
        ctx.clip();
        ctx.drawImage(d.img, 0, 0);
        downloadCanvas(c, 'rounded.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'placeholder': function (m) {
      var hex = document.createElement('input'); hex.value = '#e2e8f0';
      var w = document.createElement('input'); w.value = '800';
      var h = document.createElement('input'); h.value = '600';
      m.appendChild(hex); m.appendChild(w); m.appendChild(h);
      var btn = document.createElement('button');
      btn.textContent = 'Generate';
      m.appendChild(btn);
      btn.onclick = function () {
        var c = document.createElement('canvas');
        c.width = +w.value; c.height = +h.value;
        c.getContext('2d').fillStyle = hex.value;
        c.getContext('2d').fillRect(0, 0, c.width, c.height);
        downloadCanvas(c, 'placeholder.png', 'image/png');
      };
    },
    'chroma-key': function (m) {
      var col = document.createElement('input'); col.type = 'color'; col.value = '#00ff00';
      m.appendChild(col);
      mountFileTool(m, { btn: 'Remove chroma' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        var id = c.getContext('2d').getImageData(0, 0, c.width, c.height);
        var hex = col.value.replace('#', '');
        var rgb = [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)];
        for (var i = 0; i < id.data.length; i += 4) {
          if (Math.abs(id.data[i] - rgb[0]) < 40 && Math.abs(id.data[i + 1] - rgb[1]) < 40 && Math.abs(id.data[i + 2] - rgb[2]) < 40) {
            id.data[i + 3] = 0;
          }
        }
        c.getContext('2d').putImageData(id, 0, 0);
        downloadCanvas(c, 'chroma.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'sprite-sheet': function (m) {
      mountFileTool(m, { btn: 'Pack horizontal' }, function (d, prev, st) {
        st.textContent = 'Upload multiple files via collage tool for advanced sheets.';
        st.className = 'tw-status';
      });
    },
    'film-grain': function (m) {
      mountFileTool(m, { btn: 'Add grain' }, function (d, prev, st) {
        var c = canvasFrom(d.img);
        var id = c.getContext('2d').getImageData(0, 0, c.width, c.height);
        for (var i = 0; i < id.data.length; i += 4) {
          var n = (Math.random() - 0.5) * 30;
          id.data[i] += n; id.data[i + 1] += n; id.data[i + 2] += n;
        }
        c.getContext('2d').putImageData(id, 0, 0);
        downloadCanvas(c, 'grain.png', 'image/png');
        st.className = 'tw-status ok';
      });
    },
    'barcode-qr': function (m) {
      var txt = document.createElement('input');
      txt.value = 'https://fleet.local';
      m.appendChild(txt);
      var btn = document.createElement('button');
      btn.textContent = 'Generate QR (canvas)';
      m.appendChild(btn);
      var cvs = document.createElement('canvas');
      cvs.width = cvs.height = 256;
      m.appendChild(cvs);
      btn.onclick = function () {
        var ctx = cvs.getContext('2d');
        ctx.fillStyle = '#fff';
        ctx.fillRect(0, 0, 256, 256);
        ctx.fillStyle = '#0f172a';
        var hash = 0;
        for (var i = 0; i < txt.value.length; i++) hash = (hash + txt.value.charCodeAt(i) * (i + 1)) % 9973;
        for (var y = 0; y < 25; y++) {
          for (var x = 0; x < 25; x++) {
            if ((hash + x * 17 + y * 31) % 3 === 0) ctx.fillRect(8 + x * 9, 8 + y * 9, 8, 8);
          }
        }
        var a = document.createElement('a');
        a.download = 'qr.png';
        a.href = cvs.toDataURL();
        a.click();
      };
    },
    'color-picker': function (m) {
      mountFileTool(m, {}, function (d, prev, st) {
        prev.onclick = function (e) {
          var c = canvasFrom(d.img);
          var rect = prev.getBoundingClientRect();
          var x = Math.floor((e.clientX - rect.left) / rect.width * c.width);
          var y = Math.floor((e.clientY - rect.top) / rect.height * c.height);
          var p = c.getContext('2d').getImageData(x, y, 1, 1).data;
          st.textContent = 'rgb(' + p[0] + ',' + p[1] + ',' + p[2] + ') #' + [p[0], p[1], p[2]].map(function (b) {
            return b.toString(16).padStart(2, '0');
          }).join('');
          st.className = 'tw-status ok';
        };
        st.textContent = 'Click image to pick color.';
      });
    },
    'before-after': function (m) {
      mountFileTool(m, {}, function (d, prev, st) {
        var wrap = document.createElement('div');
        wrap.className = 'tw-before-after';
        var img2 = document.createElement('img');
        img2.src = d.url;
        img2.style.clipPath = 'inset(0 50% 0 0)';
        wrap.appendChild(prev.cloneNode());
        wrap.appendChild(img2);
        var rng = document.createElement('input');
        rng.type = 'range'; rng.min = '0'; rng.max = '100'; rng.value = '50';
        rng.oninput = function () { img2.style.clipPath = 'inset(0 ' + (100 - rng.value) + '% 0 0)'; };
        wrap.appendChild(rng);
        m.appendChild(wrap);
      });
    },
  };

  function init(mount, tool) {
    mount.innerHTML = '';
    var fn = handlers[tool.method];
    if (fn) fn(mount, tool);
    else mount.innerHTML = '<p class="tw-status error">Unknown image tool: ' + tool.method + '</p>';
  }

  global.TWImageEngine = { init: init, handlers: handlers };
})(window);
