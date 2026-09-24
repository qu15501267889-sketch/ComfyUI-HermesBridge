## 修复
- **load_workflow 重复画布 Bug 根治**：回载改走 `loadGraphData` 按工作流名绑定（第4参）。目标 tab 已开 → 激活去重；未开 → 以该名开一个 tab。不再生成"未保存的工作流(N)"临时画布（前端源码 `activateLoadedWorkflow` 实证）。
- load 命令返回 `via: bind-name / activate+bind-name`，可观测实际路径。

## 新增
- 🎚 **HermesIntensityPanel 强度总控面板**：磨皮/瘦身/背景/光影/质感 滑块 → JS 联动直写目标采样节点 `denoise/strength`（`INTENSITY_MAP` 一行一模块，无需重启 Python）。
- 背景组 **A/B 互斥联动**（`ComfySwitchNode` 117 → 两路 mode 自动切换）+ 背景组节点表更新。

## 安装 / 升级（zip 已含全部组件）
- **ComfyUI 侧**：解压 zip → `ComfyUI-HermesBridge/` 放入 `ComfyUI/custom_nodes/` → 重启 ComfyUI → 浏览器 Ctrl+R（零依赖，纯标准库）。
- **Hermes 侧**：zip 根目录含 `comfyui_hermes_bridge.py`（MCP server）+ `INSTALL.md`（三步安装：放文件 → `pip install mcp` → config.yaml 注册模板）。
- ⚠️ 前端 JS 改动需浏览器 **Ctrl+R** 刷新后生效。

## 测试画布

- **`examples/qianwen修改图2.json`**（随本 Release 附带，亦入库 `examples/`）——**使用本插件（画布操作 MCP 工具链）开发的测试画布**：7 功能串行修图链（美白→磨皮→瘦身→换背景→道具→光影重塑→风格化→保存→输出预览），每功能自带解码+预览，末端超分默认关闭。导入 `user/default/workflows/` 即可打开验收。

> Release 资产 ` qianwen-xiugaitu2-test-canvas.json ` 即该测试画布（GitHub 资产名不支持中文；仓库内文件名为 `examples/qianwen修改图2.json`，两者内容一致）。
