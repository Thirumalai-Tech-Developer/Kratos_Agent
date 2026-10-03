import assert from "node:assert/strict";
import test from "node:test";

const { getVideoProvider, parseVideoModel } = await import(
  "../../open-sse/config/videoRegistry.ts"
);
const {
  GeminiWebExecutor,
  GEMINI_VIDEOS_URL,
  resolveVideoOrientation,
  buildGeminiVideoPrompt,
  parseVideoResponseUrl,
  isVideoGenerationPrompt,
  cleanGoogleVideoUrl,
  inspectTextForVideoUrl,
  checkGeminiWebRejectionReason,
  extractWizData,
  buildVeoVideoRpcPayload,
  getCachedWizData,
  setCachedWizData,
  clearCachedWizData,
  extractVideoPromptText,
  resolveGeminiWebBaseModel,
} = await import("../../open-sse/executors/gemini-web.ts");
const { handleGeminiWebVideoGeneration } = await import(
  "../../open-sse/handlers/videoGeneration/geminiWebVideoHandler.ts"
);

test("Gemini Web video provider is registered in VIDEO_PROVIDERS", () => {
  const provider = getVideoProvider("gemini-web");
  assert.ok(provider, "gemini-web provider should exist in VIDEO_PROVIDERS");
  assert.equal(provider.id, "gemini-web");
  assert.equal(provider.alias, "gweb");
  assert.equal(provider.format, "gemini-web-video");
  assert.equal(provider.baseUrl, "https://gemini.google.com/u/0/videos");
  assert.equal(provider.authType, "cookie");
  assert.equal(provider.authHeader, "cookie");

  const modelIds = provider.models.map((m) => m.id);
  assert.ok(modelIds.includes("gemini-3.7-flash"));
  assert.ok(modelIds.includes("gemini-3.1-pro"));
  assert.ok(modelIds.includes("gemini-2.5-flash"));
  assert.ok(modelIds.includes("gemini-2.5-pro"));
  assert.ok(modelIds.includes("default"));
  // Veo-specific model IDs should NOT be registered — only web models
  assert.ok(!modelIds.includes("veo"));
  assert.ok(!modelIds.includes("veo-2.0-generate"));
  assert.ok(!modelIds.includes("veo-3.0-generate"));

  const flashModel = provider.models.find((m) => m.id === "gemini-3.7-flash");
  assert.ok(flashModel?.supportedSizes?.includes("16:9"));
  assert.ok(flashModel?.supportedSizes?.includes("9:16"));
  assert.ok(flashModel?.supportedSizes?.includes("landscape"));
  assert.ok(flashModel?.supportedSizes?.includes("portrait"));
});

test("parseVideoModel resolves gemini-web and gweb alias for all supported models", () => {
  assert.deepEqual(parseVideoModel("gemini-web/gemini-3.7-flash"), {
    provider: "gemini-web",
    model: "gemini-3.7-flash",
  });
  assert.deepEqual(parseVideoModel("gweb/gemini-3.7-flash"), {
    provider: "gemini-web",
    model: "gemini-3.7-flash",
  });
  assert.deepEqual(parseVideoModel("gweb/portrait"), {
    provider: "gemini-web",
    model: "portrait",
  });
  assert.deepEqual(parseVideoModel("gweb/potrait"), {
    provider: "gemini-web",
    model: "potrait",
  });
  assert.deepEqual(parseVideoModel("gweb/landscape"), {
    provider: "gemini-web",
    model: "landscape",
  });
  assert.deepEqual(parseVideoModel("gweb/gemini-3.7-flash-portrait"), {
    provider: "gemini-web",
    model: "gemini-3.7-flash-portrait",
  });
  assert.deepEqual(parseVideoModel("gweb/gemini-3.7-flash-landscape"), {
    provider: "gemini-web",
    model: "gemini-3.7-flash-landscape",
  });
  assert.deepEqual(parseVideoModel("gemini-web/gemini-3.1-pro"), {
    provider: "gemini-web",
    model: "gemini-3.1-pro",
  });
  assert.deepEqual(parseVideoModel("gemini-web/default"), {
    provider: "gemini-web",
    model: "default",
  });
});

test("isVideoGenerationPrompt detects video generation intent", () => {
  assert.equal(
    isVideoGenerationPrompt("create a lord murugan playing video"),
    true
  );
  assert.equal(isVideoGenerationPrompt("generate a video of flying birds"), true);
  assert.equal(isVideoGenerationPrompt("make a video in cyber city"), true);
  assert.equal(isVideoGenerationPrompt("create video now"), true);
  assert.equal(isVideoGenerationPrompt("tell me a story about lord murugan"), false);
  assert.equal(isVideoGenerationPrompt("write typescript code"), false);
});

