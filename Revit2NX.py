# -*- coding: utf-8 -*-
"""
Revit → NX 集成导入工具（图形界面）

设计要点
--------
* 本界面运行在 **NX 之外**（系统 Python + tkinter，无第三方依赖）。
  导入本身由 NX 的 run_journal 在独立的批处理会话里执行，因为
  NXOpen.pyd 只能在 NX 进程内加载。
* 每次导入自动新建【独立空目录】。实测 NX 遇到同名部件会改名另存，
  而改名那一批可能整批创建失败（173 个部件里 168 个几何没导进去）。
* 导入结束后自动【等待落盘】再核对。实测 NX 比脚本返回晚约 26 秒才写盘，
  因此不能导入一结束就检查，否则必然误判为「没有产物」。
* 所有失败都给出「往哪修」的具体路径与操作。

启动方式
--------
    双击 start_gui.bat
或  python Revit2NX.py
"""
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import nxcheck
import nxpreflight as pf

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "revit2nx_config.json")
IMPORT_SCRIPT = os.path.join(BASE, "src", "import_revit.py")
SCRIPT_LOG = os.path.join(BASE, "src", "nx_revit_import.log")

GEOMETRY_VALUES = ("Precise", "Lightweight")
UNIT_VALUES = ("Millimeter", "Meter", "Inch", "Micrometer", "NotSet")
CSYS_VALUES = ("SurveyPoint", "ProjectBasePoint", "Internal", "ActiveProjectLOC")


def _decode(raw):
    """NX 的 stdout 是本地代码页编码（中文 Windows 为 GBK），逐级尝试解码。"""
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "replace")
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def _default_model_dir():
    """给模型库挑一个合理的默认目录（不假设任何个人路径）。"""
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "Documents"),
                 os.path.join(home, "Desktop"),
                 home):
        if os.path.isdir(cand):
            return cand
    return home


def _default_output_root():
    """默认输出根目录：用户主目录下的 NXRevitImport。"""
    return os.path.join(os.path.expanduser("~"), "NXRevitImport")


