# -*- coding: utf-8 -*-
"""
环境预检与自动修复。

设计原则：能自动修的自动修掉并明确告知；修不了的给出「往哪修」的具体路径与操作。
每一步都返回可读的结论，供 GUI 或命令行显示。

纯标准库，不依赖 NX。
"""
import os
import re
import shutil
import sys

# 状态
OK = "ok"        # 通过
FIXED = "fixed"  # 原本有问题，已自动修复
WARN = "warn"    # 可继续，但有风险
FAIL = "fail"    # 必须修复才能继续


class Check(object):
    def __init__(self, name, status, detail, hint="", value=None):
        self.name = name
        self.status = status
        self.detail = detail
        self.hint = hint
        self.value = value

    @property
    def blocking(self):
        return self.status == FAIL

    def as_line(self):
        mark = {OK: "[通过]", FIXED: "[已修复]", WARN: "[注意]", FAIL: "[失败]"}[self.status]
        s = "{0} {1}：{2}".format(mark, self.name, self.detail)
        if self.hint:
            s += "\n         -> " + self.hint
        return s


# ---------------------------------------------------------------------------
# NX 安装位置探测
# ---------------------------------------------------------------------------
def _candidate_roots_from_registry():
    roots = []
    try:
        import winreg
    except ImportError:
        return roots

    def walk(hive, subkey, depth=0):
        if depth > 3:
            return
        try:
            with winreg.OpenKey(hive, subkey) as key:
                i = 0
                while True:
                    try:
                        child = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1
                    full = subkey + "\\" + child
                    try:
                        with winreg.OpenKey(hive, full) as ck:
                            for val in ("InstallLocation", "InstallDir", "UGII_BASE_DIR"):
                                try:
                                    v, _t = winreg.QueryValueEx(ck, val)
                                    if v:
                                        roots.append(str(v))
                                except OSError:
                                    pass
                    except OSError:
                        pass
                    walk(hive, full, depth + 1)
        except OSError:
            pass

    for hive, base in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Siemens"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Siemens"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Unigraphics Solutions"),
    ):
        walk(hive, base)
    return roots


def _looks_like_nx_root(path):
    if not path or not os.path.isdir(path):
        return False
    return os.path.isfile(os.path.join(path, "NXBIN", "run_journal.exe"))


def detect_nx_roots():
    """
    探测 NX 安装根目录，优先级：
      1) 环境变量 UGII_BASE_DIR
      2) 注册表里的 Siemens 安装位置
      3) 常见默认路径
    只返回确实含 NXBIN\\run_journal.exe 的目录。
    """
    found = []
    seen = set()

    def add(p):
        if not p:
            return
        p = os.path.abspath(str(p).rstrip("\\/"))
        key = p.lower()
        if key in seen:
            return
        seen.add(key)
        if _looks_like_nx_root(p):
            found.append(p)

    add(os.environ.get("UGII_BASE_DIR"))
    for r in _candidate_roots_from_registry():
        add(r)

    # 注册表里的 InstallLocation 形态不一，可能是 "D:\Siemens\NX2406\"，
    # 也可能是 "D:\DesigncenterNX2512\"，所以按关键字模糊匹配子目录名。
    for drive in ("C:", "D:", "E:", "F:", "G:"):
        for pattern in ("Program Files\\Siemens", "Siemens", "NX", "Program Files"):
            base = os.path.join(drive + "\\", pattern)
            if not os.path.isdir(base):
                continue
            try:
                for name in os.listdir(base):
                    if re.search(r"(?i)nx|designcenter|simcenter", name):
                        add(os.path.join(base, name))
            except OSError:
                continue

    return found


