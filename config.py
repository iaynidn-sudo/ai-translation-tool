#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
本地配置文件管理：模型列表（内置 + 自定义）及相关设置的持久化。
配置文件为 .env 格式，保存在程序目录下（默认 .env）。

.env 示例:
    BACKEND=nvidia
    API_KEY=
    WHISPER_MODEL=small
    EXPORT_FMT=md
    MODEL_1_NAME=中文优化版
    MODEL_1_PATH=D:/models/whisper-small-zh
    MODEL_1_KEY=
    MODEL_1_DESC=本地中文优化模型
    MODEL_1_ENABLED=true
    MODEL_1_LOCKED=false
"""

import os
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, ".env")

# 内置 Whisper 模型大小（不可删除）
BUILTIN_MODELS = ["tiny", "base", "small", "medium", "large-v3"]

HEADER = "# 客户需求调研纪要工具配置（.env）\n# 内置模型 tiny/base/small/medium/large-v3 为系统内置，无需配置。\n# AI 后端 BACKEND 支持 openai / ollama；openai 需配置 API_KEY、OPENAI_BASE_URL、OPENAI_MODEL\n# 自定义模型以 MODEL_ 前缀定义：MODEL_1_NAME / MODEL_1_PATH / MODEL_1_KEY / MODEL_1_DESC / MODEL_1_ENABLED / MODEL_1_LOCKED\n"

DEFAULT_SETTINGS = {
    "BACKEND": "openai",
    "API_KEY": "",
    "OPENAI_BASE_URL": "https://integrate.api.nvidia.com/v1",
    "OPENAI_MODEL": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "WHISPER_MODEL": "small",
    "EXPORT_FMT": "md",
}

_lock = threading.Lock()
_config = None  # 解析后的缓存 {"settings": {...}, "custom_models": [...]}


def _parse_env():
    """解析 .env 文件为字典（K -> V），支持 # 注释与引号。"""
    result = {}
    if not os.path.exists(CONFIG_PATH):
        return result
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            result[k] = v
    return result


def _load():
    global _config
    if _config is not None:
        return _config
    env = _parse_env()

    settings = {}
    for k, default in DEFAULT_SETTINGS.items():
        settings[k] = env.get(k, default)

    custom_models = []
    idx = 1
    while True:
        name = env.get(f"MODEL_{idx}_NAME")
        if name is None:
            break
        custom_models.append({
            "name": name,
            "path": env.get(f"MODEL_{idx}_PATH", ""),
            "key": env.get(f"MODEL_{idx}_KEY", ""),
            "desc": env.get(f"MODEL_{idx}_DESC", ""),
            "enabled": env.get(f"MODEL_{idx}_ENABLED", "true").lower() not in ("0", "false", "no"),
            "locked": env.get(f"MODEL_{idx}_LOCKED", "false").lower() in ("1", "true", "yes"),
        })
        idx += 1

    _config = {"settings": settings, "custom_models": custom_models}
    return _config


def _save(settings, custom_models):
    """将配置写回 .env 文件，保留全部字段。"""
    lines = [HEADER]
    for k in DEFAULT_SETTINGS:
        v = settings.get(k, "")
        lines.append(f"{k}={v}")
    lines.append("")
    for i, m in enumerate(custom_models, 1):
        lines.append(f"MODEL_{i}_NAME={m.get('name', '')}")
        lines.append(f"MODEL_{i}_PATH={m.get('path', '')}")
        lines.append(f"MODEL_{i}_KEY={m.get('key', '')}")
        lines.append(f"MODEL_{i}_DESC={m.get('desc', '')}")
        lines.append(f"MODEL_{i}_ENABLED={'true' if m.get('enabled', True) else 'false'}")
        lines.append(f"MODEL_{i}_LOCKED={'true' if m.get('locked', False) else 'false'}")
        lines.append("")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def _mutate(settings_patch=None, model_op=None):
    """统一入口：读取配置，应用修改，写回文件。"""
    global _config
    cfg = _load()
    settings = dict(cfg["settings"])
    models = [dict(m) for m in cfg["custom_models"]]
    if settings_patch:
        for k, v in settings_patch.items():
            if v is not None:
                settings[k] = v
    if model_op:
        models = model_op(models)
    _save(settings, models)
    _config = {"settings": settings, "custom_models": models}
    return _config


def get_config():
    with _lock:
        return _load()


