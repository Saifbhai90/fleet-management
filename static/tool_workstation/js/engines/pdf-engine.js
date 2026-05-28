/**
 * Document & PDF Engine — pdf-lib + jsPDF (client-side).
 */
(function (global) {
  var PDFLib = function () { return global.PDFLib; };
  var jsPDF = function () { return global.jspdf && global.jspdf.jsPDF; };

  function dl(blob, name) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
  }

  async function readPdf(file) {
    var buf = await file.arrayBuffer();
    return { bytes: new Uint8Array(buf), buf: buf };
  }

  function pdfPanel(m, label) {
    var p = document.createElement('div');
    p.className = 'tw-panel';
    var lb = document.createElement('label');
    lb.textContent = label;
    var inp = document.createElement('input');
    inp.type = 'file';
    inp.accept = label.indexOf('image') >= 0 ? 'image/*' : '.pdf,application/pdf';
    p.appendChild(lb);
    p.appendChild(inp);
    m.appendChild(p);
    return inp;
  }

  function status(m, msg, ok) {
    var s = m.querySelector('.tw-status') || document.createElement('p');
    s.className = 'tw-status ' + (ok ? 'ok' : '');
    s.textContent = msg;
    if (!s.parentNode) m.appendChild(s);
  }

  var handlers = {
    'pdf-encrypt': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var pw = document.createElement('input');
      pw.type = 'password';
      pw.placeholder = 'Password';
      m.appendChild(pw);
      var btn = document.createElement('button');
      btn.textContent = 'Encrypt';
      m.appendChild(btn);
      btn.onclick = async function () {
        try {
          var f = inp.files[0];
          var doc = await PDFLib().PDFDocument.load(await f.arrayBuffer());
          var out = await doc.save({ userPassword: pw.value, ownerPassword: pw.value });
          dl(new Blob([out], { type: 'application/pdf' }), 'encrypted.pdf');
          status(m, 'Encrypted.', true);
        } catch (e) { status(m, e.message, false); }
      };
    },
    'pdf-decrypt': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var pw = document.createElement('input');
      pw.type = 'password';
      m.appendChild(pw);
      var btn = document.createElement('button');
      btn.textContent = 'Decrypt / unlock';
      m.appendChild(btn);
      btn.onclick = async function () {
        try {
          var doc = await PDFLib().PDFDocument.load(await inp.files[0].arrayBuffer(), { password: pw.value });
          var out = await doc.save();
          dl(new Blob([out], { type: 'application/pdf' }), 'unlocked.pdf');
          status(m, 'Saved without encryption.', true);
        } catch (e) { status(m, e.message, false); }
      };
    },
    'pdf-compress': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var btn = document.createElement('button');
      btn.textContent = 'Re-save (optimize)';
      m.appendChild(btn);
      btn.onclick = async function () {
        var doc = await PDFLib().PDFDocument.load(await inp.files[0].arrayBuffer());
        var out = await doc.save({ useObjectStreams: true });
        dl(new Blob([out], { type: 'application/pdf' }), 'compressed.pdf');
        status(m, 'Repacked PDF.', true);
      };
    },
    'pdf-metadata': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var title = document.createElement('input'); title.placeholder = 'Title';
      var author = document.createElement('input'); author.placeholder = 'Author';
      m.appendChild(title); m.appendChild(author);
      var btn = document.createElement('button');
      btn.textContent = 'Update metadata';
      m.appendChild(btn);
      btn.onclick = async function () {
        var doc = await PDFLib().PDFDocument.load(await inp.files[0].arrayBuffer());
        doc.setTitle(title.value);
        doc.setAuthor(author.value);
        var out = await doc.save();
        dl(new Blob([out], { type: 'application/pdf' }), 'meta.pdf');
        status(m, 'Metadata updated.', true);
      };
    },
    'pdf-watermark': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var txt = document.createElement('input');
      txt.value = 'CONFIDENTIAL';
      m.appendChild(txt);
      var btn = document.createElement('button');
      btn.textContent = 'Stamp pages';
      m.appendChild(btn);
      btn.onclick = async function () {
        var doc = await PDFLib().PDFDocument.load(await inp.files[0].arrayBuffer());
        var font = await doc.embedFont(PDFLib().StandardFonts.Helvetica);
        doc.getPages().forEach(function (page) {
          var sz = page.getSize();
          page.drawText(txt.value, { x: sz.width / 2 - 80, y: sz.height / 2, size: 36, font: font, opacity: 0.2, rotate: PDFLib().degrees(45) });
        });
        dl(new Blob([await doc.save()], { type: 'application/pdf' }), 'watermarked.pdf');
        status(m, 'Watermark applied.', true);
      };
    },
    'pdf-page-numbers': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var btn = document.createElement('button');
      btn.textContent = 'Number pages';
      m.appendChild(btn);
      btn.onclick = async function () {
        var doc = await PDFLib().PDFDocument.load(await inp.files[0].arrayBuffer());
        var font = await doc.embedFont(PDFLib().StandardFonts.Helvetica);
        doc.getPages().forEach(function (page, i) {
          var sz = page.getSize();
          page.drawText(String(i + 1), { x: sz.width / 2 - 6, y: 24, size: 10, font: font });
        });
        dl(new Blob([await doc.save()], { type: 'application/pdf' }), 'numbered.pdf');
        status(m, 'Done.', true);
      };
    },
    'pdf-merge': function (m) {
      var inp = document.createElement('input');
      inp.type = 'file'; inp.multiple = true; inp.accept = '.pdf';
      m.appendChild(inp);
      var btn = document.createElement('button');
      btn.textContent = 'Merge PDFs';
      m.appendChild(btn);
      btn.onclick = async function () {
        var merged = await PDFLib().PDFDocument.create();
        for (var i = 0; i < inp.files.length; i++) {
          var src = await PDFLib().PDFDocument.load(await inp.files[i].arrayBuffer());
          var pages = await merged.copyPages(src, src.getPageIndices());
          pages.forEach(function (p) { merged.addPage(p); });
        }
        dl(new Blob([await merged.save()], { type: 'application/pdf' }), 'merged.pdf');
        status(m, 'Merged ' + inp.files.length + ' files.', true);
      };
    },
    'pdf-split': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var range = document.createElement('input');
      range.placeholder = 'e.g. 1-3';
      m.appendChild(range);
      var btn = document.createElement('button');
      btn.textContent = 'Split range';
      m.appendChild(btn);
      btn.onclick = async function () {
        var src = await PDFLib().PDFDocument.load(await inp.files[0].arrayBuffer());
        var part = range.value.split('-').map(Number);
        var out = await PDFLib().PDFDocument.create();
        var indices = [];
        for (var p = part[0]; p <= (part[1] || part[0]); p++) indices.push(p - 1);
        var pages = await out.copyPages(src, indices);
        pages.forEach(function (pg) { out.addPage(pg); });
        dl(new Blob([await out.save()], { type: 'application/pdf' }), 'split.pdf');
        status(m, 'Split saved.', true);
      };
    },
    'pdf-delete-pages': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var del = document.createElement('input');
      del.placeholder = 'Page numbers to delete: 2,4';
      m.appendChild(del);
      var btn = document.createElement('button');
      btn.textContent = 'Delete pages';
      m.appendChild(btn);
      btn.onclick = async function () {
        var doc = await PDFLib().PDFDocument.load(await inp.files[0].arrayBuffer());
        var remove = del.value.split(',').map(function (x) { return +x.trim() - 1; }).filter(function (x) { return x >= 0; });
        remove.sort(function (a, b) { return b - a; });
        remove.forEach(function (i) { doc.removePage(i); });
        dl(new Blob([await doc.save()], { type: 'application/pdf' }), 'trimmed.pdf');
        status(m, 'Pages removed.', true);
      };
    },
    'pdf-rotate': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var deg = document.createElement('select');
      [90, 180, 270].forEach(function (d) { deg.appendChild(new Option(d + '°', d)); });
      m.appendChild(deg);
      var btn = document.createElement('button');
      btn.textContent = 'Rotate all pages';
      m.appendChild(btn);
      btn.onclick = async function () {
        var doc = await PDFLib().PDFDocument.load(await inp.files[0].arrayBuffer());
        doc.getPages().forEach(function (page) {
          page.setRotation(PDFLib().degrees(+deg.value));
        });
        dl(new Blob([await doc.save()], { type: 'application/pdf' }), 'rotated.pdf');
        status(m, 'Rotated.', true);
      };
    },
    'pdf-reorder': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var order = document.createElement('input');
      order.placeholder = 'New order e.g. 3,1,2';
      m.appendChild(order);
      var btn = document.createElement('button');
      btn.textContent = 'Reorder';
      m.appendChild(btn);
      btn.onclick = async function () {
        var src = await PDFLib().PDFDocument.load(await inp.files[0].arrayBuffer());
        var seq = order.value.split(',').map(function (x) { return +x.trim() - 1; });
        var out = await PDFLib().PDFDocument.create();
        var pages = await out.copyPages(src, seq);
        pages.forEach(function (p) { out.addPage(p); });
        dl(new Blob([await out.save()], { type: 'application/pdf' }), 'reordered.pdf');
        status(m, 'Reordered.', true);
      };
    },
    'pdf-text-extract': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var out = document.createElement('textarea');
      out.readOnly = true;
      m.appendChild(out);
      var btn = document.createElement('button');
      btn.textContent = 'Extract text';
      m.appendChild(btn);
      btn.onclick = async function () {
        var doc = await PDFLib().PDFDocument.load(await inp.files[0].arrayBuffer());
        var lines = [];
        for (var i = 0; i < doc.getPageCount(); i++) {
          lines.push('--- Page ' + (i + 1) + ' ---');
        }
        out.value = lines.join('\n') + '\n\n(Text extraction uses pdf-lib structure; for scanned PDFs use OCR externally.)';
        status(m, 'Outline ready — embed text PDFs copy via pdf.js in future.', true);
      };
    },
    'pdf-to-images': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var btn = document.createElement('button');
      btn.textContent = 'Export pages as PNG (via render)';
      m.appendChild(btn);
      btn.onclick = async function () {
        status(m, 'Use PDF to JPG tool with pdf.js render for full fidelity.', false);
      };
    },
    'pdf-crop': function (m) {
      status(m, 'Set crop box via pdf-lib page.setCropBox in advanced build.', false);
      pdfPanel(m, 'PDF file');
    },
    'pdf-blank': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var pos = document.createElement('input');
      pos.placeholder = 'Insert after page number';
      m.appendChild(pos);
      var btn = document.createElement('button');
      btn.textContent = 'Insert blank';
      m.appendChild(btn);
      btn.onclick = async function () {
        var doc = await PDFLib().PDFDocument.load(await inp.files[0].arrayBuffer());
        var p = +pos.value || 1;
        var blank = PDFLib().PageSizes.A4;
        doc.insertPage(p, blank);
        dl(new Blob([await doc.save()], { type: 'application/pdf' }), 'with-blank.pdf');
        status(m, 'Blank page inserted.', true);
      };
    },
    'images-to-pdf': function (m) {
      var inp = document.createElement('input');
      inp.type = 'file'; inp.multiple = true; inp.accept = 'image/*';
      m.appendChild(inp);
      var btn = document.createElement('button');
      btn.textContent = 'Build PDF';
      m.appendChild(btn);
      btn.onclick = async function () {
        var doc = await PDFLib().PDFDocument.create();
        for (var i = 0; i < inp.files.length; i++) {
          var bytes = new Uint8Array(await inp.files[i].arrayBuffer());
          var img = inp.files[i].type.indexOf('png') >= 0
            ? await doc.embedPng(bytes)
            : await doc.embedJpg(bytes);
          var page = doc.addPage([img.width, img.height]);
          page.drawImage(img, { x: 0, y: 0, width: img.width, height: img.height });
        }
        dl(new Blob([await doc.save()], { type: 'application/pdf' }), 'images.pdf');
        status(m, 'PDF created.', true);
      };
    },
    'text-to-pdf': function (m) {
      var ta = document.createElement('textarea');
      m.appendChild(ta);
      var btn = document.createElement('button');
      btn.textContent = 'Create PDF';
      m.appendChild(btn);
      btn.onclick = function () {
        var pdf = new (jsPDF())();
        var lines = pdf.splitTextToSize(ta.value, 180);
        pdf.text(lines, 14, 20);
        pdf.save('text.pdf');
        status(m, 'Downloaded.', true);
      };
    },
    'html-to-pdf': function (m) {
      var ta = document.createElement('textarea');
      ta.value = '<h1>Title</h1><p>Content</p>';
      m.appendChild(ta);
      var btn = document.createElement('button');
      btn.textContent = 'Print to PDF';
      m.appendChild(btn);
      btn.onclick = function () {
        var w = window.open('', '_blank');
        w.document.write(ta.value);
        w.print();
        status(m, 'Use browser print dialog to save as PDF.', true);
      };
    },
    'markdown-to-pdf': function (m) {
      var ta = document.createElement('textarea');
      ta.value = '# Document\n\nParagraph text.';
      m.appendChild(ta);
      var btn = document.createElement('button');
      btn.textContent = 'Export PDF';
      m.appendChild(btn);
      btn.onclick = function () {
        var html = global.marked ? marked.parse(ta.value) : ta.value;
        var pdf = new (jsPDF())();
        pdf.text(pdf.splitTextToSize(html.replace(/<[^>]+>/g, ''), 180), 14, 20);
        pdf.save('markdown.pdf');
        status(m, 'Basic text PDF saved.', true);
      };
    },
    'docx-to-pdf': function (m) {
      var inp = document.createElement('input');
      inp.accept = '.docx';
      inp.type = 'file';
      m.appendChild(inp);
      status(m, 'Open DOCX in Word/Google Docs → Print to PDF for full fidelity. Client-side DOCX parse is limited.', false);
    },
    'csv-to-pdf': function (m) {
      var ta = document.createElement('textarea');
      ta.value = 'Name,Score\nAli,90\nSara,95';
      m.appendChild(ta);
      var btn = document.createElement('button');
      btn.textContent = 'Table PDF';
      m.appendChild(btn);
      btn.onclick = function () {
        var pdf = new (jsPDF())();
        ta.value.split('\n').forEach(function (line, i) {
          pdf.text(line.replace(/,/g, ' | '), 14, 14 + i * 8);
        });
        pdf.save('table.pdf');
        status(m, 'Saved.', true);
      };
    },
    'epub-to-pdf': function (m) {
      status(m, 'EPUB conversion requires dedicated parser; export from e-reader as PDF.', false);
    },
    'pdf-to-jpg': function (m) {
      handlers['pdf-viewer'](m);
      status(m, 'Use viewer + screenshot or deploy pdf.js render pipeline.', false);
    },
    'pdf-to-png': function (m) { handlers['pdf-to-jpg'](m); },
    'pdf-to-webp': function (m) { handlers['pdf-to-jpg'](m); },
    'pdf-to-text': function (m) { handlers['pdf-text-extract'](m); },
    'pdf-to-docx': function (m) {
      status(m, 'Download extracted text and open in Word for editable DOCX.', false);
      handlers['pdf-text-extract'](m);
    },
    'pdf-to-xlsx': function (m) {
      var ta = document.createElement('textarea');
      m.appendChild(ta);
      status(m, 'Paste extracted CSV-style text from PDF tables.', false);
    },
    'pdf-to-html': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var out = document.createElement('textarea');
      m.appendChild(out);
      var btn = document.createElement('button');
      btn.textContent = 'Mock HTML shell';
      m.appendChild(btn);
      btn.onclick = async function () {
        out.value = '<!DOCTYPE html><html><body><h1>PDF: ' + inp.files[0].name + '</h1><p>Embed pages as images for full layout.</p></body></html>';
        status(m, 'HTML scaffold created.', true);
      };
    },
    'pdf-viewer': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var frame = document.createElement('iframe');
      frame.style.width = '100%';
      frame.style.height = '480px';
      frame.style.border = '1px solid #e5e7eb';
      m.appendChild(frame);
      inp.onchange = function () {
        if (inp.files[0]) frame.src = URL.createObjectURL(inp.files[0]);
      };
    },
    'pdf-annotate': function (m) { handlers['pdf-viewer'](m); status(m, 'Highlight using browser PDF markup when printing.', false); },
    'pdf-text-place': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var txt = document.createElement('input');
      txt.value = 'Approved';
      m.appendChild(txt);
      var btn = document.createElement('button');
      btn.textContent = 'Place text';
      m.appendChild(btn);
      btn.onclick = async function () {
        var doc = await PDFLib().PDFDocument.load(await inp.files[0].arrayBuffer());
        var page = doc.getPage(0);
        var font = await doc.embedFont(PDFLib().StandardFonts.HelveticaBold);
        page.drawText(txt.value, { x: 72, y: 700, size: 18, font: font, color: PDFLib().rgb(0.15, 0.39, 0.92) });
        dl(new Blob([await doc.save()], { type: 'application/pdf' }), 'stamped.pdf');
        status(m, 'Text placed on page 1.', true);
      };
    },
    'pdf-form-read': function (m) { handlers['pdf-viewer'](m); },
    'pdf-flatten': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var btn = document.createElement('button');
      btn.textContent = 'Flatten (re-save)';
      m.appendChild(btn);
      btn.onclick = async function () {
        var doc = await PDFLib().PDFDocument.load(await inp.files[0].arrayBuffer());
        dl(new Blob([await doc.save()], { type: 'application/pdf' }), 'flat.pdf');
        status(m, 'Re-saved; interactive fields may remain without full flatten API.', true);
      };
    },
    'pdf-signature': function (m) {
      var inp = pdfPanel(m, 'PDF file');
      var sig = document.createElement('input');
      sig.type = 'file';
      sig.accept = 'image/*';
      m.appendChild(sig);
      var btn = document.createElement('button');
      btn.textContent = 'Stamp signature';
      m.appendChild(btn);
      btn.onclick = async function () {
        var doc = await PDFLib().PDFDocument.load(await inp.files[0].arrayBuffer());
        var imgBytes = new Uint8Array(await sig.files[0].arrayBuffer());
        var img = await doc.embedPng(imgBytes);
        var page = doc.getPages()[0];
        page.drawImage(img, { x: 72, y: 120, width: 120, height: 48 });
        dl(new Blob([await doc.save()], { type: 'application/pdf' }), 'signed.pdf');
        status(m, 'Signature image placed.', true);
      };
    },
    'invoice-pdf': function (m) {
      var company = document.createElement('input'); company.value = 'Fleet Co.';
      var amount = document.createElement('input'); amount.value = '1000';
      m.appendChild(company); m.appendChild(amount);
      var btn = document.createElement('button');
      btn.textContent = 'Generate invoice';
      m.appendChild(btn);
      btn.onclick = function () {
        var pdf = new (jsPDF())();
        pdf.setFontSize(18);
        pdf.text('INVOICE', 14, 20);
        pdf.setFontSize(11);
        pdf.text('Bill to: ' + company.value, 14, 36);
        pdf.text('Amount: PKR ' + amount.value, 14, 48);
        pdf.save('invoice.pdf');
        status(m, 'Invoice downloaded.', true);
      };
    },
    'resume-pdf': function (m) {
      var name = document.createElement('input'); name.value = 'Your Name';
      var body = document.createElement('textarea');
      body.value = 'Experience...\nSkills...';
      m.appendChild(name); m.appendChild(body);
      var btn = document.createElement('button');
      btn.textContent = 'Build CV PDF';
      m.appendChild(btn);
      btn.onclick = function () {
        var pdf = new (jsPDF())();
        pdf.setFontSize(16);
        pdf.text(name.value, 14, 20);
        pdf.setFontSize(10);
        pdf.text(pdf.splitTextToSize(body.value, 180), 14, 32);
        pdf.save('cv.pdf');
        status(m, 'CV saved.', true);
      };
    },
    'certificate-batch': function (m) {
      var ta = document.createElement('textarea');
      ta.value = 'Ali Ahmad\nSara Khan';
      ta.placeholder = 'One name per line';
      m.appendChild(ta);
      var btn = document.createElement('button');
      btn.textContent = 'Generate certificates';
      m.appendChild(btn);
      btn.onclick = async function () {
        var merged = await PDFLib().PDFDocument.create();
        var font = await merged.embedFont(PDFLib().StandardFonts.HelveticaBold);
        ta.value.split('\n').filter(Boolean).forEach(function (name) {
          var page = merged.addPage(PDFLib().PageSizes.A4);
          var sz = page.getSize();
          page.drawText('Certificate of Achievement', { x: 120, y: sz.height - 100, size: 22, font: font });
          page.drawText(name.trim(), { x: 180, y: sz.height / 2, size: 28, font: font });
        });
        dl(new Blob([await merged.save()], { type: 'application/pdf' }), 'certificates.pdf');
        status(m, 'Batch PDF ready.', true);
      };
    },
  };

  function init(mount, tool) {
    mount.innerHTML = '';
    if (!PDFLib()) {
      mount.innerHTML = '<p class="tw-status error">PDF library loading… refresh if this persists.</p>';
      return;
    }
    var fn = handlers[tool.method];
    if (fn) {
      var st = document.createElement('p');
      st.className = 'tw-status';
      mount.appendChild(st);
      fn(mount, tool);
    } else {
      mount.innerHTML = '<p class="tw-status error">Unknown PDF tool: ' + tool.method + '</p>';
    }
  }

  global.TWPdfEngine = { init: init, handlers: handlers };
})(window);
