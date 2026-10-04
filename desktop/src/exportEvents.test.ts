import { describe, expect, it } from "vitest";
import { isRuntimeEvent } from "./runtime";
import { applyRuntimeEvent, newSession } from "./workspace";
describe("export operation events", () => {
  it("accepts progress without execution IDs and leaves the workspace unchanged", () => {
    const session=newSession(); session.busy=true; session.currentExecutionId="running-query";
    const event={event:"result.export_progress",payload:{session_id:session.id,operation_id:"export",phase:"writing",current:10,total:100}};
    expect(isRuntimeEvent(event)).toBe(true);
    if(isRuntimeEvent(event)) expect(applyRuntimeEvent(session,event)).toBe(session);
  });
  it("rejects incomplete or non-finite progress before reaching subscribers", () => {
    const payload={session_id:"session",operation_id:"export",phase:"writing",current:1,total:100};
    for(const patch of [{operation_id:""},{current:NaN},{total:-1},{phase:"unknown"}]) {
      expect(isRuntimeEvent({event:"result.export_progress",payload:{...payload,...patch}})).toBe(false);
    }
  });
});
