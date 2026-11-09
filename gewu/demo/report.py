"""最小课题的论文与断言生成（LaTeX + claims）。

设计原则
--------
* **数值只从结果字典取**，模板里不写任何常量数字，避免"改一次实验、论文还留旧数"；
* 每条数值断言都带 ``source``（文件 + JSON Pointer），供校验器逐条回溯；
* 论文标题与摘要首句显式声明这是**合成数据**演示，防止读者误当成真实煤样结论。
"""
from __future__ import annotations

from .mil_lite import ARM_LABELS

# 引用（真实存在、可被 D1 核验；仅作方法背景，不用于支持合成实验结论）
REFERENCES = [
    {
        "key": "li2014pls",
        "arxiv_id": "1402.2062",
        "doi": "10.1016/j.sab.2014.06.017",
        "title": "A model combining spectrum standardization and dominant factor based "
                 "partial least square method for carbon analysis in coal by "
                 "laser-induced breakdown spectroscopy",
        "bib": "Y. Li, et al. A model combining spectrum standardization and dominant "
               "factor based partial least square method for carbon analysis in coal by "
               "LIBS. \\textit{Spectrochimica Acta Part B}, 2014. "
               "DOI: 10.1016/j.sab.2014.06.017",
    },
    {
        "key": "ilse2018mil",
        "arxiv_id": "1802.04712",
        "doi": "",
        "title": "Attention-based Deep Multiple Instance Learning",
        "bib": "M. Ilse, J. Tomczak, M. Welling. Attention-based Deep Multiple Instance "
               "Learning. \\textit{ICML}, 2018. arXiv:1802.04712",
    },
    {
        "key": "yan2023coal",
        "arxiv_id": "",
        "doi": "10.3390/app13148158",
        "title": "Rapid Classification and Quantification of Coal by Using Laser-Induced "
                 "Breakdown Spectroscopy and Machine Learning",
        "bib": "Yan, et al. Rapid Classification and Quantification of Coal by Using "
               "Laser-Induced Breakdown Spectroscopy and Machine Learning. "
               "\\textit{Applied Sciences}, 2023. DOI: 10.3390/app13148158",
    },
]


def _f(v: float, nd: int = 2) -> str:
    return f"{v:.{nd}f}"


def _p_expr(p: float) -> str:
    """p 值表述：小于 1e-4 时写 p<0.0001，避免出现 `p=0.0000` 这种"恰为零"的误读。"""
    return f"p={p:.4f}" if p >= 1e-4 else "p<0.0001"


