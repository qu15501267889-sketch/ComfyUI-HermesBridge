# -*- coding: utf-8 -*-
"""后端状态采集 —— 从 ComfyUI 内部对象直接读取。

不依赖前端即可提供的状态（版本/GPU/模型/队列/custom_nodes/节点注册表）。
画布 graph 与 active workflow 依赖前端，见 web/hermes_bridge.js 的采集。

内部实现复刻 /system_stats 的采集逻辑，全部通过已加载的 ComfyUI 内部
对象读取，不额外发 HTTP 请求到自身。所有 ComfyUI 依赖均容错 import，
缺失时返回占位而非抛异常。
"""

from __future__ import annotations

import os
import platform
import sys
from datetime import datetime, timezone
from typing import Optional

# ---- ComfyUI 内部依赖（全部容错）----
try:
    import comfy.model_management as model_management
except Exception:
    model_management = None

try:
    import folder_paths
except Exception:
    folder_paths = None

try:
    import nodes
except Exception:
    nodes = None

try:
    import comfyui_version as _module_version
    _COMFYUI_VERSION = getattr(_module_version, "__version__", "unknown")
except Exception:
    _COMFYUI_VERSION = "unknown"

try:
    from app.frontend_management import FrontendManager
    _FRONTEND_VERSION = FrontendManager.get_required_frontend_version()
except Exception:
    try:
        from importlib.metadata import version as _mv
        _FRONTEND_VERSION = _mv("comfyui-frontend-package")
    except Exception:
        _FRONTEND_VERSION = "unknown"

try:
    from server import PromptServer
except Exception:
    PromptServer = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_embedded_python() -> bool:
    exe = (getattr(sys, "executable", "") or "").replace("\\", "/")
    return "python_embeded" in exe


def get_deploy_env() -> str:
    return "local-portable" if _is_embedded_python() else "local"


def get_system_stats() -> dict:
    """复刻 /system_stats：版本/内存/设备。"""
    if model_management is None:
        return {"system": {"error": "comfy.model_management unavailable"}, "devices": []}
    try:
        primary_device = model_management.get_torch_device()
        cpu_device = model_management.torch.device("cpu")
        ram_total = model_management.get_total_memory(cpu_device)
        ram_free = model_management.get_free_memory(cpu_device)
        torch_devices = model_management.get_all_torch_devices()
        if primary_device in torch_devices:
            torch_devices = [primary_device] + [d for d in torch_devices if d != primary_device]
        else:
            torch_devices = [primary_device] + list(torch_devices)

        devices = []
        for d in torch_devices:
            vram_total, torch_vram_total = model_management.get_total_memory(d, torch_total_too=True)
            vram_free, torch_vram_free = model_management.get_free_memory(d, torch_free_too=True)
            devices.append({
                "name": model_management.get_torch_device_name(d),
                "type": str(d.type),
                "index": d.index,
                "vram_total": vram_total,
                "vram_free": vram_free,
                "torch_vram_total": torch_vram_total,
                "torch_vram_free": torch_vram_free,
            })

        return {
            "system": {
                "os": platform.system().lower(),
                "ram_total": ram_total,
                "ram_free": ram_free,
                "comfyui_version": _COMFYUI_VERSION,
                "frontend_version": _FRONTEND_VERSION,
                "python_version": sys.version,
                "pytorch_version": getattr(model_management, "torch_version", "unknown"),
                "embedded_python": _is_embedded_python(),
                "deploy_environment": get_deploy_env(),
            },
            "devices": devices,
        }
    except Exception:
        return {"system": {"error": "state unavailable"}, "devices": []}


def get_deploy_env() -> str:
    return get_deploy_environment_fast()


def get_deploy_environment_fast() -> str:
    return "local-portable" if _is_embedded_python() else "local"


def get_queue_info() -> dict:
    """读取队列统计（运行中/等待数 + 完整 ID 列表摘要）。"""
    out = {"queue_running": [], "queue_pending": [], "running": 0, "pending": 0}
    try:
        if PromptServer and getattr(PromptServer, "instance", None):
            qi = PromptServer.instance.get_queue_info()
            if isinstance(qi, dict):
                out["queue_running"] = qi.get("queue_running", [])
                out["queue_pending"] = qi.get("queue_pending", [])
                out["running"] = len(out["queue_running"])
                out["pending"] = len(out["queue_pending"])
    except Exception as e:
        out["error"] = str(e)
    return out


