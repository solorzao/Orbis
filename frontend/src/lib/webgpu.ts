/** Just what the probe needs of the WebGPU API (lib.dom has no WebGPU types). */
interface GpuLike {
  requestAdapter(): Promise<{ requestDevice(): Promise<{ destroy(): void }> } | null>;
}

let probe: Promise<boolean> | null = null;

/**
 * Whether WebGPU can really compute here: an adapter and a device, not just
 * `navigator.gpu`. three-globe's heatmap checks only `navigator.gpu`; where it
 * exists but no device can be made (a blocklisted GPU, a missing driver DLL)
 * it falls back to a WebGL2 path that draws garbage. So when the probe fails
 * it hides `navigator.gpu`, and the heatmap takes its slower but correct CPU
 * path. Probed once, the first time Intensity is shown.
 */
export function webGpuReady(): Promise<boolean> {
  probe ??= (async () => {
    const gpu = (navigator as { gpu?: GpuLike }).gpu;
    if (!gpu) return false;
    try {
      const adapter = await gpu.requestAdapter();
      const device = adapter ? await adapter.requestDevice() : null;
      if (device) {
        device.destroy();
        return true;
      }
    } catch {
      // no usable device: fall through
    }
    Object.defineProperty(navigator, "gpu", { value: undefined, configurable: true });
    return false;
  })();
  return probe;
}
