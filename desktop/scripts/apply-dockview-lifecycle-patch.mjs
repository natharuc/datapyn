const fail = message => { throw new Error(`Dockview popout-lifecycle patch: ${message}`); };

export const resizeBefore = `function onDidWindowResizeEnd(element, cb) {
\tlet resizeTimeout;
\treturn new CompositeDisposable(addDisposableListener(element, "resize", () => {
\t\tclearTimeout(resizeTimeout);
\t\tresizeTimeout = setTimeout(() => {
\t\t\tcb();
\t\t}, DEBOUCE_DELAY);
\t}));
}`;

export const resizeAfter = `function onDidWindowResizeEnd(element, cb) {
\tlet resizeTimeout;
\tlet disposed = false;
\treturn new CompositeDisposable(Disposable.from(() => {
\t\tdisposed = true;
\t\tclearTimeout(resizeTimeout);
\t\tresizeTimeout = void 0;
\t}), addDisposableListener(element, "resize", () => {
\t\tif (disposed) return;
\t\tclearTimeout(resizeTimeout);
\t\tresizeTimeout = setTimeout(() => {
\t\t\tresizeTimeout = void 0;
\t\t\tif (!disposed) cb();
\t\t}, DEBOUCE_DELAY);
\t}));
}`;

export const callbacksBefore = `\t\t\tpopoutWindowDisposable.addDisposables(_onDidWindowPositionChange, onDidWindowResizeEnd(_window.window, () => {
\t\t\t\tthis._onDidPopoutGroupSizeChange.fire({
\t\t\t\t\twidth: _window.window.innerWidth,
\t\t\t\t\theight: _window.window.innerHeight,
\t\t\t\t\tgroup: value.popoutGroup
\t\t\t\t});
\t\t\t}), _onDidWindowPositionChange.event(() => {
\t\t\t\tthis._onDidPopoutGroupPositionChange.fire({
\t\t\t\t\tscreenX: _window.window.screenX,
\t\t\t\t\tscreenY: _window.window.screenY,
\t\t\t\t\tgroup: value.popoutGroup
\t\t\t\t});
\t\t\t}), addDisposableListener(_window.window, "resize", () => {
\t\t\t\tpopoutGridview.layout(_window.window.innerWidth, _window.window.innerHeight);
\t\t\t}), overlayRenderContainer, Disposable.from(() => this.disposePopoutWindow({`;

export const callbacksAfter = `\t\t\tpopoutWindowDisposable.addDisposables(_onDidWindowPositionChange, onDidWindowResizeEnd(_window.window, () => {
\t\t\t\tconst view = _window.window;
\t\t\t\tif (!view || view.closed || popoutGridviewDisposed) return;
\t\t\t\tthis._onDidPopoutGroupSizeChange.fire({
\t\t\t\t\twidth: view.innerWidth,
\t\t\t\t\theight: view.innerHeight,
\t\t\t\t\tgroup: value.popoutGroup
\t\t\t\t});
\t\t\t}), _onDidWindowPositionChange.event(() => {
\t\t\t\tconst view = _window.window;
\t\t\t\tif (!view || view.closed || popoutGridviewDisposed) return;
\t\t\t\tthis._onDidPopoutGroupPositionChange.fire({
\t\t\t\t\tscreenX: view.screenX,
\t\t\t\t\tscreenY: view.screenY,
\t\t\t\t\tgroup: value.popoutGroup
\t\t\t\t});
\t\t\t}), addDisposableListener(_window.window, "resize", () => {
\t\t\t\tconst view = _window.window;
\t\t\t\tif (!view || view.closed || popoutGridviewDisposed) return;
\t\t\t\tpopoutGridview.layout(view.innerWidth, view.innerHeight);
\t\t\t}), overlayRenderContainer, Disposable.from(() => this.disposePopoutWindow({`;

export const lifecyclePatchDefinition = () => ({ resizeBefore, resizeAfter, callbacksBefore, callbacksAfter });

/** Exact replacements only; the outer installer validates whole-file digests before writing. */
export function transformDockviewLifecycle(source) {
  for (const [before, after] of [[resizeBefore, resizeAfter], [callbacksBefore, callbacksAfter]]) {
    if (source.split(before).length !== 2) fail("the exact upstream lifecycle hook must occur once");
    source = source.replace(before, after);
  }
  return source;
}

/** Used by fixtures to reconstruct the pinned pristine distribution without network access. */
export function reverseDockviewLifecycle(source) {
  for (const [before, after] of [[resizeBefore, resizeAfter], [callbacksBefore, callbacksAfter]]) {
    if (source.split(after).length !== 2) fail("the exact patched lifecycle hook must occur once");
    source = source.replace(after, before);
  }
  return source;
}