# ---------------------------------------------------------------------------
# 环境预检
# ---------------------------------------------------------------------------
def check_environment(nx_root):
    """
    检查 NX 环境。返回 (checks, nx_root)。
    nx_root 可能被自动探测出来（此时会有一条 FIXED 记录）。
    """
    checks = []

    if not nx_root:
        candidates = detect_nx_roots()
        if candidates:
            nx_root = candidates[0]
            extra = "" if len(candidates) == 1 else "（另有候选：{0}）".format(
                ", ".join(candidates[1:]))
            checks.append(Check(
                "NX 安装位置", FIXED,
                "自动探测到 {0}{1}".format(nx_root, extra),
                "如需指定别的安装，在界面「NX 安装目录」里手填。",
                nx_root))
        else:
            checks.append(Check(
                "NX 安装位置", FAIL, "没有探测到 NX 安装",
                "设置环境变量 UGII_BASE_DIR 指向 NX 根目录"
                "（例如 C:\\Program Files\\Siemens\\NX2406），"
                "或在界面「NX 安装目录」里手填。"))
            return checks, None
    else:
        if _looks_like_nx_root(nx_root):
            checks.append(Check("NX 安装位置", OK, nx_root, value=nx_root))
        else:
            checks.append(Check(
                "NX 安装位置", FAIL,
                "{0} 下找不到 NXBIN\\run_journal.exe".format(nx_root),
                "确认路径指向的是 NX 根目录（里面有 NXBIN 子目录），不是 NXBIN 本身。"))
            return checks, None

    # run_journal.exe
    rj = os.path.join(nx_root, "NXBIN", "run_journal.exe")
    if os.path.isfile(rj):
        checks.append(Check("run_journal.exe", OK, rj))
    else:
        checks.append(Check("run_journal.exe", FAIL, "缺少 {0}".format(rj),
                            "NX 安装不完整，建议用 NX 安装程序修复安装。"))

    # NXOpen.pyd
    pyd = os.path.join(nx_root, "NXBIN", "python", "NXOpen.pyd")
    if os.path.isfile(pyd):
        checks.append(Check("NXOpen Python 运行时", OK, pyd))
    else:
        checks.append(Check(
            "NXOpen Python 运行时", FAIL, "缺少 {0}".format(pyd),
            "NX 安装不完整（缺 Python 接口），建议修复安装。"))

    # Revit 转换器
    revit_dir = os.path.join(nx_root, "translators", "revit")
    ja = os.path.join(nx_root, "NXBIN", "libjaimporters.dll")
    if os.path.isdir(revit_dir) or os.path.isfile(ja):
        where = revit_dir if os.path.isdir(revit_dir) else ja
        checks.append(Check("Revit 数据交换模块", OK, "已安装：{0}".format(where)))
    else:
        checks.append(Check(
            "Revit 数据交换模块", FAIL, "找不到 translators\\revit 或 libjaimporters.dll",
            "这是导入 Revit 的必需模块，需通过 NX 安装程序补装并确保有对应许可。"))

    # 缓存目录可写（NX 需要写 syslog 与临时文件）
    tmp = os.environ.get("TEMP") or os.environ.get("TMP")
    if tmp and os.path.isdir(tmp):
        probe = os.path.join(tmp, "_nxbridge_write_probe.tmp")
        try:
            with open(probe, "w") as fh:
                fh.write("x")
            os.remove(probe)
            checks.append(Check("临时目录可写", OK, tmp))
        except OSError as exc:
            checks.append(Check("临时目录可写", WARN,
                                "{0} 不可写：{1!r}".format(tmp, exc),
                                "NX 需要写临时目录，请清理或改 TEMP 环境变量。"))
    else:
        checks.append(Check("临时目录可写", WARN, "TEMP/TMP 未设置或不存在",
                            "设置 TEMP 到一个可写目录。"))

    return checks, nx_root


# ---------------------------------------------------------------------------
# 模型文件检查
# ---------------------------------------------------------------------------
def check_model(model_path):
    checks = []
    if not model_path:
        checks.append(Check("模型文件", FAIL, "还没有选择模型",
                            "在上方「模型库」里双击一个 .rvt 文件。"))
        return checks

    if not os.path.isfile(model_path):
        checks.append(Check("模型文件", FAIL, "文件不存在：{0}".format(model_path),
                            "确认模型库目录与文件名，中文路径没问题。"))
        return checks

    size = os.path.getsize(model_path)
    if size == 0:
        checks.append(Check("模型文件", FAIL, "文件大小为 0：{0}".format(model_path),
                            "文件已损坏，从备份或 Revit 重新导出。"))
        return checks

    mb = round(size / 1048576.0, 2)
    try:
        with open(model_path, "rb") as fh:
            head = fh.read(2)
    except OSError as exc:
        checks.append(Check("模型文件", FAIL, "无法读取：{0!r}".format(exc),
                            "检查文件权限，或它是否被 Revit 独占锁定。"))
        return checks

    if head == b"\x89P":
        checks.append(Check("模型文件", WARN,
                            "扩展名是 .rvt，但内容像是 PNG 图片（{0} MB）".format(mb),
                            "检查是不是把截图误存成了 .rvt。"))
    else:
        checks.append(Check("模型文件", OK, "{0}（{1} MB）".format(
            os.path.basename(model_path), mb), value=model_path))

    return checks


