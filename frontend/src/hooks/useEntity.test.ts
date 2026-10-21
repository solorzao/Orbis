import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useEntity } from "./useEntity";
import { ApiError } from "@/lib/api";
import { fetchEntity, type ApiEntityDossier, type EntityRef } from "@/lib/entities";

vi.mock("@/lib/entities", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/entities")>()),
  fetchEntity: vi.fn(),
}));
const mockEntity = vi.mocked(fetchEntity);

function apiDossier(name: string, type: "person" | "org" = "person"): ApiEntityDossier {
  return {
    name,
    type,
    counts: { h24: 1, d7: 5 },
    trend: null,
    capped: false,
    cap: 2000,
    countries: [],
    places: [],
    timeline: [],
    co_mentions: [],
    headlines: [],
    since: null,
  };
}

const notFound = () => Promise.reject(new ApiError(404, "Not Found"));

const render = (entity: EntityRef | null) =>
  renderHook(({ entity }: { entity: EntityRef | null }) => useEntity(entity), {
    initialProps: { entity },
  });

beforeEach(() => {
  mockEntity.mockReset();
});

describe("useEntity", () => {
  it("is idle with nothing tracked", () => {
    const { result } = render(null);
    expect(result.current).toEqual({
      dossier: null,
      loading: false,
      notFound: false,
      error: false,
    });
    expect(mockEntity).not.toHaveBeenCalled();
  });

  it("loads a typed name's dossier", async () => {
    mockEntity.mockResolvedValue(apiDossier("Emmanuel Macron"));
    const { result } = render({ name: "emmanuel macron", type: "person" });
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.dossier?.name).toBe("Emmanuel Macron"));
    expect(mockEntity).toHaveBeenCalledWith(
      expect.objectContaining({ type: "person", name: "emmanuel macron" }),
    );
    expect(result.current.loading).toBe(false);
  });

  it("tries an untyped name as a person, then as an organisation", async () => {
    mockEntity.mockImplementationOnce(notFound).mockResolvedValueOnce(apiDossier("Houthis", "org"));
    const { result } = render({ name: "Houthis" });
    await waitFor(() => expect(result.current.dossier?.type).toBe("org"));
    expect(mockEntity.mock.calls.map((c) => c[0].type)).toEqual(["person", "org"]);
  });

  it("says when no person or organisation has the name", async () => {
    mockEntity.mockImplementation(notFound);
    const { result } = render({ name: "Nobody" });
    await waitFor(() => expect(result.current.notFound).toBe(true));
    expect(result.current).toMatchObject({ dossier: null, loading: false, error: false });
  });

  it("tells a failure from an unknown name", async () => {
    mockEntity.mockRejectedValue(new ApiError(500, "Server Error"));
    const { result } = render({ name: "Emmanuel Macron", type: "person" });
    await waitFor(() => expect(result.current.error).toBe(true));
    expect(result.current.notFound).toBe(false);
  });

  it("aborts the last name's request and never shows its dossier", async () => {
    let resolveFirst!: (d: ApiEntityDossier) => void;
    mockEntity
      .mockReturnValueOnce(new Promise((res) => (resolveFirst = res)))
      .mockResolvedValueOnce(apiDossier("European Union", "org"));
    const { result, rerender } = render({ name: "Emmanuel Macron", type: "person" });
    const signal = mockEntity.mock.calls[0][0].signal!;
    rerender({ entity: { name: "European Union", type: "org" } });
    expect(signal.aborted).toBe(true);
    await waitFor(() => expect(result.current.dossier?.name).toBe("European Union"));
    await act(async () => resolveFirst(apiDossier("Emmanuel Macron")));
    expect(result.current.dossier?.name).toBe("European Union");
  });

  it("forgets the dossier when tracking stops", async () => {
    mockEntity.mockResolvedValue(apiDossier("Emmanuel Macron"));
    const { result, rerender } = render({ name: "Emmanuel Macron", type: "person" });
    await waitFor(() => expect(result.current.dossier).not.toBeNull());
    rerender({ entity: null });
    expect(result.current.dossier).toBeNull();
  });
});
