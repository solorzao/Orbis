/** Just what the probe needs of the WebGPU API (lib.dom has no WebGPU types). */
interface GpuLike {
  requestAdapter(): Promise<{ requestDevice(): Promise<{ destroy(): void }> } | null>;
}

/** How long the probe waits for an adapter and a device before calling WebGPU unusable. */
export const PROBE_TIMEOUT_MS = 2000;

let probe: Promise<boolean> | null = null;

/** Ask the GPU for an adapter and a device; true only when both come. */
async function deviceWorks(gpu: GpuLike): Promise<boolean> {
  try {
    const adapter = await gpu.requestAdapter();
    const device = adapter ? await adapter.requestDevice() : null;
    device?.destroy();
    return device !== null;
  } catch {
    return false;
  }
}

/**
 * Whether WebGPU can really compute here: an adapter and a device, not just
 * `navigator.gpu`. three-globe's heatmap checks only `navigator.gpu`; where it
 * exists but no device can be made (a blocklisted GPU, a missing driver DLL)
 * it falls back to a WebGL2 path that draws garbage. So when the probe fails,
 * or gets no answer within PROBE_TIMEOUT_MS, it hides `navigator.gpu`, and the
 * heatmap takes its slower but correct CPU path. Probed once, the first time
 * Intensity is shown.
 */
export function webGpuReady(): Promise<boolean> {
  probe ??= (async () => {
    const gpu = (navigator as { gpu?: GpuLike }).gpu;
    if (!gpu) return false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<false>((resolve) => {
      timer = setTimeout(() => resolve(false), PROBE_TIMEOUT_MS);
    });
    const works = await Promise.race([deviceWorks(gpu), timeout]);
    clearTimeout(timer);
    if (!works) Object.defineProperty(navigator, "gpu", { value: undefined, configurable: true });
    return works;
  })();
  return probe;
}
