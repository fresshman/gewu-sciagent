# 图纸台账：一张图一个 id，一份出处

一份稿子写完之后，最常被问到又最难回答的问题是：
**「图 2 那张柱状图，是用哪份数据画的？」**

在 2026-11-10 之前，这个问题的答案只存在于文件名里。`sci_plot` 落盘的是
`<stem>_<时间戳>.pdf` 和 `.png`，`stem` 由调用方随手给，时间戳是画图时间。
于是 coal-thermal 项目里出现了这个状态：

| 事实 | 实测值 |
|---|---|
| 图 | 3 张（`coal_fold0_pred_true`、`coal_5fold_rmse`、`probe`） |
| 图片文件 | 16 个（pdf 在 4 个目录各一份，png 在 2 个目录各一份） |
| 字节是否相同 | 同格式副本 sha256 完全一致 |
| 出处记录 | 0 份 |
| 正文引用 | 2 处（`\includegraphics` 按文件名，无 `\label`） |

按文件列出来是 16 行，按图算只有 3 张。**行数比图多 5 倍，就是「图 2 是哪个文件」
这个问题产生的直接原因。**

## 一、旁文件：出图时顺手写下出处

`gewu/mcp/sci_plot.py` 的 `_save()` 现在除 pdf/png 外，还写一份
`<base>.meta.json`（实现见 `gewu/mcp/fig_meta.py`）：

```json
{
  "schema": 1,
  "created_at": "2026-11-10T11:26:03+08:00",
  "stem": "coal_ablation_arm_rmse",
  "tool": "plot_bar",                  ← 取自调用栈帧，不是传参（传参可以乱写）
  "fig_id": "fig-04195aa1",            ← pdf 内容 sha256 前 8 位
  "args": {                            ← 函数签名参数，数值只留指纹
    "values": {"kind":"seq","shape":[4],"sha256":"e7dbdd8702a68349","min":215.75,"max":227.44},
    "labels": {"kind":"list","n":4,"values":["base…","−FiLM","−SupCon","−huber"]},
    "title":  {"kind":"str","value":"四臂消融：5 折 RMSE（kcal/kg）"}
  },
  "draw": {                            ← 从渲染完的 Figure 上反读出来的
    "series": [{"kind":"patch","n":16,"sha256":"…"}, {"kind":"LineCollection","n":8,…}],
    "digest": "94aa1c2374190716"
  },
  "files": {"pdf": {"bytes":17660,"sha256":"04195aa1…"}, "png": {…}},
  "gewu": {"version":"0.1.0","git":"1330d1f"}
}
```

三条设计约束：

1. **数值只留指纹。** 单张 LIBS 光谱几万点，原样抄进 json 会让目录爆炸，而且
   未发表数据不该因为"记录出处"多出一份拷贝。留 `shape` + `sha256` + 极值就够核对。
2. **读不出来就不写。** 指纹计算失败时 `errors` 里记一条，旁文件照写，`draw` 留空，
   不拿零值占位。
3. **旁文件失败不拖垮出图。** 写失败时返回值 `provenance: false`，调用方能知道
   「这张图没有出处」，而不是以为有。
4. **PDF 里不写 CreationDate。** matplotlib 默认写入秒级创建时间，同样数据重画两次
   字节就不同，内容寻址的 `fig_id` 随之变化，台账会把一张图记成好几张。实测：
   带时间戳两次 sha 不同；`metadata={"CreationDate": None}` 后完全一致（17660 B，
   `fig-04195aa1` 两次渲染相同）。时间信息保留在旁文件的 `created_at` 里。

`draw.series` 是**渲染后**从 Axes 上读的：line 取 `get_xydata()`、collection 取
`get_offsets()`（无则退到路径顶点）、patch 取矩形几何、image 取 `get_array()`。
好处是与工具实现解耦——17 个绘图函数一个都不用改；代价是它记录的是「画布上有什么」，
不是「调用方传了什么」（后者在 `args` 里，两者互为校验）。

