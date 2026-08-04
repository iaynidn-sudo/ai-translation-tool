# MCP 调用文档

本工具以 **MCP (Model Context Protocol)** 协议对外提供服务，供 workbuddy、Claude Desktop、Cursor 等 MCP 客户端调用，也可用 Python 脚本 / HTTP / 命令行直接调用。

## 一、启动 MCP 服务

```bash
# stdio 传输（本地 MCP 客户端最常用）
python mcp_server.py

# 或 HTTP 传输（远程调用，可选）
python mcp_server.py --http 127.0.0.1:8000
```

也可直接双击项目内 `start_mcp.bat` 或 `start_mcp_http.bat`，或用 `launcher.py` 图形启动器。

## 二、workbuddy 集成配置

在 workbuddy 中新增一个 MCP Server（stdio 类型），命令指向本工具：

- **命令 (command)**: `D:\Python313\python.exe`（或你的 Python 路径）
- **参数 (args)**: `["D:\\工具目录\\mcp_server.py"]`
- **工作目录 (cwd)**: `D:\工具目录`

保存后即可在 workbuddy 中调用以下工具。

## 三、可用工具清单

| 工具名 | 功能 | 关键参数 |
|---|---|---|
| `transcribe_audio_tool` | 转写本地音频为中文文本 | `audio_path`(必填), `model` |
| `generate_minutes_tool` | 根据转写文本生成《需求调研纪要》(Markdown+Mermaid) | `text`(必填), `backend`, `api_key`, `base_url`, `model`, `start_time`, `end_time` |
| `export_minutes_tool` | 导出纪要文件 md/html/pdf/docx | `markdown_text`(必填), `fmt`, `output_dir` |
| `list_models_tool` | 列出全部 Whisper 模型 | - |
| `add_model_tool` | 新增自定义模型 | `name`, `path`(必填) |
| `update_model_tool` | 修改自定义模型 | `name`, `path`, `desc`, `enabled`, `locked` |
| `delete_model_tool` | 删除自定义模型 | `name` |
| `get_settings_tool` | 读取全局配置 | - |
| `update_settings_tool` | 更新全局配置 | `backend`, `api_key`, `openai_base_url`, `openai_model`, `whisper_model`, `export_fmt` |
| `test_config_tool` | 测试模型路径与后端连通性 | `model`, `backend`, `api_key` |

## 四、调用示例

### 4.1 workbuddy / MCP 客户端（自然语言）

```
请把 D:/会议/客户访谈_0803.mp3 转写出来，然后生成一份需求调研纪要并导出为 pdf。
```

客户端会自动依次调用 `transcribe_audio_tool` → `generate_minutes_tool` → `export_minutes_tool`。

### 4.2 Python 脚本调用（stdio）

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MCP_CMD = r"D:\Python313\python.exe"
MCP_DIR = r"D:\工具目录"

async def call_tool(name: str, args: dict):
    params = StdioServerParameters(command=MCP_CMD, args=["mcp_server.py"], cwd=MCP_DIR)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(name, args)
            return res.content[0].text

async def main():
    # 1) 转写音频
    r1 = await call_tool("transcribe_audio_tool", {"audio_path": r"D:/会议/客户访谈_0803.mp3"})
    print(r1)

    # 2) 生成纪要
    r2 = await call_tool("generate_minutes_tool", {"text": "客户提到库存管理效率低...", "backend": "openai"})
    print(r2)

    # 3) 导出 pdf
    r3 = await call_tool("export_minutes_tool", {"markdown_text": r2, "fmt": "pdf"})
    print(r3)

asyncio.run(main())
```

### 4.3 HTTP 传输调用

先启动：`python mcp_server.py --http 127.0.0.1:8000`

```bash
# 1) 握手初始化
curl -i -X POST http://127.0.0.1:8000/mcp \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'

# 2) 列出工具
curl -X POST http://127.0.0.1:8000/mcp \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

> 提示：HTTP 传输是流式会话，curl 手动调用需携带返回的 `Mcp-Session-Id` 请求头；复杂场景建议直接用 4.2 的 Python 客户端或 4.4 的命令行。

### 4.4 命令行快速调用（无需 MCP 客户端）

每个 MCP 工具都有对应的 CLI 命令，输出 JSON：

```bash
# 测试配置
python cli.py test-config --backend openai

# 转写
python cli.py transcribe --audio D:/会议/客户访谈_0803.mp3 --model 中文优化版

# 生成纪要
python cli.py generate --text "客户提到库存管理效率低..." --backend openai --api-key nvapi-xxx

# 导出
python cli.py export --input minutes.md --fmt pdf

# 模型管理
python cli.py models list
python cli.py models add --name 中文优化版 --path D:/models/whisper-small-zh

# 配置管理
python cli.py config get
python cli.py config set --backend ollama --whisper-model small
```

## 五、返回格式

所有工具返回统一 JSON 结构：

```json
{ "ok": true, "text": "转写文本...", "elapsed": 3.2 }
{ "ok": false, "error": "错误原因" }
```

- `ok`：是否成功
- 成功时附带业务字段（如 `text` / `minutes` / `path` / `models` / `settings`）
- 失败时附带 `error` 说明

## 六、常见问题

- **转写失败：音频文件不存在** → 检查 `audio_path` 为服务器本地绝对路径。
- **生成纪要 401/403** → 在 `.env` 检查 `API_KEY` 与 `OPENAI_BASE_URL`，用 `test_config_tool` 验证。
- **Ollama 连接失败** → 先启动 `ollama serve` 并 `ollama pull` 对应模型。
- **模型未找到** → 用 `add_model_tool` 添加自定义模型（路径需真实存在），或选内置 `small`。
