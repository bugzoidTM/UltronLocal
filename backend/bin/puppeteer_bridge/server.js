/**
 * UltronPro Puppeteer Bridge
 * Microserviço HTTP local que usa Puppeteer para navegação web com JS rendering.
 * Funciona nativamente no Windows sem conflito de event loop Python/asyncio.
 * Port: 9010
 */
const express = require('express');
const puppeteer = require('puppeteer');

const app = express();
app.use(express.json({ limit: '2mb' }));

const PORT = process.env.PUPPETEER_BRIDGE_PORT || 9010;
const BROWSER_TIMEOUT = parseInt(process.env.PUPPETEER_BROWSE_TIMEOUT_MS || '25000');

let _browser = null;

async function getBrowser() {
  if (_browser && _browser.isConnected()) return _browser;
  console.log('[PuppeteerBridge] Launching browser...');
  _browser = await puppeteer.launch({
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--no-first-run',
      '--no-zygote',
      '--disable-extensions',
    ],
  });
  _browser.on('disconnected', () => { _browser = null; });
  console.log('[PuppeteerBridge] Browser ready.');
  return _browser;
}

// Health check
app.get('/health', (req, res) => {
  res.json({ ok: true, service: 'puppeteer-bridge', port: PORT });
});

// Main browse endpoint
app.post('/browse', async (req, res) => {
  const { url, wait_until = 'networkidle2', timeout_ms = BROWSER_TIMEOUT, max_chars = 15000 } = req.body || {};

  if (!url || typeof url !== 'string') {
    return res.status(400).json({ ok: false, error: 'missing_url' });
  }

  let page = null;
  try {
    const browser = await getBrowser();
    page = await browser.newPage();

    // Realistic UA
    await page.setUserAgent(
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    );

    // Block heavy resources to speed up
    await page.setRequestInterception(true);
    page.on('request', (req) => {
      const rt = req.resourceType();
      if (['image', 'media', 'font', 'stylesheet'].includes(rt)) {
        req.abort();
      } else {
        req.continue();
      }
    });

    const waitUntilMap = {
      networkidle0: 'networkidle0',
      networkidle2: 'networkidle2',
      domcontentloaded: 'domcontentloaded',
      load: 'load',
    };
    const puppeteerWait = waitUntilMap[wait_until] || 'domcontentloaded';

    const response = await page.goto(url, {
      waitUntil: puppeteerWait,
      timeout: Math.min(timeout_ms, 30000),
    });

    const statusCode = response ? response.status() : 0;
    const html = await page.content();
    const title = await page.title();

    const text = await page.evaluate(() => {
      // Remove scripts, styles, nav junk
      ['script', 'style', 'nav', 'footer', 'header', 'aside'].forEach(tag => {
        document.querySelectorAll(tag).forEach(el => el.remove());
      });
      return (document.body && document.body.innerText) || '';
    });

    await page.close();

    const trimText = text.slice(0, max_chars);
    const trimHtml = html.slice(0, 80000); // Cap HTML size

    return res.json({
      ok: true,
      url,
      status: statusCode,
      title,
      text: trimText,
      html: trimHtml,
      text_chars: trimText.length,
    });

  } catch (err) {
    if (page) {
      try { await page.close(); } catch (_) {}
    }
    console.error(`[PuppeteerBridge] Error browsing ${url}: ${err.message}`);
    return res.json({ ok: false, url, error: err.message });
  }
});

// Text-only extract (faster, no HTML)
app.post('/extract', async (req, res) => {
  const { url, max_chars = 12000, timeout_ms = BROWSER_TIMEOUT } = req.body || {};
  if (!url) return res.status(400).json({ ok: false, error: 'missing_url' });

  let page = null;
  try {
    const browser = await getBrowser();
    page = await browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36');
    await page.setRequestInterception(true);
    page.on('request', r => {
      if (['image', 'media', 'font'].includes(r.resourceType())) r.abort();
      else r.continue();
    });

    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: Math.min(timeout_ms, 25000) });
    const statusCode = response ? response.status() : 0;
    const title = await page.title();
    const text = await page.evaluate(() => {
      ['script', 'style', 'nav', 'footer', 'header'].forEach(t => document.querySelectorAll(t).forEach(e => e.remove()));
      return document.body ? document.body.innerText : '';
    });
    await page.close();
    return res.json({ ok: true, url, status: statusCode, title, text: text.slice(0, max_chars) });
  } catch (err) {
    if (page) try { await page.close(); } catch (_) {}
    return res.json({ ok: false, url, error: err.message });
  }
});

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('[PuppeteerBridge] Shutting down...');
  if (_browser) await _browser.close();
  process.exit(0);
});

app.listen(PORT, '127.0.0.1', async () => {
  console.log(`[PuppeteerBridge] Listening on http://127.0.0.1:${PORT}`);
  // Pre-warm browser
  try { await getBrowser(); } catch (e) { console.warn('[PuppeteerBridge] Pre-warm failed:', e.message); }
});
