// Set the theme before anything is drawn (no flash): the saved choice, else the device setting.
// This is a separate file (not inline in index.html) so the Content-Security-Policy can
// forbid inline scripts.
(function () {
  var t = null
  try { t = localStorage.getItem('theme') } catch (e) {}
  if (t !== 'light' && t !== 'dark') {
    t = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  document.documentElement.setAttribute('data-theme', t)
})()