test("resolveVideoOrientation extracts portrait and landscape correctly", () => {
  assert.equal(resolveVideoOrientation({ orientation: "portrait" }), "portrait");
  assert.equal(resolveVideoOrientation({ orientation: "potrait" }), "portrait");
  assert.equal(resolveVideoOrientation({ orientation: "landscape" }), "landscape");
  assert.equal(resolveVideoOrientation({ aspect_ratio: "9:16" }), "portrait");
  assert.equal(resolveVideoOrientation({ aspect_ratio: "16:9" }), "landscape");
  assert.equal(resolveVideoOrientation({ size: "1080x1920" }), "portrait");
  assert.equal(resolveVideoOrientation({ size: "1920x1080" }), "landscape");
  assert.equal(resolveVideoOrientation({ ratio: "1:1" }), "square");
  assert.equal(resolveVideoOrientation({ model: "gweb/portrait" }), "portrait");
  assert.equal(resolveVideoOrientation({ model: "gweb/potrait" }), "portrait");
  assert.equal(resolveVideoOrientation({ model: "gweb/landscape" }), "landscape");
  assert.equal(resolveVideoOrientation({ model: "gemini-3.7-flash-portrait" }), "portrait");
  assert.equal(resolveVideoOrientation({}, "portrait"), "portrait");
  assert.equal(resolveVideoOrientation({}, "landscape"), "landscape");
  assert.equal(resolveVideoOrientation({}), null);
});

test("buildGeminiVideoPrompt injects portrait and landscape directives", () => {
  const portraitPrompt = buildGeminiVideoPrompt("cyberpunk city rain", {
    orientation: "portrait",
  });
  assert.match(portraitPrompt, /cyberpunk city rain/);
  assert.match(portraitPrompt, /Portrait 9:16/);

  const landscapePrompt = buildGeminiVideoPrompt("cyberpunk city rain", {
    orientation: "landscape",
  });
  assert.match(landscapePrompt, /cyberpunk city rain/);
  assert.match(landscapePrompt, /Landscape 16:9/);

  const durationPrompt = buildGeminiVideoPrompt("sunrise", {
    aspectRatio: "16:9",
    duration: 5,
  });
  assert.match(durationPrompt, /Landscape 16:9/);
  assert.match(durationPrompt, /Duration: 5s/);
});

test("parseVideoResponseUrl extracts mp4 and google video URLs", () => {
  assert.equal(
    parseVideoResponseUrl('{"url": "https://storage.googleapis.com/test/video.mp4"}'),
    "https://storage.googleapis.com/test/video.mp4"
  );
  assert.equal(
    parseVideoResponseUrl(
      'some prefix https://video-downloads.googleusercontent.com/abc123video/download.mp4 suffix'
    ),
    "https://video-downloads.googleusercontent.com/abc123video/download.mp4"
  );
  assert.equal(parseVideoResponseUrl("not a valid response"), null);
});

test("handleGeminiWebVideoGeneration requires prompt", async () => {
  const result = await handleGeminiWebVideoGeneration({
    model: "veo",
    provider: "gemini-web",
    body: { prompt: "" },
    credentials: { apiKey: "__Secure-1PSID=test_cookie" },
    log: null,
  });

  assert.equal(result.success, false);
  assert.equal(result.status, 400);
  assert.match(String(result.error), /Prompt is required/);
});

test("handleGeminiWebVideoGeneration requires session cookie", async () => {
  const result = await handleGeminiWebVideoGeneration({
    model: "veo",
    provider: "gemini-web",
    body: { prompt: "a cute kitten playing" },
    credentials: null,
    log: null,
  });

  assert.equal(result.success, false);
  assert.equal(result.status, 401);
  assert.match(String(result.error), /Missing session cookie/i);
});

test("handleGeminiWebVideoGeneration succeeds and applies portrait / landscape controls", async () => {
  let passedArgs: Record<string, unknown> | null = null;
  const mockExecutor = {
    executeVideoGeneration: async (args: Record<string, unknown>) => {
      passedArgs = args;
      return {
        success: true,
        status: 200,
        data: [{ url: "https://test.googleusercontent.com/video.mp4", format: "mp4" }],
      };
    },
  };

  const result = await handleGeminiWebVideoGeneration({
    model: "veo",
    provider: "gemini-web",
    body: {
      prompt: "a rocket launching into space",
      orientation: "portrait",
    },
    credentials: { apiKey: "__Secure-1PSID=test_psid_value" },
    log: null,
    executorFactory: () => mockExecutor,
  });

  assert.equal(result.success, true);
  assert.ok(result.data);
  assert.equal(result.data.data[0].url, "https://test.googleusercontent.com/video.mp4");
  assert.equal(result.data.data[0].format, "mp4");
  assert.equal(passedArgs?.orientation, "portrait");
  assert.equal(passedArgs?.videoUrl, GEMINI_VIDEOS_URL);
});

