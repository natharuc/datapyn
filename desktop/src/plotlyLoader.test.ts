import { afterEach, describe, expect, it, vi } from "vitest";

const moduleLoad = vi.hoisted(() => vi.fn());
vi.mock("plotly.js-basic-dist-min", () => moduleLoad());
afterEach(() => { vi.resetModules(); moduleLoad.mockReset(); });

describe("lazy Plotly module", () => {
  it("does not import before use and shares one in-flight import", async () => {
    const renderer = { react: vi.fn() }; moduleLoad.mockResolvedValue({ default: renderer });
    const { loadPlotly } = await import("./plotlyLoader");
    expect(moduleLoad).not.toHaveBeenCalled();
    const first = loadPlotly(), second = loadPlotly(); expect(second).toBe(first);
    expect(await first).toBe(renderer); expect(moduleLoad).toHaveBeenCalledTimes(1);
    expect(await loadPlotly()).toBe(renderer); expect(moduleLoad).toHaveBeenCalledTimes(1);
  });
});
