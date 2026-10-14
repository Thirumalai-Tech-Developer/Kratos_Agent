// Read only. No prompt insertion, model requests, clicks or navigation.
if (chrome.runtime?.id)
  chrome.runtime.onMessage.addListener((message, sender, reply) => {
    if (
      sender.id !== chrome.runtime.id ||
      message?.kind !== "kratos-storage-snapshot"
    )
      return;
    try {
      reply({
        origin: location.origin,
        localStorage: Object.entries(localStorage).map(([name, value]) => ({
          name,
          value,
        })),
      });
    } catch {
      reply(null);
    }
  });
let pollTimer;
function poll() {
  try {
    if (!chrome.runtime?.id) throw new Error("Extension reloaded");
    chrome.runtime.sendMessage({ kind: "kratos-chatgpt-poll" }).catch(() => {});
    return true;
  } catch {
    if (pollTimer !== undefined) clearInterval(pollTimer);
    return false;
  }
}
if (poll()) pollTimer = setInterval(poll, 1000);
