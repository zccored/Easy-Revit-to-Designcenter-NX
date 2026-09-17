# -*- coding: utf-8 -*-
"""
NX <- Revit 模型联动导入（NXOpen Python）

本文件所有 API 名称、属性名、枚举常量名均逐条核对自 NX 官方类型存根：
    <NX_HOME>\\UGOPEN\\pythonStubs\\NXOpen\\__init__.pyi
以及运行时模块 <NX_HOME>\\NXBIN\\python\\NXOpen.pyd。
未使用任何记忆/推测的签名。

运行方式（必须由 NX 自带的 run_journal 启动，NXOpen.pyd 只能在 NX 进程内加载）：

    "<NX_HOME>\\NXBIN\\run_journal.exe" -nx import_revit.py -args --rvt "D:\\bim\\model.rvt"

一般不用直接调它，用仓库根目录的 start_gui.bat（图形界面）或 run_import.bat。

不带参数运行时，使用本文件顶部 CONFIG 区的配置。

关于「模型联动」的四个关键开关（详见各处注释）：
    ProjectCSYS  -> 决定 NX 与 Revit 的坐标是否对得上（最容易踩的坑）
    ProcessAttributes -> 是否把 Revit 构件属性带进 NX
    LevelHierarchy -> 是否按 Revit 标高组织装配树
    ProcessLinkedModels -> 是否把链接模型合并进同一模型
"""

import os
import re
import sys
import time
import traceback

import NXOpen


# ============================================================================
# 配置区 —— 不使用命令行参数时读这里
# ============================================================================
CONFIG = {
    # 要导入的 .rvt 文件。可写多个：按顺序导入到同一个工作部件，即多专业模型联动。
    # 路径用原始字符串 r"..." 避免反斜杠转义问题。
    #
    # 留空 = 必须用 --rvt 传（图形界面会自动填，无需手改这里）。
    # 例： "rvt_files": [r"C:\\projects\\tower_a.rvt", r"C:\\projects\\tower_b.rvt"],
    "rvt_files": [],
    # NewPart  = 新建部件（run_import.bat 走的批处理会话只能用这个）
    # WorkPart = 导入当前工作部件（多专业叠到同一个部件里，实现真联动）
    #
    # 注意：批处理会话里没有任何打开的部件，session.Parts.Work 为 None，
    # 所以 WorkPart 在 run_import.bat 这条路上【必然中止】。它只适用于
    # 在已打开的交互式 NX 里播日志的场景。因此默认取 NewPart。
    "import_to": "NewPart",
    # Precise     = B-rep 精确实体，可继续建模/布尔运算
    # Lightweight = 轻量化面片，看着更省资源
    #
    # 实测结论（同一个 16MB Revit 模型，各导入一次，看 NX 翻译器自己的日志）：
    #     Lightweight -> 173 个部件，错误 0，【警告 168】  168 个部件的
    #                    "Failed to create import feature"，即几何没导进去
    #     Precise     -> 173 个部件，错误 0，【警告 0】    全部正常
    # 所以默认必须是 Precise。Lightweight 会静默产出缺几何的部件，
    # 在 NX 里看不出来，是最坑的一类失败。
    "geometry_as": "Precise",
    "part_unit": "Millimeter",
    # 坐标对齐（联动核心）：
    #   SurveyPoint      = 用 Revit 测量点/共享坐标 —— 跨专业、跨软件对齐应选它
    #   ProjectBasePoint = 用项目基点
    #   Internal         = 用 Revit 内部原点（NX 默认值，通常会导致模型错位）
    #   ActiveProjectLOC = 用当前项目位置
    "project_csys": "SurveyPoint",
    "process_attributes": True,      # 保留 Revit 类型/实例属性 -> NX 属性
    "level_hierarchy": True,         # 按标高生成装配树层级
    "process_linked_models": True,   # 合并链接模型
    "messages": "Informational",     # NotSet/Informational/Warning/Error/Debug/All
    "show_info_window": False,
    "import_to_teamcenter": False,
    "settings_file": None,           # 可选：revit 导入定义文件
    "output_file": None,             # 可选：仅 NewPart 时有意义
    # 导入产物的落盘目录。None = 自动取「.rvt 同级目录\nx_import_<模型名>」。
    # 必须显式给：NX 在未指定输出位置时会把每个新建部件写到进程当前工作目录，
    # 首次试跑就因此把 173 个 .prt 灌进了一个无关的工程目录。
    "output_dir": None,
}


