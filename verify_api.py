# -*- coding: utf-8 -*-
"""
静态 API 校验：用 Python 标准库 ast 解析 NX 官方类型存根，
校验 src/import_revit.py 里用到的 NXOpen 属性/方法/枚举成员是否真实存在。

为什么用 ast 而不是正则：
    存根里有大量文档字符串，其中含有以 "class " 开头的英文句子
    （例如 "class that provides the basic functionality..."），
    正则会把它们误判成类定义，从而截断类的成员范围、产生误报。

为什么需要这个校验：
    NX 各版本之间 NXOpen 的命名会变。实测 NX 2512 就把几何精度选项从
    ImportSolidAsXTBrepOrFacet 改名成了 ImportGeometryAs，且 BaseImporter
    的 Mode 是 GetMode()/SetMode() 方法而不是属性。照旧文档写必然跑不起来。
    本工具在导入前就能把这些错误挡下来。

用法：
    python verify_api.py
    python verify_api.py --nx-root "C:\\Program Files\\Siemens\\NX2406"
    python verify_api.py --pyi "<NX_HOME>\\UGOPEN\\pythonStubs\\NXOpen\\__init__.pyi"
"""
import argparse
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SCRIPT = os.path.join(HERE, "src", "import_revit.py")

# 存根相对 NX 安装根的路径
PYI_REL = os.path.join("UGOPEN", "pythonStubs", "NXOpen", "__init__.pyi")


def locate_pyi(explicit_pyi=None, explicit_root=None):
    """找出 NXOpen 的类型存根。返回 (路径, 说明)；找不到时返回 (None, 原因)。"""
    if explicit_pyi:
        if os.path.isfile(explicit_pyi):
            return explicit_pyi, "由 --pyi 指定"
        return None, "--pyi 指定的文件不存在：{0}".format(explicit_pyi)

    roots = []
    if explicit_root:
        roots.append(explicit_root)

    env = os.environ.get("UGII_BASE_DIR")
    if env:
        roots.append(env)

    try:
        import nxpreflight
        roots.extend(nxpreflight.detect_nx_roots())
    except Exception:
        pass

    seen = set()
    for root in roots:
        if not root:
            continue
        root = os.path.abspath(root)
        if root.lower() in seen:
            continue
        seen.add(root.lower())
        cand = os.path.join(root, PYI_REL)
        if os.path.isfile(cand):
            return cand, "自动探测（NX 根目录 {0}）".format(root)

    return None, ("没找到 NXOpen 类型存根。请设置 UGII_BASE_DIR，"
                  "或用 --nx-root / --pyi 指定。")


