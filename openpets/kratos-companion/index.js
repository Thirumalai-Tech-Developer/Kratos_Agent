/// <reference types="@open-pets/plugin-sdk" />

const MIN_IDLE_MS = 14000;
const MAX_IDLE_MS = 26000;
const MIN_WANDER_DISTANCE = 180;
const MAX_WANDER_DISTANCE = 420;
const MIN_WANDER_DURATION_MS = 1800;
const MAX_WANDER_DURATION_MS = 4200;
const FUN_REACTIONS = ["waving", "jumping", "celebrating"];

function randomBetween(min, max) {
  return Math.floor(min + Math.random() * (max - min + 1));
}

OpenPetsPlugin.register({
  async start(ctx) {
    const pet = ctx.pets.default;
    let enabled = true;
    let busy = false;
    let elapsedMs = 0;
    let nextActionMs = randomBetween(MIN_IDLE_MS, MAX_IDLE_MS);

    const setMovement = async (active) => {
      await pet.physics({
        gravity: active,
        bounce: active ? 0.18 : 0,
        climbEdges: active,
      });
    };

    await setMovement(true);

    const updateCommand = async () => {
      await ctx.commands.register({
        id: "kratos-roaming-toggle",
        title: enabled ? "Pause Kratos roaming" : "Resume Kratos roaming",
        description: "Toggle the companion's occasional walks and playful reactions.",
        placement: "submenu",
      }, async () => {
        enabled = !enabled;
        elapsedMs = 0;
        nextActionMs = randomBetween(MIN_IDLE_MS, MAX_IDLE_MS);
        await setMovement(enabled);
        await updateCommand();
        await pet.react(enabled ? "success" : "waiting", { showMessage: false });
      });
    };

    await updateCommand();

    pet.onTick((dtMs) => {
      if (!enabled || busy) return;
      elapsedMs += Math.max(0, Math.min(dtMs, 1000));
      if (elapsedMs < nextActionMs) return;

      elapsedMs = 0;
      nextActionMs = randomBetween(MIN_IDLE_MS, MAX_IDLE_MS);
      busy = true;
      void (async () => {
        if (Math.random() < 0.72) {
          await pet.wander({
            distance: randomBetween(MIN_WANDER_DISTANCE, MAX_WANDER_DISTANCE),
            durationMs: randomBetween(MIN_WANDER_DURATION_MS, MAX_WANDER_DURATION_MS),
          });
        } else {
          const reaction = FUN_REACTIONS[randomBetween(0, FUN_REACTIONS.length - 1)];
          await pet.react(reaction, { showMessage: false });
        }
      })().catch((error) => {
        ctx.log.warn("Kratos companion action failed", error);
      }).finally(() => {
        busy = false;
      });
    });
  },
});
