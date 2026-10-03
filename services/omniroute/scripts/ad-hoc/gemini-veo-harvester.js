/**
 * 👑 GEMINI VEO COMPLETE PIPELINE AUTODOWNLOADER & HARVESTER (V5 - CLEAN URL)
 * 
 * Fixes:
 * 1. Strips all JSON escape backslashes (c\= -> c=, \& -> &) from the download URL.
 * 2. Removes cross-origin fetch attempt (eliminates CORS error completely).
 * 3. Triggers native Chrome browser file download via clean anchor click and iframe.
 * 4. Adds direct one-click button in the HUD to instantly save the .mp4.
 */

(function () {
  console.clear();
  console.log(
    "%c👑 GEMINI VEO COMPLETE PIPELINE DAEMON ACTIVE (V5)",
    "background: #10b981; color: white; padding: 8px 16px; font-size: 15px; font-weight: bold; border-radius: 8px;"
  );
  console.log(
    "%c• URL Sanitizer Active: Backslashes stripped (c= and & clean params).",
    "color: #a855f7; font-weight: bold;"
  );
  console.log(
    "%c• CORS-Free Download: Native Chrome download manager stream.",
    "color: #34d399; font-weight: bold;"
  );
  console.log(
    "%c• Run: createVeoVideo('Lord Krishna playing in rain with golden flute highly 3d rendered', true)",
    "color: #38bdf8; font-size: 13px;"
  );

  // ─── 1. Floating On-Screen Widget ───────────────────────────────────────────
  let hudEl = document.getElementById("veo-daemon-hud");
  if (!hudEl) {
    hudEl = document.createElement("div");
    hudEl.id = "veo-daemon-hud";
    hudEl.style.cssText = `
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 999999;
      background: rgba(15, 23, 42, 0.96);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(56, 189, 248, 0.4);
      color: #f8fafc;
      padding: 14px 18px;
      border-radius: 12px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 13px;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-width: 320px;
    `;
    hudEl.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between;">
        <span style="font-weight: bold; color: #38bdf8; display: flex; align-items: center; gap: 6px;">
          🎬 Veo Auto-Downloader
        </span>
        <span id="veo-hud-status" style="font-size: 11px; padding: 2px 6px; border-radius: 4px; background: #065f46; color: #34d399;">
          READY (VEO ACTIVE)
        </span>
      </div>
      <div id="veo-hud-msg" style="color: #94a3b8; font-size: 12px;">
        Listening for video generations...
      </div>
      <div id="veo-hud-actions" style="display: none; margin-top: 4px;">
        <button id="veo-hud-download-btn" style="
          width: 100%;
          background: #10b981;
          color: white;
          border: none;
          padding: 8px 12px;
          border-radius: 6px;
          font-weight: bold;
          font-size: 12px;
          cursor: pointer;
        ">
          ⬇️ Click to Download MP4
        </button>
      </div>
    `;
    document.body.appendChild(hudEl);
  }

  function updateHud(status, msg, color = "#34d399", bg = "#065f46", showDownloadUrl = null) {
    try {
      const statusEl = document.getElementById("veo-hud-status");
      const msgEl = document.getElementById("veo-hud-msg");
      const actionsEl = document.getElementById("veo-hud-actions");
      const btnEl = document.getElementById("veo-hud-download-btn");

      if (statusEl) {
        statusEl.textContent = status;
        statusEl.style.color = color;
        statusEl.style.background = bg;
      }
      if (msgEl) msgEl.textContent = msg;

      if (showDownloadUrl && actionsEl && btnEl) {
        actionsEl.style.display = "block";
        btnEl.onclick = () => {
          downloadVideoFile(showDownloadUrl);
        };
      }
    } catch (_) {}
  }

  // ─── 2. Robust URL Sanitizer (Strips All Backslashes) ──────────────────────
  function cleanGoogleUrl(raw) {
    if (!raw || typeof raw !== "string") return "";
    let url = raw
      .replace(/\\u0026/g, "&")
      .replace(/\\u003d/g, "=")
      .replace(/\\u002F/g, "/")
      .replace(/&amp;/g, "&");

    // Strip ALL escape backslashes (\=, \&, \/) entirely!
    url = url.split("\\").join("");

    // Remove any trailing quotes or brackets
    url = url.replace(/["')\]\s]+$/, "");
    return url.trim();
  }

  // ─── 3. Native Browser Download Manager (100% Free of CORS Restrictions) ───
  const downloadedUrls = new Set();
  window.capturedVeoLinks = [];

  function downloadVideoFile(url, customName = null) {
    const cleanUrl = cleanGoogleUrl(url);
    if (!cleanUrl || cleanUrl.length < 30) return;

    if (!window.capturedVeoLinks.includes(cleanUrl)) {
      window.capturedVeoLinks.push(cleanUrl);
    }

    if (downloadedUrls.has(cleanUrl)) {
      console.log("%c[Veo] Link already dispatched to download manager.", "color: #94a3b8;");
      return;
    }
    downloadedUrls.add(cleanUrl);

    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const filename = customName || `gemini_veo_${timestamp}.mp4`;

    console.log(
      `%c⬇️ [VEO NATIVE DOWNLOAD DISPATCHED] File: ${filename}`,
      "background: #10b981; color: white; padding: 4px 8px; font-weight: bold; border-radius: 4px;"
    );
    console.log(cleanUrl);
    updateHud("DOWNLOADING", "Sending to Chrome download manager...", "#10b981", "#065f46", cleanUrl);

    // 1. Direct Anchor Click with download attribute
    // Google servers return 'Content-Disposition: attachment; filename=video.mp4'
    // This triggers Chrome's download manager directly without ANY CORS checks!
    const a = document.createElement("a");
    a.href = cleanUrl;
    a.download = filename;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 2000);

    // 2. Invisible iframe fallback
    try {
      const iframe = document.createElement("iframe");
      iframe.style.display = "none";
      iframe.src = cleanUrl;
      document.body.appendChild(iframe);
      setTimeout(() => iframe.remove(), 15000);
    } catch (_) {}

    updateHud("SAVED", "Download dispatched! Check your Chrome download bar.", "#34d399", "#065f46", cleanUrl);
  }

  // ─── 4. Full-String Video URL Extractor ────────────────────────────────────
  function inspectTextForVideo(rawText, source = "Scanner") {
    if (!rawText || typeof rawText !== "string") return null;

    // Clean text and unescape
    const text = cleanGoogleUrl(rawText);

    // Match the official contribution download URL
    const downloadMatch = text.match(/https:\/\/contribution\.usercontent\.google\.com\/download\?[^\s"'<>]+/i);
    if (downloadMatch) {
      const fullUrl = cleanGoogleUrl(downloadMatch[0]);
      console.log(`%c🎬 [CLEAN OFFICIAL DOWNLOAD LINK DETECTED via ${source}]`, "color: #10b981; font-weight: bold; font-size: 13px;");
      console.log(fullUrl);
      downloadVideoFile(fullUrl);
      return fullUrl;
    }

    // Match Google CDN direct video stream
    const cdnMatch = text.match(/https:\/\/lh3\.googleusercontent\.com\/gg\/[^\s"'<>]+/i);
    if (cdnMatch) {
      const fullUrl = cleanGoogleUrl(cdnMatch[0]);
      console.log(`%c🎬 [GOOGLE CDN STREAM DETECTED via ${source}]`, "color: #38bdf8; font-weight: bold; font-size: 13px;");
      console.log(fullUrl);
      downloadVideoFile(fullUrl);
      return fullUrl;
    }

    return null;
  }

  function checkRejectionReason(text) {
    if (!text || typeof text !== "string") return null;
    const lower = text.toLowerCase();
    if (
      lower.includes("getting a lot of requests right now") ||
      lower.includes("couldn't do that because i'm getting a lot of requests") ||
      lower.includes("please try again later") ||
      lower.includes("high demand") ||
      lower.includes("temporarily unavailable") ||
      lower.includes("too many requests") ||
      lower.includes("capacity limit")
    ) {
      return "high_traffic_busy";
    }
    return null;
  }

  // ─── 5. Safe Network Interceptors ───────────────────────────────────────────
  const origFetch = window.fetch;
  window.fetch = async function (...args) {
    const resource = args[0];
    const urlStr = typeof resource === "string" ? resource : resource?.url ? String(resource.url) : "";

    // Never intercept download links
    if (urlStr.includes("contribution.usercontent.google.com")) {
      return origFetch.apply(this, args);
    }

    const response = await origFetch.apply(this, args);
    try {
      if (
        urlStr &&
        (urlStr.includes("batchexecute") ||
          urlStr.includes("StreamGenerate"))
      ) {
        response.clone().text().then(text => inspectTextForVideo(text, "fetch response")).catch(() => {});
      }
    } catch (_) {}
    return response;
  };

  const origXHROpen = XMLHttpRequest.prototype.open;
  const origXHRSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this._url = typeof url === "string" ? url : url?.href ? String(url.href) : "";
    return origXHROpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener("load", () => {
      try {
        const urlStr = this._url || "";
        if (
          urlStr &&
          (urlStr.includes("batchexecute") ||
            urlStr.includes("StreamGenerate"))
        ) {
          inspectTextForVideo(this.responseText, `XHR response (${urlStr.split("?")[0]})`);
        }
      } catch (_) {}
    });
    return origXHRSend.apply(this, args);
  };

  // ─── 6. DOM Watcher ────────────────────────────────────────────────────────
  const observer = new MutationObserver(mutations => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (node.nodeType !== 1) continue;
        const el = node;
        if (el.tagName === "VIDEO" && el.src) inspectTextForVideo(el.src, "DOM <video src>");
        const videos = el.querySelectorAll ? el.querySelectorAll("video, source") : [];
        videos.forEach(v => { if (v.src) inspectTextForVideo(v.src, "DOM child video"); });
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });

  // ─── 7. Veo Video Payload Generator (Enforces Tool ID 16) ───────────────────
  function buildVeoVideoPayload(prompt, isPortrait = true) {
    const aspectCode = isPortrait ? 2 : 1; // 2 = 9:16 portrait, 1 = 16:9 landscape

    const videoPrompt = prompt.toLowerCase().includes("video")
      ? prompt
      : `Create a video of: ${prompt}`;

    const promptItem = [
      videoPrompt,
      0,
      null,
      null,
      null,
      null,
      0,
      null,
      null,
      [null, null, null, null, null, null, [[null, null, null, aspectCode]]],
    ];

    const clientUuid = (crypto.randomUUID ? crypto.randomUUID() : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
      const r = Math.random() * 16 | 0;
      return (c === "x" ? r : (r & 0x3 | 0x8)).toString(16);
    })).toUpperCase();

    const reqArray = [
      promptItem,
      ["en"],
      ["", "", "", null, null, null, null, null, null, ""],
      null,
      null,
      null,
      [1],
      1,
      null,
      null,
      1,
      0,
      null,
      null,
      null,
      null,
      null,
      [[0]],
      0,
      null, null, null, null, null, null, null, null,
      1,
      null, null,
      [4],
      null, null, null, null, null, null, null, null, null, null,
      [1],
      null, null, null, null, null, null, null,
      11,
      null, null, null,
      0,
      [],
      [[16]], // Tool Code 16 Activates Veo Video Engine!
      null, null, null,
      clientUuid,
      null,
      [],
      null, null, null, null, null,
      0,
      2,
      null, null, null, null, null, null, null, null, null, null,
      1, 1,
      null, null, null, null, null, null, null, null, null, null,
      0,
      null, null, null, null,
      0,
      null,
      1
    ];

    return { reqArray, clientUuid };
  }

  // ─── 8. Autonomous Video Generator with Full Pipeline ──────────────────────
  window.createVeoVideo = async function (prompt, isPortrait = true, maxRetries = 5) {
    let attempt = 0;

    while (attempt < maxRetries) {
      attempt++;
      const isRetry = attempt > 1;

      const atToken = window.WIZ_global_data?.SNlM0e || window.WIZ_global_data?.thykhd || "";
      const blLabel = window.WIZ_global_data?.cfb2h || "boq_assistant-bard-web-server_20260907.07_p0";
      const fSid = window.WIZ_global_data?.FdrFJe || "";

      console.log(
        `%c🚀 [1/4] ${isRetry ? `RETRY ATTEMPT ${attempt}/${maxRetries}:` : "DISPATCHING VEO VIDEO:"} "${prompt}" (${isPortrait ? "Portrait 9:16" : "Landscape 16:9"})`,
        "background: #0284c7; color: white; padding: 4px 8px; font-weight: bold; border-radius: 4px;"
      );
      updateHud(
        isRetry ? `RETRY ${attempt}/${maxRetries}` : "DISPATCHING",
        `Enforcing Veo Video Tool 16...`,
        "#38bdf8",
        "#0c4a6e"
      );

      const reqCounter = Math.floor(Math.random() * 800000 + 100000);
      const streamUrl = `/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate?bl=${blLabel}&f.sid=${fSid}&hl=en&_reqid=${reqCounter}&rt=c`;

      const { reqArray, clientUuid } = buildVeoVideoPayload(prompt, isPortrait);

      const formData = new URLSearchParams();
      formData.append("f.req", JSON.stringify([null, JSON.stringify(reqArray)]));
      formData.append("at", atToken);

      try {
        const resp = await origFetch(streamUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Same-Domain": "1",
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-525005358-jspb": JSON.stringify([clientUuid, 1])
          },
          body: formData.toString(),
        });

        const reader = resp.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let streamText = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          streamText += decoder.decode(value, { stream: true });
        }

        // Check for busy / rate limit
        const rejectionType = checkRejectionReason(streamText);
        if (rejectionType === "high_traffic_busy") {
          const waitTimeSec = 4 + attempt * 2;
          console.warn(`%c⚠️ Google reported high demand/busy. Auto-retrying in ${waitTimeSec}s (Attempt ${attempt}/${maxRetries})...`, "color: #f59e0b; font-weight: bold;");
          updateHud("SERVER BUSY", `Traffic high. Auto-retrying in ${waitTimeSec}s...`, "#f59e0b", "#78350f");
          await new Promise(r => setTimeout(r, waitTimeSec * 1000));
          continue;
        }

        // Extract conversation ID
        const convMatch = streamText.match(/c_[0-9a-f]{8,}/i);
        const taskMatch = streamText.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);

        const convId = convMatch ? convMatch[0] : null;
        const taskId = taskMatch ? taskMatch[0] : null;

        if (!convId) {
          console.warn("Could not find conversation ID. Stream content preview:", streamText.substring(0, 500));
          if (attempt < maxRetries) {
            await new Promise(r => setTimeout(r, 4000));
            continue;
          }
          updateHud("ERROR", "Failed to obtain conversation ID", "#ef4444", "#7f1d1d");
          return;
        }

        console.log(
          `%c⏳ [2/4] VEO RENDERING IN PROGRESS: Conv: ${convId} ${taskId ? `| Task: ${taskId}` : ""}`,
          "color: #eab308; font-weight: bold;"
        );

        // Step 2 & 3: Polling Loop
        const startTime = Date.now();
        let videoFound = false;

        while (!videoFound && Date.now() - startTime < 240000) {
          const elapsedSec = Math.floor((Date.now() - startTime) / 1000);
          updateHud("RENDERING", `Veo rendering video in cloud... (${elapsedSec}s elapsed)`, "#fbbf24", "#78350f");

          await new Promise(r => setTimeout(r, 4000));

          // Poll conversation history via hNvQHb
          const pollReqId = Math.floor(Math.random() * 800000 + 100000);
          const historyUrl = `/_/BardChatUi/data/batchexecute?rpcids=hNvQHb&bl=${blLabel}&f.sid=${fSid}&hl=en&_reqid=${pollReqId}&rt=c`;
          const historyBody = new URLSearchParams();
          historyBody.append("f.req", JSON.stringify([[["hNvQHb", JSON.stringify([convId, 10, null, 1, [1], [4], null, 1]), null, "generic"]]]));
          historyBody.append("at", atToken);

          try {
            const hResp = await origFetch(historyUrl, {
              method: "POST",
              headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
              body: historyBody.toString(),
            });
            const hText = await hResp.text();

            const matchedUrl = inspectTextForVideo(hText, "hNvQHb Poller");
            if (matchedUrl) {
              console.log(`%c✨ [3/4] VEO RENDERING COMPLETED! (Took ${elapsedSec}s)`, "color: #10b981; font-weight: bold; font-size: 14px;");
              videoFound = true;
              return;
            }

            if (checkRejectionReason(hText) === "high_traffic_busy") {
              console.warn("Generation encountered high traffic during render. Retrying...");
              break;
            }
          } catch (_) {}

          // Ping kwDCne if taskId exists
          if (taskId) {
            try {
              const kwUrl = `/_/BardChatUi/data/batchexecute?rpcids=kwDCne&bl=${blLabel}&f.sid=${fSid}&hl=en&_reqid=${pollReqId + 1}&rt=c`;
              const kwBody = new URLSearchParams();
              kwBody.append("f.req", JSON.stringify([[["kwDCne", JSON.stringify([taskId]), null, "generic"]]]));
              kwBody.append("at", atToken);
              origFetch(kwUrl, {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
                body: kwBody.toString(),
              }).catch(() => {});
            } catch (_) {}
          }
        }

        if (videoFound) return;
      } catch (err) {
        console.error("Pipeline iteration error:", err);
      }
    }

    updateHud("TIMEOUT", "Generation exceeded timeout or retries", "#ef4444", "#7f1d1d");
  };

  window.downloadLatestVeo = function () {
    if (window.capturedVeoLinks.length > 0) {
      downloadVideoFile(window.capturedVeoLinks[window.capturedVeoLinks.length - 1]);
    } else {
      console.warn("No video links captured yet.");
    }
  };

  console.log("%c✔ READY! Run: createVeoVideo('Lord Krishna playing in rain with golden flute highly 3d rendered', true)", "color: #10b981; font-weight: bold;");
})();
