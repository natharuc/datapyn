import { expect, it } from "vitest";
import { ConnectionsController } from "./connections";
import { saveSshTunnel } from "./sshTunnels";
import type { RuntimeTransport } from "./runtime";

it("keeps SSH credentials separate from public catalog data and refreshes shared references", async () => {
  const calls: Array<{method:string;params?:Record<string, unknown>}> = [];
  const transport: RuntimeTransport = { async request<T>(method: string, params?: Record<string, unknown>) { calls.push({method,params}); return (method === "connections.list" ? {version:1,groups:[],connections:[],ssh_tunnels:[]} : {}) as T; }, async subscribe() { return () => {}; } };
  const controller = new ConnectionsController(transport);
  await saveSshTunnel(controller, " VPS ", {enabled:true,host:"vps.test",port:22,username:"deploy",auth_method:"private_key",private_key_path:"/keys/deploy",password:"never-public",passphrase:"never-public-either"}, "tunnel");
  expect(calls[0]).toEqual({method:"ssh.tunnels.save",params:{tunnel:{id:"tunnel",name:"VPS",config:{enabled:true,host:"vps.test",port:22,username:"deploy",auth_method:"private_key",private_key_path:"/keys/deploy"}},password:"never-public",passphrase:"never-public-either",save_credentials:true}});
  expect(calls[1].method).toBe("connections.list");
  expect(JSON.stringify(controller.getSnapshot())).not.toContain("never-public");
});

it("does not overwrite a saved secret with a blank edit", async () => {
  let saved: Record<string,unknown> | undefined;
  const transport: RuntimeTransport = { async request<T>(method: string, params?: Record<string, unknown>) { if(method==="ssh.tunnels.save")saved=params;return {version:1,groups:[],connections:[],ssh_tunnels:[]} as T; }, async subscribe() { return () => {}; } };
  await saveSshTunnel(new ConnectionsController(transport), "VPS", {enabled:true,host:"vps.test",port:22,username:"deploy",auth_method:"password",password:""}, "tunnel");
  expect(saved).not.toHaveProperty("password");
});
