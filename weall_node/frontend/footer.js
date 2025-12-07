// Simple footer helper; keeps the year up to date.
(function () {
  const el = document.getElementById('footer-year');
  if (el) {
    el.textContent = new Date().getFullYear().toString();
  }
})();
