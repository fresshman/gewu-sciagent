import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import os

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "font.size": 11,
    "axes.titlesize": 12,
    "savefig.dpi": 300,
})

OUT = "F:/python-exercise/Industrial_LLM/langchain-learn/gewu-sciagent/openclaw/workspace/agents/gewu-director/output/figures"
os.makedirs(OUT, exist_ok=True)

# fold0 predictions (real torch inference via coal_infer.py predict-fold)
y_true = np.array([2931.0, 4138.0, 4231.0, 3622.0, 3403.0, 3518.0, 3379.0, 3972.0,
                   3892.0, 3644.0, 4099.0, 3398.0, 5714.0, 3593.0], dtype=float)
y_pred = np.array([2941.043457621015, 3891.2282208505876, 4073.5155923052907,
                   3634.85891105393, 3489.0633716830316, 3945.9813124022658,
                   3360.450630768836, 4103.85491608782, 3701.967672546781,
                   4018.718840449602, 4018.6377220487416, 3297.2857208512405,
                   5456.389353500747, 3932.5775725059766], dtype=float)

err = y_pred - y_true
ss_res = float(np.sum(err**2))
ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
r2 = round(float(1 - ss_res / ss_tot), 4)
rmse = round(float(np.sqrt(np.mean(err**2))), 4)
mae = round(float(np.mean(np.abs(err))), 4)
n = int(y_true.size)

# ---- (a) pred vs true ----
fig, ax = plt.subplots(figsize=(6.5, 6))
ax.scatter(y_true, y_pred, s=32, alpha=0.75, edgecolors="none", color="#1f77b4", label="验证样本")
lo = float(min(y_true.min(), y_pred.min()))
hi = float(max(y_true.max(), y_pred.max()))
pad = (hi - lo) * 0.05
ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], "k--", linewidth=1.2, label="1:1 参考线")
ax.set_xlim(lo - pad, hi + pad)
ax.set_ylim(lo - pad, hi + pad)
ax.set_aspect("equal", adjustable="box")
ax.legend(loc="lower right")
ax.text(0.05, 0.90, f"$R^2$ = {r2}\nRMSE = {rmse} kcal/kg\nMAE = {mae} kcal/kg\nn = {n}",
        transform=ax.transAxes, fontsize=10, va="top",
        bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8})
ax.set_title("预测值 vs 真实值 (fold 0)")
ax.set_xlabel("真实热值 (kcal/kg)")
ax.set_ylabel("预测热值 (kcal/kg)")
ax.grid(alpha=0.3)
pdf1 = os.path.join(OUT, "fig_pred_true_fold0.pdf")
png1 = os.path.join(OUT, "fig_pred_true_fold0.png")
fig.savefig(pdf1, format="pdf", bbox_inches="tight")
fig.savefig(png1, format="png", dpi=300, bbox_inches="tight")
plt.close(fig)
print("fig (a):", pdf1)

# ---- (b) 5-fold RMSE bar ----
folds = np.array([0, 1, 2, 3, 4])
hybrid = np.array([218.6108, 244.9214, 222.3821, 220.0729, 166.8624])
plsr   = np.array([231.2064, 248.8767, 255.2973, 230.6638, 203.7164])
mean_h, std_h = float(hybrid.mean()), float(hybrid.std())
mean_p, std_p = float(plsr.mean()), float(plsr.std())

fig, ax = plt.subplots(figsize=(7, 4.5))
w = 0.34
x = folds.astype(float)
ax.bar(x - w/2, hybrid, width=w, yerr=std_h, capsize=4, color="#4c72b0", edgecolor="black", linewidth=0.5, label="MIL+PLSR (融合)")
ax.bar(x + w/2, plsr,   width=w, yerr=std_p, capsize=4, color="#dd8452", edgecolor="black", linewidth=0.5, label="PLSR 基线")
ax.axhline(mean_h, color="#4c72b0", linestyle=":", linewidth=1.5)
ax.text(-0.42, mean_h + 2, f"mu={mean_h:.2f}", fontsize=9, color="#4c72b0", fontweight="bold")
ax.axhline(mean_p, color="#dd8452", linestyle=":", linewidth=1.5)
ax.text(4.02, mean_p + 2, f"mu={mean_p:.2f}", fontsize=9, color="#dd8452", fontweight="bold")
ax.set_xticks(folds)
ax.set_xticklabels([f"fold {i}" for i in folds])
ax.set_ylabel("RMSE (kcal/kg)")
ax.set_title("5 折交叉验证 RMSE 对比")
ax.legend()
ax.grid(axis="y", alpha=0.3)
pdf2 = os.path.join(OUT, "fig_cv_rmse_bars.pdf")
png2 = os.path.join(OUT, "fig_cv_rmse_bars.png")
fig.savefig(pdf2, format="pdf", bbox_inches="tight")
fig.savefig(png2, format="png", dpi=300, bbox_inches="tight")
plt.close(fig)
print("fig (b):", pdf2)
print(f"n_bags={n}  r2={r2}  rmse={rmse}  mae={mae}")
print(f"hybrid_mean={mean_h:.4f}  hybrid_std={std_h:.4f}  MJ={mean_h*0.004184:.4f}")
print(f"plsr_mean={mean_p:.4f}  plsr_std={std_p:.4f}")