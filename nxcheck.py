# -*- coding: utf-8 -*-
"""
NX ← Revit 导入产物的核对核心（可被 GUI 与命令行复用）。

纯标准库，不依赖 NX。用系统 Python 即可运行。

判据说明（这条很重要，是实测得来的）：
    NX 把新建部件留在内存里，直到批处理进程【真正退出】才写盘，
    比日志脚本的 main() 返回晚约 26 秒（时间戳证据：
    23:49:48 脚本结束 / 23:50:14 .prt 与 (null).log 才出现）。
    因此在 NX 进程内核对产物必然为 0，唯一可靠的判据是：
      a) 输出目录里的 .prt 产物
      b) NX-Revit 翻译器自己写的 (null).log 里的错误/警告计数
"""
import os
import re

# ---------------------------------------------------------------------------
# 翻译器日志解析
# ---------------------------------------------------------------------------
_RE_ERR = re.compile(r"Number of Error Messages\D+(\d+)")
_RE_WARN = re.compile(r"Number of Warning Messages\D+(\d+)")
_RE_ELEMS = re.compile(r"Number of elements to translate\D+(\d+)")
_RE_GEOM = re.compile(r"ImportGeometryAs\.+: (\S+)")
_RE_CSYS = re.compile(r"RevitProjectCSYS\.+: (\S+)")
_RE_UNIT = re.compile(r"Convert_REVIT_Files_To\.+: (\S+)")
_RE_WARNLINE = re.compile(r"^\s*WARNING:\s*(?:\[([^\]]*)\]\s*)?(.*)$", re.M)
_RE_ERRBODY = re.compile(r"^\s*ERROR:\s*(?:\[([^\]]*)\]\s*)?(.*)$", re.M)


def parse_translator_log(text, source=""):
    """
    解析 NX-Revit 翻译器日志。多轮导入会追加到同一文件，
    所以各项计数一律取【最后一次】出现的值。
    返回 dict；无法解析时 errors/warnings 为 None。

    warning_details / error_details 会带上出问题的部件完整路径 ——
    这是定位「到底哪个 Revit 构件没导进来」的唯一线索。
    """
    def last_int(rx):
        got = rx.findall(text)
        return int(got[-1]) if got else None

    def last_str(rx):
        got = rx.findall(text)
        return got[-1] if got else None

    def details(rx):
        return [{"path": p.strip(), "message": m.strip()}
                for p, m in rx.findall(text)]

    warn_details = details(_RE_WARNLINE)
    err_details = details(_RE_ERRBODY)

    return {
        "source": source,
        "errors": last_int(_RE_ERR),
        "warnings": last_int(_RE_WARN),
        "elements": last_int(_RE_ELEMS),
        "geometry_as": last_str(_RE_GEOM),
        "csys": last_str(_RE_CSYS),
        "unit": last_str(_RE_UNIT),
        "warning_details": warn_details,
        "error_details": err_details,
        "warning_messages": [d["message"] for d in warn_details],
        "error_messages": [d["message"] for d in err_details],
    }


def failed_parts(report, output_dir):
    """
    从翻译器报告的明细里提取失败部件，并回报它们在盘上的实际大小。
    用来区分「文件压根没建」与「文件建了但只是个空壳」。
    """
    out = []
    for d in list(report.get("warning_details", [])) + \
            list(report.get("error_details", [])):
        path = d.get("path") or ""
        name = os.path.basename(path) if path else "(未指明部件)"
        size = None
        for cand in (path, os.path.join(output_dir, name) if name else None):
            if not cand:
                continue
            try:
                if os.path.isfile(cand):
                    size = os.path.getsize(cand)
                    break
            except OSError:
                pass
        out.append({"name": name, "size": size, "message": d.get("message", "")})
    return out


