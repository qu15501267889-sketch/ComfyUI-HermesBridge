# -*- coding: utf-8 -*-
"""Hermes <-> ComfyUI 双向 Bridge MCP server（全新实现）。

驱动 ComfyUI-HermesBridge 后端桥 + 前端扩展，让 Hermes 经由官方 graph API
操作画布（create/delete/move/update/connect），无需任何浏览器自动化。

依赖：
  - 后端桥已注册（custom_nodes/ComfyUI-HermesBridge，/hermes_bridge/*）
  - Hermes 环境装有 `mcp` 包

用法（配置 mcp_servers）：
  command: C:\\Users\\user\\.hermes-web-ui\\desktop-runtime\\hermes\\0.20.0\\win-x64\\python\\venv\\Scripts\\python.exe
  args:    ["C:\\Users\\user\\comfyui_hermes_server.py"]
  env:     COMFY_URL=http://127.0.0.1:8188
"""

import asyncio
import json
import os
import urllib.parse
import urllib.request

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

TARGET = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
BRIDGE = TARGET + "/hermes_bridge"

app = Server("comfyui_hermes")


def _http(method: str, path: str, body=None, timeout: float = 40.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        TARGET + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


def _bridge(method: str, path: str, body=None, timeout: float = 40.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BRIDGE + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


def _http_raw(method: str, path: str, body=None, timeout: float = 60.0):
    """带状态码的 HTTP（Manager 端点 4xx/5xx 也要读 body 判断原因）。"""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        TARGET + path, data=data,
        headers={"Content-Type": "application/json"} if data else {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode()
        except Exception:
            return e.code, str(e.reason)
    except Exception as e:
        return 0, str(e)


_NODE_LIST_CACHE = {}


def _resolve_node_meta(keyword: str):
    """本地 custom-node-list.json 按 title 精确/包含匹配（绕开 getlist 端点）。
    返回 {title, files, install_type, matched}；找不到 matched=False 并带候选。"""
    if not _NODE_LIST_CACHE:
        lp = r"D:\AI\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-Manager\custom-node-list.json"
        try:
            with open(lp, encoding="utf-8") as f:
                _NODE_LIST_CACHE["nodes"] = json.load(f).get("custom_nodes", [])
        except Exception:
            _NODE_LIST_CACHE["nodes"] = []
    nodes = _NODE_LIST_CACHE.get("nodes") or []
    kw = (keyword or "").strip().lower()
    exact = [n for n in nodes if str(n.get("title", "")).lower() == kw]
    fuzzy = [n for n in nodes if kw and kw in str(n.get("title", "")).lower()]
    hit = (exact or fuzzy)
    if hit:
        n = hit[0]
        return {"matched": True, "title": n.get("title"),
                "files": n.get("files", []), "install_type": n.get("install_type"),
                "candidates": [str(x.get("title")) for x in hit[:5]]}
    return {"matched": False, "keyword": keyword, "candidates": []}


def _poll_manager_queue(timeout: float):
    """轮询 /manager/queue/status 直到队列空闲。"""
    import time as _t
    deadline = _t.time() + timeout
    last = None
    while _t.time() < deadline:
        st = _http("GET", "/manager/queue/status")
        last = st
        if (not st.get("is_processing")
                and not st.get("in_progress_count")
                and st.get("total_count", 0) == st.get("done_count", 0)):
            return st
        _t.sleep(2)
    return {"timeout": True, **(last or {})}


def _manager_enqueue(path: str, body: dict, timeout: float = 600.0):
    """Manager 队列三步：enqueue → start → poll。"""
    code, txt = _http_raw("POST", path, body)
    if code != 200:
        return {"ok": False, "stage": "enqueue", "status": code, "body": txt[:400]}
    scode, stxt = _http_raw("POST", "/manager/queue/start", {})
    if scode not in (200, 201):
        return {"ok": False, "stage": "start", "status": scode, "body": stxt[:400]}
    st = _poll_manager_queue(timeout)
    if st.get("timeout"):
        return {"ok": False, "stage": "poll", "error": "timeout", "status": st}
    return {"ok": True, "queue_status": st}


def _custom_nodes_dirs():
    root = r"D:\AI\ComfyUI_windows_portable\ComfyUI\custom_nodes"
    try:
        return set(os.listdir(root))
    except Exception:
        return set()


def _validate_workflow_impl():
    """Phase 9 图校验：类型匹配/必需输入/环/输出节点/模型文件存在。"""
    gs = _bridge("GET", "/graph")
    if not (gs or {}).get("ok"):
        return {"valid": False, "errors": [{"code": "NO_GRAPH", "msg": "画布无快照（前端未上报）"}]}
    g = gs["graph"]
    oi = _http("GET", "/object_info")
    errors, warnings = [], []
    nodes = {n["id"]: n for n in g.get("nodes", [])}

    # 1) link 存在性 + 类型匹配
    for l in g.get("links", []):
        a, b = nodes.get(l.get("origin_id")), nodes.get(l.get("target_id"))
        if not a or not b:
            errors.append({"code": "LINK_DANGLING", "link": l.get("id"),
                           "msg": f"link {l.get('id')} 端点节点不存在"})
            continue
        outs = a.get("outputs") or []
        ins = b.get("inputs") or []
        os_, ts_ = l.get("origin_slot"), l.get("target_slot")
        if os_ >= len(outs) or ts_ >= len(ins):
            errors.append({"code": "SLOT_OOB", "link": l.get("id"),
                           "msg": f"link {l.get('id')} 槽位越界"})
            continue
        lt, it = l.get("type"), ins[ts_].get("type")
        if lt and it and lt != it and "*" not in (str(lt), str(it)):
            errors.append({"code": "TYPE_MISMATCH", "link": l.get("id"),
                           "msg": f"{a['type']}.{outs[os_].get('name')}({lt}) -> "
                                  f"{b['type']}.{ins[ts_].get('name')}({it}) 类型不匹配"})

    # 2) 必需输入（纯连接项必须已连）+ 3) 未知类型
    for n in g.get("nodes", []):
        defn = oi.get(n.get("type"))
        if not defn:
            warnings.append({"code": "UNKNOWN_TYPE", "node": n.get("id"),
                             "msg": f"节点类型不在注册表: {n.get('type')}"})
            continue
        req = (defn.get("input") or {}).get("required", {})
        ins = {i.get("name"): i for i in (n.get("inputs") or [])}
        for k, v in req.items():
            link_only = isinstance(v, list) and len(v) == 1 and isinstance(v[0], str)
            if link_only:
                slot = ins.get(k)
                if slot is None:
                    errors.append({"code": "MISSING_INPUT_SLOT", "node": n.get("id"),
                                   "msg": f"{n.get('type')} 缺少必需输入槽 {k}"})
                elif slot.get("link") is None:
                    errors.append({"code": "UNCONNECTED_REQUIRED", "node": n.get("id"),
                                   "msg": f"{n.get('type')} 的必需输入 {k} 未连接"})

    # 4) 环检测（三色 DFS）
    adj = {}
    for l in g.get("links", []):
        adj.setdefault(l.get("origin_id"), []).append(l.get("target_id"))
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in nodes}
    cycle = []
    def dfs(u, stack):
        color[u] = GRAY
        for v in adj.get(u, []):
            if color.get(v, WHITE) == GRAY:
                cycle.append(stack + [v])
                return True
            if color.get(v, WHITE) == WHITE and dfs(v, stack + [v]):
                return True
        color[u] = BLACK
        return False
    for nid in nodes:
        if color.get(nid) == WHITE and dfs(nid, [nid]):
            break
    if cycle:
        errors.append({"code": "CYCLE", "msg": f"检测到环: {cycle[0]}"})

    # 5) 输出节点（object_info 标记 output_node / display 名 Save/Preview）
    has_out = False
    for n in g.get("nodes", []):
        defn = oi.get(n.get("type")) or {}
        if defn.get("output_node") or "SaveImage" in str(n.get("type")) or "PreviewImage" in str(n.get("type")):
            has_out = True
            break
    if not has_out:
        errors.append({"code": "NO_OUTPUT_NODE", "msg": "工作流没有 SaveImage/PreviewImage 等输出节点"})

    # 6) COMBO 值合法性（如 ckpt_name 是否在模型列表内）
    for n in g.get("nodes", []):
        defn = oi.get(n.get("type")) or {}
        req = (defn.get("input") or {}).get("required", {})
        wv = n.get("widget_values") or []
        for k, v in req.items():
            if (isinstance(v, list) and len(v) > 1 and all(isinstance(x, str) for x in v)
                    and any(str(x).endswith((".safetensors", ".ckpt", ".pt", ".gguf")) for x in v)):
                # combo 列表；widget 值按 widgets 顺序对齐——宽松：任一 widget 值在 combo 里则过
                if wv and not any(w in v for w in wv if isinstance(w, str)):
                    warnings.append({"code": "COMBO_UNCHECKED", "node": n.get("id"),
                                     "msg": f"{n.get('type')} 的 {k} 未能对齐校验（值可能无效）"})

    return {"valid": not errors, "errors": errors, "warnings": warnings,
            "checked": {"nodes": len(g.get("nodes", [])), "links": len(g.get("links", []))}}


def _validate_ops_impl(operations):
    """Phase 9 计划校验：投递前静态检查 create/connect/delete/update/move。"""
    gs = _bridge("GET", "/graph")
    oi = _http("GET", "/object_info")
    errors_all = []
    # 增量画布视图（从快照复制结构，批内 create 动态加入）
    view = {}
    if (gs or {}).get("ok"):
        for n in gs["graph"].get("nodes", []):
            # 1.52 前端 serializeNodeId 输出字符串 id —— view 统一 str 归一
            view[str(n["id"])] = {"type": n.get("type"),
                                  "inputs": [dict(i) for i in (n.get("inputs") or [])],
                                  "outputs": [dict(o) for o in (n.get("outputs") or [])]}
    results = []
    for idx, op in enumerate(operations or []):
        name = (op or {}).get("op") or (op or {}).get("type")
        d = op.get("data") if isinstance(op.get("data"), dict) else op
        err = None
        try:
            if name == "create_node":
                ct = d.get("class_type")
                if ct not in oi:
                    err = {"code": "NODE_TYPE_NOT_FOUND", "msg": f"未注册类型: {ct}"}
                else:
                    pos = d.get("position")
                    if pos is not None and (not isinstance(pos, list) or len(pos) < 2):
                        err = {"code": "BAD_POSITION", "msg": "position 须为 [x,y]"}
                    wd = d.get("widgets") or {}
                    req = (oi[ct].get("input") or {})
                    valid_keys = set((req.get("required") or {})) | set((req.get("optional") or {}))
                    bad = [k for k in wd if k not in valid_keys]
                    if bad:
                        err = {"code": "UNKNOWN_WIDGET", "msg": f"{ct} 无这些 widget: {bad}"}
                    if not err:
                        _nid = d.get("node_id")
                        nid = None if _nid is None else str(_nid)
                        # 合成视图（required 顺序：连接型=input，其余=widget）
                        r = (req.get("required") or {})
                        inputs, outputs = [], []
                        for k, v in r.items():
                            if isinstance(v, list) and len(v) == 1 and isinstance(v[0], str):
                                inputs.append({"name": k, "type": v[0], "link": None})
                        for ot in (oi[ct].get("output") or []):
                            outputs.append({"name": "?", "type": ot, "links": []})
                        if nid is not None:
                            view[nid] = {"type": ct, "inputs": inputs, "outputs": outputs}
            elif name == "connect":
                fid = str((d.get("from") or {}).get("node_id"))
                tid = str((d.get("to") or {}).get("node_id"))
                fs = (d.get("from") or {}).get("slot")
                ts = (d.get("to") or {}).get("slot")
                a, b = view.get(fid), view.get(tid)
                if a is None or b is None:
                    err = {"code": "NODE_NOT_FOUND", "msg": f"端点不存在: {fid}->{tid}"}
                elif fs >= len(a["outputs"]) or ts >= len(b["inputs"]):
                    err = {"code": "SLOT_OOB",
                           "msg": f"槽位越界: {fid}.out[{fs}]({len(a['outputs'])}) -> {tid}.in[{ts}]({len(b['inputs'])})"}
                else:
                    ot = a["outputs"][fs].get("type")
                    it = b["inputs"][ts].get("type")
                    if ot and it and ot != it and "*" not in (str(ot), str(it)):
                        err = {"code": "TYPE_MISMATCH", "msg": f"{ot} -> {it} 类型不匹配"}
            elif name in ("delete_node", "move_node", "update_node"):
                nid = str(d.get("node_id"))
                if nid not in view:
                    err = {"code": "NODE_NOT_FOUND", "msg": f"节点不存在: {nid}"}
                elif name == "move_node":
                    p = d.get("position")
                    if not isinstance(p, list) or len(p) < 2:
                        err = {"code": "BAD_POSITION", "msg": "position 须为 [x,y]"}
                elif name == "update_node":
                    ct = view[nid]["type"]
                    defn = oi.get(ct) or {}
                    req = (defn.get("input") or {})
                    valid = set((req.get("required") or {})) | set((req.get("optional") or {}))
                    bad = [k for k in (d.get("widgets") or {}) if k not in valid]
                    if bad:
                        err = {"code": "UNKNOWN_WIDGET", "msg": f"{ct} 无这些 widget: {bad}"}
            elif name == "disconnect":
                pass  # link_id 存在性执行时判定
            else:
                err = {"code": "UNKNOWN_OP", "msg": f"未知操作: {name}"}
        except Exception as e:
            err = {"code": "VALIDATOR_EXCEPTION", "msg": f"{type(e).__name__}: {e}"}
        results.append({"i": idx, "op": name, "ok": err is None, "error": err})
        if err:
            errors_all.append({"i": idx, **err})
    return {"ok": not errors_all, "checked": len(results), "errors": errors_all,
            "results": results}


def _send_command(cmd_type: str, data: dict, timeout: float = 30.0) -> dict:
    """投递一条画布命令并等待结果。"""
    try:
        resp = _bridge("POST", "/command",
                       {"type": cmd_type, "data": data, "origin": "hermes"})
    except Exception as e:
        return {"ok": False, "error": f"提交命令失败: {e}"}
    if not resp.get("success"):
        return {"ok": False, "error": "桥不接受命令"}
    cid = resp.get("command_id")
    # 轮询结果（带超时）
    deadline = timeout
    import time as _t
    start = _t.time()
    while _t.time() - start < deadline:
        r = _bridge("GET", f"/command/{cid}/result?timeout=0")
        if r.get("success") and r.get("result"):
            return {"ok": True, "result": r["result"]}
        _t.sleep(0.2)
    return {"ok": False, "error": "命令超时（前端扩展未响应）"}


@app.list_tools()
async def list_tools():
    return [
        types.Tool(name="hb_connect", description="探测 HermesBridge 后端是否在线并返回桥信息。",
                   inputSchema={"type": "object", "properties": {}}),
        types.Tool(name="hb_get_state", description="ComfyUI 后端综合状态：版本/GPU/队列/模型文件夹/自定义节点。",
                   inputSchema={"type": "object", "properties": {}}),
        types.Tool(name="hb_get_graph", description="读取前端最近回报的当前画布 graph（nodes+links）。",
                   inputSchema={"type": "object", "properties": {}}),
        types.Tool(name="hb_create_node", description="在画布创建节点。",
                   inputSchema={"type": "object", "properties": {
                       "class_type": {"type": "string", "description": "节点类型，如 KSampler/CheckpointLoaderSimple"},
                       "node_id": {"type": "integer", "description": "可选，指定 id"},
                       "position": {"type": "array", "items": {"type": "number"}, "description": "画布坐标 [x,y]"},
                       "title": {"type": "string"},
                       "widgets": {"type": "object", "description": "初始参数 {名称:值}"}},
                       "required": ["class_type"]}),
        types.Tool(name="hb_delete_node", description="删除指定节点。",
                   inputSchema={"type": "object", "properties": {
                       "node_id": {"type": "integer", "description": "节点 id"}},
                       "required": ["node_id"]}),
        types.Tool(name="hb_move_node", description="移动节点到新位置。",
                   inputSchema={"type": "object", "properties": {
                       "node_id": {"type": "integer"},
                       "position": {"type": "array", "items": {"type": "number"},
                                    "description": "[x,y]"}},
                       "required": ["node_id", "position"]}),
        types.Tool(name="hb_update_node", description="修改节点参数（widgets/title/mode）。",
                   inputSchema={"type": "object", "properties": {
                       "node_id": {"type": "integer"},
                       "widgets": {"type": "object"},
                       "title": {"type": "string"}, "mode": {"type": "integer"}},
                       "required": ["node_id"]}),
        types.Tool(name="hb_connect_nodes", description="连接两节点：from(输出槽) -> to(输入槽)。",
                   inputSchema={"type": "object", "properties": {
                       "from": {"type": "object", "properties": {"node_id": {"type": "integer"}, "slot": {"type": "integer"}}},
                       "to": {"type": "object", "properties": {"node_id": {"type": "integer"}, "slot": {"type": "integer"}}}},
                       "required": ["from", "to"]}),
        types.Tool(name="hb_disconnect_nodes", description="按 link_id 断开连接。",
                   inputSchema={"type": "object", "properties": {
                       "link_id": {"type": "integer"}}, "required": ["link_id"]}),
        types.Tool(name="hb_batch_ops", description="批量画布操作（事务式 sequential ops）。",
                   inputSchema={"type": "object", "properties": {
                       "operations": {"type": "array", "items": {"type": "object"}}},
                       "required": ["operations"]}),
        types.Tool(name="hb_list_models", description="列出模型文件夹；传 folder 则列出该类型模型文件。",
                   inputSchema={"type": "object", "properties": {
                       "folder": {"type": "string", "description": "checkpoints/loras/vae/..."}}}),
        types.Tool(name="hb_list_custom_nodes", description="列出已执行的自定义节点/插件。",
                   inputSchema={"type": "object", "properties": {}}),
        types.Tool(name="hb_search_nodes", description="按关键词在节点注册表中搜节点类型。",
                   inputSchema={"type": "object", "properties": {
                       "keyword": {"type": "string"}}, "required": ["keyword"]}),
        types.Tool(name="hb_get_queue", description="当前队列统计（running/pending 数量）。",
                   inputSchema={"type": "object", "properties": {}}),
        types.Tool(name="hb_get_capabilities", description="桥能力表：某能力是否支持（§37）。",
                   inputSchema={"type": "object", "properties": {}}),
        types.Tool(name="hb_get_api_prompt", description="导出当前画布的 API-format prompt（执行/分享用）。",
                   inputSchema={"type": "object", "properties": {}}),
        types.Tool(name="hb_execute_workflow", description="执行当前画布工作流并等待完成，返回产出图片。",
                   inputSchema={"type": "object", "properties": {
                       "timeout": {"type": "integer", "description": "等待秒数，默认240"},
                       "client_id": {"type": "string", "description": "客户端标识，默认hermes"}}}),
        types.Tool(name="hb_cancel_execution", description="中止当前正在执行的工作流。",
                   inputSchema={"type": "object", "properties": {}}),
        types.Tool(name="hb_save_workflow", description="当前画布存为 workflow 文件（user/default/workflows）。",
                   inputSchema={"type": "object", "properties": {
                       "name": {"type": "string", "description": "workflow 名称"}}, "required": ["name"]}),
        types.Tool(name="hb_load_workflow", description="从文件恢复画布（破坏性：覆盖当前画布）。",
                   inputSchema={"type": "object", "properties": {
                       "name": {"type": "string"}}, "required": ["name"]}),
        types.Tool(name="hb_list_workflows", description="列出已保存的 workflow 文件。",
                   inputSchema={"type": "object", "properties": {}}),
        types.Tool(name="hb_search_custom_nodes", description="按关键词搜索可安装的节点包（Manager 清单+已装列表）。",
                   inputSchema={"type": "object", "properties": {
                       "keyword": {"type": "string"}}, "required": ["keyword"]}),
        types.Tool(name="hb_install_custom_node", description="安装自定义节点（Manager 队列，装完需重启 ComfyUI）。",
                   inputSchema={"type": "object", "properties": {
                       "keyword": {"type": "string", "description": "节点包 title（先用 search 查）"},
                       "timeout": {"type": "integer", "description": "秒，默认600"}}, "required": ["keyword"]}),
        types.Tool(name="hb_uninstall_custom_node", description="卸载自定义节点（删目录）。",
                   inputSchema={"type": "object", "properties": {
                       "keyword": {"type": "string", "description": "节点包 title"},
                       "timeout": {"type": "integer"}}, "required": ["keyword"]}),
        types.Tool(name="hb_update_custom_node", description="更新自定义节点（git pull，重启生效）。",
                   inputSchema={"type": "object", "properties": {
                       "keyword": {"type": "string"},
                       "timeout": {"type": "integer"}}, "required": ["keyword"]}),
        types.Tool(name="hb_install_model", description="下载模型文件到指定目录（Manager 白名单校验）。",
                   inputSchema={"type": "object", "properties": {
                       "url": {"type": "string"},
                       "filename": {"type": "string"},
                       "folder": {"type": "string", "description": "checkpoints/loras/vae/embeddings/..."},
                       "timeout": {"type": "integer"}}, "required": ["url", "filename", "folder"]}),
        types.Tool(name="hb_validate_workflow", description="校验当前画布：类型匹配/必需输入/环/输出节点/模型存在。",
                   inputSchema={"type": "object", "properties": {}}),
        types.Tool(name="hb_validate_operations", description="投递前校验一批画布操作（计划拦截：类型/槽位/节点存在）。",
                   inputSchema={"type": "object", "properties": {
                       "operations": {"type": "array", "items": {"type": "object"}}},
                       "required": ["operations"]}),
    ]


def _to_text(data):
    return [types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False, default=str))]


