"""格物 · 最小课题（minimal case）演示包。

用途：在不依赖任何外部私有数据的前提下，用**合成数据**把七阶段链路完整跑一遍，
向评审证明「检索 → 复现 → 改进 → 成稿 → 投稿 → 沉淀」是可执行的，而不只是
对已存档产物做一致性检查。

边界（必须显式声明，不得含糊）：
  * 本包生成的数值来自**合成光谱**，只用于验证链路与方法，**不代表真实煤样结论**；
  * 真实课题的结论仍以 ``output/documents/coal_report`` 中的存档指标为准；
  * 合成数据在 ``output/min_case/`` 下生成，不入库。
"""

__all__ = ["demo_seed", "PACKAGE_VERSION"]

PACKAGE_VERSION = "1.0.0"
DEMO_SEED = 20261109


def demo_seed() -> int:
    """全链路统一随机种子（数据生成、切分、模型初始化共用）。"""
    return DEMO_SEED
