import type { SessionDocument } from "./workspace";

export interface OutputReveal { panel: "results" | "output"; sessionId: string; rich: boolean }

/** Observe every store transition, including background sessions, without replaying saved output. */
export class OutputRevealTracker {
  private previous = new Map<string, SessionDocument>();
  private resultsExecution = new Map<string, string>();
  private richExecution = new Map<string, string>();

  clear() { this.previous.clear(); this.resultsExecution.clear(); this.richExecution.clear(); }

  observe(sessions: readonly SessionDocument[], activeId: string): OutputReveal | undefined {
    let reveal: OutputReveal | undefined;
    const live = new Set(sessions.map(session => session.id));
    for (const id of this.previous.keys()) if (!live.has(id)) {
      this.previous.delete(id); this.resultsExecution.delete(id); this.richExecution.delete(id);
    }
    for (const session of sessions) {
      const before = this.previous.get(session.id);
      this.previous.set(session.id, session);
      if (!before || before === session) continue;
      const execution = session.currentExecutionId;
      let rich = false, results = false, failed = false;
      if ((session.richOutputs?.length || session.images.length) && (session.richOutputs !== before.richOutputs || session.images !== before.images)) {
        const previousArtifacts = new Set(before.richOutputs?.map(output => output.artifact_id).filter(Boolean)), previousOutputs = new Set(before.richOutputs);
        const previousImages = new Map<string, Set<string>>();
        for (const image of before.images) {
          let data = previousImages.get(image.mime); if (!data) { data = new Set(); previousImages.set(image.mime, data); } data.add(image.data);
        }
        const newIdentity = session.richOutputs?.some(output => output.artifact_id ? !previousArtifacts.has(output.artifact_id) : !previousOutputs.has(output)) ||
          session.images.some(image => !previousImages.get(image.mime)?.has(image.data));
        rich = Boolean(newIdentity || execution && session.resultRevision > before.resultRevision && this.richExecution.get(session.id) !== execution);
      }
      if (session.results.length && session.results !== before.results) {
        const previousIds = new Set(before.results.map(result => result.result_id));
        results = session.results.some(result => !previousIds.has(result.result_id)) ||
          Boolean(execution && session.resultRevision > before.resultRevision && this.resultsExecution.get(session.id) !== execution);
      }
      if (session.blocks !== before.blocks && session.blocks.some(block => block.status === "failed")) {
        const previousBlocks = new Map(before.blocks.map(block => [block.id, block]));
        failed = session.blocks.some(block => block.status === "failed" && (previousBlocks.get(block.id)?.status !== "failed" || previousBlocks.get(block.id)?.error !== block.error));
      }
      if (execution && results) this.resultsExecution.set(session.id, execution);
      if (execution && rich) this.richExecution.set(session.id, execution);
      if (session.id === activeId) {
        if (rich || results) reveal = { panel: "results", sessionId: session.id, rich };
        else if (failed) reveal = { panel: "output", sessionId: session.id, rich: false };
      }
    }
    return reveal;
  }
}
