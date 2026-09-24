# ComfyUI-HermesBridge

Hermes Studio <-> ComfyUI **双向控制桥**。Hermes 直接读写 ComfyUI 画布：
创建/删除/移动节点、修改参数、建立连接、读取当前工作流与模型状态，
全流程通过官方 graph API + REST 完成，**零鼠标模拟、零浏览器自动化**。

---

## 架构

```
Hermes Studio (Agent)
      │  MCP (stdio) — comfyui_hermes  server
      ▼
Hermes 命令 →  Post  /hermes_bridge/command
      │
      ▼
ComfyUI 后端 custom_node  (custom_nodes/ComfyUI-HermesBridge)
   ├─ 命令队列 (pending/results)
   └─ 状态采集 (GPU / models / queue / custom nodes / node registry)
      │        ▲
      │        │ 前端轮询 /poll   +  返回结果 /result
      │        │ 画布快照 回报 /graph (syncGraph)
      ▼        │
ComfyUI 前端扩展 (web/hermes_bridge.js)
   在浏览器内操作真实 LiteGraph graph：app.graph.add/remove/connect/...
      │
      ▼
用户浏览器里的真实画布 —— 每次操作实时可见
```

## 核心能力（Hermes MCP 工具，前缀 hb_）

| 工具 | 说明 |
|---|---|
| hb_connect | 探测桥是否在线 |
| hb_get_state | 后端状态：版本/GPU/队列/模型文件夹/custom nodes |
| hb_get_graph | 读前端回报的当前画布 graph（nodes + links） |
| hb_create_node | 画布创建节点（真实出现） |
| hb_delete_node | 删除节点 |
| hb_update_node | 改参数（widgets/title/mode） |
| hb_move_node | 移动位置 |
| hb_connect_nodes / hb_disconnect_nodes | 建立/断开连接 |
| hb_batch_ops | 批量画布操作 |
| hb_list_models | 列模型（传 folder 可过滤） |
| hb_list_custom_nodes | 列自定义节点 |
| hb_search_nodes | 在节点注册表搜索类型 |
| hb_get_queue | 队列统计 |

## 安装 / 接入

1. **后端桥**：整个 `custom_nodes/ComfyUI-HermesBridge/` 目录已放在
   `D:\AI\ComfyUI_windows_portable\ComfyUI\custom_nodes\` 下。重启 ComfyUI 即自动加载
   （日志出现 `ComfyUI-HermesBridge loaded`）。
2. **前端扩展**：`web/hermes_bridge.js` 由后端通过 `WEB_DIRECTORY=./web` 自动服务，
   浏览器刷新页面即生效（新增 `/extensions/ComfyUI-HermesBridge/hermes_bridge.js` 路由）。
3. **Hermes MCP**：`~/.hermes/config.yaml` 已注册 `comfyui_hermes` server，指向
   `C:\Users\user\comfyui_hermes_bridge.py`。**重启 Hermes** 后工具自动进入工具流。

## 连接流程（自动，无需点击）

```
Hermes 启动 → (mcp_servers 载入 comfyui_hermes)
   ↓ hb_connect / hb_get_state
自动探测 127.0.0.1:8188 → 桥在线 → 拿状态
   ↓
前端扩展自动同步当前画布（syncGraph 每 2.5s 回报）
用户/ Hermes 投递命令 → 画布实时变化
```

## 配置

`config.yaml` → `mcp_servers.comfyui_hermes`：

```yaml
comfyui_hermes:
  command: C:\Users\user\.hermes-web-ui\desktop-runtime\hermes\0.20.0\win-x64\python\venv\Scripts\python.exe
  args: [C:\Users\user\comfyui_hermes_bridge.py]
  env:
    COMFY_URL: "http://127.0.0.1:8188"
  enabled: true
```

后端侧可选环境变量（默认即可用）：
- `COMFY_URL` — Hermes 端连接地址，默认 `http://127.0.0.1:8188`

## 支持 / 限制

**支持**：create/delete/move/update node、connect/disconnect、批量化、状态读取
（版本/GPU/队列/模型/custom nodes/节点注册表）。

**当前版本默认不做**（为契合最新版前端 1.52.7 的动态 API）：
- 工作流文件级 load/save（`/api/routes` 现由前端 store 接管）
- Custom Node 安装 / 模型下载（可对接 ComfyUI-Manager 能力，后续版本）

## 日志

- ComfyUI 后端日志：启动命令的 stdout（`comfyui.log` 若从脚本启动）
- 桥相关关键词：`HermesBridge`

## 卸载

删除目录：
```bash
rm -rf custom_nodes/ComfyUI-HermesBridge
```
并从 `config.yaml` `mcp_servers:` 移除 `comfyui_hermes` 块，重启 ComfyUI / Hermes。

## 扩展命令与执行链（hb_batch_ops 通用投递 + HTTP 直连）

| 能力 | 入口 | 状态 |
|---|---|---|
| 导出 API-format prompt | `{op:"api_prompt"}` | ✅ 已验收 |
| workflow 存/列/取 | `{op:"save_workflow"/"load_workflow"}` + `/workflow/save|list|load` | ✅ 已验收（破坏→恢复闭环） |
| 执行出图 | `POST /prompt` → 轮询 `/history` → `outputs.images` | ✅ 已验收（SDXL 90s 成图） |
| 中止执行 | `POST /interrupt` | 原生端点直用 |
| 能力表 | `GET /capabilities` | ✅ 已验收 |

## 端到端验收记录（2026-09-22）

- create/move/connect/update/delete：画布真实变化，快照 graph_hash 变更可证
- 9 条连线全通（link_id 85–93），类型全匹配（MODEL/CLIP/VAE/CONDITIONING/LATENT/IMAGE）
- api_prompt → /prompt → /history：`success/completed`，产出 `Portrait_Snow_2K_00001_.png`
- save→删除节点/移位→load：7 节点 9 连线完整恢复
- 1.52.7 六大坑位记录见 `COMPATIBILITY.md`
