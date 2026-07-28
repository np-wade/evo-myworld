// Injects the catalog item links into the DOM AFTER load.
// A raw-HTML link parser never sees these; a JS-executing browser does.
var ITEMS = ["1", "2", "3", "4", "5", "6"];
document.addEventListener('DOMContentLoaded', function () {
  var c = document.getElementById('items');
  if (!c) return;
  c.innerHTML = ITEMS.map(function (n) {
    return "<a href='/item/" + n + "'>Item " + n + "</a>";
  }).join(' ');
});