test("GeminiWebExecutor executeVideoGeneration runs Playwright flow and handles portrait/landscape", async () => {
  const playwright = await import("playwright");
  const originalLaunch = playwright.chromium.launch;
  const actions: string[] = [];

  playwright.chromium.launch = (async () =>
    ({
      newContext: async () => ({
        addCookies: async () => {
          actions.push("addCookies");
        },
        newPage: async () => ({
          on: (
            event: string,
            handler: (response: {
              url: () => string;
              headers?: () => Record<string, string>;
              text: () => Promise<string>;
            }) => void
          ) => {
            if (event === "response") {
              void handler({
                url: () => "https://video.google.com/test-generated.mp4",
                headers: () => ({ "content-type": "video/mp4" }),
                text: async () => "",
              });
            }
          },
          goto: async (url: string) => {
            actions.push(`goto:${url}`);
          },
          waitForTimeout: async (ms: number) => {
            if (ms >= 1000) {
              await new Promise((r) => setTimeout(r, 20));
            }
          },
          $: async (selector: string) => {
            actions.push(`$:${selector}`);
            return {
              click: async () => {
                actions.push(`click:${selector}`);
              },
            };
          },
          waitForSelector: async (selector: string) => {
            actions.push(`waitForSelector:${selector}`);
            return {
              click: async () => {
                actions.push("clickInput");
              },
            };
          },
          keyboard: {
            type: async (text: string) => {
              actions.push(`type:${text}`);
            },
            insertText: async (text: string) => {
              actions.push(`type:${text}`);
            },
            press: async (key: string) => {
              actions.push(`press:${key}`);
            },
          },
          evaluate: async () => null,
        }),
      }),
      close: async () => {
        actions.push("browserClose");
      },
    }) as unknown as Awaited<ReturnType<typeof originalLaunch>>) as typeof originalLaunch;

  try {
    const executor = new GeminiWebExecutor();
    // Test the Playwright browser automation flow via explicit engine
    const result = await executor.executeVideoGeneration({
      prompt: "a cat in space",
      orientation: "portrait",
      engine: "playwright",
      credentials: { apiKey: "__Secure-1PSID=test_cookie" },
      timeoutMs: 5000,
    });

    assert.equal(result.success, true);
    assert.equal(result.status, 200);
    assert.equal(result.data?.[0].url, "https://video.google.com/test-generated.mp4");
    assert.equal(result.data?.[0].format, "mp4");
    assert.ok(actions.includes(`goto:${GEMINI_VIDEOS_URL}`));
    assert.ok(actions.some((a) => a.startsWith("type:") && a.includes("Portrait 9:16")));
    assert.ok(actions.includes("browserClose"));
  } finally {
    playwright.chromium.launch = originalLaunch;
  }
});

test("GeminiWebExecutor.execute routes video intent in chat to video studio", async () => {
  const executor = new GeminiWebExecutor();
  let calledVideo = false;
  executor.executeVideoGeneration = async () => {
    calledVideo = true;
    return {
      success: true,
      status: 200,
      data: [{ url: "https://video.google.com/murugan-video.mp4", format: "mp4" }],
    };
  };

  const result = await executor.execute({
    model: "gemini-3.7-flash",
    body: {
      messages: [{ role: "user", content: "create a lord murugan playing video" }],
      stream: false,
    },
    stream: false,
    credentials: { apiKey: "__Secure-1PSID=test_cookie" },
    signal: AbortSignal.timeout(5000),
    log: null,
  });

  assert.equal(calledVideo, true);
  assert.equal(result.response.status, 200);
  const json = (await result.response.json()) as { choices: Array<{ message: { content: string } }> };
  assert.ok(json.choices[0].message.content.includes("https://video.google.com/murugan-video.mp4"));
  assert.ok(json.choices[0].message.content.includes("<video controls"));
});

