# -*- coding: utf-8 -*-
"""
GUI 烟测：构造界面、驱动事件循环，验证
  - 界面能建起来（控件、变量、回调都合法）
  - 配置加载正常
  - 模型扫描正常（含子文件夹递归）
  - 环境自检真的跑过并给出结论
  - 输出目录规划能给出互不覆盖的独立目录
无需人工点击，且不依赖本机是否真的有 .rvt —— 测试自己造临时模型库。

用法：
    python tests\\test_gui_smoke.py
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, BASE)

import Revit2NX  # noqa: E402

FAILS = []
SANDBOX = None


def check(name, cond, extra=""):
    print("  [{0}] {1}{2}".format(
        "PASS" if cond else "FAIL", name,
        ("   <- " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        FAILS.append(name)


def make_sandbox():
    """造一个自包含的临时模型库：根目录 1 个模型，子目录 1 个模型。"""
    root = tempfile.mkdtemp(prefix="nxbridge_gui_")
    with open(os.path.join(root, "root_model.rvt"), "wb") as fh:
        fh.write(b"DUMMY" * 2000)
    sub = os.path.join(root, "sub", "deeper")
    os.makedirs(sub)
    with open(os.path.join(sub, "nested_model.rvt"), "wb") as fh:
        fh.write(b"DUMMY" * 3000)
    # 一个不该被当成模型的干扰文件
    with open(os.path.join(root, "readme.txt"), "wb") as fh:
        fh.write(b"not a model")
    return root


print("=" * 64)
print("GUI 烟测")
print("=" * 64)

SANDBOX = make_sandbox()
print("临时模型库：{0}".format(SANDBOX))
print("")

app = Revit2NX.App()
app.withdraw()          # 不弹窗
check("App 能构造", True)
check("模型库文本框已填默认值", bool(app.var_model_dir.get()), app.var_model_dir.get())
check("输出根目录已填默认值", bool(app.var_out_root.get()), app.var_out_root.get())
check("几何精度默认 Precise", app.var_geometry.get() == "Precise", app.var_geometry.get())
check("坐标对齐默认 SurveyPoint",
      app.var_csys.get() == "SurveyPoint", app.var_csys.get())
check("递归扫描默认开启", bool(app.var_recursive.get()))

# 驱动 after() 里排的初始化任务：refresh_models 与 run_preflight
deadline = time.time() + 25
while time.time() < deadline:
    app.update()
    if getattr(app, "_preflight_ok", None) is not None:
        break
    time.sleep(0.1)

check("环境自检执行过", getattr(app, "_preflight_ok", None) is not None,
      "None 表示没跑到")
check("自检面板有内容",
      len(app.txt_check.get("1.0", "end").strip()) > 50)
check("自检面板含结论行", "自检结论" in app.txt_check.get("1.0", "end"))

# ---- 指向沙箱，验证递归扫描 ----
app.var_model_dir.set(SANDBOX)
app.var_recursive.set(True)
app.refresh_models()
n_rec = len(app.models)
check("递归扫描找到 2 个模型", n_rec == 2, "找到 {0} 个".format(n_rec))
names = sorted(os.path.basename(m) for m in app.models)
check("找到的是两个 .rvt（干扰文件被忽略）",
      names == ["nested_model.rvt", "root_model.rvt"], names)

app.var_recursive.set(False)
app.refresh_models()
n_flat = len(app.models)
check("关闭递归后只找到当前层 1 个", n_flat == 1, "找到 {0} 个".format(n_flat))

app.var_recursive.set(True)
app.refresh_models()

# ---- 输出目录规划：必须互不覆盖 ----
if app.models:
    out_root = os.path.join(SANDBOX, "out")
    model = app.models[0]
    d1, _ = Revit2NX.pf.plan_output_dir(out_root, model, "Precise")
    check("能规划独立输出目录", bool(d1) and os.path.isdir(d1), str(d1))
    if d1:
        d2, _ = Revit2NX.pf.plan_output_dir(out_root, model, "Precise")
        check("连续两次规划得到不同目录（不覆盖历史）", d2 != d1,
              "{0} vs {1}".format(d1, d2))
        if d2:
            check("第二次规划带序号后缀", os.path.basename(d2) != os.path.basename(d1),
                  os.path.basename(d2))
            check("两个目录都真实存在且为空",
                  os.path.isdir(d1) and os.path.isdir(d2)
                  and not os.listdir(d1) and not os.listdir(d2))

    # ---- 模型检查：0 字节文件必须被判失败 ----
    empty = os.path.join(SANDBOX, "empty.rvt")
    open(empty, "wb").close()
    cs = Revit2NX.pf.check_model(empty)
    check("0 字节模型被判为失败",
          any(c.status == Revit2NX.pf.FAIL for c in cs),
          [c.status for c in cs])

    cs2 = Revit2NX.pf.check_model(model)
    check("正常模型通过检查",
          all(c.status != Revit2NX.pf.FAIL for c in cs2),
          [c.status for c in cs2])

app.destroy()

if SANDBOX:
    shutil.rmtree(SANDBOX, ignore_errors=True)

print("")
if FAILS:
    print("失败 {0} 项：".format(len(FAILS)))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("全部通过")
