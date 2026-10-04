import type { CopyOptions, CopyTable } from "./gridClipboard";
import type { ColumnFormats } from "./gridFormat";
import { formatCell } from "./gridFormat";
import { MAX_CLIPBOARD_BYTES, MAX_COPY_CELLS, utf8Bytes } from "./clipboardLimits";

export interface ClipboardFormatOptions extends CopyOptions { format: "excel" | "plain" | "json" }
export interface FormattedClipboard { plain: string; html?: string; rowCount: number }

/** Validate the shape/count before building output strings. No expansion of selected indices. */
export function validateCopyTable(table: CopyTable): void {
  if (!Array.isArray(table.columns) || !Array.isArray(table.rows)) throw new Error("Seleção inválida.");
  if (table.columns.length * table.rows.length > MAX_COPY_CELLS) throw new Error("Use a exportação para seleções com mais de 200 mil células.");
  let cells = 0;
  for (const row of table.rows) {
    if (!Array.isArray(row)) throw new Error("Seleção inválida.");
    cells += row.length;
    if (cells > MAX_COPY_CELLS) throw new Error("Use a exportação para seleções com mais de 200 mil células.");
  }
}

class BoundedWriter {
  private bytes = 0;
  private tailHighSurrogate = false;
  private chunks: string[] = [];
  private parts: string[] = [];
  private length = 0;
  write(value: string) {
    if (!value) return;
    const first = value.charCodeAt(0), paired = this.tailHighSurrogate && first >= 0xdc00 && first <= 0xdfff;
    this.bytes += utf8Bytes(value, MAX_CLIPBOARD_BYTES - this.bytes + (paired ? 2 : 0)) - (paired ? 2 : 0);
    const last = value.charCodeAt(value.length - 1);
    this.tailHighSurrogate = last >= 0xd800 && last <= 0xdbff;
    this.parts.push(value); this.length += value.length;
    if (this.length >= 32_768) this.flush();
  }
  private flush() { if (this.parts.length) this.chunks.push(this.parts.join("")); this.parts = []; this.length = 0; }
  finish() { this.flush(); return this.chunks.join(""); }
}

