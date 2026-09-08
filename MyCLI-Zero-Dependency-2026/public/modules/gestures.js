(() => {
  const target = document.getElementById('content');
  if (!target) return;
  let startX = 0, startY = 0;
  target.addEventListener('touchstart', (event) => {
    const touch = event.changedTouches[0]; startX = touch.clientX; startY = touch.clientY;
  }, { passive: true });
  target.addEventListener('touchend', (event) => {
    const touch = event.changedTouches[0]; const dx = touch.clientX - startX; const dy = touch.clientY - startY;
    if (Math.max(Math.abs(dx), Math.abs(dy)) < 70) return;
    if (Math.abs(dx) > Math.abs(dy)) window.dispatchEvent(new CustomEvent('mycli:gesture', { detail: dx > 0 ? 'next' : 'previous' }));
    else window.dispatchEvent(new CustomEvent('mycli:gesture', { detail: dy > 0 ? 'actions' : 'quick' }));
  }, { passive: true });
})();
