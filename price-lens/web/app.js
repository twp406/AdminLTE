/* ============ 价探 PriceLens · 前端交互 ============ */
(() => {
  "use strict";

  const PLATFORM = {
    jd: { name: "京东", color: "#ff5f6d" },
    tb: { name: "淘宝", color: "#ffa246" },
    pdd: { name: "拼多多", color: "#ff4fa3" },
  };

  const PIPELINE_STEPS = ["采集", "清洗", "去重", "建模", "图表"];
  const BADGES = new Set(["性价比首选", "全场最低", "销量冠军", "口碑之选"]);

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const state = {
    data: null,
    sort: "price",
    trendMode: "platform",
    loading: false,
    timer: null,
    chartMeta: null,
  };

  const el = {
    form: $("#searchForm"),
    keyword: $("#keyword"),
    runBtn: $("#runBtn"),
    sortSelect: $("#sortSelect"),
    sourceSelect: $("#sourceSelect"),
    pipeline: $("#pipeline"),
    status: $("#statusText"),
    modePill: $("#modePill"),
    kpiLow: $("#kpiLow"),
    kpiLowSub: $("#kpiLowSub"),
    kpiMedian: $("#kpiMedian"),
    kpiMedianSub: $("#kpiMedianSub"),
    kpiCount: $("#kpiCount"),
    kpiCountSub: $("#kpiCountSub"),
    kpiClean: $("#kpiClean"),
    kpiCleanSub: $("#kpiCleanSub"),
    picks: $("#picks"),
    rows: $("#productRows"),
    tableSub: $("#tableSub"),
    tableFoot: $("#tableFoot"),
    tableEmpty: $("#tableEmpty"),
    platformBars: $("#platformBars"),
    runLog: $("#runLog"),
    runMeta: $("#runMeta"),
    trend: $("#trend"),
    trendSub: $("#trendSub"),
    chartWrap: $("#chartWrap"),
    chart: $("#trendChart"),
    chartTip: $("#chartTip"),
    chartLegend: $("#chartLegend"),
    chartNote: $("#chartNote"),
    deltaChip: $("#deltaChip"),
    funnel: $("#funnel"),
    rawSample: $("#rawSample"),
    cleanSample: $("#cleanSample"),
    qualityBadge: $("#qualityBadge"),
    exportCsv: $("#exportCsv"),
    exportMd: $("#exportMd"),
    toast: $("#toast"),
  };

  /* ---------- 工具 ---------- */
  const escapeHtml = (value) =>
    String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  const round = (value, digits = 0) => Number(value).toFixed(digits);

  function fmtPrice(value) {
    const number = Number(value) || 0;
    const needsDecimals = Math.abs(number - Math.round(number)) > 0.005;
    return `¥${number.toLocaleString("zh-CN", {
      minimumFractionDigits: needsDecimals ? 2 : 0,
      maximumFractionDigits: 2,
    })}`;
  }

  function fmtSales(value) {
    const number = Number(value) || 0;
    return number >= 10000 ? `${(number / 10000).toFixed(1)}万` : number.toLocaleString("zh-CN");
  }

  function highlightJson(value) {
    const escaped = escapeHtml(JSON.stringify(value, null, 2));
    return escaped.replace(
      /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?/g,
      (match) => {
        let cls = "n";
        if (/^"/.test(match)) cls = /:\s*$/.test(match) ? "k" : "s";
        else if (/true|false|null/.test(match)) cls = "b";
        return `<span class="${cls}">${match}</span>`;
      }
    );
  }

  function animateNumber(target, value, format = (v) => Math.round(v).toLocaleString("zh-CN"), duration = 650) {
    const start = performance.now();
    const from = 0;
    const to = Number(value) || 0;
    function frame(now) {
      const progress = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      target.textContent = format(from + (to - from) * eased);
      if (progress < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  let toastTimer = null;
  function toast(message, type = "info") {
    el.toast.textContent = message;
    el.toast.classList.toggle("error", type === "error");
    el.toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.toast.classList.remove("show"), 4200);
  }

  function setActiveSort(sort) {
    $$(".sort-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.sort === sort));
    $$(".sort-tab").forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.sort === sort)));
    el.sortSelect.value = sort;
  }

  function setLoading(loading) {
    state.loading = loading;
    el.runBtn.disabled = loading;
    el.runBtn.classList.toggle("loading", loading);
    $(".btn-label", el.runBtn).textContent = loading ? "运行中" : "开始采集";
  }

  /* ---------- 流水线动画 ---------- */
  function buildPipeline() {
    el.pipeline.innerHTML = PIPELINE_STEPS.map(
      (step) => '<span class="pipe-step"><span class="dot"></span>' + step + "</span>"
    ).join("");
  }

  function playPipeline() {
    buildPipeline();
    const steps = $$(".pipe-step");
    let index = 0;
    steps[0].classList.add("active");
    clearInterval(state.timer);
    state.timer = setInterval(() => {
      if (index >= steps.length) return;
      steps[index].classList.remove("active");
      steps[index].classList.add("done");
      index += 1;
      if (steps[index]) steps[index].classList.add("active");
    }, 230);
  }

  function finishPipeline(ok = true) {
    clearInterval(state.timer);
    $$(".pipe-step").forEach((step) => {
      step.classList.remove("active");
      step.classList.add("done");
      if (!ok) step.classList.remove("done");
    });
  }

  /* ---------- 搜索 ---------- */
  async function runSearch(keyword) {
    if (state.loading) return;
    const query = String(keyword ?? el.keyword.value).trim();
    if (!query) {
      toast("请输入搜索关键词");
      el.keyword.focus();
      return;
    }
    const platforms = $$('input[name="platform"]:checked').map((input) => input.value);
    if (!platforms.length) {
      toast("请至少选择一个采集平台", "error");
      return;
    }
    if (location.protocol === "file:") {
      loadSample("当前为本地文件模式，展示内置示例。运行 python server.py 后可现场采集。");
      return;
    }

    el.keyword.value = query;
    state.sort = el.sortSelect.value;
    setActiveSort(state.sort);
    setLoading(true);
    el.status.textContent = "正在执行采集脚本…";
    playPipeline();

    const params = new URLSearchParams({
      keyword: query,
      platforms: platforms.join(","),
      source: el.sourceSelect.value,
      sort: state.sort,
      limit: "60",
    });

    try {
      const response = await fetch(`/api/search?${params.toString()}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "采集失败");
      state.data = payload;
      state.trendMode = "platform";
      $$(".trend-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.mode === "platform"));
      renderAll();
      finishPipeline(true);
      const cleaned = payload.clean_stats.cleaned;
      el.status.textContent = `${payload.clean_stats.raw} 条 → ${cleaned} 条 · ${payload.elapsed_ms} ms · ${timeOf(payload.generated_at)}`;
      if (payload.warnings?.length) toast(payload.warnings[0], "error");
    } catch (error) {
      finishPipeline(false);
      el.status.textContent = "运行失败";
      if (window.SAMPLE_DATA) {
        loadSample("接口不可用，已载入内置示例数据。请检查 python server.py 是否启动。");
      } else {
        toast(error.message || "采集失败，请重试", "error");
      }
    } finally {
      setLoading(false);
    }
  }

  function loadSample(message) {
    if (!window.SAMPLE_DATA) {
      toast(message || "未找到内置示例数据", "error");
      return;
    }
    state.data = window.SAMPLE_DATA;
    state.sort = el.sortSelect.value;
    renderAll();
    finishPipeline(true);
    el.status.textContent = "内置示例 · 只读 · 运行 python server.py 现场采集";
    toast(message || "已载入内置示例数据");
  }

  function timeOf(iso) {
    try {
      return new Date(iso).toLocaleTimeString("zh-CN", { hour12: false });
    } catch {
      return "";
    }
  }

  /* ---------- 渲染总入口 ---------- */
  function renderAll() {
    renderKpis();
    renderPicks();
    renderTable();
    renderPlatforms();
    renderLog();
    renderTrend();
    renderQuality();
    renderExports();
    updateModePill();
  }

  function updateModePill() {
    if (!state.data) return;
    const live = state.data.source === "live";
    el.modePill.classList.toggle("live", live);
    $("span", el.modePill).textContent = live ? "实时采集 · 本次结果" : "离线演示 · 可复现";
  }

  function renderKpis() {
    const { stats, clean_stats: clean, platforms, products } = state.data;
    animateNumber(el.kpiLow, stats.min, (v) => fmtPrice(Math.round(v)));
    el.kpiLowSub.textContent = `${stats.cheapest.platform_name} · ${stats.cheapest.title}`;
    el.kpiLowSub.title = stats.cheapest.title;

    animateNumber(el.kpiMedian, stats.median, (v) => fmtPrice(Math.round(v)));
    el.kpiMedianSub.textContent = `均价 ${fmtPrice(stats.avg)} · 价差 ${stats.spread_pct}%`;

    animateNumber(el.kpiCount, stats.count);
    el.kpiCountSub.textContent = `覆盖 ${platforms.length} 个平台 · 入榜 ${products.length} 条`;

    const dirt = clean.duplicates + clean.outliers + clean.invalid;
    animateNumber(el.kpiClean, dirt, (v) => `${Math.round(v)} 条`);
    el.kpiCleanSub.textContent = `去重 ${clean.duplicates} · 异常 ${clean.outliers} · 无效 ${clean.invalid}`;
  }

  function renderPicks() {
    const picks = (state.data.recommendations || []).slice(0, 4);
    el.picks.innerHTML = picks
      .map((pick, index) => {
        const product = pick.product;
        const meta = [
          `月销 ${fmtSales(product.sales)}`,
          `评分 ${product.rating ?? "-"}`,
          `性价比 ${product.value_score}`,
        ];
        return `
          <article class="pick ${escapeHtml(pick.type)}" style="animation-delay:${index * 45}ms">
            <a class="pick-link" href="${escapeHtml(product.url)}" target="_blank" rel="noopener" aria-label="打开商品">↗</a>
            <span class="pick-badge">${escapeHtml(pick.badge)}</span>
            <div class="pick-title" title="${escapeHtml(product.title)}">${escapeHtml(product.title)}</div>
            <div class="pick-price">${fmtPrice(product.price)}<small>${escapeHtml(product.platform_name)}</small></div>
            <div class="pick-meta">${meta.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>
            <div class="pick-reason">${escapeHtml(pick.reason)}</div>
          </article>`;
      })
      .join("");
  }

  function sortedProducts() {
    const items = [...state.data.products];
    const comparators = {
      price: (a, b) => a.price - b.price,
      value: (a, b) => b.value_score - a.value_score,
      sales: (a, b) => b.sales - a.sales,
      rating: (a, b) => (b.rating || 0) - (a.rating || 0),
    };
    return items.sort(comparators[state.sort] || comparators.price);
  }

  function renderTable() {
    if (!state.data) return;
    const products = sortedProducts();
    const bestId = state.data.stats.best_value.id;

    el.rows.innerHTML = products
      .map((product, index) => {
        const tags = (product.tags || []).slice(0, 3);
        const tagHtml = tags.length
          ? tags
              .map((tag) => {
                const cls = tag === "性价比首选" ? "tag best" : BADGES.has(tag) ? "tag hot" : "tag";
                return `<span class="${cls}">${escapeHtml(tag)}</span>`;
              })
              .join("")
          : '<span class="tag">—</span>';
        const gap = product.price_gap_pct || 0;
        const gapLabel = gap <= 0 ? `低 ${Math.abs(gap).toFixed(0)}%` : `高 ${gap.toFixed(0)}%`;
        const ratingWidth = Math.max(0, Math.min(100, ((product.rating || 0) / 5) * 100));
        const isBest = product.id === bestId;
        return `
          <tr class="${isBest ? "row-best" : ""}" style="--i:${index}">
            <td><span class="rank-num">${String(index + 1).padStart(2, "0")}</span></td>
            <td>
              <a class="prod-link" href="${escapeHtml(product.url)}" target="_blank" rel="noopener" title="${escapeHtml(product.title)}">
                <div class="prod-title">${escapeHtml(product.title)}</div>
                <div class="prod-sub">
                  <span class="chip ${escapeHtml(product.platform)}">${escapeHtml(product.platform_name)}</span>
                  <span class="prod-shop">${escapeHtml(product.shop)}</span>
                </div>
              </a>
            </td>
            <td class="cell-price">
              <strong>${fmtPrice(product.price)}</strong>
              ${product.original_price ? `<span class="price-orig">${fmtPrice(product.original_price)}</span>` : ""}
              <span class="gap ${gap <= 0 ? "down" : "up"}">${gapLabel}</span>
            </td>
            <td class="cell-sales">${fmtSales(product.sales)}</td>
            <td class="cell-rating">
              <span class="rating-bar"><i style="width:${ratingWidth}%"></i></span>
              <span class="rating-num">${product.rating ?? "-"}</span>
            </td>
            <td class="cell-score ${product.value_score >= 80 ? "high" : ""}">
              <span class="score-num">${product.value_score}</span>
              <span class="score-bar"><i style="width:${Math.min(100, product.value_score)}%"></i></span>
            </td>
            <td><div class="cell-tags">${tagHtml}</div></td>
            <td class="cell-link">
              <a class="link-btn" href="${escapeHtml(product.url)}" target="_blank" rel="noopener" aria-label="查看商品">↗</a>
            </td>
          </tr>`;
      })
      .join("");

    el.tableEmpty.hidden = products.length > 0;
    const sortNames = { price: "价格从低到高", value: "性价比优先", sales: "销量优先", rating: "评分优先" };
    el.tableSub.textContent = `${sortNames[state.sort]} · 共 ${products.length} 条`;
    el.tableFoot.innerHTML = `
      <span>清洗后共 ${state.data.clean_stats.cleaned} 条 · 已加载 ${products.length} 条，表内滚动查看</span>
      <span>${escapeHtml(state.data.source_label)} · ${escapeHtml(timeOf(state.data.generated_at))}</span>`;
  }

  function renderPlatforms() {
    const rows = state.data.platforms || [];
    if (!rows.length) {
      el.platformBars.innerHTML = "";
      return;
    }
    const globalMin = Math.min(...rows.map((row) => row.min));
    const globalMax = Math.max(...rows.map((row) => row.max));
    const span = Math.max(1, globalMax - globalMin);

    el.platformBars.innerHTML = rows
      .map((row) => {
        const meta = PLATFORM[row.code] || { color: "#8c98a8" };
        const left = Math.max(0, ((row.min - globalMin) / span) * 100);
        const width = Math.max(3, ((row.max - row.min) / span) * 100);
        const mark = Math.max(0, Math.min(100, ((row.median - globalMin) / span) * 100));
        return `
          <div class="pbar" style="--pc:${meta.color}">
            <div class="pbar-head">
              <span class="chip ${escapeHtml(row.code)}">${escapeHtml(row.name)}</span>
              <span class="count">${row.count} 件</span>
              <span class="median">中位 ${fmtPrice(row.median)}</span>
            </div>
            <div class="pbar-track">
              <span class="pbar-fill" style="left:${left}%;width:${width}%"></span>
              <span class="pbar-mark" style="left:${mark}%"></span>
            </div>
            <div class="pbar-foot"><span>${fmtPrice(row.min)}</span><span>${fmtPrice(row.max)}</span></div>
          </div>`;
      })
      .join("");
  }

  function renderLog() {
    const entries = state.data.log || [];
    el.runLog.innerHTML = entries
      .map(
        (entry) => `
          <div class="log-item ${entry.status === "warn" ? "warn" : ""}">
            <span class="log-dot"></span>
            <div>
              <div class="log-step">${escapeHtml(entry.step)}</div>
              <div class="log-detail">${escapeHtml(entry.detail)}</div>
            </div>
            <span class="log-ms">${entry.ms ? entry.ms + "ms" : ""}</span>
          </div>`
      )
      .join("");
    el.runLog.scrollTop = 0;

    const sourceFlag = state.data.source === "demo" ? "--source demo" : "--source live";
    el.runMeta.innerHTML = `<b>$</b> python cli.py search "${escapeHtml(state.data.keyword)}" ${sourceFlag}<br>
      API /api/search · ${state.data.clean_stats.raw} raw → ${state.data.clean_stats.cleaned} cleaned · ${state.data.elapsed_ms} ms`;
  }

  /* ---------- 趋势图 ---------- */
  function trendSeries() {
    const trend = state.data.trend;
    if (!trend) return [];
    if (state.trendMode === "product" && trend.product_series) {
      return [
        {
          name: "推荐单品",
          code: trend.product_series.platform,
          color: "#ffb454",
          data: trend.product_series.data,
          delta: trend.product_series.delta_pct,
          price: trend.product_series.price,
        },
      ];
    }
    return (trend.platform_series || []).map((series) => ({
      name: series.name,
      code: series.code,
      color: (PLATFORM[series.code] || {}).color || "#8c98a8",
      data: series.data,
      delta: series.delta_pct,
      median: series.median,
    }));
  }

  function renderTrend() {
    const trend = state.data.trend;
    if (!trend) return;
    const chartWrap = el.chartWrap;
    const W = Math.max(320, Math.round(chartWrap.clientWidth || 900));
    const H = W < 620 ? 250 : 300;
    const PAD = { l: W < 620 ? 46 : 56, r: 24, t: 22, b: 34 };
    const series = trendSeries();
    const labels = trend.labels;
    if (!series.length) {
      el.chart.innerHTML = "";
      el.chartLegend.innerHTML = "";
      return;
    }

    const values = series.flatMap((item) => item.data);
    let min = Math.min(...values);
    let max = Math.max(...values);
    if (min === max) {
      min = min * 0.92 || 0;
      max = max * 1.08 || 10;
    }
    const padding = (max - min) * 0.18;
    const yMin = Math.max(0, min - padding);
    const yMax = max + padding;
    const plotW = W - PAD.l - PAD.r;
    const plotH = H - PAD.t - PAD.b;
    const x = (index) => PAD.l + (labels.length <= 1 ? plotW / 2 : (index / (labels.length - 1)) * plotW);
    const y = (value) => PAD.t + (1 - (value - yMin) / (yMax - yMin)) * plotH;

    const smoothPath = (points) => {
      if (!points.length) return "";
      let d = `M${points[0][0]},${points[0][1]}`;
      for (let i = 0; i < points.length - 1; i += 1) {
        const p0 = points[i - 1] || points[i];
        const p1 = points[i];
        const p2 = points[i + 1];
        const p3 = points[i + 2] || p2;
        const c1x = p1[0] + (p2[0] - p0[0]) / 6;
        const c1y = p1[1] + (p2[1] - p0[1]) / 6;
        const c2x = p2[0] - (p3[0] - p1[0]) / 6;
        const c2y = p2[1] - (p3[1] - p1[1]) / 6;
        d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
      }
      return d;
    };

    const gridCount = 4;
    let grid = "";
    for (let i = 0; i <= gridCount; i += 1) {
      const value = yMax - ((yMax - yMin) / gridCount) * i;
      const yy = y(value);
      grid += `<line class="grid-line" x1="${PAD.l}" y1="${yy.toFixed(1)}" x2="${W - PAD.r}" y2="${yy.toFixed(1)}" stroke="rgba(255,255,255,0.055)" stroke-dasharray="3 5"/>`;
      grid += `<text x="${PAD.l - 9}" y="${(yy + 3.5).toFixed(1)}" text-anchor="end" fill="#5f6b7b" font-size="10" font-family="SFMono-Regular, Consolas, monospace">¥${Math.round(value).toLocaleString("zh-CN")}</text>`;
    }

    const step = Math.max(1, Math.ceil(labels.length / 6));
    let xLabels = "";
    labels.forEach((label, index) => {
      if (index % step !== 0 && index !== labels.length - 1) return;
      xLabels += `<text x="${x(index).toFixed(1)}" y="${H - 12}" text-anchor="middle" fill="#5f6b7b" font-size="9.5" font-family="SFMono-Regular, Consolas, monospace">${escapeHtml(label)}</text>`;
    });

    let defs = "";
    let paths = "";
    let hoverDots = "";
    series.forEach((item, index) => {
      const points = item.data.map((value, i) => [x(i), y(value)]);
      const line = smoothPath(points);
      const areaId = `areaGrad${index}`;
      if (series.length === 1) {
        defs += `<linearGradient id="${areaId}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${item.color}" stop-opacity="0.22"/>
          <stop offset="100%" stop-color="${item.color}" stop-opacity="0"/>
        </linearGradient>`;
        paths += `<path d="${line} L${points[points.length - 1][0].toFixed(1)},${(H - PAD.b).toFixed(1)} L${points[0][0].toFixed(1)},${(H - PAD.b).toFixed(1)} Z" fill="url(#${areaId})"/>`;
      }
      paths += `<path d="${line}" fill="none" stroke="${item.color}" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" pathLength="1" style="stroke-dasharray:1;stroke-dashoffset:1;animation:drawLine 1s cubic-bezier(.3,.7,.3,1) forwards"/>`;
      const last = points[points.length - 1];
      paths += `<circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="3.4" fill="${item.color}" stroke="#0b1017" stroke-width="2"/>`;
      hoverDots += `<circle data-hover-dot="${index}" cx="0" cy="0" r="3.6" fill="${item.color}" stroke="#0b1017" stroke-width="2" opacity="0"/>`;
    });

    el.chart.setAttribute("viewBox", `0 0 ${W} ${H}`);
    el.chart.innerHTML = `
      <defs>${defs}</defs>
      ${grid}
      <line x1="${PAD.l}" y1="${H - PAD.b}" x2="${W - PAD.r}" y2="${H - PAD.b}" stroke="rgba(255,255,255,0.1)"/>
      ${xLabels}
      ${paths}
      <g id="hoverLayer">
        <line id="hoverLine" x1="0" y1="${PAD.t}" x2="0" y2="${H - PAD.b}" stroke="rgba(255,255,255,0.28)" stroke-dasharray="3 4" opacity="0"/>
        ${hoverDots}
      </g>`;

    const labelsForTip = labels;
    state.chartMeta = { W, H, PAD, x, y, series, labels: labelsForTip };
    bindChartHover();

    // 图例
    el.chartLegend.innerHTML = series
      .map((item) => {
        const delta = Number(item.delta || 0);
        const tone = delta <= 0 ? "var(--teal)" : "var(--red)";
        return `<span class="legend-item"><i style="background:${item.color}"></i>${escapeHtml(item.name)}
          <em style="color:${tone}">${delta > 0 ? "+" : ""}${delta}%</em></span>`;
      })
      .join("");

    const headline = state.trendMode === "product" ? "推荐单品" : "平台均价";
    const delta = state.trendMode === "product"
      ? trend.product_series?.delta_pct ?? 0
      : trend.delta_pct;
    const down = delta <= 0;
    el.deltaChip.textContent = `30 天 ${down ? "↓" : "↑"} ${Math.abs(delta)}%`;
    el.deltaChip.className = `delta-chip ${down ? "down" : "up"}`;
    el.trendSub.textContent = state.trendMode === "product"
      ? `推荐单品价格走势 · ${headline}`
      : "近 30 天平台均价走势";
    el.chartNote.textContent =
      trend.basis === "demo"
        ? "演示模式：历史曲线由关键词种子确定性生成，可重复复现；同一商品每日快照的接入方式见 README。"
        : "实时模式：当前按抓取价格回推参考曲线；持续运行后可按日快照累积真实价格历史。";
  }

  function bindChartHover() {
    if (el.chart.dataset.hoverBound) return;
    el.chart.dataset.hoverBound = "1";

    el.chart.addEventListener("mousemove", (event) => {
      const meta = state.chartMeta;
      if (!meta) return;
      const rect = el.chart.getBoundingClientRect();
      const scaleX = meta.W / rect.width;
      const svgX = (event.clientX - rect.left) * scaleX;
      const ratio = (svgX - meta.PAD.l) / (meta.W - meta.PAD.l - meta.PAD.r);
      const index = Math.max(0, Math.min(meta.labels.length - 1, Math.round(ratio * (meta.labels.length - 1))));
      const px = meta.x(index);

      const hoverLine = $("#hoverLine", el.chart);
      if (hoverLine) {
        hoverLine.setAttribute("x1", px.toFixed(1));
        hoverLine.setAttribute("x2", px.toFixed(1));
        hoverLine.setAttribute("opacity", "1");
      }

      const rows = meta.series
        .map((item) => {
          const value = item.data[index];
          return `<div class="tip-row"><i style="background:${item.color}"></i>${escapeHtml(item.name)} <b>${fmtPrice(value)}</b></div>`;
        })
        .join("");

      meta.series.forEach((item, seriesIndex) => {
        const dot = el.chart.querySelector(`[data-hover-dot="${seriesIndex}"]`);
        if (dot) {
          dot.setAttribute("cx", px.toFixed(1));
          dot.setAttribute("cy", meta.y(item.data[index]).toFixed(1));
          dot.setAttribute("opacity", "1");
        }
      });

      el.chartTip.hidden = false;
      el.chartTip.innerHTML = `<div class="tip-date">${escapeHtml(meta.labels[index])}</div>${rows}`;
      const wrapRect = el.chartWrap.getBoundingClientRect();
      const tipWidth = el.chartTip.offsetWidth || 150;
      const left = Math.max(8, Math.min(wrapRect.width - tipWidth - 8, event.clientX - wrapRect.left + 14));
      const top = Math.max(8, Math.min(wrapRect.height - 96, event.clientY - wrapRect.top - 44));
      el.chartTip.style.left = `${left}px`;
      el.chartTip.style.top = `${top}px`;
    });

    el.chart.addEventListener("mouseleave", () => {
      el.chartTip.hidden = true;
      const hoverLine = $("#hoverLine", el.chart);
      if (hoverLine) hoverLine.setAttribute("opacity", "0");
      $$("[data-hover-dot]", el.chart).forEach((dot) => dot.setAttribute("opacity", "0"));
    });
  }

  /* ---------- 数据质量 ---------- */
  function renderQuality() {
    const data = state.data;
    const clean = data.clean_stats;
    const stages = [
      { value: clean.raw, label: "原始采集" },
      { value: clean.valid, label: "字段有效" },
      { value: clean.cleaned, label: "清洗合并" },
      { value: data.products.length, label: "入榜展示" },
    ];
    el.funnel.innerHTML = stages
      .map(
        (stage, index) => `
          ${index ? '<span class="funnel-arrow">→</span>' : ""}
          <div class="funnel-stage ${index === stages.length - 1 ? "highlight" : ""}">
            <div class="fs-value">${stage.value}</div>
            <div class="fs-label">${stage.label}</div>
          </div>`
      )
      .join("");

    const dirty = clean.duplicates + clean.outliers + clean.invalid;
    el.qualityBadge.textContent = `${dirty} 条脏数据已处理`;
    el.qualityBadge.classList.add("ok");

    const rawSample = (data.raw_sample && data.raw_sample[0]) || {};
    el.rawSample.innerHTML = highlightJson(rawSample);

    const best = data.products.find((product) => product.id === data.stats.best_value.id) || data.products[0];
    if (best) {
      el.cleanSample.innerHTML = highlightJson({
        id: best.id,
        platform: best.platform_name,
        title: best.title,
        price: best.price,
        sales: best.sales,
        rating: best.rating,
        shop: best.shop,
        value_score: best.value_score,
        tags: best.tags,
        url: best.url,
      });
    }
  }

  function renderExports() {
    if (!state.data) return;
    const params = new URLSearchParams({
      keyword: state.data.keyword,
      platforms: (state.data.query.platforms || []).join(","),
      source: state.data.source,
      sort: state.sort,
      limit: "60",
    });
    el.exportCsv.href = `/api/export?${params.toString()}&format=csv`;
    el.exportMd.href = `/api/export?${params.toString()}&format=md`;
  }

  /* ---------- 事件绑定 ---------- */
  function bindEvents() {
    el.form.addEventListener("submit", (event) => {
      event.preventDefault();
      runSearch(el.keyword.value);
    });

    $$(".preset").forEach((button) => {
      button.addEventListener("click", () => {
        el.keyword.value = button.dataset.keyword;
        $$(".preset").forEach((item) => item.classList.toggle("active", item === button));
        runSearch(button.dataset.keyword);
      });
    });

    $$(".sort-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        if (!state.data) return;
        state.sort = tab.dataset.sort;
        setActiveSort(state.sort);
        renderTable();
        renderExports();
      });
    });

    el.sortSelect.addEventListener("change", () => {
      if (!state.data) return;
      state.sort = el.sortSelect.value;
      setActiveSort(state.sort);
      renderTable();
      renderExports();
    });

    $$(".trend-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        if (!state.data) return;
        state.trendMode = tab.dataset.mode;
        $$(".trend-tab").forEach((item) => item.classList.toggle("active", item === tab));
        renderTrend();
      });
    });

    el.sourceSelect.addEventListener("change", () => {
      const live = el.sourceSelect.value === "live";
      el.modePill.classList.toggle("live", live);
      if (!state.data || !state.data.source) return;
      $("span", el.modePill).textContent = live ? "实时采集 · 需网络" : "离线演示 · 可复现";
    });

    let resizeTimer = null;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (state.data) renderTrend();
      }, 180);
    });
  }

  function init() {
    buildPipeline();
    bindEvents();
    setActiveSort(state.sort);
    if (location.protocol === "file:") {
      loadSample("本地文件模式：展示内置示例。运行 python server.py 后可现场采集。");
    } else {
      runSearch(el.keyword.value);
    }
  }

  init();
})();
