window.PD = window.PD || {};

function getNested(obj, path) {
  return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

PD.bindWidget = function (elementId, eventName) {
  if (!PD.SSE) return;
  PD.SSE.on(eventName, (evt) => {
    let payload = {};
    try { payload = JSON.parse(evt.data); } catch { return; }
    const root = document.getElementById(elementId);
    if (!root) return;
    root.querySelectorAll('[data-field]').forEach((el) => {
      const key = el.getAttribute('data-field');
      const v = getNested(payload, key);
      if (v !== undefined && v !== null) el.textContent = String(v);
      if (key === 'status' && el.classList.contains('badge') && v) {
        Array.from(el.classList).forEach((c) => { if (c.startsWith('badge-')) el.classList.remove(c); });
        el.classList.add('badge-' + v);
      }
    });
    root.querySelectorAll('.pd-state-driven').forEach((el) => {
      const key = el.getAttribute('data-state-from');
      if (!key) return;
      const v = getNested(payload, key);
      if (v === undefined || v === null) return;
      Array.from(el.classList).forEach((c) => { if (c.startsWith('pd-state-') && c !== 'pd-state-driven') el.classList.remove(c); });
      el.classList.add('pd-state-' + v);
    });
  });
};

PD.gridInit = function () {
  const el = document.querySelector('.pd-grid');
  if (!el || typeof GridStack === 'undefined') return null;
  const grid = GridStack.init({
    column: 12,
    cellHeight: 80,
    margin: 8,
    columnOpts: {
      breakpointForWindow: true,
      breakpoints: [{ w: 768, c: 1 }],
    },
  }, el);
  const layoutKey = window.matchMedia('(max-width: 768px)').matches ? 'mobile' : 'desktop';
  const storeKey = 'pd-layout-' + layoutKey;
  const saved = localStorage.getItem(storeKey);
  if (saved) {
    try {
      grid.batchUpdate();
      grid.load(JSON.parse(saved), false);
      grid.commit();
    } catch (e) { console.warn('[PD.grid] bad saved layout', e); }
  }
  el.classList.add('pd-grid-ready');
  grid.on('change', () => {
    try { localStorage.setItem(storeKey, JSON.stringify(grid.save(false))); } catch {}
  });
  grid.enableMove(false); grid.enableResize(false);
  const editBtn = document.getElementById('pd-grid-edit');
  if (editBtn) {
    let editing = false;
    editBtn.addEventListener('click', () => {
      editing = !editing;
      grid.enableMove(editing); grid.enableResize(editing);
      editBtn.textContent = editing ? 'Done' : 'Edit layout';
      el.classList.toggle('pd-grid-editing', editing);
    });
  }
  return grid;
};

document.addEventListener('DOMContentLoaded', () => { PD.gridInit(); });
