# local-mic-mcp — 本地麦克风 MCP 连接器（OS 级录音 + faster-whisper 转写）
# 通过 WorkBuddy mcp.json 以 stdio 方式加载。需 venv 已装 fastmcp + sounddevice + faster-whisper + numpy。
import os, wave, time, uuid, threading, sys

# Fix SSL cert for huggingface hub (httpx itself)
os.environ['SSL_CERT_FILE'] = r'C:\Users\jiang\AppData\Local\.certifi\cacert.pem'
os.environ['REQUESTS_CA_BUNDLE'] = r'C:\Users\jiang\AppData\Local\.certifi\cacert.pem'
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
os.environ['HF_HUB_DISABLE_SSL_VERIFY'] = '1'

# Force httpx to use unverified SSL
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import numpy as np
import sounddevice as sd
from typing import Optional
from faster_whisper import WhisperModel
from mcp.server.fastmcp import FastMCP

BASE = os.path.dirname(os.path.abspath(__file__))
REC_DIR = os.path.join(BASE, "recordings")
os.makedirs(REC_DIR, exist_ok=True)

mcp = FastMCP("mic-recorder")

_state = {
    "active": False,
    "stream": None,
    "frames": [],
    "session": None,
    "path": None,
    "last_path": None,   # 最近一次保存的 WAV，供 mic_transcribe 默认使用
    "lock": threading.Lock(),
}
_model = None
_model_lock = threading.Lock()
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        return _model


def transcribe_file(path):
    model = get_model()
    segs, _ = model.transcribe(path, language="zh")
    return "".join(s.text for s in segs).strip()


def _callback(indata, frames, time_info, status):
    with _state["lock"]:
        if _state["active"]:
            _state["frames"].append(indata.copy())


@mcp.tool()
def mic_start(session: str = "") -> str:
    """开始 OS 级录音（首次需 Windows 麦克风授权）。说完后调用 mic_stop 停录保存 WAV，再用 mic_transcribe 转写。"""
    with _state["lock"]:
        if _state["active"]:
            return "已经在录音中，先调用 mic_stop 停止。"
        sess = session or ("m_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:5])
        _state["frames"] = []
        _state["session"] = sess
        _state["path"] = os.path.join(REC_DIR, f"{sess}.wav")
        try:
            stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16", callback=_callback)
            stream.start()
            _state["stream"] = stream
            _state["active"] = True
        except Exception as e:
            return f"无法开启麦克风: {e}"
        return f"录音已开始（session={sess}）。说完后调用 mic_stop 停录并取回转写。"


@mcp.tool()
def mic_stop() -> str:
    """停止录音并保存 WAV 文件（不转写，避免长录音超时）。返回文件路径和时长；转写请单独调 mic_transcribe。"""
    with _state["lock"]:
        if not _state["active"]:
            return "当前没有进行中的录音。"
        stream = _state["stream"]
        frames = _state["frames"]
        path = _state["path"]
        _state["active"] = False
        _state["stream"] = None
        _state["frames"] = []
    try:
        if stream is not None:
            stream.stop()
            stream.close()
    except Exception:
        pass
    if not frames:
        return "未捕获到任何音频。"
    audio = np.concatenate(frames, axis=0).ravel()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(audio.tobytes())
    duration_sec = len(audio) / 16000
    size_mb = os.path.getsize(path) / 1024 / 1024
    _state["last_path"] = path
    return (
        f"录音已保存: {path}\n"
        f"时长: {duration_sec:.0f}s ({duration_sec/60:.1f}min) | 大小: {size_mb:.1f}MB\n"
        f"调用 mic_transcribe 转写此文件。"
    )


@mcp.tool()
def mic_status() -> str:
    """查询当前是否在录音。"""
    with _state["lock"]:
        active = _state["active"]
        sess = _state["session"]
    return f"录音中={active}，session={sess or '-'}"


@mcp.tool()
def mic_transcribe(file: str = "") -> str:
    """转写指定音频文件。不传 file 则转写最近一次 mic_stop 保存的文件。"""
    path = file or _state.get("last_path", "")
    if not path:
        return "未指定文件，且没有最近保存的录音。请先录音并 mic_stop，或传入 file 参数。"
    if not os.path.exists(path):
        return f"文件不存在: {path}"
    try:
        text = transcribe_file(path)
    except Exception as e:
        return f"转写失败: {e}"
    return f"【转写】\n{text}"


# ---------------------------------------------------------------------------
# 生成方式：录音转写后，按不同模式加工（默认"业务需求调研"）
# 设计：优先由 WorkBuddy 自身模型生成（返回转写 + 模式提示词）；
#       若配置了 LLM 环境变量（MIC_LLM_* 或复用 APP_OPENAI_*），技能内直接调用 LLM 兜底生成
#       —— 即"WorkBuddy 不可用/未接入时，默认用 LLM 模型"。
# ---------------------------------------------------------------------------

GENERATION_MODES = {
    "business_requirement": {
        "label": "业务需求调研",
        "prompt": (
            "你是一名资深业务分析师。基于以下录音转写，按【业务需求调研】框架结构化整理：\n"
            "1. 背景与目标\n2. 现状与痛点\n3. 核心需求（功能/非功能）\n"
            "4. 干系人与职责\n5. 约束与假设\n6. 待确认问题\n"
            "用简洁要点，不要编造转写中不存在的信息。"
        ),
    },
    "customer_requirement": {
        "label": "客户需求",
        "prompt": (
            "你是一名客户需求分析师。基于以下录音转写，站在客户视角提取：\n"
            "1. 客户明确提出的需求\n2. 隐含/潜在需求\n3. 顾虑与期望\n4. 优先级判断\n"
            "用简洁要点，并区分「已明确」与「需确认」。"
        ),
    },
    "meeting_minutes": {
        "label": "会议纪要",
        "prompt": (
            "你是会议纪要助手。基于以下录音转写，整理成标准会议纪要：\n"
            "- 会议主题\n- 参与人（如可识别）\n- 关键讨论\n- 决议事项\n- 下一步行动\n"
            "按议题/时间线组织，简洁。"
        ),
    },
    "action_items": {
        "label": "待办清单",
        "prompt": (
            "你是项目管理助手。从以下录音转写中提取 Action Items，每项一行，格式：\n"
            "[事项] | 负责人 | 截止时间 | 优先级\n"
            "无法确定的字段填 '-'。只列明确的待办，不要编造。"
        ),
    },
    "summary": {
        "label": "一句话摘要",
        "prompt": (
            "你是摘要助手。基于以下录音转写，用 3-5 条要点概括核心内容，每条不超过 40 字。"
        ),
    },
    "transcript": {
        "label": "纯转写",
        "prompt": None,  # 原样返回
    },
}

DEFAULT_MODE = "business_requirement"


def _llm_generate(text: str, system_prompt: str) -> Optional[str]:
    """尝试用 OpenAI 兼容接口生成。未配置或不可用则返回 None（交由 WorkBuddy 生成）。
    使用 httpx（mcp 已带）直接打 /chat/completions，无需额外安装 openai 包。"""
    import json
    base = os.environ.get("MIC_LLM_BASE_URL") or os.environ.get("APP_OPENAI_BASE_URL")
    key = os.environ.get("MIC_LLM_API_KEY") or os.environ.get("APP_OPENAI_API_KEY")
    model = os.environ.get("MIC_LLM_MODEL") or os.environ.get("APP_OPENAI_MODEL") or "gpt-4o-mini"
    if not (base and key):
        return None
    url = base.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        "temperature": 0.3,
    }
    try:
        try:
            import httpx
            resp = httpx.post(url, headers=headers, json=payload, timeout=120, verify=False)
            resp.raise_for_status()
            data = resp.json()
        except ImportError:
            import urllib.request
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310
                data = json.loads(r.read().decode("utf-8"))
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        return f"[LLM 生成失败，已回退为转写+提示词] {e}"


