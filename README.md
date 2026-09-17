# Easy Revit to Designcenter NX

> ## ⚠️ ALPHA — 早期测试版
>
> **本项目处于 alpha 阶段，仅供测试与评估，请勿用于生产环境。**
>
> - 所有行为均在 **Siemens Designcenter NX 2512 + Windows** 上实测得出，**其它 NX 版本未经验证**
> - 导入流程本身是可靠的（附带完整产物核对），但**界面与工具链仍在快速变动**，接口随时可能改
> - **重要模型请先备份**，首次使用请用小模型试跑并核对结果
> - 作者不对任何数据丢失或工程错误负责，详见 [LICENSE](LICENSE)
>
> **ALPHA — early test build. Do not use in production. All behaviour was measured on
> Siemens Designcenter NX 2512 + Windows only; other NX versions are untested.
> Back up your models first.**

[中文](#中文文档) · [English](#english-documentation)

---

# 中文文档

## 目录

- [这是什么](#这是什么)
- [解决什么问题](#解决什么问题)
- [功能一览](#功能一览)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [图形界面](#图形界面)
- [命令行](#命令行)
- [参数全表](#参数全表)
- [输出结构](#输出结构)
- [产物核对](#产物核对)
- [技术细节](#技术细节)
- [导入之后：怎么在 NX 里做碰撞检查](#导入之后怎么在-nx-里做碰撞检查)
- [测试](#测试)
- [已知限制](#已知限制)
- [许可](#许可)

---

## 这是什么

把 **Revit 模型导入 Siemens NX**，保留 BIM 结构与坐标，供后续在 NX 里做碰撞检查、
装配验证或机构仿真使用。

包含一个图形界面（免命令行）、一套命令行工具、以及一个**产物核对器** ——
后者是这个项目真正有价值的部分，因为 NX 的 Revit 导入存在**若干会静默失败**的陷阱。

目标用户：需要在 NX 里使用 Revit/BIM 模型，却被导入结果不可靠困扰的工程师。

---

## 解决什么问题

NX 自带的 Revit 导入能用，但有三个坑会让人反复踩，而且**踩了不一定看得出来**：

| 坑 | 表现 | 后果 |
|---|---|---|
| **几何精度选错** | `Lightweight` 在复杂模型上大面积静默失败 | 文件数正常、错误数为 0，但 173 个部件里 168 个**没有几何**。在 NX 里打开是空的 |
| **输出目录非空** | 同名部件被改名另存为 `xxx_1.prt` | 改名那一批可能整批失败，同样是静默的 |
| **脚本内核对产物** | NX 在进程退出后才把部件写盘 | 导入一结束就检查必然是 0 个文件，会误判为失败 |

本项目把这三件事全部自动化处理，并在出错时**列出具体是哪个构件失败**，
直接指向要去 Revit 里检查的对象。

---

## 功能一览

**图形界面（`start_gui.bat`）**

- 模型库递归扫描，双击即导入，按修改时间倒序
- 每次导入**自动新建独立空目录**，同名自动加序号，历史结果不覆盖
- 导入后**自动等待落盘**（轮询文件数稳定），再自动核对
- 环境自检：NX 安装位置、`run_journal.exe`、`NXOpen.pyd`、Revit 数据交换模块、
  临时目录、模型文件、磁盘空间、已打开的 NX 进程
- 能自动修的自动修（探测 NX、建目录、加序号防覆盖），修不了的给出「往哪修」
- 失败时列出失败部件的**名字与体积**，并提示去找共同的族名

**命令行**

- `run_import.bat` —— 导入（自动探测 NX 安装位置）
- `verify_output.py` —— 事后核对某次导入的产物
- `verify_api.py` —— 静态校验脚本用到的 NXOpen API 是否存在于本机 NX 的官方存根中

**测试**

- 参数解析测试、界面烟测（自包含，不依赖本机文件）、端到端真实导入测试

---

## 环境要求

| 项 | 要求 | 说明 |
|---|---|---|
| NX | **2312 或更高** | `DexManager.createRevitImporter()` 自 NX2312 起提供 |
| NX 模块 | **Revit 数据交换（DEX）** | 必须安装并授权，否则 `CreateRevitImporter()` 返回 `None` |
| 操作系统 | Windows | `run_journal.exe` 与 `.bat` 启动器是 Windows 专属 |
| Python | 3.8+（仅界面与核对工具需要） | 界面用标准库 tkinter，**无第三方依赖** |

> 导入脚本本身**不需要**你准备 Python 环境 —— 它在 NX 进程内跑，用 NX 自带的 Python。

NX 安装位置不需要手工配置：界面会自动探测（环境变量 `UGII_BASE_DIR` → 注册表 → 常见路径），
只认含 `NXBIN\run_journal.exe` 的目录。

---

## 快速开始

```bat
rem 1) 启动界面
start_gui.bat

rem 2) 界面里：选「模型库目录」和「输出根目录」，然后双击列表里的模型

rem 3) 等它自动跑完（导入 + 等落盘 + 核对），看结论
```

界面默认把输出放在 `%USERPROFILE%\NXRevitImport\` 下，每次一个独立的子目录。

不想用界面的话：

```bat
rem 导入（务必用全新的空目录）
run_import.bat --rvt "D:\bim\model.rvt" --output-dir "D:\out\model_v1"

rem 等约 1 分钟，再核对
python verify_output.py "D:\out\model_v1"
```

---

## 图形界面

界面分五块，从上往下走：

| 区块 | 作用 |
|---|---|
| **1. 目录设置** | 模型库目录（放 `.rvt` 的文件夹）、输出根目录、NX 安装目录（**留空即自动探测**） |
| **2. 选择模型** | 递归列出模型，按修改时间倒序。**双击某行 = 开始导入**。「含子文件夹」可关 |
| **3. 导入参数** | 几何精度、单位、坐标对齐、三个内容开关。一般不用改 |
| **4. 环境自检** | 启动时自动跑。有问题给出 `-> ` 开头的修复提示；修好后点「重新自检」 |
| **5. 运行日志** | 实时输出。导入完自动等落盘、自动核对、给结论。可「复制报告」 |

底部进度条在等待落盘阶段会显示「已写入 N 个 .prt，已等 N 秒」。

**几何精度选 `Lightweight` 时会弹警告**，说明实测已知问题（见下文技术细节）。

---

## 命令行

### 导入

```bat
run_import.bat [参数...]
```

它内部执行：

```
"%UGII_BASE_DIR%\NXBIN\run_journal.exe" -nx "<仓库>\src\import_revit.py" -args <你的参数>
```

若 `UGII_BASE_DIR` 未设置，会依次探测 `C:`~`G:` 下的常见 NX 安装路径。

### 核对产物

```bat
python verify_output.py "<输出目录>"
```

### 校验脚本用到的 NXOpen API

```bat
python verify_api.py
python verify_api.py --nx-root "C:\Program Files\Siemens\NX2406"
python verify_api.py --pyi "<NX_HOME>\UGOPEN\pythonStubs\NXOpen\__init__.pyi"
```

---

## 参数全表

### 输入与输出

| 参数 | 默认 | 说明 |
|---|---|---|
| `--rvt PATH` | 无（必填，或改脚本内 `CONFIG`） | 要导入的 `.rvt`。**可重复**，按顺序依次导入 |
| `--output-dir PATH` | `.rvt` 同级 `nx_import_<模型名>` | 产物落盘目录。**强烈建议每次用全新空目录** |
| `--output-file PATH` | 无 | 仅 `NewPart` 时有意义 |

### 导入行为

| 参数 | 取值 | 默认 | 说明 |
|---|---|---|---|
| `--import-to X` | `WorkPart` \| `NewPart` | `NewPart` | 见下方「关于 WorkPart」 |
| `--geometry-as X` | `Precise` \| `Lightweight` | **`Precise`** | **别改成 `Lightweight`**，见技术细节 |
| `--part-unit X` | `NotSet`\|`Micrometer`\|`Millimeter`\|`Inch`\|`Meter` | `Millimeter` | Revit 内部单位是英尺，NX 侧取毫米最通用 |
| `--project-csys X` | `Internal`\|`ActiveProjectLOC`\|`ProjectBasePoint`\|`SurveyPoint` | **`SurveyPoint`** | **坐标对齐，联动核心** |
| `--settings-file PATH` | 无 | Revit 导入定义文件，用于复用整套导入选项 |
| `--messages X` | `NotSet`\|`Informational`\|`Warning`\|`Error`\|`Debug`\|`All` | `Informational` | 翻译器写日志的消息级别 |

### 内容开关（默认全开）

| 参数 | 关掉会怎样 |
|---|---|
| `--no-attributes` | Revit 类型/实例属性不再变成 NX 属性，NX 侧无法按 BIM 属性筛选/标注/出报表 |
| `--no-hierarchy` | 不按 Revit 标高建装配层级。开时实测会产出 `标高 1.prt` |
| `--no-linked-models` | 不合并链接模型。Revit 项目把其它专业作为链接时才需要开 |

### 其他

`--teamcenter`（导入到 Teamcenter）、`--show-window`（显示导入信息窗口）、`-h` / `--help`

### 关于 `WorkPart`

批处理会话里**没有任何打开的部件**，`session.Parts.Work` 为 `None`，
所以 `WorkPart` 在 `run_import.bat` 这条路上**必然中止**。界面因此固定用 `NewPart`。

想把多专业叠进**同一个部件**（真联动），需要在已打开的交互式 NX 里手动播日志：

1. 在 NX 里打开或新建一个部件，让它成为工作部件
2. 菜单 `工具` → `日志` → `播放`
3. 文件类型选 Python，选中 `src\import_revit.py`
4. 参数按 `-args` 格式填；不便填参数就直接改脚本顶部 `CONFIG`，然后不带参数播放

> **此路径未实测**，步骤按 NX 通用机制给出。

---

## 输出结构

一次成功的导入（实测某 16 MB 模型，303 个 Revit 构件）：

```
<输出目录>\
  <模型名>_rvt.prt                 <- 顶层装配，先打开这个
  标高 1.prt                       <- 按 Revit 标高生成的层级部件
  <族名> C <类型名> C <元素ID>.prt   <- Revit 族实例，一个实例一个部件
  ...
  (null).log                       <- NX-Revit 翻译器日志，权威判据在这里
```

共 173 个 `.prt` + 1 个日志。

**命名规律**：`<Revit 族名> C <类型名> C <元素ID>.prt`，`C` 是 Revit 内部分隔符的转义。
族名与类型名直接来自 Revit，说明 `ProcessAttributes` 生效。

**对做碰撞检查的意义**：每个 Revit 族实例是独立部件，碰撞粒度天然就是**构件级** ——
这是做干涉检查最理想的粒度。

---

## 产物核对

### 为什么必须**事后**核对

NX 把新建部件留在内存里，直到批处理进程**真正退出**才写盘。实测时间戳：

```
23:49:48  导入脚本写完自己的日志，即将返回
23:50:14  .prt 与 (null).log 才出现在输出目录      <- 晚约 26 秒
```

因此**脚本内部核对产物必然为 0**，那不是失败。唯一可靠的判据是两个：

1. 输出目录里的 `.prt` 产物
2. NX-Revit 翻译器写的 `(null).log` 里的错误/警告计数

界面会自动轮询等落盘；命令行用 `verify_output.py` 手动核对。

### 判定规则

| 判据 | 结论 |
|---|---|
| 错误 > 0 | **失败**，列出错误原文 |
| 错误 = 0，警告 = 0 | **成功**，几何完整 |
| 错误 = 0，警告 > 0 且占比 < 30% | **个别构件失败**，列出失败部件名与体积，模型其余部分可用 |
| 错误 = 0，警告 > 0 且占比 ≥ 30%（或 ≥ 50 条） | **系统性问题**，给出空目录 / DEX 授权 / 磁盘空间三条排查方向 |
| 有产物但无日志 | 只能确认产物存在，无法确认几何完整性 |

核对器会区分「文件压根没建」与「文件建了但只是个空壳」——
空壳大小通常在 58~60 KB，与正常部件有明显断层。

---

## 技术细节

### 三个实测踩出来的坑

#### 坑 1：`Lightweight` 会静默产出**没有几何**的部件

同一模型、同一套参数，只改几何精度，看 NX 翻译器自己的日志：

| 几何精度 | 部件数 | 体积 | 错误 | **警告** |
|---|---|---|---|---|
| `Precise` | 173 | 15.10 MB | 0 | **0** |
| `Lightweight` | 173 | 12.33 MB | 0 | **168** |

168 条警告全是：

```
WARNING: [<输出目录>\<部件>.prt] Failed to create import feature
```

含义是**部件文件建出来了，但往里导入几何的 feature 创建失败**。
文件数正常、错误数为 0，在 NX 里打开却是空的 —— 最难发现的一类失败。

**本项目默认锁死 `Precise`。**

#### 坑 2：重复导入到同一目录会大批失败

目标文件名已存在时，NX 会自动加 `_1`、`_2` 后缀另存，而实测**改名那一批可能整批失败**：

```
WARNING: [...Rectangular Duct C ... C 394593_2.prt] Failed to create import feature   x 168
INFO: Number of Error Messages..........: 0
INFO: Number of Warning Messages........: 168
```

**本项目每次导入都用全新的带序号目录。**

#### 坑 3：脚本内不可能核对产物

见上一节。**本项目把这个等待过程自动化了**，并明确区分「还没落盘」与「真的没产出」。

### NXOpen API 陷阱（NX 2512 实测）

**1. `Mode` 不是属性，是方法**

`BaseImporter` 里 `InputFile` / `OutputFile` / `PartUnit` 都是属性，
唯独 `Mode` 是 `GetMode()` / `SetMode()` 方法。写成 `builder.Mode = ...` 会失败：

```python
builder.SetMode(NXOpen.BaseImporter.Mode.NativeFileSystem)   # 正确
```

**2. 几何精度选项改过名**

| 来源 | 名称 | 取值 |
|---|---|---|
| 在线文档（NX23xx 时代） | `ImportSolidAsXTBrepOrFacet` | `XTBrep` / `FacetBodies` |
| **NX 2512 实际** | `ImportGeometryAs` | `Precise` / `Lightweight` |

`ImportSolidAsXTBrepOrFacet` 在 2512 的存根里**完全不存在**。照旧文档写必然失败。

**3. `Commit()` 返回 `None`**

官方存根明确写着 RevitImporter「NULL object will be returned from Commit()」，
且实测 `GetCommittedObjects()` 也返回 0 个（**即使导入完全成功**）。
两者都不能作为成功依据。

**4. 获取管理器的方式在两种语言里不同**

```java
// Java
Session session = (Session) SessionFactory.get("Session");
DexManager dex = session.dexManager();
```

```python
# Python：管理器是属性，不是方法
session = NXOpen.Session.GetSession()
dex = session.DexManager
```

### `run_journal` 的官方约定

取自 `run_journal.exe -help`：

```
run_journal [ -pim ] [ -nx | -simcenter3d ] [ -r=... ] [ -allow_redo ] <journal-file> [ -args .... ]

  -nx        Run the journal in NX
  -args ...  Pass the rest of the command line after this as an array of
             strings to Main in the journal file
```

**参数顺序不能改**：`-nx` 在脚本路径前，`-args` 在脚本路径后。
日志脚本的 `main()` 必须能接收一个参数数组。

### 为什么 `.bat` 里全是英文注释

cmd.exe 按系统 ANSI 代码页（中文 Windows 是 936/GBK）读取批处理文件，**不是** UTF-8。
用 UTF-8 写中文注释会把 `rem` 行解析成乱码，后续命令全部错乱：

```
'用法（取自' is not recognized as an internal or external command
```

所以两个 `.bat` **刻意保持纯 ASCII**，中文说明只放在本文件里。
`start_gui.bat` 会自动找 Python（`py` 启动器 → `PATH` → 常见安装位置）。

### 为什么核对器要处理编码

NX 的翻译器日志是本地代码页（GBK）写的，而且实测**同一文件里可能混有无法严格解码的字节**：
utf-8 与 gbk 的严格模式都会失败。若最后用 latin-1 兜底，中文路径会变成乱码 ——
`常规模型` 会显示成 `³£¹æÄÐÍ`，进而让按路径做的文件存在性判断**全部失效**。

正确做法是最后用 **GBK 宽容模式**：中文能正确还原，个别坏字节替换掉。

### 静态 API 校验为什么要带自检

`verify_api.py` 用 `ast` 解析 NX 官方类型存根，把脚本里每个属性访问和枚举成员回查白名单。

**必须用 `ast` 而不是正则**：存根里有大量文档字符串，其中含有以 `class ` 开头的英文句子
（例如第 5252 行 `class that provides the basic functionality...`），
正则会把它们误判成类定义、截断类的成员范围、产生误报。

**必须有自检**：第一版校验器把**它自己的缺陷**放过了 —— `BaseImporter` 内嵌了枚举类 `Mode`，
若把嵌套类名也算作实例成员，`builder.Mode` 这种错误就会被判为合法（**假通过**）。
所以现在会故意拿两个已知不存在的名字去撞白名单，必须被判为不存在，否则校验器自己判定失败。

### 仓库结构

```
.
├── start_gui.bat            图形界面启动器（纯 ASCII）
├── Revit2NX.py              界面主程序（tkinter，无第三方依赖）
├── nxcheck.py               产物核对核心（GUI 与命令行共用）
├── nxpreflight.py           环境预检与自动修复
├── verify_output.py         命令行核对
├── verify_api.py            NXOpen API 静态校验（带自检）
├── run_import.bat           命令行导入启动器（纯 ASCII）
├── src/
│   └── import_revit.py      真正在 NX 进程内跑的导入脚本
├── tests/
│   ├── test_args.py         参数解析测试
│   ├── test_gui_smoke.py    界面烟测（自包含）
│   └── test_e2e_import.py   端到端真实导入测试
├── LICENSE
└── README.md
```

---

## 导入之后：怎么在 NX 里做碰撞检查

NX 里跟「碰撞」有关的是**两个不同工具**，都在 `分析` 菜单下：

| 命令 | 用途 |
|---|---|
| `分析` → **简单干涉(&I)...** | 快速判断**两个体**是否相交 |
| `分析` → **间隙分析(&C)** | 成套流程：间隙集 → 执行分析 → 间隙浏览器 → 报告。**正式用这个** |

**间隙分析的子命令**：

- 间隙集：`新建` / `设置` / `复制` / `删除` / `编辑` / `汇总`
- 分析：`执行分析` / `批处理`（组件多时用）
- 结果：`间隙浏览器`（表格） / `研究间隙违例`（在模型里标出） / `重画已研究的节点`
- 报告：`报告` / `保存报告` / `保存书签`

**操作顺序**：

1. 打开顶层装配 `<模型名>_rvt.prt`（不是那 173 个零件）
2. 进**装配**应用模块
3. `分析` → `间隙分析` → `间隙集` → `新建`
4. 在间隙集里指定**要比对的组件组**和**间隙阈值**
5. `执行分析` → `间隙浏览器` 看结果 → `报告` 导出

**三个实务提醒**：

1. **几何必须是 `Precise`**。干涉/间隙分析基于实体，`Lightweight` 那批是空壳，跑不出结果
2. **两两组合数很大**。173 个部件 → 约 14,878 对。用 `批处理` 或缩小间隙集范围
3. **同专业内部会大量误报**。相邻相接的构件本来就互相接触，必须在间隙集里
   把比较范围限定为**专业之间**（风管↔结构、桥架↔水管、设备↔墙体）

> NX 的间隙分析是**几何层面**的。如果需要 BIM 语义层面的规则集碰撞检查
> （按专业分类过滤、自动定位到构件属性、出规范格式报告），Navisworks / Solibri 更对口。
> NX 的 `AECDesign` 模块只有导航器、标高、平面/立面视图、轴网、线型，**不含碰撞功能**。

---

## 测试

```bat
python tests\test_args.py                         rem 参数解析（27 项，NX 外运行）
python tests\test_gui_smoke.py                    rem 界面烟测（18 项，自包含）
python tests\test_e2e_import.py "D:\bim\m.rvt"     rem 端到端真实导入（需 NX + 模型）
python verify_api.py                              rem NXOpen API 对照官方存根
python verify_output.py "<输出目录>"                rem 核对某次导入的产物
```

- `test_args.py` 与 `test_gui_smoke.py` **不需要 NX**，也不依赖本机有 `.rvt`（自己造临时模型库）
- `test_e2e_import.py` 必须自己传模型路径，不传则跳过（退出码 2），**仓库里不含任何模型**
- `verify_api.py` 需要本机装有 NX（自动探测安装位置）

---

## 已知限制

- **`WorkPart` 模式未实测**（依赖它需要在交互式 NX 里播日志）
- **多专业叠进同一个部件未实测**
- **通过 `-args` 传中文路径未单独验证**：界面内部用命令行传路径、实测正常，
  但第一次排查时刻意避开了这个变量。稳妥做法是中文路径写进脚本的 `CONFIG`
- `--settings-file` / `--output-file` / `--teamcenter` / `--show-window` **未实测**
- **`Parts.SaveAll()` 导入后返回 `False`**，`PartSaveStatus` 的错误码未解读出来。
  最终落盘由 NX 在进程退出时完成，不影响产物正确性，但原因未查明
- 为何 `_1` 后缀那批能成功、`_2` 整批失败，未继续实验
- 界面与核对器是 Windows 专属（依赖 `tasklist` 与 `.bat`）；导入脚本本身跨平台

---

## 许可

[MIT](LICENSE)

---

<br>
<br>

---

# English Documentation

> ## ⚠️ ALPHA — early test build
>
> **This project is in alpha. Use for testing and evaluation only, not in production.**
>
> - All behaviour was measured on **Siemens Designcenter NX 2512 + Windows**.
>   **Other NX versions are untested.**
> - The import pipeline itself is dependable (it ships with full output verification),
>   but the GUI and tooling are **still changing rapidly** and interfaces may break
> - **Back up important models first.** Start with a small model and verify the result
> - The author accepts no liability for data loss or engineering errors — see [LICENSE](LICENSE)

## Contents

- [What it is](#what-it-is)
- [Problems it solves](#problems-it-solves)
- [Features](#features)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [GUI](#gui)
- [Command line](#command-line)
- [Parameter reference](#parameter-reference)
- [Output layout](#output-layout)
- [Output verification](#output-verification)
- [Technical details](#technical-details)
- [After import: clash detection in NX](#after-import-clash-detection-in-nx)
- [Tests](#tests)
- [Known limitations](#known-limitations)
- [License](#license)

---

## What it is

Imports **Revit models into Siemens NX**, preserving BIM structure and coordinates, so the
model can be used for clash detection, assembly validation or mechanism simulation inside NX.

It ships a GUI (no command line needed), a command line toolkit, and — the part that
actually matters — an **output verifier**, because NX's Revit import has several traps that
**fail silently**.

Intended for engineers who need Revit/BIM models inside NX and have been burned by
unreliable import results.

---

## Problems it solves

NX's built-in Revit import works, but three traps are easy to hit and **not always visible**:

| Trap | Symptom | Consequence |
|---|---|---|
| **Wrong geometry precision** | `Lightweight` fails at scale on complex models | File count is fine and errors are 0, but 168 of 173 parts end up with **no geometry**. The model opens empty in NX |
| **Non-empty output directory** | Same-named parts get renamed to `xxx_1.prt` | That renamed batch may fail entirely — again silently |
| **Verifying from inside the script** | NX writes parts only after the process exits | Checking right after the import always yields 0 files and looks like a failure |

This project automates all three, and on failure it **names the exact components that
failed**, pointing you straight at the families to inspect in Revit.

---

## Features

**GUI (`start_gui.bat`)**

- Recursive model library scan; double-click to import; newest first
- **Automatically creates a fresh, empty output directory** per import, with automatic
  numbering so previous results are never overwritten
- **Waits for the disk flush automatically**, then verifies automatically
- Preflight checks: NX install location, `run_journal.exe`, `NXOpen.pyd`, Revit DEX module,
  temp directory, model file, disk space, running NX processes
- Fixes what it can automatically (detects NX, creates directories, avoids overwrites) and
  tells you where to fix the rest
- On failure, lists the failing parts with their **names and sizes** and tells you to look
  for the common family name

**Command line**

- `run_import.bat` — import (auto-detects the NX installation)
- `verify_output.py` — verify the output of a given import
- `verify_api.py` — statically verify that the NXOpen APIs the script uses actually exist in
  your local NX type stubs

**Tests**

- Argument parsing tests, GUI smoke tests (self-contained), and a real end-to-end import test

---

## Requirements

| Item | Requirement | Notes |
|---|---|---|
| NX | **2312 or newer** | `DexManager.createRevitImporter()` exists from NX2312 |
| NX module | **Revit Data Exchange (DEX)** | Must be installed and licensed, otherwise `CreateRevitImporter()` returns `None` |
| OS | Windows | `run_journal.exe` and the `.bat` launchers are Windows-only |
| Python | 3.8+ (GUI and verifier only) | GUI uses stdlib tkinter, **no third-party packages** |

> The import script itself needs **no** Python environment of yours — it runs inside the NX
> process using NX's bundled Python.

You do not need to configure the NX install path by hand: the GUI auto-detects it
(`UGII_BASE_DIR` env var → registry → common locations), accepting only directories that
contain `NXBIN\run_journal.exe`.

---

## Quick start

```bat
rem 1) Launch the GUI
start_gui.bat

rem 2) Pick the "model library" and "output root" folders, then double-click a model

rem 3) Let it finish (import + flush wait + verification) and read the verdict
```

By default the GUI writes to `%USERPROFILE%\NXRevitImport\`, one subdirectory per import.

Prefer the command line?

```bat
rem Import (always use a fresh, empty output directory)
run_import.bat --rvt "D:\bim\model.rvt" --output-dir "D:\out\model_v1"

rem Wait about a minute, then verify
python verify_output.py "D:\out\model_v1"
```

---

## GUI

Five panels, top to bottom:

| Panel | Purpose |
|---|---|
| **1. Folders** | Model library folder, output root, NX install folder (**leave blank to auto-detect**) |
| **2. Pick a model** | Recursive list, newest first. **Double-click a row to import.** "Include subfolders" can be turned off |
| **3. Import options** | Geometry precision, unit, coordinate system, three content toggles. Usually leave as-is |
| **4. Preflight** | Runs automatically at startup. Failures come with `-> ` fix hints; click "Re-check" after fixing |
| **5. Run log** | Live output. Automatically waits for the flush, verifies, and reports a verdict. "Copy report" available |

During the flush wait the status bar shows how many `.prt` files have appeared and how long
it has been waiting.

**Selecting `Lightweight` pops a warning** explaining the measured problem (see below).

---

## Command line

### Import

```bat
run_import.bat [options...]
```

Internally it runs:

```
"%UGII_BASE_DIR%\NXBIN\run_journal.exe" -nx "<repo>\src\import_revit.py" -args <your options>
```

If `UGII_BASE_DIR` is unset it probes common NX locations on drives `C:`–`G:`.

### Verify output

```bat
python verify_output.py "<output directory>"
```

### Verify the NXOpen APIs used

```bat
python verify_api.py
python verify_api.py --nx-root "C:\Program Files\Siemens\NX2406"
python verify_api.py --pyi "<NX_HOME>\UGOPEN\pythonStubs\NXOpen\__init__.pyi"
```

---

## Parameter reference

### Input and output

| Option | Default | Notes |
|---|---|---|
| `--rvt PATH` | none (required, or edit `CONFIG`) | `.rvt` to import. **Repeatable**, imported in order |
| `--output-dir PATH` | `nx_import_<model>` next to the `.rvt` | Output folder. **Always use a fresh, empty directory** |
| `--output-file PATH` | none | Only meaningful with `NewPart` |

### Import behaviour

| Option | Values | Default | Notes |
|---|---|---|---|
| `--import-to X` | `WorkPart` \| `NewPart` | `NewPart` | See "About WorkPart" below |
| `--geometry-as X` | `Precise` \| `Lightweight` | **`Precise`** | **Do not switch to `Lightweight`** — see Technical details |
| `--part-unit X` | `NotSet`\|`Micrometer`\|`Millimeter`\|`Inch`\|`Meter` | `Millimeter` | Revit's internal unit is feet; millimetres is the usual choice in NX |
| `--project-csys X` | `Internal`\|`ActiveProjectLOC`\|`ProjectBasePoint`\|`SurveyPoint` | **`SurveyPoint`** | **Coordinate alignment — the core of model linkage** |
| `--settings-file PATH` | none | Revit import definition file, for reusing a full option set |
| `--messages X` | `NotSet`\|`Informational`\|`Warning`\|`Error`\|`Debug`\|`All` | `Informational` | Translator log message level |

### Content toggles (all on by default)

| Option | What turning it off costs you |
|---|---|
| `--no-attributes` | Revit type/instance properties no longer become NX attributes; no BIM-attribute filtering, annotation or reporting in NX |
| `--no-hierarchy` | No level-based assembly hierarchy. When on, a `标高 1.prt` (Level 1) part is produced |
| `--no-linked-models` | Linked models are not merged. Only needed when the Revit project links other disciplines |

### Other

`--teamcenter` (import to Teamcenter), `--show-window` (show the import info window),
`-h` / `--help`

### About `WorkPart`

A batch session has **no part open**, so `session.Parts.Work` is `None` and `WorkPart`
**always aborts** on the `run_import.bat` route. The GUI therefore always uses `NewPart`.

To stack multiple disciplines into **one part** (true model linkage), play the journal
manually inside an already-open interactive NX:

1. Open or create a part in NX and make it the work part
2. Menu `Tools` → `Journal` → `Play`
3. Choose Python as the file type and select `src\import_revit.py`
4. Fill in options in `-args` form, or just edit `CONFIG` at the top of the script and play
   it without arguments

> **This path is untested.** The steps follow NX's general journal mechanism.

---

## Output layout

A successful import (measured on a 16 MB model with 303 Revit elements):

```
<output dir>\
  <model>_rvt.prt                      <- top-level assembly; open this first
  标高 1.prt                           <- level-based part generated from Revit levels
  <Family> C <Type> C <ElementId>.prt  <- one part per Revit family instance
  ...
  (null).log                           <- NX-Revit translator log; the authoritative record
```

173 `.prt` files plus one log in total.

**Naming**: `<Revit family> C <type> C <element id>.prt`, where `C` escapes Revit's internal
separator. Family and type names come straight from Revit, which shows that
`ProcessAttributes` took effect.

**Why this matters for clash detection**: every Revit family instance becomes its own part,
so the clash granularity is naturally **per component** — the ideal granularity for
interference checking.

---

## Output verification

### Why verification must be **post-process**

NX keeps newly created parts in memory until the batch process **actually exits**. Measured
timestamps:

```
23:49:48  the import script wrote its own log and is about to return
23:50:14  the .prt files and (null).log appear in the output directory   <- ~26 s later
```

So **verifying from inside the script always yields 0** — that is not a failure. There are
exactly two reliable signals:

1. the `.prt` artefacts in the output directory
2. the error/warning counts in NX-Revit's own `(null).log`

The GUI polls and waits for the flush; on the command line, use `verify_output.py`.

### Verdict rules

| Signal | Verdict |
|---|---|
| errors > 0 | **Failed** — the error text is listed |
| errors = 0, warnings = 0 | **Success**, geometry complete |
| errors = 0, warnings > 0 and < 30% of parts | **Individual components failed** — failing part names and sizes are listed; the rest of the model is usable |
| errors = 0, warnings > 0 and ≥ 30% (or ≥ 50) | **Systemic** — the verifier points at empty directory / DEX licensing / disk space |
| artefacts present but no log | Existence confirmed, geometry completeness unknown |

The verifier distinguishes "the file was never created" from "the file was created as an
empty shell" — shells are typically 58–60 KB, clearly separated from normal parts.

---

## Technical details

### Three traps found by measurement

#### Trap 1: `Lightweight` silently produces parts with **no geometry**

Same model, same options, only the geometry precision changed — read from NX's own
translator log:

| Geometry | Parts | Size | Errors | **Warnings** |
|---|---|---|---|---|
| `Precise` | 173 | 15.10 MB | 0 | **0** |
| `Lightweight` | 173 | 12.33 MB | 0 | **168** |

All 168 warnings read:

```
WARNING: [<output dir>\<part>.prt] Failed to create import feature
```

Meaning: **the part file was created, but the feature that brings the geometry into it
failed.** The file count is right, errors are 0, and the model opens empty in NX — the
hardest class of failure to notice.

**This project pins `Precise` as the default.**

#### Trap 2: Re-importing into the same directory fails at scale

When a target filename already exists, NX renames the new one with a `_1` / `_2` suffix, and
that renamed batch **may fail entirely**:

```
WARNING: [...Rectangular Duct C ... C 394593_2.prt] Failed to create import feature   x 168
INFO: Number of Error Messages..........: 0
INFO: Number of Warning Messages........: 168
```

**This project always uses a fresh, numbered directory.**

#### Trap 3: The script cannot verify its own output

See the previous section. **This project automates that wait** and clearly separates
"not flushed yet" from "genuinely produced nothing".

### NXOpen API traps (measured on NX 2512)

**1. `Mode` is a method, not a property**

Within `BaseImporter`, `InputFile` / `OutputFile` / `PartUnit` are properties, but `Mode` is
the methods `GetMode()` / `SetMode()`. `builder.Mode = ...` fails:

```python
builder.SetMode(NXOpen.BaseImporter.Mode.NativeFileSystem)   # correct
```

**2. The geometry precision option was renamed**

| Source | Name | Values |
|---|---|---|
| Online docs (NX23xx era) | `ImportSolidAsXTBrepOrFacet` | `XTBrep` / `FacetBodies` |
| **Actual NX 2512** | `ImportGeometryAs` | `Precise` / `Lightweight` |

`ImportSolidAsXTBrepOrFacet` **does not exist at all** in the 2512 stubs. Code written from
the old docs cannot work.

**3. `Commit()` returns `None`**

The official stub states RevitImporter "NULL object will be returned from Commit()", and
`GetCommittedObjects()` also returns 0 **even on a fully successful import**. Neither can be
used as a success signal.

**4. Getting managers differs between the two languages**

```java
// Java
Session session = (Session) SessionFactory.get("Session");
DexManager dex = session.dexManager();
```

```python
# Python: managers are properties, not methods
session = NXOpen.Session.GetSession()
dex = session.DexManager
```

### `run_journal` contract

From `run_journal.exe -help`:

```
run_journal [ -pim ] [ -nx | -simcenter3d ] [ -r=... ] [ -allow_redo ] <journal-file> [ -args .... ]

  -nx        Run the journal in NX
  -args ...  Pass the rest of the command line after this as an array of
             strings to Main in the journal file
```

**Do not reorder**: `-nx` goes before the script path, `-args` after it. The journal's
`main()` must accept an argument array.

### Why the `.bat` files contain English comments only

cmd.exe parses `.bat` files using the system ANSI codepage (936/GBK on Chinese Windows),
**not** UTF-8. UTF-8 Chinese comments corrupt the `rem` lines and derail every command that
follows:

```
'用法（取自' is not recognized as an internal or external command
```

Both `.bat` files are therefore **deliberately pure ASCII**; Chinese documentation lives in
this file only. `start_gui.bat` locates Python automatically
(`py` launcher → `PATH` → common install locations).

### Why the verifier handles encodings

NX's translator log is written in the local codepage (GBK), and the same file can contain
bytes that fail **strict** decoding in both utf-8 and gbk. Falling back to latin-1 turns
Chinese paths into mojibake — `常规模型` becomes `³£¹æÄÐÍ` — which silently breaks every
path-based file-existence check.

The correct fallback is a **lenient GBK decode**: Chinese is restored correctly and only the
stray bytes are replaced.

### Why the static API check has a self-test

`verify_api.py` parses the official NX type stubs with `ast` and checks every property access
and enum member used by the script against that whitelist.

**It must use `ast`, not regex**: the stubs contain large docstrings with English sentences
starting with `class ` (e.g. line 5252, `class that provides the basic functionality...`).
A regex mistakes them for class definitions, truncates the member ranges and produces false
positives.

**It must have a self-test**: the first version of the checker let **its own bug** through —
`BaseImporter` contains a nested enum class named `Mode`, and if nested class names count as
instance members then the mistake `builder.Mode` is judged legal (a **false pass**). The
checker now deliberately feeds two known-nonexistent names through the whitelist; if they are
not rejected, the checker itself fails.

### Repository layout

```
.
├── start_gui.bat            GUI launcher (pure ASCII)
├── Revit2NX.py              GUI main program (tkinter, no third-party deps)
├── nxcheck.py               Verification core (shared by GUI and CLI)
├── nxpreflight.py           Preflight checks and automatic fixes
├── verify_output.py         Command line verification
├── verify_api.py            NXOpen API static check (with self-test)
├── run_import.bat           Command line import launcher (pure ASCII)
├── src/
│   └── import_revit.py      The script that actually runs inside NX
├── tests/
│   ├── test_args.py         Argument parsing tests
│   ├── test_gui_smoke.py    GUI smoke tests (self-contained)
│   └── test_e2e_import.py   Real end-to-end import test
├── LICENSE
└── README.md
```

---

## After import: clash detection in NX

NX has **two different tools** related to "clash", both under the `Analysis` menu:

| Command | Purpose |
|---|---|
| `Analysis` → **Simple Interference...** | Quickly determines whether **two bodies** intersect |
| `Analysis` → **Assembly Clearance** | The full workflow: clearance set → perform analysis → clearance browser → report. **Use this one** |

**Assembly Clearance sub-commands**:

- Clearance set: `New` / `Set` / `Copy` / `Delete` / `Edit` / `Summary`
- Analysis: `Perform Analysis` / `Batch` (for many components)
- Results: `Clearance Browser` (table) / `Study Clearance Violations` (annotate in model) /
  `Redraw Studied Nodes`
- Reporting: `Report` / `Save Report` / `Save Bookmark`

**Procedure**:

1. Open the top-level assembly `<model>_rvt.prt` (not the 173 individual parts)
2. Switch to the **Assemblies** application
3. `Analysis` → `Assembly Clearance` → `Clearance Set` → `New`
4. In the clearance set, specify the **component groups** to compare and the **clearance
   threshold**
5. `Perform Analysis` → `Clearance Browser` for results → `Report` to export

**Three practical notes**:

1. **Geometry must be `Precise`.** Interference/clearance analysis works on solids; the
   `Lightweight` batch is empty shells and will produce nothing
2. **The pair count explodes.** 173 parts → about 14,878 pairs. Use `Batch` or narrow the
   clearance set
3. **Same-discipline false positives.** Adjacent and touching components inherently
   intersect. You must restrict the comparison to **between disciplines** in the clearance
   set (ducts↔structure, cable trays↔pipes, equipment↔walls)

> NX's clearance analysis is **geometric**. For BIM-semantic, ruleset-driven clash detection
> (discipline filtering, automatic location of component properties, standard-format
> reports), Navisworks or Solibri are better suited. NX's `AECDesign` module only covers
> navigator, levels, plan/elevation views, grids and line styles — it contains **no clash
> functionality**.

---

## Tests

```bat
python tests\test_args.py                        rem argument parsing (27 checks, no NX)
python tests\test_gui_smoke.py                   rem GUI smoke tests (18 checks, self-contained)
python tests\test_e2e_import.py "D:\bim\m.rvt"    rem real end-to-end import (needs NX + a model)
python verify_api.py                             rem NXOpen API vs the official stubs
python verify_output.py "<output dir>"            rem verify one import's output
```

- `test_args.py` and `test_gui_smoke.py` **need no NX** and do not depend on you having any
  `.rvt` around — they build their own temporary model library
- `test_e2e_import.py` requires a model path; without one it skips (exit code 2).
  **No models are included in this repository**
- `verify_api.py` needs NX installed locally (the install location is auto-detected)

---

## Known limitations

- **`WorkPart` mode is untested** (it depends on playing the journal inside an interactive NX
  session)
- **Stacking multiple disciplines into a single part is untested**
- **Passing Chinese paths via `-args` was not verified in isolation**: the GUI passes paths on
  the command line and works in practice, but that variable was deliberately avoided during
  initial debugging. Safest is to put Chinese paths in the script's `CONFIG`
- `--settings-file` / `--output-file` / `--teamcenter` / `--show-window` are **untested**
- **`Parts.SaveAll()` returns `False` after import**; the `PartSaveStatus` error code was not
  decoded. The final flush happens when NX exits, so correctness is unaffected — but the
  reason is unknown
- Why the `_1`-suffixed batch succeeded while the `_2` batch failed entirely was not
  investigated further
- The GUI and verifier are Windows-only (they rely on `tasklist` and `.bat`); the import
  script itself is cross-platform

---

## License

[MIT](LICENSE)
