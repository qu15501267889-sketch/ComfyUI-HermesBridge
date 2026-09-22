# ComfyUI-HermesBridge · 架构说明

## 总览

Hermes Studio ↔ ComfyUI 双向控制，三部分：

```
┌───────────────────────────────────────────────────┐
│ Hermes Studio (agent + MCP stdio: comfyui_hermes) │
│   hb_create_node / hb_get_state / …（14 个工具）    │
└───────────────────────┬───────────────────────────┘
                        │ POST /hermes_bridge/command
                        │ GET  /hermes_bridge/state|graph
                        ▼
┌───────────────────────────────────────────────────┐
│ ComfyUI Backend  (custom_nodes/ComfyUI-HermesBridge│
│   bridge/commands.py   命令队列(FIFO+结果)           │
│   bridge/state.py      状态采集                     │
│   bridge/protocol.py   协议常量/错误码              │
│   bridge/security.py   本机白名单                   │
└───────┬───────────────────────────▲───────────────┘
        │ GET  /poll  拉取命令        │ POST /result 回报
        │ POST /graph 回报画布快照     │ GET  /poll
        ▼                            │
┌───────────────────────────────────────────────────┐
│ ComfyUI Frontend  (web/hermes_bridge.js)           │
│   浏览器内驱动真实 LiteGraph：app.graph.add/remove/  │
│   board/getNodeById/connect/…                     │
│   syncGraph 每 2.5s 回报画布快照                     │
│   命令轮询 每 1.2s 拉 /poll 执行                    │
└───────────────────────────────────────────────────┘
```

## 设计原则（需求 §1 / §13 / §21 / §35）

- **零鼠标模拟**：全部通过 `app.graph` LiteGraph 官方接口 + 后端官方 REST。
- **双向**：Hermes 写画布（create/delete/…），画布状态实时回报。
- **防抖循环**：每条写命令带 `origin` + `command_id`，前端回报也带 origin，
  命令队列用 command_id 关联结果并去重（需求 §35 echo-loop 防护）。
- **不破坏用户工作**：只做增量画布操作，默认不 replace 工作流。

## 数据流

**写方向（Hermes → 画布）：**
```
Hermes hb_create_node → POST /command{type,data}
  → Bridge 入队 → 前端 poll 拉取
  → 前端 executeCmd 对 app.graph 真实改写
  → POST /result 回报 → Hermes 读结果
```

**读方向（画布 → Hermes）：**
```
前端 syncGraph（2.5s）→ POST /graph 全量快照
后端缓存 → GET /graph → Hermes hb_get_graph
```
常规画布写操作的 delta（节点级）不发全图（需求 §33）。

## 关键模块

- **bridge/commands.py**：`_command_queue`(deque)+`_results`(map)，线程安全锁；
  `enqueue/poll/report/get_result`。
- **bridge/state.py**：直接读 ComfyUI 内部对象
  `comfy.model_management` / `folder_paths` / `nodes` / `server.PromptServer`
  采集版本/GPU/队列/模型/custom nodes/节点注册表。
- **bridge/security.py**：仅 127.0.0.1/localhost/::1 默认允许。
- **web/hermes_bridge.js**：前端全部画布操作 + 轮询 + 快照回报；
  不依赖 `app.registerExtension` 的 setup（各版本时机不稳），自检测就绪。

## 安全（需求 §56）

- 默认本地回环。远程需 token + Origin 校验（当前关闭）。
- 证书/路径穿越由后端限定的目录白名单兜底。

## 未来扩展（对应需求 §18-20/38）

- ComfyUI-Manager 对接（安装/卸载/更新 custom node、模型下载）
- 工作流文件 load/save（前端 store 接管新版 `/api/routes`）
- 执行 / 队列监控深化