def claim_list(res: dict, n_bags: int, n_instances: int) -> list[dict]:
    """把结果字典里被论文引用的每个数字登记为一条断言。"""
    s = res["summary"]
    t = res["paired_tests"]["hybrid_vs_plsr"]
    claims = [
        {
            "id": "n_bags",
            "text": f"合成数据集共 {n_bags} 个 bag、{n_instances} 条实例光谱",
            "value": n_bags,
            "unit": "bag",
            "source": {"file": "model/summary.json", "pointer": "/dataset/n_bags"},
            "tolerance": 0,
        },
        {
            "id": "hybrid_rmse",
            "text": f"本方法 5 折 RMSE 均值 {_f(s['hybrid']['rmse_mean'])} kcal/kg",
            "value": s["hybrid"]["rmse_mean"],
            "unit": "kcal/kg",
            "source": {"file": "model/summary.json", "pointer": "/summary/hybrid/rmse_mean"},
            "tolerance": 1e-6,
        },
        {
            "id": "hybrid_rmse_std",
            "text": f"5 折 RMSE 总体标准差 {_f(s['hybrid']['rmse_std'])} kcal/kg",
            "value": s["hybrid"]["rmse_std"],
            "unit": "kcal/kg",
            "source": {"file": "model/summary.json", "pointer": "/summary/hybrid/rmse_std"},
            "tolerance": 1e-6,
        },
        {
            "id": "plsr_rmse",
            "text": f"袋均谱 PLSR 基线 RMSE 均值 {_f(s['plsr']['rmse_mean'])} kcal/kg",
            "value": s["plsr"]["rmse_mean"],
            "unit": "kcal/kg",
            "source": {"file": "model/summary.json", "pointer": "/summary/plsr/rmse_mean"},
            "tolerance": 1e-6,
        },
        {
            "id": "mil_rmse",
            "text": f"仅做逐实例定标 + 池化（不加残差）RMSE {_f(s['mil']['rmse_mean'])} kcal/kg",
            "value": s["mil"]["rmse_mean"],
            "unit": "kcal/kg",
            "source": {"file": "model/summary.json", "pointer": "/summary/mil/rmse_mean"},
            "tolerance": 1e-6,
        },
        {
            "id": "improvement_pct",
            "text": f"相对 PLSR 基线降低 {_f(res['improvement_pct'])}%",
            "value": res["improvement_pct"],
            "unit": "%",
            "source": {"file": "model/summary.json", "pointer": "/improvement_pct"},
            "tolerance": 1e-3,
        },
        {
            "id": "paired_t",
            "text": f"逐折配对 t 检验 t = {_f(t['t'])}",
            "value": t["t"],
            "unit": "",
            "source": {"file": "model/summary.json", "pointer": "/paired_tests/hybrid_vs_plsr/t"},
            "tolerance": 1e-3,
        },
        {
            "id": "paired_p",
            "text": f"配对 t 检验 {_p_expr(t['p'])}",
            "rendered": "<0.0001" if t["p"] < 1e-4 else f"{t['p']:.4f}",
            "value": t["p"],
            "unit": "",
            "source": {"file": "model/summary.json", "pointer": "/paired_tests/hybrid_vs_plsr/p"},
            "tolerance": 1e-5,
        },
        {
            "id": "hybrid_r2",
            "text": f"5 折平均 R^2 = {_f(s['hybrid']['r2_mean'], 3)}",
            "value": s["hybrid"]["r2_mean"],
            "unit": "",
            "source": {"file": "model/summary.json", "pointer": "/summary/hybrid/r2_mean"},
            "tolerance": 1e-6,
        },
    ]
    for i, v in enumerate(s["hybrid"]["per_fold_rmse"]):
        claims.append(
            {
                "id": f"fold{i}_rmse",
                "text": f"第 {i} 折本方法 RMSE = {_f(v)} kcal/kg",
                "value": v,
                "unit": "kcal/kg",
                "source": {
                    "file": "model/summary.json",
                    "pointer": f"/summary/hybrid/per_fold_rmse/{i}",
                },
                "tolerance": 1e-6,
            }
        )
    return claims


