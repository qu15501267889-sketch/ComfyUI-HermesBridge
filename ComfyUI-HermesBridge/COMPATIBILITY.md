# ComfyUI-HermesBridge · 兼容性

本桥针对 **ComfyUI 0.37.0 + Frontend 1.52.7（portable）** 实测。

## 已适配的现实（1.52.7）

| 项 | 现状 | 适配位置 |
|---|---|---|
| `window.app.graph` | 真实实例，含 `.nodes`、`.getNodeById` | 前端 `getApp()` |
| `graph.links` | **`Map` 实例（`graph._links.set()` 存取），不是数组也不是普通对象** | 前端 `linksArray()`（`instanceof Map` 兜底） |
| 节点注册表 | `window.LiteGraph.registered_node_types`（964 个） | 前端 `nodeClassFor()` |
| 建模节点 | `new registered_node_types[class_type]()` | 前端 `createNode()` |
| 后端状态 | `/system_stats` `/prompt`(queue) `/models` `/object_info` `/extensions` 官方端点稳定 | 后端 `state.py` |
| 前端扩展加载 | `/extensions/<pkg>/…`，浏览器刷新加载 | `WEB_DIRECTORY=./web` |

## 版本差异的处理原则（需求 §54）

所有前端版本差异集中在**前端 `hermes_bridge.js`**，后端尽量用稳定官方
REST 端点。升级 ComfyUI / Frontend 后：
1. 先用浏览器控制台确认 `window.app.graph` 与 `window.LiteGraph.registered_node_types`
   是否仍存在。
2. 若 links 结构变化，只改 `linksArray()`。
3. 若注册表属性名变化，只改 `nodeClassFor()`。

## 已知注意事项

- 前端 1.52.7 的 `graph.links` 是对象 map，老版本是数组——`linksArray()` 已兼容两者。
- 前端 `app.registerExtension` 的 setup 时机在部分版本不稳定，本桥**不依赖**它，
  采用模块顶层检测 `window.app.graph` 就绪后自启动轮询，更稳健。

## 1.52.7 实测坑位修正记录（2026-09-22 端到端验收后补录）

以下 6 项均为**真实踩坑后从源码实证修正**，升级版本时逐项复查：

| # | 坑 | 实测事实 | 修正位置 |
|---|---|---|---|
| 1 | `connect()` 方向反了 | 1.52 fork 签名是 `connect(output_slot, target_node, input_slot)`——**发起方是输出节点**；老 litegraph 是 `目标.connect(输入槽, 源节点, 输出槽)`，方向相反。调反会静默失败（return null 不抛错） | 前端 `connect()`：改 `a.connect(from.slot, b, to.slot)`，并以 `b.inputs[slot].link` 登记为成功判据 |
| 2 | 节点坐标是自定义 **vec2 类** | `ComfyNode.boundingRect.pos` / `pos` 是 vec2：`v[0]/v[1]` 下标可访问、`toString()="x,y"`，但 **`Array.isArray()` 返回 false**，实例上**无 x/y 属性**（诊断实测 `x: absent`）。`graph.serialize()` 按下标读 → 任何 `Array.isArray` 检查都会静默跳过坐标（快照全 0 的根因）。写侧 `typeof==="object"` 判定通过、读侧 `Array.isArray` 失败 = 写有效读无效不对称 | 前端 `readPos()`：**全部按下标 `v[0]/v[1]` 访问**（grab 判定），顺序 boundingRect → pos → x/y 非全0优先；`setPos()` 三路全写（x/y + pos 下标 + boundingRect.pos 下标） |
| 3 | `graph.links` 是 Map | 新版 `_links.set()`——`Object.values(Map)` 得空数组，快照会误报 links:0 | 前端 `linksArray()` 加 `instanceof Map` 分支 |
| 4 | custom node `active` 全 False | 0.37 加载成功登记在 **`nodes.LOADED_MODULE_DIRS`**（`{module_name: abspath}`，IMPORT FAILED 不登记）；`LOADED_MODULE_NAMES` 该版本**不存在** | 后端 `state.py::_node_active()` 优先读 `LOADED_MODULE_DIRS`，兼容旧名 |
| 5 | `widget_values` 上报过期 | 它是**序列化缓存**，改 `widget.value` 不会自动同步；反之 serialize 应读实时值 | 前端 `updateNode()` 写后同步缓存 + 调 widget.callback；`serializeGraph` 优先 `widgets.map(w=>w.value)` |
| 6 | `graphToPrompt`/`loadGraphData` 挂哪 | 挂在 graph service 上（`app` 或 `app.graph`，含 `rootGraph` 属性），非固定 `window.app` | 前端 `getGraphSvc()` 探测链；`executeCmd` 已 async（支持 await graphToPrompt） |

判定 connect 成功**不能信返回值**（fork 返回值不稳定），必须查目标输入槽
`inputs[slot].link` 是否登记——这条同时是假成功（success:true 但 links:0）的防线。

## ComfyUI-Manager V3.42 队列 API 坑位（2026-09-22 Phase 7 实测）

| # | 坑 | 实测事实 | 对策 |
|---|---|---|---|
| 1 | `POST /manager/queue/install` 500 | body **硬性必填 `channel` + `mode`**（manager_server 1537 行直接下标，缺则 KeyError→500） | body 补 `"channel":"default","mode":"cache"`；uninstall/update/install_model 不需要这俩 |
| 2 | `POST /manager/queue/install_model` 500 | `check_whitelist_for_model` 要求 **`save_path`+`base`+`filename` 三元组与 model-list.json 条目精确一致**，缺 `save_path` 即 KeyError | 按 url 反查本地 model-list 补全三元组 |
| 3 | `GET /customnode/getlist` 500 | **`mode` 是必填 query 参数**（`query["mode"]` 直接下标） | `?mode=cache`；清单搜索改读本地 custom-node-list.json 更稳 |
| 4 | 所有端点间歇性 500（traceback 指向 `print`→`stdout.flush`→`OSError [Errno 22]`） | Manager 内部大量 `print`；若宿主进程 **stdout 接在已失效的管道上**，flush 抛 EINVAL 被 aiohttp 包成 500 | 后台启动 ComfyUI 必须 **stdout+stderr 都重定向到文件**（`>>log 2>>log`），勿留裸管道 |

队列三步固定形态：`enqueue(200) → POST /manager/queue/start → GET /manager/queue/status 轮询至 total==done 且 is_processing=false`；
结果内容不回传 HTTP，**以目标目录/文件的存在性做落地验证**。

## 环境

- ComfyUI 0.37.0，`python_embeded` 3.13.14，PyTorch 2.13.0+cu130
- RTX 4060 Ti 8GB（VRAM total 8188 MB）
- ComfyUI-Manager 已安装（当前版本以 V4 frontend 能力为主）