// Test-render scenes that Claude wrote: bundle once, then render a few stills per scene.
// Usage: node check-custom-scenes.cjs <manifest.json>
// Manifest: {entry, publicDir, outDir, scenes: [{name, block}]}. Prints one CHECK_RESULT line.
const path = require('node:path'), fs = require('node:fs');
const {bundle} = require('@remotion/bundler');
const {openBrowser, selectComposition, renderStill} = require('@remotion/renderer');

let reported = false;
const report = (value) => console.log('CHECK_RESULT:' + JSON.stringify(value));
const clean = (error) => String(error && (error.stack || error.message) || error)
  .replace(/\u001b\[[0-9;]*m/g, '').split('\n').slice(0, 14).join('\n').slice(0, 2500);

(async () => {
  const manifest = JSON.parse(fs.readFileSync(path.resolve(process.argv[2]), 'utf8'));
  fs.mkdirSync(manifest.outDir, {recursive: true});
  let serveUrl;
  try {
    serveUrl = await bundle({entryPoint: manifest.entry, publicDir: manifest.publicDir});
  } catch (error) {
    report({bundleError: clean(error), scenes: {}});
    return;
  }
  const browser = await openBrowser('chrome', {logLevel: 'error'});
  const scenes = {};
  try {
    for (const scene of manifest.scenes) {
      const inputProps = {block: scene.block};
      const length = scene.block.durationFrames;
      // Start, middle, end and the held frame during the next transition.
      const frames = [...new Set([Math.min(5, length - 1), Math.floor(length / 2), length - 1, length + 8])];
      const logs = [];
      try {
        const composition = await selectComposition({serveUrl, id: 'CustomSceneCheck', inputProps, puppeteerInstance: browser, logLevel: 'error'});
        for (const frame of frames) {
          const output = path.join(manifest.outDir, `${scene.name}-${frame === Math.floor(length / 2) ? 'mid' : frame}.png`);
          await renderStill({serveUrl, composition, inputProps, frame, output, scale: 1 / 3, puppeteerInstance: browser,
            logLevel: 'error', onBrowserLog: (log) => { if (log.type === 'error') logs.push(log.text); }});
        }
        scenes[scene.name] = {ok: true, warnings: logs.slice(0, 5)};
      } catch (error) {
        scenes[scene.name] = {ok: false, error: clean(error), warnings: logs.slice(0, 5)};
      }
      console.log('[REFERENCE] Checked ' + scene.name + (scenes[scene.name].ok ? '' : ' (needs a fix)'));
    }
  } finally {
    // Report first: a browser that is already closing must not hide the results.
    report({scenes});
    reported = true;
    await browser.close({silent: true}).catch(() => {});
  }
})().catch((error) => { if (!reported) report({bundleError: clean(error), scenes: {}}); process.exitCode = reported ? 0 : 1; });
process.on('unhandledRejection', () => { if (!reported) process.exitCode = 1; });
