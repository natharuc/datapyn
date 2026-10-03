import { useEffect, useState, type RefObject } from "react";
import { observeElementDocument } from "./documentWindows";

/** Keep component state; recreate only document-bound widgets after a portal is adopted. */
export function useOwnerDocumentRevision(ref: RefObject<HTMLElement>): number {
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const element = ref.current; if (!element) return;
    return observeElementDocument(element, () => setRevision(value => value + 1));
  }, [ref]);
  return revision;
}
