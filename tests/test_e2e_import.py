# -*- coding: utf-8 -*-
"""
端到端测试：走 GUI 真实的导入流程（start_import -> 工作线程 -> 等待落盘 -> 核对）。
把 messagebox 打桩成自动应答，从而无需人工点击。

这是最重的一项测试：会真的启动一次 NX 批处理会话并导入一个真实模型，
耗时约 2~4 分钟。

用法（必须自己指定一个 .rvt，仓库里不含任何模型）：
    python tests\\test_e2e_import.py "D:\\bim\\model.rvt"
    python tests\\test_e2e_import.py "D:\\bim\\model.rvt" "D:\\out\\_e2e"

未指定模型时本测试会直接跳过（退出码 2），不算失败。
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, BASE)

import Revit2NX  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else ""
OUT_ROOT = sys.argv[2] if len(sys.argv) > 2 else \
    os.path.join(tempfile.gettempdir(), "NXRevitImport_e2e")

FAILS = []
POPUPS = []


def check(name, cond, extra=""):
    print("  [{0}] {1}{2}".format(
        "PASS" if cond else "FAIL", name,
        ("   <- " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        FAILS.append(name)


# ---- 把弹窗打桩，避免测试卡住等人点 ----
def _record(kind):
    def fn(title, msg, **kw):
        POPUPS.append((kind, title, msg))
        return False
    return fn


Revit2NX.messagebox.askyesno = _record("askyesno")
Revit2NX.messagebox.showerror = _record("showerror")
Revit2NX.messagebox.showinfo = _record("showinfo")
Revit2NX.messagebox.showwarning = _record("showwarning")

print("=" * 66)
print("端到端测试：GUI 导入流程")
print("模型：{0}".format(MODEL or "(未指定)"))
print("=" * 66)

if not MODEL:
    print("")
    print("未指定模型，跳过本测试。")
    print("用法： python tests\\test_e2e_import.py \"D:\\bim\\model.rvt\" [输出根目录]")
    sys.exit(2)

if not os.path.isfile(MODEL):
    print("模型不存在，跳过：{0}".format(MODEL))
    sys.exit(2)

app = Revit2NX.App()
app.withdraw()
app.var_out_root.set(OUT_ROOT)

# 等预检跑完
deadline = time.time() + 30
while time.time() < deadline:
    app.update()
    if getattr(app, "_preflight_ok", None) is not None:
        break
    time.sleep(0.1)

check("预检通过", getattr(app, "_preflight_ok", False) is True, app._preflight_ok)
check("已探测到 NX 根目录", bool(app.nx_root), app.nx_root)

# 选中模型
iid = None
for m in app.models:
    if os.path.normcase(m) == os.path.normcase(MODEL):
        iid = m
        break
if iid is None:
    print("模型不在模型库列表里，改为直接加入列表")
    app.tree.insert("", "end", iid=MODEL, values=(os.path.basename(MODEL), "-", "-"))
    app.models.append(MODEL)
    iid = MODEL
app.tree.selection_set(iid)
app.var_geometry.set("Precise")

# ---- 记录导入前的输出目录集合 ----
before_dirs = set()
if os.path.isdir(OUT_ROOT):
    before_dirs = set(os.listdir(OUT_ROOT))

print("")
print("调用 start_import()（真实 GUI 流程）…")
app.start_import()

# 等 busy 变 True（确认真的开始了）
t0 = time.time()
while time.time() - t0 < 30:
    app.update()
    if app.busy:
        break
    time.sleep(0.1)
check("导入已启动", app.busy, "busy={0}".format(app.busy))

# 等 busy 变 False（确认结束）
t0 = time.time()
seen_log = []
while time.time() - t0 < 420:
    app.update()
    if not app.busy:
        break
    time.sleep(0.2)

check("导入已结束", not app.busy, "仍在运行")

log_text = app.txt_log.get("1.0", "end")
check("日志里有核对结果", "核对结果" in log_text)
check("日志里报告了落盘数量", "已落盘" in log_text)

# ---- 新增的输出目录应当恰好一个 ----
after_dirs = set()
if os.path.isdir(OUT_ROOT):
    after_dirs = set(os.listdir(OUT_ROOT))
new_dirs = sorted(after_dirs - before_dirs)
check("自动新建了恰好一个独立输出目录", len(new_dirs) == 1, new_dirs)

if new_dirs:
    out_dir = os.path.join(OUT_ROOT, new_dirs[0])
    prts = [n for n in os.listdir(out_dir) if n.lower().endswith(".prt")]
    logs = [n for n in os.listdir(out_dir) if n.lower().endswith(".log")]
    check("输出目录里有部件", len(prts) > 0, len(prts))
    check("输出目录里有翻译器日志", len(logs) > 0, len(logs))

    import nxcheck
    rep = nxcheck.analyze(out_dir)
    check("核对结论为成功", rep.ok, rep.verdict)
    check("无 _N 后缀残留", len(rep.data.get("suffixed", [])) == 0,
          rep.data.get("suffixed"))

    print("")
    print("--- 核对报告 ---")
    print(rep.text())

check("没有弹出错误对话框", not [p for p in POPUPS if p[0] == "showerror"],
      [p[1] for p in POPUPS if p[0] == "showerror"])

app.destroy()

print("")
if FAILS:
    print("失败 {0} 项：".format(len(FAILS)))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("全部通过")
