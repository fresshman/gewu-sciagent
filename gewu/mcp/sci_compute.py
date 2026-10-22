"""通用科学计算 MCP Server：PCA / PLS / 曲线拟合 / 交叉验证 / 超参寻优。"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sci-compute")


@mcp.tool()
def pca_reduce(data_2d: list[list[float]], n_components: int = 2) -> dict:
    """对二维数据做 PCA 降维，返回投影与解释方差比。"""
    from sklearn.decomposition import PCA
    import numpy as np
    X = np.array(data_2d)
    p = PCA(n_components=n_components)
    return {
        "transformed": p.fit_transform(X).tolist(),
        "explained_variance": p.explained_variance_ratio_.tolist(),
    }


@mcp.tool()
def pls_regress(X: list[list[float]], y: list[float], n_components: int = 2) -> dict:
    """偏最小二乘回归（化学计量学常用），返回 R2 与系数。"""
    from sklearn.cross_decomposition import PLSRegression
    import numpy as np
    model = PLSRegression(n_components=n_components)
    model.fit(np.array(X), np.array(y))
    return {
        "r2": float(model.score(np.array(X), np.array(y))),
        "coef": np.asarray(model.coef_).ravel().tolist(),
    }


@mcp.tool()
def curve_fit(x: list[float], y: list[float], model: str = "linear") -> dict:
    """曲线拟合。model ∈ {linear, exp}。"""
    import numpy as np
    from scipy.optimize import curve_fit as cf
    x = np.array(x)
    y = np.array(y)
    f = (lambda x, a, b: a * x + b) if model == "linear" else (lambda x, a, b, c: a * np.exp(-b * x) + c)
    popt, _ = cf(f, x, y, maxfev=10000)
    return {"params": popt.tolist(), "model": model}


@mcp.tool()
def cross_validate(X: list[list[float]], y: list[float], cv: int = 5) -> dict:
    """交叉验证评分（默认 R2）。"""
    from sklearn.model_selection import cross_val_score
    from sklearn.linear_model import LinearRegression
    import numpy as np
    scores = cross_val_score(LinearRegression(), np.array(X), np.array(y), cv=cv, scoring="r2")
    return {"cv_scores": scores.tolist(), "mean": float(scores.mean())}


if __name__ == "__main__":
    mcp.run()
