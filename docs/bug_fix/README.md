# bug_fix：会再踩一次的约束

这里不写「已修复」的流水账。只记一件事：**下次动到同一处时，什么写法会立刻重犯**。

判据是「这条约束能不能变成一句可执行的检查」。写不出来的，说明还没想清楚，不收。

| 文件 | 什么时候翻它 |
|---|---|
| [2026-11-10-claim-status-false-green.md](2026-11-10-claim-status-false-green.md) | 要显示「已核 / 通过 / 有效」这类判断状态时 |
| [2026-11-10-provenance-parser.md](2026-11-10-provenance-parser.md) | 改 `claim_provenance.py` 的 source 解析或 metric 取值时 |
| [2026-11-10-frontend-render-traps.md](2026-11-10-frontend-render-traps.md) | 新增论文视图 / 写带 `/g` 的正则 / 显示数值时 |

每条都带「怎么验证」——没有验证手段的约束等于没有。
