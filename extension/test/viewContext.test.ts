import { describe, expect, it } from "vitest";
import { compareViewContext, pendingCompareContext, preserveViewContext } from "../src/viewContext.js";

describe("persisted evolution view context", () => {
  it("restores only a complete, distinct, bounded compare pair", () => {
    expect(compareViewContext({ beforeRevision: " before ", afterRevision: " after " })).toEqual({
      beforeRevision: "before",
      afterRevision: "after"
    });
    expect(compareViewContext({ beforeRevision: "same", afterRevision: "same" })).toBeUndefined();
    expect(compareViewContext({ beforeRevision: "before" })).toBeUndefined();
    expect(compareViewContext({ beforeRevision: "a".repeat(257), afterRevision: "after" })).toBeUndefined();
    expect(compareViewContext({ beforeRevision: "be\nfore", afterRevision: "after" })).toBeUndefined();
  });

  it("keeps pending capture separate while rejecting corrupted state", () => {
    expect(pendingCompareContext({ beforeRevision: "before" })).toEqual({ beforeRevision: "before" });
    expect(pendingCompareContext({ beforeRevision: "before", afterRevision: "after" })).toEqual({
      beforeRevision: "before", afterRevision: "after"
    });
    expect(pendingCompareContext({ beforeRevision: "same", afterRevision: "same" })).toBeUndefined();
    expect(pendingCompareContext({ beforeRevision: 7 })).toBeUndefined();
  });

  it("restores only a concrete bounded shared lens ID", () => {
    expect(preserveViewContext(" lens-123 ")).toEqual({ lens: "lens-123" });
    expect(preserveViewContext("preview-lens")).toBeUndefined();
    expect(preserveViewContext("preview:abc")).toBeUndefined();
    expect(preserveViewContext("x".repeat(201))).toBeUndefined();
    expect(preserveViewContext("lens\ninvalid")).toBeUndefined();
    expect(preserveViewContext({ lens: "lens-123" })).toBeUndefined();
  });
});
