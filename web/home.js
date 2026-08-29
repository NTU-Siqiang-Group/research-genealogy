(() => {
  "use strict";

  const I18n = window.GenealogyI18n;
  const t = I18n.t;

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
    return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(I18n.language === "zh" ? "zh-CN" : "en-US", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    }).format(date);
  }

  function statusLabel(state) {
    const key = `status.${state}`;
    const translated = t(key);
    return translated === key ? state || t("status.unknown") : translated;
  }

  function progressLabel(status) {
    const key = `stage.${status.stage}`;
    const translated = t(key);
    return translated === key ? status.message || statusLabel(status.state) : translated;
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
    content.append(make("h3", "result-title", result.topic || result.seeds?.[0] || t("home.untitled")));
    const displayedSeeds = (result.seeds || []).slice(0, 3);
    const seedSuffix = (result.seeds || []).length > 3 ? ` ${t("home.moreSeeds", { count: result.seeds.length })}` : "";
    content.append(make("p", "seed-list", `${displayedSeeds.join(" · ")}${seedSuffix}`));
    const meta = make("div", "result-meta");
    meta.append(make("span", "", `${summary.paper_count ?? "—"} ${t("unit.papers")}`));
    meta.append(make("span", "", `${summary.edge_count ?? "—"} ${t("unit.relations")}`));
    meta.append(make("span", "", `${status.fulltext_retrieved ?? "—"} ${t("unit.fullTexts")}`));
    meta.append(make("span", "", t("home.createdAt", { date: formatDate(result.created_at) })));
    meta.append(make("span", "", `ID · ${result.result_id}`));
    content.append(meta);

    const actions = make("div", "result-actions");
    actions.append(make("span", `status ${currentState}`, statusLabel(currentState)));
    if (currentState === "completed") {
      const link = make("a", "open-result", t("home.openGraph"));
      link.href = I18n.withLanguage(result.open_url);
      actions.append(link);
    } else {
      const progress = make("div", "progress");
      const track = make("div", "progress-track");
      const fill = make("div", "progress-fill");
      fill.style.width = `${Math.max(0, Math.min(100, status.progress || 0))}%`;
      track.append(fill);
      progress.append(track, make("div", "progress-copy", progressLabel(status)));
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
        historyList.append(make("div", "empty-card", t("home.historyEmpty")));
      } else {
        results.forEach((result) => historyList.append(renderResult(result)));
      }
      hasActiveResults = results.some((result) => ["queued", "running"].includes(result.status?.state));
      if (!quiet) showMessage("");
    } catch (error) {
      hasActiveResults = false;
      historyList.replaceChildren(make("div", "empty-card", t("home.historyUnavailable")));
      if (!quiet) showMessage(t("home.serviceUnavailable", { error: error.message }));
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const seeds = seedInput.value.split("\n").map((item) => item.trim()).filter(Boolean);
    if (!seeds.length) return;
    submitButton.disabled = true;
    showMessage(t("home.creating"));
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
        window.location.assign(I18n.withLanguage(payload.result.open_url));
        return;
      }
      showMessage(t("home.created"));
      await loadHistory({ quiet: true });
    } catch (error) {
      showMessage(t("home.createFailed", { error: error.message }));
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