def _search_nodes_registry(keyword):
    """从后端 node_registry_summary 检索。"""
    try:
        st = _bridge("GET", "/state")
        summ = st.get("node_registry_summary", {}).get("classes", {})
        kw = (keyword or "").lower()
        hits = [name for name in summ if kw in name.lower()]
        return {"count": len(hits), "matches": sorted(hits)[:60]}
    except Exception as e:
        return {"error": str(e)}


@app.call_tool()
async def call_tool(name, arguments=None):
    args = arguments or {}
    try:
        if name == "hb_connect":
            d = _bridge("GET", "/ping")
            return _to_text(d)
        if name == "hb_get_state":
            d = _bridge("GET", "/state")
            return _to_text(d)
        if name == "hb_get_graph":
            d = _bridge("GET", "/graph")
            return _to_text(d)
        if name == "hb_create_node":
            d = _send_command("create_node", args)
            return _to_text(d)
        if name == "hb_delete_node":
            d = _send_command("delete_node", {"node_id": args["node_id"]})
            return _to_text(d)
        if name == "hb_move_node":
            d = _send_command("move_node", args)
            return _to_text(d)
        if name == "hb_update_node":
            d = _send_command("update_node", args)
            return _to_text(d)
        if name == "hb_connect_nodes":
            d = _send_command("connect", args)
            return _to_text(d)
        if name == "hb_disconnect_nodes":
            d = _send_command("disconnect", {"link_id": args["link_id"]})
            return _to_text(d)
        if name == "hb_batch_ops":
            outs = []
            for op in args.get("operations", []):
                outs.append(_send_command(op.get("op") or op.get("type"), op.get("data") or {}, timeout=20))
            return _to_text({"results": outs})
        if name == "hb_list_models":
            if args.get("folder"):
                d = _http("GET", "/models/" + urllib.parse.quote(args["folder"]))
            else:
                d = _http("GET", "/models")
            return _to_text(d)
        if name == "hb_list_custom_nodes":
            d = _bridge("GET", "/state")
            return _to_text(d.get("custom_nodes", []))
        if name == "hb_search_nodes":
            d = _search_nodes_registry(args.get("keyword", ""))
            return _to_text(d)
        if name == "hb_get_queue":
            d = _http("GET", "/prompt")
            qi = d.get("exec_info", {})
            return _to_text({"queue_remaining": qi.get("queue_remaining"), "exec_info": qi})
        if name == "hb_get_capabilities":
            return _to_text(_bridge("GET", "/capabilities"))
        if name == "hb_get_api_prompt":
            return _to_text(_send_command("api_prompt", {}, timeout=30))
        if name == "hb_save_workflow":
            return _to_text(_send_command("save_workflow", {"name": args.get("name", "")}, timeout=30))
        if name == "hb_load_workflow":
            return _to_text(_send_command("load_workflow", {"name": args.get("name", "")}, timeout=30))
        if name == "hb_list_workflows":
            return _to_text(_bridge("GET", "/workflow/list"))
        if name == "hb_search_custom_nodes":
            kw = (args.get("keyword") or "").lower()
            meta = _resolve_node_meta(args.get("keyword", ""))
            installed = sorted(x for x in _custom_nodes_dirs()
                               if kw and kw in x.lower() and not x.endswith(".py"))
            return _to_text({"keyword": args.get("keyword"),
                             "list_matched": meta, "installed_matched": installed})
        if name == "hb_install_custom_node":
            meta = _resolve_node_meta(args.get("keyword", ""))
            if not meta.get("matched"):
                return _to_text({"ok": False, "error": "NODE_NOT_IN_LIST",
                                 "keyword": args.get("keyword"),
                                 "hint": "先用 hb_search_custom_nodes 确认 title"})
            before = _custom_nodes_dirs()
            body = {"id": meta["title"], "title": meta["title"], "ui_id": meta["title"],
                    "version": "unknown", "selected_version": "unknown",
                    "skip_post_install": False,
                    "files": meta["files"], "install_type": meta.get("install_type", "git-clone"),
                    # Manager V3.42 硬性必填（缺则 500 KeyError，源码 1537 行）
                    "channel": "default", "mode": "cache"}
            r = _manager_enqueue("/manager/queue/install", body,
                                 float(args.get("timeout", 600)))
            after = _custom_nodes_dirs()
            new_dirs = sorted(after - before)
            r.update({"title": meta["title"], "new_dirs": new_dirs,
                      "installed": bool(new_dirs), "restart_required": True})
            return _to_text(r)
        if name == "hb_uninstall_custom_node":
            meta = _resolve_node_meta(args.get("keyword", ""))
            if not meta.get("matched"):
                # 也许直接是已装目录名 → 用 unknown 路径 files=[dir]
                dirs = _custom_nodes_dirs()
                kw = (args.get("keyword") or "").strip()
                if kw not in dirs:
                    return _to_text({"ok": False, "error": "NOT_FOUND",
                                     "keyword": args.get("keyword")})
                meta = {"matched": True, "title": kw, "files": [kw], "install_type": "git-clone"}
            before = _custom_nodes_dirs()
            body = {"id": meta["title"], "ui_id": meta["title"],
                    "version": "unknown", "files": meta["files"]}
            r = _manager_enqueue("/manager/queue/uninstall", body,
                                 float(args.get("timeout", 300)))
            after = _custom_nodes_dirs()
            removed = sorted(before - after)
            r.update({"title": meta["title"], "removed_dirs": removed,
                      "uninstalled": bool(removed) or meta["title"] not in after})
            return _to_text(r)
        if name == "hb_update_custom_node":
            meta = _resolve_node_meta(args.get("keyword", ""))
            if not meta.get("matched"):
                return _to_text({"ok": False, "error": "NOT_FOUND",
                                 "keyword": args.get("keyword")})
            body = {"id": meta["title"], "ui_id": meta["title"],
                    "version": "unknown", "files": meta["files"]}
            r = _manager_enqueue("/manager/queue/update", body,
                                 float(args.get("timeout", 600)))
            r.update({"title": meta["title"], "restart_required": True})
            return _to_text(r)
        if name == "hb_install_model":
            folder = args.get("folder", "checkpoints")
            # check_whitelist_for_model 要求 save_path+base+filename 三元组与列表
            # 精确一致（缺键直接 500 KeyError）——按 url 反查本地 model-list 补全
            entry = {}
            try:
                ml_path = r"D:\AI\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-Manager\model-list.json"
                with open(ml_path, encoding="utf-8") as _mf:
                    for _m in json.load(_mf).get("models", []):
                        if _m.get("url") == args.get("url"):
                            entry = _m
                            break
            except Exception:
                entry = {}
            sp = entry.get("save_path") or folder
            body = {"url": args.get("url"),
                    "filename": args.get("filename") or entry.get("filename"),
                    "save_path": sp,
                    "base": entry.get("base", "SDXL"),
                    "directory": sp,
                    "ui_id": args.get("filename"), "name": args.get("filename")}
            r = _manager_enqueue("/manager/queue/install_model", body,
                                 float(args.get("timeout", 600)))
            # 验证落盘（models 目录递归找）
            models_root = r"D:\AI\ComfyUI_windows_portable\ComfyUI\models"
            target = os.path.join(models_root, folder, str(args.get("filename")))
            found = os.path.isfile(target)
            if not found:
                for root, _d, files in os.walk(os.path.join(models_root, folder)):
                    if str(args.get("filename")) in files:
                        found = True
                        break
            r.update({"filename": args.get("filename"), "folder": folder,
                      "file_exists": found})
            return _to_text(r)
        if name == "hb_validate_workflow":
            return _to_text(_validate_workflow_impl())
        if name == "hb_validate_operations":
            return _to_text(_validate_ops_impl(args.get("operations") or []))
        if name == "hb_cancel_execution":
            d = _http("POST", "/interrupt")
            return _to_text({"ok": True, "interrupt": d})
        if name == "hb_execute_workflow":
            # 0) 优先走前端执行链（queue_prompt）：前端自己的 clientId + WebSocket
            #    → 进度条 / 画布连线预览缩略图 / 任务队列 全套原生反馈；
            #    外部 client_id 直投 /prompt 只有任务列表、无连线预览（实测）。
            #    失败再回退 api_prompt + 直投 /prompt。
            import time as _t
            pid = None
            r0 = _send_command("queue_prompt", {}, timeout=30)
            if (r0 or {}).get("ok") and ((r0 or {}).get("result") or {}).get("success"):
                # 前端已提交 → 从 /queue 拿 prompt_id
                for _ in range(15):
                    q0 = _http("GET", "/queue")
                    running = q0.get("queue_running") or []
                    pending = q0.get("queue_pending") or []
                    if running:
                        pid = running[0][1] if len(running[0]) > 1 else None
                    elif pending:
                        pid = pending[0][1] if len(pending[0]) > 1 else None
                    if pid:
                        break
                    _t.sleep(0.5)
            if not pid:
                # 回退：api_prompt + 直投 /prompt（无连线预览，但能出图）
                r = _send_command("api_prompt", {}, timeout=30)
                prompt = (((r or {}).get("result") or {}).get("data") or {}).get("prompt")
                if not prompt:
                    return _to_text({"ok": False, "stage": "queue_prompt+api_prompt",
                                     "detail": {"q": r0, "a": r}})
                q = _http("POST", "/prompt", {"prompt": prompt,
                                              "client_id": args.get("client_id", "hermes")})
                pid = q.get("prompt_id")
                if not pid:
                    return _to_text({"ok": False, "stage": "queue",
                                     "node_errors": q.get("node_errors"), "error": q.get("error")})
            # 轮询 /history 等完成
            deadline = _t.time() + float(args.get("timeout", 240))
            status = None
            while _t.time() < deadline:
                h = _http("GET", f"/history/{pid}", timeout=15)
                status = h.get(pid)
                if status:
                    st0 = status.get("status", {})
                    if st0.get("completed") or st0.get("status_str") in ("error", "success"):
                        break
                _t.sleep(2)
            if not status:
                return _to_text({"ok": False, "stage": "history", "prompt_id": pid,
                                 "error": "timeout"})
            st = status.get("status", {})
            images = []
            for _nid, out in status.get("outputs", {}).items():
                images.extend(out.get("images", []))
            return _to_text({"ok": st.get("status_str") == "success",
                             "prompt_id": pid, "status": st.get("status_str"),
                             "images": images,
                             "messages": st.get("messages") if st.get("status_str") == "error" else None})
        return [types.TextContent(type="text", text=f"unknown tool {name}")]
    except Exception as e:
        return _to_text({"ok": False, "error": f"{type(e).__name__}: {e}"})


async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())