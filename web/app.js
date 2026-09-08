(() => {
  "use strict";

  const I18n = window.GenealogyI18n;
  const t = I18n.t;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const LEVEL_RANK = { weak: 0, medium: 1, strong: 2 };
  const LEVEL_LABEL = {
    weak: t("level.weak"), medium: t("level.medium"), strong: t("level.strong"),
  };
  const LEVEL_COLOR = { weak: "#a9b2ad", medium: "#3f78a8", strong: "#c85134" };
  const RELATION_LABELS = Object.fromEntries([
    "ADDRESSES_LIMITATION", "EXPLICIT_BASELINE", "IMPLICIT_BASELINE",
    "METHOD_DEPENDENCY", "USES_CONCEPT_FROM", "EXTENDS",
    "SAME_RESEARCH_GROUP", "KEY_AUTHOR_OVERLAP", "CITES",
  ].map((relation) => [relation, t(`relation.${relation}`)]));

  const state = {
    resultId: null,
    payload: null,
    nodes: [],
    edges: [],
    nodeById: new Map(),
    edgeByKey: new Map(),
    primaryNodeIds: new Set(),
    backboneEdgeKeys: new Set(),
    technicalEdgeKeys: new Set(),
    narrativeEdgeKeys: new Set(),
    mode: "lineage",
    layoutMode: "topology",
    showGroupEdges: false,
    selected: null,
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
      zoomReadout: $("#zoom-readout"),
    });
  }

  async function init() {
    setupDom();
    bindControls();
    try {
      const params = new URLSearchParams(window.location.search);
      const requestedResult = params.get("result");
      if (requestedResult && !/^[a-z0-9][a-z0-9-]{0,95}$/.test(requestedResult)) {
        throw new Error("Invalid result ID");
      }
      state.resultId = requestedResult;
      const primaryUrl = requestedResult
        ? `/api/results/${encodeURIComponent(requestedResult)}/inspector`
        : "./data/inspector.json";
      let response = await fetch(primaryUrl, { cache: "no-store" });
      if (!response.ok && requestedResult && response.status === 404) {
        response = await fetch(`../data/searches/${encodeURIComponent(requestedResult)}/inspector.json`, { cache: "no-store" });
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.payload = await response.json();
      state.nodes = state.payload.dag.nodes || [];
      state.edges = state.payload.dag.edges || [];
      state.nodeById = new Map(state.nodes.map((node) => [node.paper_id, node]));
      state.edgeByKey = new Map(state.edges.map((edge) => [edgeKey(edge), edge]));
      state.backboneEdgeKeys = new Set(state.payload.auto_branch_discovery?.backbone_edge_keys || []);
      state.technicalEdgeKeys = new Set(state.payload.auto_branch_discovery?.technical_edge_keys || []);
      state.narrativeEdgeKeys = new Set(
        state.payload.auto_branch_discovery?.narrative_edge_keys
        || state.payload.auto_branch_discovery?.technical_edge_keys
        || [],
      );
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
      dom.loading.innerHTML = `<div class="error-message"><b>${escapeHtml(t("inspector.loadError"))}</b><br>${escapeHtml(error.message)}<br><br>${escapeHtml(t("inspector.loadErrorHelp"))}</div>`;
    }
  }

  function populateChrome() {
    const { summary } = state.payload;
    $("#topic-title").textContent = state.payload.topic;
    $("#run-pill").textContent = `${summary.paper_count} papers · ${summary.edge_count} relations`;
    $("#lineage-paper-count").textContent = summary.narrative_lineage_paper_count ?? summary.technical_lineage_paper_count ?? "—";
    $("#lineage-edge-count").textContent = summary.narrative_lineage_edge_count ?? summary.technical_lineage_edge_count ?? "—";
    $("#primary-count").textContent = summary.display_primary_count ?? "—";
  }

  function applyInitialLocation() {
    const params = new URLSearchParams(window.location.search);
    const mode = params.get("mode");
    if (["lineage", "evidence", "corpus"].includes(mode)) {
      state.mode = mode;
      $$(".mode-button").forEach((item) => item.classList.toggle("active", item.dataset.mode === mode));
    }
    state.showGroupEdges = params.get("group") === "1";
    $("#group-layer").checked = state.showGroupEdges;
    if (params.get("layout") === "timeline") state.layoutMode = "timeline";
    const initialGraph = activeGraph();
    const visibleNodeIds = new Set(initialGraph.nodes.map((node) => node.paper_id));
    const visibleEdgeKeys = new Set(initialGraph.edges.map(edgeKey));
    const paperId = params.get("paper");
    if (paperId && visibleNodeIds.has(paperId)) state.selected = { type: "paper", id: paperId };
    const edgePair = params.get("edge")?.split(",");
    if (edgePair?.length === 2) {
      const key = `${edgePair[0]}→${edgePair[1]}`;
      if (visibleEdgeKeys.has(key)) state.selected = { type: "edge", id: key };
    }
  }

  function syncLocation() {
    const params = new URLSearchParams();
    if (I18n.language === "zh") params.set("lang", "zh");
    if (state.resultId) params.set("result", state.resultId);
    if (state.mode !== "lineage") params.set("mode", state.mode);
    if (state.showGroupEdges) params.set("group", "1");
    if (state.layoutMode !== "topology") params.set("layout", state.layoutMode);
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
        state.selected = null;
        state.fitOnNextRender = true;
        $$(".mode-button").forEach((item) => item.classList.toggle("active", item === button));
        syncLocation();
        renderInspector();
        renderGraph({ fit: true });
      });
    });

    $$(".layout-button").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled) return;
        state.layoutMode = button.dataset.layout;
        state.fitOnNextRender = true;
        syncLocation();
        renderGraph({ fit: true });
      });
    });

    $("#group-layer").addEventListener("change", (event) => {
      state.showGroupEdges = event.currentTarget.checked;
      if (state.selected?.type === "edge") state.selected = null;
      syncLocation();
      renderInspector();
      renderGraph({ fit: false });
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
      : `<div class="search-result"><small>${escapeHtml(t("inspector.noMatchingPaper"))}</small></div>`;
    dom.searchResults.hidden = false;
    dom.searchResults.querySelectorAll("[data-search-paper]").forEach((button) => {
      button.addEventListener("click", () => {
        dom.searchResults.hidden = true;
        dom.search.value = "";
        state.mode = "corpus";
        state.selected = null;
        $$(".mode-button").forEach((item) => item.classList.toggle("active", item.dataset.mode === "corpus"));
        renderGraph({ fit: true });
        selectPaper(button.dataset.searchPaper, true);
      });
    });
  }

  function activeGraph() {
    const baseEdges = state.mode === "lineage"
      ? state.edges.filter((edge) => state.narrativeEdgeKeys.has(edgeKey(edge)))
      : state.mode === "evidence"
        ? state.edges.filter((edge) => state.technicalEdgeKeys.has(edgeKey(edge)))
        : [...state.edges];
    const baseEdgeKeys = new Set(baseEdges.map(edgeKey));
    const baseNodeIds = new Set();
    if (state.mode === "corpus") {
      state.nodes.forEach((node) => baseNodeIds.add(node.paper_id));
    } else {
      baseEdges.forEach((edge) => {
        baseNodeIds.add(edge.source);
        baseNodeIds.add(edge.target);
      });
    }
    const groupEdges = state.edges.filter((edge) =>
      isResearchGroupEdge(edge)
      && baseNodeIds.has(edge.source)
      && baseNodeIds.has(edge.target)
    );
    const supplemental = state.showGroupEdges
      ? groupEdges.filter((edge) => !baseEdgeKeys.has(edgeKey(edge)))
      : [];
    return {
      edges: [...baseEdges, ...supplemental],
      layoutEdges: baseEdges,
      baseEdgeKeys,
      groupEdgeCount: groupEdges.length,
      nodes: state.nodes.filter((node) => baseNodeIds.has(node.paper_id)),
    };
  }

  function isResearchGroupEdge(edge) {
    return edge.relation === "SAME_RESEARCH_GROUP"
      || (edge.relation_types || []).includes("SAME_RESEARCH_GROUP")
      || (edge.relation_types || []).includes("KEY_AUTHOR_OVERLAP");
  }

  function displayEdge(edge) {
    if (state.showGroupEdges || !isResearchGroupEdge(edge)) return edge;
    const relationTypes = (edge.relation_types || []).filter((relation) =>
      !["KEY_AUTHOR_OVERLAP", "SAME_RESEARCH_GROUP"].includes(relation)
    );
    const logicalRelation = edge.relation === "SAME_RESEARCH_GROUP"
      ? relationTypes.find((relation) => relation !== "CITES") || "CITES"
      : edge.relation;
    return {
      ...edge,
      relation: logicalRelation,
      relation_types: relationTypes.length ? relationTypes : [logicalRelation],
      association_level: logicalRelation === "CITES" ? "weak" : edge.association_level,
      evidence_details: (edge.evidence_details || []).filter((atom) => atom.role !== "KEY_AUTHOR_OVERLAP"),
      explanation: logicalRelation === "CITES"
        ? "In-corpus citation. Enable the research-group overlay to inspect key-author overlap evidence."
        : edge.explanation,
    };
  }

  function edgeSemanticClass(edge) {
    const logicalRelation = edge.relation === "SAME_RESEARCH_GROUP"
      ? (edge.relation_types || []).find((relation) => !["CITES", "KEY_AUTHOR_OVERLAP", "SAME_RESEARCH_GROUP"].includes(relation)) || "CITES"
      : edge.relation;
    if (logicalRelation === "EXPLICIT_BASELINE") return "semantic-explicit";
    if (logicalRelation === "IMPLICIT_BASELINE") return "semantic-implicit";
    if (["METHOD_DEPENDENCY", "USES_CONCEPT_FROM", "EXTENDS"].includes(logicalRelation)) {
      return "semantic-inheritance";
    }
    if (logicalRelation === "ADDRESSES_LIMITATION") return "semantic-limitation";
    if (logicalRelation === "CITES") return "semantic-citation";
    if (edge.association_level === "medium") return "semantic-discussion";
    return "semantic-citation";
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

  function layoutMetrics(style, mode) {
    const metrics = {
      card: { horizontalStep: 236, verticalStep: 88, left: 135, top: 98 },
      compact: { horizontalStep: mode === "topology" ? 196 : 174, verticalStep: 66, left: 104, top: 82 },
      dot: { horizontalStep: mode === "topology" ? 84 : 72, verticalStep: 30, left: 65, top: 70 },
    };
    return metrics[style];
  }

  function distributedRow(index, count, rowSlots) {
    if (count <= 1) return (rowSlots - 1) / 2;
    const margin = count === 2 && rowSlots >= 5 ? 1 : 0.5;
    return margin + index * (rowSlots - 1 - margin * 2) / (count - 1);
  }

  function assignRouteLanes(edges, routePoints, positions, layers, metrics, rowSlots, style) {
    const result = new Map();
    const laneUsage = new Map();
    const halfHeight = style === "card" ? 29 : style === "compact" ? 22 : 8;
    const candidates = [];
    for (let slot = 0; slot <= rowSlots - 1; slot += 0.5) {
      candidates.push(metrics.top + slot * metrics.verticalStep);
    }
    [...edges]
      .sort((left, right) => (routePoints.get(edgeKey(right))?.length || 0) - (routePoints.get(edgeKey(left))?.length || 0))
      .forEach((edge) => {
        const routeIds = routePoints.get(edgeKey(edge)) || [];
        if (!routeIds.length) return;
        const crossedLayers = new Set(
          routeIds.map((id) => positions.get(id)?.layer).filter(Number.isFinite)
        );
        const source = positions.get(edge.source);
        const target = positions.get(edge.target);
        const preferred = ((source?.y || 0) + (target?.y || 0)) / 2;
        let best = null;
        candidates.forEach((candidate) => {
          let collisions = 0;
          crossedLayers.forEach((layerIndex) => {
            (layers[layerIndex]?.nodes || []).forEach((node) => {
              if (node.isDummy) return;
              const position = positions.get(node.paper_id);
              if (position && Math.abs(position.y - candidate) < halfHeight + 11) collisions += 1;
            });
          });
          const laneKey = Math.round(candidate / (metrics.verticalStep / 2));
          const score = collisions * 10000
            + Math.abs(candidate - preferred)
            + (laneUsage.get(laneKey) || 0) * 42;
          if (!best || score < best.score) best = { y: candidate, laneKey, score };
        });
        if (best) {
          result.set(edgeKey(edge), best.y);
          laneUsage.set(best.laneKey, (laneUsage.get(best.laneKey) || 0) + 1);
        }
      });
    return result;
  }

  function buildTimelineLayout(nodes, edges, style) {
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
        label: year === fallbackYear ? "N/A" : String(year),
        nodes: layerNodes.sort((a, b) => a.title.localeCompare(b.title)),
      }));
    const layerByPaper = new Map();
    layers.forEach((layer, index) => {
      layer.nodes.forEach((node) => layerByPaper.set(node.paper_id, index));
    });
    const routePoints = new Map();
    const segments = [];
    edges.forEach((edge, edgeIndex) => {
      const sourceLayer = layerByPaper.get(edge.source);
      const targetLayer = layerByPaper.get(edge.target);
      let previous = edge.source;
      const routeIds = [];
      if (Number.isFinite(sourceLayer) && Number.isFinite(targetLayer) && sourceLayer !== targetLayer) {
        const direction = targetLayer >= sourceLayer ? 1 : -1;
        for (
          let layerIndex = sourceLayer + direction;
          layerIndex !== targetLayer;
          layerIndex += direction
        ) {
          const dummyId = `__time_route__${edgeIndex}:${layerIndex}`;
          layers[layerIndex].nodes.push({ paper_id: dummyId, title: "", isDummy: true });
          segments.push({ ...edge, source: previous, target: dummyId });
          routeIds.push(dummyId);
          previous = dummyId;
        }
      }
      segments.push({ ...edge, source: previous, target: edge.target });
      routePoints.set(edgeKey(edge), routeIds);
    });
    minimizeLayerCrossings(layers, segments);

    const metrics = layoutMetrics(style, "timeline");
    const { horizontalStep, verticalStep, left, top } = metrics;
    const maxRows = Math.max(1, ...layers.map((layer) => layer.nodes.length));
    const rowSlots = Math.max(style === "dot" ? 6 : 6, maxRows);
    const positions = new Map();
    const layerPositions = new Map();
    layers.forEach((layer, layerIndex) => {
      const x = left + layerIndex * horizontalStep;
      layerPositions.set(layerIndex, x);
      layer.nodes.forEach((node, row) => {
        const slot = distributedRow(row, layer.nodes.length, rowSlots);
        positions.set(node.paper_id, { x, y: top + slot * verticalStep, layer: layerIndex, row: slot });
      });
    });
    const routeLanes = assignRouteLanes(
      edges,
      routePoints,
      positions,
      layers,
      metrics,
      rowSlots,
      style,
    );
    return {
      positions,
      layers,
      layerPositions,
      routePoints,
      routeLanes,
      width: Math.max(420, left * 2 + Math.max(0, layers.length - 1) * horizontalStep),
      height: Math.max(430, top * 2 + (rowSlots - 1) * verticalStep),
      style,
      cards: style !== "dot",
      mode: "timeline",
      method: "chronological_layers_with_virtual_edge_routes",
    };
  }

  function buildTopologyLayout(nodes, edges, style) {
    const nodeIds = new Set(nodes.map((node) => node.paper_id));
    const indegree = new Map(nodes.map((node) => [node.paper_id, 0]));
    const outgoing = new Map(nodes.map((node) => [node.paper_id, []]));
    edges.forEach((edge) => {
      if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) return;
      outgoing.get(edge.source).push(edge.target);
      indegree.set(edge.target, indegree.get(edge.target) + 1);
    });
    const nodeOrder = (left, right) =>
      (state.nodeById.get(left)?.year || 9999) - (state.nodeById.get(right)?.year || 9999)
      || (state.nodeById.get(left)?.title || left).localeCompare(state.nodeById.get(right)?.title || right);
    const queue = [...nodeIds].filter((id) => indegree.get(id) === 0).sort(nodeOrder);
    const topologicalOrder = [];
    const processed = new Set();
    while (queue.length) {
      const current = queue.shift();
      processed.add(current);
      topologicalOrder.push(current);
      (outgoing.get(current) || []).sort(nodeOrder).forEach((target) => {
        indegree.set(target, indegree.get(target) - 1);
        if (indegree.get(target) === 0) {
          queue.push(target);
          queue.sort(nodeOrder);
        }
      });
    }
    // Evidence extraction should produce a DAG. Keep a deterministic fallback
    // for malformed/cyclic overlays so the UI remains inspectable.
    [...nodeIds]
      .filter((id) => !processed.has(id))
      .sort(nodeOrder)
      .forEach((id) => topologicalOrder.push(id));

    // A longest-path rank makes every disconnected paper look like a Gen-1
    // ancestor.  Instead, start from evenly populated chronological columns
    // and move a paper right only when a detected dependency requires it.
    // Time is therefore a soft spatial prior, not a fixed x-axis.
    const chronological = [...nodes].sort((left, right) => nodeOrder(left.paper_id, right.paper_id));
    const baseColumnCount = Math.max(3, Math.min(6, Math.round(Math.sqrt(nodes.length * 1.35))));
    const columnByPaper = new Map();
    chronological.forEach((node, index) => {
      const column = Math.min(
        baseColumnCount - 1,
        Math.floor(index * baseColumnCount / Math.max(1, chronological.length)),
      );
      columnByPaper.set(node.paper_id, column);
    });
    topologicalOrder.forEach((source) => {
      (outgoing.get(source) || []).forEach((target) => {
        columnByPaper.set(
          target,
          Math.max(columnByPaper.get(target) || 0, (columnByPaper.get(source) || 0) + 1),
        );
      });
    });

    const maxColumn = Math.max(0, ...columnByPaper.values());
    const layers = Array.from({ length: maxColumn + 1 }, () => ({
      label: "",
      nodes: [],
    }));
    nodes.forEach((node) => layers[columnByPaper.get(node.paper_id)].nodes.push(node));
    layers.forEach((layer) => layer.nodes.sort((a, b) => nodeOrder(a.paper_id, b.paper_id)));
    minimizeLayerCrossings(layers, edges);

    const baseMetrics = layoutMetrics(style, "topology");
    const balancedLeft = style === "compact" ? 88 : baseMetrics.left;
    const targetWidth = style === "compact" ? 1088 : 1180;
    const balancedStep = layers.length <= 1
      ? baseMetrics.horizontalStep
      : Math.max(
        style === "compact" ? 152 : baseMetrics.horizontalStep * 0.82,
        Math.min(
          baseMetrics.horizontalStep,
          (targetWidth - balancedLeft * 2) / (layers.length - 1),
        ),
      );
    const metrics = {
      ...baseMetrics,
      horizontalStep: balancedStep,
      verticalStep: style === "compact" ? 112 : baseMetrics.verticalStep,
      left: balancedLeft,
      top: style === "compact" ? 72 : baseMetrics.top,
    };
    const { horizontalStep, verticalStep, left, top } = metrics;
    const maxRows = Math.max(1, ...layers.map((layer) => layer.nodes.length));
    // Empty outer slots double as routing gutters, keeping long lines from
    // passing through a card that happens to lie between their endpoints.
    const rowSlots = Math.max(5, maxRows + 1);
    const positions = new Map();
    const layerPositions = new Map();
    layers.forEach((layer, layerIndex) => {
      const x = left + layerIndex * horizontalStep;
      layerPositions.set(layerIndex, x);
      layer.nodes.forEach((node, row) => {
        const slot = distributedRow(row, layer.nodes.length, rowSlots);
        positions.set(node.paper_id, {
          x,
          y: top + slot * verticalStep,
          layer: layerIndex,
          row: slot,
        });
      });
    });

    // Virtual route points affect only the edge paths, not the number or
    // vertical distribution of visible papers in a column.
    const routePoints = new Map();
    edges.forEach((edge, edgeIndex) => {
      const sourceColumn = columnByPaper.get(edge.source);
      const targetColumn = columnByPaper.get(edge.target);
      const routeIds = [];
      if (Number.isFinite(sourceColumn) && Number.isFinite(targetColumn)) {
        const direction = targetColumn >= sourceColumn ? 1 : -1;
        for (
          let column = sourceColumn + direction;
          column !== targetColumn;
          column += direction
        ) {
          const routeId = `__route__${edgeIndex}:${column}`;
          routeIds.push(routeId);
          positions.set(routeId, {
            x: layerPositions.get(column),
            y: ((positions.get(edge.source)?.y || top) + (positions.get(edge.target)?.y || top)) / 2,
            layer: column,
            row: null,
          });
        }
      }
      routePoints.set(edgeKey(edge), routeIds);
    });
    const routeLanes = assignRouteLanes(
      edges,
      routePoints,
      positions,
      layers,
      metrics,
      rowSlots,
      style,
    );
    return {
      positions,
      layers,
      layerPositions,
      routePoints,
      routeLanes,
      width: Math.max(520, left * 2 + Math.max(0, layers.length - 1) * horizontalStep),
      height: Math.max(500, top * 2 + (rowSlots - 1) * verticalStep),
      style,
      cards: style !== "dot",
      mode: "topology",
      method: "balanced_temporal_topological_dag_with_obstacle_routes",
    };
  }

  function effectiveLayoutMode() {
    return state.mode === "corpus" ? "timeline" : state.layoutMode;
  }

  function updateLayoutControls(mode) {
    $$(".layout-button").forEach((button) => {
      button.classList.toggle("active", button.dataset.layout === mode);
      button.disabled = state.mode === "corpus" && button.dataset.layout === "topology";
    });
  }

  function renderGraph({ fit = false } = {}) {
    if (!state.payload) return;
    const graph = activeGraph();
    $("#group-count").textContent = graph.groupEdgeCount;
    const visibleYearCount = new Set(graph.nodes.map((node) => node.year).filter(Number.isFinite)).size;
    const style = graph.nodes.length <= 8
      ? "card"
      : graph.nodes.length <= 40 && state.mode !== "corpus"
        ? "compact"
        : graph.nodes.length <= 16 && visibleYearCount <= 10
          ? "compact"
          : "dot";
    const layoutMode = effectiveLayoutMode();
    state.layout = layoutMode === "topology"
      ? buildTopologyLayout(graph.nodes, graph.layoutEdges, style)
      : buildTimelineLayout(graph.nodes, graph.layoutEdges, style);
    updateLayoutControls(layoutMode);
    dom.lanes.replaceChildren();
    dom.edges.replaceChildren();
    dom.nodes.replaceChildren();
    renderLayerGrid(state.layout);
    renderEdges(graph.edges, state.layout, graph.baseEdgeKeys);
    renderNodes(graph.nodes, state.layout);
    updateViewSummary(graph);
    if (!state.selected) renderInspector();
    const app = $("#app");
    app.dataset.ready = "true";
    app.dataset.mode = state.mode;
    app.dataset.layout = layoutMode;
    app.dataset.visibleNodes = String(graph.nodes.length);
    app.dataset.visibleEdges = String(graph.edges.length);
    app.dataset.baseEdges = String(graph.layoutEdges.length);
    app.dataset.groupRelations = String(graph.groupEdgeCount);
    app.dataset.groupEnabled = String(state.showGroupEdges);
    app.dataset.layoutMethod = state.layout.method;
    app.dataset.layoutColumns = String(state.layout.layers.length);
    renderSelectionStyles();
    if (fit || state.fitOnNextRender) {
      requestAnimationFrame(initialView);
      state.fitOnNextRender = false;
    } else {
      applyTransform();
    }
  }

  function renderLayerGrid(layout) {
    layout.layers.forEach((layer, index) => {
      const x = layout.layerPositions.get(index);
      if (index % 2) {
        const previousX = index ? layout.layerPositions.get(index - 1) : x;
        const nextX = index + 1 < layout.layers.length ? layout.layerPositions.get(index + 1) : x;
        dom.lanes.appendChild(svgEl("rect", {
          x: (previousX + x) / 2,
          y: 45,
          width: Math.max(0, (nextX - previousX) / 2),
          height: layout.height - 70,
          class: "time-band",
        }));
      }
      if (layout.mode === "topology") return;
      dom.lanes.appendChild(svgEl("line", { x1: x, y1: 42, x2: x, y2: layout.height - 22, class: "year-line" }));
      dom.lanes.appendChild(svgEl("text", {
        x,
        y: 28,
        "text-anchor": "middle",
        class: "year-label",
      }, layer.label));
    });
  }

  function edgePath(edge, layout) {
    const source = layout.positions.get(edge.source);
    const target = layout.positions.get(edge.target);
    if (!source || !target) return null;
    const horizontalGap = Math.abs(target.x - source.x);
    const offset = layout.style === "card" ? 91 : layout.style === "compact" ? 70 : 7;
    const direction = target.x >= source.x ? 1 : -1;
    const routeLane = layout.routeLanes?.get(edgeKey(edge));
    const route = (layout.routePoints.get(edgeKey(edge)) || [])
      .map((id) => {
        const position = layout.positions.get(id);
        return position && Number.isFinite(routeLane) ? { ...position, y: routeLane } : position;
      })
      .filter(Boolean);
    if (route.length) {
      const points = [
        { x: source.x + direction * offset, y: source.y },
        ...route,
        { x: target.x - direction * offset, y: target.y },
      ];
      let d = `M ${points[0].x} ${points[0].y}`;
      for (let index = 1; index < points.length; index += 1) {
        const previous = points[index - 1];
        const current = points[index];
        const tangent = (current.x - previous.x) * 0.42;
        d += ` C ${previous.x + tangent} ${previous.y}, ${current.x - tangent} ${current.y}, ${current.x} ${current.y}`;
      }
      const middle = points[Math.floor(points.length / 2)];
      return { d, mx: middle.x, my: middle.y - 7 };
    }
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
    const sx = source.x + direction * offset;
    const tx = target.x - direction * offset;
    const span = Math.max(45, Math.abs(tx - sx) * 0.42);
    return {
      d: `M ${sx} ${source.y} C ${sx + direction * span} ${source.y}, ${tx - direction * span} ${target.y}, ${tx} ${target.y}`,
      mx: (sx + tx) / 2,
      my: (source.y + target.y) / 2 - 5,
    };
  }

  function renderEdges(edges, layout, baseEdgeKeys) {
    const isSupplemental = (edge) => !baseEdgeKeys.has(edgeKey(edge));
    const ordered = [...edges].sort((a, b) => Number(isSupplemental(b)) - Number(isSupplemental(a)) || LEVEL_RANK[a.association_level] - LEVEL_RANK[b.association_level] || Number(a.dominant) - Number(b.dominant));
    ordered.forEach((edge) => {
      const curve = edgePath(edge, layout);
      if (!curve) return;
      const key = edgeKey(edge);
      const supplemental = isSupplemental(edge);
      const group = svgEl("g", { class: "edge-group", "data-edge-key": key });
      const line = svgEl("path", {
        d: curve.d,
        class: `graph-edge ${edge.association_level} ${supplemental ? "semantic-group supplemental" : edgeSemanticClass(edge)}${edge.dominant ? " dominant" : ""}`,
        "data-edge-key": key,
      });
      const hit = svgEl("path", { d: curve.d, class: "edge-hit", "data-edge-key": key });
      [line, hit].forEach((element) => {
        element.addEventListener("click", (event) => { event.stopPropagation(); selectEdge(key); });
        element.addEventListener("pointerenter", (event) => showEdgeTooltip(event, edge));
        element.addEventListener("pointerleave", hideTooltip);
      });
      group.append(line);
      if (state.showGroupEdges && !supplemental && isResearchGroupEdge(edge)) {
        group.appendChild(svgEl("path", {
          d: curve.d,
          class: "graph-edge group-affiliation-overlay",
          "data-edge-key": key,
          "aria-hidden": "true",
        }));
      }
      group.append(hit);
      dom.edges.appendChild(group);
    });
  }

  function renderNodes(nodes, layout) {
    nodes.forEach((node) => {
      const position = layout.positions.get(node.paper_id);
      if (!position) return;
      const primary = state.primaryNodeIds.has(node.paper_id);
      const hub = Boolean(node.metadata?.is_hub);
      const group = svgEl("g", {
        class: `node-group${primary ? " primary-node" : ""}`,
        transform: `translate(${position.x} ${position.y})`,
        "data-paper-id": node.paper_id,
        tabindex: 0,
        role: "button",
        "aria-label": `${node.title}, ${node.year || "unknown year"}`,
      });
      group.style.setProperty("--node-color", primary ? "#476f5d" : "#91a098");
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
    group.appendChild(svgEl("text", { x: -58, y: -8, class: "node-year compact-year" }, node.year || "N/A"));
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
      lineage: ["Narrative genealogy", "Sparse strong-relation skeleton"],
      evidence: ["Evidence map", "Complete medium and strong evidence network"],
      corpus: ["Full citation graph", "All papers and in-corpus citation relations"],
    }[state.mode];
    const layoutCopy = effectiveLayoutMode() === "topology"
      ? "balanced DAG · topology + temporal prior"
      : "publication timeline · expanded vertical lanes";
    $("#view-title").textContent = copy[0];
    $("#view-subtitle").textContent = `${graph.nodes.length} papers · ${graph.edges.length} relations · ${layoutCopy}`;
  }

  function toggleSelection(type, id) {
    const alreadySelected = state.selected?.type === type && state.selected.id === id;
    state.selected = alreadySelected ? null : { type, id };
    return !alreadySelected;
  }

  function selectPaper(paperId, center) {
    if (!state.nodeById.has(paperId)) return;
    const selected = toggleSelection("paper", paperId);
    syncLocation();
    renderSelectionStyles();
    renderInspector();
    if (selected && center) requestAnimationFrame(() => centerOnPaper(paperId));
    if (selected && window.innerWidth <= 920) $(".inspector-panel").classList.add("open");
  }

  function selectEdge(key) {
    if (!state.edgeByKey.has(key)) return;
    const selected = toggleSelection("edge", key);
    syncLocation();
    renderSelectionStyles();
    renderInspector();
    if (selected && window.innerWidth <= 920) $(".inspector-panel").classList.add("open");
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
    if (!state.selected) {
      renderEmptyInspector();
      return;
    }
    if (state.selected.type === "paper") renderPaperInspector(state.nodeById.get(state.selected.id));
    else renderEdgeInspector(state.edgeByKey.get(state.selected.id));
  }

  function renderEmptyInspector() {
    const summary = state.payload?.summary || {};
    const graph = activeGraph();
    const prefix = `guide.${state.mode}`;
    const copy = {
      title: t(`${prefix}Title`),
      description: t(`${prefix}Description`),
      guides: [1, 2, 3].map((index) => [
        t(`${prefix}${index}Title`), t(`${prefix}${index}Detail`),
      ]),
    };
    dom.inspector.innerHTML = `<div class="empty-inspector">
      <div class="empty-hero">
        <div class="inspector-eyebrow">HOW TO READ</div>
        <h2>${copy.title}</h2>
        <p>${copy.description}</p>
      </div>
      <div class="reading-guide">
        ${copy.guides.map(([title, detail], index) => `<div class="guide-row"><span class="guide-number">${index + 1}</span><div><b>${title}</b><small>${detail}</small></div></div>`).join("")}
      </div>
      <div class="run-stats">
        <div class="run-stat"><b>${summary.paper_count ?? "—"}</b><small>Papers</small></div>
        <div class="run-stat"><b>${graph.nodes.length}</b><small>Visible papers</small></div>
        <div class="run-stat"><b>${summary.evidence_atom_count ?? "—"}</b><small>Evidence atoms</small></div>
        <div class="run-stat"><b>${graph.edges.length}</b><small>Visible links</small></div>
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

  function paperAuthorships(node) {
    const detailed = Array.isArray(node.metadata?.authorships)
      ? node.metadata.authorships.filter((author) => author && author.display_name)
      : [];
    if (detailed.length) {
      return detailed
        .map((author, fallbackIndex) => ({ ...author, fallbackIndex }))
        .sort((left, right) => {
          const leftIndex = Number.isFinite(Number(left.byline_index)) ? Number(left.byline_index) : left.fallbackIndex;
          const rightIndex = Number.isFinite(Number(right.byline_index)) ? Number(right.byline_index) : right.fallbackIndex;
          return leftIndex - rightIndex;
        });
    }
    const authorNames = Array.isArray(node.metadata?.authors) ? node.metadata.authors : [];
    return authorNames
      .filter(Boolean)
      .map((name, bylineIndex) => ({
        display_name: name,
        byline_index: bylineIndex,
        institutions: [],
        is_corresponding: false,
      }));
  }

  function renderAuthorshipMetadata(node) {
    const authors = paperAuthorships(node);
    if (!authors.length) {
      return `<div class="authorship-card"><div class="authorship-heading">${escapeHtml(t("metadata.authorsAffiliations"))}</div><p class="authorship-empty">${escapeHtml(t("metadata.authorsUnavailable"))}</p></div>`;
    }

    const institutions = [];
    const institutionIndexByKey = new Map();
    const indexInstitution = (institution) => {
      const name = String(institution?.display_name || "").trim();
      if (!name) return null;
      const institutionId = String(institution?.institution_id || "").trim();
      const key = institutionId || `name:${name.toLocaleLowerCase()}`;
      if (!institutionIndexByKey.has(key)) {
        institutionIndexByKey.set(key, institutions.length + 1);
        institutions.push({ name, institutionId });
      }
      return institutionIndexByKey.get(key);
    };

    const authorRows = authors.map((author) => {
      const affiliationIndices = [...new Set(
        (Array.isArray(author.institutions) ? author.institutions : []).map(indexInstitution).filter(Boolean),
      )];
      const affiliationNames = affiliationIndices.map((index) => institutions[index - 1].name);
      const affiliationRefs = affiliationIndices.length
        ? `<span class="author-affiliation-refs" title="${escapeHtml(affiliationNames.join("; "))}" aria-label="${escapeHtml(`${t("metadata.affiliations")}: ${affiliationNames.join("; ")}`)}">${affiliationIndices.map((index) => `<sup aria-hidden="true">${index}</sup>`).join("")}</span>`
        : `<span class="author-affiliation-missing" title="${escapeHtml(t("metadata.affiliationUnavailable"))}">—</span>`;
      return `<div class="author-row" role="listitem">
        <span class="author-identity"><span class="author-name">${escapeHtml(author.display_name)}</span>${author.is_corresponding ? `<span class="author-role">${escapeHtml(t("metadata.correspondingAuthor"))}</span>` : ""}</span>
        ${affiliationRefs}
      </div>`;
    });
    const previewLimit = 6;
    const hiddenAuthorCount = Math.max(0, authorRows.length - previewLimit);
    const overflow = hiddenAuthorCount
      ? `<details class="author-overflow"><summary>${escapeHtml(t("metadata.moreAuthors", { count: hiddenAuthorCount }))}</summary><div class="author-list author-list-more" role="list">${authorRows.slice(previewLimit).join("")}</div></details>`
      : "";
    const affiliationRows = institutions.map((institution, index) => `<li><span class="affiliation-index" aria-hidden="true">${index + 1}</span><span>${escapeHtml(institution.name)}</span></li>`);
    const affiliationPreviewLimit = 6;
    const hiddenAffiliationCount = Math.max(0, affiliationRows.length - affiliationPreviewLimit);
    const affiliationOverflow = hiddenAffiliationCount
      ? `<details class="affiliation-overflow"><summary>${escapeHtml(t("metadata.moreAffiliations", { count: hiddenAffiliationCount }))}</summary><ol class="affiliation-list affiliation-list-more" start="${affiliationPreviewLimit + 1}">${affiliationRows.slice(affiliationPreviewLimit).join("")}</ol></details>`
      : "";
    const affiliationList = institutions.length
      ? `<ol class="affiliation-list" aria-label="${escapeHtml(t("metadata.affiliations"))}">${affiliationRows.slice(0, affiliationPreviewLimit).join("")}</ol>${affiliationOverflow}`
      : `<p class="authorship-empty">${escapeHtml(t("metadata.affiliationsUnavailable"))}</p>`;

    return `<div class="authorship-card">
      <div class="authorship-heading">${escapeHtml(t("metadata.authorsAffiliations"))}</div>
      <div class="author-list" role="list">${authorRows.slice(0, previewLimit).join("")}</div>
      ${overflow}
      ${affiliationList}
    </div>`;
  }

  function renderPaperInspector(node) {
    if (!node) return renderEmptyInspector();
    const fulltext = state.payload.fulltext?.[node.paper_id];
    const connections = activeGraph().edges
      .filter((edge) => edge.source === node.paper_id || edge.target === node.paper_id)
      .map(displayEdge)
      .sort((a, b) => Number(b.dominant) - Number(a.dominant) || LEVEL_RANK[b.association_level] - LEVEL_RANK[a.association_level] || Number(a.relation === "SAME_RESEARCH_GROUP") - Number(b.relation === "SAME_RESEARCH_GROUP") || b.confidence - a.confidence);
    const doi = node.metadata?.doi;
    const openAlexId = node.paper_id.startsWith("OPENALEX:") ? node.paper_id.split(":")[1] : null;
    const links = [
      doi && `<a class="action-link" href="${escapeHtml(doi)}" target="_blank" rel="noreferrer">DOI</a>`,
      openAlexId && `<a class="action-link" href="https://openalex.org/${escapeHtml(openAlexId)}" target="_blank" rel="noreferrer">OpenAlex</a>`,
      fulltext?.local_path && `<a class="action-link" href="../${escapeHtml(fulltext.local_path)}" target="_blank">Local PDF</a>`,
      fulltext?.selected_url && `<a class="action-link" href="${escapeHtml(fulltext.selected_url)}" target="_blank" rel="noreferrer">Source PDF</a>`,
    ].filter(Boolean).join("");
    dom.inspector.innerHTML = `<div style="--accent:${state.primaryNodeIds.has(node.paper_id) ? "#476f5d" : "#557b98"}">
      <div class="inspector-eyebrow">PAPER · ${escapeHtml(node.paper_id)}</div>
      <h2 class="inspector-title">${escapeHtml(node.title)}</h2>
      <p class="inspector-subtitle">${escapeHtml([node.venue, node.year].filter(Boolean).join(" · ") || "Publication metadata unavailable")}</p>
      <div class="detail-chips">
        ${state.primaryNodeIds.has(node.paper_id) ? `<span class="detail-chip parent">Primary spine</span>` : ""}
        ${node.metadata?.is_hub ? `<span class="detail-chip parent">Hub · ${Number(node.metadata.hub_score || 0).toFixed(2)}</span>` : ""}
        <span class="detail-chip">${connections.length} visible relations</span>
        ${fulltext ? `<span class="detail-chip parent">Full text verified</span>` : ""}
      </div>
      <div class="inspector-section"><h3>METADATA</h3><dl class="metadata-list">
        <dt>Year</dt><dd>${node.year || "Unknown"}</dd>
        <dt>Citations</dt><dd>${node.metadata?.citation_count ?? "Unknown"}</dd>
        <dt>Open access</dt><dd>${node.metadata?.is_open_access ? "Yes" : "Not reported by OpenAlex"}</dd>
        ${fulltext ? `<dt>Full-text source</dt><dd>${escapeHtml(fulltext.selected_provider || "fallback")} · title score ${fulltext.title_score}</dd>` : ""}
      </dl>${renderAuthorshipMetadata(node)}</div>
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
    edge = displayEdge(edge);
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
    showTooltip(event, `<b>${escapeHtml(node.title)}</b><small>${node.year || "Unknown year"}<br>${node.metadata?.citation_count ?? 0} citations</small>`);
  }

  function showEdgeTooltip(event, edge) {
    edge = displayEdge(edge);
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
    if (state.layout.mode === "topology") {
      fitView();
      return;
    }
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