class App(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)
        self.title("Revit → NX 集成导入工具")
        self.geometry("1020x780")
        self.minsize(920, 680)

        self.queue = queue.Queue()
        self.worker = None
        self.busy = False
        self.nx_root = None
        self.models = []

        self.var_model_dir = tk.StringVar()
        self.var_out_root = tk.StringVar()
        self.var_nx_root = tk.StringVar()
        self.var_geometry = tk.StringVar(value="Precise")
        self.var_unit = tk.StringVar(value="Millimeter")
        self.var_csys = tk.StringVar(value="SurveyPoint")
        self.var_attrs = tk.BooleanVar(value=True)
        self.var_hier = tk.BooleanVar(value=True)
        self.var_linked = tk.BooleanVar(value=True)
        self.var_recursive = tk.BooleanVar(value=True)
        self.var_status = tk.StringVar(value="就绪")

        self._build_ui()
        self._load_config()
        self.after(120, self._drain_queue)
        self.after(300, self.refresh_models)
        self.after(600, self.run_preflight)

    # ==================================================================
    # 界面
    # ==================================================================
    def _build_ui(self):
        pad = dict(padx=8, pady=4)

        # ---- 第 1 块：路径 ----
        box1 = ttk.LabelFrame(self, text="1. 目录设置")
        box1.pack(fill="x", **pad)
        self._path_row(box1, 0, "模型库目录", self.var_model_dir,
                       self.pick_model_dir, "放 .rvt 的文件夹，界面会列出里面的模型")
        self._path_row(box1, 1, "输出根目录", self.var_out_root,
                       self.pick_out_root, "每次导入会在它下面自动新建独立子目录")
        self._path_row(box1, 2, "NX 安装目录", self.var_nx_root,
                       self.pick_nx_root, "留空则自动探测（找 NXBIN\\run_journal.exe）")

        # ---- 第 2 块：模型列表 ----
        box2 = ttk.LabelFrame(self, text="2. 选择模型（双击某行即开始导入）")
        box2.pack(fill="both", expand=True, **pad)
        cols = ("name", "size", "mtime")
        self.tree = ttk.Treeview(box2, columns=cols, show="headings", height=7,
                                 selectmode="browse")
        self.tree.heading("name", text="模型文件")
        self.tree.heading("size", text="大小")
        self.tree.heading("mtime", text="修改时间")
        self.tree.column("name", width=520, anchor="w")
        self.tree.column("size", width=110, anchor="e")
        self.tree.column("mtime", width=170, anchor="center")
        vs = ttk.Scrollbar(box2, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        vs.pack(side="left", fill="y", pady=6)
        btns = ttk.Frame(box2)
        btns.pack(side="left", fill="y", padx=6, pady=6)
        ttk.Button(btns, text="刷新列表", command=self.refresh_models).pack(fill="x", pady=2)
        ttk.Button(btns, text="开始导入", command=self.start_import).pack(fill="x", pady=2)
        ttk.Checkbutton(btns, text="含子文件夹", variable=self.var_recursive,
                        command=self.refresh_models).pack(fill="x", pady=(8, 2))
        ttk.Label(btns, text="提示：模型按修改\n时间倒序排列", foreground="#666666",
                  justify="left").pack(fill="x", pady=(8, 0))
        self.tree.bind("<Double-1>", lambda e: self.start_import())

        # ---- 第 3 块：参数 ----
        box3 = ttk.LabelFrame(self, text="3. 导入参数")
        box3.pack(fill="x", **pad)

        r1 = ttk.Frame(box3); r1.pack(fill="x", padx=6, pady=3)
        ttk.Label(r1, text="几何精度：").pack(side="left")
        ttk.Radiobutton(r1, text="Precise（推荐）", value="Precise",
                        variable=self.var_geometry).pack(side="left", padx=4)
        ttk.Radiobutton(r1, text="Lightweight（有风险）", value="Lightweight",
                        variable=self.var_geometry, command=self._warn_lightweight)\
            .pack(side="left", padx=4)
        ttk.Label(r1, text="   单位：").pack(side="left")
        ttk.Combobox(r1, textvariable=self.var_unit, values=UNIT_VALUES,
                     width=12, state="readonly").pack(side="left", padx=4)
        ttk.Label(r1, text="   坐标对齐：").pack(side="left")
        ttk.Combobox(r1, textvariable=self.var_csys, values=CSYS_VALUES,
                     width=18, state="readonly").pack(side="left", padx=4)

        r2 = ttk.Frame(box3); r2.pack(fill="x", padx=6, pady=(0, 5))
        ttk.Label(r2, text="导入内容：").pack(side="left")
        ttk.Checkbutton(r2, text="Revit 构件属性", variable=self.var_attrs).pack(side="left", padx=4)
        ttk.Checkbutton(r2, text="按标高建层级", variable=self.var_hier).pack(side="left", padx=4)
        ttk.Checkbutton(r2, text="合并链接模型", variable=self.var_linked).pack(side="left", padx=4)

        # ---- 第 4 块：预检 ----
        box4 = ttk.LabelFrame(self, text="4. 环境自检")
        box4.pack(fill="both", expand=True, **pad)
        self.txt_check = ScrolledText(box4, height=8, wrap="word")
        self.txt_check.pack(fill="both", expand=True, padx=6, pady=6)
        self.txt_check.tag_config("ok", foreground="#0a7d28")
        self.txt_check.tag_config("warn", foreground="#b06a00")
        self.txt_check.tag_config("fail", foreground="#c00000")
        self.txt_check.tag_config("fix", foreground="#0057b8")
        self.txt_check.tag_config("muted", foreground="#666666")

        cb = ttk.Frame(box4)
        cb.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(cb, text="重新自检（检测是否已恢复正常）",
                   command=self.run_preflight).pack(side="left")
        ttk.Button(cb, text="打开 NX 安装目录",
                   command=lambda: self._open(self.var_nx_root.get())).pack(side="left", padx=6)
        ttk.Button(cb, text="打开输出根目录",
                   command=lambda: self._open(self.var_out_root.get())).pack(side="left")

        # ---- 第 5 块：日志 ----
        box5 = ttk.LabelFrame(self, text="5. 运行日志")
        box5.pack(fill="both", expand=True, **pad)
        self.txt_log = ScrolledText(box5, height=10, wrap="word")
        self.txt_log.pack(fill="both", expand=True, padx=6, pady=6)
        self.txt_log.tag_config("step", foreground="#0057b8")
        self.txt_log.tag_config("ok", foreground="#0a7d28")
        self.txt_log.tag_config("warn", foreground="#b06a00")
        self.txt_log.tag_config("fail", foreground="#c00000")
        self.txt_log.tag_config("muted", foreground="#666666")

        # ---- 底部状态栏 ----
        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        self.progress = ttk.Progressbar(bar, mode="determinate", maximum=100, length=260)
        self.progress.pack(side="left")
        ttk.Label(bar, textvariable=self.var_status).pack(side="left", padx=10)
        ttk.Button(bar, text="复制报告", command=self.copy_report).pack(side="right", padx=4)
        ttk.Button(bar, text="清空日志", command=lambda: self.txt_log.delete("1.0", "end"))\
            .pack(side="right")

    def _path_row(self, parent, row, label, var, cmd, hint):
        ttk.Label(parent, text=label, width=12, anchor="e").grid(
            row=row, column=0, sticky="e", padx=(8, 4), pady=3)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(parent, text="浏览…", command=cmd, width=8).grid(
            row=row, column=2, padx=6, pady=3)
        ttk.Label(parent, text=hint, foreground="#666666").grid(
            row=row, column=3, sticky="w", padx=(0, 8), pady=3)
        parent.columnconfigure(1, weight=1)

    # ==================================================================
    # 配置持久化
    # ==================================================================
    def _load_config(self):
        cfg = {}
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                cfg = json.load(fh) or {}
        except (OSError, ValueError):
            pass
        self.var_model_dir.set(cfg.get("model_dir") or _default_model_dir())
        self.var_out_root.set(cfg.get("output_root") or _default_output_root())
        self.var_nx_root.set(cfg.get("nx_root") or "")
        self.var_geometry.set(cfg.get("geometry") or "Precise")
        self.var_unit.set(cfg.get("unit") or "Millimeter")
        self.var_csys.set(cfg.get("csys") or "SurveyPoint")
        self.var_attrs.set(cfg.get("attrs", True))
        self.var_hier.set(cfg.get("hier", True))
        self.var_linked.set(cfg.get("linked", True))
        self.var_recursive.set(cfg.get("recursive", True))

    def _save_config(self):
        cfg = {
            "model_dir": self.var_model_dir.get(),
            "output_root": self.var_out_root.get(),
            "nx_root": self.var_nx_root.get(),
            "geometry": self.var_geometry.get(),
            "unit": self.var_unit.get(),
            "csys": self.var_csys.get(),
            "attrs": bool(self.var_attrs.get()),
            "hier": bool(self.var_hier.get()),
            "linked": bool(self.var_linked.get()),
            "recursive": bool(self.var_recursive.get()),
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # ==================================================================
    # 小工具
    # ==================================================================
    def _open(self, path):
        path = (path or "").strip()
        if not path:
            messagebox.showinfo("提示", "这个目录还没设置。")
            return
        if not os.path.isdir(path):
            messagebox.showwarning("提示", "目录不存在：\n" + path)
            return
        try:
            os.startfile(path)
        except OSError as exc:
            messagebox.showerror("打不开", "{0!r}".format(exc))

    def pick_model_dir(self):
        d = filedialog.askdirectory(title="选择模型库目录（放 .rvt 的文件夹）",
                                    initialdir=self.var_model_dir.get() or None)
        if d:
            self.var_model_dir.set(d)
            self.refresh_models()

    def pick_out_root(self):
        d = filedialog.askdirectory(title="选择输出根目录",
                                    initialdir=self.var_out_root.get() or None)
        if d:
            self.var_out_root.set(d)

    def pick_nx_root(self):
        d = filedialog.askdirectory(title="选择 NX 安装根目录（里面有 NXBIN 子目录）",
                                    initialdir=self.var_nx_root.get() or None)
        if d:
            self.var_nx_root.set(d)
            self.run_preflight()

    def _warn_lightweight(self):
        if self.var_geometry.get() == "Lightweight":
            messagebox.showwarning(
                "Lightweight 有已知问题",
                "实测：同一个模型用 Lightweight 导入，173 个部件里有 168 个的"
                "几何没进去（翻译器报 168 条 'Failed to create import feature'）。\n\n"
                "表现是：文件数正常、错误数为 0，但在 NX 里看不到模型。\n\n"
                "除非你明确知道自己要什么，否则请用 Precise。")

    def log(self, msg, tag=None):
        self.txt_log.insert("end", msg + "\n", tag or "")
        self.txt_log.see("end")

    def copy_report(self):
        text = self.txt_log.get("1.0", "end").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.var_status.set("报告已复制到剪贴板")

    def _set_status(self, s):
        self.var_status.set(s)

    # ==================================================================
    # 模型列表
    # ==================================================================
    def refresh_models(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.models = []
        d = self.var_model_dir.get().strip()
        self.log("---- 扫描模型库：{0}".format(d or "(未设置)"), "step")
        if not d or not os.path.isdir(d):
            self.log("  目录不存在，请在「模型库目录」里选择一个文件夹。", "warn")
            return

        recursive = bool(self.var_recursive.get())
        ext_ok = (".rvt", ".rfa", ".rte")
        found = []

        try:
            for root, dirs, files in os.walk(d):
                if not recursive:
                    dirs[:] = []          # 只看当前层
                else:
                    rel_root = os.path.relpath(root, d)
                    depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
                    if depth >= 4:        # 限深，避免扫进巨大的无关目录
                        dirs[:] = []
                for name in files:
                    if not name.lower().endswith(ext_ok):
                        continue
                    full = os.path.join(root, name)
                    try:
                        st = os.stat(full)
                    except OSError:
                        continue
                    if st.st_size == 0:
                        continue
                    found.append((
                        full,
                        os.path.relpath(full, d),
                        st.st_size,
                        time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                        st.st_mtime,
                    ))
        except OSError as exc:
            self.log("  扫描出错：{0!r}".format(exc), "fail")
            return

        found.sort(key=lambda t: t[4], reverse=True)   # 按修改时间倒序，最近的在上面
        for full, rel, size, mt, _ts in found:
            human = "{0:.2f} MB".format(size / 1048576.0) if size >= 1048576 \
                else "{0:.1f} KB".format(size / 1024.0)
            self.tree.insert("", "end", iid=full, values=(rel, human, mt))
            self.models.append(full)

        self.log("  找到 {0} 个模型{1}。双击某一行即可导入。".format(
            len(found), "（含子文件夹）" if recursive else "（仅当前层）"),
            "ok" if found else "warn")
        if not found:
            self.log("  没找到 .rvt / .rfa / .rte。如果模型在更深的子目录里，"
                     "勾选「含子文件夹」。", "muted")

    def selected_model(self):
        sel = self.tree.selection()
        if sel:
            return sel[0]
        return self.models[0] if self.models else None

    # ==================================================================
    # 环境自检
    # ==================================================================
    def run_preflight(self):
        self.txt_check.delete("1.0", "end")
        self._save_config()

        def show(check):
            tag = {"ok": "ok", "warn": "warn", "fail": "fail", "fixed": "fix"}[check.status]
            self.txt_check.insert("end", check.as_line() + "\n", tag)

        self.txt_check.insert("end", "== NX 环境 ==\n", "step")
        checks, root = pf.check_environment(self.var_nx_root.get().strip() or None)
        for c in checks:
            show(c)
        if root and not self.var_nx_root.get().strip():
            self.var_nx_root.set(root)
        self.nx_root = root

        # 交互式 NX 进程状态（仅供说明，不是错误）
        self.txt_check.insert("end", "\n== NX 进程 ==\n", "step")
        running = self._nx_processes()
        if running:
            self.txt_check.insert(
                "end",
                "[注意] 检测到已打开的 NX：{0}\n"
                "         -> 本工具用 run_journal 启动的是【独立】批处理会话，"
                "导入结果不会出现在那个窗口里。\n"
                "            想在已打开的 NX 里导入，请用 NX 的 工具→日志→播放。\n"
                .format("、".join(running)), "warn")
        else:
            self.txt_check.insert(
                "end", "[通过] 当前没有交互式 NX 在运行，将直接启动批处理会话。\n", "ok")

        self.txt_check.insert("end", "\n== 模型与输出 ==\n", "step")
        model = self.selected_model()
        for c in pf.check_model(model):
            show(c)
        d, cs = pf.plan_output_dir(self.var_out_root.get().strip(), model,
                                   self.var_geometry.get())
        for c in cs:
            show(c)
        if d and os.path.isdir(d):
            # 预检时建的空目录先删掉，真正导入时再建，避免留下空壳
            try:
                os.rmdir(d)
            except OSError:
                pass

        all_checks = checks + pf.check_model(model) + cs
        ok, _ = pf.summarize(all_checks)
        self._preflight_ok = ok

        self.txt_check.insert("end", "\n" + "=" * 60 + "\n")
        if ok:
            self.txt_check.insert("end", "自检结论：可以开始导入。\n", "ok")
            self._set_status("自检通过")
        else:
            self.txt_check.insert(
                "end",
                "自检结论：有必须解决的问题，先按上面每条的 -> 提示处理，\n"
                "          修好后点「重新自检」确认是否恢复正常。\n", "fail")
            self._set_status("自检未通过")

    def _nx_processes(self):
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq ugraf.exe", "/NH"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=10).stdout
            text = _decode(out)
            pids = re.findall(r"ugraf\.exe\s+(\d+)", text)
            return ["ugraf.exe PID " + p for p in pids]
        except Exception:
            return []

    # ==================================================================
    # 导入
    # ==================================================================
    def start_import(self):
        if self.busy:
            messagebox.showinfo("提示", "上一次导入还在进行中。")
            return
        model = self.selected_model()
        if not model:
            messagebox.showwarning("提示", "请先在列表里选中一个模型。")
            return

        self._save_config()
        self.run_preflight()
        if not getattr(self, "_preflight_ok", False):
            messagebox.showerror(
                "自检未通过",
                "环境自检发现问题，已写在「4. 环境自检」里。\n\n"
                "每条失败项下面都有 -> 开头的修复提示，处理完点「重新自检」。")
            return

        out_dir, cs = pf.plan_output_dir(self.var_out_root.get().strip(), model,
                                         self.var_geometry.get())
        if not out_dir:
            messagebox.showerror("无法创建输出目录",
                                 "\n".join(c.detail for c in cs))
            return

        self.busy = True
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.var_status.set("正在导入…")

        args = [
            "--rvt", model,
            "--import-to", "NewPart",                 # 批处理会话只能用 NewPart
            "--geometry-as", self.var_geometry.get(),
            "--part-unit", self.var_unit.get(),
            "--project-csys", self.var_csys.get(),
            "--output-dir", out_dir,
        ]
        if not self.var_attrs.get():
            args.append("--no-attributes")
        if not self.var_hier.get():
            args.append("--no-hierarchy")
        if not self.var_linked.get():
            args.append("--no-linked-models")

        self.log("")
        self.log("=" * 66, "step")
        self.log("开始导入：{0}".format(os.path.basename(model)), "step")
        self.log("输出目录：{0}".format(out_dir))
        self.log("=" * 66, "step")

        t = threading.Thread(target=self._worker, args=(model, out_dir, args), daemon=True)
        self.worker = t
        t.start()

    def _worker(self, model, out_dir, args):
        q = self.queue

        # 队列条目统一为 (kind, payload) 二元组，这里用三个小助手避免拼错
        def emit_log(msg, tag=None):
            q.put(("log", (msg, tag or "")))

        def emit_progress(text):
            q.put(("progress", text))

        try:
            rj = os.path.join(self.nx_root, "NXBIN", "run_journal.exe")
            cmd = [rj, "-nx", IMPORT_SCRIPT, "-args"] + args
            emit_log("启动 NX 批处理会话 …", "step")
            emit_log("  " + subprocess.list2cmdline(cmd), "muted")

            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=BASE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

            for raw in iter(proc.stdout.readline, b""):
                line = _decode(raw).rstrip()
                if line:
                    emit_log("  " + line)
            rc = proc.wait()
            emit_log("NX 会话结束，退出码 = {0}".format(rc),
                     "ok" if rc == 0 else "warn")

            # ---- 等落盘 ----
            emit_log("")
            emit_log("等待 NX 把部件写盘（实测比脚本返回晚约 26 秒）…", "step")
            flushed, count = self._wait_for_flush(out_dir, emit_progress)
            if flushed:
                emit_log("已落盘：{0} 个 .prt".format(count), "ok")
            else:
                emit_log("等待超时，仍按当前状态核对（可能尚未写完）", "warn")

            # ---- 核对 ----
            emit_log("")
            emit_log("=" * 66, "step")
            emit_log("核对结果", "step")
            emit_log("=" * 66, "step")

            report = nxcheck.analyze(out_dir)
            emit_log(report.verdict, "ok" if report.ok else "fail")
            for ln in report.lines:
                emit_log(ln)
            if report.hints:
                emit_log("")
                emit_log("怎么修：", "warn")
                for h in report.hints:
                    emit_log("  - " + h, "warn")

            # 导入脚本自己日志里的异常 -> 可操作建议
            _slines, shints = nxcheck.fix_hint_for_log(SCRIPT_LOG)
            if shints:
                emit_log("")
                emit_log("导入脚本日志里的线索：", "warn")
                for h in shints:
                    emit_log("  - " + h, "warn")

            q.put(("done", (report, out_dir)))
        except Exception:
            emit_log("内部异常：\n" + traceback.format_exc(), "fail")
            q.put(("done", (None, out_dir)))

    def _wait_for_flush(self, out_dir, emit_progress, timeout=240, interval=3, stable=3):
        """
        轮询输出目录，等 NX 把部件写完。
        判定：.prt 数量 > 0，且连续 stable 次不再增加；同时翻译器日志已出现。
        """
        last = -1
        same = 0
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                names = os.listdir(out_dir)
            except OSError:
                names = []
            n = sum(1 for x in names if x.lower().endswith(".prt"))
            has_log = any(x.lower().endswith(".log") for x in names)

            emit_progress("{0} 个 .prt，已等 {1} 秒".format(n, int(time.time() - t0)))
            if n > 0 and n == last and has_log:
                same += 1
                if same >= stable:
                    return True, n
            else:
                same = 0
            last = n
            time.sleep(interval)
        return False, max(last, 0)

    # ==================================================================
    # 主线程消费队列
    # ==================================================================
    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    msg, tag = payload
                    self.log(msg, tag)
                elif kind == "progress":
                    self.var_status.set("导入中，已写入 " + payload)
                elif kind == "done":
                    self._on_done(*payload)
        except queue.Empty:
            pass
        self.after(120, self._drain_queue)

    def _on_done(self, report, out_dir):
        self.busy = False
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress["value"] = 100 if (report and report.ok) else 0

        if report is None:
            self._set_status("导入异常结束")
            messagebox.showerror("导入异常", "内部发生异常，详情见日志区。")
            return

        if report.ok:
            self._set_status("导入成功")
            if messagebox.askyesno(
                    "导入成功",
                    "{0}\n\n输出目录：\n{1}\n\n现在打开该目录吗？".format(
                        report.verdict, out_dir)):
                self._open(out_dir)
        else:
            self._set_status("导入未通过核对")
            hints = "\n".join("· " + h for h in report.hints[:6]) or "（见日志区）"
            messagebox.showerror(
                "导入未通过核对",
                "{0}\n\n怎么修：\n{1}\n\n完整报告在下面的日志区，可点「复制报告」。".format(
                    report.verdict, hints))


def main():
    if not os.path.isfile(IMPORT_SCRIPT):
        root = tk.Tk(); root.withdraw()
        messagebox.showerror("缺少文件", "找不到导入脚本：\n" + IMPORT_SCRIPT)
        return 2
    app = App()
    app.protocol("WM_DELETE_WINDOW", lambda: (app._save_config(), app.destroy()))
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
