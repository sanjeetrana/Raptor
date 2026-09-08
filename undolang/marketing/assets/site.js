(() => {
  const menu = document.querySelector('[data-menu]');
  const navigation = document.querySelector('[data-navigation]');
  const sidebar = document.querySelector('[data-sidebar]');
  if (menu) menu.addEventListener('click', () => {
    const target = sidebar || navigation;
    const open = target && target.classList.toggle('open');
    menu.setAttribute('aria-expanded', String(Boolean(open)));
  });
  document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    const selector = button.getAttribute('data-copy');
    const node = document.querySelector(selector);
    if (!node || !navigator.clipboard) return;
    await navigator.clipboard.writeText(node.textContent);
    const old = button.textContent;
    button.textContent = 'Copied';
    setTimeout(() => { button.textContent = old; }, 1400);
  }));
  document.querySelectorAll('[data-agent-context]').forEach(button => button.addEventListener('click', async () => {
    try {
      const response = await fetch(button.getAttribute('data-agent-context'));
      if (!response.ok) throw new Error('context unavailable');
      await navigator.clipboard.writeText(await response.text());
      button.textContent = 'Context copied';
    } catch (_) {
      window.location.href = button.getAttribute('data-fallback');
    }
  }));
})();

