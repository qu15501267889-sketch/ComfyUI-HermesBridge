/*
 * ComfyUI-HermesBridge — hermes_bridge.js（前端扩展入口）
 *
 * 通过官方 ComfyUI Extension 机制注册（app.registerExtension），在浏览器
 * 前端上下文内驱动真实 graph（全部官方 graph API，零鼠标/零DOM模拟）。
 *
 * 关键环境（Frontend 1.52.x 实测）：
 *   window.app                         应用实例（含 .graph）
 *   window.comfyAPI.app              官方模块暴露的 app（优先用这个）
 *   window.LiteGraph.registered_node_types  节点类注册表
 *
 * 扩展脚本本身是 ES module，但为避免旧 deprecation import，我们不依赖
 * `import "scripts/app.js"` —— 延迟到 setup 阶段从全局取 app 实例。
 */

(() => {
  const NS = "hermesBridge";
  const BASE = window.location.origin; // http://127.0.0.1:8188

  // ---- 延迟取 app（避免系统未就绪）----
    function getApp() {
      // 实测 1.52.7：驱动画布的真实实例是 window.app（含 .graph）。
      // window.comfyAPI.app 只是模块暴露，可能 graph 未初始化，仅作 fallback。
      try {
        if (window.app && window.app.graph) return window.app;
      } catch (_) {}
      try {
        if (window.app) return window.app;
      } catch (_) {}
      try {
        if (window.comfyAPI && window.comfyAPI.app && window.comfyAPI.app.graph) {
          return window.comfyAPI.app;
        }
      } catch (_) {}
      return null;
    }

  // 1.52: graphToPrompt/loadGraphData 挂在 graph service 上（app 或 app.graph 或其他）
  function getGraphSvc() {
    const app = getApp();
    const cands = [
      app,
      app && app.graph,
      app && app.graphService,
      window.comfyAPI && window.comfyAPI.app,
    ];
    for (const c of cands) {
      if (c && typeof c.graphToPrompt === "function" && c.rootGraph) return c;
    }
    for (const c of cands) {
      if (c && typeof c.graphToPrompt === "function") return c;
    }
    return null;
  }

  // 1.52 workflow store（Pinia）：app.extensionManager.workflow
  // —— 打开/保存"已命名标签"的正门（openWorkflow 是 tab 级操作）
  function getWfStore() {
    const app = getApp();
    try {
      const s = app && app.extensionManager && app.extensionManager.workflow;
      if (s && typeof s.openWorkflow === "function") return s;
    } catch (_) {}
    return null;
  }

  function wfKey(w) {
    return String((w && (w.name || w.filename || w.path)) || "").replace(/\.json$/i, "");
  }

  function findWfAsset(store, name) {
    const list = [].concat(store.workflows || [], store.persistedWorkflows || []);
    return {
      asset: list.find((w) => wfKey(w) === name)
          || list.find((w) => wfKey(w).endsWith("/" + name)) || null,
      names: list.slice(0, 30).map(wfKey),
    };
  }

  // ---- 🎛 组开关面板联动（HermesSwitchPanel → 目标组批量 mode 切换）----
  const PANEL_MAP = {
    "磨皮美颜组": [13],
    "瘦身组": [14, 15, 17, 18, 19, 20, 23, 24, 76, 77, 78],
    "背景组": [100, 101, 102, 105, 106, 107, 108, 110, 111, 112, 113, 114, 115, 117, 118],
    "光影组": [40, 41, 44, 45, 46, 47, 48, 81, 84],
    "质感风格组": [50, 52, 53, 54, 55, 56, 57, 82, 85],
  };

  // ---- 🎚 强度面板联动（HermesIntensityPanel → 各采样节点 denoise/strength）----
  // 滑块名 -> {nodeId, widget[,scale]}：滑块值直接写进该节点 widget。
  // 新增模块=在此加一行；widget 会在节点存在时更新。
  const INTENSITY_MAP = {
    "磨皮美颜强度": { node: 13, widget: "denoise", scale: 1.0 },
    "瘦身强度": { node: 18, widget: "denoise", scale: 1.0 },
    "背景替换强度": { node: 30, widget: "denoise", scale: 1.0 },
    "光影强度": { node: 40, widget: "strength", scale: 1.0 },
    "质感风格强度": { node: 50, widget: "denoise", scale: 1.0 },
  };

  function findNodeById(graph, id) {
    try { if (typeof graph.getNodeById === "function") { const n = graph.getNodeById(id); if (n) return n; } } catch (_) {}
    return (graph.nodes || []).find((n) => String(n.id) === String(id)) || null;
  }

  function syncSwitchPanel() {
    const app = getApp();
    if (!app || !app.graph) return;
    const graph = app.graph;
    const panel = (graph.nodes || []).find((n) => n.type === "HermesSwitchPanel");
    if (!panel || !Array.isArray(panel.widgets)) return;
    for (const [name, ids] of Object.entries(PANEL_MAP)) {
      const w = panel.widgets.find((x) => x.name === name);
      if (!w) continue;
      if (!w._hermesBound) {
        w._hermesBound = true;
        const orig = w.callback;
        w.callback = function (v, ...rest) {
          const on = !!v;
          for (const id of ids) {
            const t = findNodeById(graph, id);
            if (t) t.mode = on ? 0 : 4;
          }
          if (name === "背景组") {
            const m = findNodeById(graph, 120);   // 背景组主输出开关
            if (m) { const sw = (m.widgets || []).find((x) => x.name === "switch"); if (sw) sw.value = on; }
          }
          if (typeof orig === "function") { try { orig.call(w, v, ...rest); } catch (_) {} }
        };
      }
      // 状态反向同步：组内任一节点 mode=0 即视为"启用"
      const anyOn = ids.some((id) => { const t = findNodeById(graph, id); return t && t.mode === 0; });
      if (w.value !== anyOn) {
        w.value = anyOn;   // 直接赋值不触发 callback（避免回环）
        try { if (typeof graph.setDirtyCanvas === "function") graph.setDirtyCanvas(true, true); } catch (_) {}
      }
    }
  }

  // ---- 背景 A/B 互斥联动（117 ComfySwitchNode → 两路 mode）----
  // 117.switch=True(文生B) → 路A(102,108) mode=4; False(传图A) → 路B(110-115,118) mode=4
  function syncBgAbSwitch() {
    const app = getApp();
    if (!app || !app.graph) return;
    const graph = app.graph;
    const sw = (graph.nodes || []).find((n) => n.type === "ComfySwitchNode" && String(n.id) === "117");
    if (!sw || !Array.isArray(sw.widgets)) return;
    const w = sw.widgets.find((x) => x.name === "switch");
    if (!w) return;
    if (!w._hermesAbBound) {
      w._hermesAbBound = true;
      const orig = w.callback;
      w.callback = function (v, ...rest) {
        const useB = !!v;                 // true=文生背景
        [102, 108].forEach((id) => { const t = findNodeById(graph, id); if (t) t.mode = useB ? 4 : 0; });
        [110, 111, 112, 113, 114, 115, 118].forEach((id) => { const t = findNodeById(graph, id); if (t) t.mode = useB ? 0 : 4; });
        if (typeof orig === "function") { try { orig.call(w, v, ...rest); } catch (_) {} }
      };
    }
  }

  // ---- 简易 fetch JSON ----
  async function jget(path) {
    try {
      const r = await fetch(BASE + path);
      if (!r.ok) return null;
      const t = await r.text();
      return t ? JSON.parse(t) : {};
    } catch (e) { return null; }
  }
  async function jpost(path, body) {
    try {
      const r = await fetch(BASE + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      });
      return r.ok ? { ok: true } : { ok: false };
    } catch (e) { return { ok: false }; }
  }

  // ---- graph 简易序列化（供回报后端 / Hermes）----
  // 兼容两种 links 形态：数组（老 LiteGraph）与 对象map（新前端 1.52.x 以 id 为键）
  function linksArray(graph) {
    const l = graph.links;
    if (Array.isArray(l)) return l;
    if (l instanceof Map) return Array.from(l.values());
    if (l && typeof l === "object") return Object.values(l);
    return [];
  }

  function serializeGraph(graph) {
    const nodes = (graph.nodes || []).map((n) => ({
      id: n.id,
      type: n.type || null,
      title: n.title || null,
      pos: readPos(n),
      size: Array.isArray(n.size) ? [+n.size[0], +n.size[1]] : null,
      mode: n.mode,
      widget_values: (Array.isArray(n.widgets) && n.widgets.length)
        ? n.widgets.map((w) => w.value)
        : (Array.isArray(n.widgets_values) ? n.widgets_values : null),
      inputs: (n.inputs || []).map((i, k) => ({ index: k, name: i.name, type: i.type, link: i.link ?? null })),
      outputs: (n.outputs || []).map((o, k) => ({ index: k, name: o.name, type: o.type, links: Array.isArray(o.links) ? o.links : (o.links instanceof Map ? Array.from(o.links.values()) : []) })),
    }));
    const links = linksArray(graph).map((l) => ({
      id: l.id,
      origin_id: l.origin_id,
      origin_slot: l.origin_slot,
      target_id: l.target_id,
      target_slot: l.target_slot,
      type: l.type ?? null,
    }));
    return { nodes, links };
  }

  function graphHash(graph) {
    const s = JSON.stringify(serializeGraph(graph));
    let h = 0x811c9dc5;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return (h >>> 0).toString(16);
  }

  // ---- 在画布执行一条命令 ----
  async function executeCmd(graph, cmd) {
    const { type, data } = cmd;
    switch (type) {
      case "create_node": return createNode(graph, data);
      case "delete_node": return deleteNode(graph, data);
      case "move_node":   return moveNode(graph, data);
      case "update_node": return updateNode(graph, data);
      case "connect":     return connect(graph, data);
      case "disconnect":  return disconnect(graph, data);
      case "get_graph":   return { ok: true, data: serializeGraph(graph) };
      case "batch_graph_ops": return batchOps(graph, data);
      case "api_prompt":    return apiPrompt(graph, data);
      case "queue_prompt":  return queuePromptCmd(graph, data);
      case "save_workflow": return saveWorkflow(graph, data);
      case "load_workflow": return loadWorkflow(graph, data);
      case "open_workflow":  return openWfTab(graph, data);
      case "inspect_node":  return inspectNode(graph, data);
      case "inspect_wf_api": return inspectWfApi(graph, data);
      case "group_ops": return groupOps(graph, data);
      default: return { ok: false, error: "INVALID_COMMAND", message: `未知命令 ${type}` };
    }
  }

  // 批量操作：顺序执行，遇错即停并报告失败步骤（第一版不做自动回滚，
  // 已执行步骤保留在画布上，Hermes 可据 results 反向修复）。兼容两种入参：
  // {op, data:{...}} 与规格 §28 的扁平 {op, class_type, ...}。
  async function batchOps(graph, data = {}) {
    const ops = Array.isArray(data.operations) ? data.operations : [];
    if (!ops.length) return { ok: false, error: "INVALID_COMMAND", message: "operations 为空" };
    const results = [];
    for (let i = 0; i < ops.length; i++) {
      const op = ops[i] || {};
      const r = await executeCmd(graph, { type: op.op || op.type, data: op.data || op });
      results.push(r);
      if (!r.ok) {
        return { ok: false, error: r.error || "BATCH_FAILED",
                 message: `batch 第 ${i + 1}/${ops.length} 步失败: ${r.message || r.error}`,
                 data: { failed_at: i, results } };
      }
    }
    return { ok: true, data: { count: results.length, results } };
  }

  // ---- Phase 8: 导出 API-format prompt（POST /prompt 用）----
  // 打开已保存工作流到它的命名标签（纯 tab 切换，不灌数据）
  async function openWfTab(graph, data = {}) {
    const name = String(data.name || "").trim();
    if (!name) return { ok: false, error: "INVALID_ARGUMENT", message: "缺少 name" };
    const store = getWfStore();
    if (!store) return { ok: false, error: "WF_STORE_UNAVAILABLE", message: "workflow store 不可用" };
    try {
      const { asset, names } = findWfAsset(store, name);
      if (!asset) {
        return { ok: false, error: "WORKFLOW_NOT_FOUND_IN_STORE",
                 message: "前端 store 列表无此工作流: " + name,
                 data: { count: names.length, names } };
      }
      await store.openWorkflow(asset);
      return { ok: true, data: { name, via: "openWorkflow" } };
    } catch (e) {
      return { ok: false, error: "OPEN_FAILED", message: String(e) };
    }
  }

  // ---- 走前端自己的执行链（进度条/连线预览/任务队列 = 原生体验）----
  // 源码实证：queuePrompt 与 graphToPrompt 同一 service（getGraphSvc 可探测到）。
  // 外部 client_id 走 HTTP /prompt 时前端执行状态机不知情 → 无连线预览；
  // queuePrompt(1) = 前端自己的 clientId + WebSocket 事件链 → 全套原生反馈。
  async function queuePromptCmd(graph, data = {}) {
    const svc = getGraphSvc();
    const app = getApp();
    const target = (svc && typeof svc.queuePrompt === "function") ? svc
                 : (app && typeof app.queuePrompt === "function") ? app : null;
    if (!target) return { ok: false, error: "QUEUE_UNAVAILABLE", message: "queuePrompt 不可用" };
    try {
      const r = await target.queuePrompt(1);
      if (r === false) return { ok: false, error: "QUEUE_BUSY", message: "执行队列忙碌" };
      return { ok: true, data: { queued: true, result: (r === undefined ? null : r) } };
    } catch (e) {
      return { ok: false, error: "QUEUE_FAILED", message: String(e) };
    }
  }

  async function apiPrompt(graph, data = {}) {
    const svc = getGraphSvc();
    if (!svc) {
      const app = getApp();
      return { ok: false, error: "API_PROMPT_UNAVAILABLE", message: "graphToPrompt 不可用",
               data: { hasApp: !!app, appKeys: Object.keys(app || {}).filter((k) => /graph|workflow|prompt/i.test(k)) } };
    }
    try {
      const r = await svc.graphToPrompt(svc.rootGraph || graph);
      const out = r && (r.output || (r.prompt ? r.prompt : null)) || null;
      if (!out || typeof out !== "object") return { ok: false, error: "API_PROMPT_EMPTY", message: "graphToPrompt 无 output" };
      return { ok: true, data: { prompt: out, workflow: r.workflow || null } };
    } catch (e) {
      return { ok: false, error: "API_PROMPT_FAILED", message: String(e) };
    }
  }

  // ---- Phase 5: 存/读 workflow 文件（后端 user/default/workflows/*.json）----
  async function saveWorkflow(graph, data = {}) {
    const name = String(data.name || "").trim();
    if (!name) return { ok: false, error: "INVALID_ARGUMENT", message: "缺少 name" };
    let full = null;
    try { full = typeof graph.serialize === "function" ? graph.serialize() : null; } catch (_) {}
    if (!full) return { ok: false, error: "SERIALIZE_FAILED", message: "graph.serialize 不可用" };
    try {
      const r = await fetch(BASE + "/hermes_bridge/workflow/save", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, graph: full }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok && j.success) return { ok: true, data: { name: j.name } };
      return { ok: false, error: j.code || "SAVE_FAILED", message: j.message || ("HTTP " + r.status) };
    } catch (e) { return { ok: false, error: "SAVE_FAILED", message: String(e) }; }
  }

  async function loadWorkflow(graph, data = {}) {
    const name = String(data.name || "").trim();
    if (!name) return { ok: false, error: "INVALID_ARGUMENT", message: "缺少 name" };
    // FIX 2026-09-24 v2（重复画布 Bug 根治，源码实证 settingStore/activateLoadedWorkflow）：
    // loadGraphData(data, clean, restore_view, r) 第4参 r 决定 tab 归属：
    //   r=null → createNewTemporary() 新建"未保存的工作流(N)"临时 tab（=重复画布元凶）；
    //   r=字符串名 → 按 workflows/<名>.json 查已开 tab：已开→绑定去重，未开→以该名建 tab。
    // 故：先把目标名的已开 tab 激活（若已开且未激活），再以名字为绑定参数灌数据。
    let wf = null;
    try {
      const r = await fetch(BASE + "/hermes_bridge/workflow/load?name=" + encodeURIComponent(name));
      if (!r.ok) return { ok: false, error: "WORKFLOW_NOT_FOUND", message: "HTTP " + r.status };
      const j = await r.json().catch(() => null);
      wf = j && j.graph;
    } catch (e) { return { ok: false, error: "LOAD_FAILED", message: String(e) }; }
    if (!wf) return { ok: false, error: "WORKFLOW_EMPTY", message: "文件无 graph" };

    const bare = name.replace(/\.json$/i, "");
    let activated = false;
    try {
      const store = getWfStore();
      if (store && typeof store.openWorkflow === "function") {
        const tabs = [].concat(store.openWorkflows || []);
        let hit = tabs.find((w) => wfKey(w) === bare || wfKey(w).endsWith("/" + bare)) || null;
        if (!hit && typeof store.getWorkflowByPath === "function") {
          const dirs = [...new Set(tabs.map((w) => String((w && w.path) || "").replace(/[^/]+$/, "")).filter(Boolean))];
          for (const d of (dirs.length ? dirs : ["workflows/"])) {
            try { hit = store.getWorkflowByPath(d + bare + ".json"); } catch (_) {}
            if (hit) break;
          }
        }
        if (hit && typeof store.isActive === "function" && !store.isActive(hit)) {
          try { await store.openWorkflow(hit); activated = true; } catch (_) {}
        }
      }
    } catch (_) {}

    try {
      const svc = getGraphSvc();
      const app = getApp();
      if (svc && typeof svc.loadGraphData === "function") await svc.loadGraphData(wf, true, true, bare);
      else if (app && typeof app.loadGraphData === "function") await app.loadGraphData(wf, true, true, bare);
      else if (app && app.graph && typeof app.graph.configure === "function") app.graph.configure(wf);
      else return { ok: false, error: "LOAD_UNAVAILABLE", message: "loadGraphData 不可用" };
    } catch (e) { return { ok: false, error: "LOAD_FAILED", message: String(e) }; }
    return { ok: true, data: { name, via: activated ? "activate+bind-name" : "bind-name" } };
  }

  // ---- 诊断：节点对象形态（定位 pos 快照读 0 的根因）----
  function inspectNode(graph, data = {}) {
    const viaGet = getNode(graph, data.node_id);
    const viaArr = (graph.nodes || []).find((m) => m && String(m.id) === String(data.node_id)) || null;
    const desc = (obj, prop) => {
      try {
        const d = Object.getOwnPropertyDescriptor(obj, prop);
        if (d) return { own: true, kind: d.get ? "getter" : "data" };
        const p = Object.getPrototypeOf(obj);
        const d2 = p ? Object.getOwnPropertyDescriptor(p, prop) : null;
        return d2 ? { own: false, kind: d2.get ? "getter" : "data" } : "absent";
      } catch (e) { return "ERR:" + e; }
    };
    const probe = (n) => {
      if (!n) return null;
      const out = { ctor: n.constructor && n.constructor.name };
      try { out.x = n.x; out.y = n.y; } catch (e) { out.x = "ERR:" + e; }
      try { const p = n.pos; out.pos = Array.isArray(p) ? p.slice(0, 2) : String(p); } catch (e) { out.pos = "ERR:" + e; }
      try {
        const b = n.boundingRect;
        out.boundingRect = b ? { pos: (b.pos || []).slice ? b.pos.slice(0, 2) : String(b.pos), own: Object.getOwnPropertyDescriptor(n, "boundingRect") ? "own" : "proto" } : null;
      } catch (e) { out.boundingRect = "ERR:" + e; }
      out.desc = { x: desc(n, "x"), pos: desc(n, "pos"), boundingRect: desc(n, "boundingRect") };
      try { out.ownKeys = Object.keys(n).slice(0, 40); } catch (_) {}
      return out;
    };
    return {
      ok: true,
      data: {
        same_instance: viaGet === viaArr,
        via_getNode: probe(viaGet),
        via_graphNodes: probe(viaArr),
        graph_ctor: graph && graph.constructor && graph.constructor.name,
        graph_has_getNodeById: typeof (graph && graph.getNodeById),
        readPos_on_viaGet: viaGet ? readPos(viaGet) : null,
        readPos_on_viaArr: viaArr ? readPos(viaArr) : null,
      },
    };
  }

  // ---- 组框管理（模块化分组）：1.52 Group API 多路兼容 + 诊断回传 ----
  function groupOps(graph, data = {}) {
    const op = data.op || "add";
    const groupsOf = () => {
      if (Array.isArray(graph._groups)) return graph._groups;
      if (Array.isArray(graph.groups)) return graph.groups;
      try {
        const g = graph.groups;
        if (g && typeof g.values === "function") return Array.from(g.values());
      } catch (_) {}
      return [];
    };
    const detach = (g) => {
      try { if (typeof graph.remove === "function") { graph.remove(g); return; } } catch (_) {}
      try { if (graph._groups && Array.isArray(graph._groups)) { const i = graph._groups.indexOf(g); if (i >= 0) graph._groups.splice(i, 1); } } catch (_) {}
      try { if (graph.groups && Array.isArray(graph.groups)) { const i = graph.groups.indexOf(g); if (i >= 0) graph.groups.splice(i, 1); } } catch (_) {}
      try { if (graph.groups && typeof graph.groups.delete === "function") graph.groups.delete(g); } catch (_) {}
    };

    if (op === "clear") {
      const gs = groupsOf();
      const n = gs.length;
      gs.slice().forEach(detach);
      return { ok: true, data: { removed: n } };
    }
    if (op === "remove") {
      const title = String(data.title || "");
      const gs = groupsOf();
      const hit = gs.find((g) => String(g.title || "") === title);
      if (!hit) return { ok: false, error: "GROUP_NOT_FOUND", message: title,
                         data: { titles: gs.map((g) => String(g.title || "")) } };
      detach(hit);
      return { ok: true, data: { title } };
    }
    if (op === "list") {
      const gs = groupsOf();
      return { ok: true, data: { groups: gs.map((g) => ({
        title: String(g.title || ""),
        bounding: (() => { try { return (g.bounding || []).slice ? g.bounding.slice() : String(g.bounding); } catch (_) { return null; } })(),
      })) } };
    }

    // add（默认）
    const LG = window.LiteGraph;
    const GL = (LG && (LG.Group || LG.LGraphGroup)) || null;
    if (!GL) {
      const keys = LG ? Object.keys(LG).filter((k) => /group/i.test(k)) : [];
      return { ok: false, error: "GROUP_CLASS_UNAVAILABLE",
               message: JSON.stringify({ has_litegraph: !!LG, group_keys: keys,
                                         graph_group: (() => { try { return typeof graph.addGroup; } catch (_) { return "n/a"; } })() }),
               data: { litegraph_keys: keys } };
    }
    let g = null;
    const diag = {};
    try {
      g = new GL(String(data.title || "Group"));
      diag.ctor = g.constructor && g.constructor.name;
      diag.ownKeys = Object.keys(g).slice(0, 30);
      // bounding 多形态写入：bounding 数组 → _bounding → pos/size
      const b = Array.isArray(data.bounding) ? data.bounding : [0, 0, 400, 300];
      let wrote = false;
      try { if ("bounding" in g || Object.getOwnPropertyDescriptor(Object.getPrototypeOf(g) || {}, "bounding")) { g.bounding = b.slice(); wrote = true; diag.bounding_via = "setter/prop"; } } catch (e) { diag.bounding_err = String(e); }
      if (!wrote) { try { g._bounding = b.slice(); wrote = true; diag.bounding_via = "_bounding"; } catch (_) {} }
      try { if (g.pos && typeof g.pos === "object") { g.pos[0] = b[0]; g.pos[1] = b[1]; } } catch (_) {}
      try { g.x = b[0]; g.y = b[1]; g.width = b[2]; g.height = b[3]; } catch (_) {}
      if (data.color) { try { g.color = data.color; } catch (_) {} }
      // 入图多路
      let added = false;
      try { if (typeof graph.add === "function") { graph.add(g); added = true; diag.added_via = "graph.add"; } } catch (e) { diag.add_err = String(e); }
      if (!added) {
        try { if (typeof graph.addGroup === "function") { graph.addGroup(g); added = true; diag.added_via = "graph.addGroup"; } } catch (e) { diag.addGroup_err = String(e); }
      }
      if (!added) {
        try {
          if (Array.isArray(graph._groups)) { graph._groups.push(g); added = true; diag.added_via = "_groups.push"; }
          else if (Array.isArray(graph.groups)) { graph.groups.push(g); added = true; diag.added_via = "groups.push"; }
          else if (graph.groups && typeof graph.groups.add === "function") { graph.groups.add(g); added = true; diag.added_via = "groups.set"; }
        } catch (e) { diag.push_err = String(e); }
      }
      if (!added) return { ok: false, error: "GROUP_ADD_FAILED", data: diag };
      return { ok: true, data: { title: String(g.title || ""), added_via: diag.added_via,
                                 bounding_via: diag.bounding_via || null, ctor: diag.ctor } };
    } catch (e) {
      return { ok: false, error: "GROUP_ADD_EXCEPTION", message: String(e), data: diag };
    }
  }

  // ---- 诊断：workflow 服务/商店 API（定位"加载进已有测试1标签"的正门）----
  function inspectWfApi() {
    const app = getApp();
    const out = { window_keys: [], app_keys: [], service_probe: {} };
    try {
      out.window_keys = Object.getOwnPropertyNames(window)
        .filter((k) => /workflow|service|store|pinia/i.test(k));
    } catch (_) {}
    try {
      out.app_keys = Object.keys(app || {})
        .filter((k) => /workflow|service|store|tab|graph/i.test(k));
    } catch (_) {}
    const cands = {
      window_useWorkflowService: typeof window.useWorkflowService,
      app_workflowService: app && typeof app.workflowService,
      app_workflow: app && typeof app.workflow,
      ext_manager: typeof (window.app && window.app.extensionManager),
      ext_workflow: typeof (window.app && window.app.extensionManager && window.app.extensionManager.workflow),
      pinia: typeof window.__PINIA__,
      comfyAPI_keys: window.comfyAPI ? Object.keys(window.comfyAPI) : null,
    };
    out.service_probe = cands;
    // extensionManager.workflow 的可用方法（如果存在）
    try {
      const w = window.app && window.app.extensionManager && window.app.extensionManager.workflow;
      if (w) out.ext_workflow_keys = Object.getOwnPropertyNames(Object.getPrototypeOf(w) || {}).concat(Object.keys(w)).slice(0, 40);
    } catch (_) {}
    // 试调 useWorkflowService（若全局暴露）
    try {
      if (typeof window.useWorkflowService === "function") {
        const svc = window.useWorkflowService();
        out.svc_keys = Object.keys(svc || {}).slice(0, 50);
        out.svc_proto = svc ? Object.getOwnPropertyNames(Object.getPrototypeOf(svc) || {}).slice(0, 50) : null;
      }
    } catch (e) { out.svc_err = String(e); }
    return { ok: true, data: out };
  }

  function nodeClassFor(typeName) {
    const t = window.LiteGraph && window.LiteGraph.registered_node_types
        ? window.LiteGraph.registered_node_types[typeName] : null;
    return (t && typeof t === "function") ? t : null;
  }

  function num(v, d) { const n = Number(v); return Number.isFinite(n) ? n : (d ?? 0); }

  // 宽松按 id 找节点：兼容数字 / 字符串 id（新前端节点 id 可能是 string）
  function getNode(graph, id) {
    if (id === undefined || id === null) return null;
    // 1) 数字匹配
    const numId = Number(id);
    if (Number.isFinite(numId)) {
      const n = graph.getNodeById(numId);
      if (n) return n;
    }
    // 2) 字符串匹配
    const sId = String(id);
    if (graph.getNodeById && sId) {
      const n2 = graph.getNodeById(sId);
      if (n2) return n2;
    }
    // 3) 遍历 nodes 匹配（兜底，处理 id 类型歧义）
    const nodes = graph.nodes || [];
    for (let i = 0; i < nodes.length; i++) {
      const nn = nodes[i];
      if (nn && String(nn.id) === sId) return nn;
    }
    return null;
  }

  function nextNodeId(graph) {
    let max = 0;
    (graph.nodes || []).forEach((n) => { if (n.id > max) max = n.id; });
    return max + 1;
  }

  // 1.52 ComfyNode 坐标是自定义 vec2 类（实测）：
  //   - n.pos 与 graph.serialize() 同源 = **坐标真值**（save 文件即证据）
  //   - boundingRect.pos 是派生渲染框（y 比真值小约 30，add 时按 pos 重算）→ 只作兜底
  //   - v[0]/v[1] 下标可访问、toString()="x,y"，但 Array.isArray() 为 false
  // 读取顺序：pos（真值）→ boundingRect → x/y，非全0优先。
  function readPos(n) {
    const grab = (v) => {
      if (v == null) return null;
      try {
        const a = +v[0], b = +v[1];
        return Number.isFinite(a) && Number.isFinite(b) ? [a, b] : null;
      } catch (_) { return null; }
    };
    let p = null;
    try { p = grab(n.pos); } catch (_) {}
    if (p && (p[0] !== 0 || p[1] !== 0)) return p;
    try { p = grab(n.boundingRect && n.boundingRect.pos); } catch (_) {}
    if (p && (p[0] !== 0 || p[1] !== 0)) return p;
    const ax = +n.x, ay = +n.y;
    if (Number.isFinite(ax) && Number.isFinite(ay) && (ax !== 0 || ay !== 0)) return [ax, ay];
    // 节点真在原点：给出真 0
    try { p = grab(n.pos); if (p) return p; } catch (_) {}
    try { p = grab(n.boundingRect && n.boundingRect.pos); if (p) return p; } catch (_) {}
    return [0, 0];
  }

  function setPos(node, x, y) {
    // 1.52 双存储：x/y（传统 LiteGraph 链）+ pos/boundingRect（新几何存储）
    // 必须三路全写，否则 save 文件与快照读到不同坐标。
    const px = num(x, 0), py = num(y, 0);
    node.x = px;
    node.y = py;
    try {
      if (node.pos && typeof node.pos === "object") { node.pos[0] = px; node.pos[1] = py; }
    } catch (_) {}
    try {
      const br = node.boundingRect;
      if (br && br.pos) { br.pos[0] = px; br.pos[1] = py; }
    } catch (_) {}
  }

  function createNode(graph, data = {}) {
    const Klass = nodeClassFor(data.class_type);
    if (!Klass) return { ok: false, error: "NODE_TYPE_NOT_FOUND", message: `节点类型未注册: ${data.class_type}` };
    const node = new Klass(data.title || data.class_type);
    node.type = data.class_type;   // 显式设置 type —— 构造后 LiteGraph 不会自动填
    node.id = num(data.node_id, nextNodeId(graph));
    if (Array.isArray(data.position) && data.position.length >= 2) {
      setPos(node, data.position[0], data.position[1]);
    }
    // widgets 在 add 之前设置（保证 add 后 widget 即生效）
    if (data.widgets && typeof data.widgets === "object") {
      for (const [k, v] of Object.entries(data.widgets)) {
        const w = (node.widgets || []).find((w) => w.name === k);
        if (w) w.value = v;
      }
    }
    graph.add(node);
    return {
      ok: true,
      node_id: node.id,
      type: node.type,
      pos: [num(node.x, 0), num(node.y, 0)],
    };
  }

  function deleteNode(graph, data = {}) {
    const node = getNode(graph, data.node_id);
    if (!node) return { ok: false, error: "NODE_NOT_FOUND", message: `节点 ${data.node_id} 不存在` };
    graph.remove(node);
    return { ok: true, node_id: node.id };
  }

  function moveNode(graph, data = {}) {
    const node = getNode(graph, data.node_id);
    if (!node) return { ok: false, error: "NODE_NOT_FOUND", message: `节点 ${data.node_id} 不存在` };
    if (Array.isArray(data.position) && data.position.length >= 2) {
      setPos(node, data.position[0], data.position[1]);
    }
    return { ok: true, node_id: node.id, pos: readPos(node) };
  }

  function updateNode(graph, data = {}) {
    const node = getNode(graph, data.node_id);
    if (!node) return { ok: false, error: "NODE_NOT_FOUND", message: `节点 ${data.node_id} 不存在` };
    const out = { ok: true, node_id: node.id };
    if (data.widgets && typeof data.widgets === "object") {
      for (const [k, v] of Object.entries(data.widgets)) {
        const w = (node.widgets || []).find((w) => w.name === k);
        if (w) {
          w.value = v;
          try { if (typeof w.callback === "function") w.callback(v, w, node); } catch (_) {}
        }
      }
      // 同步缓存数组（widgets_values 是序列化缓存，不刷新会读回旧值）
      if (Array.isArray(node.widgets)) node.widgets_values = node.widgets.map((x) => x.value);
    }
    if (data.title != null) node.title = String(data.title);
    if (data.mode != null) node.mode = Number(data.mode);
    return out;
  }

  function connect(graph, data = {}) {
    const a = getNode(graph, data.from ? data.from.node_id : null);
    const b = getNode(graph, data.to ? data.to.node_id : null);
    if (!a || !b) return { ok: false, error: "NODE_NOT_FOUND", message: "端点节点不存在" };
    try {
      // frontend 1.52 fork 实测签名（见 comfyui_frontend_package 静态源码）：
      //   connect(output_slot, target_node, input_slot) —— 发起方是输出节点！
      // （老 litegraph 是 目标.connect(输入槽, 源节点, 输出槽)，方向相反）
      a.connect(Number(data.from.slot), b, Number(data.to.slot));
    } catch (e) {
      return { ok: false, error: "CONNECT_FAILED", message: String(e) };
    }
    // frontend 1.52: connect 返回值不稳定 —— 以目标输入槽的 link 登记为准
    const inp = b.inputs && b.inputs[Number(data.to.slot)];
    if (!inp || inp.link == null) {
      return { ok: false, error: "CONNECT_FAILED", message: "连接未登记到目标槽（槽位或类型不匹配）" };
    }
    return { ok: true, link_id: inp.link };
  }

  function disconnect(graph, data = {}) {
    const id = Number(data.link_id);
    const lk = linksArray(graph).find((l) => l.id === id);
    if (!lk) return { ok: false, error: "NODE_NOT_FOUND", message: `link ${id} 不存在` };
    const tgt = getNode(graph, lk.target_id);
    if (!tgt) return { ok: false, error: "NODE_NOT_FOUND", message: "目标节点不存在" };
    tgt.disconnectInput(lk.target_slot);
    return { ok: true, link_id: id };
  }

  // ---- 主轮询 ----
  let running = false;
  async function poll() {
    if (running) return;
    running = true;
    try {
      const app = getApp();
      if (!app || !app.graph) { return; }
      const cmd = await jget("/hermes_bridge/poll");
      if (cmd && cmd.command_id && cmd.type) {
        const res = await executeCmd(app.graph, cmd);
        const { ok, error, message, data: d, ...rest } = res;
        await jpost("/hermes_bridge/result", {
          command_id: cmd.command_id,
          success: !!ok,
          data: ok ? (d !== undefined && d !== null ? d : rest) : null,
          error: ok ? null : { code: error || "COMMAND_FAILED", message: message || "",
                               data: (d !== undefined && d !== null) ? d : undefined },
          origin: "comfyui",
        });
      }
    } catch (_e) {
      /* 静默 */
    } finally {
      running = false;
    }
  }

  // ---- 画布状态周期回报 ----
  async function syncGraph() {
    const app = getApp();
    if (!app || !app.graph) return;
    await jpost("/hermes_bridge/graph", {
      graph: serializeGraph(app.graph),
      graph_hash: graphHash(app.graph),
      ts: Date.now(),
    });
  }

  // ---- 自启动：等待 app.graph 就绪后开始轮询 ----
  // 不依赖 app.registerExtension 的 setup 生命周期（各版本时机不稳定），
  // 直接在模块顶层探测 window.app.graph 就绪，然后启动命令轮询 + 状态回报。
  let started = false;

  function tick() {
    const app = getApp();
    if (!app || !app.graph) {
      setTimeout(tick, 800);
      return;
    }
    if (!started) {
      started = true;
      console.log("[HermesBridge] 画布就绪，启动双向轮询");
      setInterval(poll, 1200);
      setInterval(syncGraph, 2500);
      function syncSwitchPanelIntensity() {
    const app = getApp();
    if (!app || !app.graph) return;
    const graph = app.graph;
    const panel = (graph.nodes || []).find((n) => n.type === "HermesIntensityPanel");
    if (!panel || !Array.isArray(panel.widgets)) return;
    for (const [name, cfg] of Object.entries(INTENSITY_MAP)) {
      const w = panel.widgets.find((x) => x.name === name);
      if (!w) continue;
      if (!w._hermesIntenBound) {
        w._hermesIntenBound = true;
        const orig = w.callback;
        w.callback = function (v, ...rest) {
          const target = findNodeById(graph, cfg.node);
          if (target) {
            const tw = (target.widgets || []).find((x) => x.name === cfg.widget);
            if (tw) tw.value = cfg.scale * Number(v);
          }
          if (typeof orig === "function") { try { orig.call(w, v, ...rest); } catch (_) {} }
        };
      }
    }
  }
      setInterval(syncSwitchPanel, 800);
      setInterval(syncSwitchPanelIntensity, 800);
      setInterval(syncBgAbSwitch, 800);
    }
  }

  // 暴露 adapter 供调试
  window.hermesBridge = window.hermesBridge || {};
  window.hermesBridge.execute = (type, data) => {
    const app = getApp();
    if (!app || !app.graph) return { ok: false, code: "BRIDGE_NOT_READY" };
    return executeCmd(app.graph, { type, data });
  };
  window.hermesBridge.getApp = getApp;
  window.hermesBridge.serialize = serializeGraph;
  window.hermesBridge.debug = () => ({
    ns: typeof window.hermesBridge, started,
    hasApp: !!getApp(),
    hasGraph: !!(getApp() && getApp().graph),
    polling: started,
    nodeCount: getApp() && getApp().graph ? getApp().graph.nodes.length : null,
  });

  tick();
})();