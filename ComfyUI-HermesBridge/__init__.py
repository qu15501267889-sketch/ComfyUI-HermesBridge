# -*- coding: utf-8 -*-
"""ComfyUI-HermesBridge —— Hermes Studio <-> ComfyUI 双向控制桥（后端侧）。

职责：
- 服务前端扩展（WEB_DIRECTORY -> /extensions/ComfyUI-HermesBridge/*）
- 在 PromptServer 的共享 routes 上挂 /hermes_bridge/* 端点：
    /ping     健康检查
    /poll     前端扩展轮询拉取待执行画布命令
    /result   前端回报命令执行结果
    /command  Hermes 投递命令
    /graph    读/写最近回报的画布快照
    /state    后端状态汇总（版本/GPU/队列/模型/custom nodes）
    /debug    调试

路由挂载到 PromptServer.instance.routes（官方插件标准：add_routes() 在
PromptServer 启动时统一注册），这样无论 custom_node 何时加载都生效。

零鼠标模拟 / 零浏览器自动化 —— 全部走官方 graph API + REST。
"""

import logging
import os
import sys
import json

logger = logging.getLogger("hermes_bridge")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# workflow 文件库（Phase 5）：ComfyUI/user/default/workflows/*.json
_WF_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "user", "default", "workflows"))


def _wf_path(name: str) -> str:
    """名称白名单化：只取 basename，防路径穿越；无 .json 后缀自动补。"""
    safe = os.path.basename(str(name or "").replace("\\", "/").strip())
    if safe and not safe.lower().endswith(".json"):
        safe += ".json"
    return os.path.join(_WF_DIR, safe) if safe else ""

import bridge.protocol as PROTO  # noqa: E402
import bridge.commands as CMDS  # noqa: E402
import bridge.state as STATE  # noqa: E402


class HermesBridgeProbe:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}
    RETURN_TYPES = ()
    FUNCTION = "noop"
    CATEGORY = "hermes"

    def noop(self):
        return ()


class HermesSwitchPanel:
    """🎛 组开关面板（纯 UI 节点，无输出 → 不进执行链）。
    Boolean 开关由 web/hermes_bridge.js 轮询挂回调：
    勾选=True 组活跃(mode=0)；取消=False 组透传(mode=4)。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "磨皮美颜组": ("BOOLEAN", {"default": True, "label_on": "启用", "label_off": "关·透传"}),
                "瘦身组": ("BOOLEAN", {"default": True, "label_on": "启用", "label_off": "关·透传"}),
                "背景组": ("BOOLEAN", {"default": True, "label_on": "启用", "label_off": "关·透传"}),
                "光影组": ("BOOLEAN", {"default": True, "label_on": "启用", "label_off": "关·透传"}),
                "质感风格组": ("BOOLEAN", {"default": True, "label_on": "启用", "label_off": "关·透传"}),
            }
        }
    RETURN_TYPES = ()
    FUNCTION = "noop"
    CATEGORY = "hermes"
    DESCRIPTION = "总控开关面板：取消勾选=该组整组透传（Never）。由 HermesBridge JS 联动。"

    def noop(self):
        return ()


class HermesIntensityPanel:
    """🎚 强度总控面板（纯 UI 节点，无输出 → 不进执行链）。
    多个 FLOAT 强度滑块（磨皮/瘦身/背景/光影/质感……），由 web/hermes_bridge.js
    联动：拖动滑块 → 值写进对应目标节点的 denoise/strength widget。
    映射在 JS 侧 INTENSITY_MAP 维护，新增模块=加一行滑块+映射，无需重启 Python。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "磨皮美颜强度": ("FLOAT", {"default": 0.32, "min": 0.0, "max": 1.0, "step": 0.01, "round": 0.001}),
                "瘦身强度": ("FLOAT", {"default": 0.30, "min": 0.0, "max": 1.0, "step": 0.01, "round": 0.001}),
                "背景替换强度": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "光影强度": ("FLOAT", {"default": 0.80, "min": 0.0, "max": 1.0, "step": 0.01}),
                "质感风格强度": ("FLOAT", {"default": 0.60, "min": 0.0, "max": 1.0, "step": 0.01}),
            }
        }
    RETURN_TYPES = ()
    FUNCTION = "noop"
    CATEGORY = "hermes"
    DESCRIPTION = "强度总控面板：各模块强度滑杆，由 HermesBridge JS 联动写入对应采样节点 denoise/strength。"

    def noop(self):
        return ()


NODE_CLASS_MAPPINGS = {"HermesBridgeProbe": HermesBridgeProbe}
NODE_CLASS_MAPPINGS["HermesSwitchPanel"] = HermesSwitchPanel
NODE_CLASS_MAPPINGS["HermesIntensityPanel"] = HermesIntensityPanel
NODE_DISPLAY_NAME_MAPPINGS = {
    "HermesBridgeProbe": "Hermes Bridge",
    "HermesSwitchPanel": "🎛 组开关面板 (Hermes)",
    "HermesIntensityPanel": "🎚 强度总控面板 (Hermes)",
}
WEB_DIRECTORY = "./web"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]


