## 📦 开箱即用打包（v1.0.3）

- **zip 包内文件齐全**：`ComfyUI-HermesBridge/`（ComfyUI 插件，零依赖）+ `comfyui_hermes_bridge.py`（Hermes 侧 MCP server，28 个 hb_* 工具）+ `README.md` / `INSTALL.md` 文档 + `examples/qianwen修改图2.json` 测试画布
- **README.md 新增完整「使用方法」**：
  1. ComfyUI 侧：解压 → 放入 `custom_nodes/` → 重启 → Ctrl+R（零依赖，纯标准库）
  2. Hermes 侧：放 MCP 文件 → `pip install mcp` → `config.yaml` 注册（README 内有可直接抄的模板，路径换成本机的）→ 重启 Hermes
  3. 导入测试画布做安装验收（该画布由本插件开发）
  4. 常见问题表（找不到工具 / COMMAND_TIMEOUT / Ctrl+R）
- 无安装脚本、无需额外权限、零浏览器自动化——下载解压按 README 操作即可部署到另一台电脑

## 自 v1.0.2 起的修复（沿用）
- load_workflow 重复画布根治（名字绑定 + tab 去重）
- HermesIntensityPanel 强度总控面板 / 背景组 A/B 互斥联动