TEX_TEMPLATE = r"""% 由 gewu 最小课题链路自动生成 —— 请勿手工修改，改模板后重跑 scripts/run_min_case.py
% 编译：xelatex main.tex（使用 ctexart 以支持中文）
\documentclass[11pt,a4paper,UTF8]{ctexart}
\usepackage{geometry}
\usepackage{booktabs}
\usepackage{amsmath}
\usepackage{hyperref}
\geometry{margin=2.5cm}
\title{多示例学习 + LIBS 热值预测\\[2pt]\large 合成数据上的端到端链路验证报告}
\author{格物 (Gewu) 最小课题自动链路}
\date{__DATE__}
\begin{document}
\maketitle

\section*{摘要}
\noindent\textbf{本报告的全部数值来自合成光谱数据，用于验证「检索—复现—改进—成稿—投稿—沉淀」
链路可自主跑通，不代表真实煤样的精度结论。}
在 __N_BAGS__ 个 bag（共 __N_INST__ 条实例光谱）上，袋均谱 PLSR 基线 RMSE 为
$__PLSR__$ kcal/kg；逐实例定标后池化（MIL）为 $__MIL__$ kcal/kg；进一步叠加强度上尾残差
（本方法）为 $__HYB__ \pm __HYB_SD__$ kcal/kg，相对基线降低 $__GAIN__\%$。
逐折配对 $t$ 检验 $t(__DF__)=__T__$、$__P__$，其中 __NSIG__ 折方向为改进。

\section{引言}
激光诱导击穿光谱（LIBS）用于煤质快速分析时，样品以「大颗粒堆积」形式被烧蚀：
一个煤样对应多条光谱（多示例），标签只在\textbf{样}级可得，单条光谱没有独立标签。
这正是多示例学习（MIL）的设定\cite{ilse2018mil}。
经典做法是把一个样品的多条光谱先平均成一条再回归\cite{li2014pls,yan2023coal}，
但平均会把颗粒尺度的差异抹平——少数粗颗粒主导信号，平均后这部分信息被稀释。

本文的贡献不在提出新网络，而是给出一条\textbf{可被第三方独立重跑}的最小链路：
数据可合成、模型只依赖 numpy/scikit-learn、每个数字都能回溯到 JSON Pointer。

\section{方法}
\subsection{数据生成机制}
合成数据把「成分」与「颗粒尺度」显式分离：
\begin{equation}
  \mathbf{x}_i = a_i \cdot \bigl[\, \mathbf{b} + \sum_k c_k \mathbf{p}_k \,\bigr] \cdot (1+\varepsilon_i) + \mathbf{n}_i,
  \qquad a_i = 1 + h z_i,
\end{equation}
其中 $c$ 为成分（逐实例可见），$h$ 为样品级颗粒异质性（\textbf{仅 bag 级可见}），
标签 $y = 3000 + 1200c_0 + 900c_1 + 600c_2 + 1400h + \mathcal{N}(0,20)$。
关键性质：$\overline{a_i} \to 1$ 使袋均谱几乎抹去 $h$，而上尾 $\max_i a_i$ 保留 $h$。

\subsection{三个对照臂}
\begin{itemize}
  \item \textbf{PLSR 基线}：袋均谱 $\to$ PLSR（$n_c=6$）；
  \item \textbf{MIL 直接}：逐实例谱形定标 $\mathbf{x}_i/\overline{\mathbf{x}_i}$ $\to$ 实例 PLS $\to$
        LSE 池化（$\beta$ 由内层 CV 选，$\beta=0$ 即均值）；
  \item \textbf{本方法}：MIL 直接 + 以强度池化统计量（max/p90/std/极差/实例数，共 7 维）回归残差的 Ridge。
\end{itemize}

\section{实验设置}
5 折交叉验证，\textbf{按 bag 切分}（同一 bag 的实例不会跨折，否则泄漏）。
$\beta$ 与 Ridge 的 $\alpha$ 只在内层 4 折的折外预测上选择；残差特征同样取折外预测，
避免自拟合乐观偏差。随机种子固定，重复运行结果逐位一致。

\section{结果}
\begin{table}[h]
\centering
\caption{5 折交叉验证（RMSE，kcal/kg）}
\begin{tabular}{lccc}
\toprule
臂 & 均值 & 总体标准差 & 逐折 \\
\midrule
PLSR 基线 & __PLSR__ & __PLSR_SD__ & __PLSR_FOLDS__ \\
MIL 直接 & __MIL__ & __MIL_SD__ & __MIL_FOLDS__ \\
本方法 & __HYB__ & __HYB_SD__ & __HYB_FOLDS__ \\
\bottomrule
\end{tabular}
\end{table}

本方法 5 折平均 $R^2=__R2__$。逐折配对 $t$ 检验（本方法 $-$ 基线）：
$t(__DF__)=__T__$，$__P__$，95\% 置信区间 $[__CI_LO__, __CI_HI__]$；
Wilcoxon 检验 $p=__WILCOX__$（$n=5$ 时双侧最小可达 $0.0625$，本身不显著，两种检验结论一并报告）。

\section{消融与讨论}
在三臂对比中，去掉残差（MIL 直接）比基线低 $__G1__\%$，再加残差再低 $__G2__\%$。
这说明本数据上的增益主要来自两点：\textbf{逐实例定标}把尺度与成分解耦；
\textbf{强度上尾统计量}回收了被袋均抹掉的 $h$；残差模型只吃基线看不到的量，刻意不放入与 MIL 输出共线的预测统计量（实测会过拟合）。
内层 CV 选出的 $\beta$ 为 $__BETAS__$——若 $\beta=0$ 占多数，应如实解读为
「该数据上均值池化已足够，增益不来自高阶池化」，而不是宣称 LSE 有效。

\paragraph{适用边界。}合成数据不含基体效应、自吸收与仪器漂移，绝对误差量级不可外推到真实煤样；
本报告证明的是\textbf{机制与链路}，真实精度以存档课题的实测指标为准。

\section{结论}
在零外部数据依赖的前提下，七阶段链路可从零跑出可复现的数值、可回溯的断言与可编译的成稿，
为「成果可复现性」提供了第三方可独立执行的证据。

\begin{thebibliography}{9}
__BIB__
\end{thebibliography}
\end{document}
"""


