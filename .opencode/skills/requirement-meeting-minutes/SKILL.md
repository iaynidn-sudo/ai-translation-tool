---
name: requirement-meeting-minutes
description: 客户需求调研纪要工具的使用技能。当用户提到录音转写、客户需求调研纪要、会议纪要生成、Whisper 转写、AI 纪要生成、纪要导出(md/html/pdf/docx)、MCP 调用本工具、workbuddy 集成、模型配置管理时，务必使用本技能。它指导代理通过 cli.py / mcp_server.py 完成「录音转写 → AI 生成需求调研纪要（含业务流程图）→ 导出文件」的完整流程。
---

# 客户需求调研纪要工具

本技能指导如何在**当前项目**（客户需求调研纪要工具）中使用命令行和 MCP 完成需求调研纪要的全流程。

## 工具路径

所有命令在本项目目录下执行（Windows 环境），Python 用 `python`（建议 `D:\usr\Project\Python313\python.exe`）。

```bash
cd D:\usr\Project\python\录音模型
```

## 能力概览

| 能力 | CLI 命令 | 说明 |
|---|---|---|
| 测试配置 | `python cli.py test-config [--backend openai|ollama]` | 校验转写模型路径 + AI 后端连通性 |
| 转写音频 | `python cli.py transcribe --audio <路径> [--model <模型>]` | Whisper 转写为中文文本 |
| 生成纪要 | `python cli.py generate --text <文本> [--input <文件>] --backend openai|ollama` | AI 生成结构化纪要（Markdown + Mermaid 流程图） |
| 导出纪要 | `python cli.py export --input <md文件> --fmt md|html|pdf|docx` | 导出为文件，保存到 exports/ |
| 模型管理 | `python cli.py models list/add/update/delete` | Whisper 模型增删改查 |
| 配置管理 | `python cli.py config get/set` | 读取/修改 .env 配置 |
| MCP 服务 | `python mcp_server.py [--http host:port]` | 启动 MCP server（stdio 或 HTTP） |

## 工作流程

### 1. 先测试配置

任何任务前先确认环境可用：

```bash
python cli.py test-config
```

- 转写模型「未找到」→ 用 `models add` 添加（路径需真实存在），或改配置用内置 `small`。
- 后端 401/连接失败 → 检查 `.env` 的 `API_KEY` / `OPENAI_BASE_URL` / Ollama 服务。

### 2. 转写音频

```bash
python cli.py transcribe --audio "D:/会议/客户访谈.mp3" --model 中文优化版
```

若音频很大（>1 小时），可先用 ffmpeg 分段或提示用户本工具支持长文本分段摘要。输出 JSON：`{"ok":true,"text":"...","elapsed":3.2}`。

### 3. 生成需求调研纪要

```bash
python cli.py generate --input transcript.txt --backend openai
# 或指定 key/地址/模型：
python cli.py generate --text "客户提到库存管理效率低..." --backend openai --api-key nvapi-xxx --base-url https://integrate.api.nvidia.com/v1 --model nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
```

生成的 Markdown 包含：调研概要、客户核心诉求与痛点、需求明细（明确/潜在）、需求优先级(P0/P1/P2)、待确认事项与行动项、业务流程图（Mermaid）。**只依据录音内容归纳，不编造。**

### 4. 导出文件

```bash
python cli.py export --input minutes.md --fmt pdf
```

保存到 `exports/minutes_<时间戳>.<格式>`。

## 关键配置（.env）

| 键 | 说明 |
|---|---|
| `BACKEND` | `openai`（兼容 NVIDIA/OpenAI/通义等）或 `ollama`（本地） |
| `API_KEY` | OpenAI 兼容后端 Key；Ollama 不需要 |
| `OPENAI_BASE_URL` | OpenAI 兼容地址，默认 NVIDIA 网关 |
| `OPENAI_MODEL` | 模型名 |
| `WHISPER_MODEL` | 默认转写模型 |
| `MODEL_N_NAME/PATH/...` | 自定义本地 Whisper 模型 |

修改配置用 `python cli.py config set --backend ollama --whisper-model small`，或直接编辑 `.env`。

## MCP 调用方式

workbuddy / Claude 等 MCP 客户端可调用 10 个工具（详见 `MCP调用文档.md`）：

- `transcribe_audio_tool`、`generate_minutes_tool`、`export_minutes_tool`
- `list_models_tool` / `add_model_tool` / `update_model_tool` / `delete_model_tool`
- `get_settings_tool` / `update_settings_tool` / `test_config_tool`

需要 MCP 服务时：`python mcp_server.py`（stdio）。HTTP 模式：`python mcp_server.py --http 127.0.0.1:8000`。

## 注意事项

- **Windows 控制台编码**：运行含中文输出的命令时设置 `PYTHONIOENCODING=utf-8`，避免乱码。
- **不要编造**：纪要内容只依据转写文本，未提及的信息标注「未提及」。
- **导出格式**：pdf 需系统有 SimHei/Microsoft YaHei 字体；docx 依赖 htmldocx。
- **长录音**：超过 4000 字文本会自动分段摘要，无需手动处理。
