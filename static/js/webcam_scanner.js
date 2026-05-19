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
  const cropPreviewEl = root.querySelector("[data-webcam-crop-preview]");
  const confirmEl = root.querySelector("[data-webcam-confirm]");
  const foundNameEl = root.querySelector("[data-webcam-found-name]");
  const foundSetEl = root.querySelector("[data-webcam-found-set]");
  const btnConfirmSet = root.querySelector("[data-webcam-confirm-set]");
  const btnConfirmName = root.querySelector("[data-webcam-confirm-name]");

  if (!video || !capCanvas || !procCanvas || !btnStart || !btnCapture || !btnStop) return;

  let stream = null;

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg || "";
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
      setStatus("Hold kortet op foran kameraet og tryk «Fang og læs navn».");
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
    var frame = drawVideoFrame();
    if (!frame) {
      setStatus("Intet billede endnu — vent et øjeblik og prøv igen.");
      return;
    }

    setStatus("Scanner kort …");
    btnCapture.disabled = true;
    if (confirmEl) confirmEl.hidden = true;

    try {
      var imageData = frame.toDataURL("image/jpeg", 0.85);

      var resp = await fetch("/api/scan-card-ai", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image: imageData }),
      });

      if (!resp.ok) {
        var err = await resp.json().catch(function () { return {}; });
        setStatus((err && err.error) || "Serverfejl ved scanning. Prøv igen.");
        return;
      }

      var data = await resp.json();
      var name = (data.name || "").trim();

      if (name.length < 3) {
        setStatus("Kunne ikke læse et kortnavn. Prøv mere lys, tættere på kortet, eller ret kortet.");
      } else {
        var cardSet = (data.set || "").trim();
        setStatus("");
        if (foundNameEl) foundNameEl.textContent = name;
        if (foundSetEl) foundSetEl.textContent = cardSet ? ' fra "' + cardSet + '"' : "";
        if (confirmEl) {
          confirmEl.dataset.foundName = name;
          confirmEl.dataset.foundSet = cardSet;
          confirmEl.hidden = false;
        }
      }
    } catch (e) {
      setStatus((e && e.message) || "Netværksfejl. Er serveren kørende?");
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

  if (btnConfirmSet) {
    btnConfirmSet.addEventListener("click", function () {
      var n = confirmEl && confirmEl.dataset.foundName || "";
      var s = confirmEl && confirmEl.dataset.foundSet || "";
      if (!n) return;
      var url = "/lookup?q=" + encodeURIComponent(n);
      if (s) url += "&set=" + encodeURIComponent(s);
      window.location.href = url;
    });
  }

  if (btnConfirmName) {
    btnConfirmName.addEventListener("click", function () {
      var n = confirmEl && confirmEl.dataset.foundName || "";
      if (!n) return;
      window.location.href = "/lookup?q=" + encodeURIComponent(n);
    });
  }

  window.addEventListener("beforeunload", function () {
    stopTracks();
  });
})();