# ============================================================================
# 枚举合法值（逐条核对自 __init__.pyi，用于参数校验与报错提示）
# ============================================================================
IMPORT_TO_VALUES = ("WorkPart", "NewPart")
GEOMETRY_AS_VALUES = ("Precise", "Lightweight")
PART_UNIT_VALUES = ("NotSet", "Micrometer", "Millimeter", "Inch", "Meter")
PROJECT_CSYS_VALUES = ("Internal", "ActiveProjectLOC", "ProjectBasePoint", "SurveyPoint")
MESSAGES_VALUES = ("NotSet", "Informational", "Warning", "Error", "Debug", "All")


def _enum(enum_cls, member_name, valid_names, label):
    """按名字取 NXOpen 枚举成员，取不到时抛出带合法值清单的错误。"""
    try:
        return getattr(enum_cls, member_name)
    except AttributeError:
        raise ValueError(
            "{0} 的取值 '{1}' 无效，合法值：{2}".format(label, member_name, ", ".join(valid_names))
        )


# ============================================================================
# 输出（日志文件 + ListingWindow；两者都不可用时退回 stdout）
# ============================================================================
def _script_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return None


def _log_path():
    """挑一个可写的日志路径：优先脚本同目录，退回 %TEMP%。"""
    for base in (_script_dir(), os.environ.get("TEMP"), os.environ.get("TMP")):
        if not base:
            continue
        p = os.path.join(base, "nx_revit_import.log")
        try:
            with open(p, "a", encoding="utf-8"):
                pass
            return p
        except Exception:
            continue
    return None


def _count_dir(dirpath):
    """目录内文件数；失败时把异常原文带出来，不要吞掉。"""
    try:
        return len(os.listdir(dirpath))
    except Exception as exc:
        return "listdir 失败: {0!r}".format(exc)


def _translator_report(dirpath):
    """
    读 NX-Revit 翻译器自己写出的日志，取「错误/警告消息数」。

    这是比数文件更权威的成功信号：翻译器会在日志末尾给出
        INFO: Number of Error Messages..........: 0
        INFO: Number of Warning Messages........: 168
    实测即使导入成功，Commit() 返回值与 GetCommittedObjects() 都是空的，
    而文件落盘时机又不受控，所以以这里为准。

    返回 [(日志文件名, 错误数, 警告数), ...]
    """
    found = []
    try:
        names = os.listdir(dirpath)
    except Exception:
        return found
    for name in sorted(names):
        if not name.lower().endswith(".log"):
            continue
        path = os.path.join(dirpath, name)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except Exception:
            continue
        errs = re.findall(r"Number of Error Messages\D+(\d+)", text)
        warns = re.findall(r"Number of Warning Messages\D+(\d+)", text)
        if errs or warns:
            found.append((
                name,
                int(errs[-1]) if errs else None,
                int(warns[-1]) if warns else None,
            ))
    return found


class _Log(object):
    """
    三路输出：日志文件 + NX ListingWindow + stdout。

    加日志文件是因为 run_journal 由 NX 接管进程，它的 stdout 未必能可靠回收，
    而「到底哪一步失败了」必须留证据。
    """

    def __init__(self):
        self._lw = None
        self._fh = None
        path = _log_path()
        if path:
            try:
                self._fh = open(path, "w", encoding="utf-8")
            except Exception:
                self._fh = None
        try:
            self._lw = NXOpen.Session.GetSession().ListingWindow
            if not self._lw.IsOpen:
                self._lw.Open()
        except Exception:
            self._lw = None

    def write(self, msg):
        text = str(msg)
        if self._fh is not None:
            try:
                self._fh.write(text + "\n")
                self._fh.flush()
            except Exception:
                self._fh = None
        if self._lw is not None:
            try:
                self._lw.WriteLine(text)
                return
            except Exception:
                self._lw = None
        print(text)

    def close(self):
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None


