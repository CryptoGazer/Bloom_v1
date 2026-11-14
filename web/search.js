'use strict';
/* Address box with suggestions while typing (ARIA combobox pattern: arrows, Enter, Escape).
   Asks /api/geocode on our own server; nothing typed leaves it. Needs t() from i18n.js.
   AddressBox(input, list, onPick) -> { set(text), clear() }; onPick gets {kind, name, lat, lon, detail, number_missing}. */
function AddressBox(input, list, onPick) {
  let items = [], active = -1, req = 0, timer = null;
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-expanded', 'false');
  input.setAttribute('aria-controls', list.id);
  list.setAttribute('role', 'listbox');

  function detail(r) {
    if (r.number_missing) return t('numberMissing', { n: r.number_missing });
    if (r.kind === 'stop') return r.detail ? t('stopLines', { lines: r.detail }) : t('kindLabel.stop');
    if (r.kind === 'place' && r.detail) {
      const cat = t('cat.' + r.detail);
      return cat === 'cat.' + r.detail ? t('kindLabel.place') : cat;
    }
    return t('kindLabel.' + r.kind);
  }

  function close() {
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
  }

  function highlight(i) {
    active = i;
    [...list.children].forEach((li, k) => li.setAttribute('aria-selected', String(k === i)));
    if (i >= 0) {
      input.setAttribute('aria-activedescendant', `${list.id}-${i}`);
      list.children[i].scrollIntoView({ block: 'nearest' });
    } else {
      input.removeAttribute('aria-activedescendant');
    }
  }

  function render() {
    list.innerHTML = items.length
      ? items.map((r, i) => `<li role="option" id="${list.id}-${i}" data-i="${i}" aria-selected="false">${esc(r.name)}<span class="sub">${esc(detail(r))}</span></li>`).join('')
      : `<li class="empty" role="option" aria-disabled="true">${esc(t('noResults'))}</li>`;
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    active = -1;
  }

  function pick(i) {
    const r = items[i];
    if (!r) return;
    input.value = r.name;
    close();
    onPick(r);
  }

  function query() {
    const q = input.value.trim(), mine = ++req;
    if (q.length < 2) { items = []; close(); return; }
    fetch('/api/geocode?limit=8&q=' + encodeURIComponent(q))
      .then(r => (r.ok ? r.json() : { results: [] }))
      .then(d => { if (mine === req && document.activeElement === input) { items = d.results || []; render(); } })
      .catch(() => { /* the route still works with map clicks */ });
  }

  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(query, 150); });
  input.addEventListener('focus', () => { if (input.value.trim().length >= 2 && !items.length) query(); });
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (list.hidden) { query(); return; }
      if (!items.length) return;
      const step = e.key === 'ArrowDown' ? 1 : -1;
      highlight((active + step + items.length) % items.length);
    } else if (e.key === 'Enter') {
      if (!list.hidden && items.length) { e.preventDefault(); pick(active >= 0 ? active : 0); }
    } else if (e.key === 'Escape') {
      close();
    }
  });
  input.addEventListener('blur', () => setTimeout(close, 120));
  list.addEventListener('mousedown', e => e.preventDefault()); // keep focus in the input while choosing
  list.addEventListener('click', e => {
    const li = e.target.closest('li[data-i]');
    if (li) pick(+li.dataset.i);
  });

  return {
    set(text) { input.value = text || ''; items = []; close(); },
    clear() { input.value = ''; items = []; close(); },
  };
}
