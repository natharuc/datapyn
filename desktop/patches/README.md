# Glide native pop-out support

`@glideapps/glide-data-grid` is intentionally pinned to **6.0.3**. The adjacent
unified patch is applied by `node scripts/apply-glide-patch.mjs` on every `npm ci`
/ install. The applicator verifies the package version and SHA-256 of the patch,
each pristine file and each generated file. It rejects unexpected content before
writing any file and is idempotent. Digests come from the official 6.0.3 registry
tarball and the reviewed patch. No additional patch-tool dependency is installed.
It adapts the ESM entry consumed by Vite; the unmodified CommonJS entry is not
used by this application.

Upstream 6.0.3 binds mouse/touch, clipboard, overlays and some rendering helpers
to the window that imports the package. Dockview adopts the grid into another
document, so those listeners and realm-dependent `instanceof MouseEvent` checks
can no longer handle native pop-out interactions.

The patch adds an optional `ownerDocument` prop and a per-grid React context. It
uses that document for focus guards, clipboard, rendering buffers, font readiness,
scrolling, event listeners and overlay portals. Mouse/pointer detection is based
on event coordinates and the absence of TouchEvent touch lists. Resize and overlay
observers use the host window. Disposal cancels pending hover/damage animations.
There is no change to global browser objects.

`ResultGrid` observes document adoption and recreates only `DataEditor`; its
filters, sorting, selection, formats, pagination cache and pending RPC generation
remain in the parent component. A grid initially rendered into a pop-out also waits
for its DOM ref before creating the widget, avoiding listeners in the main realm.

Regression coverage: `src/glideOwnerDocument.test.ts` exercises foreign-realm mouse
events, child document focus/listeners, overlay placement, child clipboard constructors
and animation cleanup. `src/glidePatch.test.ts` verifies clean application,
idempotency, version/content/digest rejection without partial writes.
`src/documentWindows.test.ts` verifies adoption notifications
and cleanup. A clean `npm ci` must apply the patch before build/test; upgrading Glide
requires re-evaluating these assumptions and regenerating the patch.

The pure named-color parser and static browser-family detection remain shared:
DataPyn supplies resolved theme colors, and both windows run on the same browser
engine/platform. They do not own interaction listeners or focus state.