## 二、台账：按内容合并，一个 id 一张图

`web/proxy/figure_index.mjs` 扫 4 个目录（`output/figures`、`stages/5-paper/figures`、
`stages/5-paper/draft`、`output/documents`），然后：

- **母版**取 pdf（矢量），没有 pdf 才退到 png；
- **id** = `fig-<母版 sha256 前 8>`，同一份图在任何目录都是这个 id；
- **副本**按目录归并，回答「这张图在几个地方各有一份」——这正是「改了一份、
  另一份还是旧的」这类事故的现场；
- **正文引用**按 `\includegraphics` 的 basename 对（带不带扩展名都行），
  给出「图 N / §小节 / 行号 / `\label`」；
- **旁文件**只在母版同目录找，找不到就是 `provenance: null`，不跨目录猜、不编造。

接口：`GET /api/writing/figures`（台账 JSON）、
`GET /api/writing/figures/<fig-xxxxxxxx>/preview.png|file.pdf`（取文件）。

> 注意：仓库里另有 `GET /api/figures`，那是案例包的投影（`gewu_paper/figures/`），
> 与这条不是同一份数据，没有合并。

## 三、明确不做的事

| 不做 | 原因 |
|---|---|
| 给老图补出处 | 3 张 2026-10-28 的图没有旁文件，补一份就是伪造。UI 上如实显示「无出处记录」 |
| 判定图里数据对不对 | 需要拿 `args.values.sha256` 回 registry 重画一遍比对，这一步没做 |
| 合并「同一张图不同名字」 | 只按内容 sha256 合并。换了名字又改了内容，就是两张图 |
| 自动插回 tex | 引用位置由人决定；台账只报「未引用」，不改稿 |

## 四、图纸化收尾：id 与 provenance 进正文图谱（2026-11-10 下午）

台账层早就按内容合并了，但**正文图谱**（写作台的大纲/图叶）此前仍按文件名识别一张图
——同一张图的换名副本在图谱里各算各的，对不上就报「找不到同名文件」。

`annotateFigLeaves(structure, ledger)`（`web/proxy/figure_index.mjs`）把台账注进图谱，
`GET /api/writing` 组装时用同一份 5s 缓存调用（不重复扫盘）：

- 每个 fig leaf 挂 `fig_id`（内容寻址）、`fig_copies`/`fig_dirs`（副本数/目录数）、
  `fig_provenance`（旁文件在不在场，不猜）；
- 对齐**先按内容再按名字**：名字集合 = 母版 base + 全部副本的 basename——
  同一张图换了文件名的副本也指到同一个 id；两个 fig_id 抢同一个名字时保留
  台账排序先到的，不猜；
- 同一张图被正文多处引用时挂 `fig_reused`（「图 1、图 3」），UI 提示改图要两处同核；
- 台账里没有的图如实记 `fig_id: null`，统计口径 `fig_graph.leaves` 只计对上的。

UI：图叶详情新增「图纸 id」行与同图复用提示；`figForLeaf` 对齐升级为 id 优先、
base 名兜底（旧响应兼容）。测试：`web/tests/figure_index.test.mjs` +4 条（17 条全过）。

## 五、验证

- `tests/test_figure_provenance.py`（13 条）：文件 sha256 与磁盘一致、同数据重画
  `draw.digest` 不变而换数据会变、数值原值不进 json、旁文件失败不影响出图、
  同一秒同名不覆盖。
- `web/tests/figure_index.test.mjs`（13 条）：字节相同必合并、`\label` 在 caption
  前后都能收到、无旁文件不许编 tool、`fig-xxxxxxxx` 之外一律拒绝（防路径拼接）。
- 真实数据：coal-thermal 18 个文件 → 4 张图，2 张被正文引用，1 张有出处
  （2026-11-10 用表 4 的四臂数字新画的那张）。
