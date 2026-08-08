---
name: local-mic-mcp
description: 本地麦克风 MCP 连接器（OS 级原生录音 + 多模式生成）。当用户希望在 WorkBuddy 对话里"一键（首次需 OS 授权）录音"、把语音实时/停止后转写进对话、或抱怨浏览器录音权限/兼容性（webm 容器 Invalid data、麦克风弹窗）时，使用本技能。它提供 FastMCP(stdio) server 模板：sounddevice 抓系统麦克风 → 写 WAV → faster-whisper 转写，暴露 mic_start/mic_stop/mic_status/mic_transcribe/mic_generate 五个工具；mic_generate 支持录音结束后按不同方式加工（默认"业务需求调研"，另含客户需求/会议纪要/待办清单/摘要/纯转写），优先由 WorkBuddy 自身模型生成，未接入时自动用 LLM 兜底。并说明如何注册到 ~/.workbuddy/mcp.json 与验证。解压即用。
license: MIT
---

# 本地麦克风 MCP 连接器（OS 级原生录音）

让 WorkBuddy 在**不依赖浏览器**的情况下直接抓系统麦克风、转写文本回对话。相比浏览器内 `MediaRecorder`/`Web Audio` 方案，它首次 OS 授权后不再弹窗，更接近原生。

## 何时用
- 用户要在对话里录音但嫌浏览器录音麻烦/报错（webm `Invalid data`、麦克风弹窗）。
- 已确认方案为"纯 MCP 原生录音（停止后出结果）"——MCP 是请求/响应模型，不原生支持对话内实时滚动（实时滚动需浏览器组件或 agent 轮询，本技能不覆盖）。

## 目录结构
```
local-mic-mcp/
├── SKILL.md            # 本文件
└── scripts/
    ├── server.py       # FastMCP stdio 服务（麦克风录音 + 转写），可直接用
    └── test_client.py  # stdio 客户端联调脚本，验证连接器是否健康
```

## 前置依赖（一次性）
复用任意 managed Python venv（需已装 faster-whisper + sounddevice + numpy）：
```
"<venv>/Scripts/pip.exe" install fastmcp
```
> ⚠️ 坑：旧 `mcp` 2.0.0 已移除 `mcp.server.fastmcp`，`from mcp.server.fastmcp import FastMCP` 会报 ModuleNotFoundError。装 `fastmcp` 会自动把 `mcp` 降到 1.29.0（含 fastmcp 子模块），即可用。

## 部署步骤
1. 把 `scripts/server.py` 复制到目标位置（如 `<workspace>/mic-recorder/server.py`）。
2. 在 `~/.workbuddy/mcp.json` 合并注册（**不要覆盖其它 server**）：
   ```json
   {
     "mcpServers": {
       "mic-recorder": {
         "command": "<venv>/Scripts/python.exe",
         "args": ["<目标路径>/server.py"],
         "env": {}
       }
     }
   }
   ```
3. 在 WorkBuddy **连接器管理页**找到 `mic-recorder` 点「信任」启用（安全确认，代理不能代点）。
4. 重启 WorkBuddy 让新 `mcp.json` 生效（若没自动加载）。

## 验证（无需真实麦克风）
```
"<venv>/Scripts/python.exe" <目标路径>/test_client.py
```
期望输出：`TOOLS: ['mic_start', 'mic_stop', 'mic_status', 'mic_transcribe']` 且 `STDIO_HANDSHAKE_OK`。
此脚本用 `mcp.client.stdio` 真实拉起 server 并 list_tools + 调 mic_status，等价于 WorkBuddy 加载时的握手。

## 使用（对话里）
- 用户说「开始录音」→ 代理调 `mic_start()`（首次 Windows 弹麦克风授权，允许即可）。
- 用户说「停止」→ 代理调 `mic_stop()`，返回 WAV 路径 + 时长 + 大小（**不含转写**）。
- 生成 → 代理调 `mic_generate()`（见下「生成方式」章节）。同一回合内 `mic_start → mic_stop → mic_generate` 完成。
- 纯转写（不加模式加工）→ 代理调 `mic_transcribe()` 不带参数（自动用最近保存的文件），或 `mic_transcribe(file="path")` 指定文件。
- `mic_status()` 查状态。

## 生成方式（录音结束后）

`mic_stop` 只存 WAV（快速），录音结束后的「加工」由 `mic_generate(mode, file)` 负责：先转写，再按 `mode` 加工。

**内置模式**（默认 `business_requirement`）：

