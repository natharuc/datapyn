import type { SavedConnection } from "./connections";
import type { SessionDocument } from "./workspace";

/** Match the legacy focused-block precedence without borrowing another connection's dialect. */
export function exportContext(session: SessionDocument, catalog: SavedConnection[]) {
  const block = session.blocks.find(item => item.id === session.focusedBlockId);
  const connectionId = block?.connection_id || session.savedConnectionId;
  const saved = catalog.find(item => item.id === connectionId);
  const config = saved?.config ?? (!block?.connection_id || block.connection_id === session.savedConnectionId ? session.connection : undefined);
  const inherits = !block?.connection_id || block.connection_id === session.savedConnectionId;
  return {
    connectionId,
    connectionType: config?.db_type,
    database: block?.database_name || (inherits ? session.database : undefined) || config?.database,
    schema: block?.schema || (inherits ? session.schema : undefined) || config?.schema,
  };
}
