# PDF 编译链路取证（2026-11-09）

> 一句话结论：本项目此前所有「论文已生成」的说法，实质都停在「`.tex` 文本已写出」。
> 评审拿到的只是一份 245 行源码，无法翻阅。本次接入真实 TeX 编译，把两篇论文都变成
> 可打开、可核对、可复算的 PDF，并把「编译是否成功」从自述变成可校验的一层。

## 一、为什么这是硬缺口而不是锦上添花

改动前 `handoff_5_writer.json` 里的编译状态是**硬编码**的：

```json
{"pdf_compiled": false, "reason": "本机无 TeX 发行版；已做结构 lint（环境配对/括号/cite-bib 对应）",
 "instruction": "cd ... && xelatex main.tex"}
```

问题有三层：

1. `pdf_compiled: false` 不是一个测量结果，而是一句写死的话——即使某天编译成功了它也仍写 `false`；
2. `instruction` 把复现责任推给读者，等于承认「本仓库自己不闭环」；
3. 结构 lint 只能查括号与环境配对，**查不出中文丢字**——而后者恰恰是本次发现的真缺陷。

## 二、引擎选型与获取

| 选项 | 结论 |
|---|---|
| TeX Live 全量 | 数 GB，为两篇论文装全量不划算，且需写系统目录 |
| MiKTeX | Windows 可用，但按需弹窗安装，非交互环境不可控 |
| **tectonic 0.17.0** | **选用**：单文件、无需系统安装、按需从 CTAN 拉包、`-X compile` 幂等 |

实测体积与耗时：

| 项 | 实测值 |
|---|---|
| 发布包 `tectonic-0.17.0-x86_64-pc-windows-msvc.zip` | 21,060,223 B（约 20 MB） |
| 解压后 `tectonic.exe` | 51,538,432 B（约 49 MB） |
| 首次编译（拉 TeX bundle） | 约 6 分钟（含约 300 MB bundle 下载） |
| 之后每次编译 | 1.2 s（最小课题，见 `handoff_5_writer.json` 的 `duration_s`） |

