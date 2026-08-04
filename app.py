#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
客户需求调研纪要工具 - Web 版
用法:
    python app.py [--host 0.0.0.0] [--port 5000]
浏览器打开 http://127.0.0.1:5000
"""

import os
import sys
import io
import json
import time
import argparse
import threading
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, render_template, send_file

# 国内网络直连 huggingface.co 会 SSL 证书校验失败，必须在导入 faster_whisper 前设置镜像
if "HF_ENDPOINT" not in os.environ:
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from faster_whisper import WhisperModel

from mdconvert import convert_markdown, EXPORT_FORMATS
from config import (
    list_models, add_custom_model, update_custom_model,
    delete_custom_model, update_settings, resolve_model_path,
    resolve_model, get_config,
)

# ========================== 配置 ==========================
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2:7b"  # 可改为你已下载的其他模型

WHISPER_SIZES = ["tiny", "base", "small", "medium", "large-v3"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "exports")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB 上传上限

_model_lock = threading.Lock()
_model = None
_model_name = None

# ========================== AI 生成纪要 ==========================
REQ_SYSTEM_PROMPT = """你是一位资深的产品需求分析师。请基于提供的客户调研/需求访谈录音文字，生成一份结构化的《需求调研纪要》，使用 Markdown 格式，要求：
1. 文档以 `# 《需求调研纪要》` 为一级标题开头
2. 包含以下小节（二级标题 `##`）：
   - ## 调研概要：会议时间、参会客户、调研主题
   - ## 客户核心诉求与痛点：客户的真实需求、遇到的困难、期望解决的问题
   - ## 需求明细：尽量按业务场景/模块归类，区分"明确需求"和"潜在需求"，用表格呈现
   - ## 需求优先级：基于客户表述的紧迫程度标注 P0/P1/P2，用表格呈现
   - ## 待确认事项与行动项：哪些需求需要进一步沟通确认、后续跟进人/时间，用表格呈现
