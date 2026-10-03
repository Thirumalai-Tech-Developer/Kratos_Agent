import assert from "node:assert/strict";
import test from "node:test";
import type { Page } from "playwright";
import { selectZaiBrowserModel } from "../../open-sse/executors/zai-web/browserAutomation";
import { browserModelName, getZaiModelCapabilities } from "../../open-sse/executors/zai-web/protocol";

test("GLM-5.3 is selected exactly when GLM-5.3-Flash is already selected", async () => {
  let selected = "GLM-5.3-Flash";
  let requested = "";
  const selector = {
    first() { return this; },
    async waitFor() {},
    async innerText() { return selected; },
    async evaluate() {},
    filter() { return this; },
  };
  const button = {
    first() { return this; },
    filter(options: { has?: { text: string }; hasText?: string }) {
      requested = options.has?.text || options.hasText || "";
      return this;
    },
    async evaluate() { selected = requested; },
  };
  const menu = {
    first() { return this; },
    filter() { return this; },
    async waitFor() {},
    locator() { return button; },
  };
  const page = {
    locator(css: string) { return css === '[role="menu"]' ? menu : selector; },
    getByText(text: string, options: { exact: boolean }) {
      assert.equal(options.exact, true);
      return { text };
    },
  } as unknown as Page;
  await selectZaiBrowserModel(page, "GLM-5.3");
  assert.equal(selected, "GLM-5.3");
});

test("Latest Z.ai wire IDs have their actual display names and modalities", () => {
  assert.equal(browserModelName("zw/x-preview-l"), "GLM-5.3-Flash");
  assert.equal(browserModelName("zw/glm-5.3"), "GLM-5.3");
  assert.equal(getZaiModelCapabilities("x-preview-l").vision, true);
  assert.equal(getZaiModelCapabilities("glm-5.3").vision, false);
  assert.equal(getZaiModelCapabilities("glm-5.3").reasoningEffort, true);
});
