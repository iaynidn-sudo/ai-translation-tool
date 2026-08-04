# 客户需求调研纪要工具

浏览器录音 / 上传音频 → Whisper 转写 → AI 生成结构化《需求调研纪要》（含业务流程图）→ 导出 md/html/pdf/docx。
支持 Web 页面、MCP 协议、命令行三种方式调用，可集成到 workbuddy 等工具。

## 一、安装依赖

要求 Python 3.10+（推荐 3.13）。国内网络建议先设置镜像：

```bash
pip install -r requirements.txt
```

如需 GPU 转写更快，安装 CUDA 版 ctranslate2 并复制对应 cublas/cudnn DLL（见项目说明）。

## 二、配置

复制 `.env.example` 为 `.env` 并填写：

```bash
copy .env.example .env
```

| 配置项 | 说明 |
|---|---|
| `BACKEND` | AI 后端：`openai`（兼容 NVIDIA/OpenAI/通义等）或 `ollama`（本地） |
| `API_KEY` | OpenAI 兼容后端的 API Key；Ollama 无需填写 |
| `OPENAI_BASE_URL` | OpenAI 兼容后端地址，默认 NVIDIA 网关 |
| `OPENAI_MODEL` | 模型名，默认 NVIDIA Nemotron |
| `WHISPER_MODEL` | 默认转写模型（内置 small 或自定义模型名） |
| `MODEL_N_NAME/PATH/...` | 自定义 Whisper 本地模型（路径需存在） |

## 三、方式一：Web 页面

```bash
python app.py --port 5000
```

浏览器打开 http://127.0.0.1:5000 ，页面支持录音、上传音频、生成纪要、导出、配置管理与一键「测试配置」。

## 四、方式二：MCP 协议（供 workbuddy 等调用）

标准 stdio 传输（本地 MCP 客户端最常用）：

```bash
python mcp_server.py
```

HTTP 传输（远程调用，可选）：

```bash
python mcp_server.py --http 127.0.0.1:8000
```

### workbuddy 集成示例

在 MCP 客户端配置中新增一个 stdio server，命令指向：

```
命令: D:\Python313\python.exe
参数: ["D:\\...\\mcp_server.py"]
```

暴露的工具：

| 工具 | 功能 |
|---|---|
| `transcribe_audio_tool` | 转写本地音频文件为中文文本 |
| `generate_minutes_tool` | 根据转写文本生成需求调研纪要（Markdown，含 Mermaid 流程图） |
| `export_minutes_tool` | 导出纪要文件 md/html/pdf/docx |
| `list_models_tool` / `add_model_tool` / `update_model_tool` / `delete_model_tool` | Whisper 模型管理 |
| `get_settings_tool` / `update_settings_tool` | 读取 / 修改全局配置 |
| `test_config_tool` | 测试模型路径与 AI 后端连通性 |

## 五、方式三：命令行

```bash
# 转写音频
python cli.py transcribe --audio D:/rec.mp3 --model 中文优化版

# 生成纪要
python cli.py generate --text "客户说..." --backend openai --api-key nvapi-xxx
python cli.py generate --input transcript.txt --backend ollama

# 导出
python cli.py export --input minutes.md --fmt pdf

# 模型管理
python cli.py models list
python cli.py models add --name 中文优化版 --path D:/models/whisper-small-zh --desc "本地中文优化模型"
python cli.py models update --name 中文优化版 --path D:/models/whisper-small-zh
python cli.py models delete --name 中文优化版

# 配置管理
python cli.py config get
python cli.py config set --backend ollama --whisper-model small

# 测试配置
python cli.py test-config --backend openai
```

所有命令输出 JSON，便于程序解析。

## 六、导出目录

生成的纪要文件默认保存在 `exports/` 目录；录音文件在 `uploads/`；转写模型优先使用项目内 `models/` 目录。

## 七、常见问题

- **转写很慢/无 GPU**：改用内置 `small` 模型；确认 ctranslate2 CUDA 库正常。
- **OpenAI 接口 401**：检查 `.env` 的 `API_KEY` 与 `OPENAI_BASE_URL`，用 `python cli.py test-config` 验证。
- **Ollama 连接失败**：先启动本地 `ollama serve`，并确认已 `ollama pull qwen2:7b`（或改 `OLLAMA_MODEL`）。
