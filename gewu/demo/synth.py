"""合成 LIBS 数据集生成器（零下载、确定性、可复现）。

为什么需要它
------------
真实课题（LIBS 大颗粒原煤热值）依赖未发表的私有数据与权重，评审无法独立运行。
本模块生成一个**已知生成机制**的替身数据集，用来证明整条链路能自主跑完，并且
可以用来检验 MIL（多示例学习）是否真的比"袋均谱回归"更强——因为在合成数据里
我们知道真值机制，可以验证模型抓到的是不是它声称抓到的东西。

生成机制（刻意做成 MIL 才有优势）
--------------------------------
每个 bag（一个煤样）有 K 个颗粒实例，每实例一条光谱::

    spec_i(λ) = a_i · [ b(λ) + Σ_k c_k · peak_k(λ) ] · (1 + ε) + shot

其中:

* ``c`` 为成分向量（挥发分/灰分/水分），决定谱峰相对强度 —— **逐实例可见**；
* ``a_i = 1 + h · z_i`` 为颗粒尺度因子，``z_i ~ N(0,1)`` 截断，``h`` 为该 bag 的
  颗粒异质性（**仅 bag 级隐变量，逐实例不可辨识**）；
* 热值真值::

      y = 3000 + 1200·c₀ + 900·c₁ + 600·c₂ + 1100·h + N(0, 25)

关键性质：``mean_i(a_i) → 1``，所以**袋均谱几乎抹掉 h**（残留标准差 ∝ h/√K），
而 ``max_i(a_i) → 1 + h·E[max z]``，**上尾保留了 h**。因此任何"先平均再回归"的
方法在该数据上都有系统性损失，而实例级池化（max / LSE）能补回来。

这不是为了"造一个 MIL 必胜的数据集"——它对应真实场景里"大颗粒煤样中少数高反射
颗粒主导信号、袋均后信息被稀释"的物理直觉；只是把该机制写成了可验证的公式。
生成器把真实机制写进 ``data_card.json``，评审可据此判断结论的适用边界。
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import numpy as np

from .truth_guard import truth_from_measured

# 通道数（真实 LIBS 常见 2k-8k，这里取小值以保证秒级跑完；机制与通道数无关）
N_CHANNELS = 384
# 谱峰中心（以通道比例表示），对应 6 个特征谱线
PEAK_POS = (0.12, 0.24, 0.37, 0.51, 0.68, 0.83)
# 谱峰宽度
PEAK_WIDTH = 0.018

# 生成机制常量（同时写入 data_card，供评审核对）
COEF_COMPOSITION = (1200.0, 900.0, 600.0)   # c0/c1/c2 → kcal/kg
COEF_HETEROGENEITY = 1100.0                  # h → kcal/kg
INTERCEPT = 3000.0
LABEL_NOISE = 25.0
INSTANCE_NOISE = 0.02                        # 逐实例乘性噪声
SHOT_NOISE = 0.004                           # 加性散粒噪声
COMPOSITION_JITTER = 0.06                    # 逐实例成分微扰（真实样品内不均匀）


def _grid() -> np.ndarray:
    return np.linspace(0.0, 1.0, N_CHANNELS, dtype=np.float64)


def _peak_matrix() -> np.ndarray:
    """(n_peaks, n_channels) 的高斯谱峰基。"""
    x = _grid()
    return np.stack(
        [np.exp(-0.5 * ((x - p) / PEAK_WIDTH) ** 2) for p in PEAK_POS], axis=0
    )


def _basis() -> np.ndarray:
    """连续背景 + 6 条谱峰 → (6, n_channels) 基矩阵。

    前 3 条主峰承载成分信息，后 3 条为次要峰（同样由成分线性混合）。
    """
    x = _grid()
    continuum = 0.25 + 0.15 * np.exp(-x / 0.35)
    peaks = _peak_matrix()
    # 6 条峰的权重矩阵：把 3 维成分映射到 6 条峰
    mix = np.array(
        [
            [0.9, 0.2, 0.1],
            [0.5, 0.6, 0.1],
            [0.2, 0.9, 0.2],
            [0.3, 0.3, 0.7],
            [0.6, 0.1, 0.5],
            [0.1, 0.7, 0.4],
        ],
        dtype=np.float64,
    )  # (6 peaks, 3 comps)
    return np.vstack([continuum[None, :], mix.T @ peaks])  # (1+3, L)


def make_dataset(
    n_bags: int = 70,
    seed: int = 20261109,
    min_instances: int = 5,
    max_instances: int = 12,
) -> dict:
    """生成内存态数据集。

    返回 ``{"bags": [{"bag_id","y","h","c","scales","spectra"}...], "meta": {...}}``。
    """
    rng = np.random.default_rng(seed)
    basis = _basis()
    continuum, comp_basis = basis[0], basis[1:]  # (L,), (3, L)

    bags = []
    for b in range(n_bags):
        c = rng.uniform(0.20, 0.80, size=3)
        h = float(rng.uniform(0.05, 0.45))
        k = int(rng.integers(min_instances, max_instances + 1))

        z = rng.standard_normal(k)
        scales = np.clip(1.0 + h * z, 0.35, 2.6)

        spectra = np.empty((k, N_CHANNELS), dtype=np.float64)
        for i in range(k):
            ci = c * (1.0 + COMPOSITION_JITTER * rng.standard_normal(3))
            shape = continuum + ci @ comp_basis            # (L,)
            amp = scales[i] * (1.0 + INSTANCE_NOISE * rng.standard_normal())
            spectra[i] = amp * shape + SHOT_NOISE * rng.standard_normal(N_CHANNELS)

        y = (
            INTERCEPT
            + float(np.dot(COEF_COMPOSITION, c))
            + COEF_HETEROGENEITY * h
            + LABEL_NOISE * float(rng.standard_normal())
        )
        bags.append(
            {
                "bag_id": f"bag{b:03d}",
                "y": round(y, 4),
                "h": h,
                "c": [round(float(v), 6) for v in c],
                "scales": scales,
                "spectra": spectra,
            }
        )

    meta = {
        "n_bags": n_bags,
        "n_channels": N_CHANNELS,
        "seed": seed,
        "generator_version": "1.0.0",
        "mechanism": {
            "label_formula": "y = 3000 + 1200*c0 + 900*c1 + 600*c2 + 1100*h + N(0,25)",
            "instance_formula": "spec_i = (1 + h*z_i) * [continuum + c·peaks] * (1+eps) + shot",
            "latent": ["c0:c3 成分（逐实例可见）", "h 颗粒异质性（仅 bag 级）"],
            "why_mil": "mean_i(1+h*z_i) → 1，袋均谱抹掉 h；max_i 保留上尾，故实例池化可回收 h",
        },
        "known_limits": [
            "合成数据不含基体效应、自吸收、仪器漂移，不可外推到真实煤样精度",
            "结论仅说明方法机制成立，不代表真实 LIBS 数据上的 RMSE 量级",
        ],
    }
    return {"bags": bags, "meta": meta}


def _write_csv(path: Path, spectrum: np.ndarray) -> None:
    x = _grid()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["wavelength", "intensity"])
        for xi, yi in zip(x, spectrum):
            w.writerow([f"{xi:.6f}", f"{yi:.6f}"])


def materialise(dataset: dict, root: Path) -> dict:
    """落盘为真实数据集目录，返回写入清单。

    目录结构（与真实课题 ``data/`` 同构，便于复用同一套读取逻辑）::

        root/
          bags/bag000/spec_00.csv ...
          labels.json          # {"bag000": 5xx?, ...}
          data_card.json       # 生成机制与已知边界
          split.json           # 5 折 bag 级划分（固定种子）
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    labels: dict[str, float] = {}
    bag_dirs: list[str] = []
    n_files = 0
    for bag in dataset["bags"]:
        bid = bag["bag_id"]
        bdir = root / "bags" / bid
        for i, spec in enumerate(bag["spectra"]):
            _write_csv(bdir / f"spec_{i:02d}.csv", spec)
            n_files += 1
        labels[bid] = float(bag["y"])
        bag_dirs.append(bid)

    # 分层 5 折：按 y 排序后蛇形分配，保证各折标签分布接近（避免切分运气主导结论）
    order = sorted(labels, key=lambda k: labels[k])
    folds: list[list[str]] = [[] for _ in range(5)]
    for idx, bid in enumerate(order):
        j = idx % 5 if (idx // 5) % 2 == 0 else 4 - (idx % 5)
        folds[j].append(bid)

    (root / "labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (root / "split.json").write_text(
        json.dumps({"n_folds": 5, "seed": dataset["meta"]["seed"], "folds": folds},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    card = dict(dataset["meta"])
    card["n_files"] = n_files
    card["bag_ids"] = bag_dirs
    card["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (root / "data_card.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"root": str(root), "n_bags": len(bag_dirs), "n_files": n_files,
            "n_folds": 5}


def load_bags(root: Path) -> tuple[list[np.ndarray], np.ndarray, list[str], dict]:
    """从落盘目录读回 ``(实例矩阵列表, 标签, bag_id 列表, data_card)``。

    读取真实的 CSV 文件（而不是复用内存对象），这样"链路"包含真实 I/O，
    任何落盘/解析错误都会在这一步暴露，而不是被内存态掩盖。
    """
    root = Path(root)
    card = json.loads((root / "data_card.json").read_text(encoding="utf-8"))
    labels = json.loads((root / "labels.json").read_text(encoding="utf-8"))

    mats, ys, ids = [], [], []
    for bid in card["bag_ids"]:
        files = sorted((root / "bags" / bid).glob("spec_*.csv"))
        if not files:
            raise FileNotFoundError(f"{bid} 下没有光谱 CSV")
        rows = []
        for f in files:
            arr = np.loadtxt(f, delimiter=",", skiprows=1)
            rows.append(arr[:, 1])
        mats.append(np.stack(rows, axis=0))
        ys.append(float(labels[bid]))
        ids.append(bid)
    return mats, np.asarray(ys, dtype=np.float64), ids, card


def split_folds(root: Path) -> list[list[str]]:
    data = json.loads((Path(root) / "split.json").read_text(encoding="utf-8"))
    return data["folds"]


def load_truth(root: Path):
    """读回 ``labels.json`` 并**声明来源** —— 真值隔离的唯一合法入口。

    与 ``load_bags`` 返回的裸数组不同，这里返回 `TruthLabels`（带 source），
    `run_cv` 只接受这种类型。这样「标签是从哪来的」在类型层面就留了痕，
    而不是靠调用方自觉写对。
    """
    p = Path(root) / "labels.json"
    labels = json.loads(p.read_text(encoding="utf-8"))
    return truth_from_measured(
        {k: float(v) for k, v in labels.items()},
        source=str(p.resolve()),
        unit="kcal/kg",
    )