# ============================================================================
# 输出目录与产物比对
# ============================================================================
def _resolve_output_dir(rvt_path, opt):
    """
    决定导入产物的落盘目录。

    为什么必须显式指定：NX 的 Revit 导入在未给出输出位置时，会把每个新建部件
    都写到「进程当前工作目录」。首次试跑就因此把 173 个 .prt 灌进了一个
    与此事完全无关的工程目录。所以默认也绝不留给 CWD。
    """
    explicit = opt.get("output_dir")
    if explicit:
        return os.path.abspath(explicit)
    stem = os.path.splitext(os.path.basename(rvt_path))[0]
    parent = os.path.dirname(os.path.abspath(rvt_path))
    return os.path.join(parent, "nx_import_{0}".format(stem))


def _scan_outputs(dirpath, since_ts):
    """
    列出 dirpath 下「修改时间不早于 since_ts」的文件。

    为什么按时间而不是按「前后差集」：
      1) 实测在 NX 内嵌 Python 里，差集比对本应工作却返回了空集，
         导致一次成功的导入被误判为「未产生文件」；
      2) 更重要 —— 重复导入同一个模型到同一目录时文件名不变、内容被覆盖，
         差集恒为空，正常重导也会被误判为失败。
    按 mtime 判定同时覆盖「新建」和「覆盖重写」两种情形。
    """
    out = []
    try:
        names = os.listdir(dirpath)
    except Exception:
        return out
    for name in names:
        full = os.path.join(dirpath, name)
        try:
            if os.path.isfile(full) and os.path.getmtime(full) >= since_ts:
                out.append(full)
        except Exception:
            continue
    return sorted(out)


