#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
客户需求调研纪要工具 - MCP Server
将录音转写 / AI 生成纪要 / 导出 / 配置管理封装为 MCP 工具，供 workbuddy 等 MCP 客户端调用。

用法:
    python mcp_server.py                 # stdio 传输（默认，本地 MCP 客户端使用）
    python mcp_server.py --http 127.0.0.1:8000   # Streamable HTTP 传输（远程调用）
"""

import argparse
import os
import sys
import time
from datetime import datetime

from mcp.server.fastmcp import FastMCP

# 国内网络直连 huggingface.co 会 SSL 证书校验失败，必须在导入 faster_whisper 前设置镜像
if "HF_ENDPOINT" not in os.environ:
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from app import (
    transcribe_audio,
    generate_minutes_with_openai,
    generate_minutes_with_ollama,
    _test_openai,
    _test_ollama,
    _check_whisper_model,
    _check_backend,
    find_default_model_path,
    BASE_DIR,
    OUTPUT_DIR,
)
from config import (
    list_models,
    add_custom_model,
    update_custom_model,
    delete_custom_model,
    update_settings,
    resolve_model_path,
    get_config,
)
from mdconvert import convert_markdown, EXPORT_FORMATS

mcp = FastMCP("需求调研纪要工具")


def _parse_time(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def _resolve_model_arg(model):
    return resolve_model_path(model) if model else "small"


# ========================== 转写 ==========================
@mcp.tool(
    description="转写音频文件为中文文本。输入本地音频文件路径（wav/mp3/m4a/webm 等），返回 Whisper 转写结果。"
)
def transcribe_audio_tool(audio_path: str, model: str = "") -> dict:
    """转写本地音频文件。
    Args:
        audio_path: 本地音频文件绝对路径。
        model: Whisper 模型名或本地模型路径（如 small、中文优化版，留空用默认配置）。
    """
    if not audio_path or not os.path.exists(audio_path):
        return {"ok": False, "error": f"音频文件不存在: {audio_path}"}
    start = time.time()
    try:
        text = transcribe_audio(audio_path, _resolve_model_arg(model))
        return {"ok": True, "text": text, "elapsed": round(time.time() - start, 1)}
    except Exception as e:
        return {"ok": False, "error": f"转写失败: {e}"}


# ========================== AI 生成纪要 ==========================
@mcp.tool(
    description="根据转写文本生成结构化《需求调研纪要》（Markdown，含业务流程图）。后端支持 openai 兼容接口 / ollama。"
)
def generate_minutes_tool(
    text: str,
    backend: str = "openai",
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    start_time: str = "",
    end_time: str = "",
) -> dict:
    """生成需求调研纪要。
    Args:
        text: 客户调研录音转写文本。
        backend: AI 后端，openai（兼容 NVIDIA/OpenAI/通义等）或 ollama（本地）。
        api_key: OpenAI 兼容后端的 API Key，留空回退配置文件。
        base_url: OpenAI 兼容后端地址（如 https://integrate.api.nvidia.com/v1），留空用配置。
        model: OpenAI 兼容后端的模型名，留空用配置。
        start_time: 会议开始时间（可选，格式 2026-08-03 14:00:00）。
        end_time: 会议结束时间（可选）。
    """
    if not text or not text.strip():
        return {"ok": False, "error": "转写文本为空"}
    try:
        if backend == "ollama":
            minutes = generate_minutes_with_ollama(text, _parse_time(start_time), _parse_time(end_time))
        else:
            minutes = generate_minutes_with_openai(
                text, _parse_time(start_time), _parse_time(end_time),
                api_key=api_key, base_url=base_url, model=model,
            )
        if not minutes:
            return {"ok": False, "error": "生成纪要失败（后端无返回）"}
        return {"ok": True, "minutes": minutes}
    except Exception as e:
        return {"ok": False, "error": f"生成纪要失败: {e}"}


# ========================== 导出 ==========================
@mcp.tool(
    description="将 Markdown 纪要导出为文件（md/html/pdf/docx），返回保存路径。"
)
def export_minutes_tool(markdown_text: str, fmt: str = "md", output_dir: str = "") -> dict:
    """导出纪要文件。
    Args:
        markdown_text: Markdown 纪要内容。
        fmt: 导出格式，md / html / pdf / docx。
        output_dir: 输出目录（绝对路径），留空用默认 exports 目录。
    """
    fmt = (fmt or "md").lower().lstrip(".")
    if fmt not in EXPORT_FORMATS:
        return {"ok": False, "error": f"不支持的格式: {fmt}，可选 {EXPORT_FORMATS}"}
    if not markdown_text or not markdown_text.strip():
        return {"ok": False, "error": "纪要内容为空"}
    out_dir = output_dir or OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(out_dir, f"minutes_{ts}")
    try:
        path = convert_markdown(markdown_text, fmt, base)
        return {"ok": True, "path": path, "format": fmt}
    except Exception as e:
        return {"ok": False, "error": f"导出失败: {e}"}


# ========================== 配置 / 模型管理 ==========================
@mcp.tool(description="列出所有 Whisper 转写模型（内置 + 自定义）。")
def list_models_tool() -> dict:
    try:
        return {"ok": True, "models": list_models()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool(description="新增自定义 Whisper 模型。name 需唯一，path 为本地模型目录绝对路径。")
def add_model_tool(name: str, path: str, desc: str = "") -> dict:
    try:
        m = add_custom_model(name, path, desc=desc)
        return {"ok": True, "model": m}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool(description="修改自定义 Whisper 模型。锁定模型需先解锁。")
def update_model_tool(
    name: str, path: str = "", desc: str = "", enabled: bool | None = None, locked: bool | None = None
) -> dict:
    try:
        m = update_custom_model(
            name, path=(path or None), desc=(desc if desc is not None else None),
            enabled=enabled, locked=locked,
        )
        return {"ok": True, "model": m}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool(description="删除自定义 Whisper 模型。锁定模型需先解锁。")
def delete_model_tool(name: str) -> dict:
    try:
        m = delete_custom_model(name)
        return {"ok": True, "model": m}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool(description="读取 AI 后端 / 转写模型等全局配置（含 OpenAI 兼容后端地址、模型名）。")
def get_settings_tool() -> dict:
    try:
        return {"ok": True, "settings": get_config()["settings"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool(
    description="更新全局配置。可设置 backend(openai/ollama)、api_key、openai_base_url、openai_model、whisper_model、export_fmt。"
)
def update_settings_tool(
    backend: str = "",
    api_key: str = "",
    openai_base_url: str = "",
    openai_model: str = "",
    whisper_model: str = "",
    export_fmt: str = "",
) -> dict:
    patch = {}
    if backend:
        patch["BACKEND"] = backend
    if api_key is not None:
        patch["API_KEY"] = api_key
    if openai_base_url:
        patch["OPENAI_BASE_URL"] = openai_base_url
    if openai_model:
        patch["OPENAI_MODEL"] = openai_model
    if whisper_model:
        patch["WHISPER_MODEL"] = whisper_model
    if export_fmt:
        patch["EXPORT_FMT"] = export_fmt
    try:
        return {"ok": True, "settings": update_settings(patch)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool(
    description="测试配置是否可用：校验 Whisper 模型路径，并真实调用 AI 后端验证 key/地址/模型连通性。"
)
def test_config_tool(model: str = "", backend: str = "openai", api_key: str = "") -> dict:
    try:
        model = model or get_config()["settings"].get("WHISPER_MODEL", "small")
        m_ok, m_msg = _check_whisper_model(model)
        b_ok, b_msg = _check_backend(backend, api_key)
        if backend == "ollama":
            t_ok, t_msg = _test_ollama()
        else:
            t_ok, t_msg = _test_openai(api_key=api_key)
        return {
            "ok": m_ok and b_ok and t_ok,
            "model": {"ok": m_ok, "message": m_msg},
            "backend": {"ok": b_ok, "message": b_msg},
            "backend_test": {"ok": t_ok, "message": t_msg},
            "default_model_path": find_default_model_path(),
        }
    except Exception as e:
        return {"ok": False, "error": f"测试异常: {e}"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="需求调研纪要工具 - MCP Server")
    parser.add_argument("--http", default="", help="以 HTTP 传输启动，格式 host:port（如 127.0.0.1:8000），缺省为 stdio")
    args = parser.parse_args()

    if args.http:
        host, _, port = args.http.partition(":")
        mcp = FastMCP("需求调研纪要工具", host=host or "127.0.0.1", port=int(port or 8000))
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
