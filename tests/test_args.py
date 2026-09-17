# -*- coding: utf-8 -*-
"""
参数解析测试。

用假 NXOpen 模块顶替真模块，从而可以在 NX 之外运行。
重点验证刚修掉的那个浅拷贝别名 bug，以及 --help 的处理。

用法：
    python tests\\test_args.py
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))

# ---- 用假 NXOpen 顶替真模块，使脚本可在 NX 以外导入 ----
_fake = types.ModuleType("NXOpen")
_fake.Session = type("Session", (), {"GetSession": staticmethod(lambda: None)})
sys.modules["NXOpen"] = _fake

sys.path.insert(0, SRC)
import import_revit as ir  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    mark = "PASS" if cond else "FAIL"
    line = "  [{0}] {1}".format(mark, name)
    if extra and not cond:
        line += "   <- 实际: " + extra
    print(line)
    if not cond:
        FAILS.append(name)


print("=" * 64)
print("参数解析测试（NX 外运行，用假 NXOpen 模块）")
print("=" * 64)

# ---- 1. --rvt 必须是替换 CONFIG，而不是追加（浅拷贝别名 bug）----
PLACEHOLDER = r"C:\placeholder\占位.rvt"
ir.CONFIG["rvt_files"] = [PLACEHOLDER]
before = list(ir.CONFIG["rvt_files"])

opt = ir._parse_args(["--rvt", r"D:\a.rvt", "--rvt", r"D:\b.rvt"])
check("--rvt 替换而非追加 CONFIG 列表",
      opt["rvt_files"] == [r"D:\a.rvt", r"D:\b.rvt"], repr(opt["rvt_files"]))
check("占位文件未被一并导入",
      PLACEHOLDER not in opt["rvt_files"], repr(opt["rvt_files"]))
check("--rvt 未污染 CONFIG（list 别名已断开）",
      ir.CONFIG["rvt_files"] == before, repr(ir.CONFIG["rvt_files"]))

# ---- 2. 不给 --rvt 时沿用 CONFIG ----
opt2 = ir._parse_args(["--import-to", "NewPart"])
check("不给 --rvt 时沿用 CONFIG", opt2["rvt_files"] == before, repr(opt2["rvt_files"]))

# ---- 3. --help 抛 _ShowHelp，而不是 SystemExit ----
# SystemExit 继承自 BaseException，main() 的 except Exception 抓不到，
# 会直接漏进 NX 的日志处理器。
try:
    ir._parse_args(["--help"])
    check("--help 抛 _ShowHelp 而非 SystemExit", False, "没有抛任何异常")
except ir._ShowHelp:
    check("--help 抛 _ShowHelp 而非 SystemExit", True)
except BaseException as exc:
    check("--help 抛 _ShowHelp 而非 SystemExit", False, "抛了 " + type(exc).__name__)

# ---- 4. 默认值 ----
d = ir._parse_args([])
check("默认 geometry_as = Precise", d["geometry_as"] == "Precise", d["geometry_as"])
check("默认 project_csys = SurveyPoint",
      d["project_csys"] == "SurveyPoint", d["project_csys"])
check("默认 part_unit = Millimeter", d["part_unit"] == "Millimeter", d["part_unit"])
check("默认 output_dir = None", d["output_dir"] is None, repr(d["output_dir"]))
check("默认 process_attributes = True", d["process_attributes"] is True)

# ---- 5. 开关类参数 ----
s = ir._parse_args(["--no-attributes", "--no-hierarchy",
                    "--no-linked-models", "--teamcenter", "--show-window"])
check("--no-attributes 生效", s["process_attributes"] is False)
check("--no-hierarchy 生效", s["level_hierarchy"] is False)
check("--no-linked-models 生效", s["process_linked_models"] is False)
check("--teamcenter 生效", s["import_to_teamcenter"] is True)
check("--show-window 生效", s["show_info_window"] is True)

# ---- 6. 带值参数 ----
v = ir._parse_args(["--geometry-as", "Lightweight", "--part-unit", "Meter",
                    "--project-csys", "ProjectBasePoint", "--messages", "Warning",
                    "--output-dir", r"D:\out", "--output-file", r"D:\out\x.prt"])
check("--geometry-as 生效", v["geometry_as"] == "Lightweight", v["geometry_as"])
check("--part-unit 生效", v["part_unit"] == "Meter", v["part_unit"])
check("--project-csys 生效",
      v["project_csys"] == "ProjectBasePoint", v["project_csys"])
check("--messages 生效", v["messages"] == "Warning", v["messages"])
check("--output-dir 生效", v["output_dir"] == r"D:\out", v["output_dir"])
check("--output-file 生效", v["output_file"] == r"D:\out\x.prt", v["output_file"])

# ---- 7. 缺值必须报错 ----
for bad in ("--rvt", "--output-dir", "--geometry-as"):
    try:
        ir._parse_args([bad])
        check(bad + " 缺值时报错", False, "没有报错")
    except ValueError as exc:
        check(bad + " 缺值时报错", "缺少取值" in str(exc), str(exc))

# ---- 8. 枚举取值校验函数 ----
class _E(object):
    A = "a"
    B = "b"


check("_enum 正常取值", ir._enum(_E, "A", ("A", "B"), "demo") == "a")
try:
    ir._enum(_E, "Z", ("A", "B"), "demo")
    check("_enum 非法值时给出合法值清单", False, "没有报错")
except ValueError as exc:
    check("_enum 非法值时给出合法值清单", "A, B" in str(exc), str(exc))

# ---- 9. 未知参数应被忽略而不是崩溃 ----
try:
    u = ir._parse_args(["--not-a-flag", "junk", "--geometry-as", "Precise"])
    check("未知参数被忽略且不影响后续解析",
          u["geometry_as"] == "Precise", repr(u["geometry_as"]))
except Exception as exc:
    check("未知参数被忽略且不影响后续解析", False, repr(exc))

print("")
if FAILS:
    print("失败 {0} 项：".format(len(FAILS)))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("全部通过")
