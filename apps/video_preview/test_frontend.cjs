// Dependency-free tests of the embedded page's timeout and recovery behavior.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, 'preview.py'), 'utf8')
  .match(/<script>([\s\S]*?)<\/script>/)[1];

function setup(mode) {
  const timers = new Map(), nodes = {}, calls = [], revoked = [], events = {};
  let id = 0, clock = 10;
  const video = {set src(value) {queueMicrotask(() => this.onload?.());}};
  nodes.video = video; nodes.status = {}; nodes.connection = {};
  const document = {hidden: false, getElementById: id => nodes[id],
    addEventListener: (name, fn) => events[name] = fn};
  const context = vm.createContext({document, AbortController,
    performance: {now: () => clock},
    URL: {createObjectURL: () => 'blob:test', revokeObjectURL: url => revoked.push(url)},
    setTimeout(fn, delay) {timers.set(++id, {fn, delay}); return id;},
    clearTimeout(id) {timers.delete(id);},
    fetch(url, options) {
      calls.push(url);
      if ((mode === 'frame-hang' && url === '/snapshot.jpg') || mode === 'all-hang') {
        return new Promise((resolve, reject) => options.signal.addEventListener('abort',
          () => reject(new Error('aborted')), {once: true}));
      }
      return Promise.resolve({ok: mode !== 'stale', status: 503,
        headers: {get: () => '10'}, blob: async () => ({}),
        json: async () => ({mode: 'hardware', fps: 30, jpeg_bytes: 49000, running: true})});
    }
  });
  vm.runInContext(code, context);
  return {timers, nodes, calls, revoked, events, document,
    run(delay) {
      const item = [...timers].find(([, timer]) => timer.delay === delay);
      assert.ok(item, 'Expected timer ' + delay);
      timers.delete(item[0]); clock += delay; item[1].fn();
    }};
}
async function flush() {for (let n = 0; n < 30; n++) await Promise.resolve();}
(async () => {
  const good = setup('ok'); await flush();
  assert.match(good.nodes.connection.textContent, /画面已连接/);
  assert.deepEqual(good.revoked, ['blob:test']);
  good.document.hidden = true; good.events.visibilitychange();
  const previous = good.calls.length;
  await flush();
  assert.equal(good.calls.length, previous, 'Hidden page must not fetch frames');
  good.document.hidden = false; good.events.visibilitychange();
  good.run(0); await flush();
  assert.equal(good.calls.length, previous + 1, 'Visible page resumes');

  const hung = setup('frame-hang'); await flush();
  hung.run(3000); await flush();
  assert.match(hung.nodes.connection.textContent, /连接中断/);
  assert.ok([...hung.timers.values()].some(t => t.delay === 1000));

  const all = setup('all-hang'); await flush();
  all.run(3000); all.run(3000); await flush();
  assert.match(all.nodes.status.textContent, /连接中断/);
  assert.match(all.nodes.connection.textContent, /连接中断/);

  const stale = setup('stale'); await flush();
  assert.match(stale.nodes.connection.textContent, /连接中断/);
  assert.equal(stale.revoked.length, 0);
  console.log('PASS: frame/status timeout, fresh frame, URL release, hidden/resume, stale response');
})().catch(error => {console.error(error); process.exitCode = 1;});
