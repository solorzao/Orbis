import { describe, it, expect } from "vitest";
import { NO_OVERLAYS, overlayNote, overlays } from "./overlays";

describe("overlays: Links and Relations, one at a time (decision 5)", () => {
  it("starts with both off", () => {
    expect(NO_OVERLAYS).toEqual({ links: false, relations: false });
  });

  it("turns Relations off when Links turns on, and the reverse", () => {
    const relations = overlays(NO_OVERLAYS, { type: "relations", on: true });
    expect(relations).toEqual({ links: false, relations: true });
    expect(overlays(relations, { type: "links", on: true })).toEqual({
      links: true,
      relations: false,
    });
    expect(overlays({ links: true, relations: false }, { type: "relations", on: true })).toEqual({
      links: false,
      relations: true,
    });
  });

  it("turns off only its own", () => {
    expect(overlays({ links: true, relations: false }, { type: "relations", on: false })).toEqual({
      links: true,
      relations: false,
    });
    expect(overlays({ links: true, relations: false }, { type: "links", on: false })).toEqual({
      links: false,
      relations: false,
    });
  });

  it("keeps the same state when nothing changes, so React skips the render", () => {
    const state = { links: true, relations: false };
    expect(overlays(state, { type: "links", on: true })).toBe(state);
    expect(overlays(state, { type: "relations", on: false })).toBe(state);
  });
});

describe("overlayNote: what the announcer says when one turns the other off", () => {
  it("names both", () => {
    expect(overlayNote({ links: true, relations: false }, { type: "relations", on: true })).toBe(
      "Relations on. Links off.",
    );
    expect(overlayNote({ links: false, relations: true }, { type: "links", on: true })).toBe(
      "Links on. Relations off.",
    );
  });

  it("says nothing when the other was off anyway, or for turning one off", () => {
    expect(overlayNote(NO_OVERLAYS, { type: "relations", on: true })).toBeNull();
    expect(overlayNote({ links: true, relations: false }, { type: "links", on: false })).toBeNull();
  });
});
