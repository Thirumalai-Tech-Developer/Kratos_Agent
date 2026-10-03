import assert from "node:assert/strict";
import { test } from "node:test";
import { randomBytes } from "node:crypto";

process.env.STORAGE_ENCRYPTION_KEY = randomBytes(32).toString("hex");
const {
  sealBrowserSyncCredential,
  openBrowserSyncData,
  decryptConnectionFields,
  encryptConnectionFields,
} = await import("../../src/lib/db/encryption");
const { createLazyConnectionView, createLazyRowProxy } =
  await import("../../src/lib/db/providers/lazyConnectionView");

test("Browser companion credentials are sealed at rest and decoded across provider read paths", () => {
  const secret = { cookie: "session=private-cookie", token: "private-token", userAgent: "Chrome" };
  const sealed = sealBrowserSyncCredential(secret);
  assert.ok(sealed.startsWith("enc:v1:"));
  assert.ok(!sealed.includes(secret.cookie));
  assert.ok(!sealed.includes(secret.token));
  const stored = { browserSyncCredential: sealed, browserSyncProfile: "original-chrome" };
  const row = { id: "sync", provider: "qwen-browser", providerSpecificData: stored };
  assert.equal(openBrowserSyncData(stored).cookie, secret.cookie);
  assert.equal(createLazyConnectionView(row).providerSpecificData.token, secret.token);
  assert.equal(
    (createLazyRowProxy(row).providerSpecificData as Record<string, unknown>).cookie,
    secret.cookie
  );
  assert.equal(
    (decryptConnectionFields(row).providerSpecificData as Record<string, unknown>).token,
    secret.token
  );
  assert.equal(
    JSON.parse(JSON.stringify(createLazyRowProxy(row))).providerSpecificData.token,
    secret.token
  );
  assert.deepEqual(row.providerSpecificData, stored);
  assert.equal("cookie" in stored, false);
  const updated = encryptConnectionFields({
    ...row,
    providerSpecificData: { ...openBrowserSyncData(stored), cookie: "session=renewed" },
  });
  assert.equal("cookie" in updated.providerSpecificData, false);
  assert.equal("token" in updated.providerSpecificData, false);
  assert.equal(openBrowserSyncData(updated.providerSpecificData).cookie, "session=renewed");
});