# ============================================================================
# 核心：单次 Revit 导入
# ============================================================================
def import_revit(rvt_path, opt, log):
    """
    把单个 .rvt 导入 NX，返回 NXOpen.NXObject 列表（GetCommittedObjects）。

    注意：官方存根明确写着 RevitImporter「NULL object will be returned from Commit()」，
    所以 Commit() 的返回值按 None 处理，不要拿它当导入结果用。
    """
    if not os.path.isfile(rvt_path):
        raise IOError("找不到 Revit 文件：{0}".format(rvt_path))

    out_dir = _resolve_output_dir(rvt_path, opt)
    try:
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
    except Exception as exc:
        raise IOError("无法创建输出目录 {0}：{1}".format(out_dir, exc))
    if not os.path.isdir(out_dir):
        raise IOError("输出目录不可用：{0}".format(out_dir))

    log.write("    输出目录 = {0}".format(out_dir))
    # 减 2 秒留余量，避免文件系统时间粒度/时钟抖动造成漏判
    start_ts = time.time() - 2.0

    session = NXOpen.Session.GetSession()
    dex_manager = session.DexManager                      # @property

    prev_cwd = os.getcwd()
    builder = None
    try:
        # 实测依据：不指定输出位置时，NX 把新建的每个部件都写到「进程当前工作目录」。
        # 所以这里先把 CWD 切到专用输出目录，导入结束再切回。
        os.chdir(out_dir)

        builder = dex_manager.CreateRevitImporter()       # -> RevitImporter
        if builder is None:
            # 常见原因：未安装 NX 的 Revit 数据交换模块，或该模块未授权
            raise RuntimeError(
                "DexManager.CreateRevitImporter() 返回 None。"
                "请确认本机 NX 已安装 Revit 数据交换(DEX)模块并具有对应许可。"
            )

        # ---- BaseImporter 层：文件来源与单位 ----
        # 注意 NX 自家 API 在这里不统一：Mode 是 GetMode()/SetMode() 方法，
        # 而 InputFile / OutputFile / PartUnit 是属性。
        # （依据存根 __init__.pyi 第 2464 行 GetMode、第 2470 行 SetMode）
        builder.SetMode(NXOpen.BaseImporter.Mode.NativeFileSystem)
        builder.InputFile = rvt_path
        builder.PartUnit = _enum(
            NXOpen.BaseImporter.PartUnitOption, opt["part_unit"], PART_UNIT_VALUES, "part_unit"
        )
        if opt.get("output_file"):
            builder.OutputFile = opt["output_file"]

        # ---- RevitImporter 层 ----
        # 这是「导入」而不是「打开文件」，官方对该开关的说明就是 set this to false if doing file import
        builder.FileOpenFlag = False

        builder.ImportTo = _enum(
            NXOpen.RevitImporter.ImportToOption, opt["import_to"], IMPORT_TO_VALUES, "import_to"
        )
        builder.ImportGeometryAs = _enum(
            NXOpen.RevitImporter.ImportGeometryAsEnum,
            opt["geometry_as"], GEOMETRY_AS_VALUES, "geometry_as",
        )
        builder.RevitProjectCSYS = _enum(
            NXOpen.RevitImporter.RevitProjectCSYSEnum,
            opt["project_csys"], PROJECT_CSYS_VALUES, "project_csys",
        )
        builder.Messages = _enum(
            NXOpen.RevitImporter.MessageEnum, opt["messages"], MESSAGES_VALUES, "messages"
        )

        builder.ProcessAttributes = bool(opt["process_attributes"])
        builder.ProcessLevelBasedHierarchy = bool(opt["level_hierarchy"])
        builder.ProcessLinkedModels = bool(opt["process_linked_models"])
        builder.ImportToTeamcenter = bool(opt["import_to_teamcenter"])
        builder.ShowInformationWindowFlag = bool(opt["show_info_window"])

        if opt.get("settings_file"):
            builder.SettingsFile = opt["settings_file"]

        log.write(
            "      几何={0}  坐标={1}  单位={2}  属性={3}  层级={4}  链接={5}".format(
                opt["geometry_as"], opt["project_csys"], opt["part_unit"],
                opt["process_attributes"], opt["level_hierarchy"],
                opt["process_linked_models"],
            )
        )
        log.write("    导入中……（Revit 项目会拆成大量部件，可能耗时较久）")

        # RevitImporter 的 Commit() 官方说明就是「NULL object will be returned」，
        # 且实测即使导入成功 GetCommittedObjects() 也返回 0 个。
        # 因此这两个返回值都【不能】作为成功依据。
        builder.Commit()
        builder.GetCommittedObjects()

        # 实测现象：Commit() 一返回就去列目录，看不到任何文件；等整个日志进程
        # 退出之后文件才出现在磁盘上。怀疑 NX 把新建部件攒到会话收尾才刷盘，
        # 所以这里显式保存一次，并打印保存前后的文件数用于确认。
        log.write("    提交后即时可见文件数 = {0}".format(_count_dir(out_dir)))
        try:
            ok_save, save_status = session.Parts.SaveAll()
            log.write("    Parts.SaveAll() -> {0}".format(ok_save))
            if not ok_save and save_status is not None:
                for line in str(save_status).splitlines()[:10]:
                    log.write("      " + line)
        except Exception as exc:
            log.write("    Parts.SaveAll() 异常: {0!r}".format(exc))
        log.write("    保存后可见文件数 = {0}".format(_count_dir(out_dir)))

    finally:
        try:
            os.chdir(prev_cwd)
        except Exception:
            pass
        if builder is not None:
            # NXOpen Builder 必须销毁，否则会话里会残留构建器
            try:
                builder.Destroy()
            except Exception:
                pass

    produced = _scan_outputs(out_dir, start_ts)
    report = _translator_report(out_dir)
    for name, errs, warns in report:
        log.write("    翻译器日志 {0}：错误={1}  警告={2}".format(name, errs, warns))
    log.write("    产物核对：mtime 晚于本次开始的部件 = {0} 个".format(len(produced)))
    return produced, report


