# ComfyUI-HermesBridge · Hermes MCP 工具 API

Hermes 通过 `comfyui_hermes` MCP server 暴露 28 个工具（前缀 `hb_`）。
重启 Hermes 后自动进入工具流（`tool_search` 可查 `mcp__comfyui_hermes__…`）。

## 工具速查

### 连接 / 状态

**hb_connect** — 探测桥在线性。
返回：`{protocol, protocol_version, ok, queued, bridge}`

**hb_get_state()** — 后端综合状态。
返回：版本 / GPU / 队列 / 模型文件夹 / custom nodes / 节点注册表摘要。

**hb_get_graph()** — 读前端最近回报的画布。
返回：`{ok, graph:{nodes[],links[]}, graph_hash}`

### 画布操作（驱动真实画布）
**hb_create_node({class_type, node_id?, position:[x,y], widgets:{…}, title?})**
创建节点，画布实时出现。`class_type` 如 `KSampler` / `CheckpointLoaderSimple`。

**hb_delete_node({node_id})** — 删除节点。

**hb_update_node({node_id, widgets?, title?, mode?})** — 改参数/标题/模式。

**hb_move_node({node_id, position:[x,y]})** — 移动。

**hb_connect_nodes({from:{node_id,slot}, to:{node_id,slot}})** — 建连。
`from.slot` 是输出槽索引，`to.slot` 是输入槽索引。

**hb_disconnect_nodes({link_id})** — 按 link_id 断开。

**hb_batch_ops({operations:[{op,data},…]})** — 顺序批量执行多条画布操作。

### 目录 / 查询
**hb_list_models({folder?})** — 无 folder 列模型文件夹；传 folder（如 checkpoints）列该类型模型文件。

**hb_list_custom_nodes()** — 列自定义节点。

**hb_search_nodes({keyword})** — 在节点注册表搜索类型（如 "wan" / "sampler"）。

**hb_get_queue()** — 队列统计。

## 3. 自然语言示例

用户："在我当前工作流里加一个 KSampler"
执行：`hb_get_state` → `hb_search_nodes({keyword:"sampler"})` → `hb_create_node({class_type:"KSampler"})`

用户："在该 Load 后接一个 CLIP Text Encode"
执行：`hb_get_graph` → 定位两节点 → `hb_connect_nodes({from,to})`

用户："给我搭一个完整图生图工作流"
执行：搜索节点 → `hb_batch_ops([…])`

## 结果结构

成功：
```
{ ok:true, result: { command_id, success:true, data:{…}, error:null } }
```

失败（如前端未探测、画布未就绪）：
```
{ ok:false, error:"…" }
```
注意：命令投递成功但前端扩展在浏览器未加载/未轮询时，会返回超时
（`COMMAND_TIMEOUT`）——先确保 ComfyUI 页面打开、画布出现、扩展轮询激活。

## HTTP 直连端点（不经 MCP 也可用）

基址 `http://127.0.0.1:8188/hermes_bridge`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ping` | 桥健康检查 |
| GET | `/capabilities` | 能力表（§37：命令前先查，未支持项明确报错） |
| GET | `/state` | 后端状态：版本/GPU/队列/模型文件夹/custom nodes(active)/节点注册表 |
| GET | `/graph` | 前端画布快照：nodes（含 inputs/outputs 槽位+类型+link 登记）+ links |
| GET | `/poll` | 前端轮询拉命令 |
| POST | `/command` | 投递命令 `{type,data,origin}` → `{command_id}` |
| GET | `/command/{cid}/result?timeout=` | 取命令结果（阻塞等待） |
| POST | `/result` | 前端回报执行结果 |
| POST | `/workflow/save` | `{name, graph}` 当前画布全量落盘 `user/default/workflows/*.json` |
| GET | `/workflow/list` | 列出已存 workflow |
| GET | `/workflow/load?name=` | 载入 workflow JSON |
| GET | `/debug` | pending 计数 / graph 缓存状态 |

## 画布命令扩展（经 hb_batch_ops 通用投递）

| op | data | 说明 |
|---|---|---|
| `api_prompt` | `{}` | 调 `graphToPrompt()` → `data:{prompt:API格式, workflow:UI格式}` |
| `save_workflow` | `{name}` | 当前画布 serialize → 后端写文件 |
| `load_workflow` | `{name}` | 后端读文件 → `loadGraphData()` 恢复画布 |

## 执行工作流（端到端已验收，90s/2048x880x30步）

1. `hb_batch_ops([{op:"api_prompt",data:{}}])` → 取 `data.prompt`
2. `POST /prompt` body `{"prompt": <…>, "client_id": "hermes"}` → `{prompt_id}`
3. 轮询 `GET /history/{prompt_id}` 至 `status.completed == true`
4. `outputs[*].images[]` 即产出文件（type=output）；中途放弃：`POST /interrupt`
