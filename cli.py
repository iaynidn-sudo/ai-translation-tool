#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
客户需求调研纪要工具 - 命令行接口（CLI）
供 workbuddy 等以子进程方式调用。

用法示例:
    python cli.py transcribe --audio D:/rec.mp3 --model 中文优化版
    python cli.py generate --text "转写文本" --backend openai
    python cli.py export --fmt pdf --input minutes.md
    python cli.py models list
    python cli.py models add --name 中文优化版 --path D:/models/whisper-zh
    python cli.py config get
    python cli.py config set --backend ollama --whisper-model small
    python cli.py test-config
"""

import argparse
import json
import os
import sys

# 确保 stdout 使用 UTF-8，避免 Windows 控制台 cp936 导致中文乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import mcp_server
from config import get_config

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _emit(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_transcribe(args):
    result = mcp_server.transcribe_audio_tool(args.audio, args.model)
    _emit(result)


def cmd_generate(args):
    text = args.text
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            text = f.read()
    result = mcp_server.generate_minutes_tool(
        text, backend=args.backend, api_key=args.api_key,
        base_url=args.base_url, model=args.model,
        start_time=args.start_time, end_time=args.end_time,
    )
    _emit(result)


def cmd_export(args):
    content = args.input
    if args.input and os.path.exists(args.input):
        with open(args.input, "r", encoding="utf-8") as f:
            content = f.read()
    elif args.text:
        content = args.text
    result = mcp_server.export_minutes_tool(content, fmt=args.fmt, output_dir=args.output_dir)
    _emit(result)


def cmd_models(args):
    if args.action == "list":
        _emit(mcp_server.list_models_tool())
    elif args.action == "add":
        _emit(mcp_server.add_model_tool(args.name, args.path, args.desc))
    elif args.action == "update":
        _emit(mcp_server.update_model_tool(args.name, args.path, args.desc,
                                           enabled=args.enabled, locked=args.locked))
    elif args.action == "delete":
        _emit(mcp_server.delete_model_tool(args.name))
    else:
        print(json.dumps({"ok": False, "error": f"未知操作: {args.action}"}))


def cmd_config(args):
    if args.action == "get":
        _emit(mcp_server.get_settings_tool())
    elif args.action == "set":
        _emit(mcp_server.update_settings_tool(
            backend=args.backend or "", api_key=args.api_key or "",
            openai_base_url=args.base_url or "", openai_model=args.openai_model or "",
            whisper_model=args.whisper_model or "", export_fmt=args.fmt or "",
        ))
    else:
        print(json.dumps({"ok": False, "error": f"未知操作: {args.action}"}))


def cmd_test(args):
    _emit(mcp_server.test_config_tool(model=args.model, backend=args.backend, api_key=args.api_key))


def main():
    parser = argparse.ArgumentParser(description="客户需求调研纪要工具 - CLI")
    sub = parser.add_subparsers(dest="command")

    p_t = sub.add_parser("transcribe", help="转写音频文件")
    p_t.add_argument("--audio", required=True, help="音频文件路径")
    p_t.add_argument("--model", default="", help="Whisper 模型名或路径")
    p_t.set_defaults(func=cmd_transcribe)

    p_g = sub.add_parser("generate", help="根据文本生成需求调研纪要")
    p_g.add_argument("--text", default="", help="转写文本（与 --input 二选一）")
    p_g.add_argument("--input", default="", help="读取文本文件")
    p_g.add_argument("--backend", default="openai", choices=["openai", "ollama"])
    p_g.add_argument("--api-key", default="")
    p_g.add_argument("--base-url", default="")
    p_g.add_argument("--model", default="")
    p_g.add_argument("--start-time", default="")
    p_g.add_argument("--end-time", default="")
    p_g.set_defaults(func=cmd_generate)

    p_e = sub.add_parser("export", help="导出纪要文件")
    p_e.add_argument("--input", default="", help="Markdown 文件路径")
    p_e.add_argument("--text", default="", help="或直接提供 Markdown 内容")
    p_e.add_argument("--fmt", default="md", choices=["md", "html", "pdf", "docx"])
    p_e.add_argument("--output-dir", default="")
    p_e.set_defaults(func=cmd_export)

    p_m = sub.add_parser("models", help="模型管理")
    p_m.add_argument("action", choices=["list", "add", "update", "delete"])
    p_m.add_argument("--name", default="")
    p_m.add_argument("--path", default="")
    p_m.add_argument("--desc", default="")
    p_m.add_argument("--enabled", type=bool, default=None)
    p_m.add_argument("--locked", type=bool, default=None)
    p_m.set_defaults(func=cmd_models)

    p_c = sub.add_parser("config", help="配置管理")
    p_c.add_argument("action", choices=["get", "set"])
    p_c.add_argument("--backend", default="")
    p_c.add_argument("--api-key", default="")
    p_c.add_argument("--base-url", default="")
    p_c.add_argument("--openai-model", default="")
    p_c.add_argument("--whisper-model", default="")
    p_c.add_argument("--fmt", default="")
    p_c.set_defaults(func=cmd_config)

    p_tc = sub.add_parser("test-config", help="测试配置是否可用")
    p_tc.add_argument("--model", default="")
    p_tc.add_argument("--backend", default="openai")
    p_tc.add_argument("--api-key", default="")
    p_tc.set_defaults(func=cmd_test)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
