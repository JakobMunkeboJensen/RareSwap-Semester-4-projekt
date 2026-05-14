/**
 * Webcam → beskær navnebånd (som pi_card_scanner) → OCR (Tesseract.js) → søgefelt.
 */
(function () {
  "use strict";

  const root = document.querySelector("[data-webcam-scanner]");
  if (!root) return;

  const targetSel = root.getAttribute("data-scanner-target") || "#q";
  const video = root.querySelector("[data-webcam-video]");
  const capCanvas = root.querySelector("[data-webcam-canvas-full]");
  const procCanvas = root.querySelector("[data-webcam-canvas-crop]");
  const btnStart = root.querySelector("[data-webcam-start]");
  const btnCapture = root.querySelector("[data-webcam-capture]");
  const btnStop = root.querySelector("[data-webcam-stop]");
  const statusEl = root.querySelector("[data-webcam-status]");

  if (!video || !capCanvas || !procCanvas || !btnStart || !btnCapture || !btnStop) return;

  let stream = null;
  let tesseractWorker = null;
  let tesseractLoading = null;

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg || "";
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.async = true;
      s.onload = resolve;
      s.onerror = function () {
        reject(new Error("Kunne ikke indlæse OCR-bibliotek."));
      };
      document.head.appendChild(s);
    });
  }

  function cleanName(text) {
    return String(text || "")
      .replace(/[^A-Za-z \-]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  /** Samme procenter som pi_card_scanner._crop_name_band */
  function cropNameBand(sourceCanvas) {
    var w = sourceCanvas.width;
    var h = sourceCanvas.height;
    var y0 = Math.floor(h * 0.02);
    var y1 = Math.floor(h * 0.22);
    var x0 = Math.floor(w * 0.08);
    var x1 = Math.floor(w * 0.92);
    var cw = x1 - x0;
    var ch = y1 - y0;
    procCanvas.width = cw;
    procCanvas.height = ch;
    var ctx = procCanvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(sourceCanvas, x0, y0, cw, ch, 0, 0, cw, ch);
    var img = ctx.getImageData(0, 0, cw, ch);
    var d = img.data;
    for (var i = 0; i < d.length; i += 4) {
      var y = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
      d[i] = d[i + 1] = d[i + 2] = y;
    }
    ctx.putImageData(img, 0, 0);
    return procCanvas;
  }

  function drawVideoFrame() {
    if (!stream || video.readyState < 2) return null;
    var vw = video.videoWidth;
    var vh = video.videoHeight;
    if (!vw || !vh) return null;
    var maxW = 1280;
    var scale = vw > maxW ? maxW / vw : 1;
    var tw = Math.floor(vw * scale);
    var th = Math.floor(vh * scale);
    capCanvas.width = tw;
    capCanvas.height = th;
    var ctx = capCanvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, tw, th);
    return capCanvas;
  }

  function ensureTesseract() {
    if (tesseractWorker) return Promise.resolve(tesseractWorker);
    if (tesseractLoading) return tesseractLoading;

    tesseractLoading = (async function () {
      if (typeof Tesseract === "undefined") {
        await loadScript("https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js");
      }
      if (typeof Tesseract === "undefined" || !Tesseract.createWorker) {
        throw new Error("OCR-biblioteket loadedes ikke korrekt.");
      }
      var worker = await Tesseract.createWorker("eng", 1, {
        workerPath: "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/worker.min.js",
        corePath: "https://cdn.jsdelivr.net/npm/tesseract.js-core@5/tesseract-core.wasm.js",
        logger: function () {},
      });
      await worker.setParameters({
        tessedit_pageseg_mode: "7",
      });
      tesseractWorker = worker;
      tesseractLoading = null;
      return worker;
    })().catch(function (e) {
      tesseractLoading = null;
      throw e;
    });

    return tesseractLoading;
  }

  async function onStart() {
    setStatus("");
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } },
        audio: false,
      });
      video.srcObject = stream;
      await video.play();
      btnCapture.disabled = false;
      btnStop.disabled = false;
      btnStart.disabled = true;
      setStatus("Webcam kører. Placér kort med navnet øverst og tryk «Fang og læs navn».");
    } catch (e) {
      setStatus(
        "Kunne ikke starte webcam (tilladelse eller ingen kamera?). På telefon kræves ofte HTTPS."
      );
    }
  }

  function stopTracks() {
    if (stream) {
      stream.getTracks().forEach(function (t) {
        t.stop();
      });
      stream = null;
    }
    video.srcObject = null;
    btnCapture.disabled = true;
    btnStop.disabled = true;
    btnStart.disabled = false;
  }

  async function onCapture() {
    var target = document.querySelector(targetSel);
    if (!target) {
      setStatus("Internt: kunne ikke finde søgefeltet.");
      return;
    }

    var frame = drawVideoFrame();
    if (!frame) {
      setStatus("Intet billede endnu — vent et øjeblik og prøv igen.");
      return;
    }

    var crop = cropNameBand(frame);
    if (!crop) {
      setStatus("Kunne ikke forberede billede.");
      return;
    }

    setStatus("Læser tekst (første gang hentes OCR-data; kan tage ca. 10–30 sek.) …");
    btnCapture.disabled = true;

    try {
      var worker = await ensureTesseract();
      var result = await worker.recognize(crop);
      var raw = (result && result.data && result.data.text) || "";
      var name = cleanName(raw);

      if (name.length < 3) {
        setStatus(
          'Teksten "' +
            (raw.trim().slice(0, 40) || "(tom)") +
            '" var for kort/usikker. Prøv mere lys eller tættere på kortet.'
        );
      } else {
        target.value = name;
        target.dispatchEvent(new Event("input", { bubbles: true }));
        setStatus('Sat navn til: "' + name + '". Tryk «Søg» når du er klar.');
      }
    } catch (e) {
      setStatus((e && e.message) || "OCR fejlede. Prøv igen eller genindlæs siden.");
    } finally {
      btnCapture.disabled = !stream;
    }
  }

  function onStop() {
    stopTracks();
    setStatus("Webcam stoppet.");
  }

  btnStart.addEventListener("click", function () {
    onStart();
  });
  btnCapture.addEventListener("click", function () {
    onCapture();
  });
  btnStop.addEventListener("click", function () {
    onStop();
  });

  window.addEventListener("beforeunload", function () {
    stopTracks();
    if (tesseractWorker && typeof tesseractWorker.terminate === "function") {
      tesseractWorker.terminate();
      tesseractWorker = null;
    }
  });
})();
