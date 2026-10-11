import { describe, expect, it } from "vitest";
import { SshHostTrustCancelledError, SshHostTrustController, type SshHostKeyDetails } from "./sshHostTrust";

const key = (host = "ssh.example", fingerprint = "SHA256:abc"): SshHostKeyDetails => ({ host, port: 22, key_type: "ssh-ed25519", public_key: "ssh-ed25519 public-key-" + fingerprint, fingerprint });

describe("SSH host trust queue", () => {
  it("waits for explicit approval and freezes the displayed key before accepting", async () => {
    const controller = new SshHostTrustController(), details = key();
    let approved = false;
    const promise = controller.request(details).then(() => { approved = true; });
    details.fingerprint = "SHA256:changed";
    await Promise.resolve();
    expect(approved).toBe(false); expect(controller.getSnapshot()?.details.fingerprint).toBe("SHA256:abc");
    controller.confirm(controller.getSnapshot()!.id); await promise;
    expect(approved).toBe(true); expect(controller.getSnapshot()).toBeUndefined();
  });
  it("queues different hosts without letting a stale dialog approve the next server", async () => {
    const controller = new SshHostTrustController();
    const first = controller.request(key()), firstId = controller.getSnapshot()!.id;
    const second = controller.request(key("another.example"));
    controller.confirm(firstId); await first;
    const secondId = controller.getSnapshot()!.id;
    controller.confirm(firstId); expect(controller.getSnapshot()?.id).toBe(secondId);
    const rejection = expect(second).rejects.toBeInstanceOf(SshHostTrustCancelledError);
    controller.decline(secondId); await rejection;
  });
  it("shares only an identical key challenge while keeping cancellation local to each operation", async () => {
    const controller = new SshHostTrustController();
    const first = controller.request(key(), { operationKey: "test:a" }), rejected = expect(first).rejects.toMatchObject({ code: "cancelled" });
    const second = controller.request(key(), { operationKey: "session:b" });
    const id = controller.getSnapshot()!.id;
    controller.cancel("test:a"); await rejected;
    expect(controller.getSnapshot()?.id).toBe(id);
    controller.confirm(id); await second;
    expect(controller.getSnapshot()).toBeUndefined();
  });
  it("does not approve a different key for the same host and advances after abort", async () => {
    const controller = new SshHostTrustController(), abort = new AbortController();
    const first = controller.request(key(), { signal: abort.signal }), rejected = expect(first).rejects.toMatchObject({ code: "cancelled" });
    const next = controller.request(key("ssh.example", "SHA256:different"));
    abort.abort(); await rejected;
    expect(controller.getSnapshot()?.details.fingerprint).toBe("SHA256:different");
    controller.confirm(controller.getSnapshot()!.id); await next;
  });
  it("rejects every pending operation on shutdown and never leaves a dialog behind", async () => {
    const controller = new SshHostTrustController();
    const pending = [controller.request(key()), controller.request(key("b.example")), controller.request(key("c.example"))];
    const assertions = pending.map(promise => expect(promise).rejects.toMatchObject({ code: "cancelled" }));
    controller.cancel(); await Promise.all(assertions);
    expect(controller.getSnapshot()).toBeUndefined();
    const abort = new AbortController(); abort.abort();
    await expect(controller.request(key(), { signal: abort.signal })).rejects.toMatchObject({ code: "cancelled" });
    expect(controller.getSnapshot()).toBeUndefined();
  });
});
