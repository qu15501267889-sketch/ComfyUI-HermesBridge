# -*- coding: utf-8 -*-
"""安全层 —— 默认只允许本地回环访问 Bridge 端点（需求 §56）。

/proc/host 校验：仅 127.0.0.1 / localhost / ::1 默认可见。
远程访问需要显式 token + Origin 校验（本版默认关闭远程）。
"""

from __future__ import annotations

IPV4_LOOPBACK = {"127.0.0.1", "localhost"}
IPV6_LOOPBACK = {"::1", "::ffff:127.0.0.1"}

_ALLOWED_REMOTE = False
_TOKEN: str | None = None


def configure(*, allow_remote: bool = False, token: str | None = None) -> None:
    """全局配置 Bridge 的网络开放范围（由 __init__ 调用）。"""
    global _ALLOWED_REMOTE, _TOKEN
    _ALLOWED_REMOTE = bool(allow_remote)
    _TOKEN = token


def is_local_address(host: str) -> bool:
    """host 是常见本地回环表示则允许。"""
    h = (host or "").strip().lower()
    return h in IPV4_LOOPBACK or h in IPV6_LOOPBACK or h in {"localhost"}


def authorized(request_peer_host: str, *, request_token: str | None,
               origin: str | None = None) -> bool:
    """判断一次 HTTP 请求是否被允许访问 Bridge。

    规则：
    - 远程未开放：仅回环地址允许，token 可空。
    - 远程已开放：必须提供 token 且与配置一致（目前留空则拒绝）。
    - Origin 校验：LAN 开放时必须 host 于白名单（当前仅 localhost）。
    """
    if is_local_address(request_peer_host):
        return True
    if not _ALLOWED_REMOTE:
        return False
    if not _TOKEN:
        return False
    if request_token != _TOKEN:
        return False
    # Origin 校验（LAN 才需要）
    if origin:
        ow = (origin or "").lower()
        if "127.0.0.1" not in ow and "localhost" not in ow:
            return False
    return True