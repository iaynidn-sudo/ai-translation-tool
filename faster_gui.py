#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
客户需求调研纪要工具 - GUI 版
用法:
    python faster_gui.py
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
import requests
import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write

# 国内网络直连 huggingface.co 会 SSL 证书校验失败，必须在导入 faster_whisper 前设置镜像
if "HF_ENDPOINT" not in os.environ:
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from faster_whisper import WhisperModel

# ========================== 配置 ==========================
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2:7b"

WHISPER_SIZES = ["tiny", "base", "small", "medium", "large-v3"]

# ========================== 录音功能 ==========================
def _pick_mic():
    """返回默认输入设备索引，找不到则返回 None"""
    try:
        return sd.default.device[0]
    except Exception:
        return None

class Recorder:
    """后台线程录音控制器"""
    def __init__(self, samplerate=16000, channels=1):
        self.samplerate = samplerate
        self.channels = channels
        self.stream = None
        self.chunks = []
        self._lock = threading.Lock()

    def start(self):
        self.chunks = []
        def callback(indata, frames, time, status):
            with self._lock:
                self.chunks.append(indata.copy())
        self.stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            callback=callback,
            dtype='float32'
        )
        self.stream.start()
        return True

    def stop(self, filename):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        with self._lock:
            chunks = self.chunks
        if not chunks:
            return False
        recording = np.concatenate(chunks, axis=0)
        recording_int16 = (recording * 32767).astype(np.int16)
        write(filename, self.samplerate, recording_int16)
        return True

# ========================== 语音转写 ==========================
def transcribe_audio(filename, whisper_model="small", on_log=None):
    """使用 faster-whisper 转写音频，返回文本"""
    log = on_log or (lambda m: None)
    log(f"正在加载 Whisper 模型 ({whisper_model})...")
    try:
        # compute_type="int8" 加速，若 CPU 不支持可改为 "float32"
        model = WhisperModel(whisper_model, device="auto", compute_type="int8")
    except Exception:
        log("int8 量化失败，尝试使用 float32")
        model = WhisperModel(whisper_model, device="auto", compute_type="float32")

    log("正在进行语音转写（可能需要几秒到几分钟）...")
    try:
        segments, _ = model.transcribe(filename, language="zh")
        text = "".join([seg.text for seg in segments])
        return text.strip()
    except Exception as e:
        log(f"转写失败: {e}")
        return None

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