| mode | 含义 | 说明 |
|---|---|---|
| `business_requirement` | 业务需求调研 | **默认**。按背景/痛点/核心需求/干系人/约束/待确认 框架结构化 |
| `customer_requirement` | 客户需求 | 客户视角：明确需求/潜在需求/顾虑/优先级 |
| `meeting_minutes` | 会议纪要 | 主题/参与人/讨论/决议/下一步 |
| `action_items` | 待办清单 | 事项 \| 负责人 \| 截止时间 \| 优先级 |
| `summary` | 一句话摘要 | 3-5 条要点概括 |
| `transcript` | 纯转写 | 原样返回逐字稿（同 `mic_transcribe`） |

**双引擎（WorkBuddy 优先，LLM 兜底）**：
1. **WorkBuddy 自身生成（默认/优先）**：`mic_generate` 返回「转写文本 + 该模式的 SYSTEM_PROMPT」，由 WorkBuddy 的模型按模式产出结构化结果。零新依赖、不需 API key。
2. **LLM 兜底（WorkBuddy 未接入时自动启用）**：若配置了 LLM 环境变量，`mic_generate` 会**在技能内直接调用 LLM** 生成结果再返回；即使脱离 WorkBuddy 单独跑也能出成品。
   - 读取顺序：`MIC_LLM_BASE_URL` / `MIC_LLM_API_KEY` / `MIC_LLM_MODEL`，未设置时**复用**项目的 `APP_OPENAI_BASE_URL` / `APP_OPENAI_API_KEY` / `APP_OPENAI_MODEL`（兼容 OpenAI 接口）。
   - LLM 兜底通过 `httpx`（mcp 已自带）直接请求 `/chat/completions`，**无需额外安装 `openai` 包**；调用失败会优雅回退为「转写 + 提示词」交给 WorkBuddy。
   - 仅当这些变量存在时才走 LLM 路径；否则一律回退为「转写 + 提示词」交给 WorkBuddy。

> 对话里代理应在 `mic_stop` 后**询问用户用哪种 mode**（默认业务需求调研），再调 `mic_generate(mode=...)`；若用户直接说「整理成会议纪要」，代理传 `mode="meeting_minutes"` 即可。

> ⚠️ **重要限制**：
> 1. **不能跨回合**：MCP stdio 进程跨回合可能重启，内存中的录音状态会丢失。必须同一回合内 `mic_start` → 说话 → `mic_stop`。
> 2. **长录音转写**：`mic_stop` 已拆分为只停录存 WAV（快速），转写用 `mic_transcribe` 单独调。但长录音（>10 分钟）转写仍可能超时，此时建议走独立脚本。

## 关键实现要点（server.py 内已处理）
- **抓麦**：`sounddevice.InputStream(samplerate=16000, channels=1, dtype="int16", callback=...)` 在后台线程累积 `indata.copy()`；停止时 `np.concatenate` 写 WAV（16k 单声道 16-bit）。
- **转写**：`faster_whisper.WhisperModel(model, device="cpu", compute_type="int8")`。
  > ⚠️ 本机无 CUDA 驱动，`device="auto"` 会因 `cublas64_12.dll` 找不到而整体失败——**必须强制 `device="cpu"`**。
- **为何不用 webm**：浏览器 `MediaRecorder` 产出的 webm/opus 容器常缺头，PyAV 探针失败报 `[Errno 1094995529] Invalid data`；OS 级直接抓 PCM 写 WAV 可彻底规避。

## 故障排查
- `mic_start` 返回「无法开启麦克风」→ 无输入设备或 WorkBuddy 进程无麦克风权限。
- 工具列表里没有 `mic-recorder` → 没信任成功，或 WorkBuddy 未重载 mcp.json（重启）。
- 转写报 `cublas64_12.dll` → 确认 server.py 里 `device="cpu"`。
- `mic_stop` 超时 → 大概率跨回合调用了（MCP 进程重启，状态丢失）。同一回合内调用即可。
- `mic_transcribe` 超时 → 文件太大（>10 分钟），CPU 转写耗时超 MCP 超时。走独立脚本转写。
- `mic_generate` 返回「[LLM 生成失败…]」→ 检查 `MIC_LLM_*` / `APP_OPENAI_*` 是否配置正确、网络与 key 是否有效；失败时会自动回退为「转写 + 模式提示词」交给 WorkBuddy 生成。
- `mic_generate` 未知 mode → 用 `business_requirement` 等上表 6 个值之一。
