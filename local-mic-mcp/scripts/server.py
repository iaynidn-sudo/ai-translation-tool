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


if __name__ == "__main__":
    mcp.run()
