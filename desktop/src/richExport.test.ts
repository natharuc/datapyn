import {describe, expect, it} from "vitest";
import {artifactExportTarget} from "./richExport";

describe("rich output export destinations", () => {
  it("preserves JPEG aliases and uppercase destination extensions", () => {
    expect(artifactExportTarget("image", "C:/dados/chart.JPG")).toEqual({path: "C:/dados/chart.JPG", format: "jpg"});
    expect(artifactExportTarget("image", "C:/dados/chart.jpeg")).toEqual({path: "C:/dados/chart.jpeg", format: "jpeg"});
  });
  it("adds an extension only when a supported one is missing", () => {
    expect(artifactExportTarget("image", "C:/dir.with.dot/chart")).toEqual({path: "C:/dir.with.dot/chart.png", format: "png"});
    expect(artifactExportTarget("plotly", "C:/chart.json")).toEqual({path: "C:/chart.json", format: "json"});
    expect(artifactExportTarget("html", "C:/chart")).toEqual({path: "C:/chart.html", format: "html"});
  });
});
