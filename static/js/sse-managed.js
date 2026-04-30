// PD.SSE: a parallel EventSource to /events for direct widget JS handlers
// (PD.bindWidget). HTMX's own sse-ext keeps its own EventSource alive
// independently via the `sse-connect` attribute; we don't manage that here.
// On visibilitychange we close/reopen our parallel source to save power on
// hidden tabs and re-emit a `pd-sse-reconnected` event so widgets can
// re-fetch initial state if needed.
window.PD = window.PD || {};

PD.SSE = (() => {
  let es = null;
  const listeners = {};

  function open() {
    if (es) return;
    es = new EventSource('/events');
    es.addEventListener('error', () => console.debug('[PD.SSE] error event'));
    for (const [evt, fns] of Object.entries(listeners)) {
      for (const fn of fns) es.addEventListener(evt, fn);
    }
  }

  function close() {
    if (es) { es.close(); es = null; }
  }

  function on(evt, fn) {
    (listeners[evt] = listeners[evt] || []).push(fn);
    if (es) es.addEventListener(evt, fn);
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      close();
    } else {
      open();
      document.dispatchEvent(new CustomEvent('pd-sse-reconnected'));
    }
  });

  document.addEventListener('DOMContentLoaded', open);

  return { open, close, on };
})();
