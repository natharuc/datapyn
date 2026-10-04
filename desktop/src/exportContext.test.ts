import { describe, expect, it } from "vitest";
import { exportContext } from "./exportContext";
import { newSession, type ConnectionConfig } from "./workspace";
import type { SavedConnection } from "./connections";

const config: ConnectionConfig = {db_type:"sqlserver",host:"local",port:1433,database:"source",username:"",schema:"dbo"};
const saved: SavedConnection = {id:"destination",name:"Destination",group_id:null,color:"",favorite:false,order:0,has_password:false,config:{...config,db_type:"postgresql",database:"target",schema:"public"}};
describe("export connection context", () => {
  it("uses the focused block's connection instead of the session's dialect and database", () => {
    const session = newSession();
    session.connection=config; session.savedConnectionId="source"; session.database="source_override"; session.schema="source_schema";
    session.blocks[0].connection_id="destination";
    expect(exportContext(session,[saved])).toEqual({connectionId:"destination",connectionType:"postgresql",database:"target",schema:"public"});
    session.blocks[0].database_name="block_db"; session.blocks[0].schema="block_schema";
    expect(exportContext(session,[saved])).toMatchObject({database:"block_db",schema:"block_schema"});
  });
  it("inherits session context and never guesses the dialect of a missing block connection", () => {
    const session = newSession(); session.connection=config; session.savedConnectionId="source"; session.database="override";
    expect(exportContext(session,[])).toMatchObject({connectionType:"sqlserver",database:"override",schema:undefined});
    session.blocks[0].connection_id="removed";
    expect(exportContext(session,[])).toEqual({connectionId:"removed",connectionType:undefined,database:undefined,schema:undefined});
  });
});


it("does not export to the schema of the previous database after a database-only selection",()=>{
  const session=newSession();session.savedConnectionId=saved.id;session.connection=saved.config;session.database="target";session.schema="private";
  session.blocks[0].database_name="selected_database";
  expect(exportContext(session,[saved])).toMatchObject({database:"selected_database",schema:undefined});
  session.blocks[0].schema="chosen_schema";
  expect(exportContext(session,[saved])).toMatchObject({database:"selected_database",schema:"chosen_schema"});
});