test("GeminiWebExecutor.execute routes gweb/portrait model in chat to video studio and returns OpenAI choices", async () => {
  const executor = new GeminiWebExecutor();
  let passedOpts: Parameters<typeof executor.executeVideoGeneration>[0] | null = null;
  executor.executeVideoGeneration = async (opts) => {
    passedOpts = opts;
    return {
      success: true,
      status: 200,
      data: [{ url: "https://video.google.com/portrait-video.mp4", format: "mp4" }],
    };
  };

  const result = await executor.execute({
    model: "gweb/portrait",
    body: {
      messages: [{ role: "user", content: "Lord Krishna in rain" }],
      stream: false,
    },
    stream: false,
    credentials: { apiKey: "__Secure-1PSID=test_cookie" },
    signal: AbortSignal.timeout(5000),
    log: null,
  });

  assert.ok(passedOpts);
  assert.equal(passedOpts?.orientation, "portrait");
  assert.equal(passedOpts?.aspectRatio, "9:16");
  assert.equal(result.response.status, 200);
  const json = (await result.response.json()) as { choices: Array<{ message: { content: string } }> };
  assert.ok(Array.isArray(json.choices), "Response must have choices array for OpenAI chat compatibility");
  assert.ok(json.choices[0].message.content.includes("https://video.google.com/portrait-video.mp4"));
  assert.ok(json.choices[0].message.content.includes("<video controls"));
});

test("cleanGoogleVideoUrl strips backslashes, unescapes characters and removes trailing noise", () => {
  const dirtyUrl =
    "https://contribution.usercontent.google.com/download?c\\=CgxiYXJkX3N0b3JhZ2USUBINcmVzcG9uc2VfZGF0YRo\\&filename\\=video.mp4\\&opi\\=103135050\"]";
  const cleaned = cleanGoogleVideoUrl(dirtyUrl);
  assert.equal(
    cleaned,
    "https://contribution.usercontent.google.com/download?c=CgxiYXJkX3N0b3JhZ2USUBINcmVzcG9uc2VfZGF0YRo&filename=video.mp4&opi=103135050"
  );
  assert.equal(cleanGoogleVideoUrl(""), "");
});

test("extractWizData parses SNlM0e, cfb2h, and FdrFJe from HTML", () => {
  const html = `
    <html>
      <script>
        window.WIZ_global_data = {
          "SNlM0e": "AIzaSyTestAtToken123",
          "cfb2h": "boq_assistant-bard-web-server_20260907.07_p0",
          "FdrFJe": "session_id_xyz789"
        };
      </script>
    </html>
  `;
  const data = extractWizData(html);
  assert.ok(data);
  assert.equal(data.atToken, "AIzaSyTestAtToken123");
  assert.equal(data.blLabel, "boq_assistant-bard-web-server_20260907.07_p0");
  assert.equal(data.fSid, "session_id_xyz789");

  assert.equal(extractWizData("<html><body>No tokens here</body></html>"), null);
});

test("buildVeoVideoRpcPayload enforces Tool Code 16 and aspect ratio mapping", () => {
  const portraitPayload = buildVeoVideoRpcPayload("Lord Krishna in rain", {
    orientation: "portrait",
  });
  assert.ok(portraitPayload.clientUuid);
  assert.equal(portraitPayload.clientUuid, portraitPayload.clientUuid.toUpperCase());

  // Check Tool Code 16
  assert.deepEqual(portraitPayload.reqArray[55], [[16]]);

  // Check prompt item and aspect code 2 for portrait
  const promptItem = portraitPayload.reqArray[0] as unknown[];
  assert.match(String(promptItem[0]), /Create a video of: Lord Krishna in rain/);
  assert.deepEqual(promptItem[9], [
    null,
    null,
    null,
    null,
    null,
    null,
    [[null, null, null, 2]],
  ]);

  // Check landscape aspect code 1
  const landscapePayload = buildVeoVideoRpcPayload("Lord Krishna video", {
    orientation: "landscape",
  });
  const landscapePromptItem = landscapePayload.reqArray[0] as unknown[];
  assert.equal(String(landscapePromptItem[0]), "Lord Krishna video");
  assert.deepEqual(landscapePromptItem[9], [
    null,
    null,
    null,
    null,
    null,
    null,
    [[null, null, null, 1]],
  ]);

  // Check aspect code 2 when orientation is inferred from model: "portrait" or "potrait"
  const modelPortraitPayload = buildVeoVideoRpcPayload("cute cat playing", {
    model: "portrait",
  });
  const modelPortraitItem = modelPortraitPayload.reqArray[0] as unknown[];
  assert.deepEqual(modelPortraitItem[9], [
    null,
    null,
    null,
    null,
    null,
    null,
    [[null, null, null, 2]],
  ]);

  const modelPotraitPayload = buildVeoVideoRpcPayload("cute cat playing", {
    model: "potrait",
  });
  const modelPotraitItem = modelPotraitPayload.reqArray[0] as unknown[];
  assert.deepEqual(modelPotraitItem[9], [
    null,
    null,
    null,
    null,
    null,
    null,
    [[null, null, null, 2]],
  ]);

  // Check aspect code 1 when model is landscape
  const modelLandscapePayload = buildVeoVideoRpcPayload("cute cat playing", {
    model: "landscape",
  });
  const modelLandscapeItem = modelLandscapePayload.reqArray[0] as unknown[];
  assert.deepEqual(modelLandscapeItem[9], [
    null,
    null,
    null,
    null,
    null,
    null,
    [[null, null, null, 1]],
  ]);
});

