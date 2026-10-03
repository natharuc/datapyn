export function importedDataCode(path: string, variableName: string, options: {delimiter?: string | null; encoding?: string; decimal?: string} = {}): string {
  const extension = path.split(".").at(-1)?.toLowerCase();
  const literal = JSON.stringify(path);
  let reader: string;
  if (extension === "parquet") reader = `pd.read_parquet(${literal})`;
  else if (extension === "json") reader = `pd.read_json(${literal})`;
  else if (extension === "xls" || extension === "xlsx") reader = `pd.read_excel(${literal})`;
  else {
    const delimiter = options.delimiter === undefined ? extension === "tsv" ? "\t" : ";" : options.delimiter;
    const separator = delimiter === null ? 'sep=None, engine="python"' : `sep=${JSON.stringify(delimiter)}`;
    reader = `pd.read_csv(${literal}, ${separator}, encoding=${JSON.stringify(options.encoding ?? "utf-8-sig")}, decimal=${JSON.stringify(options.decimal ?? ".")})`;
  }
  return `${variableName} = ${reader}\n${variableName}`;
}
