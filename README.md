<div align="center">

# 外箱标签打印程序

**扫码录入 SN → 自动拼装箱号 → 调用 BarTender 模板打印外箱标签**

[![Release](https://img.shields.io/github/v/release/ylqcxwl/box-label-printer?label=Release&color=0066CC)](https://github.com/ylqcxwl/box-label-printer/releases/latest)
[![Build](https://img.shields.io/github/actions/workflow/status/ylqcxwl/box-label-printer/build.yml?branch=main&label=Build)](https://github.com/ylqcxwl/box-label-printer/actions/workflows/build.yml)
[![Downloads](https://img.shields.io/github/downloads/ylqcxwl/box-label-printer/total?label=Downloads&color=0066CC)](https://github.com/ylqcxwl/box-label-printer/releases)
[![Last Commit](https://img.shields.io/github/last-commit/ylqcxwl/box-label-printer?label=Updated)](https://github.com/ylqcxwl/box-label-printer/commits/main)

[![Python](https://img.shields.io/badge/Python-3.8%20x86-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Windows-7%2B%20%7C%2032%2F64bit-0078D6?logo=windows&logoColor=white)]()
[![PyQt5](https://img.shields.io/badge/PyQt5-5.15.10-41CD52?logo=qt&logoColor=white)]()
[![BarTender](https://img.shields.io/badge/BarTender-10.0%2B-FF6B00)]()
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)]()

[![绿色免安装](https://img.shields.io/badge/%E9%83%A8%E7%BD%B2-%E7%BB%BF%E8%89%B2%E5%85%8D%E5%AE%89%E8%A3%85-2EA44F)]()
[![完全离线](https://img.shields.io/badge/%E8%BF%90%E8%A1%8C-%E5%AE%8C%E5%85%A8%E7%A6%BB%E7%BA%BF-6F42C1)]()
[![中文界面](https://img.shields.io/badge/%E7%95%8C%E9%9D%A2-%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-0066CC)]()
[![不改模板](https://img.shields.io/badge/BarTender-%E7%BB%9D%E4%B8%8D%E4%BF%AE%E6%94%B9%E6%A8%A1%E6%9D%BF-E81123)]()

</div>

---

## 快速开始

1. 到 [Releases](https://github.com/ylqcxwl/box-label-printer/releases/latest) 下载 `BoxLabelPrinter_vX.Y.Z.zip`
2. 解压到任意目录（路径建议不含特殊权限限制）
3. 把 `.btw` 模板放进 `data/templates/`
4. 双击 `标签打印.exe` 即可 —— **无需安装 Python、无需安装软件、无需联网**

> 目标机器需已安装 **BarTender 10.0 或更高版本**（程序通过 COM 调用它打印）。
> 打印模板只在内存中赋值、以「不保存更改」方式关闭，**绝不修改模板文件**。

---

## 核心特性

| | 特性 |
|---|---|
| 🖨️ | **扫码即打**：录入 SN 满箱自动打印，不满箱可手动打印；箱号、SN 按规则自动生成 |
| 🔒 | **数据严谨**：SN 唯一性校验、已打印 SN 禁止重复、打印成功才跳号、按年分库 |
| 🧩 | **高度可配**：字段映射、箱号规则、SN 规则、四个列表的列顺序与显隐全部可视化配置 |
| 📦 | **开箱即用**：纯绿色目录，整个文件夹复制到任何电脑直接运行，无后台常驻进程 |
| 🔌 | **完全离线**：全部功能本地运行；只有「检查更新 / 下载更新」是可选联网项 |
| 🛡️ | **安全可靠**：打印走单一常驻线程（避免 BarTender COM 跨线程报错）、自动备份、删除需密码 |

---

## 功能一览

程序共 4 个页面：**打印标签 / 打印记录 / 产品管理 / 设置**。

### 🖨️ 打印标签

- 输入 **SN 前缀** 或 **69 码** 即时筛选产品，选中行实心蓝高亮
- 扫码录入 SN，满箱自动打印；不满箱点「手动打印标签」
- SN 前缀 / 规则 / 批次自动校验，重复 SN 拦截
- **更换产品**会清空当前未打印的 SN，并把**生产日期与批次复位为默认**
- 产品详情显示重量等全部字段；箱号按预览规则实时生成

### 📋 打印记录

- 按 **SN / 箱号 / 日期范围** 查询，输入停笔 0.3 秒或回车自动刷新（无查询按钮）
- 自动合并**跨年**记录；箱号、箱号序号、箱内序号分列，打印日期与打印时间分列
- 列宽按内容**自适应**（仍可手动拖动）；按住 Shift 点勾选框可整段连选
- **重打印该箱**：按整箱重打，勾选同箱任意一行即可；勾到不同箱会明确提示
- 批量导出 Excel：可选单表 / 按日期分工作表，工作表名称支持 `YYYY` `YY` `MM` `DD` 占位符
- 导出采用流式写入（3 万条约 9 秒），删除记录需密码

### 📦 产品管理

- 产品录入 / 编辑（双击行直接改）/ 删除，SN 前缀唯一
- Excel 批量导入导出（中文表头，单事务批量提交，5000 条约 0.8 秒）
- 模板栏只填文件名即可，不用写 `.btw` 后缀

### ⚙️ 设置（4 个页签）

| 页签 | 内容 |
|---|---|
| 箱号规则 | 占位符拼装（年月日 / 流水 / 返修流水 / 工厂代码 / SN 前缀），每产品每月每批次独立计数、每月清零；流水支持纯数字 / 字母 / 数字+字母 / 16 进制 / 自定义序列；对话框内实时预览 |
| SN 规则 | 占位符拼装 + 总位数校验；批次、年月日占位符可选添加；流水字符集同上 |
| 字段映射 | 产品字段 ↔ BarTender 命名数据源自由增删改；支持 **导入 / 导出 Excel / 恢复默认**（恢复前自动备份）；字段变更会同步刷新各列表；新增字段默认勾选 |
| 列表设置 | **四个列表同屏并排**：打印页待选、打印记录、产品管理、产品新增；各自独立勾选、上移下移，一次保存全部 / 全部恢复默认 |

**系统设置**：默认打印机、模板目录、工厂代码、删除密码、自动/手动备份（主库 + 打印记录打包为 zip，默认保留 3 份）、备份/模板目录一键打开、打印记录默认显示周期、工作表名称格式、GitHub 更新检查。

> 💡 连点侧边栏左上角 LOGO **10 次**可更换软件图标（存于 `data/custom_logo.png`）。

---

## BarTender 模板要求

模板里的对象必须绑定**命名数据源 / 命名字符串**，名称与「设置 → 字段映射」一致：

| 用途 | 默认数据源名 |
|---|---|
| 产品字段 | `mingcheng` 名称 · `guige` 规格 · `xinghao` 型号 · `yanse` 颜色 · `SN4` SN前缀 · `SKU` · `code69` 69码 · `shuliang` 数量 · `zhongliang` 重量 |
| 箱号 | `xianghao`（打印类字段，由程序自动填入） |
| SN 列表 | 数字 `1`、`2`、`3` …… 与模板上的 SN 位一一对应 |

> ⚠️ **不满箱时的空位处理**：模板上每个 SN 位在打印时都会被赋值
> （不足的位写入空串），否则模板里预置的示例 SN 会被打印出来。
> 因此模板建议把所有 SN 位都做成命名数据源，不要写死静态文本。

---

## 数据与目录结构

**根目录只保留 3 项**：启动文件、用户数据目录、运行依赖目录。其余文件全部归到
`runtime/`，不会散落在根目录。整个程序目录复制走即可迁移。

```
标签打印/
├── 标签打印.exe            # 唯一的程序启动文件（桌面快捷方式指向它）
├── data/                   # 用户数据（升级时保留此目录即可）
│   ├── label_printer.db    # 产品、规则、字段映射、系统设置
│   ├── records/            # 打印记录，按年一个库文件
│   │   └── records_2026.db
│   ├── templates/          # .btw 模板放这里
│   ├── assets/             # 运行时生成的界面小图标
│   ├── backup/             # 自动备份 zip
│   ├── custom_logo.png     # 自定义图标（可选）
│   └── print_log.txt
└── runtime/                # 所有依赖：Python DLL / PYD / Qt 插件 / 内置图标
    └── assets/             # 随包资源（logo.png、logo.ico）
```

> ⚠️ `runtime/` 是程序运行依赖，**不要删除或改动**；升级时只替换
> `标签打印.exe` 与 `runtime/`，`data/` 原样保留即可，数据不会丢。
>
> 记录按年分库，避免单文件过大；查询时自动合并跨年数据。

<details>
<summary>源码结构（点击展开）</summary>

```
app/
├── main.py                  入口
├── version.py               版本号（打包时自动写入）
├── config.py                路径配置
├── core/
│   ├── db.py                SQLite 数据层（产品/规则/配置/计数）
│   ├── records.py           打印记录存储（按年分文件 / 跨年合并）
│   ├── rules.py             箱号 & SN 规则引擎
│   ├── bartender.py         BarTender COM 封装
│   ├── print_service.py     常驻打印线程（COM 线程亲和性）
│   ├── print_data.py        标签数据组装（打印 / 重打印共用）
│   ├── excel_io.py          Excel 导入导出（流式写入）
│   ├── listconfig.py        列表列配置
│   ├── backup.py            备份与恢复
│   └── updater.py           GitHub Releases 更新检查
└── ui/                      PyQt5 界面（4 页 + 设置 4 页签）
tools/                       图标生成 / 启动脚本 / 发布辅助脚本
.github/workflows/build.yml  一键打包 + 自动发布 Release
标签打印.spec                 PyInstaller 配置
```

</details>

---

## 打包与发布

打包由 GitHub Actions 完成（**Windows Server 2022 + Python 3.8 x86**，兼容 Win7）。

**两种触发方式：**

| 方式 | 操作 | 版本号 |
|---|---|---|
| 自动 | 修改并推送 `version.txt` | 直接取文件里的值 |
| 手动 | Actions → 「打包标签打印程序」→ Run workflow | 填 `1.0.3` 指定；留空则自动迭代修订号 |

工作流会自动：写入版本号到源码与 exe 文件属性 → 生成图标 → PyInstaller 打包 →
**校验产物目录结构**（根目录只允许启动文件 / `data/` / `runtime/`，不符直接失败）→
预建 `data/templates/` → 压缩为 `BoxLabelPrinter_vX.Y.Z.zip` →
**自动创建 GitHub Release 并附上安装包** →
回写版本号（带 `[skip ci]`，避免循环触发）→ 只保留最新 2 条运行记录。

> Release 资产名必须用 ASCII：GitHub 会静默剥掉资产名里的中文。
>
> 目录归集依赖 PyInstaller 6.x 的 `contents_directory`（见 `标签打印.spec`）。
> 5.x 的 bootloader 只认 exe 同目录的 DLL，**不能简单把文件移进子目录**。

**本地打包**（需 Python 3.8.10 32 位）：

```bat
build.bat
```

产物在 `dist\标签打印\`。

---

## 更换程序图标

三种「图标」对应三个不同文件：

| 想改什么 | 改哪个文件 | 生效范围 |
|---|---|---|
| **桌面快捷方式 / exe 文件图标** | `assets/logo.ico` | 资源管理器、任务栏、桌面快捷方式（由 `标签打印.spec` 的 `icon=` 在打包时嵌入 exe） |
| 窗口标题栏 / 侧边栏 LOGO | `assets/logo.png`（256×256） | 程序窗口内部 |
| 单台电脑临时换 LOGO | `data/custom_logo.png` | 仅窗口内；连点侧边栏 LOGO 10 次即可更换，**不改变 exe 图标** |

> ⚠️ **不要直接替换 `logo.ico` / `logo.png`**：`build.bat` 和 GitHub Actions 打包前
> 都会运行 `tools/make_icons.py` 重新生成，你改的会被覆盖回默认图。
>
> ✅ **正确做法**：把图片另存为 **`assets/logo_source.png`**。脚本会自动居中裁成
> 正方形、缩放到 256，并生成含 7 种尺寸（16～256）的 ico 与 png。
> 建议源图为正方形、边长 ≥ 256px、PNG 带透明通道。改完重新打包，
> exe 图标和窗口 LOGO 会一起更新。

**关于是否提交源图**：希望 GitHub Actions 打包出的安装包也用新图标，就把
`logo_source.png` 一起提交到仓库；只想本地打包生效则不必提交（可自行加进 `.gitignore`）。
仓库里没有该文件时，脚本仍绘制内置默认蓝色标签图，行为不变。

> 桌面快捷方式若仍显示旧图标，是 Windows 图标缓存，重建快捷方式或刷新缓存即可。

---

## 软件更新（可选）

「设置 → 系统设置」里填仓库地址（`owner/repo`）并勾选「启动时自动检查更新」。
检测到新版本时版本号旁出现红点，点「下载更新」获取更新包，解压替换同名文件即可
（`data/` 数据目录不受影响）。仓库地址留空则完全离线。

---

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 / 运行时 | Python 3.8.10 (x86) |
| 界面 | PyQt5 5.15.10（无边框窗口、自绘图标与按钮） |
| 数据 | SQLite（主库 + 按年分库）、openpyxl 3.1.2 |
| 打印 | BarTender 10.0+ COM（pywin32 306） |
| 打包 | PyInstaller 6.11.1（onedir + `contents_directory=runtime` / 32 位 / Win7 兼容） |
| 图标 | Pillow 9.5.0（仅构建期生成资源） |

---

<div align="center">

**绿色免安装 · 完全离线 · 不改动打印模板**

[⬇ 下载最新版本](https://github.com/ylqcxwl/box-label-printer/releases/latest) · [🐛 反馈问题](https://github.com/ylqcxwl/box-label-printer/issues)

</div>
