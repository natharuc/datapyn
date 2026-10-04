export const MAX_COPY_CELLS = 200_000;
export const MAX_CLIPBOARD_BYTES = 16 * 1024 * 1024;
export const CLIPBOARD_SIZE_ERROR = "A cópia excede 16 MB. Reduza a seleção ou use a exportação.";

/** Count encoded bytes without allocating a second complete Uint8Array. Stops at the budget. */
export function utf8Bytes(value: string, budget = MAX_CLIPBOARD_BYTES): number {
  let bytes = 0;
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code < 0x80) bytes++;
    else if (code < 0x800) bytes += 2;
    else if (code >= 0xd800 && code <= 0xdbff && index + 1 < value.length && value.charCodeAt(index + 1) >= 0xdc00 && value.charCodeAt(index + 1) <= 0xdfff) { bytes += 4; index++; }
    else bytes += 3;
    if (bytes > budget) throw new Error(CLIPBOARD_SIZE_ERROR);
  }
  return bytes;
}
