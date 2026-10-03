/**
 * Gemini Web Full Activity & Video Link Collector (Manual Operation Spy)
 * 
 * Instructions:
 * 1. Open https://gemini.google.com/u/0/videos (or https://gemini.google.com/app).
 * 2. Open Chrome DevTools (F12 or Ctrl+Shift+I) -> Console tab.
 * 3. Paste this entire script and press Enter.
 * 4. Manually type your prompt, generate your video, and click download in the UI.
 * 5. Run `copyLog()` or `exportLog()` in the console to copy or download all captured activity.
 */

(function () {
  console.clear();
  console.log(
    "%c🕵️ GEMINI ACTIVITY SPY ACTIVE — READY FOR MANUAL ACTIONS",
    "background: #4f46e5; color: white; padding: 10px 18px; font-size: 14px; font-weight: bold; border-radius: 8px;"
  );
  console.log(
    "%c👉 Perform your actions in the Gemini UI (type prompt, generate, click download).",
    "color: #38bdf8; font-size: 13px;"
  );
  console.log(
    "%c👉 When done, type %ccopyLog()%c or %cexportLog()%c in console to share results!",
    "color: #38bdf8; font-size: 13px;",
    "color: #10b981; font-weight: bold;",
    "color: #38bdf8;",
    "color: #10b981; font-weight: bold;",
    "color: #38bdf8;"
  );

  const spyStore = {
    sessionStart: new Date().toISOString(),
    pageUrl: window.location.href,
    wizData: {
      at: window.WIZ_global_data?.SNlM0e || window.WIZ_global_data?.thykhd || "",
      bl: window.WIZ_global_data?.cfb2h || "",
      fsid: window.WIZ_global_data?.FdrFJe || "",
    },
    userClicks: [],
    networkRequests: [],
    videoCandidates: [],
    blobsCreated: [],
    domVideos: [],
    performanceResources: [],
  };

  // Helper: check if string has video-related signatures
  function checkVideoSignatures(str) {
    if (!str || typeof str !== "string") return false;
    return (
      str.includes(".mp4") ||
      str.includes("googlevideo.com") ||
      str.includes("googleusercontent.com") ||
      str.includes("video/mp4") ||
      str.includes("filename=video") ||
      str.includes("/download?") ||
      str.includes("StreamGenerate") ||
      str.includes("GenerateVideo")
    );
  }

  function addVideoCandidate(url, source, details = {}) {
    if (!url || typeof url !== "string") return;
    const clean = url
      .replace(/\\u0026/g, "&")
      .replace(/\\u003d/g, "=")
      .replace(/\\u002F/g, "/")
      .replace(/\\\//g, "/")
      .replace(/&amp;/g, "&")
      .trim();

    if (!spyStore.videoCandidates.some(c => c.url === clean)) {
      const entry = {
        id: spyStore.videoCandidates.length + 1,
        time: new Date().toLocaleTimeString(),
        url: clean,
        source,
        details,
      };
      spyStore.videoCandidates.push(entry);
      console.log(
        `%c🎬 [VIDEO CANDIDATE DETECTED] via ${source}`,
        "background: #059669; color: white; padding: 4px 10px; font-weight: bold; border-radius: 4px;"
      );
      console.log(clean);
    }
  }

  function scanTextForUrls(text, source) {
    if (!text || typeof text !== "string") return;
    const patterns = [
      /https:\/\/[a-zA-Z0-9.-]+\.googleusercontent\.com\/[^\s"'<>\\]+/gi,
      /https:\/\/[a-zA-Z0-9.-]+\.googlevideo\.com\/[^\s"'<>\\]+/gi,
      /https:\/\/[^\s"'<>\\]+\.mp4(?:\?[^\s"'<>\\]*)?/gi,
      /https:\/\/[^\s"'<>\\]+contribution\.usercontent\.google\.com\/download[^\s"'<>\\]*/gi,
      /blob:https:\/\/gemini\.google\.com\/[a-zA-Z0-9-]+/gi,
    ];

    for (const pattern of patterns) {
      const matches = text.match(pattern);
      if (matches) {
        for (const m of matches) {
          addVideoCandidate(m, source);
        }
      }
    }
  }

  // 1. Monkeypatch window.fetch
  const originalFetch = window.fetch;
  window.fetch = async function (...args) {
    const reqStart = Date.now();
    const resource = args[0];
    const options = args[1] || {};
    const url = typeof resource === "string" ? resource : resource?.url || "";
    const method = (options.method || "GET").toUpperCase();

    let reqBody = options.body;
    let serializedBody = null;
    if (typeof reqBody === "string") {
      serializedBody = reqBody;
    } else if (reqBody instanceof URLSearchParams) {
      serializedBody = reqBody.toString();
    } else if (reqBody instanceof FormData) {
      const entries = {};
      for (const [k, v] of reqBody.entries()) {
        entries[k] = typeof v === "string" ? v : `[File/Blob: ${v.name || v.type}]`;
      }
      serializedBody = JSON.stringify(entries);
    }

    const logEntry = {
      type: "fetch",
      id: spyStore.networkRequests.length + 1,
      startTime: new Date().toLocaleTimeString(),
      method,
      url,
      requestHeaders: options.headers ? JSON.stringify(options.headers) : null,
      requestBodyPreview: serializedBody ? serializedBody.substring(0, 5000) : null,
      isSuspiciousVideoCall: checkVideoSignatures(url) || checkVideoSignatures(serializedBody),
      status: null,
      responseHeaders: {},
      responseBodyPreview: null,
      durationMs: null,
    };

    spyStore.networkRequests.push(logEntry);

    if (logEntry.isSuspiciousVideoCall) {
      console.log(
        `%c📡 [FETCH ${method}] %c${url.split("?")[0]}`,
        "background: #6366f1; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;",
        "color: #38bdf8; font-weight: bold;"
      );
    }

    try {
      const response = await originalFetch.apply(this, args);
      logEntry.status = response.status;
      logEntry.durationMs = Date.now() - reqStart;

      try {
        response.headers.forEach((v, k) => {
          logEntry.responseHeaders[k] = v;
        });
      } catch (_) {}

      const contentType = logEntry.responseHeaders["content-type"] || "";
      if (contentType.includes("video/")) {
        addVideoCandidate(response.url, "fetch response content-type: video", { headers: logEntry.responseHeaders });
      }

      // Clone and read response
      try {
        const clone = response.clone();
        if (
          url.includes("BardFrontendService") ||
          url.includes("StreamGenerate") ||
          url.includes("GenerateVideo") ||
          url.includes("videos") ||
          contentType.includes("json") ||
          contentType.includes("text")
        ) {
          clone.text().then(text => {
            logEntry.responseBodyPreview = text.length > 20000 ? text.substring(0, 20000) + " [TRUNCATED]" : text;
            scanTextForUrls(text, `fetch response (${url.split("?")[0]})`);
          }).catch(() => {});
        }
      } catch (_) {}

      return response;
    } catch (err) {
      logEntry.error = err.message;
      logEntry.durationMs = Date.now() - reqStart;
      throw err;
    }
  };

  // 2. Monkeypatch XMLHttpRequest
  const originalXHROpen = XMLHttpRequest.prototype.open;
  const originalXHRSend = XMLHttpRequest.prototype.send;
  const originalXHRSetHeader = XMLHttpRequest.prototype.setRequestHeader;

  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this._spyInfo = {
      type: "xhr",
      id: spyStore.networkRequests.length + 1,
      startTime: new Date().toLocaleTimeString(),
      method: method.toUpperCase(),
      url,
      headers: {},
      requestBodyPreview: null,
      responseBodyPreview: null,
      status: null,
    };
    return originalXHROpen.call(this, method, url, ...rest);
  };

  XMLHttpRequest.prototype.setRequestHeader = function (header, value) {
    if (this._spyInfo) this._spyInfo.headers[header] = value;
    return originalXHRSetHeader.call(this, header, value);
  };

  XMLHttpRequest.prototype.send = function (body) {
    if (this._spyInfo) {
      this._spyInfo.requestBodyPreview = typeof body === "string" ? body.substring(0, 5000) : String(body);
      spyStore.networkRequests.push(this._spyInfo);

      if (checkVideoSignatures(this._spyInfo.url) || checkVideoSignatures(this._spyInfo.requestBodyPreview)) {
        console.log(
          `%c📡 [XHR ${this._spyInfo.method}] %c${this._spyInfo.url.split("?")[0]}`,
          "background: #8b5cf6; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;",
          "color: #c084fc; font-weight: bold;"
        );
      }

      this.addEventListener("load", () => {
        this._spyInfo.status = this.status;
        try {
          const respText = this.responseText || "";
          this._spyInfo.responseBodyPreview = respText.length > 20000 ? respText.substring(0, 20000) + " [TRUNCATED]" : respText;
          scanTextForUrls(respText, `xhr response (${this._spyInfo.url.split("?")[0]})`);
        } catch (_) {}
      });
    }
    return originalXHRSend.call(this, body);
  };

  // 3. Monkeypatch URL.createObjectURL
  const originalCreateObjectURL = URL.createObjectURL;
  URL.createObjectURL = function (blob) {
    const url = originalCreateObjectURL.call(this, blob);
    try {
      const entry = {
        time: new Date().toLocaleTimeString(),
        url,
        type: blob?.type || "unknown",
        size: blob?.size || 0,
      };
      spyStore.blobsCreated.push(entry);

      if (blob?.type?.includes("video") || blob?.size > 500000) {
        addVideoCandidate(url, `URL.createObjectURL (Blob type: ${blob.type}, size: ${blob.size})`);
      }
    } catch (_) {}
    return url;
  };

  // 4. Track User Click Interactions
  document.addEventListener("click", (e) => {
    try {
      const target = e.target;
      const closestBtn = target.closest("button, a, [role='button']");
      const clickInfo = {
        time: new Date().toLocaleTimeString(),
        tag: target.tagName,
        text: (target.innerText || target.textContent || "").trim().substring(0, 100),
        ariaLabel: target.getAttribute("aria-label") || closestBtn?.getAttribute("aria-label") || null,
        href: target.getAttribute("href") || closestBtn?.getAttribute("href") || null,
        download: target.getAttribute("download") || closestBtn?.getAttribute("download") || null,
        classes: target.className || null,
      };
      spyStore.userClicks.push(clickInfo);

      if (clickInfo.href && (clickInfo.href.includes(".mp4") || clickInfo.href.includes("googleusercontent"))) {
        addVideoCandidate(clickInfo.href, "User clicked link with video URL");
      }

      console.log(
        `%c👆 [USER CLICK] %c<${clickInfo.tag}> ${clickInfo.ariaLabel || clickInfo.text || clickInfo.href || ""}`,
        "color: #f59e0b; font-weight: bold;",
        "color: #e2e8f0;"
      );
    } catch (_) {}
  }, true);

  // 5. Watch DOM for <video> and <source> elements
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (node.nodeType !== 1) continue;
        const el = node;

        if (el.tagName === "VIDEO" && el.src) {
          spyStore.domVideos.push({ time: new Date().toLocaleTimeString(), src: el.src });
          addVideoCandidate(el.src, "DOM <video src>");
        }

        const videos = el.querySelectorAll ? el.querySelectorAll("video, source, a[download], a[href*='.mp4']") : [];
        videos.forEach(v => {
          const src = v.src || v.href;
          if (src) {
            spyStore.domVideos.push({ time: new Date().toLocaleTimeString(), tag: v.tagName, src });
            addVideoCandidate(src, `DOM <${v.tagName.toLowerCase()}> element`);
          }
        });
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });

  // 6. Monitor Performance Resources (Completed Network Fetches)
  setInterval(() => {
    try {
      const resources = performance.getEntriesByType("resource");
      for (const r of resources) {
        const name = r.name || "";
        if (checkVideoSignatures(name) && !spyStore.performanceResources.some(p => p.name === name)) {
          spyStore.performanceResources.push({
            time: new Date().toLocaleTimeString(),
            name,
            initiatorType: r.initiatorType,
            duration: r.duration,
          });
          addVideoCandidate(name, `Performance Resource (${r.initiatorType})`);
        }
      }
    } catch (_) {}
  }, 1500);

  // ─── Export & Summary Tools ───────────────────────────────────────────────

  function generateSummaryReport() {
    return {
      title: "Gemini Video Generation Activity Report",
      capturedAt: new Date().toISOString(),
      sessionStart: spyStore.sessionStart,
      pageUrl: spyStore.pageUrl,
      tokens: spyStore.wizData,
      totalRequestsCaptured: spyStore.networkRequests.length,
      videoCandidatesFound: spyStore.videoCandidates.length,
      videoCandidates: spyStore.videoCandidates,
      userClicksSummary: spyStore.userClicks,
      relevantApiCalls: spyStore.networkRequests.filter(r => r.isSuspiciousVideoCall),
      allRequests: spyStore.networkRequests,
      blobsCreated: spyStore.blobsCreated,
      performanceMedia: spyStore.performanceResources,
    };
  }

  window.geminiSpy = spyStore;

  window.showSummary = function () {
    console.log("%c================ VEO VIDEO CANDIDATES ================", "color: #10b981; font-weight: bold; font-size: 14px;");
    if (spyStore.videoCandidates.length > 0) {
      console.table(spyStore.videoCandidates);
    } else {
      console.log("No video candidates detected yet.");
    }

    console.log("%c================ RELEVANT API CALLS ================", "color: #6366f1; font-weight: bold; font-size: 14px;");
    const relevant = spyStore.networkRequests.filter(r => r.isSuspiciousVideoCall);
    if (relevant.length > 0) {
      console.table(relevant.map(r => ({
        id: r.id,
        method: r.method,
        endpoint: r.url.split("?")[0],
        status: r.status,
        duration: r.durationMs ? `${r.durationMs}ms` : "in-flight",
      })));
    } else {
      console.log("No video-specific API calls captured yet.");
    }

    console.log("%c💡 Run copyLog() to copy all detailed payloads to your clipboard!", "color: #f59e0b; font-weight: bold;");
  };

  window.copyLog = async function () {
    const report = JSON.stringify(generateSummaryReport(), null, 2);
    try {
      await navigator.clipboard.writeText(report);
      console.log(
        "%c📋 COPIED FULL ACTIVITY REPORT TO CLIPBOARD!",
        "background: #10b981; color: white; padding: 6px 12px; font-weight: bold; border-radius: 6px;"
      );
      console.log("You can now simply paste (Ctrl+V) it in our chat!");
    } catch (e) {
      console.log("Clipboard write blocked. Outputting object to console:");
      console.log(report);
      console.log("👉 Right click above and select 'Copy string contents' or run exportLog()");
    }
  };

  window.exportLog = function () {
    const report = JSON.stringify(generateSummaryReport(), null, 2);
    const blob = new Blob([report], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `gemini_activity_${Date.now()}.json`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      a.remove();
      URL.revokeObjectURL(url);
    }, 5000);
    console.log("%c💾 DOWNLOADED ACTIVITY LOG JSON FILE!", "color: #10b981; font-weight: bold;");
  };

  window.downloadLatestVideo = function () {
    if (spyStore.videoCandidates.length === 0) {
      console.warn("No video candidates found to download.");
      return;
    }
    const latest = spyStore.videoCandidates[spyStore.videoCandidates.length - 1].url;
    console.log("Opening latest video URL:", latest);
    window.open(latest, "_blank");
  };

  console.log("%c✔ SPY FULLY INITIALIZED! Go ahead and interact with Gemini.", "color: #10b981; font-weight: bold;");
})();