test("inspectTextForVideoUrl extracts contribution download and CDN URLs", () => {
  const responseWithContribution =
    'prefix [["wrb.fr",null,"[[null,\\"https://contribution.usercontent.google.com/download?c\\\\=123\\\\&filename\\\\=video.mp4\\\\&opi\\\\=103135050\\"]]"]]';
  const matched1 = inspectTextForVideoUrl(responseWithContribution);
  assert.equal(
    matched1,
    "https://contribution.usercontent.google.com/download?c=123&filename=video.mp4&opi=103135050"
  );

  const responseWithCdn =
    'streaming at https://lh3.googleusercontent.com/gg/sample-video-stream-abc123xyz and more text';
  const matched2 = inspectTextForVideoUrl(responseWithCdn);
  assert.equal(matched2, "https://lh3.googleusercontent.com/gg/sample-video-stream-abc123xyz");

  assert.equal(inspectTextForVideoUrl("just text without any links"), null);
});

test("checkGeminiWebRejectionReason identifies high demand, policy violation, internal error and captcha", () => {
  assert.equal(
    checkGeminiWebRejectionReason("I'm getting a lot of requests right now. Please try again later."),
    "high_traffic_busy"
  );
  assert.equal(
    checkGeminiWebRejectionReason("Due to high demand, this feature is temporarily unavailable."),
    "high_traffic_busy"
  );
  assert.equal(
    checkGeminiWebRejectionReason("I encountered an error doing what you asked. Could you try again?"),
    "internal_error"
  );
  assert.equal(
    checkGeminiWebRejectionReason("I encountered an error. Please try again"),
    "internal_error"
  );
  assert.equal(
    checkGeminiWebRejectionReason("Our systems have detected unusual traffic from your computer network."),
    "captcha_required"
  );
  assert.equal(
    checkGeminiWebRejectionReason("https://www.google.com/sorry/index?continue=..."),
    "captcha_required"
  );
  assert.equal(checkGeminiWebRejectionReason("Here is your video!"), null);
});

test("WIZ data cache stores, retrieves, and clears tokens", () => {
  clearCachedWizData();
  const cookie = "__Secure-1PSID=unique_test_cookie_123";
  assert.equal(getCachedWizData(cookie), null);

  setCachedWizData(cookie, {
    atToken: "token_abc",
    blLabel: "bl_123",
    fSid: "fsid_456",
  });

  const cached = getCachedWizData(cookie);
  assert.ok(cached);
  assert.equal(cached.atToken, "token_abc");

  clearCachedWizData(cookie);
  assert.equal(getCachedWizData(cookie), null);
});

test("GeminiWebExecutor executeVideoGenerationHttp executes complete Veo HTTP flow with mocked responses", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: string; method: string }> = [];

  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    const urlStr = String(url);
    calls.push({ url: urlStr, method: init?.method || "GET" });

    // 1. Home page WIZ tokens fetch
    if (urlStr.includes("gemini.google.com/app") || urlStr.includes("gemini.google.com/u/0/videos")) {
      return new Response(
        `<html><script>"SNlM0e":"mock_at_token_777","cfb2h":"mock_bl_label_888","FdrFJe":"mock_fsid_999"</script></html>`,
        { status: 200 }
      );
    }

    // 2. StreamGenerate dispatch
    if (urlStr.includes("StreamGenerate")) {
      return new Response(
        `)]}'\n120\n[["wrb.fr",null,"[\\"c_fbc71e21394b7361\\",\\"40511f07-902a-413b-858b-607d0d0952e0\\"]"]]`,
        { status: 200 }
      );
    }

    // 3. History poller hNvQHb
    if (urlStr.includes("rpcids=hNvQHb")) {
      return new Response(
        `)]}'\n200\n[["wrb.fr",null,"[[null,\\"https://contribution.usercontent.google.com/download?c\\\\=CgxiYXJk\\\\&filename\\\\=video.mp4\\\\&opi\\\\=103135050\\"]]"]]`,
        { status: 200 }
      );
    }

    // 4. Ping kwDCne
    if (urlStr.includes("rpcids=kwDCne")) {
      return new Response(`)]}'\n50\n[["wrb.fr",null,"[]"]]`, { status: 200 });
    }

    // 5. Video artifact download for b64
    if (urlStr.includes("contribution.usercontent.google.com")) {
      return new Response(Buffer.from("mock_mp4_bytes"), {
        status: 200,
        headers: { "Content-Type": "video/mp4" },
      });
    }

    return new Response("Not found", { status: 404 });
  }) as typeof globalThis.fetch;

  try {
    const executor = new GeminiWebExecutor();
    clearCachedWizData();

    const result = await executor.executeVideoGenerationHttp({
      prompt: "Lord Krishna playing flute in rain",
      orientation: "portrait",
      credentials: { apiKey: "__Secure-1PSID=real_mock_cookie" },
      timeoutMs: 10000,
    });

    assert.equal(result.success, true);
    assert.equal(result.status, 200);
    assert.ok(result.data?.[0]?.url);
    assert.equal(
      result.data[0].url,
      "https://contribution.usercontent.google.com/download?c=CgxiYXJk&filename=video.mp4&opi=103135050"
    );
    assert.equal(result.data[0].format, "mp4");

    assert.ok(calls.some((c) => c.url.includes("gemini.google.com")));
    assert.ok(calls.some((c) => c.url.includes("StreamGenerate")));
    assert.ok(calls.some((c) => c.url.includes("rpcids=hNvQHb")));
  } finally {
    globalThis.fetch = originalFetch;
    clearCachedWizData();
  }
});

