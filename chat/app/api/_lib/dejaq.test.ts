import { afterEach, describe, expect, it } from "vitest";
import { getDejaQConfig, isNextResponse } from "./dejaq";

const ORIGINAL_ENV = process.env.DEJAQ_API_KEY;

afterEach(() => {
  if (ORIGINAL_ENV === undefined) delete process.env.DEJAQ_API_KEY;
  else process.env.DEJAQ_API_KEY = ORIGINAL_ENV;
});

describe("getDejaQConfig key resolution precedence", () => {
  it("uses the Settings-supplied key even when a different env key is set", () => {
    process.env.DEJAQ_API_KEY = "env-key";
    const config = getDejaQConfig(null, "settings-key");
    expect(isNextResponse(config)).toBe(false);
    if (!isNextResponse(config)) expect(config.apiKey).toBe("settings-key");
  });

  it("falls back to DEJAQ_API_KEY when Settings has no key", () => {
    process.env.DEJAQ_API_KEY = "env-key";
    const config = getDejaQConfig(null, null);
    expect(isNextResponse(config)).toBe(false);
    if (!isNextResponse(config)) expect(config.apiKey).toBe("env-key");
  });

  it("falls back to DEJAQ_API_KEY when Settings sends only whitespace", () => {
    process.env.DEJAQ_API_KEY = "env-key";
    const config = getDejaQConfig(null, "   ");
    expect(isNextResponse(config)).toBe(false);
    if (!isNextResponse(config)) expect(config.apiKey).toBe("env-key");
  });

  it("returns a 424 missing_dejaq_api_key error when neither Settings nor env has a key", async () => {
    delete process.env.DEJAQ_API_KEY;
    const config = getDejaQConfig(null, null);
    expect(isNextResponse(config)).toBe(true);
    if (isNextResponse(config)) {
      expect(config.status).toBe(424);
      const body = await config.json();
      expect(body.code).toBe("missing_dejaq_api_key");
    }
  });
});
