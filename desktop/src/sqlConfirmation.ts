import type {SqlExecutionReview} from "./sqlSafety";

interface PendingConfirmation {
  id: number;
  review: SqlExecutionReview;
  finish: (accepted: boolean) => void;
}

/** Confirmations from different tabs remain separate; closing the UI denies all. */
export class SqlConfirmationQueue {
  private items: PendingConfirmation[] = [];
  private listeners = new Set<() => void>();
  private sequence = 0;
  getSnapshot = () => this.items[0];
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); if (!this.listeners.size) this.cancelAll(); };
  };
  private emit() { this.listeners.forEach(listener => listener()); }
  request = (review: SqlExecutionReview, signal: AbortSignal): Promise<boolean> => {
    if (signal.aborted || !this.listeners.size) return Promise.resolve(false);
    return new Promise(resolve => {
      const id = ++this.sequence;
      let settled = false;
      const finish = (accepted: boolean) => {
        if (settled) return;
        settled = true;
        signal.removeEventListener("abort", abort);
        this.items = this.items.filter(item => item.id !== id);
        resolve(accepted === true && !signal.aborted);
        this.emit();
      };
      const abort = () => finish(false);
      signal.addEventListener("abort", abort, {once: true});
      this.items.push({id, review, finish});
      this.emit();
    });
  };
  respond = (id: number, accepted: boolean) => {
    const current = this.items[0];
    if (current?.id === id) current.finish(accepted);
  };
  cancelAll = () => { [...this.items].forEach(item => item.finish(false)); };
}

export const sqlConfirmations = new SqlConfirmationQueue();
