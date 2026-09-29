/**
 * `web/lib/get-cache.ts` 的行为测试（Node 直接跑 .ts 源码）。
 *
 * 跑法（Node ≥ 22.6）：
 *     node --experimental-strip-types web/lib/get-cache.test.mjs
 * 或走 Python 包装：`python -m unittest server.tests.test_get_cache`
 * （没有 node 时那条会 skip，不阻塞后端测试套件）。
 *
 * 为什么值得单独测：这是**全局请求语义**的改动，做错了界面不会报错，只会：
 *   · 该新鲜的拿到旧值（提交后还看到改之前的数据）；
 *   · 该合并的重复打请求（等于没做）；
 *   · 该永不缓存的轮询被冻住（二维码、更新进度「看着不动」）。
 * 三种都是「看起来没坏」的错，只能靠行为测试钉住。
 */
import {createGetCache, cacheKey, NO_CACHE_PATTERNS, CACHE_TTL_MS} from './get-cache.ts';

let failed = 0;

function check(name, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g === w) {
    console.log(`  ok  ${name}`);
  } else {
    console.log(`  FAIL ${name}\n       got  ${g}\n       want ${w}`);
    failed += 1;
  }
}

/** 可推进的假时钟：TTL 判定不靠真实等待 */
function makeClock(start = 1000) {
  let t = start;
  return {now: () => t, advance: (ms) => { t += ms; }};
}

/** 计数取数器：value 可以是值，也可以是 (第几次调用) => 值 */
function counter(value) {
  const fn = async () => {
    fn.calls += 1;
    return typeof value === 'function' ? value(fn.calls) : value;
  };
  fn.calls = 0;
  return fn;
}

function deferred() {
  let resolve;
  const promise = new Promise((res) => { resolve = res; });
  return {promise, resolve};
}

/* ── TTL：窗口内命中、窗口外重取 ─────────────────────────────── */

{
  const clock = makeClock();
  const cache = createGetCache({now: clock.now, ttlMs: 15_000});
  const f = counter('A');

  check('首次取数返回结果', await cache.run('/x', undefined, f), 'A');
  check('窗口内再次取用缓存（不重复请求）', await cache.run('/x', undefined, f), 'A');
  check('窗口内只打了 1 次请求', f.calls, 1);

  clock.advance(15_000);           // 到点（>= TTL 即过期）
  check('过期后重新取', await cache.run('/x', undefined, f), 'A');
  check('过期后打满 2 次', f.calls, 2);
}

/* ── 并发去重：同一 key 同时在飞 → 共享同一个 Promise ───────────── */

{
  const cache = createGetCache({now: makeClock().now});
  const d = deferred();
  const f = async () => { f.calls += 1; return d.promise; };
  f.calls = 0;

  const p1 = cache.run('/slow', undefined, f);
  const p2 = cache.run('/slow', undefined, f);
  d.resolve('V');
  check('并发同 key 得到同一个值', await Promise.all([p1, p2]), ['V', 'V']);
  check('并发同 key 只打 1 次请求', f.calls, 1);
}

/* ── 参数区分：不同 params 是不同缓存项 ────────────────────────── */

{
  const cache = createGetCache({now: makeClock().now});
  const f = counter((n) => `v${n}`);
  await cache.run('/x', {a: 1}, f);
  await cache.run('/x', {a: 1}, f);      // 命中
  await cache.run('/x', {a: 2}, f);      // 不同 key
  check('不同 params 分开缓存', f.calls, 2);
}

/* ── 黑名单：轮询类接口永不缓存 ───────────────────────────────── */

{
  const cache = createGetCache({now: makeClock().now});
  const f = counter('S');
  await cache.run('/api/auth/qr-status?token=1', undefined, f);
  await cache.run('/api/auth/qr-status?token=1', undefined, f);
  check('黑名单接口每次都真打', f.calls, 2);
  check('黑名单模式覆盖扫码/更新进度/重载状态/运行类/healthz',
        NO_CACHE_PATTERNS.length >= 5, true);
}

/* ── force：绕过缓存（且不污染已有缓存）──────────────────────── */

{
  const cache = createGetCache({now: makeClock().now});
  const f = counter((n) => `v${n}`);
  check('先正常取一次', await cache.run('/x', undefined, f), 'v1');
  check('force 绕过缓存重新取', await cache.run('/x', undefined, f, {force: true}), 'v2');
  check('force 结果不写回缓存，再次普通取仍是 v1',
        await cache.run('/x', undefined, f), 'v1');
  check('总请求数 = 2', f.calls, 2);
}

/* ── invalidate：写操作后清空 ────────────────────────────────── */

{
  const cache = createGetCache({now: makeClock().now});
  const f = counter((n) => `v${n}`);
  await cache.run('/x', undefined, f);
  cache.invalidate();
  await cache.run('/x', undefined, f);
  check('invalidate 后重新取', f.calls, 2);
}

/* ── invalidate 期间在途的旧结果不得写回 ─────────────────────── */

{
  const cache = createGetCache({now: makeClock().now});
  const d = deferred();
  const stale = async () => { stale.calls += 1; return d.promise; };
  stale.calls = 0;

  const p = cache.run('/y', undefined, stale);   // 在飞
  cache.invalidate();                            // 期间发生写操作
  d.resolve('OLD');
  check('在途请求本身仍返回给发起方', await p, 'OLD');

  const fresh = counter('NEW');
  check('清空后重新取到新值', await cache.run('/y', undefined, fresh), 'NEW');
  check('旧结果没有写回缓存', fresh.calls, 1);
}

/* ── cacheKey 规则 ──────────────────────────────────────────── */

check('无参 key 就是 url', cacheKey('/x'), '/x');
check('有参 key 带序列化', cacheKey('/x', {a: 1}), '/x?{"a":1}');
check('默认 TTL 是 15 秒', CACHE_TTL_MS, 15_000);

if (failed > 0) {
  console.log(`\n${failed} failed`);
  process.exit(1);
}
console.log('\nall passed');
