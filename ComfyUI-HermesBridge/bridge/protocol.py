# -*- coding: utf-8 -*-
"""ComfyUI-HermesBridge —— 协议常量与消息结构。

后端 custom_node、前端扩展、Hermes MCP server 三方共享的协议定义。
所有消息采用统一 envelope 结构，前后端通过命令队列中转。
"""

# 协议标识
PROTOCOL = "hermes-comfyui"
PROTOCOL_VERSION = "1.0"

# 消息类型
TYPE_COMMAND = "command"     # Hermes -> ComfyUI 的命令
TYPE_EVENT = "event"          # ComfyUI -> Hermes 的事件
TYPE_RESULT = "result"        # 命令执行结果回执

# 事件名（前端画布变化 -> Hermes）
EVENT_HELLO = "hello"
EVENT_HELLO_ACK = "hello_ack"
EVENT_GRAPH_CHANGED = "graph_changed"
EVENT_NODE_CREATED = "node_created"
EVENT_NODE_DELETED = "node_deleted"
EVENT_NODE_UPDATED = "node_updated"
EVENT_NODE_MOVED = "node_moved"
EVENT_CONNECTION_CHANGED = "connection_changed"
EVENT_WORKFLOW_CHANGED = "workflow_changed"
EVENT_WORKFLOW_LOADED = "workflow_loaded"
EVENT_WORKFLOW_SAVED = "workflow_saved"
EVENT_EXECUTION_STATUS = "execution_status"
EVENT_BRIDGE_READY = "bridge_ready"   # 前端扩展已就绪

# 错误码（需求 §41）
ERROR_CODES = {
    "COMFYUI_NOT_CONNECTED": "ComfyUI 未连接",
    "COMFYUI_VERSION_UNSUPPORTED": "ComfyUI 版本不受支持",
    "FRONTEND_VERSION_UNSUPPORTED": "Frontend 版本不受支持",
    "NODE_NOT_FOUND": "节点不存在",
    "NODE_TYPE_NOT_FOUND": "节点类型不存在",
    "NODE_CREATE_FAILED": "节点创建失败",
    "NODE_UPDATE_FAILED": "节点更新失败",
    "NODE_DELETE_FAILED": "节点删除失败",
    "CONNECTION_FAILED": "连接失败",
    "WORKFLOW_NOT_FOUND": "工作流不存在",
    "WORKFLOW_LOAD_FAILED": "工作流加载失败",
    "WORKFLOW_SAVE_FAILED": "工作流保存失败",
    "MODEL_NOT_FOUND": "模型不存在",
    "MODEL_INSTALL_FAILED": "模型安装失败",
    "CUSTOM_NODE_NOT_FOUND": "自定义节点不存在",
    "CUSTOM_NODE_INSTALL_FAILED": "自定义节点安装失败",
    "MANAGER_NOT_AVAILABLE": "ComfyUI-Manager 不可用",
    "COMMAND_TIMEOUT": "命令超时",
    "INVALID_COMMAND": "无效命令",
    "INVALID_GRAPH": "无效 Graph",
    "GRAPH_VALIDATION_FAILED": "Graph 校验失败",
    "PERMISSION_DENIED": "权限被拒绝",
    "PATH_NOT_ALLOWED": "路径不允许",
    "FRONTEND_NOT_READY": "前端扩展未就绪",
    "INVALID_ARGUMENT": "参数无效",
}

# 命令类型（Hermes -> 画布操作）
CMD_GET_STATE = "get_state"
CMD_GET_GRAPH = "get_graph"
CMD_GET_WORKFLOW = "get_workflow"
CMD_CREATE_NODE = "create_node"
CMD_DELETE_NODE = "delete_node"
CMD_UPDATE_NODE = "update_node"
CMD_MOVE_NODE = "move_node"
CMD_CONNECT = "connect"
CMD_DISCONNECT = "disconnect"
CMD_BATCH_OPS = "batch_graph_ops"
CMD_LOAD_WORKFLOW = "load_workflow"
CMD_SAVE_WORKFLOW = "save_workflow"
CMD_SAVE_WORKFLOW_AS = "save_workflow_as"
CMD_REPLACE_WORKFLOW = "replace_workflow"
CMD_EXECUTE = "execute_workflow"
CMD_CANCEL = "cancel_execution"
CMD_GET_QUEUE = "get_queue"
CMD_LIST_MODELS = "list_models"
CMD_LIST_CUSTOM_NODES = "list_custom_nodes"
CMD_SEARCH_NODES = "search_nodes"
CMD_GET_NODE_INFO = "get_node_info"

# 画布命令（前端 graph_adapter 执行）
OP_CREATE_NODE = "create_node"
OP_DELETE_NODE = "delete_node"
OP_UPDATE_NODE = "update_node"
OP_MOVE_NODE = "move_node"
OP_CONNECT = "connect"
OP_DISCONNECT = "disconnect"

# 前端轮询端点
REST = {
    "ping": "/hermes_bridge/ping",
    "hello": "/hermes_bridge/hello",          # Hermes 探测后端注册
    "poll": "/hermes_bridge/poll",            # 前端拉取待执行命令 (GET)
    "result": "/hermes_bridge/result",        # 前端回报执行结果 (POST)
    "state": "/hermes_bridge/state",          # 后端立即同步状态
    "debug": "/hermes_bridge/debug",          # 调试回显
}