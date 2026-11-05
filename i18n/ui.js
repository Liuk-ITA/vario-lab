/* Translate display text only. Never touch values, recordings or protocol bytes. */
(function () {
  const {translate} = globalThis.VarioTranslations;
  const key = 'vibevario.language';
  let language = 'en';
  try { if (localStorage.getItem(key) === 'it') language = 'it'; } catch {}
  const records = new WeakMap(), attributes = new WeakMap();
  const excluded = 'script,style,textarea,pre,code,[data-i18n-owned],[data-i18n-skip]';
  const attrNames = ['title', 'placeholder', 'aria-label'];
  function renderText(node) {
    if (!node.parentElement || node.parentElement.closest(excluded)) return;
    let record = records.get(node);
    if (!record || node.nodeValue !== record.rendered) {
      record = {source: node.nodeValue, rendered: node.nodeValue};
      records.set(node, record);
    }
    const value = translate(record.source, language);
    record.rendered = value;
    if (node.nodeValue !== value) node.nodeValue = value;
  }
  function renderAttributes(element) {
    if (element.closest(excluded)) return;
    let map = attributes.get(element);
    if (!map) { map = new Map(); attributes.set(element, map); }
    for (const name of attrNames) {
      if (!element.hasAttribute(name)) continue;
      const current = element.getAttribute(name);
      let record = map.get(name);
      if (!record || current !== record.rendered) record = {source: current};
      const value = translate(record.source, language);
      record.rendered = value; map.set(name, record);
      if (current !== value) element.setAttribute(name, value);
    }
  }
  function renderTree(root) {
    if (root.nodeType === 3) { renderText(root); return; }
    if (root.nodeType !== 1 || root.closest(excluded)) return;
    renderAttributes(root);
    for (const node of root.childNodes) renderTree(node);
  }
  function guideLinks() {
    for (const anchor of document.querySelectorAll('a[href]')) {
      const href = anchor.getAttribute('href');
      if (/^(?:\.\.\/)?guide\/$/.test(href)) {
        anchor.setAttribute('href', href + language + '/index.html');
      } else if (/guide\/(?:en|it)\//.test(href)) {
        anchor.setAttribute('href', href.replace(/guide\/(?:en|it)\//, 'guide/' + language + '/'));
      }
    }
  }
  function setLanguage(value) {
    language = value === 'it' ? 'it' : 'en';
    document.documentElement.lang = language;
    try { localStorage.setItem(key, language); } catch {}
    renderTree(document.documentElement);
    guideLinks();
    const picker = document.getElementById('site-language');
    if (picker) picker.value = language;
    window.dispatchEvent(new Event('variolanguagechange'));
  }
  window.VarioI18n = {get language() { return language; },
    t: text => translate(String(text), language), setLanguage};

  function start() {
    const label = document.createElement('label');
    label.className = 'language-picker'; label.dataset.i18nOwned = '';
    const select = document.createElement('select');
    select.id = 'site-language'; select.setAttribute('aria-label', 'Language / Lingua');
    for (const [value, text] of [['en', 'English'], ['it', 'Italiano']]) {
      const option = document.createElement('option');
      option.value = value; option.textContent = text; select.append(option);
    }
    label.append(select); (document.querySelector('header') || document.body).append(label);
    select.addEventListener('change', () => setLanguage(select.value));
    setLanguage(language);
    new MutationObserver(changes => {
      for (const change of changes) {
        if (change.type === 'characterData') renderText(change.target);
        else if (change.type === 'attributes') renderAttributes(change.target);
        else for (const node of change.addedNodes) renderTree(node);
      }
    }).observe(document.documentElement, {subtree: true, childList: true,
      characterData: true, attributes: true, attributeFilter: attrNames});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
