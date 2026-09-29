/**
 * GET 请求的结果缓存（本机补丁）。
 *
 * ## 为什么需要
 *
 * 面板没有数据缓存层（只有 axios）：每个页面挂载时各拉一遍自己的数据，切走再切回来
 * 必然重新拉（仪表盘一次挂载要打 8 个接口，其中 `/api/accounts` 重复 3 次、`/api/me`
 * 2 次）。后端是毫秒级，慢的是「每切一次页就多几个网络往返」这件事在远程浏览器上的
 * 体感。
 *
 * ## 做法（不引依赖的最小实现）
 *
 *   1. 同一 `url+params` 在 TTL 内直接返回缓存 —— 切回刚看过的页面立刻有内容；
 *   2. 同一 `url+params` 的并发请求共享同一个 Promise —— 去掉同一次挂载里的重复请求；
 *   3. 任何成功的写操作调用 `invalidate()` 清空缓存 —— 改完不会再看到旧值；
 *   4. 高频轮询 / 实时状态类接口列入黑名单，永不缓存 —— 否则二维码登录、更新进度、
 *      重载状态这些「看着不动」的界面会真的卡住不动。
 *
 * ## 陈旧度上界
 *
 * TTL 15 秒 + 各页面自己的心跳（30s / 60s）会重新拉取，所以最坏情况是「15 秒内切回来
 * 看到的是刚才那份」，下一次心跳就会纠正。需要强制新鲜的地方（手动刷新按钮）先调
 * `invalidate()`，或给 `run` 传 `{force: true}`。
 *
 * ## 为什么单独成一个模块
 *
 * 它是**全局请求语义**，且必须能被 Node 直接跑（`.mjs` 直接 import 本文件做行为测试，
 * 见 `get-cache.test.mjs`）。因此本模块**不得出现任何运行期 import**。
 */

/** 缓存的默认存活时长（毫秒）。 */
export const CACHE_TTL_MS = 15_000;

/**
 * 永不缓存的路径：轮询 / 实时状态类接口。
 *
 * 这些接口的共同点是「看着不动」本身就是错误信号——二维码状态、更新进度、上游重载
 * 状态、任务运行进度。缓存它们会让界面真的卡住不动。
 */
export const NO_CACHE_PATTERNS: RegExp[] = [
  /\/api\/auth\//,                    // 扫码登录轮询（2s 一次）
  /\/api\/system\/update-status/,     // 更新进度（运行中 1.5s 一次）
  /\/api\/upstream\/reload-state/,    // 上游重载状态
  /\/(run|poll|progress)(\/|$|\?)/,   // 任务运行 / 进度类
  /healthz/,
];

export interface GetCacheOptions {
  /** 存活时长（毫秒），默认 `CACHE_TTL_MS`。 */
  ttlMs?: number;
  /** 永不缓存的路径模式，默认 `NO_CACHE_PATTERNS`。 */
  noCachePatterns?: RegExp[];
  /** 时钟（测试可注入），默认 `Date.now`。 */
  now?: () => number;
}

export interface GetCache {
  /**
   * 取一次 GET 结果。`fetcher` 只在「未命中且无在途同 key 请求」时被调用。
   * `force: true` 绕过读与写（结果不入缓存）。
   */
  run<T>(
    url: string,
    params: unknown,
    fetcher: () => Promise<T>,
    opts?: {force?: boolean},
  ): Promise<T>;
  /** 清空缓存（写操作后调用）。 */
  invalidate(): void;
}

/** 缓存键：无参就用 url，有参附上序列化结果。 */
export function cacheKey(url: string, params?: unknown): string {
  return params == null ? url : `${url}?${JSON.stringify(params)}`;
}

export function createGetCache(options: GetCacheOptions = {}): GetCache {
  const ttlMs = options.ttlMs ?? CACHE_TTL_MS;
  const patterns = options.noCachePatterns ?? NO_CACHE_PATTERNS;
  const now = options.now ?? (() => Date.now());

  const store = new Map<string, {t: number; v: unknown}>();
  const inflight = new Map<string, Promise<unknown>>();
  // 代数：写操作（invalidate）会让在途请求的旧结果失效。否则会出现「提交后清空缓存
  // → 提交前发出的那个 GET 慢一拍又把旧值塞回来」。
  let generation = 0;

  const isCacheable = (url: string) => !patterns.some((re) => re.test(url));

  function invalidate(): void {
    generation += 1;
    store.clear();
  }

  async function run<T>(
    url: string,
    params: unknown,
    fetcher: () => Promise<T>,
    opts?: {force?: boolean},
  ): Promise<T> {
    const cacheable = isCacheable(url) && !opts?.force;
    const key = cacheKey(url, params);

    if (cacheable) {
      const hit = store.get(key);
      if (hit && now() - hit.t < ttlMs) return hit.v as T;
      const pending = inflight.get(key);
      if (pending) return pending as Promise<T>;
    }

    const gen = generation;
    const request = (async () => {
      const data = await fetcher();
      if (cacheable && gen === generation) store.set(key, {t: now(), v: data});
      return data;
    })();

    if (!cacheable) return request;

    inflight.set(key, request);
    try {
      return await request;
    } finally {
      inflight.delete(key);
    }
  }

  return {run, invalidate};
}
