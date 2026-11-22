// Ganjalf Studio: the app sets the tab title itself ("Chat - Unsloth"); show this fork's name instead.
// "Unsloth AI" (the company) is left alone. Loaded as a classic script, like theme-boot.js, so it
// satisfies script-src 'self' and is in place before the app renders.
(function () {
  var BRAND = /Unsloth(?: Studio)?(?! AI\b)/;
  function rewrite() {
    var title = document.title;
    if (BRAND.test(title)) {
      document.title = title.replace(BRAND, "Ganjalf Studio");
    }
  }
  rewrite();
  var node = document.querySelector("title");
  if (node && typeof MutationObserver === "function") {
    new MutationObserver(rewrite).observe(node, {
      childList: true,
      characterData: true,
      subtree: true,
    });
  }
})();