# ---------------------------------------------------------------------------
# 输出目录规划（自动生成独立目录）
# ---------------------------------------------------------------------------
def _safe_name(text, fallback="model"):
    text = re.sub(r"[\\/:*?\"<>|]", "_", text or "").strip().strip(".")
    return text or fallback


def plan_output_dir(output_root, model_path, suffix=""):
    """
    为一次导入生成【独立】输出目录。返回 (dir, checks)。

    为什么必须独立且为空：实测 NX 在目标文件名已存在时会改名另存，
    而改名那一批可能整批创建失败（168/173 个部件的几何没导进去）。
    """
    checks = []

    if not output_root:
        output_root = os.path.join(
            os.path.expanduser("~"), "NXRevitImport")
        checks.append(Check("输出根目录", FIXED, "未设置，自动使用 {0}".format(output_root),
                            "可在界面「输出根目录」里改成空间更大的盘。"))

    if not os.path.isdir(output_root):
        try:
            os.makedirs(output_root)
            checks.append(Check("输出根目录", FIXED, "已创建 {0}".format(output_root)))
        except OSError as exc:
            checks.append(Check("输出根目录", FAIL,
                                "无法创建 {0}：{1!r}".format(output_root, exc),
                                "换一个可写目录，或检查盘符是否存在。"))
            return None, checks

    stem = _safe_name(os.path.splitext(os.path.basename(model_path or ""))[0])
    base = stem + (("_" + suffix) if suffix else "")

    # 目录名带递增序号，保证不覆盖历史结果
    n = 1
    while True:
        candidate = os.path.join(output_root, base if n == 1 else "{0}_{1}".format(base, n))
        if not os.path.exists(candidate):
            break
        n += 1

    try:
        os.makedirs(candidate)
    except OSError as exc:
        checks.append(Check("输出目录", FAIL, "无法创建 {0}：{1!r}".format(candidate, exc),
                            "换一个可写目录。"))
        return None, checks

    empty = not os.listdir(candidate)
    checks.append(Check("输出目录", FIXED if n > 1 else OK,
                        "已新建独立空目录：{0}".format(candidate),
                        "" if n == 1 else "同名目录已存在，已自动改用带序号的新目录，避免覆盖与改名失败。"))

    # 磁盘空间：实测 16MB 模型产出约 15MB，留 20 倍余量且不低于 1GB
    try:
        usage = shutil.disk_usage(candidate)
        free_gb = usage.free / (1024.0 ** 3)
        need = 1.0
        if model_path and os.path.isfile(model_path):
            need = max(1.0, os.path.getsize(model_path) / (1024.0 ** 3) * 20)
        need = min(need, 50.0)
        if free_gb < need:
            checks.append(Check(
                "磁盘空间", WARN,
                "{0} 剩余 {1:.2f} GB，建议至少 {2:.2f} GB".format(
                    os.path.splitdrive(candidate)[0] or candidate, free_gb, need),
                "换一个剩余空间更大的盘做输出根目录，否则导入可能中途失败。"))
        else:
            checks.append(Check("磁盘空间", OK,
                                "剩余 {0:.2f} GB".format(free_gb)))
    except OSError:
        pass

    return candidate, checks


def summarize(checks):
    """把一批 Check 汇总成 (是否可继续, 文本)。"""
    blocking = [c for c in checks if c.blocking]
    lines = [c.as_line() for c in checks]
    return (len(blocking) == 0), "\n".join(lines)
