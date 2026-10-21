import {describe, expect, it} from "vitest";
import {SqlConfirmationQueue} from "./sqlConfirmation";
import type {SqlExecutionReview} from "./sqlSafety";

const review = (session_id: string): SqlExecutionReview => ({session_id, confirmation_required: true,
  risks: [{statement: 1, operation: "DELETE", preview: "DELETE FROM sample", unfiltered: true}]});

describe("explicit SQL confirmation queue", () => {
  it("denies when no dialog is mounted", async () => {
    const queue = new SqlConfirmationQueue();
    expect(await queue.request(review("a"), new AbortController().signal)).toBe(false);
  });
  it("requires a separate response for each tab and rejects stale responses", async () => {
    const queue = new SqlConfirmationQueue(), unsubscribe = queue.subscribe(() => {});
    const first = queue.request(review("a"), new AbortController().signal);
    const id = queue.getSnapshot()!.id;
    const second = queue.request(review("b"), new AbortController().signal);
    queue.respond(id, true);
    expect(await first).toBe(true);
    expect(queue.getSnapshot()!.review.session_id).toBe("b");
    queue.respond(id, true);
    expect(queue.getSnapshot()!.review.session_id).toBe("b");
    queue.respond(queue.getSnapshot()!.id, false);
    expect(await second).toBe(false);
    unsubscribe();
  });
  it("denies on cancellation or UI disposal", async () => {
    const queue = new SqlConfirmationQueue(), unsubscribe = queue.subscribe(() => {}), abort = new AbortController();
    const first = queue.request(review("a"), abort.signal);
    const second = queue.request(review("b"), new AbortController().signal);
    abort.abort();
    expect(await first).toBe(false);
    expect(queue.getSnapshot()!.review.session_id).toBe("b");
    unsubscribe();
    expect(await second).toBe(false);
    expect(queue.getSnapshot()).toBeUndefined();
  });
});