def link_models(opt=None, log=None):
    """
    多模型联动入口：把 CONFIG/传入配置里的多个 .rvt 依次导入同一工作部件，
    共用同一坐标系，从而在 NX 里形成「一套联动模型」。

    返回 (成功数, 失败清单)。
    """
    opt = opt or CONFIG
    if log is None:
        log = _Log()
    files = opt.get("rvt_files") or []

    log.write("=" * 68)
    log.write("NX <- Revit 模型联动导入")
    log.write("=" * 68)

    if not files:
        log.write("没有配置任何 .rvt 文件。请编辑脚本顶部 CONFIG['rvt_files']，")
        log.write('或用 --rvt "路径\\模型.rvt" 传入。')
        return 0, []

    session = NXOpen.Session.GetSession()
    work = session.Parts.Work
    if opt["import_to"] == "WorkPart" and work is None:
        log.write("[中止] import_to=WorkPart 但当前没有工作部件。")
        log.write("       请在 NX 里先打开/新建一个部件，或改用 --import-to NewPart。")
        return 0, [(files[0], "没有工作部件")]

    ok, failed = 0, []
    for idx, path in enumerate(files, 1):
        log.write("")
        log.write("[{0}/{1}] {2}".format(idx, len(files), os.path.basename(path)))
        try:
            new_files, report = import_revit(path, opt, log)
            n = len(new_files)

            # 以 NX-Revit 翻译器自己的错误计数为权威判据
            errs = None
            for _name, e, _w in report:
                if e is not None:
                    errs = e if errs is None else max(errs, e)

            if errs is not None:
                if errs > 0:
                    failed.append((path, "翻译器报告 {0} 条错误消息".format(errs)))
                    log.write("    [失败] 翻译器报告 {0} 条错误消息。".format(errs))
                    continue
                total = 0
                for f in new_files:
                    try:
                        total += os.path.getsize(f)
                    except Exception:
                        pass
                log.write("    导入完成：翻译器错误 0 条；本次扫描到新增/重写部件 {0} 个，{1} MB".format(
                    n, round(total / 1048576.0, 2)))
                if n == 0:
                    log.write("    注：文件数扫描为 0 不改变结论 —— NX 落盘时机不受脚本控制，")
                    log.write("        翻译器日志才是权威依据，请到输出目录核对产物。")
                for f in new_files[:6]:
                    log.write("      + {0}".format(os.path.basename(f)))
                ok += 1
            else:
                # 实测：NX 直到批处理进程退出（即本脚本返回【之后】）才把部件写盘，
                # 翻译器日志也是同一时刻才生成。所以脚本内几乎必然看不到它们。
                # 因此绝不能把「扫描不到文件」当成失败 —— 那是假警报，
                # 我在这上面连错判了 4 次，证据见 23:49:48 脚本结束 / 23:50:14 文件落盘。
                if n == 0:
                    log.write("    已提交。脚本内暂时看不到产物，这是正常现象 ——")
                    log.write("    实测 NX 在进程退出后才落盘，比本脚本返回晚约 26 秒。")
                    log.write("    请稍后用 verify_output.py 核对输出目录与翻译器日志。")
                else:
                    log.write("    导入完成，脚本内可见新增/重写部件 {0} 个".format(n))
                ok += 1
        except Exception as exc:
            failed.append((path, str(exc)))
            log.write("    失败：{0}".format(exc))

    # 汇总
    work = session.Parts.Work
    log.write("")
    log.write("-" * 68)
    log.write("成功 {0} / 共 {1}".format(ok, len(files)))
    if work is not None:
        log.write("当前工作部件：{0}".format(work.Name))
    if failed:
        log.write("失败清单：")
        for path, msg in failed:
            log.write("  - {0}  ->  {1}".format(path, msg))
    log.write("-" * 68)
    return ok, failed


# ============================================================================
# 命令行解析（run_journal 会透传参数；解析不可靠时自动回落到 CONFIG）
# ============================================================================
class _ShowHelp(Exception):
    """--help 用。不用 sys.exit：SystemExit 继承自 BaseException，
    main() 里的 except Exception 抓不到它，会直接漏进 NX 的日志处理器。"""


