import type { ExecutionFinished } from "./runtime";
import { completionConnectionScope, inheritsSessionScope } from "./sessionCompletion";
import type { ScopePreparation } from "./ScopePreparation";
import type { SessionDocument } from "./workspace";

/** Runtime listeners may precede the workspace reducer; reread after event dispatch. */
export async function prepareExecutionContextAfterEvent(payload: ExecutionFinished,
  readSession: (sessionId: string) => SessionDocument | undefined, preparation: ScopePreparation): Promise<void> {
  await Promise.resolve();
  const change=payload.context_change,current=readSession(payload.session_id),block=current?.blocks.find(item=>item.id===payload.block_id);
  if(!change || !current || !block || block.language!=="sql")return;
  const scope=completionConnectionScope(current,block);
  // The selected scope owns metadata, even when another execution or a manual
  // selection has overtaken the event before its refresh can be dispatched.
  if(scope.connectionId!==(change.requested_scope.connection_id ?? undefined)
    || scope.database!==(change.current.database ?? undefined) || scope.schema!==(change.current.schema ?? undefined))return;
  await preparation.request({sessionId:current.id,blockId:block.id,scopeInherited:inheritsSessionScope(block),...scope,dbType:change.current.db_type},block.code,true);
}