/** Escaping is done in bounded chunks; a huge cell cannot allocate an unbounded escaped copy. */
function transformed(writer: BoundedWriter, value: string, transform: (chunk: string) => string) {
  for (let first = 0; first < value.length;) {
    let end = Math.min(first + 4096, value.length);
    const code = value.charCodeAt(end - 1), next = value.charCodeAt(end);
    if (end < value.length && code >= 0xd800 && code <= 0xdbff && next >= 0xdc00 && next <= 0xdfff) end--;
    writer.write(transform(value.slice(first, end))); first = end;
  }
}
function html(writer: BoundedWriter, value: string) {
  transformed(writer,value,chunk=>chunk.replace(/[&<>"']/g,character=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[character]!));
}
function csv(writer: BoundedWriter, value: string, separator: string) {
  if (value.includes(separator) || /[\r\n"]/.test(value)) {
    writer.write('"'); transformed(writer,value,chunk=>chunk.replace(/"/g,'""')); writer.write('"');
  } else writer.write(value);
}
function jsonString(writer: BoundedWriter, value: string) {
  writer.write('"'); transformed(writer,value,chunk=>JSON.stringify(chunk).slice(1,-1)); writer.write('"');
}
function jsonValue(writer: BoundedWriter, value: CopyTable["rows"][number][number]) {
  if(typeof value === "string") jsonString(writer,value);
  else writer.write(JSON.stringify(value ?? null));
}
function text(value: CopyTable["rows"][number][number], name: string, options: CopyOptions) {
  if(value === undefined) return "";
  return options.raw ? value === null ? options.nullDisplay ?? "" : String(value) : formatCell(value,options.formats?.[name],options.nullDisplay ?? "");
}

/** JSON.stringify sorts canonical integer object keys ahead of the other keys. */
function jsonColumnOrder(columns: string[]) {
  const integer=(name:string)=>/^(?:0|[1-9]\d*)$/.test(name)&&Number(name)<4_294_967_295;
  return columns.map((name,index)=>({name,index})).sort((a,b)=>integer(a.name)?integer(b.name)?Number(a.name)-Number(b.name):-1:integer(b.name)?1:0);
}
/** Retains bounded output only. Incoming row batches can be released after each worker message. */
export class ClipboardFormatter {
  private plain=new BoundedWriter();
  private rich?:BoundedWriter;
  private rowCount=0;
  private cells=0;
  private started=false;
  private closed=false;
  private readonly settings:CopyOptions;
  private readonly duplicate:boolean;
  private readonly jsonColumns:Array<{name:string;index:number}>;
  constructor(private readonly columns:string[],private readonly options:ClipboardFormatOptions,formats?:ColumnFormats){
    if(!["excel","plain","json"].includes(options.format))throw new Error("Formato de cópia inválido.");
    if(columns.length>MAX_COPY_CELLS)throw new Error("Use a exportação para seleções com mais de 200 mil células.");
    this.settings={...options,formats:formats??options.formats};
    this.duplicate=new Set(columns).size!==columns.length;this.jsonColumns=options.format==="json"&&!this.duplicate?jsonColumnOrder(columns):[];
    if(options.format==="json"){
      if(this.duplicate){this.plain.write('{\n  "columns": [');columns.forEach((name,index)=>{this.plain.write(index?",\n    ":"\n    ");jsonString(this.plain,name);});this.plain.write('\n  ],\n  "rows": [');}
      else this.plain.write("[");
    }else{
      if(options.headers){const separator=options.separator??"\t";columns.forEach((name,index)=>{if(index)this.plain.write(separator);csv(this.plain,name,separator);});this.started=true;}
      if(options.format==="excel"){
        this.rich=new BoundedWriter();this.rich.write('<!doctype html><html><head><meta charset="utf-8"></head><body><table>');
        if(options.headers){this.rich.write("<thead><tr>");for(const name of columns){this.rich.write("<th>");html(this.rich,name);this.rich.write("</th>");}this.rich.write("</tr></thead>");}
        this.rich.write("<tbody>");
      }
    }
  }
  addRows(rows:CopyTable["rows"]){
    if(this.closed)throw new Error("Resposta de resultados inválida.");
    for(const row of rows){
      if(!Array.isArray(row))throw new Error("Seleção inválida.");
      this.cells+=row.length;
      if(this.cells>MAX_COPY_CELLS||this.columns.length*(this.rowCount+1)>MAX_COPY_CELLS)throw new Error("Use a exportação para seleções com mais de 200 mil células.");
      if(this.options.format==="json"){
        if(this.duplicate){this.plain.write(this.rowCount?",\n    [":"\n    [");for(let cell=0;cell<row.length;cell++){this.plain.write(cell?",\n      ":"\n      ");jsonValue(this.plain,row[cell]);}this.plain.write(row.length?"\n    ]":"]");}
        else{this.plain.write(this.rowCount?",\n  {":"\n  {");this.jsonColumns.forEach(({name,index:cell},column)=>{this.plain.write(column?",\n    ":"\n    ");jsonString(this.plain,name);this.plain.write(": ");jsonValue(this.plain,row[cell]);});this.plain.write(this.jsonColumns.length?"\n  }":"}");}
      }else{
        if(this.started)this.plain.write("\r\n");this.started=true;this.rich?.write("<tr>");
        const separator=this.options.separator??"\t";
        for(let index=0;index<row.length;index++){
          const value=text(row[index],this.columns[index],this.settings);if(index)this.plain.write(separator);csv(this.plain,value,separator);
          if(this.rich){this.rich.write('<td style=\'mso-number-format:"\\@";white-space:pre-wrap\'>');html(this.rich,value);this.rich.write("</td>");}
        }
        this.rich?.write("</tr>");
      }
      this.rowCount++;
    }
  }
  finish():FormattedClipboard{
    if(this.closed)throw new Error("Resposta de resultados inválida.");this.closed=true;
    if(this.options.format==="json")this.plain.write(this.duplicate?this.rowCount?"\n  ]\n}":"]\n}":this.rowCount?"\n]":"]");
    this.rich?.write("</tbody></table></body></html>");
    return{plain:this.plain.finish(),...(this.rich?{html:this.rich.finish()}:{}),rowCount:this.rowCount};
  }
}

/** Called in the dedicated worker. Never fall back to this CPU work on the UI thread. */
export function formatClipboardPayload(table: CopyTable, options: ClipboardFormatOptions, formats?: ColumnFormats): FormattedClipboard {
  validateCopyTable(table);
  const formatter=new ClipboardFormatter(table.columns,options,formats);formatter.addRows(table.rows);return formatter.finish();
}
