import { afterEach, describe, expect, it, vi } from "vitest";
import { createRuntimeRequester, RuntimeRequestError, runtimeRequestError } from "./runtime";
import { sshHostTrust } from "./sshHostTrust";

const details = { host: "ssh.example", port: 22, key_type: "ssh-ed25519", public_key: "AAAAB3NzaC1lZDI1NTE5AAAA", fingerprint: `SHA256:${"A".repeat(43)}` };
const unknown = (host = details.host) => ({ code: "ssh_host_key_unknown", message: "Confirme o servidor SSH.", details: { ...details, host } });
afterEach(() => sshHostTrust.cancel());

describe("SSH trust through the runtime bridge", () => {
  it("rejects a late tunnel-only test success after the settings dialog closes", async () => {
    let finish!: (value:unknown)=>void;
    const requester = createRuntimeRequester(<T>(method:string)=>method==="ssh.tunnels.test" ? new Promise<T>(resolve=>{finish=resolve as (value:unknown)=>void;}) : Promise.resolve({} as T));
    const task=requester.request("ssh.tunnels.test",{test_id:"standalone"});
    const rejected=expect(task).rejects.toMatchObject({code:"cancelled"});
    await requester.request("connection.test_cancel",{test_id:"standalone"});finish({success:true});await rejected;
  });
  it("preserves structured errors and treats JSON-like messages as ordinary errors", () => {
    const error = runtimeRequestError(unknown());
    expect(error).toBeInstanceOf(RuntimeRequestError);
    expect(error).toMatchObject(unknown());
    expect(runtimeRequestError(JSON.stringify(unknown()))).not.toBeInstanceOf(RuntimeRequestError);
  });
  it("waits for consent before storing a public key and retrying exactly once", async () => {
    const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
    let first = true;
    const requester = createRuntimeRequester(async <T>(method: string, params: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === "connection.test" && first) { first = false; throw unknown(); }
      return { success: true } as T;
    });
    const params = { test_id: "test-one", config: { ssh: { password: "private-password", passphrase: "private-passphrase" } } };
    const task = requester.request("connection.test", params);
    await vi.waitFor(() => expect(sshHostTrust.getSnapshot()).toBeDefined());
    expect(calls).toHaveLength(1);
    expect(JSON.stringify(sshHostTrust.getSnapshot())).not.toContain("private-");
    sshHostTrust.confirm(sshHostTrust.getSnapshot()!.id);
    await expect(task).resolves.toEqual({ success: true });
    expect(calls.map(call => call.method)).toEqual(["connection.test", "ssh.host_key.trust", "connection.test"]);
    expect(calls[1].params).toEqual({ details });
    expect(calls[2].params).toBe(params);
    expect(sshHostTrust.getSnapshot()).toBeUndefined();
  });
  it("never prompts or retries when the recorded host key changes", async () => {
    const call = vi.fn(async () => { throw { code: "ssh_host_key_changed", message: "A chave SSH mudou." }; });
    await expect(createRuntimeRequester(call).request("connection.connect", { session_id: "one" })).rejects.toMatchObject({ code: "ssh_host_key_changed" });
    expect(call).toHaveBeenCalledTimes(1);
    expect(sshHostTrust.getSnapshot()).toBeUndefined();
  });
  it("declining the fingerprint stops the operation without a direct connection fallback", async () => {
    const call = vi.fn(async () => { throw unknown(); });
    const task = createRuntimeRequester(call).request("connection.connect", { session_id: "one" });
    const rejected = expect(task).rejects.toMatchObject({ code: "cancelled" });
    await vi.waitFor(() => expect(sshHostTrust.getSnapshot()).toBeDefined());
    sshHostTrust.decline(sshHostTrust.getSnapshot()!.id);
    await rejected;
    expect(call).toHaveBeenCalledTimes(1);
  });
  it("cancels one tab's pending trust without blocking another tab", async () => {
    const attempts = new Map<string, number>();
    const requester = createRuntimeRequester(async <T>(method: string, params: Record<string, unknown>) => {
      const session = String(params.session_id);
      if (method === "connection.connect") {
        const count = attempts.get(session) ?? 0; attempts.set(session, count + 1);
        if (!count) throw unknown(`${session}.example`);
      }
      return {} as T;
    });
    const first = requester.request("connection.connect", { session_id: "one" });
    const rejected = expect(first).rejects.toMatchObject({ code: "cancelled" });
    const second = requester.request("connection.connect", { session_id: "two" });
    await vi.waitFor(() => expect(sshHostTrust.getSnapshot()?.details.host).toBe("one.example"));
    await requester.request("session.close", { session_id: "one" }); await rejected;
    expect(sshHostTrust.getSnapshot()?.details.host).toBe("two.example");
    sshHostTrust.confirm(sshHostTrust.getSnapshot()!.id); await second;
    expect(attempts.get("one")).toBe(1); expect(attempts.get("two")).toBe(2);
  });
  it("ignores a late challenge from an already cancelled test", async () => {
    let reject!: (error: unknown) => void;
    const requester = createRuntimeRequester(<T>(method: string) => method === "connection.test"
      ? new Promise<T>((_resolve, fail) => { reject = fail; }) : Promise.resolve({} as T));
    const task = requester.request("connection.test", { test_id: "test-one" });
    const rejected = expect(task).rejects.toMatchObject({ code: "cancelled" });
    await requester.request("connection.test_cancel", { test_id: "test-one" });
    reject(unknown()); await rejected;
    expect(sshHostTrust.getSnapshot()).toBeUndefined();
  });
  it.each(["session.reset","session.error"] as const)("removes the pending fingerprint after %s without trusting or retrying it",async(event)=>{
    const call=vi.fn(async()=>{throw unknown();});
    const requester=createRuntimeRequester(call);
    const task=requester.request("connection.connect",{session_id:"one"});
    const failed=expect(task).rejects.toMatchObject({code:"cancelled"});
    await vi.waitFor(()=>expect(sshHostTrust.getSnapshot()).toBeDefined());
    requester.receiveEvent(event==="session.error"?{event,payload:{session_id:"one",error:"Kernel reset"}}:{event,payload:{session_id:"one",reason:"Kernel reset"}});
    await failed;
    expect(sshHostTrust.getSnapshot()).toBeUndefined();
    expect(call).toHaveBeenCalledTimes(1);
  });
  it("rejects a connection that finishes after its session was closed",async()=>{
    let finish!:(value:unknown)=>void;
    const requester=createRuntimeRequester(<T>(method:string)=>method==="connection.connect"
      ?new Promise<T>(resolve=>{finish=resolve as (value:unknown)=>void;}):Promise.resolve({} as T));
    const task=requester.request("connection.connect",{session_id:"one"});
    const failed=expect(task).rejects.toMatchObject({code:"cancelled"});
    await requester.request("session.close",{session_id:"one"});finish({success:true});await failed;
  });
  it("does not retry after a trust-write failure or malformed challenge", async () => {
    const calls: string[] = [];
    const requester = createRuntimeRequester(async <T>(method: string) => {
      calls.push(method);
      if (method === "ssh.host_key.trust") throw { code: "ssh_host_key_changed", message: "A chave mudou." };
      throw unknown();
    });
    const task = requester.request("connection.connect", { session_id: "one" });
    const rejected = expect(task).rejects.toMatchObject({ code: "ssh_host_key_changed" });
    await vi.waitFor(() => expect(sshHostTrust.getSnapshot()).toBeDefined());
    sshHostTrust.confirm(sshHostTrust.getSnapshot()!.id); await rejected;
    expect(calls).toEqual(["connection.connect", "ssh.host_key.trust"]);
    const invalid = createRuntimeRequester(async () => { throw { ...unknown(), details: { ...details, port: 0 } }; });
    await expect(invalid.request("connection.connect")).rejects.toMatchObject({ code: "ssh_host_key_unknown" });
    expect(sshHostTrust.getSnapshot()).toBeUndefined();
  });
});