3. 最后增加一节 `## 业务流程图`：根据录音中描述的业务流程（或从需求中推断），用 Mermaid `flowchart TD` 语法绘制业务流程图，放在 ```mermaid 代码块中；若无法推断明确流程，则绘制"需求调研到需求确认"的流程
4. 只依据录音内容归纳，不要编造；内容未提到就标注"未提及"。
输出请直接给出 Markdown 正文，不要额外解释。"""


def _format_time(dt):
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "未记录"


def generate_minutes_with_openai(text, start_time=None, end_time=None, api_key=None,
                                 base_url=None, model=None, on_log=None):
    """调用 OpenAI 兼容接口生成需求调研纪要（NVIDIA、OpenAI、通义等），长录音分段摘要"""
    import requests
    log = on_log or (lambda m: None)
    base_url = (base_url or "").strip() or get_config()["settings"].get("OPENAI_BASE_URL", "").strip()
    model = (model or "").strip() or get_config()["settings"].get("OPENAI_MODEL", "").strip() or NVIDIA_MODEL
    api_key = (api_key or "").strip() or get_config()["settings"].get("API_KEY", "").strip()
    if not base_url:
        raise ValueError("未配置 OpenAI API 地址 (OPENAI_BASE_URL)")
    if not api_key:
        raise ValueError("未设置 API Key")
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    time_info = f"会议时间：{_format_time(start_time)} - {_format_time(end_time)}"

    def call(messages, max_tokens):
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": max_tokens
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=180)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    if len(text) > 4000:
        log("录音文本较长，正在分段摘要（最长支持约 5 小时录音）...")
        chunk_size = 4000
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        summaries = []
        for idx, chunk in enumerate(chunks, 1):
            messages = [
                {"role": "system", "content": "你是需求分析助手，请提取下面这段录音文本中的客户需求要点（诉求、痛点、需求点），简洁输出，不要遗漏。"},
                {"role": "user", "content": f"第 {idx}/{len(chunks)} 段录音：\n{chunk}"}
            ]
            summaries.append(f"【第{idx}段】\n{call(messages, 800)}")
        combined = "\n\n".join(summaries)
        messages = [
            {"role": "system", "content": REQ_SYSTEM_PROMPT},
            {"role": "user", "content": f"{time_info}\n\n以下是分段摘要的汇总（来自同一场客户调研）：\n{combined}"}
        ]
        return call(messages, 2048)

    messages = [
        {"role": "system", "content": REQ_SYSTEM_PROMPT},
        {"role": "user", "content": f"{time_info}\n\n客户调研录音文字：\n{text}"}
    ]
    return call(messages, 2048)


def generate_minutes_with_ollama(text, start_time=None, end_time=None):
    """调用本地 Ollama 生成需求调研纪要，长录音分段摘要"""
    import requests
    time_info = f"会议时间：{_format_time(start_time)} - {_format_time(end_time)}"

    def call(prompt):
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "temperature": 0.3
        }
        resp = requests.post(OLLAMA_URL, json=payload, timeout=300)
        resp.raise_for_status()
        return resp.json()["response"]

    if len(text) > 4000:
        chunk_size = 4000
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        summaries = []
        for idx, chunk in enumerate(chunks, 1):
            summaries.append(f"【第{idx}段】\n{call(f'你是需求分析助手，请提取下面这段录音文本中的客户需求要点（诉求、痛点、需求点），简洁输出，不要遗漏。\\n第 {idx}/{len(chunks)} 段录音：\\n{chunk}')}")
        combined = "\n\n".join(summaries)
        return call(f"{time_info}\n\n{REQ_SYSTEM_PROMPT}\n\n以下是分段摘要的汇总（来自同一场客户调研）：\n{combined}")

    return call(f"{time_info}\n\n{REQ_SYSTEM_PROMPT}\n\n客户调研录音文字：\n{text}")


# ========================== Whisper 模型管理 ==========================
def _get_model(name_or_path):
    """按需加载/缓存 Whisper 模型（线程安全）"""
    global _model, _model_name
    key = name_or_path or "small"
    with _model_lock:
        if _model is not None and _model_name == key:
            return _model
        try:
            _model = WhisperModel(key, device="auto", compute_type="int8")
        except Exception:
            _model = WhisperModel(key, device="auto", compute_type="float32")
        _model_name = key
        return _model


def transcribe_audio(filename, name_or_path="small"):
    """使用 faster-whisper 转写音频，返回文本"""
    model = _get_model(name_or_path)
    segments, _ = model.transcribe(filename, language="zh")
    return "".join([seg.text for seg in segments]).strip()


# ========================== 模型配置检测 ==========================
def _check_whisper_model(model_name):
    """检查 Whisper 模型配置是否可用。返回 (ok, message)"""
    model_name = (model_name or "").strip() or "small"
    # 若是自定义模型名，解析其路径
    resolved = resolve_model_path(model_name)
    custom = resolve_model(model_name)
    if custom is not None:
        path = custom.get("path", "")
        if not path:
            return False, f"模型「{model_name}」未配置模型地址"
        if not os.path.exists(path):
            return False, f"模型「{model_name}」的路径不存在: {path}"
        return True, f"模型「{model_name}」配置有效，路径存在"
    # 内置模型名（tiny~large-v3）由 faster-whisper 自动下载
    if resolved in WHISPER_SIZES:
        return True, f"内置模型「{resolved}」可用（首次使用时自动下载）"
    # 直接填写了本地路径
    if os.path.exists(resolved):
        return True, f"模型路径有效: {resolved}"
    return False, f"未找到模型「{model_name}」，请先在「配置 - 管理模型」中添加或选择有效模型"


def _check_backend(backend, api_key):
    """检查 AI 后端配置。返回 (ok, message)"""
    backend = (backend or "openai").strip()
    settings = get_config()["settings"]
    if backend == "openai":
        base_url = settings.get("OPENAI_BASE_URL", "").strip()
        key = (api_key or "").strip() or settings.get("API_KEY", "").strip()
        if not base_url:
            return False, "未配置 OpenAI API 地址 (OPENAI_BASE_URL)"
        if not key:
            return False, "未配置 API Key，请在「配置」中填写"
        return True, f"OpenAI 兼容后端已配置（{base_url}）"
    elif backend == "ollama":
        import socket
        try:
            s = socket.create_connection(("localhost", 11434), timeout=3)
            s.close()
            return True, "Ollama 服务正在运行"
        except Exception:
            return False, "Ollama 服务未启动，请先在本地运行 ollama serve"
    return False, f"未知后端: {backend}"


@app.route("/api/check-config", methods=["POST"])
def check_config_api():
    """录音前校验模型配置是否完整可用。参数: model, backend, api_key"""
    data = request.get_json(force=True) or {}
    model_name = data.get("model", "")
    backend = data.get("backend", "openai")
    api_key = data.get("api_key", "")

    m_ok, m_msg = _check_whisper_model(model_name)
    b_ok, b_msg = _check_backend(backend, api_key)

    # 后端测试：真实调用一次验证 key/服务可用
    test_backend_ok = True
    test_backend_msg = "（未执行网络测试）"
    try:
        if backend == "openai":
            key = (api_key or "").strip() or get_config()["settings"].get("API_KEY", "").strip()
            test_backend_ok, test_backend_msg = _test_openai(api_key=key)
        elif backend == "ollama":
            test_backend_ok, test_backend_msg = _test_ollama()
    except Exception as e:
        test_backend_ok = False
        test_backend_msg = f"后端测试异常: {e}"

    ok = m_ok and b_ok and test_backend_ok
    return jsonify({
        "ok": ok,
        "model": {"ok": m_ok, "message": m_msg},
        "backend": {"ok": b_ok, "message": b_msg},
        "backend_test": {"ok": test_backend_ok, "message": test_backend_msg},
    })


def _test_openai(api_key=None, base_url=None, model=None):
    """真实调用 OpenAI 兼容 API 验证 key/地址/模型（极小请求）"""
    import requests
    settings = get_config()["settings"]
    base_url = (base_url or "").strip() or settings.get("OPENAI_BASE_URL", "").strip()
    model = (model or "").strip() or settings.get("OPENAI_MODEL", "").strip() or NVIDIA_MODEL
    api_key = (api_key or "").strip() or settings.get("API_KEY", "").strip()
    if not base_url:
        return False, "未配置 OpenAI API 地址 (OPENAI_BASE_URL)"
    if not api_key:
        return False, "未配置 API Key"
    try:
        resp = requests.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return True, f"OpenAI 兼容接口验证通过（模型：{model}）"
        return False, f"接口返回错误 {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, f"接口连接失败: {e}"


def _test_ollama():
    """验证 Ollama 服务与模型"""
    import requests
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": "ping",
            "stream": False,
        }, timeout=30)
        if resp.status_code == 200:
            return True, f"Ollama 模型「{OLLAMA_MODEL}」可用"
        return False, f"Ollama 返回错误 {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, f"Ollama 连接失败: {e}"


# ========================== 路由 ==========================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/info")
def info():
    return jsonify({
        "whisper_sizes": WHISPER_SIZES,
        "export_formats": EXPORT_FORMATS,
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "models": list_models(),
        "settings": None,
        "default_model_path": find_default_model_path(),
    })


def find_default_model_path():
    """返回默认模型地址：
    1. 优先项目内 models 目录（存在时）
    2. 其次查找本机已缓存的 faster-whisper 模型路径
    """
    project_models = os.path.join(BASE_DIR, "models")
    if os.path.isdir(project_models):
        return project_models

    home = os.path.expanduser("~")
    hf_hub = os.path.join(home, ".cache", "huggingface", "hub")
    if not os.path.isdir(hf_hub):
        return ""
    # 优先 small，其次任意已缓存模型
    ordered = []
    for size in WHISPER_SIZES:
        d = os.path.join(hf_hub, f"models--Systran--faster-whisper-{size}")
        if os.path.isdir(d):
            ordered.append(d)
    if not ordered:
        for d in sorted(os.listdir(hf_hub)):
            if d.startswith("models--") and "whisper" in d:
                ordered.append(os.path.join(hf_hub, d))
    if not ordered:
        return ""
    # 找到 snapshots 下的具体版本目录
    for d in ordered:
        snap = os.path.join(d, "snapshots")
        if os.path.isdir(snap):
            versions = sorted(os.listdir(snap))
            if versions:
                return os.path.join(snap, versions[0])
    return ordered[0]


@app.route("/api/transcribe", methods=["POST"])
def transcribe_api():
    """上传音频并转写。参数: file(音频文件), model(模型名或本地路径)"""
    if "file" not in request.files:
        return jsonify({"error": "未收到音频文件"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "音频文件名为空"}), 400
    model_arg = resolve_model_path(request.form.get("model", "small"))

    ext = os.path.splitext(f.filename)[1] or ".webm"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = os.path.join(UPLOAD_DIR, f"recording_{ts}{ext}")
    f.save(save_path)

    try:
        start = time.time()
        text = transcribe_audio(save_path, model_arg)
        if not text:
            return jsonify({"error": "转写结果为空"}), 500
        return jsonify({
            "text": text,
            "elapsed": round(time.time() - start, 1),
            "audio_file": os.path.basename(save_path),
            "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    except Exception as e:
        return jsonify({"error": f"转写失败: {e}"}), 500


@app.route("/api/generate", methods=["POST"])
def generate_api():
    """根据转写文本生成需求调研纪要。参数: text, backend, api_key, base_url, model, start_time, end_time"""
    data = request.get_json(force=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "转写文本为空"}), 400

    backend = data.get("backend", "openai")
    api_key = data.get("api_key", "").strip()
    base_url = data.get("base_url", "").strip()
    model = data.get("model", "").strip()
    start_time = data.get("start_time")
    end_time = data.get("end_time")

    def parse_time(s):
        if not s:
            return None
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    try:
        if backend == "openai":
            minutes = generate_minutes_with_openai(
                text, parse_time(start_time), parse_time(end_time),
                api_key=api_key, base_url=base_url, model=model,
            )
        elif backend == "ollama":
            minutes = generate_minutes_with_ollama(text, parse_time(start_time), parse_time(end_time))
        else:
            return jsonify({"error": f"未知后端: {backend}"}), 400
        if not minutes:
            return jsonify({"error": "生成纪要失败（后端无返回）"}), 500
        return jsonify({"minutes": minutes})
    except Exception as e:
        return jsonify({"error": f"生成纪要失败: {e}"}), 500


@app.route("/api/export", methods=["POST"])
def export_api():
    """导出纪要。参数: minutes(Markdown), fmt(md/html/pdf/docx)"""
    data = request.get_json(force=True) or {}
    content = data.get("minutes", "").strip()
    fmt = (data.get("fmt", "md") or "md").lower().lstrip(".")
    if not content:
        return jsonify({"error": "纪要内容为空"}), 400
    if fmt not in EXPORT_FORMATS:
        return jsonify({"error": f"不支持的格式: {fmt}"}), 400

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(OUTPUT_DIR, f"minutes_{ts}")
    try:
        path = convert_markdown(content, fmt, base)
        filename = os.path.basename(path)
        mime_map = {
            "md": "text/markdown; charset=utf-8",
            "html": "text/html; charset=utf-8",
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        return send_file(path, as_attachment=True, download_name=filename,
                         mimetype=mime_map.get(fmt, "application/octet-stream"))
    except Exception as e:
        return jsonify({"error": f"导出失败: {e}"}), 500


# ========================== 模型管理 API ==========================
@app.route("/api/models", methods=["GET"])
def models_list_api():
    try:
        return jsonify({"models": list_models()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/models", methods=["POST"])
def models_add_api():
    data = request.get_json(force=True) or {}
    try:
        m = add_custom_model(data.get("name", ""), data.get("path", ""), data.get("desc", ""))
        return jsonify({"model": m}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/models/<name>", methods=["PUT"])
def models_update_api(name):
    data = request.get_json(force=True) or {}
    try:
        m = update_custom_model(name, path=data.get("path"), desc=data.get("desc"), enabled=data.get("enabled"))
        return jsonify({"model": m})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/models/<name>", methods=["DELETE"])
def models_delete_api(name):
    try:
        m = delete_custom_model(name)
        return jsonify({"model": m})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/settings", methods=["GET"])
def settings_get_api():
    from config import get_config
    return jsonify({"settings": get_config()["settings"]})


@app.route("/api/settings", methods=["POST"])
def settings_update_api():
    data = request.get_json(force=True) or {}
    try:
        s = update_settings(data)
        return jsonify({"settings": s})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="客户需求调研纪要工具 - Web 版")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="监听端口 (默认 5000)")
    args = parser.parse_args()
    print(f"启动服务: http://{args.host}:{args.port}  (Ctrl+C 退出)")
    app.run(host=args.host, port=args.port, threaded=True)
