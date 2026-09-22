# ComfyUI-HermesBridge · Troubleshooting

## 常见问题排查表

| 症状 | 可能原因 | 处理 |
|---|---|---|
| Hermes 工具报 `COMMAND_TIMEOUT` | 前端扩展未轮询 | 检查浏览器是否打开 ComfyUI 页面 + 画布已渲染。前端扩展每 1.2s 轮询，需画布出现后才激活。 |
| `/hermes_bridge/state` 返回空 / 502 | ComfyUI 未启动 | 启动 ComfyUI（见下）。 |
| 画布操作无响应，但后端 ping 通 | 前端 `syncGraph` 未回报 | 保存文件无碍；刷新 ComfyUI 页面。 |
| graph 端点 nodes=0 | 画布刚加载 / 前端 sync 未到 | 等 3 秒再查（回报间隔 2.5s）。 |

## 2. ComfyUI 启动（本机方式）

```bash
cd /d/AI/ComfyUI_windows_portable
./python_embeded/python.exe -s ComfyUI/main.py --windows-standalone-build > comfyui.log 2>&1 &
```

输出重定向到文件（非管道）——避免 ComfyUI-Manager 在非终端 stdout 下因
`flush()` 崩溃中断采样（已测无效 / 有效见下条）。

## 3. 调试端点

```bash
curl http://127.0.0.1:8188/hermes_bridge/ping       # 在线+队列
curl http://127.0.0.1:8188/hermes_bridge/debug      # 队列/缓存状态
curl http://127.0.0.1:8188/hermes_bridge/state      # 状态
curl http://127.0.0.1:8188/hermes_bridge/graph      # 画布快照
```

## 4. 常见避坑（经验）

- **画布 nodeCount 变化但与用户页面不一致**：代理/你驱动的浏览器 session 与用户
  的浏览器是**不同前端会话**，画布内存态独立。要让用户看到，必须在**用户打开**的
  ComfyUI 页面生效（后端命令经用户页面轮询执行）。
- **links 序列化报错**：前端 1.52.7 的 `graph.links` 是对象 map 不是数组——
  已用 `linksArray()` 兼容；若仍报错，检查是否有异常节点（`n.type` 非字符串）。
- **create 后 graph 读数滞后一两个节点**：syncGraph 是每 2.5s 的完整快照，
  允许一次滞后，下个周期追上。

## 5. 若命令一直不被前端执行

1. 确认浏览器已打开 `http://127.0.0.1:8188` 且画布渲染出节点。
2. 控制台看 `window.hermesBridge.debug()` 是否 `{polling:true}`。
3. 若 `polling:false`：页面前端未加载新扩展——硬刷新（Ctrl+F5）或清缓存。
4. 后端命令在队列（`/hermes_bridge/debug` 的 `pending`）说明前端没 poll——刷新页面。