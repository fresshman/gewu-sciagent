# 论文成品（PDF 快照）

本目录存放**可直接翻阅**的论文成品，供评审在不安装 TeX、不运行链路的情况下评估成稿质量。

`output/` 下的运行产物在 `.gitignore` 内（含本机绝对路径），clone 后为空；因此把编译结果
与对应源文件在此留了一份快照。它与 `docs/verification/*.json` 是同一思路：**给评委看得见的东西，
同时把"它从哪来"写清楚**。

## 两份 PDF 对应两条不同的主张，数值不可互比

| 目录 | 数据来源 | 用途 | 能否被第三方独立重跑 |
|---|---|---|---|
| `coal_report/` | 外部未发表煤项目的**真实** LIBS 数据与权重（留在本人本机） | 证明方法在真实数据上有效：5 折 RMSE `214.57 ± 25.71` kcal/kg | 否（依赖私有资产），但全部指标可由落盘预测值重算 |
| `min_case/` | `gewu/demo/synth.py` 的**合成**光谱 | 证明七阶段链路能从零跑通、数值能复算：`73.03 ± 10.17` kcal/kg | 是（`python scripts/run_min_case.py`） |

`214.57` 与 `73.03` 是不同数据、不同任务难度下的数字，**禁止并列比较或相互"提升"换算**。

## 文件清单

| 文件 | 字节 | 页 | 内容指纹 |
|---|---:|---:|---|
| `coal_report/main.tex` | 13570 | — | 源 sha256 `08890a7efe72d709` |
| `coal_report/main.pdf` | 270365 | 7 | `da35a1b09ca88960` |
| `coal_report/coal_fold0_pred_true_20261028-121746.pdf` | 21992 | 1 | `df0ef2ae405bc5cb` |
| `coal_report/coal_5fold_rmse_20261028-121844.pdf` | 19248 | 1 | `592ed3c7ce0ff4aa` |
| `min_case/main.tex` | 5776 | — | 源 sha256 `fdab12d68004d71c` |
| `min_case/main.pdf` | 197903 | 3 | `5b909ef5faf94698` |

同目录另有 `min_case/main.log`（tectonic 编译日志，20 KB），留作「0 error / 0 缺字 / 0 overfull」
的原始证据；它不含本机绝对路径，可安全入库。

PDF 的「内容指纹」不是文件二进制哈希，而是提取正文、压缩空白、把生成日期
（`YYYY-MM-DD`）归一为 `<DATE>` 后的 sha256 前 16 位（`gewu.latex_build.pdf_text_fingerprint`）。
这样做的两个理由都是实测出来的：

1. PDF 内嵌 `/CreationDate`，**同一个 `.tex` 连编两次，二进制哈希必然不同，而正文完全一致**。
   用二进制哈希做快照比对会天天报"漂移"，反而失去意义；
2. 论文封面带生成日期，跨天重跑会改这一个字符串。日期变了不等于结论变了，故归一化后再比对。

`.tex` 是纯文本，直接用文件 sha256。

两张图是论文正文引用的矢量插图（fold0 预测-真实散点、5 折 RMSE 柱状），随 `main.tex` 一起留档，
否则这份 `.tex` 无法独立编译。

## 编译确定性（实测）

| 对象 | 二进制哈希（两次编译） | 内容指纹 |
|---|---|---|
| `min_case` | `d9f2efe9a5c1` / `b5585732bbd5`（不同） | 均 `5b909ef5faf94698` |
| `coal_report` | `3bc4d6a8cb1d` / `de99ab7a46f2`（不同） | 均 `da35a1b09ca88960` |

即：**排版结果可复现，字节不可复现**。校验层因此只比对文本与关键数值，不比对文件哈希。
上表两份 PDF 的指纹与本目录快照一致，说明快照未过期。

## 怎么重新生成

```bash
# 真实课题（需本机有 output/documents/coal_report/main.tex 及其插图）
python -c "from gewu.latex_build import build; print(build('output/documents/coal_report/main.tex'))"

# 合成课题（完整重跑，含重新编译）
python scripts/run_min_case.py --offline --emit-snapshot

# 只编译已存在的 tex
python -m gewu.latex_build output/min_case/report/main.tex
```

引擎：`tectonic 0.17.0`（单文件，无需 TeX Live）。`gewu.latex_build` 会依次探测
`GEWU_LATEX_ENGINE` → `PATH` → 常见安装位置；找不到引擎时返回 `status="no_engine"`，
**不会伪造成功**。

编译判据不是「进程退出码 0」，而是三条同时成立：无 `!` 开头的 TeX error、
无 `Missing character`（中文掉字）、PDF 文件非空。日志里的 `overfull hbox` 单独计数，
本次两份均为 0。

## 编译过程中修掉的三个真问题

留档以免后来者重踩：

1. **`.tex` 用 `article` + `inputenc/fontenc` 写中文**：XeLaTeX 下每个汉字都报
   `Missing character` 并被丢弃，**编译"成功"但 PDF 正文空白**。已改为 `ctexart`。
   现在 `gewu/demo/lint_tex.py` 会在编译前直接拦下这种源文件。
2. **三段超宽行**（`Overfull \hbox` 最大 135pt）：长公式与长路径没有断行点，文字被切到页面外。
   长公式改为「记逐折差值为 … 其五元组为 …」的分句，路径改用 `\path{}`（可在 `/` 处断行）。
3. **Markdown 残留**：模板里 `标签只在**样**级可得` 直接进了 LaTeX，渲染成 `**样 **`。
   已改 `\textbf{样}`，并把 Markdown 残留纳入 `lint_tex` 的检查项。

## 公开边界

- 真实课题的 PDF 只含**聚合指标**（5 折 RMSE、逐袋预测值、消融表），
  不含原始光谱、模型权重或数据文件；这些指标已另行公开在 `handoff_4_improver.json`
  与 `docs/verification/` 中。
- 模型与数据仍留在本机外部项目，不入库、不上云。

## 双源漂移风险（已知，未消除）

`main.tex` 是唯一真源，PDF 是它的派生物。本目录的 `.tex` 是**快照**，不是运行时会读取的文件；
若日后修改了 `gewu/demo/report.py` 模板并重跑，`output/` 下的 tex/pdf 会更新，而本目录不会自动跟随。

防漂移手段是校验而不是自动同步：

- 最小课题：`gewu/demo/verify.py` 第 10 层会检查 `output/min_case/report/main.pdf`
  是否存在、可解析、正文含 claims 里的关键数值——**旧 PDF 冒充新结果会被判 FAIL**；
- 真实课题：`scripts/e2e_smoke_test.py` 同样校验 PDF 与关键数字。

本目录更新时机：仅当论文内容确有变更、且重新编译通过后，手动刷新并同步上表哈希。
