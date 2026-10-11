'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');

async function main() {
  const html = fs.readFileSync(path.join(root, 'src/static/index.html'), 'utf8');
  const dom = new JSDOM(html, { url: 'http://localhost/', runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  const requests = [];
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.HTMLMediaElement.prototype.pause = () => {};
  w.HTMLMediaElement.prototype.play = async () => {};
  w.scrollTo = () => {};
  w.URL.createObjectURL = () => 'blob:test';
  const revoked = [];
  w.URL.revokeObjectURL = (url) => revoked.push(url);
  w.EventSource = class { constructor(url) { this.url = url; } close() {} };
  const info = { url: 'https://public.example/playlist', title: 'Example', duration: 60, is_playlist: true, playlist_count: 1,
    available_video_resolutions: [{ value: '1080p', label: '1080p', height: 1080 }],
    playlist_entries: [{ index: 1, title: '<img src=x onerror="window.pwned=true">', duration_formatted: '01:00' }] };
  w.fetch = async (url, options = {}) => {
    requests.push({ url, options });
    const data = url === '/api/info' ? info : url === '/api/cookies' ? { has_cookies: false } : undefined;
    return { ok: true, json: async () => ({ success: true, data, task_id: 'fcd53ce7-59cf-4f27-92bf-8cd651c80f25' }) };
  };
  w.eval(fs.readFileSync(path.join(root, 'src/static/js/app.js'), 'utf8'));
  w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
  const app = w.app;
  assert(app);
  assert.equal(w.document.querySelectorAll('[onclick],[onchange],[onsubmit]').length, 0);
  app.dom.urlInput.value = 'https://public.example/playlist';
  app.dom.urlForm.dispatchEvent(new w.Event('submit', { cancelable: true }));
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(app.dom.mediaTitle.textContent, 'Example');
  assert.equal(app.dom.playlistList.querySelector('img'), null);
  assert.equal(app.dom.playlistList.querySelector('.playlist-item-title').textContent, info.playlist_entries[0].title);
  assert.equal(w.pwned, undefined);

  app.renderVideoResolutions([{ value: '1080p', label: '<img src=x onerror="window.pwned=true">', height: 1080 }]);
  assert.equal(app.dom.videoResolutionsGrid.querySelector('img'), null);
  app.dom.themeToggleBtn.click();
  assert.equal(app.dom.html.dataset.theme, 'light');
  app.dom.cookieNavBtn.click();
  assert.equal(app.dom.cookieModal.classList.contains('hidden'), false);
  app.closeCookieModal();

  app.toggleAllPlaylist(false);
  await app.startDownload();
  assert.equal(app.state.isProcessing, false);
  assert.match(app.dom.errorMessage.textContent, /Select at least one/);
  assert(!requests.some(r => r.url === '/api/download'));
  app.toggleAllPlaylist(true);
  let clientCalled = false;
  w.StreamFabClientEngine = { process: async () => { clientCalled = true; }, cancel() {} };
  await app.startDownload();
  assert.equal(clientCalled, false);
  const serverRequest = requests.find(r => r.url === '/api/download');
  assert.deepEqual(JSON.parse(serverRequest.options.body).playlist_indices, [1]);
  app.resetAll();

  // Cancel an in-browser operation and ensure it never falls back to the server.
  info.is_playlist = false;
  app.renderMediaInfo(info);
  const before = requests.filter(r => r.url === '/api/download').length;
  let rejectProcess;
  w.StreamFabClientEngine = {
    process: () => new Promise((_, reject) => { rejectProcess = reject; }),
    cancel: () => { const error = new Error('cancelled'); error.name = 'AbortError'; rejectProcess(error); }
  };
  const pending = app.startDownload();
  await app.cancelCurrentTask();
  await pending;
  assert.equal(requests.filter(r => r.url === '/api/download').length, before);
  assert.equal(app.state.isProcessing, false);
  app.state.blobUrl = 'blob:previous';
  app.resetAll();
  assert(revoked.includes('blob:previous'));
  dom.window.close();
  console.log('App DOM regressions passed: event bindings, XSS, theme, cookies, playlist routing, cancellation and blob cleanup.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
