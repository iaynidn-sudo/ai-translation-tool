#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
客户需求调研纪要工具 - 启动器 (GUI)
一键启动 / 停止 Web 服务 与 MCP 服务，显示运行日志，并支持配置自检。

用法:
    python launcher.py
"""

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable or "python"


def _pick_python():
    for p in (sys.executable, "python"):
        if p:
            try:
                subprocess.run([p, "--version"], capture_output=True, timeout=5)
                return p
            except Exception:
                continue
    return "python"


class LauncherApp:
    def __init__(self, root):
        self.root = root
        self.procs = {}  # name -> Popen
        self.python = _pick_python()
        root.title("客户需求调研纪要工具 - 启动器")
        root.geometry("760x520")
        root.minsize(640, 440)

        top = ttk.Frame(root, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text=f"Python: {self.python}").pack(anchor="w")
        ttk.Label(top, text=f"目录: {BASE_DIR}").pack(anchor="w")

        # 控制区
        ctrl = ttk.LabelFrame(root, text="服务控制", padding=10)
        ctrl.pack(fill="x", padx=12)

        row1 = ttk.Frame(ctrl)
        row1.pack(fill="x", pady=4)
        ttk.Button(row1, text="▶ 启动 Web 服务", command=lambda: self.start("web")).pack(side="left", padx=4)
        ttk.Button(row1, text="■ 停止 Web", command=lambda: self.stop("web")).pack(side="left", padx=4)
        ttk.Label(row1, text="端口:").pack(side="left", padx=(16, 4))
        self.port_var = tk.StringVar(value="5000")
        ttk.Entry(row1, textvariable=self.port_var, width=8).pack(side="left")
        self.web_status = ttk.Label(ctrl, text="● 未启动", foreground="gray")
        self.web_status.pack(anchor="e")

        row2 = ttk.Frame(ctrl)
        row2.pack(fill="x", pady=4)
        ttk.Button(row2, text="▶ 启动 MCP (stdio)", command=lambda: self.start("mcp")).pack(side="left", padx=4)
        ttk.Button(row2, text="▶ 启动 MCP (HTTP)", command=lambda: self.start("mcp_http")).pack(side="left", padx=4)
        ttk.Button(row2, text="■ 停止 MCP", command=lambda: self.stop("mcp")).pack(side="left", padx=4)
        self.mcp_status = ttk.Label(ctrl, text="● 未启动", foreground="gray")
        self.mcp_status.pack(anchor="e")

        row3 = ttk.Frame(ctrl)
        row3.pack(fill="x", pady=4)
        ttk.Button(row3, text="🔍 配置自检", command=self.self_check).pack(side="left", padx=4)
        ttk.Button(row3, text="🧹 清空日志", command=self.clear_log).pack(side="left", padx=4)

        # 日志区
        log_frame = ttk.LabelFrame(root, text="运行日志", padding=6)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(6, 12))
        self.log_text = tk.Text(log_frame, height=16, wrap="none", state="disabled",
                                font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4")
        sb = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.log_text.tag_configure("err", foreground="#f48771")
        self.log_text.tag_configure("ok", foreground="#6ccb5f")
        self.log_text.tag_configure("info", foreground="#9cdcfe")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._reader_threads = []
        self.log("启动器就绪，Python: " + self.python, "ok")
        self.log("可点击上方按钮启动 Web 或 MCP 服务，停止/日志实时显示。", "info")

    # ---------- 日志 ----------
    def log(self, msg, tag="info"):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.root.update_idletasks()

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _read_pipe(self, name, pipe, tag):
        for line in iter(pipe.readline, ""):
            line = line.rstrip("\r\n")
            if line:
                self.root.after(0, self.log, f"[{name}] {line}", tag)
        pipe.close()

    def _mark(self, name, status, color):
        lbl = self.web_status if name == "web" else self.mcp_status
        lbl.configure(text=f"● {status}", foreground=color)

    # ---------- 启动 / 停止 ----------
    def _spawn(self, name, args, tag="info"):
        self.log(f"启动 {name}: {' '.join(args)}", "info")
        try:
            p = subprocess.Popen(
                args, cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception as e:
            self.log(f"启动 {name} 失败: {e}", "err")
            return None
        self.procs[name] = p
        threading.Thread(target=self._read_pipe, args=(name, p.stdout, "info"), daemon=True).start()
        threading.Thread(target=self._read_pipe, args=(name, p.stderr, "err"), daemon=True).start()
        self._mark(name, "运行中", "#2ea043")
        threading.Thread(target=self._watch, args=(name, p), daemon=True).start()
        return p

    def _watch(self, name, p):
        code = p.wait()
        self.root.after(0, self.log, f"{name} 已退出，退出码 {code}", "err")
        self.root.after(0, self._mark, name, "已退出", "#f48771")
        self.root.after(0, self.procs.pop, name)

    def start(self, which):
        if which in self.procs:
            messagebox.showinfo("提示", f"{which} 已在运行")
            return
        if which == "web":
            port = self.port_var.get().strip() or "5000"
            p = self._spawn("web", [self.python, "app.py", "--port", port])
            if p:
                threading.Thread(
                    target=self._wait_http, args=("web", f"http://127.0.0.1:{port}"),
                    daemon=True,
                ).start()
        elif which == "mcp":
            self._spawn("mcp", [self.python, "mcp_server.py"])
        elif which == "mcp_http":
            self._spawn("mcp_http", [self.python, "mcp_server.py", "--http", "127.0.0.1:8000"])

    def stop(self, which):
        names = [which] if which != "mcp" else [n for n in self.procs if n.startswith("mcp")]
        for n in names:
            p = self.procs.get(n)
            if p and p.poll() is None:
                p.terminate()
                self.log(f"已请求停止 {n}", "info")
            else:
                self.log(f"{n} 未在运行", "info")

    def _wait_http(self, name, url):
        import urllib.request
        import time
        for _ in range(20):
            try:
                urllib.request.urlopen(url, timeout=1)
                self.root.after(0, self.log, f"✅ {name} 服务已就绪: {url}", "ok")
                return
            except Exception:
                time.sleep(0.5)
        self.root.after(0, self.log, f"{name} 启动后 10s 内未响应，请查看上方日志", "err")

    # ---------- 配置自检 ----------
    def self_check(self):
        self.log("开始配置自检...", "info")
        threading.Thread(target=self._run_check, daemon=True).start()

    def _run_check(self):
        import json as jsonlib
        try:
            r = subprocess.run(
                [self.python, "cli.py", "test-config"], cwd=BASE_DIR,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            )
            out = r.stdout.strip()
            try:
                data = jsonlib.loads(out)
            except Exception:
                data = None
            if r.returncode != 0 or data is None:
                self.root.after(0, self.log, f"自检失败: {r.stderr.strip() or out}", "err")
                return
            for key, label in (("model", "转写模型"), ("backend", "AI 后端"), ("backend_test", "后端连通性")):
                item = data.get(key)
                if isinstance(item, dict):
                    tag = "ok" if item.get("ok") else "err"
                    self.root.after(0, self.log, f"  [{label}] {item.get('message')}", tag)
            if data.get("ok"):
                self.root.after(0, self.log, "✅ 配置自检全部通过", "ok")
            else:
                self.root.after(0, self.log, "❌ 配置自检未通过，请按提示修正后重试", "err")
        except Exception as e:
            self.root.after(0, self.log, f"自检异常: {e}", "err")

    # ---------- 关闭 ----------
    def on_close(self):
        for p in list(self.procs.values()):
            if p.poll() is None:
                p.terminate()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
