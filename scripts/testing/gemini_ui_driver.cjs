/* The desktop form and Timur's mobile request sheet share an API, with different controls. */
'use strict';
const { execFileSync } = require('node:child_process');

// Read the same dataset as create_app, including LIGHTMAP_SEGMENTS from .env.
const places = () => JSON.parse(execFileSync('.venv/bin/python', ['-c',
  "import gzip,json,os; from pathlib import Path; from backend.app import DEFAULT_SEGMENTS; p=Path(os.environ.get('LIGHTMAP_SEGMENTS') or DEFAULT_SEGMENTS).parent/'places.json.gz'; print(json.dumps(json.load(gzip.open(p,'rt'))['entries']))"], { encoding: 'utf8' }));

const input = mobile => mobile ? '#ask-ta' : '#ask-text';
const mic = mobile => mobile ? '[data-act="askMic"]' : '#ask-mic';
async function open(page, mobile) {
  if (mobile) {
    await page.evaluate(() => { if (screen !== 'home') go('home', false); });
    if (!await page.locator('#ask-ta').isVisible()) {
      await page.locator('[data-act="askOpen"], [data-act="askEdit"]').first().click();
    }
  }
  await page.locator(input(mobile)).waitFor({ state: 'visible' });
}
async function settled(page, mobile) {
  await page.waitForFunction(isMobile => isMobile ? !['wait', 'rec'].includes(ask.phase)
    : !document.getElementById('ask-go').disabled, mobile, { timeout: 120000 });
}
async function note(page, mobile) {
  return page.evaluate(isMobile => {
    if (!isMobile) return document.getElementById('ask-note').textContent;
    return document.querySelector('.ask-card, #ask-msg')?.textContent || '';
  }, mobile);
}
module.exports = { input, mic, open, settled, note, places };