def generate_minutes_with_nvidia(text, start_time=None, end_time=None, api_key=None, on_log=None):
    """调用 NVIDIA API 生成需求调研纪要，长录音分段摘要"""
    log = on_log or (lambda m: None)
    if not api_key:
        raise ValueError("未设置 NVIDIA_API_KEY")
    headers = {
        "Authorization": f"Bearer {api_key}",
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
            log(f"NVIDIA API 调用失败: {e}")
            if hasattr(e, 'response') and e.response:
                log("响应详情: " + e.response.text)
            return None

    if len(text) > 4000:
        log("录音文本较长，正在分段摘要（最长支持约 5 小时录音）...")
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

def generate_minutes_with_ollama(text, start_time=None, end_time=None, on_log=None):
    """调用本地 Ollama 生成需求调研纪要，长录音分段摘要"""
    log = on_log or (lambda m: None)
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
            log(f"Ollama 调用失败: {e}")
            return None

    if len(text) > 4000:
        log("录音文本较长，正在分段摘要（最长支持约 5 小时录音）...")
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

# ========================== GUI ==========================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("客户需求调研纪要工具")
        self.geometry("780x700")
        self.minsize(640, 560)

        self.recorder = Recorder()
        self.is_recording = False
        self.audio_file = None
        self.start_time = None
        self.end_time = None
        self.work_thread = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}
        # ---------- 录音控制区 ----------
        rec_frame = ttk.LabelFrame(self, text=" 录音控制 ")
        rec_frame.pack(fill="x", **pad)
        btn_row = ttk.Frame(rec_frame)
        btn_row.pack(fill="x", padx=8, pady=6)
        self.btn_record = ttk.Button(btn_row, text="● 开始录音", width=16, command=self.toggle_record)
        self.btn_record.pack(side="left")
        self.lbl_status = ttk.Label(btn_row, text="就绪")
        self.lbl_status.pack(side="left", padx=12)

        # ---------- 配置区 ----------
        cfg = ttk.LabelFrame(self, text=" 配置 ")
        cfg.pack(fill="x", **pad)

        row1 = ttk.Frame(cfg)
        row1.pack(fill="x", padx=8, pady=3)
        ttk.Label(row1, text="保存位置:").pack(side="left")
        self.var_save_dir = tk.StringVar(value=os.getcwd())
        ttk.Entry(row1, textvariable=self.var_save_dir).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row1, text="浏览...", command=self.browse_save_dir).pack(side="left")

        row2 = ttk.Frame(cfg)
        row2.pack(fill="x", padx=8, pady=3)
        ttk.Label(row2, text="AI 后端:").pack(side="left")
        self.var_backend = tk.StringVar(value="nvidia")
        backend_cb = ttk.Combobox(row2, textvariable=self.var_backend, values=["nvidia", "ollama"],
                                  state="readonly", width=10)
        backend_cb.pack(side="left", padx=(4, 16))
        ttk.Label(row2, text="Whisper 模型:").pack(side="left")
        self.var_model = tk.StringVar(value="small")
        model_cb = ttk.Combobox(row2, textvariable=self.var_model, values=WHISPER_SIZES,
                                state="readonly", width=12)
        model_cb.pack(side="left", padx=4)

        row3 = ttk.Frame(cfg)
        row3.pack(fill="x", padx=8, pady=3)
        ttk.Label(row3, text="模型地址(可选):").pack(side="left")
        self.var_model_path = tk.StringVar(value="")
        ttk.Entry(row3, textvariable=self.var_model_path).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row3, text="浏览...", command=self.browse_model_path).pack(side="left")

        row4 = ttk.Frame(cfg)
        row4.pack(fill="x", padx=8, pady=3)
        ttk.Label(row4, text="NVIDIA API Key:").pack(side="left")
        self.var_api_key = tk.StringVar(value=os.environ.get("NVIDIA_API_KEY", ""))
        ttk.Entry(row4, textvariable=self.var_api_key).pack(side="left", fill="x", expand=True, padx=4)

        # ---------- 输出区 ----------
        out = ttk.LabelFrame(self, text=" 输出 ")
        out.pack(fill="both", expand=True, **pad)

        ttk.Label(out, text="转写结果:").pack(anchor="w", padx=8, pady=(6, 2))
        self.txt_transcript = tk.Text(out, height=7, wrap="word", state="disabled")
        self.txt_transcript.pack(fill="both", expand=True, padx=8)

        ttk.Label(out, text="需求调研纪要 (Markdown):").pack(anchor="w", padx=8, pady=(6, 2))
        self.txt_minutes = tk.Text(out, height=12, wrap="word", state="disabled")
        self.txt_minutes.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        btn_row2 = ttk.Frame(out)
        btn_row2.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(btn_row2, text="导出格式:").pack(side="left", padx=(0, 4))
        self.var_format = tk.StringVar(value="md")
        fmt_cb = ttk.Combobox(btn_row2, textvariable=self.var_format, values=["md", "html", "pdf", "docx"],
                              state="readonly", width=8)
        fmt_cb.pack(side="left")
        self.btn_save = ttk.Button(btn_row2, text="保存纪要", command=self.save_minutes)
        self.btn_save.pack(side="right")

    # ---------- 界面动作 ----------
    def log(self, msg):
        """往状态栏写日志（线程安全）"""
        def _do():
            self.lbl_status.config(text=str(msg))
        self.after(0, _do)

    def browse_save_dir(self):
        d = filedialog.askdirectory(title="选择保存目录", initialdir=self.var_save_dir.get() or os.getcwd())
        if d:
            self.var_save_dir.set(d)

    def browse_model_path(self):
        d = filedialog.askdirectory(title="选择本地 Whisper 模型目录",
                                    initialdir=self.var_model_path.get() or os.getcwd())
        if d:
            self.var_model_path.set(d)

    def toggle_record(self):
        if self.is_recording:
            self.stop_record()
        else:
            self.start_record()

    def start_record(self):
        if self.work_thread and self.work_thread.is_alive():
            messagebox.showwarning("提示", "正在处理上一条录音，请稍候")
            return
        save_dir = self.var_save_dir.get().strip()
        if not os.path.isdir(save_dir):
            messagebox.showerror("错误", "保存位置目录不存在，请先选择有效目录")
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.audio_file = os.path.join(save_dir, f"recording_{timestamp}.wav")
        try:
            self.recorder.start()
        except Exception as e:
            messagebox.showerror("错误", f"启动录音失败: {e}")
            return
        self.is_recording = True
        self.start_time = datetime.now()
        self.btn_record.config(text="■ 结束录音")
        self.log("录音中... 点击 [结束录音] 停止")
        self._tick()

    def _tick(self):
        if not self.is_recording:
            return
        elapsed = (datetime.now() - self.start_time).total_seconds()
        m, s = int(elapsed // 60), int(elapsed % 60)
        self.lbl_status.config(text=f"录音中 {m:02d}:{s:02d}  点击 [结束录音] 停止")
        self.after(1000, self._tick)

    def stop_record(self):
        if not self.is_recording:
            return
        self.is_recording = False
        self.end_time = datetime.now()
        self.log("正在保存录音...")
        ok = self.recorder.stop(self.audio_file)
        if not ok:
            self.btn_record.config(text="● 开始录音")
            self.log("未录到音频数据")
            messagebox.showwarning("提示", "未录到音频数据")
            return
        self.btn_record.config(text="● 开始录音")
        self.log("录音已保存，开始转写与生成纪要...")
        self.work_thread = threading.Thread(target=self._process, args=(self.audio_file,), daemon=True)
        self.work_thread.start()

    # ---------- 后台处理 ----------
    def _process(self, audio_file):
        try:
            model_arg = self.var_model_path.get().strip() or self.var_model.get()
            self._set_transcript("")
            self._set_minutes("")
            self.log("正在加载 Whisper 模型并转写...")
            text = transcribe_audio(audio_file, model_arg, on_log=self.log)
            if not text:
                self.log("转写失败")
                messagebox.showerror("错误", "转写失败，请检查模型或网络")
                return
            self._set_transcript(text)

            backend = self.var_backend.get()
            self.log(f"正在使用后端 ({backend}) 生成需求调研纪要...")
            if backend == "nvidia":
                api_key = self.var_api_key.get().strip()
                minutes = generate_minutes_with_nvidia(text, self.start_time, self.end_time,
                                                       api_key=api_key, on_log=self.log)
            else:
                minutes = generate_minutes_with_ollama(text, self.start_time, self.end_time, on_log=self.log)
            if minutes:
                self._set_minutes(minutes)
                self.log("生成完成")
            else:
                self.log("生成纪要失败")
        except Exception as e:
            self.log(f"处理出错: {e}")

    def _set_transcript(self, text):
        def _do():
            self.txt_transcript.config(state="normal")
            self.txt_transcript.delete("1.0", tk.END)
            self.txt_transcript.insert("1.0", text)
            self.txt_transcript.config(state="disabled")
        self.after(0, _do)

    def _set_minutes(self, text):
        def _do():
            self.txt_minutes.config(state="normal")
            self.txt_minutes.delete("1.0", tk.END)
            self.txt_minutes.insert("1.0", text)
            self.txt_minutes.config(state="disabled")
        self.after(0, _do)

    def save_minutes(self):
        content = self.txt_minutes.get("1.0", tk.END).strip()
        if not content:
            messagebox.showwarning("提示", "当前没有纪要内容")
            return
        save_dir = self.var_save_dir.get().strip() or os.getcwd()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fmt = self.var_format.get()
        base = os.path.join(save_dir, f"minutes_{timestamp}")
        try:
            from mdconvert import convert_markdown
            path = convert_markdown(content, fmt, base)
        except Exception as e:
            messagebox.showerror("保存失败", f"转换失败: {e}")
            return
        messagebox.showinfo("已保存", f"纪要已保存至:\n{path}")

    def on_close(self):
        if self.is_recording:
            try:
                self.recorder.stop(self.audio_file)
            except Exception:
                pass
        self.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()