def _register_routes() -> None:
    try:
        from aiohttp import web
        from server import PromptServer
        ps = PromptServer.instance
        if ps is None:
            logger.warning("HermesBridge: PromptServer.instance 尚未就绪，跳过路由注册")
            return
    except Exception as e:
        logger.warning("HermesBridge: 无法获取 PromptServer: %s", e)
        return

    # 共享 RouteTableDef —— PromptServer.add_routes() 启动时统一注册到 app
    routes = ps.routes
    H = "/hermes_bridge"

    @routes.get(H + "/ping")
    async def ping(request):
        return web.json_response({
            "protocol": PROTO.PROTOCOL,
            "protocol_version": PROTO.PROTOCOL_VERSION,
            "ok": True,
            "queued": CMDS.peek_pending_count(),
            "bridge": "HermesBridge",
        })

    @routes.get(H + "/debug")
    async def debug(request):
        return web.json_response({
            "protocol": PROTO.PROTOCOL,
            "pending": CMDS.peek_pending_count(),
            "graph_cached": CMDS.get_graph_state() is not None,
        })

    # 能力表（规格 §37）：Hermes 每条命令前先查这里，未支持返回明确错误
    @routes.get(H + "/capabilities")
    async def get_capabilities(request):
        return web.json_response({"capabilities": STATE.collect_capabilities()})

    # ---- Phase 5: workflow 文件存取 ----
    @routes.post(H + "/workflow/save")
    async def wf_save(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"success": False, "code": "INVALID_ARGUMENT"}, status=400)
        path = _wf_path(body.get("name"))
        graph = body.get("graph")
        if not path or not isinstance(graph, dict):
            return web.json_response({"success": False, "code": "INVALID_ARGUMENT",
                                      "message": "name/graph 必填"}, status=400)
        try:
            os.makedirs(_WF_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(graph, f, ensure_ascii=False)
        except Exception as e:
            return web.json_response({"success": False, "code": "WRITE_FAILED",
                                      "message": str(e)}, status=500)
        return web.json_response({"success": True, "name": os.path.basename(path)})

    @routes.get(H + "/workflow/list")
    async def wf_list(request):
        try:
            os.makedirs(_WF_DIR, exist_ok=True)
            items = sorted(f for f in os.listdir(_WF_DIR) if f.lower().endswith(".json"))
        except Exception as e:
            return web.json_response({"success": False, "message": str(e)}, status=500)
        return web.json_response({"success": True, "workflows": items})

    @routes.get(H + "/workflow/load")
    async def wf_load(request):
        path = _wf_path(request.rel_url.query.get("name", ""))
        if not path or not os.path.isfile(path):
            return web.json_response({"success": False, "code": "NOT_FOUND"}, status=404)
        try:
            with open(path, encoding="utf-8") as f:
                graph = json.load(f)
        except Exception as e:
            return web.json_response({"success": False, "code": "READ_FAILED",
                                      "message": str(e)}, status=500)
        return web.json_response({"success": True, "name": os.path.basename(path), "graph": graph})

    # 后端状态（不依赖前端）
    @routes.get(H + "/state")
    async def get_state(request):
        try:
            return web.json_response(STATE.collect_raw_state())
        except Exception as e:
            logger.exception("state 采集失败")
            return web.json_response({"error": str(e)}, status=500)

    # 前端扩展轮询命令
    @routes.get(H + "/poll")
    async def poll(request):
        cmd = CMDS.poll_command()
        return web.json_response(cmd if cmd is not None else {})

    # 前端回报命令结果
    @routes.post(H + "/result")
    async def report_result(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": {"code": "INVALID_COMMAND"}})
        cid = body.get("command_id")
        CMDS.report_result(
            cid,
            success=bool(body.get("success")),
            data=body.get("data"),
            error=body.get("error"),
            origin=body.get("origin", "comfyui"),
        )
        return web.json_response({"success": True})

    # Hermes 投递命令
    @routes.post(H + "/command")
    async def post_command(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"success": False,
                                      "error": {"code": "INVALID_COMMAND",
                                                "message": "body 非 JSON"}})
        cmd_type = body.get("type") or body.get("command")
        data = body.get("data") or {}
        origin = body.get("origin", "hermes")
        if not cmd_type:
            return web.json_response({"success": False,
                                      "error": {"code": "INVALID_COMMAND",
                                                "message": "缺 type"}})
        cid = CMDS.enqueue_command(cmd_type, data, origin=origin)
        return web.json_response({"success": True, "command_id": cid})

    @routes.get(H + "/command/{command_id}/result")
    async def get_result(request):
        cid = request.match_info.get("command_id")
        timeout = float(request.query.get("timeout", "0") or 0)
        r = CMDS.get_result(cid, timeout=timeout)
        if r is None:
            return web.json_response({"success": False,
                                      "error": {"code": "COMMAND_TIMEOUT",
                                                "message": "等待结果超时"}})
        return web.json_response({"success": True, "result": r})

    @routes.post(H + "/graph")
    async def post_graph(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": {"code": "INVALID_ARGUMENT"}})
        graph = body.get("graph")
        if isinstance(graph, dict):
            CMDS.stamp_graph(graph, body.get("graph_hash") or "")
            return web.json_response({"success": True})
        return web.json_response({"success": False, "error": {"code": "INVALID_GRAPH"}})

    @routes.get(H + "/graph")
    async def get_graph(request):
        gs = CMDS.get_graph_state()
        if gs is None:
            return web.json_response({"ok": False, "empty": True})
        return web.json_response({"ok": True, **gs})

    logger.info("HermesBridge: /hermes_bridge/* 已挂到共享 routes")


_register_routes()
logger.info("ComfyUI-HermesBridge loaded. WEB_DIRECTORY=%s", WEB_DIRECTORY)