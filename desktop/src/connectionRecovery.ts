import type {ConnectionRecoveryState} from "./runtime";
import type {Block,SessionDocument} from "./workspace";
import {completionConnectionScope,inheritsSessionScope} from "./sessionCompletion";

const equal=(left:string|null|undefined,right:string|null|undefined)=>(left??"")===(right??"");
/** A recovery belongs to a physical SQL lane, never to whichever editor has focus. */
export function recoveryMatches(session:SessionDocument,block:Block|undefined,recovery:ConnectionRecoveryState,automaticTransactions=true):boolean {
  if(recovery.session_id!==session.id || recovery.block_id!==block?.id)return false;
  const scope=block?completionConnectionScope(session,block):{connectionId:session.savedConnectionId,database:session.database,schema:session.schema};
  return recovery.automatic_transactions===(automaticTransactions && block?.disable_automatic_transactions!==true)
    && (recovery.scope_inherited===undefined || recovery.scope_inherited===(block?inheritsSessionScope(block):false))
    && equal(recovery.requested_scope.connection_id,scope.connectionId)
    && equal(recovery.requested_scope.database,scope.database)
    && equal(recovery.requested_scope.schema,scope.schema);
}

export function activeConnectionRecovery(session:SessionDocument,block:Block|undefined,automaticTransactions=true):ConnectionRecoveryState|undefined {
  const recovery=block?.connectionRecovery??(!block?session.connectionRecovery:undefined);
  return recovery && recoveryMatches(session,block,recovery,automaticTransactions)?recovery:undefined;
}

export function applyConnectionRecovery(session:SessionDocument,recovery:ConnectionRecoveryState,automaticTransactions=true,expectedPreviousId?:string):SessionDocument {
  const block=recovery.block_id?session.blocks.find(item=>item.id===recovery.block_id):undefined;
  if(recovery.block_id && !block || !recoveryMatches(session,block,recovery,automaticTransactions))return session;
  const previous=block?block.connectionRecovery:session.connectionRecovery;
  // Terminal events/old RPC responses cannot replace a more recent recovery.
  if(recovery.phase!=="recovering" && previous && previous.recovery_id!==recovery.recovery_id && previous.recovery_id!==expectedPreviousId)return session;
  if(recovery.phase==="recovering" && previous?.recovery_id===recovery.recovery_id && previous.phase!=="recovering")return session;
  if(recovery.execution_id && recovery.execution_id!==session.currentExecutionId && previous?.recovery_id!==recovery.recovery_id)return session;
  // A successful replacement owns new transaction state. Never keep the lost
  // socket's "unknown" state after the backend has confirmed recovery.
  const recoveredState=recovery.phase==="ready"?{transactionState:recovery.transaction_state}:{};
  const next=block?{...session,blocks:session.blocks.map(item=>item.id===block.id?{...item,...recoveredState,connectionRecovery:recovery}:item)}:{...session,connectionRecovery:recovery};
  if(recovery.phase!=="ready" || !recovery.automatic_transactions || !recovery.affected_block_ids?.length)return next;
  // Equal public scopes can still own different physical sockets. Only the
  // backend affinity list can authorize refreshing a sibling's recovery state.
  const affected=new Set(recovery.affected_block_ids);
  return {...next,blocks:next.blocks.map(peer=>{
    const old=peer.connectionRecovery;
    if(peer.id===block?.id || !affected.has(peer.id) || !old || !["blocked","error"].includes(old.phase) || !old.automatic_transactions)return peer;
    if(!equal(old.requested_scope.connection_id,recovery.requested_scope.connection_id)||!equal(old.requested_scope.database,recovery.requested_scope.database)||!equal(old.requested_scope.schema,recovery.requested_scope.schema))return peer;
    const ready={...recovery,block_id:peer.id,scope_inherited:old.scope_inherited};
    return recoveryMatches(next,peer,ready,automaticTransactions)?{...peer,...recoveredState,connectionRecovery:ready}:peer;
  })};
}
