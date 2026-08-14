import { describe, expect, it } from "vitest";
import { validateApiKey, validateDatabase, validateProfileLabel } from "../src/setupValidation.js";

describe("setup validation", () => {
  it("rejects blank and control-bearing visible labels", () => {
    expect(validateProfileLabel(" ")).toBeTruthy();
    expect(validateProfileLabel("work\nsecret")).toBeTruthy();
    expect(validateProfileLabel("Work account")).toBeUndefined();
  });

  it("validates secrets without returning their values", () => {
    expect(validateApiKey("short")).not.toContain("short");
    expect(validateApiKey("valid-secret-key")).toBeUndefined();
    expect(validateDatabase("private-db")).toBeUndefined();
    expect(validateDatabase("bad\ndatabase")).not.toContain("bad");
  });
});
