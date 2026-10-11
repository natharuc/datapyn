export interface SshHostKeyDetails {
  host: string;
  port: number;
  key_type: string;
  public_key: string;
  fingerprint: string;
}

export interface SshHostTrustRequest {
  id: number;
  details: Readonly<SshHostKeyDetails>;
}

export class SshHostTrustCancelledError extends Error {
  readonly code = "cancelled";
  constructor() { super("Confirmação do servidor SSH cancelada."); }
}

interface Waiter {
  operationKey?: string;
  resolve: () => void;
  reject: (error: SshHostTrustCancelledError) => void;
  detach?: () => void;
}
interface PendingTrust extends SshHostTrustRequest { waiters: Set<Waiter> }

/** Only public host keys enter this queue. Credentials stay in the connection request. */
export class SshHostTrustController {
  private queue: PendingTrust[] = [];
  private snapshot?: SshHostTrustRequest;
  private listeners = new Set<() => void>();
  private nextId = 0;
  getSnapshot = () => this.snapshot;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private update() {
    const first = this.queue[0];
    if (this.snapshot?.id === first?.id) return;
    this.snapshot = first ? { id: first.id, details: first.details } : undefined;
    this.listeners.forEach(listener => listener());
  }
  request(details: SshHostKeyDetails, options: { operationKey?: string; signal?: AbortSignal } = {}): Promise<void> {
    if (options.signal?.aborted) return Promise.reject(new SshHostTrustCancelledError());
    let entry = this.queue.find(item => item.details.host === details.host && item.details.port === details.port
      && item.details.public_key === details.public_key && item.details.fingerprint === details.fingerprint && item.details.key_type === details.key_type);
    if (!entry) { entry = { id: ++this.nextId, details: Object.freeze({ ...details }), waiters: new Set() }; this.queue.push(entry); }
    const pending = entry;
    const promise = new Promise<void>((resolve, reject) => {
      const waiter: Waiter = { operationKey: options.operationKey, resolve, reject };
      const abort = () => { this.remove(pending, waiter); waiter.reject(new SshHostTrustCancelledError()); };
      if (options.signal) {
        options.signal.addEventListener("abort", abort, { once: true });
        waiter.detach = () => options.signal?.removeEventListener("abort", abort);
      }
      pending.waiters.add(waiter);
    });
    this.update();
    return promise;
  }
  private remove(entry: PendingTrust, waiter: Waiter) {
    waiter.detach?.(); entry.waiters.delete(waiter);
    if (!entry.waiters.size) this.queue = this.queue.filter(item => item !== entry);
    this.update();
  }
  confirm(id: number) { this.settle(id, true); }
  decline(id: number) { this.settle(id, false); }
  private settle(id: number, accepted: boolean) {
    const entry = this.queue[0];
    if (!entry || entry.id !== id) return;
    this.queue.shift(); this.update();
    for (const waiter of entry.waiters) {
      waiter.detach?.();
      if (accepted) waiter.resolve(); else waiter.reject(new SshHostTrustCancelledError());
    }
    entry.waiters.clear();
  }
  cancel(operationKey?: string) {
    for (const entry of [...this.queue]) for (const waiter of [...entry.waiters]) {
      if (operationKey !== undefined && waiter.operationKey !== operationKey) continue;
      this.remove(entry, waiter); waiter.reject(new SshHostTrustCancelledError());
    }
  }
}

export const sshHostTrust = new SshHostTrustController();
export const requestSshHostTrust = (details: SshHostKeyDetails, options?: { operationKey?: string; signal?: AbortSignal }) => sshHostTrust.request(details, options);
export const cancelSshHostTrust = (operationKey?: string) => sshHostTrust.cancel(operationKey);
