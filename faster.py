#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
会议助手 - 录音 + 转写 + AI 生成需求调研纪要（面向客户需求调研/需求分析场景）
用法:
    python faster.py [--whisper MODEL] [--backend {nvidia,ollama}] [--no-record]
"""

import os
import sys
import argparse
import threading
from datetime import datetime, timedelta

# 国内网络直连 huggingface.co 会 SSL 证书校验失败，必须在导入 faster_whisper 前设置镜像
if "HF_ENDPOINT" not in os.environ:
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import requests
import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write
from faster_whisper import WhisperModel


# ========================== 配置 ==========================
# 从环境变量读取 NVIDIA API Key（更安全，不硬编码）
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2:7b"  # 可改为你已下载的其他模型

# ========================== 录音功能 ==========================
def interactive_record(filename, samplerate=16000, channels=1):
    """
    交互式录音：按 Enter 开始，再按 Enter 停止，实时显示音量
    """
    print("⏳ 按 Ent【】er 键开始录音...")
    input()

    print("🔴 录音中... 再次按 Enter 键停止（音量指示器实时显示）")
    audio_chunks = []
    stop_event = threading.Event()

    def callback(indata, frames, time, status):
        if status:
            print(f"⚠️ 状态警告: {status}", flush=True)
        # 计算音量（RMS）并显示进度条
        rms = np.sqrt(np.mean(indata**2))
        bar_length = int(min(rms * 100, 50))  # 最大50格
        bar = '█' * bar_length + '░' * (50 - bar_length)
        print(f"\r音量: [{bar}]", end='', flush=True)
        audio_chunks.append(indata.copy())

    # 创建输入流（16kHz 单声道，适合语音识别）
    stream = sd.InputStream(
        samplerate=samplerate,
        channels=channels,
        callback=callback,
        dtype='float32'
    )

    with stream:
        input()  # 等待第二次回车

    print("\n⏹️ 录音停止。正在保存...")
    if audio_chunks:
        recording = np.concatenate(audio_chunks, axis=0)
        recording_int16 = (recording * 32767).astype(np.int16)
        write(filename, samplerate, recording_int16)
        print(f"✅ 录音已保存至: {filename}")
        return True
    else:
        print("❌ 未录到任何音频数据")
        return False

# ========================== 语音转写 ==========================
def transcribe_audio(filename, whisper_model_size="small"):
    """
    使用 faster-whisper 转写音频，返回文本
    """
    print(f"🧠 正在加载 Whisper 模型 ({whisper_model_size})...")
    try:
        # compute_type="int8" 加速，若 CPU 不支持可改为 "float32"
        model = WhisperModel(whisper_model_size, device="auto", compute_type="int8")
    except Exception:
        print("⚠️ int8 量化失败，尝试使用 float32")
        model = WhisperModel(whisper_model_size, device="auto", compute_type="float32")

    print("🎤 正在进行语音转写（可能需要几秒到几分钟）...")
    try:
        segments, _ = model.transcribe(filename, language="zh")
        text = "".join([seg.text for seg in segments])
        print("\n--- 转写结果 ---")
        print(text)
        print("----------------\n")
        return text.strip()
    except Exception as e:
        print(f"❌ 转写失败: {e}")
        return None

# ========================== AI 生成纪要 ==========================
# 需求调研/需求分析场景的提示词（输出 Markdown 格式）
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

def generate_minutes_with_nvidia(text, start_time=None, end_time=None):
    """调用 NVIDIA API 生成需求调研纪要，长录音分段摘要"""
    if not NVIDIA_API_KEY:
        raise ValueError("未设置 NVIDIA_API_KEY 环境变量")
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json"
    }
    time_info = f"会议时间：{_format_time(start_time)} - {_format_time(end_time)}"

    def call(messages, max_tokens):
        payload = {
            "model": NVIDIA_MODEL,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": max_tokens
        }
        try:
            resp = requests.post(NVIDIA_API_URL, headers=headers, json=payload, timeout=180)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"❌ NVIDIA API 调用失败: {e}")
            if hasattr(e, 'response') and e.response:
                print("响应详情:", e.response.text)
            return None

    # 长录音（最长约 5 小时）按 4000 字符分段先摘要，再合并生成纪要
    if len(text) > 4000:
        print("⏳ 录音文本较长，正在分段摘要（最长支持约 5 小时录音）...")
        chunk_size = 4000
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
        summaries = []
        for idx, chunk in enumerate(chunks, 1):
            messages = [
                {"role": "system", "content": "你是需求分析助手，请提取下面这段录音文本中的客户需求要点（诉求、痛点、需求点），简洁输出，不要遗漏。"},
                {"role": "user", "content": f"第 {idx}/{len(chunks)} 段录音：\n{chunk}"}
            ]
            s = call(messages, 800)
            if s:
                summaries.append(f"【第{idx}段】\n{s}")
        combined = "\n\n".join(summaries) if summaries else text
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
    time_info = f"会议时间：{_format_time(start_time)} - {_format_time(end_time)}"

    def call(prompt):
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "temperature": 0.3
        }
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=300)
            resp.raise_for_status()
            return resp.json()["response"]
        except Exception as e:
            print(f"❌ Ollama 调用失败: {e}")
            return None

    if len(text) > 4000:
        print("⏳ 录音文本较长，正在分段摘要（最长支持约 5 小时录音）...")
        chunk_size = 4000
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
        summaries = []
        for idx, chunk in enumerate(chunks, 1):
            s = call(f"你是需求分析助手，请提取下面这段录音文本中的客户需求要点（诉求、痛点、需求点），简洁输出，不要遗漏。\n第 {idx}/{len(chunks)} 段录音：\n{chunk}")
            if s:
                summaries.append(f"【第{idx}段】\n{s}")
        combined = "\n\n".join(summaries) if summaries else text
        return call(f"{time_info}\n\n{REQ_SYSTEM_PROMPT}\n\n以下是分段摘要的汇总（来自同一场客户调研）：\n{combined}")

    return call(f"{time_info}\n\n{REQ_SYSTEM_PROMPT}\n\n客户调研录音文字：\n{text}")

# ========================== 主流程 ==========================
def main():
    parser = argparse.ArgumentParser(description="会议助手 - 录音转写并生成纪要")
    parser.add_argument("--whisper", default="small", choices=["tiny","base","small","medium","large-v3"],
                        help="Whisper 模型大小 (默认: small)")
    parser.add_argument("--backend", default="nvidia", choices=["nvidia", "ollama"],
                        help="AI 后端: nvidia (云端) 或 ollama (本地)")
    parser.add_argument("--no-record", action="store_true",
                        help="跳过录音，直接使用已存在的 audio.wav 文件")
    parser.add_argument("--file", default="recording.wav",
                        help="音频文件路径 (仅在 --no-record 时使用)")
    args = parser.parse_args()

    # 1. 录音（除非指定 --no-record）
    if not args.no_record:
        # 自动生成带时间戳的文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_file = f"recording_{timestamp}.wav"
        print(f"🎙️ 准备录音，文件将保存为: {audio_file}")
        start_time = datetime.now()
        if not interactive_record(audio_file):
            print("录音失败，程序退出")
            sys.exit(1)
        end_time = datetime.now()
    else:
        audio_file = args.file
        if not os.path.exists(audio_file):
            print(f"❌ 指定的音频文件不存在: {audio_file}")
            sys.exit(1)
        print(f"📂 使用已有音频文件: {audio_file}")
        # 没有录制时间信息时，以文件修改时间为会议开始时间
        start_time = datetime.fromtimestamp(os.path.getmtime(audio_file))
        end_time = start_time

    # 2. 转写
    transcribed_text = transcribe_audio(audio_file, args.whisper)
    if not transcribed_text:
        print("转写失败，程序退出")
        sys.exit(1)

    # 3. 生成纪要
    print(f"🤖 正在使用后端 ({args.backend}) 生成需求调研纪要...")
    if args.backend == "nvidia":
        minutes = generate_minutes_with_nvidia(transcribed_text, start_time, end_time)
    else:  # ollama
        minutes = generate_minutes_with_ollama(transcribed_text, start_time, end_time)

    if minutes:
        print("\n" + "="*60)
        print("📋 需求调研纪要")
        print("="*60)
        print(minutes)
        print("="*60)
        # 可选：将纪要保存为 Markdown 文件
        output_file = f"minutes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(minutes)
        print(f"✅ 会议纪要已保存至: {output_file}")
    else:
        print("生成会议纪要失败")

if __name__ == "__main__":
    main()