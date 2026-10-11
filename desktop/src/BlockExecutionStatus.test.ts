import {createElement} from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {describe,expect,it} from "vitest";
import {BlockExecutionLine,BlockExecutionStatus,formatExecutionTime} from "./BlockExecutionStatus";
import {newBlock} from "./workspace";

describe("execution feedback",()=>{
  it.each([[0,"0.000 s"],[1234.99,"1.234 s"],[59999,"59.999 s"],[60001,"1:00.001"],[3600123,"1:00:00.123"],[-1,"0.000 s"],[NaN,"0.000 s"]])("formats %s ms without losing milliseconds",(value,expected)=>expect(formatExecutionTime(value as number)).toBe(expected));
  it("keeps final driver duration and removes the moving line after cancellation",()=>{
    const block={...newBlock(),status:"cancelled" as const,duration_ms:2412.5};
    const html=renderToStaticMarkup(createElement(BlockExecutionStatus,{block}));
    expect(html).toContain("2.412 s");expect(html).toContain("Cancelado");
    expect(renderToStaticMarkup(createElement(BlockExecutionLine,{active:false}))).toBe("");
    expect(renderToStaticMarkup(createElement(BlockExecutionLine,{active:true}))).toContain('aria-hidden="true"');
  });
});
