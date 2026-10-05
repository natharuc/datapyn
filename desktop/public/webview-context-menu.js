(() => {
  const installed = Symbol.for("datapyn.browserContextMenuGuard");
  if (window[installed]) return;
  // Cancel only the browser action. Application and editor menus still receive
  // right-click and keyboard context-menu events, including stopped bubbles.
  window.addEventListener("contextmenu", event => event.preventDefault(), true);
  window[installed] = true;
})();
