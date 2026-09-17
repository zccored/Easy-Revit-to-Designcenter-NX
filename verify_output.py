# -*- coding: utf-8 -*-
"""
导入产物核对工具（命令行）。

核心逻辑在 nxcheck.py 里，本文件只是它的命令行外壳。

为什么必须【事后】核对：
    NX 把新建部件留在内存里，直到批处理进程真正退出才写盘，比导入脚本的
    main() 返回晚约 26 秒。时间戳证据：
        23:49:48  脚本自己的日志写完，即将返回
        23:50:14  .prt 与 (null).log 才出现在输出目录
    所以导入脚本内部核对必然为 0，唯一可靠判据是输出目录的文件与
    NX-Revit 翻译器自己写的日志。

用法：
    python verify_output.py "<某次导入的输出目录>"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nxcheck  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    target = sys.argv[1]
    if not os.path.isdir(target):
        print("目录不存在：{0}".format(target))
        print("")
        print("提示：输出目录是每次导入自动新建的，名字形如 <模型名>_Precise。")
        print("      去输出根目录下找最近修改的那个子目录。")
        return 1

    report = nxcheck.analyze(target)
    print("=" * 70)
    print("导入产物核对")
    print("=" * 70)
    print(report.text())
    print("=" * 70)

    if not report.data.get("prt"):
        print("")
        print("补充提示：")
        print("  · 导入刚结束不到 1 分钟时 NX 可能还没落盘，稍等再跑一次本工具。")
        print("  · 若始终没有产物，看 src\\nx_revit_import.log 里的异常回溯；")
        print("    最常见原因是 NX 未安装或未授权 Revit 数据交换(DEX)模块。")

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
