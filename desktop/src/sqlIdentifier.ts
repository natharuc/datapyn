/** Quoted SQL identifiers may contain spaces and dots. */
export function identifierAtCursor(line:string,column:number):string|undefined {
  const pattern=/(?:\[(?:[^\]]|\]\])+\]|"(?:[^"]|"")+"|`(?:[^`]|``)+`|[\p{L}\p{N}_$#]+)(?:\s*\.\s*(?:\[(?:[^\]]|\]\])+\]|"(?:[^"]|"")+"|`(?:[^`]|``)+`|[\p{L}\p{N}_$#]+))*/gu;
  for(const match of line.matchAll(pattern))if(column-1 >= match.index && column-1 <= match.index+match[0].length)return match[0];
}
