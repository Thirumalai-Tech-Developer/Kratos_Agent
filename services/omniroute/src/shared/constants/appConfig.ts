import pkg from "../../../package.json" with { type: "json" };

export const APP_CONFIG = {
  name: "Kratos Studio",
  description: "Kratos Agent with the complete OmniRoute gateway",
  version: pkg.version,
};

export const THEME_CONFIG = {
  storageKey: "theme",
  defaultTheme: "system",
};
