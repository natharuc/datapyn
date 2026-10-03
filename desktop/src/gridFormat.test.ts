import { describe, expect, it } from "vitest";
import { dateDisplay, decimalDisplay, formatCell } from "./gridFormat";

describe("Database value display",()=>{
  it("formats exact bigint and Decimal strings without a lossy Number conversion",()=>{
    expect(decimalDisplay("9007199254740993.145",2)).toBe("9,007,199,254,740,993.15");
    expect(decimalDisplay("-1.005",2)).toBe("-1.01");
    expect(decimalDisplay("1.999",0)).toBe("2");
    expect(decimalDisplay("3.45e2",4)).toBe("345.0000");
    expect(formatCell("0.123456",{type:"percent",decimals:2})).toBe("12.35%");
  });
  it("keeps plain values intact and supports custom currency affixes",()=>{
    expect(formatCell(null)).toBe("∅");
    expect(formatCell("000123")).toBe("000123");
    expect(formatCell("<text>",{type:"number"})).toBe("<text>");
    expect(formatCell("1000.3",{type:"currency",prefix:"R$ ",decimals:2})).toBe("R$ 1,000.30");
  });
  it("preserves database wall-clock timestamps and explicit epoch units",()=>{
    expect(dateDisplay("2026-10-03T15:30:00-03:00",true)).toBe("2026-10-03 15:30:00");
    expect(dateDisplay(1_700_000_000,false)).toBe("2023-11-14");
    expect(dateDisplay(1_700_000_000_000,false)).toBe("2023-11-14");
    expect(dateDisplay(1234,false)).toBeUndefined();
  });
});
