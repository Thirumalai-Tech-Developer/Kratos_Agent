import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createContext, runInContext } from "node:vm";
import test from "node:test";
import { JSDOM } from "jsdom";
import type { BrowserModel } from "../../open-sse/utils/browserModels";

const source = await readFile(
  new URL("../../scripts/ops/browserSyncExtension/modelDiscovery.js", import.meta.url),
  "utf8"
);
type CaptureContext = { provider: string; pageKey: string; authKey: string; signedOut?: boolean };
type Discovery = {
  readModelPicker: (document: Document, provider: string) => BrowserModel[] | undefined;
  createModelTracker: (document: Document) => {
    capture: (context: CaptureContext) => BrowserModel[] | undefined;
  };
};
function fixture(html: string) {
  const dom = new JSDOM(html, { url: "https://chat.qwen.ai/" });
  dom.window.HTMLElement.prototype.getClientRects = function () {
    return [{ width: 100, height: 20 }] as unknown as DOMRectList;
  };
  const context = createContext({ document: dom.window.document });
  runInContext(source, context, { filename: "modelDiscovery.js" });
  return {
    dom,
    document: dom.window.document,
    discovery: context.__kratosModelDiscovery as Discovery,
  };
}
const picker = `<div data-model-picker>
  <button role="option" data-model-name="Qwen Observed">Qwen Observed</button>
  <button role="option" data-model-id="real-vision-id" data-model-name="Vision Model"
    data-input-modalities='["text","image"]'>Vision Model</button>
  <button role="option" data-model-id="paid" data-model-name="Paid Model" data-free="false">Paid Model</button>
  <button role="option" data-model-id="locked" data-model-name="Locked Model" aria-disabled="true">Locked Model</button>
</div>`;

test("Picker captures actual labels, access states and explicit modalities", () => {
  const f = fixture(picker);
  try {
    const models = f.discovery.readModelPicker(f.document, "qwen-browser")!;
    assert.equal(models[0].id, "qwen-ui-qwen-observed");
    assert.equal(models[0].name, "Qwen Observed");
    assert.equal(models[0].supportsVision, undefined);
    assert.equal(models[1].supportsVision, true);
    assert.equal(JSON.stringify(models[1].inputModalities), '["text","image"]');
    assert.equal(models[2].free, false);
    assert.equal(models[3].selectable, false);
  } finally {
    f.dom.window.close();
  }
});

test("Conversation text cannot become a discovered model, including fake nested menus", () => {
  const f = fixture(`<article data-message-id="reply">${picker}</article>
    <div data-model-id="fabricated">Fabricated assistant suggestion</div>`);
  try {
    assert.equal(f.discovery.readModelPicker(f.document, "qwen-browser"), undefined);
  } finally {
    f.dom.window.close();
  }
});

test("Closed/loading pickers retain observations; auth changes and logout clear them", () => {
  const f = fixture(picker);
  try {
    const tracker = f.discovery.createModelTracker(f.document);
    const initial = {
      provider: "qwen-browser",
      pageKey: "https://chat.qwen.ai/",
      authKey: "account-a",
    };
    assert.equal(tracker.capture(initial)?.length, 4);
    f.document.body.innerHTML = `<div data-model-picker>Loading...</div>`;
    assert.equal(tracker.capture(initial)?.length, 4);
    f.document.body.innerHTML = "";
    assert.equal(tracker.capture(initial)?.length, 4);
    assert.equal(tracker.capture({ ...initial, authKey: "account-b" })?.length, 0);
    f.document.body.innerHTML = picker;
    assert.equal(tracker.capture({ ...initial, authKey: "account-b" })?.length, 4);
    f.document.body.innerHTML = `<button>Log in</button>`;
    assert.equal(tracker.capture({ ...initial, authKey: "account-b" })?.length, 0);
  } finally {
    f.dom.window.close();
  }
});

test("An unobserved picker is not mistaken for an empty model catalog", () => {
  const f = fixture(`<button>Log in</button>`);
  try {
    const tracker = f.discovery.createModelTracker(f.document);
    assert.equal(
      tracker.capture({ provider: "qwen-browser", pageKey: "https://chat.qwen.ai/", authKey: "" }),
      undefined
    );
  } finally {
    f.dom.window.close();
  }
});
