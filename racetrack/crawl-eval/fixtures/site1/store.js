// Injects store links by FETCHING a JSON endpoint, then building <a>.
// jsdom provides no global fetch() -> this throws there and no links
// appear; real browsers (playwright/selenium/crawl4ai) have fetch.
document.addEventListener('DOMContentLoaded', function () {
  fetch('/store-data.json').then(function (r) { return r.json(); })
    .then(function (ids) {
      var c = document.getElementById('store');
      if (!c) return;
      c.innerHTML = ids.map(function (n) {
        return "<a href='/product/" + n + "'>Product " + n + "</a>";
      }).join(' ');
    });
});