引擎刻意**不入库**（49 MB 二进制进 Git 是灾难），装到用户级目录
`%LOCALAPPDATA%\gewu\tools\`，由 `gewu/latex_build.py:find_engine()` 按
「显式指定 → `PATH` → 常见安装位置」三级探测，可用 `GEWU_LATEX_ENGINE` 覆盖。

### 2.1 获取：一条命令，且校验有据

```bash
python scripts/fetch_tectonic.py --version 0.17.0
```

实测（2026-11-09，本机，冷缓存）：

| 阶段 | 实测 |
|---|---|
| 取元数据（GitHub Releases API） | 版本 `tectonic@0.17.0`，资产 `tectonic-0.17.0-x86_64-pc-windows-msvc.zip`，21,060,223 B |
| 下载 | 20.1 MB，全程约 26 s |
| sha256 校验 | `f61ce51f0b0ade10…` 与 API `asset.digest` 一致 |
| 解压安装 | `tectonic.exe` 51,538,432 B 写入 `%LOCALAPPDATA%\gewu\tools\` |
| 功能自检 | 实际执行 `tectonic --version` → `Tectonic 0.17.0` |
| 项目探测 | `find_engine()` → `tectonic`，路径即上述位置 |

**「装上了」不等于「能用」，所以第 5 步是执行而不是看文件**。再用这份新下载的二进制
编译一遍最小课题：`197,903 B`、`error=0 缺字=0 overfull=0`，内容指纹
`5b909ef5faf94698` 与入库快照**完全一致**（二进制哈希不同：`5e62958e19d2` vs
`d4356e6f42a0`）——即「一台没有 TeX 的机器，一条命令后能产出与仓库里那份可核对一致的 PDF」。

校验能力与边界（不夸大）：

| 情形 | 行为 |
|---|---|
| API 提供 `asset.digest` | 以之为期望值；**同源**校验，能发现传输损坏、版本/资产错配、资产在发布后被替换 |
| API 不可达 / 限流（403） | 回退脚本内钉住表；覆盖率仅 0.17.0 的 6 个平台包 |
| 两者都没有 | **拒绝安装**（退出码 1），提示 `--expect-sha256` 或 `--version` 或显式 `--allow-unverified` |
| 显式放弃校验 | 允许，但结果标记 `integrity.verified=false`、`signature=none`，不冒充「已校验」 |
| API 给了值但解析不了（如改成 md5） | **报错**，不静默降级到钉住表——否则「换了算法」会被当成「校验通过」 |

负向实测三条：给错 `--expect-sha256` → 退出码 1、目标目录为空（未落任何二进制）；
本地包不给版本也不给校验值 → 拒绝并列出三条出路；`--allow-unverified` → 安装成功但
`verified=false`。

> 诚实标注：GitHub 的 `asset.digest` 与下载包**同源**（同一个 HTTPS 来源），
> 它不是签名，**不构成对「GitHub 账号或发布流程本身被攻破」的防护**。本项目
> 没有做 GPG/签名验证（tectonic 也未发布 `.sha256` 或签名的校验文件——发布页
> 资产清单里没有这类文件，这是查证过的事实，不是未做）。
> 钉住表中只有 Windows 包经本机实下载复算一致；其余平台条目是「读取时的
> 发布方声明值缓存」，用于断网时拒绝被替换的资产，**不是第三方独立验证**。

## 三、两篇论文的真实编译结果

| 论文 | 页 | 字节 | error | 缺字 | overfull |
|---|---:|---:|---:|---:|---:|
| 真实课题 `docs/paper/coal_report/main.pdf` | 7 | 270,365 | 0 | 0 | 0 |
| 最小课题 `docs/paper/min_case/main.pdf` | 3 | 197,903 | 0 | 0 | 0 |

内容核对（不只看「有没有 PDF」，而是逐项确认正文里有该有的东西）：抽取 PDF 文本后
检查 `214.57`、`233.95`、`347.55`、`8.28`、`0.041`、`参考文献`、`Ilse`、`Spectrochimica`
全部命中；两张插图在页面上渲染清晰（fold0 预测-真实散点、5 折 RMSE 柱状）。

> 注：`page.get_images()` 返回 0 是正常现象——两图是 PDF **矢量**对象，不是位图，
> 要确认必须渲染页面看，不能只数图片对象。这一点最初差点被误判为「图没嵌进去」。

## 四、抓到并修掉的三类真问题

### 4.1 中文全丢，而退出码是 0

原 `main.tex` 导言区是 `\documentclass{article}` + `inputenc` + `T1 fontenc`。
用 XeLaTeX/tectonic 编译这份**中文**文档，结果：

```text
status        = compile_error
missing_glyphs= 13 处
样例          = Missing character: There is no 摘 ("6458) in font ec-lmbx12!
PDF 文本长度  = 30 字符（只剩 "LIBS 214.57 kcal/kg" 这类 ASCII）
```

这是本次最有价值的一条教训：**编译退出码正常、PDF 页数正常、文件大小正常，中文却全没了**。
若只用 `subprocess` 看 returncode，会得到一份「成功」的空壳论文。因此
`latex_build.parse_log()` 必须解析 `Missing character` 计数，并把它作为失败判据之一
（判据：缺字 > 0 即 `ok=False`，理由写进 `reason`）。

修复：改为 `\documentclass[11pt,a4paper,UTF8]{ctexart}`，去掉 `inputenc`/`fontenc`。
最小课题侧从一开始就生成 `ctexart`，但它此前**没有编译验证**，等于没验证过。

### 4.2 三处 overfull hbox（内容被切到页边外）

| 位置 | 原因 | 修法 |
|---|---|---|
| 统计检验段的逐折差值数组 | `$[-12.60, -3.96, \dots]$` 是整体数学模式，不可断行 | 拆成行内短片段或允许断行的写法 |
| β 敏感性段的两个花括号集合 | 同上，`$\{0.1, 0.3, \dots\}$` 一整个盒子 | 改为逐项列出，可断行 |
| 产物路径 | `\texttt{output/documents/coal\_report/metrics\_recomputed.json}` 无断点 | 改用 `\path{}`（hyperref），可在 `/` 处断行、下划线免转义 |

修前 3 处 overfull、修后 0 处。其中路径那一处，修前在 PDF 里渲染成
`py.output` 这种易误读的粘连，属于「能编译但读错」的隐蔽缺陷。

### 4.3 快照天天「漂移」

PDF 内嵌 `/CreationDate`，论文封面还印着生成日期。若用文件二进制哈希做快照比对，
**同一个 `.tex` 连编两次就报不一致**，这种校验会立刻失去意义。
故内容指纹定义为：抽取正文 → 压缩空白 → 把 `YYYY-MM-DD` 归一为 `<DATE>` → sha256 前 16 位。
`.tex` 是纯文本，仍用文件 sha256。

## 五、确定性实测

### 5.1 默认（不钉时间戳）

| 对象 | 两次编译的二进制哈希 | 两次编译的内容指纹 |
|---|---|---|
| `min_case` | `d9f2efe9a5c1` / `b5585732bbd5`（**不同**） | 均 `5b909ef5faf94698`（相同） |
| `coal_report` | `3bc4d6a8cb1d` / `de99ab7a46f2`（**不同**） | 均 `da35a1b09ca88960`（相同） |

PDF 内嵌 `/CreationDate`，所以默认下**排版结果可复现、字节能不同**。校验层因此只比对
内容指纹与关键数值，绝不比对文件哈希。

> 上表是**当时那一版** `main.tex` 的读数。论文后来新增了组件级消融一节（9 页，见
> `docs/verification/2026-11-09-component-ablation.md`），源文与 PDF 都变了，指纹自然随之改变：
> 当前 `coal_report` 两次默认编译为 `ceb63a1a3315` / `f5886837bef8`（仍不同），
> 内容指纹均 `d912711f93fbffe6`（仍相同）。**性质被重测复现，具体数值以 `docs/paper/README.md` 为准**，
> 这里保留旧读数是为了留下「同一性质在不同版本上重复成立」的记录。

### 5.2 钉住 `SOURCE_DATE_EPOCH` 后字节级也可复现（修正前一版结论）

前一版把「字节不可复现」写成了引擎的固有性质，这是**过宽的结论**。实测发现它只是
「默认没钉时间戳」的后果：给 `build(..., source_date_epoch=1600000000)`
（CLI 对应 `--source-date-epoch`），tectonic 会按该时刻写 PDF 元数据。

| 对象 | 两次编译的二进制哈希 | 内容指纹 | 字节 |
|---|---|---|---|
| `min_case` | 均 `924e52260285`（**相同**） | 均 `5b909ef5faf94698` | 均 197,903 |

另用小样例连编三次（同一 epoch）也得到完全相同的字节。故：

* 需要**第三方按文件哈希复核** → 钉 `SOURCE_DATE_EPOCH`；
* 只需要「排版可复现」 → 用内容指纹即可（不要求复核者钉同一时刻）。

校验层仍用内容指纹，因为不能要求每个复核者钉同一个 epoch；两者不是替代关系。

## 六、接入点：从「手工能编」到「链路自己会编」

本次没有停在「我这边编译成功」，而是把能力接进三个位置：

1. **工具层**：`gewu/latex_build.py`（引擎探测 / 编译 / 日志解析 / 缺字与 overfull 判定 / 内容指纹 / CLI）；
2. **智能体层**：MCP 工具 `compile_latex(path, engine, timeout)`，智能体不再只能打印「请手工 xelatex」；
   该 MCP 以脚本方式启动、`sys.path` 无仓库根，故用显式路径注入加载，不能裸 `import gewu`；
3. **链路层**：最小课题第 5 阶段自动编译，把真实 `error / missing_glyphs / overfull_hbox`
   计数写进 `compilation_status`；`verify.py` 新增第 10 层「PDF 成品」四项检查：

   - PDF 存在且可解析（不可解析即失败，不再静默跳过）；
   - 页数 > 0；
   - 正文含本次关键数值（探针取自 claims，整数与小数分别格式化，避免 `70` vs `70.00` 的假阴性）；
   - `docs/paper` 入库快照的内容指纹与本轮编译一致（防模板改了而快照悄悄过期）；
   - 未宣称编译成功时**不得残留旧 PDF**（防「上次的 PDF 冒充这次的结果」）。

配套负向测试（证明这层不是橡皮章）：伪造损坏 PDF、PDF 缺关键数值、快照被换成另一份内容，
三种情况均被精确报出。

## 七、两份论文的关系（易混淆，特此说明）

| | 存档版 `docs/paper/coal_report/main.tex` | 源头版 `coal-calorific-value/gewu_paper/` |
|---|---|---|
| 形态 | 单文件 245 行，自带摘要到结论 | 模块化 `\input sections/*.tex` + `refs.bib` + `figures/` |
| 用途 | 格物七阶段流水线的产出与取证对象 | 期刊投稿稿（作者侧维护） |
| 生成方式 | 一次性写就的留存稿，**无确定性生成器** | 人工/半自动维护 |

两者**不是同一份文档**，因此不存在「同步」问题；但数值必须不打架。抽检一致：
`214.57 ± 25.71`、PLSR 基线 `233.95 ± 17.95`、相对改善 `8.28%`、MIL 直接 `633.19 ± 122.55`、
复算偏差 `1.1e-5 kcal/kg`，两侧表述相同。

也正因为存档 tex 没有确定性生成器，4.1 的导言区修复只能落在**产物本身**；
`gewu/demo/report.py` 是目前唯一的确定性 LaTeX 生成器，它从一开始就用 `ctexart`，
并在 `gewu/demo/lint_tex.py` 里加了「有中文但没加载 ctex/xeCJK」的编译前拦截，
避免同一类错误在合成课题侧复发。

## 八、边界与未覆盖（不粉饰）

* **引擎不入库**：克隆后本机无 TeX 时，链路会诚实降级为 `pdf_compiled: false` + 原因，
  不伪造成功；此时想翻阅论文请看已入库的 `docs/paper/*.pdf` 快照，想自己重编则
  `python scripts/fetch_tectonic.py --version 0.17.0` 一条命令装引擎。
* **下载校验已补（第二轮）**：`scripts/fetch_tectonic.py` 以 GitHub API 的
  `asset.digest` 做 sha256 比对，装完再实际执行 `tectonic --version` 自检。
  残留边界有三条，都不粉饰：
  1. digest 与资产**同源**，不是签名，挡不住「GitHub 账号/发布流程被攻破」；
  2. tectonic 发布页本身**不提供** `.sha256` 或签名文件（已查证资产清单），
     所以「做签名验证」这条路在当前上游是走不通的，不是本项目偷懒；
  3. 钉住表里只有 Windows 包经本机实下载复算，其余平台是声明值缓存。
* **获取脚本只在 Windows 实测**：Linux/macOS 的资产选择逻辑有单测覆盖（纯字符串），
  但没有在那些平台真正下载安装过。
* **首次必须联网**：CTAN bundle 约 300 MB，离线环境无法首次编译（之后可离线）。
  已有可用的本地发行包时可用 `--archive` 走离线安装（配套 `--version` 或
  `--expect-sha256` 取期望值）。
* **只在 Windows 实测**：`find_engine()` 写了 Linux/macOS 的常见路径，但没有在那些平台跑过，
  不宣称跨平台可用。
* **未做 PDF↔tex 逐字符比对**：只核关键数值与页数，不做全文 diff——排版引擎会重排断行与连字，
  逐字符比对必然假阳性。
* **19 条编译单测里 6 条挂 `needs_engine`**：无引擎环境会跳过而非失败；其余纯逻辑用例
  （日志解析、缺字判定、无引擎降级、指纹归一化、可复现编译、CLI 退出码）始终可跑，
  保证判定逻辑本身被验证。获取脚本另有 **36 条逻辑用例**（含 1 条联网用例默认跳过）。
* **组件级消融仍未做**：与本文件无关，但同属未闭环项，参见 `2026-11-09-min-case.md` §8。

## 九、复现

```bash
# 0) 本机没有 TeX 时：一条命令装引擎（下载 + sha256 校验 + 功能自检）
python scripts/fetch_tectonic.py --version 0.17.0
python scripts/fetch_tectonic.py --check-only      # 只体检，不联网

# 1) 编译（自动探测引擎；也可 GEWU_LATEX_ENGINE=/path/to/tectonic）
python -m gewu.latex_build docs/paper/coal_report/main.tex
python -m gewu.latex_build docs/paper/min_case/main.tex
#    需要按文件哈希复核时钉住时间戳：
python -m gewu.latex_build docs/paper/min_case/main.tex --source-date-epoch 1600000000

# 2) 指纹与页数
python -c "from gewu.latex_build import pdf_text_fingerprint as f, pdf_page_count as p; \
print(p('docs/paper/coal_report/main.pdf'), f('docs/paper/coal_report/main.pdf'))"

# 3) 端到端（真实课题，含第 9 层 PDF 成品校验）
python scripts/e2e_smoke_test.py

# 4) 最小课题（含第 10 层 PDF 成品与快照比对）
python scripts/run_min_case.py --offline
```
