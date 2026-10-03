import {describe,expect,it} from "vitest";
import {identifierAtCursor} from "./sqlIdentifier";
describe("Entidade no cursor SQL",()=>{
  it("mantém partes qualificadas e identificadores entre aspas",()=>{
    expect(identifierAtCursor("SELECT * FROM [db].[sales].[Order Details]",33)).toBe("[db].[sales].[Order Details]");
    expect(identifierAtCursor('SELECT * FROM "schema.dot"."table name"',30)).toBe('"schema.dot"."table name"');
    expect(identifierAtCursor("SELECT * FROM public.orders;",24)).toBe("public.orders");
    expect(identifierAtCursor("  ;",2)).toBeUndefined();
  });
});
