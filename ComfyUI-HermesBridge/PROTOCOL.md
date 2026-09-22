# ComfyUI-HermesBridge · 协议说明

本桥在三方之间传递统一的命令/事件消息，全部为 JSON。

## 消息 envelope

所有消息遵循：

```json
{
  "protocol": "hermes-comfyui",
  "protocol_version": "1.0",
  "message_id": "uuid",
  "command_id": "uuid",
  "origin": "hermes | comfyui",
  "type": "create_node",
  "data": {}
}
```

- `protocol` / `protocol_version`：桥标识。
- `command_id`：命令唯一 id，用于结果关联与 echo-loop 去重。
- `origin`：写入来源。`hermes` = Hermes 发起的画布写操作，
  `comfyui` = 前端回报。Bridge 据此跳过“自己造成的变化”重复执行（需求 §35）。
- `type`：命令类型（见下）。
- `data`：命令参数。

## 2. 命令类型

后端与前端扩展执行同一组画布操作类型：

| type | data 说明 |
|---|---|
| create_node | `{class_type, node_id?, position?, widgets?, title?}` |
| delete_node | `{node_id}` |
| move_node | `{node_id, position:[x,y]}` |
| update_node | `{node_id, widgets?, title?, mode?}` |
| connect | `{from:{node_id,slot}, to:{node_id,slot}}` |
| disconnect | `{link_id}` |
| get_graph | （无参数，返回当前画布 nodes+links） |

## 3. 结果回显

Hermes 投 `POST /hermes_bridge/command` → 返回 `{success:true, command_id}`。
前端执行后 `POST /hermes_bridge/result`。Hermes 读取
`GET /hermes_bridge/command/{command_id}/result`。

成功：

```json
{ "command_id": "…", "success": true, "data": {…}, "error": null }
```

失败：

```json
{ "command_id": "…", "success": false, "data": null,
  "error": { "code": "NODE_NOT_FOUND", "message": "节点 12 不存在" } }
```

## 4. REST 端点（全部前缀 `/hermes_bridge`）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET  | /ping | 健康检查 |
| GET  | /state | 后端状态（版本/GPU/队列/模型/custom nodes/节点注册表） |
| GET  | /graph | 读前端最近回报的画布 graph |
| POST | /graph | 前端回报画布快照 `{graph, graph_hash, ts}` |
| GET  | /poll | 前端轮询拉取下一条画布命令 |
| POST | /result | 前端回报命令执行结果 |
| POST | /command | Hermes 投递画布命令 |
| GET  | /command/{id}/result | Hermes 读命令结果 |
| GET  | /debug | 调试信息（队列/缓存状态） |

## 5. 同步机制（需求 §34）

- 启动：前端 `syncGraph` 每 2.5s 回报完整画布快照 + graph_hash。
- 常规：`create/delete/move/update/connect` 命令是**增量 delta**（需求 §33），
  不每次发全图。
- 变化源：`graph_hash`（FNV-1a 32bit）判断画布是否变化，避免重复同步 / 死循环事件。

## 6. 安全（需求 §56）

- 默认只服务 `127.0.0.1` / `localhost` / `::1`。
- 远程访问需显式 `token` + Origin 校验（本版默认远程关闭）。
- 路径、命令、模型下载等操作默认仅本机允许。