def get_models(folder: Optional[str] = None):
    """枚举模型。folder 为空则返回全部文件夹类型清单；否则返回该类文件名列表。"""
    if folder_paths is None:
        return []
    try:
        if folder:
            return sorted(folder_paths.get_filename_list(folder))
        return sorted(folder_paths.folder_names_and_paths.keys())
    except Exception as e:
        return [{"error": str(e)}]


def _custom_nodes_dir() -> str:
    # state.py 位于 <ComfyUI>/custom_nodes/<pkg>/bridge/state.py，
    # custom_nodes 目录 = 上上上一级。
    try:
        # ComfyUI 文件管理器登记的 custom_nodes 首路径（最可靠）
        if folder_paths is not None:
            cand = folder_paths.folder_names_and_paths["custom_nodes"][0][0]
            if cand and os.path.isdir(cand):
                return cand
    except Exception:
        pass
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_custom_nodes() -> list:
    """枚举 custom_nodes 目录下已加载的子目录。"""
    base = _custom_nodes_dir()
    out = []
    try:
        if not os.path.isdir(base):
            return out
        for ent in sorted(os.listdir(base)):
            if ent.startswith("__") or ent == ".git":
                continue
            p = os.path.join(base, ent)
            if os.path.isdir(p) and not ent.endswith(".py"):
                out.append({"name": ent, "path": p, "active": _node_active(ent)})
    except Exception as e:
        out.append({"error": str(e)})
    return out


def _node_active(name: str) -> bool:
    """推断该 custom node 是否处于加载状态。

    ComfyUI 0.37 实际机制（见 nodes.load_custom_node）：加载成功后登记
    ``LOADED_MODULE_DIRS[module_name] = abspath``，module_name 即目录名；
    IMPORT FAILED 的包不会登记。旧版本曾用 LOADED_MODULE_NAMES，两代都兼容。
    """
    try:
        if nodes is None:
            return False
        dirs = getattr(nodes, "LOADED_MODULE_DIRS", None)
        if isinstance(dirs, dict) and name in dirs:
            return True
        legacy = getattr(nodes, "LOADED_MODULE_NAMES", None) or {}
        for k in legacy:
            if k == name or k.endswith("/" + name) or k == name.replace("-", "_"):
                return True
        return False
    except Exception:
        return False


def manager_available() -> bool:
    """ComfyUI-Manager 是否已加载（决定 install_* capability）。"""
    return _node_active("ComfyUI-Manager")


def collect_capabilities() -> dict:
    """规格 §37：命令执行前的能力检查表。"""
    return {
        "get_state": True,
        "get_workflow": True,
        "get_graph": True,
        "create_node": True,
        "delete_node": True,
        "update_node": True,
        "move_node": True,
        "connect_nodes": True,
        "disconnect_nodes": True,
        "batch_graph_ops": True,
        "load_workflow": True,
        "save_workflow": True,
        "save_workflow_as": True,
        "execute_workflow": True,
        "cancel_execution": True,
        "get_models": True,
        "find_model": True,
        "get_custom_nodes": True,
        "search_custom_nodes": True,
        "install_custom_node": manager_available(),
        "uninstall_custom_node": manager_available(),
        "update_custom_node": manager_available(),
        "install_model": manager_available(),
        "get_queue": True,
        "restart_comfyui": False,
    }


def get_node_registry_summary() -> dict:
    """节点注册表摘要（数量 + 轻量索引），不整包塞定义（需求 §45）。"""
    try:
        if nodes is None or not hasattr(nodes, "NODE_CLASS_MAPPINGS"):
            return {"count": 0, "classes": {}}
        raw = nodes.NODE_CLASS_MAPPINGS
        summary = {}
        for name, cls in raw.items():
            try:
                summary[name] = {
                    "category": getattr(cls, "CATEGORY", "uncategorized"),
                    "display_name": nodes.NODE_DISPLAY_NAME_MAPPINGS.get(name, name),
                }
            except Exception:
                continue
        return {"count": len(raw), "classes": summary}
    except Exception as e:
        return {"count": 0, "classes": {}, "error": str(e)}


def collect_raw_state() -> dict:
    """后端可直接提供的完整初始状态。"""
    return {
        "captured_at": _now(),
        "system": get_system_stats(),
        "queue": get_queue_info(),
        "model_folders": get_models(),
        "custom_nodes": get_custom_nodes(),
        "node_registry_summary": get_node_registry_summary(),
    }