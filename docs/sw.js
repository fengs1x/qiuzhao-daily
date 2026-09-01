/* 秋招每日通 - Service Worker：应用外壳与数据离线缓存 */
var CACHE = "qiuzhao-v16";
var SHELL = [
  "./",
  "./index.html",
  "./css/style.css",
  "./js/app.js",
  "./js/data.js",
  "./manifest.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png"
];

self.addEventListener("install", function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) {
      return c.addAll(SHELL);
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (e) {
  var url = e.request.url;

  // 刷新/抓取接口：始终直连网络，绝不缓存（避免轮询拿到旧状态）
  if (url.indexOf("/refresh") >= 0) {
    e.respondWith(fetch(e.request));
    return;
  }

  // 数据文件：网络优先，失败回退缓存（保证离线可看历史数据）
  if (url.indexOf("data/data.json") >= 0) {
    e.respondWith(
      fetch(e.request)
        .then(function (res) {
          var clone = res.clone();
          caches.open(CACHE).then(function (c) { c.put(e.request, clone); });
          return res;
        })
        .catch(function () {
          return caches.match(e.request).then(function (hit) {
            return hit || caches.match("./js/data.js");
          });
        })
    );
    return;
  }

  // 应用外壳：缓存优先
  e.respondWith(
    caches.match(e.request).then(function (hit) {
      return hit || fetch(e.request).then(function (res) {
        var clone = res.clone();
        caches.open(CACHE).then(function (c) { c.put(e.request, clone); });
        return res;
      });
    })
  );
});
