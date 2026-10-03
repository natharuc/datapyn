import {describe,expect,it} from "vitest";
import {acceptStartupSnapshot,INITIAL_STARTUP,startupEditorId,startupPhase,type StartupSnapshot} from "./splashProtocol";

const snapshot=(phase:StartupSnapshot["phase"],attempt=0,message:string=phase):StartupSnapshot=>({phase,attempt,message,version:"1.57.0"});

describe("startup status delivery",()=>{
  it("keeps a newer event when the initial snapshot reply arrives afterwards",()=>{
    const event=snapshot("workspace"),lateReply=snapshot("runtime");
    expect(acceptStartupSnapshot(event,lateReply)).toBe(event);
    expect(acceptStartupSnapshot(INITIAL_STARTUP,event)).toBe(event);
  });

  it("accepts a new attempt after an error and ignores prior-attempt replies",()=>{
    const failed=snapshot("error",0,"Workspace could not be restored"),retry=snapshot("runtime",1,"Retrying");
    expect(acceptStartupSnapshot(failed,retry)).toBe(retry);
    for(const phase of ["workspace","ready","error"] as const)expect(acceptStartupSnapshot(retry,snapshot(phase,0))).toBe(retry);
    expect(acceptStartupSnapshot(retry,snapshot("workspace",1)).phase).toBe("workspace");
  });

  it("keeps ready and error terminal until a different attempt starts",()=>{
    for(const phase of ["ready","error"] as const){
      const terminal=snapshot(phase,2);
      for(const incoming of ["frontend","runtime","workspace","editor","ready","error"] as const)expect(acceptStartupSnapshot(terminal,snapshot(incoming,2))).toBe(terminal);
    }
  });

  it("accepts details for the current phase and avoids notifying identical snapshots",()=>{
    const current=snapshot("workspace"),same={...current};
    expect(acceptStartupSnapshot(current,same)).toBe(current);
    const detailed={...same,message:"Restoring 121 analyses"};
    expect(acceptStartupSnapshot(current,detailed)).toBe(detailed);
    const versioned={...same,version:"1.57.1"};
    expect(acceptStartupSnapshot(current,versioned)).toBe(versioned);
  });
});

describe("one restored startup editor",()=>{
  const blocks=[{id:"sql"},{id:"python",cell_type:"code"},{id:"note",cell_type:"markdown"},{id:"raw",cell_type:"raw"},{id:"hidden",collapsed:true}];

  it("prepares the focused usable code block without mounting every block",()=>{
    expect(startupEditorId(blocks,"python")).toBe("python");
    expect(startupEditorId(blocks)).toBe("sql");
  });

  it("falls back when saved focus points to collapsed, non-code or deleted content",()=>{
    for(const focused of ["hidden","note","raw","deleted"])expect(startupEditorId(blocks,focused)).toBe("sql");
  });

  it("respects maximization instead of waiting for an editor outside the visible block",()=>{
    expect(startupEditorId(blocks,"sql","python")).toBe("python");
    for(const maximized of ["note","raw","hidden","deleted"])expect(startupEditorId(blocks,"sql",maximized)).toBeUndefined();
  });

  it("allows the workbench to become ready when there is no usable code editor",()=>{
    expect(startupEditorId([])).toBeUndefined();
    expect(startupEditorId([{id:"collapsed",collapsed:true},{id:"note",cell_type:"markdown"},{id:"raw",cell_type:"raw"}])).toBeUndefined();
  });
});

describe("functional startup readiness",()=>{
  const ready={runtime:"ready" as const,error:"",profile:true,layout:true,editor:true,files:true};

  it("waits for broker, profile, docking, editor and startup files independently",()=>{
    expect(startupPhase({...ready,runtime:"connecting"})).toBe("runtime");
    expect(startupPhase({...ready,profile:false})).toBe("workspace");
    for(const flag of ["layout","editor","files"] as const)expect(startupPhase({...ready,[flag]:false})).toBe("editor");
    expect(startupPhase(ready)).toBe("ready");
  });

  it("reports failures before successful readiness and resumes when retry clears them",()=>{
    expect(startupPhase({...ready,runtime:"unavailable"})).toBe("error");
    expect(startupPhase({...ready,error:"Corrupted workspace"})).toBe("error");
    expect(startupPhase({...ready,runtime:"connecting",profile:false,layout:false,editor:false,files:false})).toBe("runtime");
    expect(startupPhase(ready)).toBe("ready");
  });
});