def render_tex(res: dict, n_bags: int, n_instances: int, date: str) -> str:
    s = res["summary"]
    t = res["paired_tests"]["hybrid_vs_plsr"]
    ci = t.get("ci95") or [0.0, 0.0]
    wil = (t.get("wilcoxon") or {}).get("p")
    n_sig = sum(1 for d in t["deltas"] if d < 0)
    g1 = (s["plsr"]["rmse_mean"] - s["mil"]["rmse_mean"]) / s["plsr"]["rmse_mean"] * 100
    g2 = (s["mil"]["rmse_mean"] - s["hybrid"]["rmse_mean"]) / s["plsr"]["rmse_mean"] * 100

    bib = "\n".join(f"\\bibitem{{{r['key']}}} {r['bib']}" for r in REFERENCES)

    values = {
        "__DATE__": date,
        "__N_BAGS__": str(n_bags),
        "__N_INST__": str(n_instances),
        "__PLSR__": _f(s["plsr"]["rmse_mean"]),
        "__PLSR_SD__": _f(s["plsr"]["rmse_std"]),
        "__MIL__": _f(s["mil"]["rmse_mean"]),
        "__MIL_SD__": _f(s["mil"]["rmse_std"]),
        "__HYB__": _f(s["hybrid"]["rmse_mean"]),
        "__HYB_SD__": _f(s["hybrid"]["rmse_std"]),
        "__GAIN__": _f(res["improvement_pct"]),
        "__G1__": _f(g1),
        "__G2__": _f(g2),
        "__R2__": _f(s["hybrid"]["r2_mean"], 3),
        "__T__": _f(t["t"]),
        "__DF__": str(t["df"]),
        "__P__": _p_expr(t["p"]),
        "__CI_LO__": _f(ci[0]),
        "__CI_HI__": _f(ci[1]),
        "__WILCOX__": "n/a" if wil is None else f"{wil:.4f}",
        "__NSIG__": str(n_sig),
        "__BETAS__": ", ".join(f"{b:g}" for b in res["beta_selected"]),
        "__PLSR_FOLDS__": " / ".join(_f(v) for v in s["plsr"]["per_fold_rmse"]),
        "__MIL_FOLDS__": " / ".join(_f(v) for v in s["mil"]["per_fold_rmse"]),
        "__HYB_FOLDS__": " / ".join(_f(v) for v in s["hybrid"]["per_fold_rmse"]),
        "__BIB__": bib,
    }
    text = TEX_TEMPLATE
    for k, v in values.items():
        text = text.replace(k, v)
    leftover = [k for k in values if k in text]
    if leftover:  # pragma: no cover - 模板改错时的保护
        raise ValueError(f"模板占位符未替换: {leftover}")
    return text


__all__ = ["REFERENCES", "claim_list", "render_tex", "ARM_LABELS"]
