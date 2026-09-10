// Render outside scroll containers so truncated cells and chips remain readable.
(() => {
  const tip = document.createElement('div');
  tip.className = 'floating-tooltip';
  tip.id = 'full-text-tooltip';
  tip.setAttribute('role', 'tooltip');
  tip.hidden = true;
  document.body.append(tip);
  let active;
  function hide() {
    if (active) active.removeAttribute('aria-describedby');
    active = null;
    tip.hidden = true;
  }
  function show(event) {
    const target = event.target.closest?.('[data-tooltip]');
    if (!target?.dataset.tooltip) { hide(); return; }
    if (active === target) return;
    hide();
    active = target;
    tip.textContent = target.dataset.tooltip;
    tip.hidden = false;
    target.setAttribute('aria-describedby', tip.id);
    const box = target.getBoundingClientRect();
    const size = tip.getBoundingClientRect();
    const left = Math.max(12, Math.min(box.left, innerWidth - size.width - 12));
    const top = box.top >= size.height + 20 ? box.top - size.height - 8 : box.bottom + 8;
    tip.style.left = `${left}px`;
    tip.style.top = `${Math.max(12, Math.min(top, innerHeight - size.height - 12))}px`;
  }
  document.addEventListener('pointerover', show);
  document.addEventListener('focusin', show);
  document.addEventListener('pointerout', event => {
    if (active && !active.contains(event.relatedTarget)) hide();
  });
  document.addEventListener('focusout', hide);
  document.addEventListener('scroll', hide, true);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') hide(); });
  window.addEventListener('resize', hide);
})();
