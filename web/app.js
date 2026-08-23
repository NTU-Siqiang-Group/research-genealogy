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
    primaryNodeIds: new Set(),
    backboneEdgeKeys: new Set(),
    technicalEdgeKeys: new Set(),
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
    return node.title;
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
      state.backboneEdgeKeys = new Set(state.payload.auto_branch_discovery?.backbone_edge_keys || []);
      state.technicalEdgeKeys = new Set(state.payload.auto_branch_discovery?.technical_edge_keys || []);
      state.primaryNodeIds = new Set();
      state.edges.filter((edge) => state.backboneEdgeKeys.has(edgeKey(edge))).forEach((edge) => {
        state.primaryNodeIds.add(edge.source);
        state.primaryNodeIds.add(edge.target);
      });
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
    const { summary } = state.payload;
    $("#topic-title").textContent = state.payload.topic;
    $("#run-pill").textContent = `${summary.paper_count} papers · ${summary.edge_count} relations`;
    $("#strong-count").textContent = summary.association_level_counts.strong;
    $("#medium-count").textContent = state.edges.filter((edge) =>
      edge.association_level === "medium" && state.technicalEdgeKeys.has(edgeKey(edge))
    ).length;
    $("#weak-count").textContent = summary.association_level_counts.weak;
    $("#group-count").textContent = state.edges.filter((edge) =>
      isResearchGroupEdge(edge) && !state.technicalEdgeKeys.has(edgeKey(edge))
    ).length;
    $("#lineage-paper-count").textContent = summary.technical_lineage_paper_count ?? "—";
    $("#lineage-edge-count").textContent = summary.technical_lineage_edge_count ?? "—";
    $("#primary-count").textContent = summary.display_primary_count ?? "—";
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
    window.addEventListener("resize", () => state.layout && initialView());

    dom.inspector.addEventListener("click", (event) => {
      const edgeButton = event.target.closest("[data-edge-key]");
      const paperButton = event.target.closest("[data-paper-id]");
      if (edgeButton) selectEdge(edgeButton.dataset.edgeKey);
      if (paperButton) selectPaper(paperButton.dataset.paperId, false);
    });
  }

  function renderBranchList() {
    dom.branchList.innerHTML = "";
    const branches = state.payload?.auto_branches || [];
    if (!branches.length) {
      dom.branchList.innerHTML = `<p class="section-empty">Primary evidence DAG 暂未形成可识别路径。</p>`;
      return;
    }
    branches.forEach((branch, index) => {
      const button = document.createElement("button");
      button.className = `branch-card${state.branchFocus === branch.branch_id ? " active" : ""}`;
      button.style.setProperty("--branch-color", BRANCH_COLORS[index % BRANCH_COLORS.length]);
      const kind = branch.kind === "branch_cone" ? "branch cone" : "lineage path";
      button.innerHTML = `<b>${escapeHtml(branch.label)}</b><small>${branch.paper_ids.length} papers · ${kind} · ${formatPct(branch.confidence)}</small>`;
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
      edges = state.edges.filter((edge) =>
        state.technicalEdgeKeys.has(edgeKey(edge))
        && state.levels.has(edge.association_level)
      );
      if (state.showGroupEdges && state.levels.has("medium")) {
        const technicalNodes = new Set();
        edges.forEach((edge) => {
          technicalNodes.add(edge.source);
          technicalNodes.add(edge.target);
        });
        const supplemental = state.edges.filter((edge) =>
          isResearchGroupEdge(edge)
          && !state.technicalEdgeKeys.has(edgeKey(edge))
          && technicalNodes.has(edge.source)
          && technicalNodes.has(edge.target)
        );
        edges = [...edges, ...supplemental];
      }
    } else {
      edges = state.edges.filter((edge) => state.levels.has(edge.association_level));
      if (!state.showGroupEdges) {
        edges = edges.filter((edge) => !isResearchGroupEdge(edge) || state.technicalEdgeKeys.has(edgeKey(edge)));
      }
      if (state.mode === "evidence" && state.levels.has("weak")) {
        const selectedPaper = state.selected?.type === "paper" ? state.selected.id : null;
        edges = edges.filter((edge) => edge.association_level !== "weak" || (selectedPaper && (edge.source === selectedPaper || edge.target === selectedPaper)));
      }
    }

    const branch = (state.payload.auto_branches || []).find((item) => item.branch_id === state.branchFocus);
    if (branch) {
      const members = new Set(branch.paper_ids);
      const pathEdges = new Set(branch.edge_keys || []);
      edges = edges.filter((edge) =>
        members.has(edge.source)
        && members.has(edge.target)
        && (state.mode !== "lineage" || pathEdges.has(edgeKey(edge)))
      );
    }

    const ids = new Set();
    if (state.mode === "corpus" && !branch) state.nodes.forEach((node) => ids.add(node.paper_id));
    if (branch) branch.paper_ids.forEach((id) => ids.add(id));
    edges.forEach((edge) => { ids.add(edge.source); ids.add(edge.target); });
    if (state.selected?.type === "paper") ids.add(state.selected.id);
    if (state.selected?.type === "edge") {
      const selectedEdge = state.edgeByKey.get(state.selected.id);
      if (selectedEdge) { ids.add(selectedEdge.source); ids.add(selectedEdge.target); }
    }
    return { edges, nodes: state.nodes.filter((node) => ids.has(node.paper_id)) };
  }

  function isResearchGroupEdge(edge) {
    return edge.relation === "SAME_RESEARCH_GROUP"
      || (edge.relation_types || []).includes("SAME_RESEARCH_GROUP")
      || (edge.relation_types || []).includes("KEY_AUTHOR_OVERLAP");
  }

  function layoutEdgeWeight(edge) {
    if (edge.dominant) return 100;
    if (edge.association_level === "strong") return 30;
    if (edge.relation === "SAME_RESEARCH_GROUP") return 2;
    if (edge.association_level === "medium") return 10;
    return 1;
  }

  function minimizeLayerCrossings(layers, edges) {
    const layerById = new Map();
    layers.forEach((layer, index) => layer.nodes.forEach((node) => layerById.set(node.paper_id, index)));
    const incoming = new Map();
    const outgoing = new Map();
    edges.forEach((edge) => {
      if (!layerById.has(edge.source) || !layerById.has(edge.target)) return;
      const weighted = { id: edge.source, weight: layoutEdgeWeight(edge) };
      const reverse = { id: edge.target, weight: layoutEdgeWeight(edge) };
      if (!incoming.has(edge.target)) incoming.set(edge.target, []);
      if (!outgoing.has(edge.source)) outgoing.set(edge.source, []);
      incoming.get(edge.target).push(weighted);
      outgoing.get(edge.source).push(reverse);
    });

    function normalizedPositions() {
      const result = new Map();
      layers.forEach((layer) => {
        const denominator = Math.max(1, layer.nodes.length - 1);
        layer.nodes.forEach((node, index) => result.set(node.paper_id, index / denominator));
      });
      return result;
    }

    function sweep(start, end, step, neighbors) {
      const positions = normalizedPositions();
      for (let layerIndex = start; layerIndex !== end; layerIndex += step) {
        const layer = layers[layerIndex];
        const previous = new Map(layer.nodes.map((node, index) => [node.paper_id, index]));
        layer.nodes.sort((left, right) => {
          const score = (node) => {
            const candidates = (neighbors.get(node.paper_id) || []).filter((item) => positions.has(item.id));
            if (!candidates.length) return previous.get(node.paper_id);
            const total = candidates.reduce((sum, item) => sum + item.weight, 0);
            const mean = candidates.reduce((sum, item) => sum + positions.get(item.id) * item.weight, 0) / total;
            return mean * Math.max(1, layer.nodes.length - 1);
          };
          return score(left) - score(right) || previous.get(left.paper_id) - previous.get(right.paper_id);
        });
      }
    }

    for (let iteration = 0; iteration < 6; iteration += 1) {
      sweep(1, layers.length, 1, incoming);
      sweep(layers.length - 2, -1, -1, outgoing);
    }
  }

  function buildLayout(nodes, edges, style) {
    const knownYears = state.nodes.map((node) => node.year).filter(Number.isFinite);
    const fallbackYear = knownYears.length ? Math.max(...knownYears) + 1 : 1;
    const grouped = new Map();
    nodes.forEach((node) => {
      const key = Number.isFinite(node.year) ? node.year : fallbackYear;
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(node);
    });
    const layers = [...grouped.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([year, layerNodes]) => ({
        year: year === fallbackYear ? null : year,
        nodes: layerNodes.sort((a, b) => a.title.localeCompare(b.title)),
      }));
    minimizeLayerCrossings(layers, edges);

    const metrics = {
      card: { horizontalStep: 236, verticalStep: 82, left: 135, top: 98 },
      compact: { horizontalStep: 174, verticalStep: 58, left: 100, top: 76 },
      dot: { horizontalStep: 72, verticalStep: 28, left: 65, top: 70 },
    }[style];
    const { horizontalStep, verticalStep, left, top } = metrics;
    const maxRows = Math.max(1, ...layers.map((layer) => layer.nodes.length));
    const positions = new Map();
    const yearPositions = new Map();
    layers.forEach((layer, layerIndex) => {
      const x = left + layerIndex * horizontalStep;
      yearPositions.set(layer.year ?? "unknown", x);
      const offset = (maxRows - layer.nodes.length) / 2;
      layer.nodes.forEach((node, row) => {
        positions.set(node.paper_id, { x, y: top + (row + offset) * verticalStep, layer: layerIndex, row });
      });
    });
    return {
      positions,
      layers,
      yearPositions,
      width: Math.max(420, left * 2 + Math.max(0, layers.length - 1) * horizontalStep),
      height: Math.max(300, top * 2 + Math.max(1, maxRows - 1) * verticalStep),
      style,
      cards: style !== "dot",
      method: "weighted_layered_barycentric",
    };
  }

  function renderGraph({ fit = false } = {}) {
    if (!state.payload) return;
    const graph = activeGraph();
    const visibleYearCount = new Set(graph.nodes.map((node) => node.year).filter(Number.isFinite)).size;
    const style = graph.nodes.length <= 8
      ? "card"
      : graph.nodes.length <= 40 && state.mode !== "corpus"
        ? "compact"
        : graph.nodes.length <= 16 && visibleYearCount <= 10
          ? "compact"
          : "dot";
    state.layout = buildLayout(graph.nodes, graph.edges, style);
    dom.lanes.replaceChildren();
    dom.edges.replaceChildren();
    dom.nodes.replaceChildren();
    renderTimeGrid(state.layout);
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
      requestAnimationFrame(initialView);
      state.fitOnNextRender = false;
    } else {
      applyTransform();
    }
  }

  function renderTimeGrid(layout) {
    layout.layers.forEach((layer, index) => {
      const x = layout.yearPositions.get(layer.year ?? "unknown");
      if (index % 2) {
        const previousX = index ? layout.yearPositions.get(layout.layers[index - 1].year ?? "unknown") : x;
        const nextX = index + 1 < layout.layers.length ? layout.yearPositions.get(layout.layers[index + 1].year ?? "unknown") : x;
        dom.lanes.appendChild(svgEl("rect", {
          x: (previousX + x) / 2,
          y: 45,
          width: Math.max(0, (nextX - previousX) / 2),
          height: layout.height - 70,
          class: "time-band",
        }));
      }
      dom.lanes.appendChild(svgEl("line", { x1: x, y1: 42, x2: x, y2: layout.height - 22, class: "year-line" }));
      dom.lanes.appendChild(svgEl("text", { x, y: 28, "text-anchor": "middle", class: "year-label" }, layer.year ?? "N/A"));
    });
  }

  function edgePath(edge, layout) {
    const source = layout.positions.get(edge.source);
    const target = layout.positions.get(edge.target);
    if (!source || !target) return null;
    const horizontalGap = Math.abs(target.x - source.x);
    const offset = layout.style === "card" ? 91 : layout.style === "compact" ? 70 : 7;
    if (horizontalGap < 1) {
      const side = source.y <= target.y ? 1 : -1;
      const x = source.x + side * (layout.style === "card" ? 118 : layout.style === "compact" ? 88 : 25);
      const attach = source.x + side * offset;
      return {
        d: `M ${attach} ${source.y} C ${x} ${source.y}, ${x} ${target.y}, ${attach} ${target.y}`,
        mx: x,
        my: (source.y + target.y) / 2,
      };
    }
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
    nodes.forEach((node) => {
      const position = layout.positions.get(node.paper_id);
      if (!position) return;
      const primary = state.primaryNodeIds.has(node.paper_id);
      const hub = Boolean(node.metadata?.is_hub);
      const branchIndex = Math.max(0, (state.payload.auto_branches || []).findIndex((branch) => branch.paper_ids.includes(node.paper_id)));
      const group = svgEl("g", {
        class: `node-group${primary ? " primary-node" : ""}`,
        transform: `translate(${position.x} ${position.y})`,
        "data-paper-id": node.paper_id,
        tabindex: 0,
        role: "button",
        "aria-label": `${node.title}, ${node.year || "unknown year"}`,
      });
      group.style.setProperty("--node-color", primary ? BRANCH_COLORS[branchIndex % BRANCH_COLORS.length] : "#91a098");
      if (layout.style === "card") renderNodeCard(group, node, { primary, hub });
      else if (layout.style === "compact") renderNodeCompact(group, node, { primary, hub });
      else renderNodeDot(group, node, { primary, hub });
      group.addEventListener("click", (event) => { event.stopPropagation(); selectPaper(node.paper_id, false); });
      group.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") selectPaper(node.paper_id, false); });
      group.addEventListener("pointerenter", (event) => showPaperTooltip(event, node));
      group.addEventListener("pointerleave", hideTooltip);
      dom.nodes.appendChild(group);
    });
  }

  function renderNodeCard(group, node, { primary, hub }) {
    group.appendChild(svgEl("rect", { x: -91, y: -29, width: 182, height: 58, class: "node-card" }));
    group.appendChild(svgEl("rect", { x: -91, y: -29, width: 5, height: 58, rx: 3, class: "node-accent" }));
    group.appendChild(svgEl("text", { x: -77, y: -13, class: "node-year" }, node.year || "N/A"));
    if (hub) {
      group.append(svgEl("circle", { cx: 75, cy: -14, r: 8, class: "hub-ring" }), svgEl("text", { x: 75, y: -11, "text-anchor": "middle", class: "hub-star" }, "✦"));
    } else if (primary) {
      group.appendChild(svgEl("text", { x: 78, y: -11, "text-anchor": "end", class: "node-meta" }, "PRIMARY DAG"));
    }
    const lines = wrapTitle(paperDisplayTitle(node), 27, 2);
    lines.forEach((line, index) => group.appendChild(svgEl("text", { x: -77, y: 3 + index * 13, class: "node-title" }, line)));
    const citations = node.metadata?.citation_count;
    group.appendChild(svgEl("text", { x: 78, y: 20, "text-anchor": "end", class: "node-meta" }, `${citations ?? 0} cites`));
  }

  function renderNodeCompact(group, node, { primary, hub }) {
    group.appendChild(svgEl("rect", { x: -70, y: -22, width: 140, height: 44, class: "node-card compact-card" }));
    group.appendChild(svgEl("rect", { x: -70, y: -22, width: 4, height: 44, rx: 2, class: "node-accent" }));
    group.appendChild(svgEl("text", { x: -58, y: -8, class: "node-year" }, node.year || "N/A"));
    if (hub) {
      group.append(svgEl("circle", { cx: 57, cy: -8, r: 7, class: "hub-ring" }), svgEl("text", { x: 57, y: -5, "text-anchor": "middle", class: "hub-star" }, "✦"));
    } else if (primary) {
      group.appendChild(svgEl("text", { x: 61, y: -6, "text-anchor": "end", class: "node-meta" }, "SPINE"));
    }
    group.appendChild(svgEl("text", { x: -58, y: 10, class: "node-title compact-title" }, shortTitle(paperDisplayTitle(node), 22)));
  }

  function renderNodeDot(group, node, { primary, hub }) {
    group.appendChild(svgEl("circle", { cx: 0, cy: 0, r: hub ? 8 : primary ? 7 : 4.5, class: "node-dot" }));
    if (hub || primary || state.selected?.id === node.paper_id) {
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
      lineage: ["Technical genealogy", "Primary spine plus logical medium and strong relations"],
      evidence: ["Evidence map", "Logical evidence first; research-group links are optional"],
      corpus: ["Corpus overview", "All papers; relationship layers remain optional"],
    }[state.mode];
    const branch = (state.payload.auto_branches || []).find((item) => item.branch_id === state.branchFocus);
    $("#view-title").textContent = branch ? branch.label : copy[0];
    $("#view-subtitle").textContent = `${graph.nodes.length} papers · ${graph.edges.length} visible relations · weighted layered layout${branch ? " · auto path focus" : ""}`;
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
    const branch = state.payload.auto_branches.find((item) => item.branch_id === state.branchFocus);
    if (!branch) return renderEmptyInspector();
    const papers = branch.paper_ids.map((id) => state.nodeById.get(id)).filter(Boolean);
    const splitPaper = branch.split_paper_id ? state.nodeById.get(branch.split_paper_id) : null;
    const representatives = branch.representative_paper_ids.map((id) => state.nodeById.get(id)).filter(Boolean);
    dom.inspector.innerHTML = `<div style="--accent:#557b98">
      <div class="inspector-eyebrow">AUTO-DISCOVERED · ${branch.kind === "branch_cone" ? "BRANCH CONE" : "LINEAGE PATH"}</div>
      <h2 class="inspector-title">${escapeHtml(branch.label)}</h2>
      <p class="inspector-subtitle">${escapeHtml(branch.explanation)}</p>
      <div class="detail-chips">
        <span class="detail-chip parent">Evidence DAG derived</span>
        <span class="detail-chip">${papers.length} papers</span>
        <span class="detail-chip">${branch.edge_keys.length} display edges</span>
        <span class="detail-chip">${formatPct(branch.confidence)} minimum confidence</span>
      </div>
      ${splitPaper ? `<div class="inspector-section"><h3>DETECTED SPLIT POINT</h3><button class="branch-paper-button" data-paper-id="${escapeHtml(splitPaper.paper_id)}"><span>${splitPaper.year || "?"}</span><b>${escapeHtml(paperDisplayTitle(splitPaper))}</b><small>More than one non-redundant primary successor</small></button></div>` : ""}
      <div class="inspector-section"><h3>REPRESENTATIVE PAPERS</h3><div class="branch-paper-list">${representatives.map((paper) => `<button class="branch-paper-button" data-paper-id="${escapeHtml(paper.paper_id)}"><span>${paper.year || "?"}</span><b>${escapeHtml(paperDisplayTitle(paper))}</b><small>Grounded primary-DAG representative</small></button>`).join("")}</div></div>
      <div class="inspector-section"><h3>RELATION FAMILIES</h3><p class="explanation-copy">${branch.relation_types.length ? escapeHtml(branch.relation_types.map((item) => RELATION_LABELS[item] || item).join(" · ")) : "No typed primary relation is available."}</p></div>
    </div>`;
  }

  function renderEmptyInspector() {
    const summary = state.payload?.summary || {};
    dom.inspector.innerHTML = `<div class="empty-inspector">
      <div class="empty-hero">
        <div class="inspector-eyebrow">HOW TO READ</div>
        <h2>先看技术谱系，再沿主干追踪</h2>
        <p>默认图同时展示技术主干和有逻辑内容的中、强关联；纯引用与纯作者重合不会挤进主谱系。</p>
      </div>
      <div class="reading-guide">
        <div class="guide-row"><span class="guide-number">1</span><div><b>先看完整技术谱系</b><small>蓝色虚线是逻辑中关联，红色和深绿色是强关联。</small></div></div>
        <div class="guide-row"><span class="guide-number">2</span><div><b>沿深绿色主干追踪</b><small>深绿色边同时是 strong、parent-eligible 和 dominant。</small></div></div>
        <div class="guide-row"><span class="guide-number">3</span><div><b>平移查看，不强塞一屏</b><small>较大的图默认保持可读字号；拖动画布浏览，Fit 才会显示全局概览。</small></div></div>
      </div>
      <div class="run-stats">
        <div class="run-stat"><b>${summary.paper_count ?? "—"}</b><small>Papers</small></div>
        <div class="run-stat"><b>${summary.technical_lineage_paper_count ?? "—"}</b><small>Lineage papers</small></div>
        <div class="run-stat"><b>${summary.evidence_atom_count ?? "—"}</b><small>Evidence atoms</small></div>
        <div class="run-stat"><b>${summary.technical_lineage_edge_count ?? "—"}</b><small>Technical links</small></div>
      </div>
      <div class="inspector-section"><h3>CURRENT PRIMARY SPINE</h3><div class="connection-list">${renderPrimaryOverview()}</div></div>
    </div>`;
  }

  function renderPrimaryOverview() {
    return state.edges.filter((edge) => state.backboneEdgeKeys.has(edgeKey(edge))).map((edge) => {
      const source = state.nodeById.get(edge.source);
      const target = state.nodeById.get(edge.target);
      return `<button class="connection-button" data-edge-key="${escapeHtml(edgeKey(edge))}" style="--edge-color:#204b3e"><span class="connection-dot"></span><span class="connection-title">${escapeHtml(shortTitle(source ? paperDisplayTitle(source) : edge.source, 20))} → ${escapeHtml(shortTitle(target ? paperDisplayTitle(target) : edge.target, 20))}</span><span class="connection-level">${escapeHtml(RELATION_LABELS[edge.relation] || edge.relation)}</span></button>`;
    }).join("");
  }

  function renderPaperInspector(node) {
    if (!node) return renderEmptyInspector();
    const fulltext = state.payload.fulltext?.[node.paper_id];
    const connections = state.edges
      .filter((edge) => edge.source === node.paper_id || edge.target === node.paper_id)
      .sort((a, b) => Number(b.dominant) - Number(a.dominant) || LEVEL_RANK[b.association_level] - LEVEL_RANK[a.association_level] || Number(a.relation === "SAME_RESEARCH_GROUP") - Number(b.relation === "SAME_RESEARCH_GROUP") || b.confidence - a.confidence);
    const autoPaths = (state.payload.auto_branches || []).filter((branch) => branch.paper_ids.includes(node.paper_id));
    const doi = node.metadata?.doi;
    const openAlexId = node.paper_id.startsWith("OPENALEX:") ? node.paper_id.split(":")[1] : null;
    const links = [
      doi && `<a class="action-link" href="${escapeHtml(doi)}" target="_blank" rel="noreferrer">DOI</a>`,
      openAlexId && `<a class="action-link" href="https://openalex.org/${escapeHtml(openAlexId)}" target="_blank" rel="noreferrer">OpenAlex</a>`,
      fulltext?.local_path && `<a class="action-link" href="../${escapeHtml(fulltext.local_path)}" target="_blank">Local PDF</a>`,
      fulltext?.selected_url && `<a class="action-link" href="${escapeHtml(fulltext.selected_url)}" target="_blank" rel="noreferrer">Source PDF</a>`,
    ].filter(Boolean).join("");
    dom.inspector.innerHTML = `<div style="--accent:${escapeHtml(BRANCH_COLORS[Math.max(0, (state.payload.auto_branches || []).findIndex((branch) => branch.paper_ids.includes(node.paper_id))) % BRANCH_COLORS.length])}">
      <div class="inspector-eyebrow">PAPER · ${escapeHtml(node.paper_id)}</div>
      <h2 class="inspector-title">${escapeHtml(node.title)}</h2>
      <p class="inspector-subtitle">${escapeHtml([node.venue, node.year].filter(Boolean).join(" · ") || "Publication metadata unavailable")}</p>
      <div class="detail-chips">
        ${state.primaryNodeIds.has(node.paper_id) ? `<span class="detail-chip parent">Primary spine</span>` : ""}
        ${node.metadata?.is_hub ? `<span class="detail-chip parent">Hub · ${Number(node.metadata.hub_score || 0).toFixed(2)}</span>` : ""}
        <span class="detail-chip">${connections.length} in-corpus relations</span>
        ${fulltext ? `<span class="detail-chip parent">Full text verified</span>` : ""}
      </div>
      <div class="inspector-section"><h3>METADATA</h3><dl class="metadata-list">
        <dt>Year</dt><dd>${node.year || "Unknown"}</dd>
        <dt>Auto paths</dt><dd>${autoPaths.length ? escapeHtml(autoPaths.map((branch) => branch.label).join(" · ")) : "Not in the current primary path"}</dd>
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
    const paths = (state.payload.auto_branches || []).filter((branch) => branch.paper_ids.includes(node.paper_id)).length;
    showTooltip(event, `<b>${escapeHtml(node.title)}</b><small>${node.year || "Unknown year"} · ${paths} auto path${paths === 1 ? "" : "s"}<br>${node.metadata?.citation_count ?? 0} citations</small>`);
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

  function initialView() {
    if (!state.layout) return;
    const rect = dom.viewport.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const comfortablyFits = state.layout.width <= rect.width * 1.08
      && state.layout.height <= rect.height * 1.08;
    if (comfortablyFits) {
      fitView();
      return;
    }
    const scale = Math.min(1, Math.max(0.72, (rect.height - 80) / state.layout.height));
    let anchorId = state.selected?.type === "paper" ? state.selected.id : null;
    if (!anchorId && state.selected?.type === "edge") {
      anchorId = state.edgeByKey.get(state.selected.id)?.source || null;
    }
    if (!anchorId) {
      const backbone = state.edges.filter((edge) => state.backboneEdgeKeys.has(edgeKey(edge)));
      const targets = new Set(backbone.map((edge) => edge.target));
      anchorId = backbone
        .map((edge) => edge.source)
        .filter((paperId) => !targets.has(paperId))
        .sort((left, right) => (state.nodeById.get(left)?.year || 9999) - (state.nodeById.get(right)?.year || 9999))[0]
        || backbone[0]?.source
        || null;
    }
    const anchor = anchorId ? state.layout.positions.get(anchorId) : null;
    state.transform = {
      scale,
      x: anchor ? rect.width * 0.2 - anchor.x * scale : 24,
      y: Math.max(24, (rect.height - state.layout.height * scale) / 2),
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
