import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";
import {
  GeminiWebExecutor,
  __resetGeminiSessionRotatorForTesting,
  geminiSessionRotator,
  DEFAULT_PAGE_MIN_PROMPTS,
  DEFAULT_PAGE_MAX_PROMPTS,
} from "../../open-sse/executors/gemini-web.ts";

describe("GeminiWebExecutor Antiban Page Rotation & Session Reuse", () => {
  beforeEach(() => {
    __resetGeminiSessionRotatorForTesting();
  });

  it("rotates session after reaching prompt limit (5..7 prompts)", async () => {
    const executor = new GeminiWebExecutor();
    let pageCount = 0;
    const usedConvIds: string[] = [];

    // Mock executeVideoGenerationHttp to track conversationId reuse and rotation
    executor.executeVideoGenerationHttp = async (opts) => {
      let currentConvId = opts.conversationId;
      if (!currentConvId) {
        pageCount++;
        currentConvId = `c_gemini_page_${pageCount}`;
      }
      usedConvIds.push(currentConvId);
      return {
        success: true,
        status: 200,
        data: [{ url: `https://contribution.usercontent.google.com/download?c=mock_${pageCount}`, format: "mp4" }],
        conversationId: currentConvId,
      };
    };

    const cookie = "__Secure-1PSID=mock_psid_token; __Secure-1PSIDTS=mock_ts";

    // Execute 5 video prompts with fixed limit of 5 prompts per session
    for (let i = 1; i <= 5; i++) {
      const res = await executor.execute({
        model: "gemini-3.7-flash",
        body: {
          messages: [{ role: "user", content: `Generate video: prompt ${i}` }],
        },
        credentials: {
          apiKey: cookie,
          providerSpecificData: { minPromptsPerPage: 5, maxPromptsPerPage: 5 },
        },
        stream: false,
        signal: null,
      } as never);

      assert.equal(res.response.status, 200);
    }

    // First 5 prompts must reuse the exact same conversation session
    assert.equal(usedConvIds.length, 5);
    assert.equal(usedConvIds[0], "c_gemini_page_1");
    assert.equal(usedConvIds[1], "c_gemini_page_1");
    assert.equal(usedConvIds[2], "c_gemini_page_1");
    assert.equal(usedConvIds[3], "c_gemini_page_1");
    assert.equal(usedConvIds[4], "c_gemini_page_1");

    const session = geminiSessionRotator.get("mock_psid_token:gemini-3.7-flash");
    assert.ok(session);
    assert.equal(session?.promptCount, 5);
    assert.equal(session?.data.conversationId, "c_gemini_page_1");

    // 6th prompt should rotate to a fresh conversation page
    const res6 = await executor.execute({
      model: "gemini-3.7-flash",
      body: {
        messages: [{ role: "user", content: "Generate video: prompt 6" }],
      },
      credentials: {
        apiKey: cookie,
        providerSpecificData: { minPromptsPerPage: 5, maxPromptsPerPage: 5 },
      },
      stream: false,
      signal: null,
    } as never);

    assert.equal(res6.response.status, 200);
    assert.equal(usedConvIds.length, 6);
    assert.equal(usedConvIds[5], "c_gemini_page_2");

    const rotatedSession = geminiSessionRotator.get("mock_psid_token:gemini-3.7-flash");
    assert.ok(rotatedSession);
    assert.equal(rotatedSession?.promptCount, 1);
    assert.equal(rotatedSession?.data.conversationId, "c_gemini_page_2");
  });

  it("defaults to ten attempts per conversation", () => {
    assert.equal(DEFAULT_PAGE_MIN_PROMPTS, 10);
    assert.equal(DEFAULT_PAGE_MAX_PROMPTS, 10);
  });

  it("preserves conversation pages without deleting them on rotate", async () => {
    const executor = new GeminiWebExecutor();
    const createdPages: string[] = [];

    executor.executeVideoGenerationHttp = async (opts) => {
      const pageId = opts.conversationId || `c_saved_page_${createdPages.length + 1}`;
      if (!createdPages.includes(pageId)) {
        createdPages.push(pageId);
      }
      return {
        success: true,
        status: 200,
        data: [{ url: `https://contribution.usercontent.google.com/download?c=${pageId}`, format: "mp4" }],
        conversationId: pageId,
      };
    };

    const cookie = "__Secure-1PSID=test_no_delete_cookie";

    // Run 6 prompts with limit of 3 to trigger rotation
    for (let i = 1; i <= 6; i++) {
      await executor.execute({
        model: "gemini-web",
        body: {
          messages: [{ role: "user", content: `Generate video: frame ${i}` }],
        },
        credentials: {
          apiKey: cookie,
          providerSpecificData: { minPromptsPerPage: 3, maxPromptsPerPage: 3 },
        },
        stream: false,
        signal: null,
      } as never);
    }

    // Both pages were created and kept intact (never deleted)
    assert.equal(createdPages.length, 2);
    assert.equal(createdPages[0], "c_saved_page_1");
    assert.equal(createdPages[1], "c_saved_page_2");
  });
});