test("GeminiWebExecutor executeVideoGenerationHttp supports b64_json format", async () => {
  const originalFetch = globalThis.fetch;

  globalThis.fetch = (async (url: string | URL | Request) => {
    const urlStr = String(url);
    if (urlStr.includes("gemini.google.com/app") || urlStr.includes("gemini.google.com/u/0/videos")) {
      return new Response(
        `<html><script>"SNlM0e":"mock_at","cfb2h":"mock_bl","FdrFJe":"mock_fsid"</script></html>`,
        { status: 200 }
      );
    }
    if (urlStr.includes("StreamGenerate")) {
      return new Response(
        `)]}'\n120\n[["wrb.fr",null,"[\\"c_12345678abcdef00\\",\\"40511f07-902a-413b-858b-607d0d0952e0\\"]"]]`,
        { status: 200 }
      );
    }
    if (urlStr.includes("rpcids=hNvQHb")) {
      return new Response(
        `)]}'\n200\n[["wrb.fr",null,"[[null,\\"https://contribution.usercontent.google.com/download?c\\\\=test\\\\&filename\\\\=video.mp4\\"]]"]]`,
        { status: 200 }
      );
    }
    if (urlStr.includes("contribution.usercontent.google.com")) {
      return new Response(Buffer.from("fake_mp4_binary_stream"), {
        status: 200,
        headers: { "Content-Type": "video/mp4" },
      });
    }
    return new Response("OK", { status: 200 });
  }) as typeof globalThis.fetch;

  try {
    const executor = new GeminiWebExecutor();
    clearCachedWizData();

    const result = await executor.executeVideoGenerationHttp({
      prompt: "golden sunrise time lapse",
      responseFormat: "b64_json",
      credentials: { apiKey: "__Secure-1PSID=mock_cookie" },
      timeoutMs: 10000,
    });

    assert.equal(result.success, true);
    assert.equal(result.status, 200);
    assert.ok(result.data?.[0]?.b64_json);
    assert.equal(
      Buffer.from(result.data[0].b64_json, "base64").toString(),
      "fake_mp4_binary_stream"
    );
    assert.equal(result.data[0].format, "mp4");
  } finally {
    globalThis.fetch = originalFetch;
    clearCachedWizData();
  }
});

test("isVideoGenerationPrompt detects uppercase 'CREATE A FUNNY VIDEO' and handles multi-turn array content", async () => {
  assert.equal(isVideoGenerationPrompt("CREATE A FUNNY VIDEO"), true);
  assert.equal(isVideoGenerationPrompt("make a video"), true);

  const executor = new GeminiWebExecutor();
  let capturedPrompt = "";
  executor.executeVideoGeneration = async (opts) => {
    capturedPrompt = opts.prompt;
    return {
      success: true,
      status: 200,
      data: [{ url: "https://video.google.com/funny-video.mp4", format: "mp4" }],
    };
  };

  const result = await executor.execute({
    model: "gemini-web",
    body: {
      messages: [
        { role: "user", content: "hello" },
        { role: "assistant", content: "Hi! How can I help you?" },
        { role: "user", content: [{ type: "text", text: "CREATE A FUNNY VIDEO" }] },
      ],
      stream: false,
    },
    stream: false,
    credentials: { apiKey: "__Secure-1PSID=mock_cookie" },
    signal: AbortSignal.timeout(5000),
    log: null,
  });

  assert.equal(capturedPrompt, "CREATE A FUNNY VIDEO");
  assert.equal(result.response.status, 200);
});