def update_settings(patch):
    """更新设置项（合并式）。返回最新设置。"""
    with _lock:
        cfg = _mutate(settings_patch=patch)
        return dict(cfg["settings"])


def _public_model(m, include_key=True):
    """转为 API 对外字段。锁定模型的 key 不回传，避免泄露。"""
    data = {
        "name": m.get("name", ""),
        "path": m.get("path", ""),
        "desc": m.get("desc", ""),
        "source": m.get("source", "custom"),
        "enabled": m.get("enabled", True),
        "locked": m.get("locked", False),
    }
    if include_key:
        data["key"] = m.get("key", "")
    return data


def list_models():
    """返回完整模型列表（内置 + 自定义）。"""
    with _lock:
        cfg = _load()
        builtin = [_public_model({"name": m, "path": "", "desc": "内置模型", "source": "builtin",
                                  "enabled": True, "locked": False, "key": ""})
                   for m in BUILTIN_MODELS]
        custom = [_public_model({**m, "source": "custom"}) for m in cfg["custom_models"]]
        return builtin + custom


def add_custom_model(name, path, key="", desc=""):
    """新增自定义模型。name 需唯一。"""
    with _lock:
        name = (name or "").strip()
        path = (path or "").strip()
        if not name or not path:
            raise ValueError("模型名称和地址不能为空")
        cfg = _load()
        for m in cfg["custom_models"]:
            if m.get("name") == name:
                raise ValueError(f"模型名称已存在: {name}")
        new = {"name": name, "path": path, "key": (key or "").strip(),
               "desc": (desc or "").strip(), "enabled": True, "locked": False}
        _mutate(model_op=lambda ms: ms + [new])
        return _public_model(dict(new))


def update_custom_model(name, path=None, key=None, desc=None, enabled=None, locked=None, force=False):
    """修改自定义模型。name 定位。锁定模型需 force=True 才能修改。"""
    with _lock:
        def op(ms):
            for m in ms:
                if m.get("name") == name:
                    if m.get("locked") and not force:
                        raise ValueError(f"模型「{name}」已锁定，请先解锁后再修改")
                    if path is not None:
                        p = (path or "").strip()
                        if not p:
                            raise ValueError("模型地址不能为空")
                        m["path"] = p
                    if key is not None:
                        m["key"] = (key or "").strip()
                    if desc is not None:
                        m["desc"] = (desc or "").strip()
                    if enabled is not None:
                        m["enabled"] = bool(enabled)
                    if locked is not None:
                        m["locked"] = bool(locked)
                    return ms
            raise ValueError(f"未找到模型: {name}")
        cfg = _mutate(model_op=op)
        for m in cfg["custom_models"]:
            if m.get("name") == name:
                return _public_model({**m, "source": "custom"})
        raise ValueError(f"未找到模型: {name}")


def delete_custom_model(name, force=False):
    """删除自定义模型。锁定模型需 force=True 才能删除。"""
    with _lock:
        removed = [None]

        def op(ms):
            for i, m in enumerate(ms):
                if m.get("name") == name:
                    if m.get("locked") and not force:
                        raise ValueError(f"模型「{name}」已锁定，请先解锁后再删除")
                    removed[0] = dict(m)
                    return ms[:i] + ms[i + 1:]
            raise ValueError(f"未找到模型: {name}")

        _mutate(model_op=op)
        if removed[0] is None:
            raise ValueError(f"未找到模型: {name}")
        return _public_model({**removed[0], "source": "custom"})


def resolve_model(name_or_path):
    """按名称或路径查找模型完整信息（含 key），找不到返回 None。"""
    name_or_path = (name_or_path or "").strip()
    if not name_or_path:
        return None
    with _lock:
        cfg = _load()
        for m in cfg["custom_models"]:
            if m.get("name") == name_or_path or m.get("path") == name_or_path:
                if m.get("enabled"):
                    return dict(m)
    return None


def resolve_model_path(name_or_path):
    """
    将模型选择值解析为 faster-whisper 可用的模型标识：
    - 自定义模型名称 -> 其路径
    - 直接是本地路径 -> 原样返回
    - 内置模型名 -> 原样返回
    """
    name_or_path = (name_or_path or "").strip()
    if not name_or_path:
        return "small"
    with _lock:
        cfg = _load()
        for m in cfg["custom_models"]:
            if m.get("name") == name_or_path and m.get("enabled"):
                return m["path"] or name_or_path
    return name_or_path