def _parse_args(argv):
    opt = dict(CONFIG)
    # dict(CONFIG) 是浅拷贝：opt["rvt_files"] 与 CONFIG["rvt_files"] 是同一个 list。
    # 所以命令行给的 --rvt 必须先单独收集、最后整体替换，否则会往 CONFIG 里追加，
    # 把 CONFIG 的占位文件也一起导进去，并且永久污染 CONFIG。
    cli_rvt = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--rvt", "--import-to", "--geometry-as", "--part-unit",
                 "--project-csys", "--messages", "--settings-file", "--output-file",
                 "--output-dir"):
            if i + 1 >= len(argv):
                raise ValueError("{0} 缺少取值".format(a))
            v = argv[i + 1]
            key = {
                "--rvt": "rvt_files", "--import-to": "import_to",
                "--geometry-as": "geometry_as", "--part-unit": "part_unit",
                "--project-csys": "project_csys", "--messages": "messages",
                "--settings-file": "settings_file", "--output-file": "output_file",
                "--output-dir": "output_dir",
            }[a]
            if key == "rvt_files":
                cli_rvt.append(v)
            else:
                opt[key] = v
            i += 2
            continue
        if a == "--no-attributes":
            opt["process_attributes"] = False; i += 1; continue
        if a == "--no-hierarchy":
            opt["level_hierarchy"] = False; i += 1; continue
        if a == "--no-linked-models":
            opt["process_linked_models"] = False; i += 1; continue
        if a == "--teamcenter":
            opt["import_to_teamcenter"] = True; i += 1; continue
        if a == "--show-window":
            opt["show_info_window"] = True; i += 1; continue
        if a in ("-h", "--help"):
            raise _ShowHelp()
        i += 1

    if cli_rvt:
        # 命令行给了 --rvt 就完全取代 CONFIG，而不是追加
        opt["rvt_files"] = cli_rvt
    return opt


def _print_help():
    print(__doc__)
    print("参数：")
    print('  --rvt PATH            要导入的 .rvt，可重复多次')
    print("  --import-to X         WorkPart | NewPart")
    print("  --geometry-as X       Precise | Lightweight")
    print("  --part-unit X         NotSet | Micrometer | Millimeter | Inch | Meter")
    print("  --project-csys X      Internal | ActiveProjectLOC | ProjectBasePoint | SurveyPoint")
    print("  --messages X          NotSet | Informational | Warning | Error | Debug | All")
    print("  --settings-file PATH  revit 导入定义文件")
    print("  --output-file PATH    (NewPart 时的新部件路径)")
    print("  --output-dir PATH     导入产物落盘目录（强烈建议显式指定）")
    print("  --no-attributes       不导入 Revit 构件属性")
    print("  --no-hierarchy        不按标高组织装配树")
    print("  --no-linked-models    不合并链接模型")
    print("  --teamcenter          导入到 Teamcenter")
    print("  --show-window         显示导入信息窗口")


def main(args=None):
    """
    NX 的 run_journal 约定（取自 run_journal.exe 的 -help 输出）：

        run_journal [ -nx ] <journal-file> [ -args .... ]
        -args ...  Pass the rest of the command line after this as
                   an array of strings to Main in the journal file

    所以这里必须能接收一个参数数组；同时兼容 run_journal 直接调 main() 的情况，
    那时退回 sys.argv。
    """
    if args is None:
        try:
            args = list(sys.argv[1:])
        except Exception:
            args = []

    log = _Log()
    log.write("参数: {0}".format(args))
    log.write("")

    try:
        opt = _parse_args(args)
    except _ShowHelp:
        _print_help()
        log.close()
        return 0
    except Exception:
        log.write("=" * 68)
        log.write("参数解析失败：")
        for line in traceback.format_exc().splitlines():
            log.write(line)
        log.write("=" * 68)
        log.close()
        return 1

    try:
        ok, failed = link_models(opt, log)
        log.close()
        return 0 if not failed else 1
    except Exception:
        # NX 里必须把异常完整打出来，否则只看到「日志执行失败」而没有任何线索
        log.write("=" * 68)
        log.write("发生未处理异常：")
        for line in traceback.format_exc().splitlines():
            log.write(line)
        log.write("=" * 68)
        log.close()
        return 1


if __name__ == "__main__":
    main()
