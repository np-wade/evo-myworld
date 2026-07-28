// jsdom render helper — a pure-JS DOM engine (no Chromium, no system libs).
// Loads a URL, fetches + executes page scripts, waits for DOMContentLoaded
// injectors to run, then prints the rendered outerHTML. Used by JsdomRenderer.
//   node render_jsdom.js <url>
const { JSDOM } = require('jsdom');
const url = process.argv[2];
// TLS verification is disabled via NODE_TLS_REJECT_UNAUTHORIZED=0 in the parent
// env (set by JsdomRenderer) so the hardened target's self-signed cert is OK.
(async () => {
  try {
    const dom = await JSDOM.fromURL(url, {
      runScripts: 'dangerously',   // execute <script> like a browser
      resources: 'usable',         // actually fetch /catalog.js etc.
      pretendToBeVisual: true,
    });
    // let DOMContentLoaded-registered injectors run
    await new Promise((r) => setTimeout(r, 250));
    process.stdout.write(dom.serialize());
    dom.window.close();
  } catch (e) {
    process.stderr.write('JSDOM_ERR: ' + (e && e.message ? e.message : e));
    process.exit(1);
  }
})();
