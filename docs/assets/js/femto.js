/* femto_UN docs — comportamiento mínimo: tema, menú móvil, índice lateral, botones de copiar. */
(function () {
  'use strict';
  var doc = document, root = doc.documentElement;

  /* ── tema claro / oscuro ── */
  function currentTheme() {
    var t = root.getAttribute('data-theme');
    if (t) return t;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  doc.querySelectorAll('.theme-toggle').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var next = currentTheme() === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('femto-theme', next); } catch (e) {}
    });
  });

  /* ── menú móvil ── */
  var menuBtn = doc.getElementById('menu-toggle');
  function setNav(open) {
    doc.body.classList.toggle('nav-open', open);
    if (menuBtn) menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  if (menuBtn) menuBtn.addEventListener('click', function () { setNav(!doc.body.classList.contains('nav-open')); });
  var backdrop = doc.getElementById('backdrop');
  if (backdrop) backdrop.addEventListener('click', function () { setNav(false); });
  doc.addEventListener('keydown', function (e) { if (e.key === 'Escape') setNav(false); });
  doc.querySelectorAll('.sidebar nav a').forEach(function (a) { a.addEventListener('click', function () { setNav(false); }); });

  var prose = doc.querySelector('.prose');
  if (!prose) return;

  /* ── tablas con desplazamiento horizontal ── */
  prose.querySelectorAll('table').forEach(function (t) {
    if (t.parentElement.classList.contains('table-wrap')) return;
    var w = doc.createElement('div');
    w.className = 'table-wrap';
    t.parentNode.insertBefore(w, t);
    w.appendChild(t);
  });

  /* ── botones de copiar en bloques de código ── */
  prose.querySelectorAll('pre').forEach(function (pre) {
    if (pre.closest('.code-wrap')) return;
    var wrap = doc.createElement('div');
    wrap.className = 'code-wrap';
    var host = pre.parentElement && /highlight|codehilite/.test(pre.parentElement.className) ? pre.parentElement : pre;
    host.parentNode.insertBefore(wrap, host);
    wrap.appendChild(host);
    var b = doc.createElement('button');
    b.type = 'button'; b.className = 'copy'; b.textContent = 'Copiar';
    b.setAttribute('aria-label', 'Copiar código');
    b.addEventListener('click', function () {
      var text = pre.innerText.replace(/\n$/, '');
      var done = function () { b.textContent = 'Copiado'; setTimeout(function () { b.textContent = 'Copiar'; }, 1400); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () {});
      } else {
        var ta = doc.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
        doc.body.appendChild(ta); ta.select();
        try { doc.execCommand('copy'); done(); } catch (e) {}
        doc.body.removeChild(ta);
      }
    });
    wrap.appendChild(b);
  });

  /* ── enlaces de ancla + índice "En esta página" ── */
  var heads = Array.prototype.slice.call(prose.querySelectorAll('h2, h3'));
  heads.forEach(function (h) {
    if (!h.id) return;
    var a = doc.createElement('a');
    a.className = 'anchor'; a.href = '#' + h.id; a.setAttribute('aria-label', 'Enlace a esta sección'); a.textContent = '#';
    h.appendChild(a);
  });

  var toc = doc.getElementById('toc');
  var withId = heads.filter(function (h) { return h.id; });
  if (toc && withId.length >= 3) {
    var ul = toc.querySelector('ul');
    var links = [];
    withId.forEach(function (h) {
      var li = doc.createElement('li');
      if (h.tagName === 'H3') li.className = 'sub';
      var a = doc.createElement('a');
      a.href = '#' + h.id;
      var clone = h.cloneNode(true);
      var anc = clone.querySelector('.anchor'); if (anc) anc.remove();
      a.textContent = clone.textContent.trim();
      li.appendChild(a); ul.appendChild(li); links.push({ a: a, h: h });
    });
    toc.hidden = false;
    if ('IntersectionObserver' in window) {
      var current = null;
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) { if (en.isIntersecting) current = en.target; });
        if (!current) return;
        links.forEach(function (l) { l.a.classList.toggle('on', l.h === current); });
      }, { rootMargin: '-72px 0px -70% 0px', threshold: 0 });
      withId.forEach(function (h) { io.observe(h); });
    }
  }
})();
