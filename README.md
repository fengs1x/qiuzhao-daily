# 秋招每日通 · GitHub 免费部署版

完全免费、不依赖电脑的秋招信息自动更新方案。

## 工作原理

```
GitHub Actions（每天 7:00-21:00 每隔 2 小时自动跑）
        │  运行爬虫（youoffer + hahazhao）
        ▼
crawler/data/*.json   ← 增量累积历史数据
web/data/data.json    ← App 读取的数据
        │  git commit + push
        ▼
GitHub 仓库
   ├── GitHub Pages → PWA（手机浏览器 / iPhone 添加到主屏幕）
   └── jsDelivr CDN  → Android APK 拉取数据（国内访问更友好）
```

## 目录结构

```
crawler/                 爬虫与数据构建（纯 Python 标准库 + lxml）
  ├── common.py          HTTP 请求 / 限速 / 重试
  ├── youoffer.py        Offer派 秋招信息（每日抓前 5 页）
  ├── hahazhao.py        今日校招（每日抓前 5 页，补全行业字段）
  ├── build.py           合并数据 → docs/data/data.json + docs/js/data.js
  ├── update_daily.py    每日更新入口（youoffer --daily + hahazhao --pages 5 + build）
  └── data/*.json        增量累积的源站数据（随仓库保存，构成历史）
docs/                    PWA 前端（App 本体，由 GitHub Pages 托管）
  ├── index.html / app.js / style.css
  ├── data/data.json     App 拉取的数据
  └── js/data.js         离线兜底数据
.github/workflows/crawl.yml   每日定时抓取工作流
```

## 手动触发一次抓取

GitHub 仓库 → **Actions** → **每日抓取秋招数据** → **Run workflow**。

## 手机端使用

- **iPhone / Android 浏览器**：访问 `https://<用户名>.github.io/<仓库名>/`，可"添加到主屏幕"当 App 用。
- **Android APK**：在 App 设置里把服务器地址填为 `https://cdn.jsdelivr.net/gh/<用户名>/<仓库名>@main/docs`，即可通过 CDN 拉取每日最新数据。

> 说明：GitHub 静态托管模式下数据**每天 7:00-21:00 每隔 2 小时自动更新**；App 里的"手动刷新"会重新拉取服务器最新数据（无法像自有后端那样即时触发爬虫，但每 2 小时会自动抓到最新）。

## 注意事项

- 遵守目标站点 robots 协议，抓取间隔 ≥ 5 秒（代码内置）。
- 数据仅个人使用，不涉及商业化传播。