test("registerLazyExecutor and registerExecutor allow idempotent re-registration in non-production mode", async () => {
  const { registerLazyExecutor, registerExecutor, getRegisteredExecutor } = await import(
    "../../open-sse/executors/registry.ts"
  );
  const dummyExecutor = new GeminiWebExecutor();

  // Re-registering an alias should not throw
  assert.doesNotThrow(() => {
    registerLazyExecutor("test-alias-unique", async () => dummyExecutor);
    registerLazyExecutor("test-alias-unique", async () => dummyExecutor);
  });

  assert.doesNotThrow(() => {
    registerExecutor("test-alias-sync", dummyExecutor);
    registerExecutor("test-alias-sync", dummyExecutor);
  });
  assert.equal(getRegisteredExecutor("test-alias-sync"), dummyExecutor);
});

test("extractVideoPromptText strips command prefixes cleanly", () => {
  assert.equal(
    extractVideoPromptText("Generate video: A serene sunset over mountain peaks"),
    "A serene sunset over mountain peaks"
  );
  assert.equal(
    extractVideoPromptText("Genrate video: Golden eagle soaring above clouds"),
    "Golden eagle soaring above clouds"
  );
  assert.equal(
    extractVideoPromptText("Create a video of: Neon futuristic city rain"),
    "Neon futuristic city rain"
  );
  assert.equal(
    extractVideoPromptText("Make video: Dancing peacock in forest"),
    "Dancing peacock in forest"
  );
  assert.equal(
    extractVideoPromptText("video of: Lord Krishna playing golden flute in rain"),
    "Lord Krishna playing golden flute in rain"
  );
  assert.equal(
    extractVideoPromptText("Lord Krishna playing golden flute in rain"),
    "Lord Krishna playing golden flute in rain"
  );
});

test("isVideoGenerationPrompt detects 'Genrate video:' and video prefixes", () => {
  assert.equal(isVideoGenerationPrompt("Genrate video: Krishna playing flute"), true);
  assert.equal(isVideoGenerationPrompt("genrate video of ocean waves"), true);
  assert.equal(isVideoGenerationPrompt("Generate video: Flying birds"), true);
  assert.equal(isVideoGenerationPrompt("video of: Beautiful garden"), true);
  assert.equal(isVideoGenerationPrompt("video: Cosmic galaxy"), true);
});

test("parseVideoModel resolves gemini-2.5-flash and gemini-2.5-pro models", () => {
  assert.deepEqual(parseVideoModel("gemini-web/gemini-2.5-flash"), {
    provider: "gemini-web",
    model: "gemini-2.5-flash",
  });
  assert.deepEqual(parseVideoModel("gemini-web/gemini-2.5-pro"), {
    provider: "gemini-web",
    model: "gemini-2.5-pro",
  });
});

test("GeminiWebExecutor executeVideoGeneration defaults to HTTP RPC (matching gemini-veo-harvester.js) and routes to Playwright when explicitly requested", async () => {
  let playwrightAttempted = false;
  let httpAttempted = false;

  const executor = new GeminiWebExecutor();
  // Intercept both engines to track which one is called by default
  executor.executeVideoGenerationPlaywright = async () => {
    playwrightAttempted = true;
    return { success: true, status: 200, data: [{ url: "https://video.google.com/lion.mp4", format: "mp4" }] };
  };
  executor.executeVideoGenerationHttp = async () => {
    httpAttempted = true;
    return { success: true, status: 200, data: [{ url: "https://video.google.com/lion.mp4", format: "mp4" }] };
  };

  const result = await executor.executeVideoGeneration({
    prompt: "Generate video: A running lion",
    credentials: { apiKey: "__Secure-1PSID=mock_cookie" },
    timeoutMs: 5000,
  });

  assert.equal(result.success, true);
  assert.equal(httpAttempted, true, "HTTP RPC should be the default engine (matching gemini-veo-harvester.js)");
  assert.equal(playwrightAttempted, false, "Playwright must NOT be invoked by default");

  // Now test that engine: "playwright" explicitly routes to Playwright
  playwrightAttempted = false;
  httpAttempted = false;
  const pwResult = await executor.executeVideoGeneration({
    prompt: "Generate video: A running lion",
    credentials: { apiKey: "__Secure-1PSID=mock_cookie" },
    timeoutMs: 5000,
    engine: "playwright",
  });

  assert.equal(pwResult.success, true);
  assert.equal(playwrightAttempted, true, "Playwright should be used when engine='playwright'");
  assert.equal(httpAttempted, false, "HTTP RPC must NOT be invoked when engine='playwright'");
});