@mcp.tool()
def mic_generate(mode: str = DEFAULT_MODE, file: str = "") -> str:
    """录音转写后，按指定「生成方式」加工文本。默认 mode=business_requirement（业务需求调研）。
    可用 mode：business_requirement(业务需求调研) / customer_requirement(客户需求) / meeting_minutes(会议纪要) / action_items(待办清单) / summary(一句话摘要) / transcript(纯转写)。
    行为：若配置了 MIC_LLM_*（或复用 APP_OPENAI_*）环境变量，技能内直接调用 LLM 生成结果；否则返回转写文本 + 模式提示词，交由 WorkBuddy 自身模型生成。"""
    if mode not in GENERATION_MODES:
        return f"未知 mode='{mode}'。可选：{', '.join(GENERATION_MODES.keys())}"
    path = file or _state.get("last_path", "")
    if not path:
        return "未指定文件，且没有最近保存的录音。请先录音并 mic_stop，或传入 file 参数。"
    if not os.path.exists(path):
        return f"文件不存在: {path}"
    try:
        text = transcribe_file(path)
    except Exception as e:
        return f"转写失败: {e}"
    if mode == "transcript" or not GENERATION_MODES[mode]["prompt"]:
        return f"【纯转写】\n{text}"
    sys_prompt = GENERATION_MODES[mode]["prompt"]
    label = GENERATION_MODES[mode]["label"]
    generated = _llm_generate(text, sys_prompt)
    if generated:
        return f"【{label}】\n{generated}\n\n--- 原始转写 ---\n{text}"
    # 兜底：交给 WorkBuddy 自身模型生成
    return (
        f"【转写】\n{text}\n\n"
        f"--- 请按以下模式生成（WorkBuddy 自身模型）---\n"
        f"MODE: {mode} ({label})\n"
        f"SYSTEM_PROMPT:\n{sys_prompt}"
    )


if __name__ == "__main__":
    mcp.run()
