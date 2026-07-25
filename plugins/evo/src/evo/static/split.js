// split.js — universal drag-to-resize for panels, ported from stablyai/orca's
// split-tree clamping model (ratios clamped 0.15–0.85 of the viewport) with
// localStorage persistence per panel. Every .ascii-panel gets a bottom drag
// edge; works for panels rendered later too (MutationObserver).
(() => {
  'use strict';

  const MIN_PX = 120;
  const MAX_RATIO = 0.85;              // orca MAX_RATIO
  const KEY = (id) => `evo-split-${id}`;

  function makeResizable(panel) {
    if (panel.dataset.splitReady) return;
    panel.dataset.splitReady = '1';
    const id = panel.id || `${panel.className.split(' ')[0]}-${Math.abs([...panel.parentElement?.children || []].indexOf(panel))}`;

    const saved = Number(localStorage.getItem(KEY(id)));
    if (saved > MIN_PX) {
      panel.style.height = `${saved}px`;
      panel.style.maxHeight = 'none';
      panel.style.overflowY = 'auto';
    }

    const bar = document.createElement('div');
    bar.className = 'split-bar-h';
    bar.title = 'Drag to resize';
    panel.insertAdjacentElement('afterend', bar);

    let startY = 0;
    let startH = 0;
    function onMove(ev) {
      const dy = ev.clientY - startY;
      const max = window.innerHeight * MAX_RATIO;
      const h = Math.min(max, Math.max(MIN_PX, startH + dy));
      panel.style.height = `${h}px`;
      panel.style.maxHeight = 'none';
      panel.style.overflowY = 'auto';
    }
    function onUp() {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      bar.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      localStorage.setItem(KEY(id), String(panel.getBoundingClientRect().height | 0));
    }
    bar.addEventListener('mousedown', (ev) => {
      ev.preventDefault();
      startY = ev.clientY;
      startH = panel.getBoundingClientRect().height;
      bar.classList.add('dragging');
      document.body.style.cursor = 'row-resize';
      document.body.style.userSelect = 'none';
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
    // double-click resets to natural size
    bar.addEventListener('dblclick', () => {
      panel.style.height = '';
      panel.style.maxHeight = '';
      localStorage.removeItem(KEY(id));
    });
  }

  function sweep() {
    document.querySelectorAll('.ascii-panel').forEach(makeResizable);
  }
  new MutationObserver(sweep).observe(document.body, { childList: true, subtree: true });
  sweep();
})();
