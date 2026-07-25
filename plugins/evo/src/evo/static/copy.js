// copy.js — clipboard support everywhere (pattern: ibelick/ui-skills
// copy-button, ported to vanilla + event delegation).
//  · elements with  data-copy="text"      → click copies that text
//  · panels with    data-copy-wrap        → get a hover "copy" button
//  · every <pre> rendered into the drawer → gets a hover "copy" button
// localhost is a secure context so navigator.clipboard works; execCommand
// kept as fallback for odd webviews.
(() => {
  'use strict';

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch { ok = false; }
      ta.remove();
      return ok;
    }
  }

  // Toast
  const toast = document.createElement('div');
  toast.className = 'copy-toast';
  toast.textContent = 'copied';
  document.body.appendChild(toast);
  let toastTimer = null;
  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 1200);
  }

  // Delegated: anything carrying data-copy
  document.addEventListener('click', async (ev) => {
    const chip = ev.target.closest('[data-copy]');
    if (!chip || chip.hasAttribute('data-copy-wrap')) return;
    ev.stopPropagation();
    if (await copyText(chip.dataset.copy)) showToast(`copied  ${chip.dataset.copy.slice(0, 40)}`);
  }, true);

  // Attach a copy button to a wrapper (idempotent).
  function attachButton(el, getText) {
    if (el.querySelector(':scope > .copy-btn')) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'copy-btn';
    btn.textContent = 'copy';
    btn.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      if (await copyText(getText())) {
        btn.textContent = 'copied';
        btn.classList.add('copied');
        setTimeout(() => { btn.textContent = 'copy'; btn.classList.remove('copied'); }, 1200);
      }
    });
    const style = getComputedStyle(el);
    if (style.position === 'static') el.style.position = 'relative';
    el.appendChild(btn);
  }

  // Static panels declared in index.html
  document.querySelectorAll('[data-copy-wrap]').forEach((el) => {
    attachButton(el, () => el.innerText.replace(/copy(ied)?$/, '').trimEnd());
  });

  // Dynamic content (drawer, modals): give every rendered <pre> a button.
  const seen = new WeakSet();
  function sweep(rootEl) {
    rootEl.querySelectorAll('pre').forEach((pre) => {
      if (seen.has(pre) || pre.closest('.copy-btn')) return;
      seen.add(pre);
      // copy the code content only (exclude our own button text)
      attachButton(pre, () => {
        const code = pre.querySelector('code');
        return (code ? code.innerText : pre.innerText).replace(/copy(ied)?$/, '').trimEnd();
      });
    });
  }
  const observer = new MutationObserver((muts) => {
    for (const m of muts) {
      for (const n of m.addedNodes) {
        if (n.nodeType === 1) sweep(n.matches('pre') ? n.parentElement || n : n);
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
  sweep(document.body);
})();
