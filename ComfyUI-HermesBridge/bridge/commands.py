# -*- coding: utf-8 -*-
"""命令队列 —— 前后端命令中转（需求 §28 事务 + §33 delta + §35 echo loop 防护）。

路径：
    Hermes(MCP) --POST--> /hermes_bridge/command  放入 pending 队列
    前端扩展 poll() --> 拉到最老命令 --> graph 执行 --> POST /result
    --> 结果存 result 表，Hermes 侧 get_result 阻塞取到。

echo-loop 防护：每个命令带 origin + command_id；Bridge 用 command_id 去重，
前端回报也带 origin，同源变化不重新入队触发连锁。
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, Optional

# 待前端执行的画布命令队列（FIFO）
_command_queue: Deque[dict] = deque()
_queue_lock = threading.RLock()

# 结果注册表：command_id -> {status, data, error, ts}
_results: Dict[str, Dict[str, Any]] = {}
_result_lock = threading.RLock()

# 前端回传的当前画布状态
_current_graph: Optional[Dict[str, Any]] = None
_graph_lock = threading.RLock()

# 前端扩展的 hello 信息
_hello_payload: Optional[Dict[str, Any]] = None
_hello_lock = threading.RLock()


def enqueue_command(
    cmd_type: str,
    data: Optional[dict] = None,
    *,
    command_id: Optional[str] = None,
    origin: str = "hermes",
) -> str:
    """把一条画布命令放入待执行队列，返回 command_id。"""
    cid = command_id or uuid.uuid4().hex
    with _queue_lock:
        _command_queue.append({
            "command_id": cid,
            "origin": origin,
            "type": cmd_type,
            "data": data or {},
        })
    return cid


def poll_command() -> Optional[dict]:
    """前端扩展轮询拉取下一条待执行命令（非阻塞，FIFO）。"""
    with _queue_lock:
        if not _command_queue:
            return None
        return _command_queue.popleft()


def peek_pending_count() -> int:
    with _queue_lock:
        return len(_command_queue)


def clear_pending() -> int:
    with _queue_lock:
        n = len(_command_queue)
        _command_queue.clear()
        return n


def report_result(
    command_id: str,
    *,
    success: bool,
    data: Any = None,
    error: Optional[dict] = None,
    origin: str = "comfyui",
) -> None:
    """前端回报命令执行结果。"""
    with _result_lock:
        _results[command_id] = {
            "command_id": command_id,
            "success": bool(success),
            "data": data,
            "error": error,
            "origin": origin,
            "received_at": time.time(),
        }


def get_result(command_id: str, *, timeout: float = 30.0) -> Optional[dict]:
    """Hermes 侧取某命令结果；阻塞等待直到 timeout(秒)或拿到。"""
    deadline = time.time() + timeout
    while True:
        with _result_lock:
            r = _results.get(command_id)
            if r is not None:
                _results.pop(command_id, None)
                return r
        if time.time() >= deadline:
            return None
        time.sleep(0.15)


def set_hello_payload(payload: Optional[dict]) -> None:
    """前端扩展初次连接时回传的桥信息。"""
    global _hello_payload
    with _hello_lock:
        _hello_payload = payload


def get_hello_payload() -> Optional[dict]:
    with _hello_lock:
        return _hello_payload


def stamp_graph(graph: dict, graph_hash: str) -> None:
    """前端回报的当前画布快照。"""
    global _current_graph
    with _graph_lock:
        _current_graph = {"graph": graph, "graph_hash": graph_hash, "ts": time.time()}


def get_graph_state() -> Optional[dict]:
    with _graph_lock:
        return _current_graph