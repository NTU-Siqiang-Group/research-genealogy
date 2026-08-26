(() => {
  "use strict";

  const GOLD_SEEDS = [
    "The Log-Structured Merge-Tree (LSM-Tree)",
    "Monkey: Optimal Navigable Key-Value Store",
    "Dostoevsky: Better Space-Time Trade-Offs for LSM-Tree Based Key-Value Stores",
    "LSM-bush: A New Leveling Model for LSM-trees",
    "Spooky: Granulating LSM-Tree Compactions Correctly",
    "RusKey: Microsecond-Scale LSM-Tree Searches without Sacrificing Write Throughput",
    "Moose: A Learned LSM-Tree for CPU Efficiency",
    "CAMAL: Optimizing LSM-trees via Active Learning",
    "Grow LSM-tree: Towards practical workload-aware LSM-trees",
    "ArceKV: Efficient LSM-Tree Key-Value Store with Adaptive Compression",
  ];

  const form = document.querySelector("#search-form");
  const seedInput = document.querySelector("#seed-input");
  const submitButton = document.querySelector("#submit-button");
  const message = document.querySelector("#form-message");
  const historyList = document.querySelector("#history-list");
  let hasActiveResults = false;

  function showMessage(text) {
    message.textContent = text;
    message.hidden = !text;
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    }).format(date);
  }

  function statusLabel(state) {
    return ({
      completed: "已完成", running: "生成中", queued: "排队中",
      failed: "失败", interrupted: "已中断",
    })[state] || state || "未知";
  }

  function make(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = content;
    return element;
  }

  function renderResult(result) {
    const status = result.status || {};
    const summary = result.summary || status.summary || {};
    const currentState = status.state || "unknown";
    const card = make("article", "result-card");
    const content = make("div", "result-content");
    content.append(make("h3", "result-title", result.topic || result.seeds?.[0] || "Untitled genealogy"));
    const displayedSeeds = (result.seeds || []).slice(0, 3);
    const seedSuffix = (result.seeds || []).length > 3 ? ` 等 ${result.seeds.length} 篇` : "";
    content.append(make("p", "seed-list", `${displayedSeeds.join(" · ")}${seedSuffix}`));
    const meta = make("div", "result-meta");
    meta.append(make("span", "", `${summary.paper_count ?? "—"} papers`));
    meta.append(make("span", "", `${summary.edge_count ?? "—"} relations`));
    meta.append(make("span", "", `${status.fulltext_retrieved ?? "—"} full texts`));
    meta.append(make("span", "", `创建于 ${formatDate(result.created_at)}`));
    meta.append(make("span", "", `ID · ${result.result_id}`));
    content.append(meta);

    const actions = make("div", "result-actions");
    actions.append(make("span", `status ${currentState}`, statusLabel(currentState)));
    if (currentState === "completed") {
      const link = make("a", "open-result", "打开图谱 →");
      link.href = result.open_url;
      actions.append(link);
    } else {
      const progress = make("div", "progress");
      const track = make("div", "progress-track");
      const fill = make("div", "progress-fill");
      fill.style.width = `${Math.max(0, Math.min(100, status.progress || 0))}%`;
      track.append(fill);
      progress.append(track, make("div", "progress-copy", status.message || statusLabel(currentState)));
      actions.append(progress);
    }
    card.append(content, actions);
    return card;
  }

  async function loadHistory({ quiet = false } = {}) {
    try {
      const response = await fetch("/api/results", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const { results = [] } = await response.json();
      historyList.replaceChildren();
      if (!results.length) {
        historyList.append(make("div", "empty-card", "还没有保存的结果。输入一篇 seed paper 开始第一张谱系。"));
      } else {
        results.forEach((result) => historyList.append(renderResult(result)));
      }
      hasActiveResults = results.some((result) => ["queued", "running"].includes(result.status?.state));
      if (!quiet) showMessage("");
    } catch (error) {
      hasActiveResults = false;
      historyList.replaceChildren(make("div", "empty-card", "无法连接本地搜索服务。请使用 scripts/09_serve_app.py 启动应用。"));
      if (!quiet) showMessage(`本地服务不可用：${error.message}`);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const seeds = seedInput.value.split("\n").map((item) => item.trim()).filter(Boolean);
    if (!seeds.length) return;
    submitButton.disabled = true;
    showMessage("正在创建持久化搜索任务…");
    try {
      const response = await fetch("/api/results", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          seeds,
          topic: document.querySelector("#topic-input").value.trim() || undefined,
          corpus_cap: Number(document.querySelector("#corpus-cap").value),
          fulltext_limit: Number(document.querySelector("#fulltext-limit").value),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      if (payload.reused && payload.result.status?.state === "completed") {
        window.location.assign(payload.result.open_url);
        return;
      }
      showMessage("任务已创建。可以留在这里查看进度，完成后从历史列表打开；关闭页面也不会丢失结果。");
      await loadHistory({ quiet: true });
    } catch (error) {
      showMessage(`无法创建任务：${error.message}`);
    } finally {
      submitButton.disabled = false;
    }
  });

  document.querySelector("#gold-example").addEventListener("click", () => {
    seedInput.value = GOLD_SEEDS.join("\n");
    seedInput.focus();
  });
  document.querySelector("#refresh-history").addEventListener("click", () => loadHistory());

  loadHistory();
  window.setInterval(() => {
    if (hasActiveResults) loadHistory({ quiet: true });
  }, 2500);
})();
