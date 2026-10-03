export function editCodeLines(code: string, start: unknown, end: unknown, content: string, operation: string = "replace"): string {
  const lines = code.split("\n");
  if (typeof start !== "number" || !Number.isInteger(start) || start < 1 || start > lines.length + (operation === "insert" ? 1 : 0)) throw new Error("start_line fora do intervalo do bloco (índice começa em 1).");
  const last = end == null ? start : end;
  if (typeof last !== "number" || !Number.isInteger(last) || last < start || (operation !== "insert" && last > lines.length)) throw new Error("end_line fora do intervalo do bloco.");
  const added = content ? content.split("\n") : [];
  if (operation === "replace") lines.splice(start - 1, last - start + 1, ...added);
  else if (operation === "insert") lines.splice(start - 1, 0, ...added);
  else if (operation === "delete") lines.splice(start - 1, last - start + 1);
  else throw new Error("line_operation deve ser replace, insert ou delete.");
  return lines.join("\n");
}
export function validateWholeBlockReplace(previous: string, replacement: string, force: unknown) {
  const oldLines = previous.split("\n").length, newLines = replacement.split("\n").length;
  if (!force && oldLines >= 60 && newLines < oldLines * 0.5) throw new Error(`O bloco tem ${oldLines} linhas e o conteúdo novo tem ${newLines}. Use operation=lines para edição parcial ou force=true para substituir todo o bloco.`);
}
