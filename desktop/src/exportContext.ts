import type { SavedConnection } from "./connections";
import type { SessionDocument } from "./workspace";
import {completionConnectionScope} from "./sessionCompletion";

/** Match the legacy focused-block precedence without borrowing another connection's dialect. */
export function exportContext(session: SessionDocument, catalog: SavedConnection[]) {
  const block = session.blocks.find(item => item.id === session.focusedBlockId);
  const connectionId = block?.connection_id || session.savedConnectionId;
  const saved = catalog.find(item => item.id === connectionId);
  const config = saved?.config ?? (!block?.connection_id || block.connection_id === session.savedConnectionId ? session.connection : undefined);
  const scope=block ? completionConnectionScope(session,block,config) : {connectionId,database:session.database ?? config?.database,schema:session.schema ?? config?.schema};
  return {
    connectionId,
    connectionType: config?.db_type,
    database:scope.database,
    schema:scope.schema,
  };
}