test("resolveGeminiWebBaseModel strips provider prefixes and orientation suffixes cleanly", () => {
  assert.equal(resolveGeminiWebBaseModel("gemini-3.7-flash-portrait"), "gemini-3.7-flash");
  assert.equal(resolveGeminiWebBaseModel("gemini-3.7-flash-landscape"), "gemini-3.7-flash");
  assert.equal(resolveGeminiWebBaseModel("gweb/gemini-3.7-flash-portrait"), "gemini-3.7-flash");
  assert.equal(resolveGeminiWebBaseModel("gemini-web/gemini-2.5-flash-portrait"), "gemini-2.5-flash");
  assert.equal(resolveGeminiWebBaseModel("custom-model-portrait"), "custom-model");
  assert.equal(resolveGeminiWebBaseModel("portrait"), "gemini-2.5-pro");
  assert.equal(resolveGeminiWebBaseModel("gweb/portrait"), "gemini-2.5-pro");
  assert.equal(resolveGeminiWebBaseModel(null), "gemini-2.5-pro");
  assert.equal(resolveGeminiWebBaseModel(undefined), "gemini-2.5-pro");
});

test("casual greetings on portrait models do NOT trigger video generation and route to chat", async () => {
  const executor = new GeminiWebExecutor();
  let videoCalled = false;
  executor.executeVideoGeneration = async () => {
    videoCalled = true;
    return { success: true, status: 200, data: [] };
  };

  // We mock playwright to verify it falls through to chat rather than calling executeVideoGeneration
  const playwright = await import("playwright");
  const originalLaunch = playwright.chromium.launch;
  let playwrightCalled = false;
  playwright.chromium.launch = (async () => {
    playwrightCalled = true;
    return {
      newContext: async () => ({
        addCookies: async () => {},
        addInitScript: async () => {},
        newPage: async () => ({
          on: (_ev: string, handler: (resp: { url: () => string; text: () => Promise<string> }) => void) => {
            void handler({
              url: () => "https://gemini.google.com/StreamGenerate",
              text: async () => `)]}'\n50\n[["wrb.fr",null,"[null,null,null,null,[[null,[\\"Hello! How can I help you today?\\"]]]]"]]`,
            });
          },
          goto: async () => {},
          waitForTimeout: async () => {},
          waitForSelector: async () => ({ click: async () => {} }),
          keyboard: {
            type: async () => {},
            insertText: async () => {},
            press: async () => {},
          },
          url: () => "https://gemini.google.com/app/c_test_conv_123",
        }),
      }),
      close: async () => {},
    };
  }) as unknown as typeof originalLaunch;

  try {
    const res = await executor.execute({
      model: "gweb/gemini-3.7-flash-portrait",
      body: {
        messages: [{ role: "user", content: "hii" }],
        stream: false,
      },
      credentials: { apiKey: "__Secure-1PSID=mock_psid" },
      stream: false,
    });

    assert.equal(videoCalled, false, "Casual greeting 'hii' must NOT invoke video generation");
    assert.equal(playwrightCalled, true, "Casual greeting should fall through to normal chat");
    assert.equal(res.response.status, 200);
    const json = (await res.response.json()) as { choices: Array<{ message: { content: string } }> };
    assert.equal(json.choices[0].message.content, "Hello! How can I help you today?");
  } finally {
    playwright.chromium.launch = originalLaunch;
  }
});

test("normalizeGeminiCookieInput correctly parses Chrome DevTools TSV cookies", async () => {
  const { normalizeGeminiCookieInput } = await import("../../open-sse/utils/geminiCookies.ts");
  const tsvInput = `__Secure-1PSID\tpsid_val_123\t.google.com\t/\t2027\t100\t✓\t✓\tHigh
__Secure-1PSIDTS\tsidts_val_456\t.google.com\t/\t2027\t100\t✓\t✓\tHigh
__Secure-1PSIDCC\tcc_val_789\t.google.com\t/\t2027\t100\t✓\t✓\tHigh`;

  const normalized = normalizeGeminiCookieInput(tsvInput);
  assert.ok(normalized.includes("__Secure-1PSID=psid_val_123"));
  assert.ok(normalized.includes("__Secure-1PSIDTS=sidts_val_456"));
  assert.ok(normalized.includes("__Secure-1PSIDCC=cc_val_789"));
  assert.ok(normalized.includes("; "));
});


