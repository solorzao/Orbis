import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

type GpuStub = { requestAdapter: ReturnType<typeof vi.fn> };

function stubGpu(gpu: GpuStub | undefined) {
  Object.defineProperty(navigator, "gpu", { value: gpu, configurable: true });
}

async function freshProbe() {
  vi.resetModules();
  return (await import("./webgpu")).webGpuReady;
}

beforeEach(() => {
  stubGpu(undefined);
});

afterEach(() => {
  delete (navigator as { gpu?: unknown }).gpu;
});

describe("webGpuReady", () => {
  it("is false without navigator.gpu", async () => {
    const webGpuReady = await freshProbe();
    await expect(webGpuReady()).resolves.toBe(false);
  });

  it("is true with an adapter and a device, and frees the test device", async () => {
    const destroy = vi.fn();
    const gpu = {
      requestAdapter: vi.fn().mockResolvedValue({
        requestDevice: vi.fn().mockResolvedValue({ destroy }),
      }),
    };
    stubGpu(gpu);
    const webGpuReady = await freshProbe();
    await expect(webGpuReady()).resolves.toBe(true);
    expect(destroy).toHaveBeenCalled();
    expect((navigator as { gpu?: unknown }).gpu).toBe(gpu);
  });

  it("hides navigator.gpu when there is no adapter, so three-globe uses its CPU path", async () => {
    stubGpu({ requestAdapter: vi.fn().mockResolvedValue(null) });
    const webGpuReady = await freshProbe();
    await expect(webGpuReady()).resolves.toBe(false);
    expect((navigator as { gpu?: unknown }).gpu).toBeUndefined();
  });

  it("hides navigator.gpu when the device can't be created", async () => {
    stubGpu({
      requestAdapter: vi.fn().mockResolvedValue({
        requestDevice: vi.fn().mockRejectedValue(new Error("dxil.dll")),
      }),
    });
    const webGpuReady = await freshProbe();
    await expect(webGpuReady()).resolves.toBe(false);
    expect((navigator as { gpu?: unknown }).gpu).toBeUndefined();
  });

  it("probes once", async () => {
    const requestAdapter = vi.fn().mockResolvedValue(null);
    stubGpu({ requestAdapter });
    const webGpuReady = await freshProbe();
    await webGpuReady();
    await webGpuReady();
    expect(requestAdapter).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["the adapter", () => ({ requestAdapter: vi.fn(() => new Promise(() => {})) })],
    [
      "the device",
      () => ({
        requestAdapter: vi.fn().mockResolvedValue({
          requestDevice: vi.fn(() => new Promise(() => {})),
        }),
      }),
    ],
  ])("gives up after 2 s when %s never comes", async (_, gpu) => {
    vi.useFakeTimers();
    try {
      stubGpu(gpu());
      const webGpuReady = await freshProbe();
      let settled: boolean | undefined;
      webGpuReady().then((ok) => (settled = ok));
      await vi.advanceTimersByTimeAsync(1999);
      expect(settled).toBeUndefined();
      await vi.advanceTimersByTimeAsync(1);
      expect(settled).toBe(false);
      expect((navigator as { gpu?: unknown }).gpu).toBeUndefined();
    } finally {
      vi.useRealTimers();
    }
  });
});
