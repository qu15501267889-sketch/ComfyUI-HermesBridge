# ComfyUI-HermesBridge 安装指南（v1.0.2）

> 本插件实现「Hermes Agent ↔ ComfyUI 双向直连画布」：28 个 `hb_*` MCP 工具
> 直接读写画布（建节点/连线/改参数/存取工作流/执行出图），零浏览器自动化。
> 分两部分安装：**ComfyUI 侧（插件）** + **Hermes 侧（MCP server）**。

---

## 第一部分：ComfyUI 侧（解压即用，零依赖）

本压缩包内层目录 `ComfyUI-HermesBridge/` 即 custom node，**纯 Python 标准库实现，无任何第三方依赖、无 requirements**。

1. 解压本 zip
2. 把 `ComfyUI-HermesBridge/` 整个目录放入你的 `ComfyUI/custom_nodes/`
3. 启动（或重启）ComfyUI —— 启动日志出现 `HermesBridge` 即注册成功
4. 浏览器打开 ComfyUI 页面后按 **Ctrl+R** 刷新一次（让前端扩展 hermes_bridge.js 生效）

**版本要求**：ComfyUI ≥ 0.37、前端 ≥ 1.52（实测环境 0.37.0 / 1.52.7）。

验证后端桥在线：

```
curl http://127.0.0.1:8188/hermes_bridge/ping
```

## 第二部分：Hermes 侧（MCP server，三步）

压缩包根目录的 `comfyui_hermes_bridge.py` = Hermes 侧 MCP server（28 个 hb_* 工具）。

### 1. 放置文件

把它放到你机器上一个固定路径，例如：

```
C:\你的路径\comfyui_hermes_bridge.py
```

### 2. 给 Hermes 用的 Python 装 mcp 包

用 **Hermes 启动 MCP 用的同一个 Python** 执行（路径换成你机器上的）：

```
"<Hermes的python.exe>" -m pip install mcp
```

### 3. 注册进 Hermes 配置

编辑 Hermes 配置文件 `~/.hermes/config.yaml`，在 `mcp_servers:` 下加入（**路径全部换成你机器上的实际路径**）：

```yaml
mcp_servers:
  comfyui_hermes:
    command: C:\你的路径\python.exe        # 必须是装了 mcp 包的那个 Python 的完整绝对路径
    args:
    - C:\你的路径\comfyui_hermes_bridge.py  # 第1步放置的文件
    env:
      COMFY_URL: "http://127.0.0.1:8188"
    enabled: true
```

保存后**重启 Hermes**（MCP server 列表不支持热加载），即可看到 `mcp__comfyui_hermes__hb_*` 工具。

---

## 常见问题

| 现象 | 处理 |
|---|---|
| `hb_*` 工具不存在 | 检查 config.yaml 路径是否为**绝对路径**、`pip install mcp` 是否装进了同一个 Python、Hermes 是否重启 |
| 命令返回 `COMMAND_TIMEOUT` | ComfyUI 浏览器页面没开/在后台被节流 → 打开页面并保持前台，Ctrl+R |
| 装完多出"未保存的工作流"画布 | v1.0.2 已根治；如遇到旧版本残留，请升级到本 Release |
| 要求权限/浏览器自动化 | 本插件**不需要**任何浏览器自动化或额外系统权限 |

详细文档见仓库 `ComfyUI-HermesBridge/` 内的 README / API.md / TROUBLESHOOTING.md。