def main():
    ap = argparse.ArgumentParser(
        description="校验 import_revit.py 用到的 NXOpen 名称是否存在于官方存根中")
    ap.add_argument("--pyi", help="直接指定 NXOpen/__init__.pyi 的完整路径")
    ap.add_argument("--nx-root", help="NX 安装根目录（其下有 UGOPEN\\pythonStubs）")
    ap.add_argument("--script", default=SCRIPT, help="要校验的脚本，默认 src/import_revit.py")
    args = ap.parse_args()

    pyi, how = locate_pyi(args.pyi, args.nx_root)
    if not pyi:
        print("=" * 70)
        print("NXOpen 静态 API 校验 —— 无法开始")
        print("=" * 70)
        print(how)
        print("")
        print("提示：图形界面（start_gui.bat）会自动探测 NX 安装位置。")
        return 2

    if not os.path.isfile(args.script):
        print("找不到要校验的脚本：{0}".format(args.script))
        return 2

    with open(pyi, encoding="utf-8", errors="replace") as fh:
        pyi_src = fh.read()
    try:
        tree = ast.parse(pyi_src)
    except SyntaxError as exc:
        print("存根解析失败（可能 NX 版本差异）：{0}".format(exc))
        return 2

    # ---- 建立顶层 class -> ClassDef 映射 ----
    CLASSES = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            CLASSES[node.name] = node

    def own_members(name):
        """
        只取该类自身可被「实例属性访问」的成员：方法名与注解属性名。
        故意不收集嵌套类名 —— BaseImporter 内嵌了枚举类 Mode，
        若把嵌套类名也算作实例成员，`builder.Mode = ...` 这种把枚举类
        当属性用的错误就会被放过（正确写法是 builder.SetMode(...)）。
        """
        cd = CLASSES.get(name)
        if cd is None:
            return set()
        out = set()
        for item in cd.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.add(item.name)
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                out.add(item.target.id)
        return out

    def all_members(name, seen=None):
        """沿继承链合并成员。"""
        if seen is None:
            seen = set()
        if name in seen:
            return set()
        seen.add(name)
        out = own_members(name)
        cd = CLASSES.get(name)
        if cd is not None:
            for base in cd.bases:
                bn = None
                if isinstance(base, ast.Name):
                    bn = base.id
                elif isinstance(base, ast.Attribute):
                    bn = base.attr
                if bn:
                    out |= all_members(bn, seen)
        return out

    def nested_enum_members(outer, inner):
        """取 outer 内嵌类 inner 的枚举成员名（形如 `Name: int` 的注解）。"""
        cd = CLASSES.get(outer)
        if cd is None:
            return None
        for item in cd.body:
            if isinstance(item, ast.ClassDef) and item.name == inner:
                return {n.target.id for n in item.body
                        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
        return None

    with open(args.script, encoding="utf-8") as fh:
        script = fh.read()

    RECEIVERS = {
        "builder": "RevitImporter",
        "dex_manager": "DexManager",
        "session": "Session",
        "work": "Part",
        "self._lw": "ListingWindow",
    }

    problems = []
    checked = 0

    for recv, cls in RECEIVERS.items():
        allowed = all_members(cls)
        if not allowed:
            problems.append("!! 存根里找不到类 {0}（NX 版本可能差异过大）".format(cls))
            continue
        for m in re.finditer(r"\b" + re.escape(recv) + r"\.(\w+)", script):
            attr = m.group(1)
            checked += 1
            if attr not in allowed:
                problems.append("{0}.{1}  <-- 不在 {2} 的成员中".format(recv, attr, cls))

    ENUMS = {
        "BaseImporter": ["Mode", "PartUnitOption"],
        "RevitImporter": ["ImportToOption", "ImportGeometryAsEnum",
                          "MessageEnum", "RevitProjectCSYSEnum"],
    }
    enum_checked = 0
    for outer, inners in ENUMS.items():
        for inner in inners:
            valid = nested_enum_members(outer, inner)
            if valid is None:
                problems.append("!! 存根里找不到嵌套枚举 {0}.{1}".format(outer, inner))
                continue
            for m in re.finditer(r"NXOpen\." + outer + r"\." + inner + r"\.(\w+)", script):
                enum_checked += 1
                if m.group(1) not in valid:
                    problems.append("NXOpen.{0}.{1}.{2}  <-- 合法值为 {3}".format(
                        outer, inner, m.group(1), sorted(valid)))

    # ---- 自检：两个已确认不存在的名字必须被判为不存在 ----
    # 没有这一步，校验器自己的缺陷会被静默放过（假通过），
    # 这在实际开发中发生过：把嵌套类名当成实例成员就会漏掉 `builder.Mode`。
    selftest_ok = True
    for recv, attr in [("builder", "ImportSolidAsXTBrepOrFacet"), ("builder", "Mode")]:
        if attr in all_members(RECEIVERS[recv]):
            selftest_ok = False

    print("=" * 70)
    print("NXOpen 静态 API 校验（ast 解析官方存根）")
    print("=" * 70)
    print("存根    : {0}".format(pyi))
    print("来源    : {0}".format(how))
    print("脚本    : {0}".format(args.script))
    print("检查属性/方法访问 {0} 处，枚举成员 {1} 处".format(checked, enum_checked))
    print("自检（两个已知不存在的名字必须被判为不存在）：{0}".format(
        "通过" if selftest_ok else "失败"))
    print("")

    if not selftest_ok:
        print("校验器自检失败，结果不可信，已中止。")
        return 2
    if problems:
        print("发现 {0} 个问题：".format(len(problems)))
        for p in problems:
            print("  " + p)
        return 1
    print("全部通过：脚本用到的每个 NXOpen 名称都存在于官方存根中。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
