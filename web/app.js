(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const LEVEL_RANK = { weak: 0, medium: 1, strong: 2 };
  const LEVEL_LABEL = { weak: "弱关联", medium: "中关联", strong: "强关联" };
  const LEVEL_COLOR = { weak: "#a9b2ad", medium: "#3f78a8", strong: "#c85134" };
  const BRANCH_COLORS = ["#476f5d", "#8c6a3d", "#557b98", "#80688d", "#9a5c51", "#687869"];
  const RELATION_LABELS = {
    ADDRESSES_LIMITATION: "回应前作局限",
    EXPLICIT_BASELINE: "显式 baseline",
    IMPLICIT_BASELINE: "隐式 baseline",
    METHOD_DEPENDENCY: "方法依赖",
    USES_CONCEPT_FROM: "沿用概念",
    EXTENDS: "扩展前作",
    SAME_RESEARCH_GROUP: "同研究组（关键作者重叠）",
    KEY_AUTHOR_OVERLAP: "一作 / 二作 / 通讯作者重叠",
    CITES: "引用",
  };

  const state = {
    payload: null,
    nodes: [],
    edges: [],
    nodeById: new Map(),
    edgeByKey: new Map(),
    landmarkIds: new Set(),
    mode: "lineage",
    levels: new Set(["strong", "medium"]),
    showGroupEdges: false,
    selected: null,
    branchFocus: null,
    transform: { x: 0, y: 0, scale: 1 },
    layout: null,
    dragging: null,
    fitOnNextRender: true,
  };

  const dom = {};
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function edgeKey(edge) {
    return `${edge.source}→${edge.target}`;
  }

  function shortTitle(title, limit = 42) {
    if (!title) return "Untitled paper";
    const prefix = title.includes(":") ? title.split(":", 1)[0] : title;
    const candidate = prefix.length >= 5 && prefix.length <= limit ? prefix : title;
    return candidate.length > limit ? `${candidate.slice(0, limit - 1)}…` : candidate;
  }

  function paperDisplayTitle(node) {
    if (!node) return "Unknown paper";
    const landmark = state.payload?.landmarks?.find((item) => item.paper_id === node.paper_id);
    return landmark?.short_name || node.title;
  }

  function formatPct(value) {
    return Number.isFinite(value) ? `${Math.round(value * 100)}%` : "—";
  }

  function svgEl(tag, attrs = {}, text = null) {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, String(value)));
    if (text !== null) element.textContent = text;
    return element;
  }

  function setupDom() {
    Object.assign(dom, {
      svg: $("#graph-svg"),
      world: $("#world"),
      lanes: $("#lane-layer"),
      edges: $("#edge-layer"),
      nodes: $("#node-layer"),
      viewport: $("#graph-viewport"),
      tooltip: $("#graph-tooltip"),
      inspector: $("#inspector-content"),
      loading: $("#loading-state"),
      search: $("#paper-search"),
      searchResults: $("#search-results"),
      branchList: $("#branch-list"),
      zoomReadout: $("#zoom-readout"),
      hairball: $("#hairball-warning"),
    });
  }

  async function init() {
    setupDom();
    bindControls();
    try {
      const response = await fetch("./data/inspector.json", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.payload = await response.json();
      state.nodes = state.payload.dag.nodes || [];
      state.edges = state.payload.dag.edges || [];
      state.nodeById = new Map(state.nodes.map((node) => [node.paper_id, node]));
      state.edgeByKey = new Map(state.edges.map((edge) => [edgeKey(edge), edge]));
      state.landmarkIds = new Set(
        (state.payload.landmarks || []).filter((item) => item.found).map((item) => item.paper_id),
      );
      populateChrome();
      applyInitialLocation();
      dom.loading.hidden = true;
      renderInspector();
      renderGraph({ fit: true });
    } catch (error) {
      dom.loading.classList.add("error");
      dom.loading.innerHTML = `<div class="error-message"><b>界面数据加载失败</b><br>${escapeHtml(error.message)}<br><br>请先运行 <code>scripts/07_build_inspector_data.py</code>，并通过本地 HTTP server 打开页面。</div>`;
    }
  }

  function populateChrome() {
    const { summary, evaluation } = state.payload;
    $("#topic-title").textContent = state.payload.topic;
    $("#run-pill").textContent = `${summary.paper_count} papers · ${summary.edge_count} relations`;
    $("#strong-count").textContent = summary.association_level_counts.strong;
    $("#medium-count").textContent = summary.association_level_counts.medium;
    $("#weak-count").textContent = summary.association_level_counts.weak;
    $("#group-count").textContent = state.edges.filter((edge) => edge.relation === "SAME_RESEARCH_GROUP").length;
    $("#edge-recall").textContent = formatPct(evaluation.metrics?.expected_dominant_edge_recall);
    $("#forbidden-count").textContent = evaluation.metrics?.forbidden_edge_count ?? "—";
    $("#chronology-count").textContent = evaluation.metrics?.chronology_violation_count ?? "—";
    renderBranchList();
  }

  function applyInitialLocation() {
    const params = new URLSearchParams(window.location.search);
    const mode = params.get("mode");
    if (["lineage", "evidence", "corpus"].includes(mode)) {
      state.mode = mode;
      $$(".mode-button").forEach((item) => item.classList.toggle("active", item.dataset.mode === mode));
    }
    const paperId = params.get("paper");
    if (paperId && state.nodeById.has(paperId)) state.selected = { type: "paper", id: paperId };
    const edgePair = params.get("edge")?.split(",");
    if (edgePair?.length === 2) {
      const key = `${edgePair[0]}→${edgePair[1]}`;
      if (state.edgeByKey.has(key)) state.selected = { type: "edge", id: key };
    }
  }

  function syncLocation() {
    const params = new URLSearchParams();
    if (state.mode !== "lineage") params.set("mode", state.mode);
    if (state.selected?.type === "paper") params.set("paper", state.selected.id);
    if (state.selected?.type === "edge") {
      const edge = state.edgeByKey.get(state.selected.id);
      if (edge) params.set("edge", `${edge.source},${edge.target}`);
    }
    const query = params.toString();
    history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
  }

  function bindControls() {
    $$(".mode-button").forEach((button) => {
      button.addEventListener("click", () => {
        state.mode = button.dataset.mode;
        state.branchFocus = null;
        state.fitOnNextRender = true;
        $$(".mode-button").forEach((item) => item.classList.toggle("active", item === button));
        $("#clear-branch").hidden = true;
        syncLocation();
        renderGraph({ fit: true });
      });
    });

    $$(".relation-toggle input").forEach((input) => {
      if (!input.dataset.level) return;
      input.addEventListener("change", () => {
        input.checked ? state.levels.add(input.dataset.level) : state.levels.delete(input.dataset.level);
        dom.hairball.hidden = !state.levels.has("weak");
        renderGraph({ fit: false });
      });
    });

    $("#group-layer").addEventListener("change", (event) => {
      state.showGroupEdges = event.currentTarget.checked;
      renderGraph({ fit: false });
    });

    $("#reset-filters").addEventListener("click", () => {
      state.levels = new Set(["strong", "medium"]);
      $$(".relation-toggle input").forEach((input) => {
        input.checked = input.dataset.level ? state.levels.has(input.dataset.level) : false;
      });
      state.showGroupEdges = false;
      dom.hairball.hidden = true;
      renderGraph({ fit: false });
    });

    $("#clear-branch").addEventListener("click", () => {
      state.branchFocus = null;
      $("#clear-branch").hidden = true;
      renderBranchList();
      renderGraph({ fit: true });
    });

    dom.search.addEventListener("input", renderSearchResults);
    dom.search.addEventListener("focus", renderSearchResults);
    dom.search.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        dom.searchResults.hidden = true;
        dom.search.blur();
      }
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".search-section")) dom.searchResults.hidden = true;
    });
    document.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        dom.search.focus();
      }
    });

    $("#zoom-in").addEventListener("click", () => zoomBy(1.18));
    $("#zoom-out").addEventListener("click", () => zoomBy(0.85));
    $("#fit-view").addEventListener("click", fitView);
    $("#help-button").addEventListener("click", () => {
      state.selected = null;
      state.branchFocus = null;
      $("#clear-branch").hidden = true;
      renderBranchList();
      syncLocation();
      renderGraph({ fit: true });
      renderSelectionStyles();
      renderInspector();
    });

    dom.viewport.addEventListener("wheel", onWheel, { passive: false });
    dom.viewport.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("resize", () => state.layout && fitView());

    dom.inspector.addEventListener("click", (event) => {
      const edgeButton = event.target.closest("[data-edge-key]");
      const paperButton = event.target.closest("[data-paper-id]");
      if (edgeButton) selectEdge(edgeButton.dataset.edgeKey);
      if (paperButton) selectPaper(paperButton.dataset.paperId, false);
    });
  }

  function renderBranchList() {
    dom.branchList.innerHTML = "";
    (state.payload?.benchmark_branches || []).forEach((branch, index) => {
      const button = document.createElement("button");
      button.className = `branch-card${state.branchFocus === branch.branch_id ? " active" : ""}`;
      button.style.setProperty("--branch-color", BRANCH_COLORS[index % BRANCH_COLORS.length]);
      const coverage = branch.evaluation?.paper_coverage;
      button.innerHTML = `<b>${escapeHtml(branch.label)}</b><small>${branch.paper_ids.length} landmarks · ${formatPct(coverage)} coverage</small>`;
      button.addEventListener("click", () => {
        state.branchFocus = state.branchFocus === branch.branch_id ? null : branch.branch_id;
        $("#clear-branch").hidden = !state.branchFocus;
        state.selected = null;
        renderBranchList();
        renderInspector();
        renderGraph({ fit: true });
      });
      dom.branchList.appendChild(button);
    });
  }

  function renderSearchResults() {
    if (!state.payload) return;
    const query = dom.search.value.trim().toLowerCase();
    if (!query) {
      dom.searchResults.hidden = true;
      return;
    }
    const matches = state.nodes
      .map((node) => {
        const haystack = [node.title, node.paper_id, node.venue, ...(node.metadata?.authors || [])]
          .filter(Boolean).join(" ").toLowerCase();
        const title = node.title.toLowerCase();
        const score = title === query ? 3 : title.startsWith(query) ? 2 : haystack.includes(query) ? 1 : 0;
        return { node, score };
      })
      .filter((item) => item.score > 0)
      .sort((a, b) => b.score - a.score || (b.node.metadata?.citation_count || 0) - (a.node.metadata?.citation_count || 0))
      .slice(0, 8);
    dom.searchResults.innerHTML = matches.length
      ? matches.map(({ node }) => `<button class="search-result" data-search-paper="${escapeHtml(node.paper_id)}"><b>${escapeHtml(node.title)}</b><small>${node.year || "Unknown year"} · ${escapeHtml(node.venue || node.paper_id)}</small></button>`).join("")
      : `<div class="search-result"><small>No matching paper</small></div>`;
    dom.searchResults.hidden = false;
    dom.searchResults.querySelectorAll("[data-search-paper]").forEach((button) => {
      button.addEventListener("click", () => {
        dom.searchResults.hidden = true;
        dom.search.value = "";
        state.mode = "corpus";
        state.branchFocus = null;
        $("#clear-branch").hidden = true;
        renderBranchList();
        $$(".mode-button").forEach((item) => item.classList.toggle("active", item.dataset.mode === "corpus"));
        selectPaper(button.dataset.searchPaper, true);
      });
    });
  }

  function activeGraph() {
    let edges;
    if (state.mode === "lineage") {
      edges = state.edges.filter((edge) => edge.dominant);
    } else {
      edges = state.edges.filter((edge) => state.levels.has(edge.association_level));
      if (!state.showGroupEdges) {
        edges = edges.filter((edge) => edge.relation !== "SAME_RESEARCH_GROUP");
      }
      if (state.mode === "evidence" && state.levels.has("weak")) {
        const selectedPaper = state.selected?.type === "paper" ? state.selected.id : null;
        edges = edges.filter((edge) => edge.association_level !== "weak" || (selectedPaper && (edge.source === selectedPaper || edge.target === selectedPaper)));
      }
    }

    const branch = (state.payload.benchmark_branches || []).find((item) => item.branch_id === state.branchFocus);
    if (branch) {
      const seeds = new Set(branch.paper_ids);
      edges = edges.filter((edge) => seeds.has(edge.source) || seeds.has(edge.target));
    }

    const ids = new Set();
    if (state.mode === "corpus" && !branch) state.nodes.forEach((node) => ids.add(node.paper_id));
    if (state.mode !== "corpus" && !branch) state.landmarkIds.forEach((id) => ids.add(id));
    if (branch) branch.paper_ids.forEach((id) => ids.add(id));
    edges.forEach((edge) => { ids.add(edge.source); ids.add(edge.target); });
    if (state.selected?.type === "paper") ids.add(state.selected.id);
    if (state.selected?.type === "edge") {
      const selectedEdge = state.edgeByKey.get(state.selected.id);
      if (selectedEdge) { ids.add(selectedEdge.source); ids.add(selectedEdge.target); }
    }
    return { edges, nodes: state.nodes.filter((node) => ids.has(node.paper_id)) };
  }

  function laneKey(node) {
    return node.cluster_paths?.[state.payload.dag.run_metadata?.axis || "solution"]?.[0] ?? "unclustered";
  }

  function buildLayout(nodes, cards) {
    const knownYears = state.nodes.map((node) => node.year).filter(Number.isFinite);
    const visibleYears = [...new Set(nodes.map((node) => node.year).filter(Number.isFinite))].sort((a, b) => a - b);
    const minYear = Math.min(...knownYears);
    const maxYear = Math.max(...knownYears);
    // Preserve chronology while compressing long inactive periods.  A literal
    // 1996–2026 scale made the evidence cards unreadable in the default view.
    const yearStep = cards ? 82 : 54;
    const left = 118;
    const right = 145;
    const top = 56;
    const yearPositions = new Map();
    let yearCursor = left;
    visibleYears.forEach((year, index) => {
      if (index) {
        const gap = Math.max(1, Math.min(3, year - visibleYears[index - 1]));
        yearCursor += gap * yearStep;
      }
      yearPositions.set(year, yearCursor);
    });
    const laneOrder = [...new Set(nodes.map(laneKey))].sort((a, b) => {
      const preferred = ["3", "1", "0", "2", "unclustered"];
      return (preferred.indexOf(a) < 0 ? 99 : preferred.indexOf(a)) - (preferred.indexOf(b) < 0 ? 99 : preferred.indexOf(b)) || String(a).localeCompare(String(b));
    });
    const positions = new Map();
    const lanes = [];
    let currentY = top;

    laneOrder.forEach((key, laneIndex) => {
      const laneNodes = nodes.filter((node) => laneKey(node) === key).sort((a, b) => (a.year || maxYear) - (b.year || maxYear) || a.title.localeCompare(b.title));
      const trackEnds = [];
      const collisionDistance = cards ? 192 : 24;
      laneNodes.forEach((node) => {
        const x = yearPositions.get(node.year) ?? yearCursor + yearStep;
        let track = trackEnds.findIndex((lastX) => x - lastX >= collisionDistance);
        if (track < 0) { track = trackEnds.length; trackEnds.push(-Infinity); }
        trackEnds[track] = x;
        positions.set(node.paper_id, { x, y: currentY + 60 + track * (cards ? 76 : 27), lane: laneIndex, track });
      });
      const laneHeight = Math.max(cards ? 150 : 112, 95 + Math.max(1, trackEnds.length) * (cards ? 76 : 27));
      lanes.push({ key, y: currentY, height: laneHeight, index: laneIndex });
      currentY += laneHeight + 12;
    });

    return {
      positions, lanes, minYear, maxYear, yearStep, left,
      yearPositions,
      width: yearCursor + right,
      height: currentY + 45,
      cards,
    };
  }

  function renderGraph({ fit = false } = {}) {
    if (!state.payload) return;
    const graph = activeGraph();
    const cards = state.mode !== "corpus" && graph.nodes.length <= 48;
    state.layout = buildLayout(graph.nodes, cards);
    dom.lanes.replaceChildren();
    dom.edges.replaceChildren();
    dom.nodes.replaceChildren();
    renderLanes(state.layout);
    renderEdges(graph.edges, state.layout);
    renderNodes(graph.nodes, state.layout);
    updateViewSummary(graph);
    const app = $("#app");
    app.dataset.ready = "true";
    app.dataset.mode = state.mode;
    app.dataset.visibleNodes = String(graph.nodes.length);
    app.dataset.visibleEdges = String(graph.edges.length);
    renderSelectionStyles();
    if (fit || state.fitOnNextRender) {
      requestAnimationFrame(fitView);
      state.fitOnNextRender = false;
    } else {
      applyTransform();
    }
  }

  function renderLanes(layout) {
    layout.lanes.forEach((lane) => {
      dom.lanes.appendChild(svgEl("rect", {
        x: 20, y: lane.y, width: layout.width - 40, height: lane.height,
        rx: 14, class: `lane-band${lane.index % 2 ? " alt" : ""}`,
      }));
      dom.lanes.appendChild(svgEl("text", {
        x: 36, y: lane.y + 25, class: "lane-title",
      }, lane.key === "unclustered" ? "UNCLUSTERED" : `MODEL · SOLUTION CLUSTER ${lane.key}`));
    });
    layout.yearPositions.forEach((x, year) => {
      dom.lanes.appendChild(svgEl("line", { x1: x, y1: 37, x2: x, y2: layout.height - 22, class: "year-line" }));
      dom.lanes.appendChild(svgEl("text", { x, y: 27, "text-anchor": "middle", class: "year-label" }, year));
    });
  }

  function edgePath(edge, layout) {
    const source = layout.positions.get(edge.source);
    const target = layout.positions.get(edge.target);
    if (!source || !target) return null;
    const horizontalGap = Math.abs(target.x - source.x);
    const offset = layout.cards ? Math.min(91, Math.max(16, horizontalGap / 3)) : 8;
    const sx = source.x + offset;
    const tx = target.x - offset;
    const span = Math.max(45, Math.abs(tx - sx) * 0.42);
    return {
      d: `M ${sx} ${source.y} C ${sx + span} ${source.y}, ${tx - span} ${target.y}, ${tx} ${target.y}`,
      mx: (sx + tx) / 2,
      my: (source.y + target.y) / 2 - 5,
    };
  }

  function renderEdges(edges, layout) {
    const supplemental = (edge) => Number(edge.relation === "SAME_RESEARCH_GROUP");
    const ordered = [...edges].sort((a, b) => supplemental(b) - supplemental(a) || LEVEL_RANK[a.association_level] - LEVEL_RANK[b.association_level] || Number(a.dominant) - Number(b.dominant));
    ordered.forEach((edge) => {
      const curve = edgePath(edge, layout);
      if (!curve) return;
      const key = edgeKey(edge);
      const group = svgEl("g", { class: "edge-group", "data-edge-key": key });
      const line = svgEl("path", {
        d: curve.d,
        class: `graph-edge ${edge.association_level}${edge.relation === "SAME_RESEARCH_GROUP" ? " supplemental" : ""}${edge.dominant ? " dominant" : ""}`,
        "data-edge-key": key,
      });
      const hit = svgEl("path", { d: curve.d, class: "edge-hit", "data-edge-key": key });
      [line, hit].forEach((element) => {
        element.addEventListener("click", (event) => { event.stopPropagation(); selectEdge(key); });
        element.addEventListener("pointerenter", (event) => showEdgeTooltip(event, edge));
        element.addEventListener("pointerleave", hideTooltip);
      });
      group.append(line, hit);
      if (edge.dominant && layout.cards) {
        const label = RELATION_LABELS[edge.relation] || edge.relation.replaceAll("_", " ");
        const width = Math.min(132, Math.max(52, label.length * 8 + 15));
        group.append(
          svgEl("rect", { x: curve.mx - width / 2, y: curve.my - 9, width, height: 17, rx: 8, class: "edge-label-bg" }),
          svgEl("text", { x: curve.mx, y: curve.my + 3, "text-anchor": "middle", class: "edge-label" }, label),
        );
      }
      dom.edges.appendChild(group);
    });
  }

  function renderNodes(nodes, layout) {
    const laneColor = new Map(layout.lanes.map((lane, index) => [lane.key, BRANCH_COLORS[index % BRANCH_COLORS.length]]));
    nodes.forEach((node) => {
      const position = layout.positions.get(node.paper_id);
      if (!position) return;
      const landmark = state.landmarkIds.has(node.paper_id);
      const hub = Boolean(node.metadata?.is_hub);
      const group = svgEl("g", {
        class: `node-group${landmark ? " landmark" : ""}`,
        transform: `translate(${position.x} ${position.y})`,
        "data-paper-id": node.paper_id,
        tabindex: 0,
        role: "button",
        "aria-label": `${node.title}, ${node.year || "unknown year"}`,
      });
      group.style.setProperty("--node-color", laneColor.get(laneKey(node)));
      if (layout.cards) renderNodeCard(group, node, { landmark, hub });
      else renderNodeDot(group, node, { landmark, hub });
      group.addEventListener("click", (event) => { event.stopPropagation(); selectPaper(node.paper_id, false); });
      group.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") selectPaper(node.paper_id, false); });
      group.addEventListener("pointerenter", (event) => showPaperTooltip(event, node));
      group.addEventListener("pointerleave", hideTooltip);
      dom.nodes.appendChild(group);
    });
  }

  function renderNodeCard(group, node, { landmark, hub }) {
    group.appendChild(svgEl("rect", { x: -91, y: -29, width: 182, height: 58, class: "node-card" }));
    group.appendChild(svgEl("rect", { x: -91, y: -29, width: 5, height: 58, rx: 3, class: "node-accent" }));
    group.appendChild(svgEl("text", { x: -77, y: -13, class: "node-year" }, node.year || "N/A"));
    if (hub) {
      group.append(svgEl("circle", { cx: 75, cy: -14, r: 8, class: "hub-ring" }), svgEl("text", { x: 75, y: -11, "text-anchor": "middle", class: "hub-star" }, "✦"));
    } else if (landmark) {
      group.appendChild(svgEl("text", { x: 78, y: -11, "text-anchor": "end", class: "node-meta" }, "LANDMARK"));
    }
    const lines = wrapTitle(paperDisplayTitle(node), 27, 2);
    lines.forEach((line, index) => group.appendChild(svgEl("text", { x: -77, y: 3 + index * 13, class: "node-title" }, line)));
    const citations = node.metadata?.citation_count;
    group.appendChild(svgEl("text", { x: 78, y: 20, "text-anchor": "end", class: "node-meta" }, `${citations ?? 0} cites`));
  }

  function renderNodeDot(group, node, { landmark, hub }) {
    group.appendChild(svgEl("circle", { cx: 0, cy: 0, r: hub ? 8 : landmark ? 7 : 4.5, class: "node-dot" }));
    if (hub || landmark || state.selected?.id === node.paper_id) {
      group.appendChild(svgEl("text", { x: 10, y: -7, class: "node-dot-label" }, `${shortTitle(paperDisplayTitle(node), 25)} · ${node.year || "?"}`));
    }
  }

  function wrapTitle(value, maxChars, maxLines) {
    const words = String(value).split(/\s+/);
    const lines = [];
    let current = "";
    words.forEach((word) => {
      if (lines.length >= maxLines) return;
      const candidate = current ? `${current} ${word}` : word;
      if (candidate.length > maxChars && current) {
        lines.push(current);
        current = word;
      } else current = candidate;
    });
    if (lines.length < maxLines && current) lines.push(current);
    if (lines.length === maxLines && words.join(" ").length > lines.join(" ").length) {
      lines[maxLines - 1] = `${lines[maxLines - 1].slice(0, maxChars - 1)}…`;
    }
    return lines;
  }

  function updateViewSummary(graph) {
    const copy = {
      lineage: ["Primary genealogy", "Dominant lineage + benchmark landmarks"],
      evidence: ["Evidence map", "Logical evidence first; research-group links are optional"],
      corpus: ["Corpus overview", "All papers; relationship layers remain optional"],
    }[state.mode];
    const branch = (state.payload.benchmark_branches || []).find((item) => item.branch_id === state.branchFocus);
    $("#view-title").textContent = branch ? branch.label : copy[0];
    $("#view-subtitle").textContent = `${graph.nodes.length} papers · ${graph.edges.length} visible relations${branch ? " · benchmark focus" : ""}`;
  }

  function selectPaper(paperId, center) {
    if (!state.nodeById.has(paperId)) return;
    state.selected = { type: "paper", id: paperId };
    syncLocation();
    if (state.mode === "evidence" && state.levels.has("weak")) renderGraph({ fit: false });
    else renderSelectionStyles();
    renderInspector();
    if (center) requestAnimationFrame(() => centerOnPaper(paperId));
    if (window.innerWidth <= 920) $(".inspector-panel").classList.add("open");
  }

  function selectEdge(key) {
    if (!state.edgeByKey.has(key)) return;
    state.selected = { type: "edge", id: key };
    syncLocation();
    renderSelectionStyles();
    renderInspector();
    if (window.innerWidth <= 920) $(".inspector-panel").classList.add("open");
  }

  function renderSelectionStyles() {
    const selectedPaper = state.selected?.type === "paper" ? state.selected.id : null;
    const selectedEdgeKey = state.selected?.type === "edge" ? state.selected.id : null;
    let connected = new Set();
    if (selectedPaper) {
      state.edges.filter((edge) => edge.source === selectedPaper || edge.target === selectedPaper).forEach((edge) => { connected.add(edge.source); connected.add(edge.target); });
    }
    if (selectedEdgeKey) {
      const edge = state.edgeByKey.get(selectedEdgeKey);
      if (edge) connected = new Set([edge.source, edge.target]);
    }
    dom.nodes.querySelectorAll(".node-group").forEach((group) => {
      const id = group.dataset.paperId;
      group.classList.toggle("selected", id === selectedPaper || (selectedEdgeKey && connected.has(id)));
      group.classList.toggle("dimmed", Boolean(state.selected) && !connected.has(id) && id !== selectedPaper);
    });
    dom.edges.querySelectorAll(".graph-edge").forEach((path) => {
      const key = path.dataset.edgeKey;
      const edge = state.edgeByKey.get(key);
      const incident = edge && selectedPaper && (edge.source === selectedPaper || edge.target === selectedPaper);
      path.classList.toggle("selected", key === selectedEdgeKey || Boolean(incident));
      path.classList.toggle("dimmed", Boolean(state.selected) && key !== selectedEdgeKey && !incident);
    });
  }

  function renderInspector() {
    if (!state.payload) return;
    if (!state.selected && state.branchFocus) {
      renderBranchInspector();
      return;
    }
    if (!state.selected) {
      renderEmptyInspector();
      return;
    }
    if (state.selected.type === "paper") renderPaperInspector(state.nodeById.get(state.selected.id));
    else renderEdgeInspector(state.edgeByKey.get(state.selected.id));
  }

  function renderBranchInspector() {
    const branch = state.payload.benchmark_branches.find((item) => item.branch_id === state.branchFocus);
    if (!branch) return renderEmptyInspector();
    const papers = branch.paper_ids.map((id) => state.nodeById.get(id)).filter(Boolean);
    const axis = state.payload.dag.run_metadata?.axis || "solution";
    const clusters = [...new Set(papers.map((paper) => (paper.cluster_paths?.[axis] || []).join(" / ") || "unclustered"))];
    const topClusterIds = [...new Set(papers.map((paper) => paper.cluster_paths?.[axis]?.[0]).filter(Boolean))];
    const splitNotes = (state.payload.dag.branches || [])
      .filter((item) => topClusterIds.some((cluster) => item.branch_id === `${axis}:${cluster}`) && item.split_reason)
      .map((item) => item.split_reason);
    const evaluation = branch.evaluation || {};
    dom.inspector.innerHTML = `<div style="--accent:#557b98">
      <div class="inspector-eyebrow">BENCHMARK BRANCH · HUMAN LENS</div>
      <h2 class="inspector-title">${escapeHtml(branch.label)}</h2>
      <p class="inspector-subtitle">${escapeHtml(branch.note || "Expert-curated branch hypothesis used to inspect the current model output.")}</p>
      <div class="detail-chips">
        <span class="detail-chip gold">Human benchmark</span>
        <span class="detail-chip">${papers.length} landmarks</span>
        <span class="detail-chip parent">${formatPct(evaluation.paper_coverage)} paper coverage</span>
        <span class="detail-chip">${formatPct(evaluation.coarse_cluster_coherence)} cluster coherence</span>
      </div>
      <div class="inspector-section"><h3>REPRESENTATIVE PAPERS</h3><div class="branch-paper-list">${papers.map((paper) => `<button class="branch-paper-button" data-paper-id="${escapeHtml(paper.paper_id)}"><span>${paper.year || "?"}</span><b>${escapeHtml(paperDisplayTitle(paper))}</b><small>solution / ${escapeHtml((paper.cluster_paths?.[axis] || []).join(" / ") || "unclustered")}</small></button>`).join("")}</div></div>
      <div class="inspector-section"><h3>MODEL COMPARISON</h3><p class="explanation-copy">This expert branch currently spans ${clusters.length} model cluster${clusters.length === 1 ? "" : "s"}: ${escapeHtml(clusters.join(", "))}. The two views remain separate so disagreement stays visible.</p></div>
      <div class="inspector-section"><h3>SPLIT EXPLANATION STATUS</h3><p class="abstract-copy">${splitNotes.length ? escapeHtml(splitNotes.join(" ")) : "No technical split explanation has been validated for this branch in the current run. This remains an explicit evidence gap."}</p></div>
    </div>`;
  }

  function renderEmptyInspector() {
    const summary = state.payload?.summary || {};
    dom.inspector.innerHTML = `<div class="empty-inspector">
      <div class="empty-hero">
        <div class="inspector-eyebrow">HOW TO READ</div>
        <h2>从主干开始，逐层展开证据</h2>
        <p>这不是 citation dashboard。默认图只显示能够成为技术谱系的关系；点击节点或连线检查原文证据。</p>
      </div>
      <div class="reading-guide">
        <div class="guide-row"><span class="guide-number">1</span><div><b>先看深绿色主谱系</b><small>这些边同时是 strong、parent-eligible 和 dominant。</small></div></div>
        <div class="guide-row"><span class="guide-number">2</span><div><b>切换到“证据图”</b><small>查看 baseline、Introduction 讨论和没有进入主干的强关联。</small></div></div>
        <div class="guide-row"><span class="guide-number">3</span><div><b>点击边查看正文</b><small>每个 evidence atom 都保留 section、role、citation marker 与来源 PDF。</small></div></div>
      </div>
      <div class="run-stats">
        <div class="run-stat"><b>${summary.paper_count ?? "—"}</b><small>Papers</small></div>
        <div class="run-stat"><b>${summary.dominant_count ?? "—"}</b><small>Primary edges</small></div>
        <div class="run-stat"><b>${summary.evidence_atom_count ?? "—"}</b><small>Evidence atoms</small></div>
        <div class="run-stat"><b>${formatPct(state.payload?.evaluation?.metrics?.expected_dominant_edge_recall)}</b><small>Gold edge recall</small></div>
      </div>
      <div class="inspector-section"><h3>CURRENT PRIMARY MAP</h3><div class="connection-list">${renderPrimaryOverview()}</div></div>
    </div>`;
  }

  function renderPrimaryOverview() {
    return state.edges.filter((edge) => edge.dominant).map((edge) => {
      const source = state.nodeById.get(edge.source);
      const target = state.nodeById.get(edge.target);
      return `<button class="connection-button" data-edge-key="${escapeHtml(edgeKey(edge))}" style="--edge-color:#204b3e"><span class="connection-dot"></span><span class="connection-title">${escapeHtml(shortTitle(source ? paperDisplayTitle(source) : edge.source, 20))} → ${escapeHtml(shortTitle(target ? paperDisplayTitle(target) : edge.target, 20))}</span><span class="connection-level">${escapeHtml(RELATION_LABELS[edge.relation] || edge.relation)}</span></button>`;
    }).join("");
  }

  function renderPaperInspector(node) {
    if (!node) return renderEmptyInspector();
    const path = node.cluster_paths?.[state.payload.dag.run_metadata?.axis || "solution"] || [];
    const fulltext = state.payload.fulltext?.[node.paper_id];
    const connections = state.edges
      .filter((edge) => edge.source === node.paper_id || edge.target === node.paper_id)
      .sort((a, b) => Number(b.dominant) - Number(a.dominant) || LEVEL_RANK[b.association_level] - LEVEL_RANK[a.association_level] || Number(a.relation === "SAME_RESEARCH_GROUP") - Number(b.relation === "SAME_RESEARCH_GROUP") || b.confidence - a.confidence);
    const landmark = state.payload.landmarks.find((item) => item.paper_id === node.paper_id);
    const doi = node.metadata?.doi;
    const openAlexId = node.paper_id.startsWith("OPENALEX:") ? node.paper_id.split(":")[1] : null;
    const links = [
      doi && `<a class="action-link" href="${escapeHtml(doi)}" target="_blank" rel="noreferrer">DOI</a>`,
      openAlexId && `<a class="action-link" href="https://openalex.org/${escapeHtml(openAlexId)}" target="_blank" rel="noreferrer">OpenAlex</a>`,
      fulltext?.local_path && `<a class="action-link" href="../${escapeHtml(fulltext.local_path)}" target="_blank">Local PDF</a>`,
      fulltext?.selected_url && `<a class="action-link" href="${escapeHtml(fulltext.selected_url)}" target="_blank" rel="noreferrer">Source PDF</a>`,
    ].filter(Boolean).join("");
    dom.inspector.innerHTML = `<div style="--accent:${escapeHtml(BRANCH_COLORS[Math.max(0, ["3","1","0","2"].indexOf(laneKey(node))) % BRANCH_COLORS.length])}">
      <div class="inspector-eyebrow">PAPER · ${escapeHtml(node.paper_id)}</div>
      <h2 class="inspector-title">${escapeHtml(node.title)}</h2>
      <p class="inspector-subtitle">${escapeHtml([node.venue, node.year].filter(Boolean).join(" · ") || "Publication metadata unavailable")}</p>
      <div class="detail-chips">
        ${landmark ? `<span class="detail-chip gold">Benchmark landmark</span>` : ""}
        ${node.metadata?.is_hub ? `<span class="detail-chip parent">Hub · ${Number(node.metadata.hub_score || 0).toFixed(2)}</span>` : ""}
        <span class="detail-chip">${connections.length} in-corpus relations</span>
        ${fulltext ? `<span class="detail-chip parent">Full text verified</span>` : ""}
      </div>
      <div class="inspector-section"><h3>METADATA</h3><dl class="metadata-list">
        <dt>Year</dt><dd>${node.year || "Unknown"}</dd>
        <dt>Model cluster</dt><dd>${path.length ? `solution / ${path.join(" / ")}` : "Unclustered"}</dd>
        <dt>Citations</dt><dd>${node.metadata?.citation_count ?? "Unknown"}</dd>
        <dt>Open access</dt><dd>${node.metadata?.is_open_access ? "Yes" : "Not reported by OpenAlex"}</dd>
        ${fulltext ? `<dt>Full-text source</dt><dd>${escapeHtml(fulltext.selected_provider || "fallback")} · title score ${fulltext.title_score}</dd>` : ""}
      </dl></div>
      ${node.abstract ? `<div class="inspector-section"><h3>ABSTRACT</h3><p class="abstract-copy">${escapeHtml(node.abstract)}</p></div>` : ""}
      ${links ? `<div class="action-links">${links}</div>` : ""}
      <div class="inspector-section"><h3>STRONGEST CONNECTIONS</h3><div class="connection-list">${renderConnections(node, connections)}</div></div>
    </div>`;
  }

  function renderConnections(node, connections) {
    if (!connections.length) return `<p class="inspector-subtitle">No in-corpus relationship.</p>`;
    return connections.slice(0, 18).map((edge) => {
      const otherId = edge.source === node.paper_id ? edge.target : edge.source;
      const other = state.nodeById.get(otherId);
      const direction = edge.source === node.paper_id ? "→" : "←";
      return `<button class="connection-button" data-edge-key="${escapeHtml(edgeKey(edge))}" style="--edge-color:${LEVEL_COLOR[edge.association_level]}">
        <span class="connection-dot"></span><span class="connection-title">${direction} ${escapeHtml(shortTitle(other ? paperDisplayTitle(other) : otherId, 46))}</span><span class="connection-level">${edge.dominant ? "PRIMARY" : LEVEL_LABEL[edge.association_level]}</span>
      </button>`;
    }).join("");
  }

  function renderEdgeInspector(edge) {
    if (!edge) return renderEmptyInspector();
    const source = state.nodeById.get(edge.source);
    const target = state.nodeById.get(edge.target);
    const relationChips = (edge.relation_types || []).map((relation) => `<span class="detail-chip">${escapeHtml(RELATION_LABELS[relation] || relation.replaceAll("_", " "))}</span>`).join("");
    const atoms = edge.evidence_details || [];
    dom.inspector.innerHTML = `<div style="--accent:${LEVEL_COLOR[edge.association_level]}">
      <div class="inspector-eyebrow">RELATION · ${LEVEL_LABEL[edge.association_level]}</div>
      <h2 class="inspector-title">${escapeHtml(RELATION_LABELS[edge.relation] || edge.relation.replaceAll("_", " "))}</h2>
      <div class="edge-route">
        <button class="route-paper" data-paper-id="${escapeHtml(edge.source)}"><small>PREDECESSOR</small><b>${escapeHtml(shortTitle(source ? paperDisplayTitle(source) : edge.source, 30))}</b></button>
        <span class="route-arrow">→</span>
        <button class="route-paper" data-paper-id="${escapeHtml(edge.target)}"><small>DESCENDANT</small><b>${escapeHtml(shortTitle(target ? paperDisplayTitle(target) : edge.target, 30))}</b></button>
      </div>
      <div class="detail-chips">
        <span class="detail-chip ${edge.association_level}">${LEVEL_LABEL[edge.association_level]}</span>
        ${edge.parent_eligible ? `<span class="detail-chip parent">Parent eligible</span>` : `<span class="detail-chip">Cross-link only</span>`}
        ${edge.dominant ? `<span class="detail-chip parent">Primary genealogy</span>` : ""}
        <span class="detail-chip">${Math.round(edge.confidence * 100)}% confidence</span>
        ${relationChips}
      </div>
      <div class="inspector-section"><h3>WHY CONNECTED</h3><p class="explanation-copy">${escapeHtml(edge.explanation || "No generated explanation.")}</p></div>
      <div class="inspector-section"><h3>EVIDENCE · ${atoms.length}</h3><div class="evidence-stack">${atoms.length ? atoms.map(renderEvidenceAtom).join("") : `<p class="inspector-subtitle">No section-aware or authorship evidence atom; this is a citation-overlay relation.</p>`}</div></div>
    </div>`;
  }

  function renderEvidenceAtom(atom) {
    const origin = atom.role === "ENTITY_ORIGIN";
    return `<article class="evidence-card${origin ? " origin" : ""}">
      <div class="evidence-head"><span class="evidence-role">${escapeHtml(atom.role)}</span><span class="evidence-section-name">${escapeHtml(atom.section_type)} · ${escapeHtml(atom.section)}</span></div>
      <p class="evidence-text">${escapeHtml(atom.text)}</p>
      <div class="evidence-meta">
        ${atom.citation_marker ? `<span>${escapeHtml(atom.citation_marker)}</span>` : ""}
        ${atom.entity ? `<span>entity: ${escapeHtml(atom.entity)}</span>` : ""}
        <span>${Math.round((atom.confidence || 0) * 100)}% confidence</span>
        ${atom.source_path ? `<span>${escapeHtml(atom.source_path.split("/").pop())}</span>` : ""}
      </div>
    </article>`;
  }

  function showPaperTooltip(event, node) {
    const path = node.cluster_paths?.[state.payload.dag.run_metadata?.axis || "solution"] || [];
    showTooltip(event, `<b>${escapeHtml(node.title)}</b><small>${node.year || "Unknown year"} · solution/${escapeHtml(path.join("/")) || "unclustered"}<br>${node.metadata?.citation_count ?? 0} citations</small>`);
  }

  function showEdgeTooltip(event, edge) {
    const source = state.nodeById.get(edge.source);
    const target = state.nodeById.get(edge.target);
    showTooltip(event, `<b>${escapeHtml(shortTitle(source ? paperDisplayTitle(source) : edge.source))} → ${escapeHtml(shortTitle(target ? paperDisplayTitle(target) : edge.target))}</b><small>${LEVEL_LABEL[edge.association_level]} · ${escapeHtml(RELATION_LABELS[edge.relation] || edge.relation)}<br>${edge.evidence_details?.length || 0} evidence atoms${edge.dominant ? " · primary genealogy" : ""}</small>`);
  }

  function showTooltip(event, html) {
    dom.tooltip.innerHTML = html;
    dom.tooltip.hidden = false;
    const x = Math.min(window.innerWidth - 300, event.clientX + 13);
    const y = Math.min(window.innerHeight - 110, event.clientY + 13);
    dom.tooltip.style.left = `${x}px`;
    dom.tooltip.style.top = `${y}px`;
  }

  function hideTooltip() { dom.tooltip.hidden = true; }

  function applyTransform() {
    dom.world.setAttribute("transform", `translate(${state.transform.x} ${state.transform.y}) scale(${state.transform.scale})`);
    dom.zoomReadout.textContent = `${Math.round(state.transform.scale * 100)}%`;
  }

  function fitView() {
    if (!state.layout) return;
    const rect = dom.viewport.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const padding = 34;
    const scale = Math.min(1, Math.max(0.18, Math.min((rect.width - padding * 2) / state.layout.width, (rect.height - padding * 2) / state.layout.height)));
    state.transform = {
      scale,
      x: (rect.width - state.layout.width * scale) / 2,
      y: (rect.height - state.layout.height * scale) / 2,
    };
    applyTransform();
  }

  function centerOnPaper(paperId) {
    const position = state.layout?.positions.get(paperId);
    if (!position) return;
    const rect = dom.viewport.getBoundingClientRect();
    const scale = Math.max(state.transform.scale, 0.85);
    state.transform = { scale, x: rect.width / 2 - position.x * scale, y: rect.height / 2 - position.y * scale };
    applyTransform();
  }

  function zoomBy(factor, center = null) {
    const rect = dom.viewport.getBoundingClientRect();
    const point = center || { x: rect.width / 2, y: rect.height / 2 };
    const oldScale = state.transform.scale;
    const newScale = Math.min(2.6, Math.max(0.16, oldScale * factor));
    const worldX = (point.x - state.transform.x) / oldScale;
    const worldY = (point.y - state.transform.y) / oldScale;
    state.transform.scale = newScale;
    state.transform.x = point.x - worldX * newScale;
    state.transform.y = point.y - worldY * newScale;
    applyTransform();
  }

  function onWheel(event) {
    event.preventDefault();
    const rect = dom.viewport.getBoundingClientRect();
    zoomBy(event.deltaY < 0 ? 1.1 : 0.9, { x: event.clientX - rect.left, y: event.clientY - rect.top });
  }

  function onPointerDown(event) {
    if (event.target.closest(".node-group, .edge-hit")) return;
    state.dragging = { x: event.clientX, y: event.clientY, tx: state.transform.x, ty: state.transform.y };
    dom.viewport.classList.add("dragging");
  }

  function onPointerMove(event) {
    if (!state.dragging) return;
    state.transform.x = state.dragging.tx + event.clientX - state.dragging.x;
    state.transform.y = state.dragging.ty + event.clientY - state.dragging.y;
    applyTransform();
  }

  function onPointerUp() {
    state.dragging = null;
    dom.viewport?.classList.remove("dragging");
  }

  init();
})();