def _read_text(path):
    """
    读文本，自动处理编码。

    NX 的翻译器日志用本地代码页（中文 Windows 为 GBK）写，而且实测同一
    文件里可能混有无法严格解码的字节：utf-8 与 gbk 的【严格】模式都会失败，
    于是旧的 latin-1 兜底把中文路径变成乱码 —— '常规模型' 会显示成
    '³£¹æÄ£ÐÍ'，进而让按路径做的文件存在性判断全部失效。
    所以最后一步改用 GBK 宽容模式：中文能正确还原，个别坏字节替换掉。
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("gbk", errors="replace")


# ---------------------------------------------------------------------------
# 目录扫描
# ---------------------------------------------------------------------------
def scan_dir(output_dir):
    """扫描输出目录，返回产物统计。"""
    info = {
        "exists": False,
        "entries": [],
        "prt": [],
        "logs": [],
        "total_bytes": 0,
        "suffixed": [],      # 带 _1/_2 后缀的部件
        "unreadable": [],
    }
    if not os.path.isdir(output_dir):
        return info

    info["exists"] = True
    try:
        names = os.listdir(output_dir)
    except OSError as exc:
        info["unreadable"].append("无法列出目录: {0!r}".format(exc))
        return info

    suffixed_rx = re.compile(r"_\d+\.prt$", re.IGNORECASE)
    for name in sorted(names):
        full = os.path.join(output_dir, name)
        if not os.path.isfile(full):
            continue
        info["entries"].append(name)
        low = name.lower()
        if low.endswith(".prt"):
            info["prt"].append(name)
            try:
                info["total_bytes"] += os.path.getsize(full)
            except OSError:
                pass
            if suffixed_rx.search(name):
                info["suffixed"].append(name)
        elif low.endswith(".log"):
            info["logs"].append(name)

    info["prt"].sort()
    info["logs"].sort()
    return info


def newest_mtime(output_dir):
    """目录内最新文件的 mtime；目录为空或无权限时返回 None。"""
    best = None
    try:
        for name in os.listdir(output_dir):
            full = os.path.join(output_dir, name)
            if os.path.isfile(full):
                try:
                    t = os.path.getmtime(full)
                except OSError:
                    continue
                if best is None or t > best:
                    best = t
    except OSError:
        return None
    return best


# ---------------------------------------------------------------------------
# 综合判定
# ---------------------------------------------------------------------------
class Report(object):
    """核对结果。ok 表示几何完整可用；lines 是给人看的说明；hints 是修复建议。"""

    def __init__(self, ok, verdict, lines=None, hints=None, data=None):
        self.ok = ok
        self.verdict = verdict
        self.lines = lines or []
        self.hints = hints or []
        self.data = data or {}

    def text(self):
        out = [self.verdict]
        out.extend(self.lines)
        if self.hints:
            out.append("")
            out.append("怎么修：")
            for h in self.hints:
                out.append("  - " + h)
        return "\n".join(out)


def analyze(output_dir):
    """
    综合判定一次导入的结果。

    判据优先级：
      翻译器错误 > 0                     -> 失败
      翻译器错误 = 0 且警告 = 0 且有产物 -> 成功
      翻译器错误 = 0 但警告 > 0          -> 不完整（几何没进去）
      无翻译器日志                       -> 只能确认产物存在，无法确认几何
    """
    scan = scan_dir(output_dir)
    lines = []
    hints = []

    mb = round(scan["total_bytes"] / 1048576.0, 2)
    lines.append("输出目录：{0}".format(output_dir))

    if not scan["exists"]:
        return Report(False, "[失败] 输出目录不存在", lines,
                      ["确认 --output-dir 的路径写对了，且盘符存在。"],
                      scan)

    lines.append("部件文件：{0} 个，{1} MB".format(len(scan["prt"]), mb))

    if not scan["prt"]:
        lines.append("（目录里没有任何 .prt）")
        hints.append("导入刚结束不到 1 分钟时，NX 可能还没落盘 —— 稍等再核对一次。")
        hints.append("若始终没有产物，看 src\\nx_revit_import.log 里的异常回溯。")
        hints.append("常见原因：NX 未装 Revit 数据交换(DEX)模块或未授权，"
                     "此时 CreateRevitImporter() 会返回 None。")
        return Report(False, "[失败] 输出目录里没有部件文件", lines, hints, scan)

    # 命名后缀
    if scan["suffixed"]:
        lines.append("命名警告：有 {0} 个部件带 _N 后缀".format(len(scan["suffixed"])))
        hints.append("带 _N 后缀说明导入时目录里已存在同名部件，NX 改名另存了。")
        hints.append("实测改名那一批可能整批失败 —— 请换一个【全新的空目录】重导。")
    else:
        lines.append("命名检查：干净，无 _N 后缀")

    # 翻译器日志
    reports = []
    for log_name in scan["logs"]:
        text = _read_text(os.path.join(output_dir, log_name))
        if not text:
            continue
        rep = parse_translator_log(text, log_name)
        if rep["errors"] is not None or rep["warnings"] is not None:
            reports.append(rep)

    if not reports:
        lines.append("翻译器日志：未找到可解析的报告")
        hints.append("只能确认产物存在，无法确认几何是否完整。")
        hints.append("请在 NX 里打开顶层 <模型名>_rvt.prt 目视确认。")
        return Report(True, "[未知] 有产物，但无翻译器日志可判读", lines, hints, scan)

    rep = reports[-1]
    lines.append("翻译器日志：{0}".format(rep["source"]))
    if rep["errors"] is not None:
        lines.append("  错误消息 = {0}".format(rep["errors"]))
    if rep["warnings"] is not None:
        lines.append("  警告消息 = {0}".format(rep["warnings"]))
    if rep["elements"] is not None:
        lines.append("  Revit 构件数 = {0}".format(rep["elements"]))
    for key, label in (("geometry_as", "几何精度"), ("csys", "坐标对齐"), ("unit", "输出单位")):
        if rep[key]:
            lines.append("  {0} = {1}".format(label, rep[key]))

    n_err = rep["errors"] or 0
    n_warn = rep["warnings"] or 0
    geom = (rep["geometry_as"] or "").upper()

    if n_err > 0:
        lines.append("")
        lines.append("前几条错误：")
        for m in rep["error_messages"][:5]:
            lines.append("  " + m)
        hints.append("翻译器报告了 {0} 条错误。先看上面的错误原文定位问题构件。".format(n_err))
        hints.append("若错误集中在某类构件，考虑用 --no-attributes 或 --no-hierarchy 简化后重试。")
        hints.append("确认 NX 的 Revit 数据交换(DEX)模块已授权。")
        return Report(False, "[失败] 翻译器报告 {0} 条错误".format(n_err), lines, hints, scan)

    if n_warn > 0:
        fails = failed_parts(rep, output_dir)
        n_parts = len(scan["prt"])
        ratio = (float(n_warn) / n_parts) if n_parts else 1.0
        # 区分「个别构件失败」与「系统性问题」：比例高或绝对数大才算系统性
        systemic = ratio >= 0.30 or n_warn >= 50

        lines.append("")
        if fails:
            lines.append("失败部件明细（{0} 个，占已生成部件的 {1:.1f}%）：".format(
                len(fails), ratio * 100.0))
            for f in fails[:15]:
                size = "{0} 字节".format(f["size"]) if f["size"] is not None else "盘上不存在"
                lines.append("  {0}   [{1}]".format(f["name"], size))
            if len(fails) > 15:
                lines.append("  ... 另有 {0} 个".format(len(fails) - 15))
        else:
            lines.append("翻译器报了 {0} 条警告，但日志里没给出具体部件名。".format(n_warn))
        lines.append("")
        lines.append("含义：部件文件建出来了，但往里导入几何的 feature 创建失败 ——")
        lines.append("这些部件是空壳，在 NX 里没有几何。文件数与错误数都正常，"
                     "所以光看数字发现不了。")

        if systemic:
            hints.append("失败面很大（占 {0:.0f}%），属于系统性问题。".format(ratio * 100.0))
            if geom.startswith("LIGHT"):
                hints.append("几何精度是 Lightweight，实测对复杂模型会大面积失败"
                             "（某模型 173 个里 168 个失败）。请改用 Precise 重导。")
            else:
                hints.append("几何精度已是 Precise，逐项排查：")
                hints.append("  1) 输出目录必须是全新的空目录（有无 _N 后缀残留）")
                hints.append("  2) NX 的 Revit 数据交换(DEX)模块是否已授权")
                hints.append("  3) 目标磁盘剩余空间是否充足")
        else:
            hints.append("这是【个别构件】失败，不是系统性问题，模型其余部分可用。")
            hints.append("上面列出的部件名直接来自 Revit 的族名与类型名，"
                         "可以在 Revit 里按名字找到对应构件。")
            hints.append("注意：把失败的名字互相对比，找共同的那一段"
                         "（族名或类型名）—— 相同的往往就是要去 Revit 里检查的那个族。")
            hints.append("常见原因是这几个族/类型的几何形态 NX 转换器处理不了："
                         "含导入的 CAD(DWG) 几何、自相交或退化曲面、零厚度面。")
            hints.append("同类别里其它构件往往是成功的，所以问题出在具体的族上，"
                         "不是整个类别。可先在 Revit 里把它们的几何炸开或用标准族重建后重导；"
                         "若这些构件不影响后续用途（例如只是装饰），直接忽略也可以。")

        return Report(False, "[不完整] 错误 0，但 {0} 个部件几何没进去".format(n_warn),
                      lines, hints, scan)

    lines.append("")
    lines.append("几何精度、坐标对齐、单位均已由 NX 翻译器确认生效。")
    return Report(True, "[成功] 错误 0、警告 0，几何完整", lines, hints, scan)


def fix_hint_for_log(script_log_path):
    """
    读导入脚本自己写的日志（UTF-8），把常见异常翻译成可操作的建议。
    返回 (摘要行列表, 建议行列表)。
    """
    lines, hints = [], []
    text = _read_text(script_log_path)
    if not text:
        return ["（没有找到脚本日志：{0}）".format(script_log_path)], \
               ["说明导入脚本没跑到写日志那一步，或路径不对。"]

    tail = text.strip().splitlines()
    for ln in tail[-40:]:
        lines.append(ln)

    joined = text
    if "CreateRevitImporter() 返回 None" in joined:
        hints.append("NX 缺 Revit 数据交换(DEX)模块或未授权 —— 检查 NX 安装项与许可。")
    if "没有工作部件" in joined:
        hints.append("import_to=WorkPart 但当前没有工作部件。批处理会话只能用 NewPart；"
                     "想在同一个部件里叠多专业，需要在已打开的 NX 里播日志。")
    if "参数解析失败" in joined:
        hints.append("命令行参数写错了，看上面的回溯里 ValueError 的内容。")
    if "Traceback" in joined:
        hints.append("出现了未处理异常，回溯已在上面的日志里，按最末一行定位。")
    if "找不到 Revit 文件" in joined:
        hints.append("模型文件路径不存在或不可读，检查路径与权限。")
    return lines, hints
