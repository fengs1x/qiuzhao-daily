/* ===== 秋招每日通 App 逻辑 v2 ===== */
(function () {
  "use strict";

  // ---------- 常量与状态 ----------
  var LS_26 = "qd_switch26";
  var LS_NOTIFIED = "qd_notified_date";
  var LS_FAV = "qd_favorites";
  var LS_SERVER = "qd_server";   // 云端后端地址（脱离电脑版）
  var DB_NAME = "qiuzhao-db";
  var STORE = "data";
  var RENDER_BATCH = 40; // 每次渲染条数（无限滚动）

  var HEART_OFF = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 20.5S4.5 16 2.8 11.3C1.6 8 3.4 5 6.4 5c2 0 3.5 1.2 4.3 2.4C11.5 6.2 13 5 15 5c3 0 4.8 3 3.6 6.3C17 16 12 20.5 12 20.5z"/></svg>';
  var HEART_ON = '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M12 20.5S4.5 16 2.8 11.3C1.6 8 3.4 5 6.4 5c2 0 3.5 1.2 4.3 2.4C11.5 6.2 13 5 15 5c3 0 4.8 3 3.6 6.3C17 16 12 20.5 12 20.5z"/></svg>';

  var state = {
    data: null,           // { meta, companies }
    tab: "today_new",     // today_new | ongoing | favorites
    only26: false,
    search: "",
    industry: "",
    companyType: "",
    location: "",
    year: "",
    visible: RENDER_BATCH, // 已渲染条数
    filteredLen: 0         // 当前筛选结果总数
  };

  var refreshState = { busy: false, timer: null, tries: 0 };

  var el = {};
  var db = null;
  var io = null;          // 无限滚动观察器

  // ---------- 工具 ----------
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s); }
  function escHtml(s) {
    return esc(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function openDB() {
    return new Promise(function (resolve, reject) {
      if (db) { return resolve(db); }
      if (!window.indexedDB) { return reject(new Error("no indexedDB")); }
      var req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () {
        if (!req.result.objectStoreNames.contains(STORE)) {
          req.result.createObjectStore(STORE);
        }
      };
      req.onsuccess = function () { db = req.result; resolve(db); };
      req.onerror = function () { reject(req.error); };
    });
  }
  function dbSet(key, val) {
    return openDB().then(function (d) {
      return new Promise(function (resolve, reject) {
        var tx = d.transaction(STORE, "readwrite");
        tx.objectStore(STORE).put(val, key);
        tx.oncomplete = resolve;
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }
  function dbGet(key) {
    return openDB().then(function (d) {
      return new Promise(function (resolve, reject) {
        var tx = d.transaction(STORE, "readonly");
        var req = tx.objectStore(STORE).get(key);
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function todayStr() {
    var d = new Date();
    function p(n) { return n < 10 ? "0" + n : "" + n; }
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
  }

  // ---------- 筛选维度辅助 ----------
  function typeBucket(t) {
    if (!t) { return "其他"; }
    if (t.indexOf("央") >= 0) { return "央国企"; }
    if (t.indexOf("外企") >= 0 || t.indexOf("外资") >= 0 || t.indexOf("合资") >= 0) { return "外企"; }
    if (t.indexOf("事业") >= 0) { return "事业单位"; }
    if (t.indexOf("银行") >= 0) { return "银行"; }
    if (t.indexOf("民企") >= 0) { return "民企"; }
    return "其他";
  }
  function locTokens(loc) {
    if (!loc) { return []; }
    var seen = {};
    String(loc).split(/[,，、;；\s]+/).forEach(function (t) {
      t = t.trim();
      if (t) { seen[t] = true; }
    });
    return Object.keys(seen);
  }
  function positionsPreview(c) {
    if (c.positions && c.positions.length) {
      return c.positions.slice(0, 3).join("、") + (c.positions.length > 3 ? " 等 " + c.positions.length + " 个岗位" : "");
    }
    return "";
  }

  // ---------- 我的收藏 ----------
  var favs = []; // [{ name, snapshot, at }]

  function favLoad() {
    try { favs = JSON.parse(localStorage.getItem(LS_FAV)) || []; }
    catch (e) { favs = []; }
    if (!Array.isArray(favs)) { favs = []; }
  }
  function favSave() {
    try { localStorage.setItem(LS_FAV, JSON.stringify(favs)); } catch (e) {}
  }
  function favIndexOf(name) {
    for (var i = 0; i < favs.length; i++) { if (favs[i].name === name) { return i; } }
    return -1;
  }
  function isFav(name) { return favIndexOf(name) >= 0; }
  function favToggle(record) {
    var i = favIndexOf(record.name);
    if (i >= 0) { favs.splice(i, 1); }
    else { favs.unshift({ name: record.name, snapshot: record, at: Date.now() }); }
    favSave();
    updateFavCount();
    return isFav(record.name);
  }
  function favRecords() {
    var byName = {};
    if (state.data && state.data.companies) {
      state.data.companies.forEach(function (c) { if (!byName[c.name]) { byName[c.name] = c; } });
    }
    return favs.map(function (f) { return byName[f.name] || f.snapshot; });
  }
  function updateFavCount() {
    if (el.countFav) { el.countFav.textContent = favs.length; }
  }
  function makeFavBtn(record) {
    var btn = document.createElement("button");
    btn.className = "fav-btn" + (isFav(record.name) ? " on" : "");
    btn.setAttribute("aria-label", "收藏");
    btn.innerHTML = isFav(record.name) ? HEART_ON : HEART_OFF;
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      var on = favToggle(record);
      btn.className = "fav-btn" + (on ? " on" : "");
      btn.innerHTML = on ? HEART_ON : HEART_OFF;
      toast(on ? "已加入我的收藏" : "已取消收藏");
      renderList();
    });
    return btn;
  }

  function toast(msg) {
    var t = el.toast;
    t.textContent = msg;
    t.hidden = false;
    t.classList.remove("show");
    void t.offsetWidth;
    t.classList.add("show");
    clearTimeout(toast._timer);
    toast._timer = setTimeout(function () { t.hidden = true; }, 2400);
  }

  // ---------- 服务器地址（脱离电脑：手机 App 指向云端后端） ----------
  function baseUrl() {
    var v = "";
    try { v = localStorage.getItem(LS_SERVER) || ""; } catch (e) {}
    return v.replace(/\/+$/, "");
  }
  function serverLabel() {
    var v = baseUrl();
    return v ? v : "当前页面来源";
  }
  function openSettings() {
    if (!el.settingsModal) { return; }
    el.settingsInput.value = baseUrl();
    el.settingsStatus.textContent = "当前： " + serverLabel();
    el.settingsModal.hidden = false;
  }
  function closeSettings() {
    if (el.settingsModal) { el.settingsModal.hidden = true; }
  }
  function saveServer(url) {
    url = (url || "").trim().replace(/\/+$/, "");
    try { localStorage.setItem(LS_SERVER, url); } catch (e) {}
    closeSettings();
    toast(url ? "服务器地址已保存 · " + url : "已使用当前页面来源");
    loadData(true);
  }

  // ---------- 数据加载（秒开：缓存先行 + 后台刷新） ----------
  function fetchRemote() {
    return fetch(baseUrl() + "/data/data.json?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); });
  }

  function loadEmbeddedFallback() {
    return new Promise(function (resolve, reject) {
      if (window.__QIUDATA__ && window.__QIUDATA__.companies) {
        return resolve(window.__QIUDATA__);
      }
      var s = document.createElement("script");
      s.src = "js/data.js";
      s.onload = function () {
        if (window.__QIUDATA__ && window.__QIUDATA__.companies) {
          resolve(window.__QIUDATA__);
        } else {
          reject(new Error("data.js 无数据"));
        }
      };
      s.onerror = function () { reject(new Error("data.js 加载失败")); };
      document.head.appendChild(s);
    });
  }

  function showSkeleton(on) {
    if (!el.loading) { return; }
    el.loading.hidden = !on;
  }

  function loadData(forceNetwork) {
    showSkeleton(true);
    el.empty.hidden = true;
    state.visible = RENDER_BATCH;

    function applyFresh(json) {
      var changed = !state.data || !state.data.meta || !json.meta ||
        state.data.meta.generated_at !== json.meta.generated_at;
      state.data = json;
      renderAll();
      return dbSet("cached", json).catch(function () {}).then(function () { return changed; });
    }
    function applyCached(c) {
      state.data = c;
      renderAll();
    }

    if (forceNetwork) {
      return fetchRemote().then(applyFresh).catch(function () {
        return dbGet("cached").then(function (c) { if (c) { applyCached(c); } });
      }).then(function (changed) {
        showSkeleton(false);
        return !!changed;
      });
    }

    return dbGet("cached").then(function (c) {
      if (c) {
        applyCached(c);           // 秒开
        showSkeleton(false);
        return fetchRemote().then(function (json) {   // 后台刷新
          var changed = !json.meta || !c.meta || json.meta.generated_at !== c.meta.generated_at;
          if (changed) { applyFresh(json); }
          return dbSet("cached", json).catch(function () {});
        }).catch(function () {});
      }
      return fetchRemote().then(applyFresh);          // 首次无缓存
    }).then(function () { showSkeleton(false); })
      .catch(function (e) {
        showSkeleton(false);
        el.empty.hidden = false;
        el.empty.textContent = "数据加载失败，请联网或先运行一次抓取： " + e.message;
      });
  }

  // ---------- 抓取今日最新数据（右上角刷新 → 后台跑爬虫 → 轮询） ----------
  function pollRefresh() {
    if (refreshState.timer) { clearTimeout(refreshState.timer); }
    refreshState.tries++;
    fetch(baseUrl() + "/refresh/status", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (s) {
        if (s.status === "running") {
          toast("正在抓取今日最新数据（约 1~2 分钟）…");
          refreshState.timer = setTimeout(pollRefresh, 2500);
          return;
        }
        finishRefresh(s);
      })
      .catch(function () {
        if (refreshState.tries > 80) {          // 约 3 分钟上限
          finishRefresh({ ok: false, err: true });
          return;
        }
        refreshState.timer = setTimeout(pollRefresh, 2500);
      });
  }

  function finishRefresh(s) {
    refreshState.busy = false;
    el.refreshBtn.classList.remove("spin");
    if (refreshState.timer) { clearTimeout(refreshState.timer); }
    refreshState.timer = null;
    loadData(true).then(function () {
      if (s && s.err) {
        toast("抓取超时，请稍后重试");
      } else if (s && s.ok === false && s.err !== true) {
        toast("抓取未成功，已展示当前数据");
      } else {
        var gen = (state.data && state.data.meta && state.data.meta.generated_at) || "";
        toast("已抓取今日最新数据 · 更新于 " + gen);
      }
    });
  }

  // ---------- 过滤 ----------
  function filterCompanies() {
    var source = (state.tab === "favorites") ? favRecords() : state.data.companies;
    return source.filter(function (c) {
      if (state.tab !== "favorites" && c.status !== state.tab) { return false; }
      if (state.only26 && !c.is_26) { return false; }
      if (state.industry && c.industry !== state.industry) { return false; }
      if (state.companyType && typeBucket(c.company_type) !== state.companyType) { return false; }
      if (state.location && locTokens(c.location).indexOf(state.location) < 0) { return false; }
      if (state.year && (c.years || []).indexOf(state.year) < 0) { return false; }
      if (state.search) {
        var q = state.search.toLowerCase();
        var hay = (c.name + " " + (c.position || "") + " " + (c.location || "") + " " +
          (c.industry || "") + " " + ((c.positions || []).join(" ")) + " " +
          ((c.majors || []).join(" ")) + " " + (c.title || "") + " " + (c.scale || "")).toLowerCase();
        if (hay.indexOf(q) < 0) { return false; }
      }
      return true;
    });
  }

  // ---------- 渲染 ----------
  function renderAll() {
    if (!state.data) { return; }
    var meta = state.data.meta || {};
    el.todayLabel.textContent = (meta.today || todayStr()) + " · 更新于 " + (meta.generated_at || "--");
    el.countToday.textContent = meta.today_new || 0;
    el.countOngoing.textContent = meta.ongoing || 0;
    updateFavCount();
    buildIndustryOptions(meta.industries || []);
    buildTypeOptions();
    buildLocOptions();
    buildYearOptions();
    renderList();
    checkNotice(meta);
  }

  function buildIndustryOptions(industries) {
    var sel = el.industrySelect;
    if (sel.dataset.built === "1") { sel.value = state.industry; return; }
    sel.innerHTML = "";
    var all = document.createElement("option");
    all.value = ""; all.textContent = "全部行业";
    sel.appendChild(all);
    industries.forEach(function (ind) {
      var opt = document.createElement("option");
      opt.value = ind; opt.textContent = ind;
      sel.appendChild(opt);
    });
    sel.dataset.built = "1";
    sel.value = state.industry;
  }

  function buildTypeOptions() {
    var sel = el.typeSelect;
    if (sel.dataset.built === "1") { sel.value = state.companyType; return; }
    sel.innerHTML = "";
    var all = document.createElement("option");
    all.value = ""; all.textContent = "全部单位";
    sel.appendChild(all);
    ["民企", "央国企", "外企", "事业单位", "银行", "其他"].forEach(function (t) {
      var opt = document.createElement("option");
      opt.value = t; opt.textContent = t;
      sel.appendChild(opt);
    });
    sel.dataset.built = "1";
    sel.value = state.companyType;
  }

  function buildLocOptions() {
    var sel = el.locSelect;
    if (sel.dataset.built === "1") { sel.value = state.location; return; }
    var cnt = {};
    state.data.companies.forEach(function (c) {
      locTokens(c.location).forEach(function (t) { cnt[t] = (cnt[t] || 0) + 1; });
    });
    sel.innerHTML = "";
    var all = document.createElement("option");
    all.value = ""; all.textContent = "全部地点";
    sel.appendChild(all);
    Object.keys(cnt)
      .filter(function (t) { return t !== "全国" && t.indexOf("不限") < 0 && t.indexOf("地点") < 0; })
      .sort(function (a, b) { return cnt[b] - cnt[a]; })
      .slice(0, 24)
      .forEach(function (t) {
        var opt = document.createElement("option");
        opt.value = t; opt.textContent = t + "（" + cnt[t] + "）";
        sel.appendChild(opt);
      });
    if (cnt["全国"]) {
      var o = document.createElement("option");
      o.value = "全国"; o.textContent = "全国（" + cnt["全国"] + "）";
      sel.appendChild(o);
    }
    sel.dataset.built = "1";
    sel.value = state.location;
  }

  function buildYearOptions() {
    var sel = el.yearSelect;
    if (sel.dataset.built === "1") { sel.value = state.year; return; }
    var ys = {};
    state.data.companies.forEach(function (c) {
      (c.years || []).forEach(function (y) { if (/^20\d\d$/.test(y)) { ys[y] = 1; } });
    });
    sel.innerHTML = "";
    var all = document.createElement("option");
    all.value = ""; all.textContent = "全部届数";
    sel.appendChild(all);
    Object.keys(ys).sort().forEach(function (y) {
      var opt = document.createElement("option");
      opt.value = y; opt.textContent = y + "届";
      sel.appendChild(opt);
    });
    sel.dataset.built = "1";
    sel.value = state.year;
  }

  function buildCard(c) {
    var card = document.createElement("div");
    card.className = "card" + (isFav(c.name) ? " is-fav" : "");

    // 头部
    var head = document.createElement("div");
    head.className = "card-head";
    if (c.is_26) {
      var dot = document.createElement("span");
      dot.className = "dot26";
      dot.title = "26届可投";
      head.appendChild(dot);
    }
    var name = document.createElement("span");
    name.className = "card-name";
    name.textContent = c.name;
    head.appendChild(name);

    if (c.recruit_type) {
      var rb = document.createElement("span");
      rb.className = "badge badge-recruit";
      rb.textContent = c.recruit_type;
      head.appendChild(rb);
    }
    if (c.company_type) {
      var cb = document.createElement("span");
      cb.className = "badge badge-type";
      cb.textContent = c.company_type;
      head.appendChild(cb);
    }
    if (c.is_26) {
      var b26 = document.createElement("span");
      b26.className = "badge badge-26";
      b26.textContent = "26届";
      head.appendChild(b26);
    }
    head.appendChild(makeFavBtn(c));
    card.appendChild(head);

    // 信息行
    var rows = document.createElement("div");
    rows.className = "card-rows";
    var pv = positionsPreview(c);
    if (pv) {
      rows.appendChild(row("岗位", pv, false, true));
    } else if (c.title) {
      rows.appendChild(row("主题", c.title, false, false));
    }
    if (c.target_years) {
      rows.appendChild(row("目标届数", c.target_years, true));
    }
    if (c.industry && c.industry !== "其他") {
      rows.appendChild(row("行业", c.industry, false));
    }
    rows.appendChild(row("更新", c.post_date || "--", false));
    rows.appendChild(row("截止", c.deadline || "--", false));
    if (c.location) {
      rows.appendChild(row("地点", c.location, false));
    }
    card.appendChild(rows);

    card.addEventListener("click", function () { showDetail(c); });
    return card;
  }

  function row(k, v, strong, accent) {
    var r = document.createElement("div");
    r.className = "card-row";
    var kk = document.createElement("span");
    kk.className = "k"; kk.textContent = k;
    var vv = document.createElement("span");
    vv.className = "v" + (strong ? " v-strong" : "") + (accent ? " v-accent" : "");
    vv.textContent = v;
    r.appendChild(kk); r.appendChild(vv);
    return r;
  }

  function renderList() {
    var listEl = el.cardList;
    listEl.innerHTML = "";
    if (!state.data) { return; }
    var list = filterCompanies();
    state.filteredLen = list.length;
    if (list.length === 0) {
      el.empty.hidden = false;
      el.empty.innerHTML = emptyMsg();
      if (el.loadMore) { el.loadMore.hidden = true; }
      updateFilterTip(0);
      return;
    }
    el.empty.hidden = true;
    var shown = list.slice(0, state.visible);
    var frag = document.createDocumentFragment();
    shown.forEach(function (c) { frag.appendChild(buildCard(c)); });
    listEl.appendChild(frag);
    if (!el.loadMore) {
      var sentinel = document.createElement("div");
      sentinel.id = "loadMore";
      sentinel.className = "load-more";
      sentinel.textContent = "上滑加载更多…";
      listEl.appendChild(sentinel);
      el.loadMore = sentinel;
      setupInfiniteScroll();
    } else {
      listEl.appendChild(el.loadMore);
    }
    el.loadMore.hidden = list.length <= state.visible;
    el.loadMore.textContent = list.length <= state.visible ? "" : "上滑加载更多 · 已显示 " + shown.length + " / " + list.length;
    updateFilterTip(list.length);
  }

  function updateFilterTip(total) {
    if (state.tab === "favorites") {
      el.filterTip.textContent = "已收藏 " + favs.length + " 家";
      return;
    }
    var parts = [];
    if (state.only26) { parts.push("仅26届"); }
    if (state.industry) { parts.push(state.industry); }
    if (state.companyType) { parts.push(state.companyType); }
    if (state.location) { parts.push(state.location); }
    if (state.year) { parts.push(state.year + "届"); }
    if (state.search) { parts.push("“" + state.search + "”"); }
    el.filterTip.textContent = parts.length ? parts.join(" · ") + " · " + total + " 家" : "共 " + total + " 家";
  }

  function emptyMsg() {
    if (state.tab === "favorites") {
      return '<div class="empty-icon">♡</div><div>暂无收藏</div><div class="empty-sub">点击公司卡片右上角 ♥ 即可加入收藏</div>';
    }
    if (state.tab === "today_new") {
      return '<div class="empty-icon">🌱</div><div>今日暂无新增</div><div class="empty-sub">数据更新于 ' +
        escHtml((state.data && state.data.meta && state.data.meta.generated_at) || "--") + ' · 每日自动刷新</div>';
    }
    return '<div class="empty-icon">🔍</div><div>暂无符合条件的公司</div><div class="empty-sub">试试调整筛选条件</div>';
  }

  function setupInfiniteScroll() {
    if (io || !("IntersectionObserver" in window)) { return; }
    io = new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting && state.filteredLen > state.visible) {
        state.visible += RENDER_BATCH;
        renderList();
      }
    }, { rootMargin: "600px" });
    io.observe(el.loadMore);
  }

  // ---------- 详情 ----------
  function showDetail(c) {
    var body = el.detailBody;
    body.innerHTML = "";
    el.detailActions.innerHTML = "";
    el.detailActions.appendChild(makeFavBtn(c));

    // 名称卡
    var headCard = document.createElement("div");
    headCard.className = "detail-card detail-hero";
    var nameRow = document.createElement("div");
    nameRow.className = "detail-name";
    if (c.is_26) {
      var dot = document.createElement("span");
      dot.className = "dot26"; dot.title = "26届可投";
      nameRow.appendChild(dot);
    }
    var nm = document.createElement("span");
    nm.textContent = c.name;
    nameRow.appendChild(nm);
    headCard.appendChild(nameRow);

    var sub = document.createElement("div");
    sub.className = "detail-sub";
    if (c.recruit_type) {
      var rb = document.createElement("span");
      rb.className = "badge badge-recruit"; rb.textContent = c.recruit_type;
      sub.appendChild(rb);
    }
    if (c.industry && c.industry !== "其他") {
      var ib = document.createElement("span");
      ib.className = "badge badge-type"; ib.textContent = c.industry;
      sub.appendChild(ib);
    }
    if (c.company_type) {
      var tb = document.createElement("span");
      tb.className = "badge badge-type"; tb.textContent = c.company_type;
      sub.appendChild(tb);
    }
    if (c.is_26) {
      var b26 = document.createElement("span");
      b26.className = "badge badge-26"; b26.textContent = "26届可投";
      sub.appendChild(b26);
    }
    headCard.appendChild(sub);
    body.appendChild(headCard);

    // 详情字段卡
    var info = document.createElement("div");
    info.className = "detail-card";
    info.appendChild(field("目标届数", c.target_years || "--", c.is_26));
    info.appendChild(field("状态", c.status === "today_new" ? "今日新增" : "正在进行", false));
    info.appendChild(field("更新日期", c.post_date || "--", false));
    info.appendChild(field("投递截止", c.deadline || "--", false));
    if (c.industry && c.industry !== "其他") info.appendChild(field("行业", c.industry, false));
    if (c.company_type) info.appendChild(field("公司类型", c.company_type, false));
    if (c.location) info.appendChild(field("工作地点", c.location, false));
    if (c.title) info.appendChild(field("招聘主题", c.title, false));
    if (c.positions && c.positions.length) info.appendChild(field("招聘岗位", c.positions.join("、"), false));
    if (c.majors && c.majors.length) info.appendChild(field("专业要求", c.majors.join("、"), false));
    if (!(c.positions && c.positions.length) && c.position) info.appendChild(field("招聘岗位", c.position, false));
    if (c.scale) info.appendChild(field("招聘规模", c.scale, false));
    body.appendChild(info);

    // 链接按钮
    var official = c.apply_url || c.notice_url;
    if (official) {
      var btn = document.createElement("button");
      btn.className = "btn-link";
      btn.textContent = c.apply_url ? "前往官方招聘链接" : "查看招聘公告";
      btn.addEventListener("click", function () {
        window.open(official, "_blank", "noopener");
      });
      body.appendChild(btn);
    }
    if (c.notice_url && c.notice_url !== official) {
      var btn2 = document.createElement("button");
      btn2.className = "btn-link secondary";
      btn2.textContent = "查看招聘公告";
      btn2.addEventListener("click", function () {
        window.open(c.notice_url, "_blank", "noopener");
      });
      body.appendChild(btn2);
    }

    el.listView.hidden = true;
    el.detailView.hidden = false;
    el.detailView.scrollTop = 0;
  }

  function field(k, v, highlight) {
    var f = document.createElement("div");
    f.className = "detail-field";
    var kk = document.createElement("span");
    kk.className = "k"; kk.textContent = k;
    var vv = document.createElement("span");
    vv.className = "v" + (highlight ? " highlight26" : "");
    if (highlight) {
      vv.innerHTML = escHtml(v).replace(/26\s*届/g, '<span class="highlight26">26届</span>');
    } else {
      vv.textContent = v;
    }
    f.appendChild(kk); f.appendChild(vv);
    return f;
  }

  function closeDetail() {
    el.detailView.hidden = true;
    el.listView.hidden = false;
  }

  // ---------- 通知 ----------
  function checkNotice(meta) {
    var today = meta.today || todayStr();
    var n = meta.today_new || 0;
    var n26 = meta.today_new_26 || 0;
    if (n <= 0) { return; }
    var msg = "今日新增 " + n + " 家公司，其中 26 届可投 " + n26 + " 家";
    var shown = localStorage.getItem(LS_NOTIFIED);
    if (shown !== today) {
      el.noticeText.textContent = msg;
      el.noticeBanner.hidden = false;
      localStorage.setItem(LS_NOTIFIED, today);
      try {
        if ("Notification" in window && Notification.permission === "granted") {
          new Notification("秋招每日通", { body: msg });
        } else if ("Notification" in window && Notification.permission === "default") {
          Notification.requestPermission();
        }
      } catch (e) {}
    }
  }

  // ---------- 事件绑定 ----------
  function bindEvents() {
    el.switch26.addEventListener("change", function () {
      state.only26 = el.switch26.checked;
      try { localStorage.setItem(LS_26, state.only26 ? "1" : "0"); } catch (e) {}
      resetView();
      renderList();
    });

    var searchTimer;
    el.searchInput.addEventListener("input", function () {
      clearTimeout(searchTimer);
      var v = el.searchInput.value.trim();
      searchTimer = setTimeout(function () {
        state.search = v;
        resetView();
        renderList();
      }, 200);
    });

    el.industrySelect.addEventListener("change", function () {
      state.industry = el.industrySelect.value;
      resetView(); renderList();
    });
    el.typeSelect.addEventListener("change", function () {
      state.companyType = el.typeSelect.value;
      resetView(); renderList();
    });
    el.locSelect.addEventListener("change", function () {
      state.location = el.locSelect.value;
      resetView(); renderList();
    });
    el.yearSelect.addEventListener("change", function () {
      state.year = el.yearSelect.value;
      resetView(); renderList();
    });

    document.querySelectorAll(".tab").forEach(function (t) {
      t.addEventListener("click", function () {
        document.querySelectorAll(".tab").forEach(function (x) { x.classList.remove("active"); });
        t.classList.add("active");
        state.tab = t.getAttribute("data-tab");
        resetView();
        renderList();
      });
    });

    el.backBtn.addEventListener("click", closeDetail);
    el.noticeClose.addEventListener("click", function () { el.noticeBanner.hidden = true; });

    el.refreshBtn.addEventListener("click", function () {
      if (refreshState.busy) { return; }
      refreshState.busy = true;
      el.refreshBtn.classList.add("spin");
      toast("正在获取最新数据…");
      fetch(baseUrl() + "/refresh", { method: "POST", cache: "no-store" })
        .then(function (r) {
          if (!r.ok) { throw new Error("no-refresh-endpoint"); }
          return r.json();
        })
        .then(function (res) {
          if (res.status === "started" || res.status === "busy") {
            toast("正在抓取今日最新数据（约 1~2 分钟）…");
            pollRefresh();
          } else {
            throw new Error("bad status");
          }
        })
        .catch(function () {
          // 静态托管（GitHub Pages / CDN）没有 /refresh 接口：
          // 退回"重新拉取服务器最新数据"（每日 21:00 自动更新）
          refreshState.busy = false;
          el.refreshBtn.classList.remove("spin");
          loadData(true).then(function () {
            var gen = (state.data && state.data.meta && state.data.meta.generated_at) || "";
            toast(gen ? "已拉取最新数据 · 更新于 " + gen : "已重新加载数据");
          });
        });
    });

    window.addEventListener("popstate", function () {
      if (!el.detailView.hidden) { closeDetail(); }
    });

    if (el.settingsBtn) { el.settingsBtn.addEventListener("click", openSettings); }
    if (el.settingsClose) { el.settingsClose.addEventListener("click", closeSettings); }
    if (el.settingsModal) {
      el.settingsModal.addEventListener("click", function (e) {
        if (e.target === el.settingsModal) { closeSettings(); }
      });
    }
    if (el.settingsSave) {
      el.settingsSave.addEventListener("click", function () {
        saveServer(el.settingsInput.value);
      });
    }
    if (el.settingsClear) {
      el.settingsClear.addEventListener("click", function () {
        el.settingsInput.value = "";
        saveServer("");
      });
    }
  }

  function resetView() {
    state.visible = RENDER_BATCH;
    if (el.listView) { el.listView.scrollTop = 0; }
  }

  // ---------- 初始化 ----------
  function init() {
    el.todayLabel = $("todayLabel");
    el.refreshBtn = $("refreshBtn");
    el.switch26 = $("switch26");
    el.searchInput = $("searchInput");
    el.industrySelect = $("industrySelect");
    el.typeSelect = $("typeSelect");
    el.locSelect = $("locSelect");
    el.yearSelect = $("yearSelect");
    el.filterTip = $("filterTip");
    el.noticeBanner = $("noticeBanner");
    el.noticeText = $("noticeText");
    el.noticeClose = $("noticeClose");
    el.countToday = $("countToday");
    el.countOngoing = $("countOngoing");
    el.countFav = $("countFav");
    el.detailActions = $("detailActions");
    el.listView = $("listView");
    el.detailView = $("detailView");
    el.detailBody = $("detailBody");
    el.backBtn = $("backBtn");
    el.cardList = $("cardList");
    el.loading = $("loading");
    el.empty = $("empty");
    el.toast = $("toast");
    el.settingsBtn = $("settingsBtn");
    el.settingsModal = $("settingsModal");
    el.settingsInput = $("settingsInput");
    el.settingsStatus = $("settingsStatus");
    el.settingsClose = $("settingsClose");
    el.settingsSave = $("settingsSave");
    el.settingsClear = $("settingsClear");

    try {
      state.only26 = localStorage.getItem(LS_26) === "1";
    } catch (e) {}
    el.switch26.checked = state.only26;
    favLoad();
    updateFavCount();

    bindEvents();
    loadData(false);

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("sw.js").catch(function () {});
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
