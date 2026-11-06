# 多模态图读取证（parse_figure × InternVL3.5）· 2026-11-04

> 目的：证明 `sci_data.parse_figure` 真在调多模态模型读科学图，并且**读数可对真值、
> 失败会诚实降级**。此前它是占位工具（永远返回 `modality:"unknown"` 的假结构），
> 在一个卖点写着反幻觉的项目里属于自相矛盾级缺陷。
> 本文所有数字来自本机真实调用，不来自文档复述。

## 0. 结论先说

- **真调通了**：6 次真实请求（3 次合成谱图 + 3 次论文原页图），模型
  `internvl3.5-241b-a28b`，`temperature=0`，每次 `status` 都如实返回。
- **合成谱图（真值由脚本自造）**：3 次运行**都是 5/5 峰检出、0 个幻觉峰**；
  峰位读数三次完全一致（250/400/450/650/780），对真值 247.8/393.4/450.1/656.3/777.4
  的最大偏差 **6.6 nm**（模型把峰位取整到 50/100 的倍数）；相对强度最大偏差 **0.07**。
  按 ±3 nm 判"命中"则 3/5，按 ±7 nm 判则 5/5 —— 这个差别本身就是"图读只可作估读"的量化证据。
- **真实论文图（公开 arXiv 1905.12226 第 6 页 Figure 3）**：caption 逐字命中、
  4 条图例全对、读出的 **16 个数字 100% 出现在同页正文文本层，0 个编造**；
  但**确有 1 处真实误读**：图上纵轴标签是 `L-Risk`（花体 L），模型读成 `Z-Risk`，
  并把左右双 y 轴合并成一个 `y_axis`（label 写成 "Risk"，min/max 留 null），
  而 `confidence` 仍是 `high`。→ 二次对照（图读 × 文本层）纪律不能拆，这条是硬证据。
- **降级路径全部实测过**：喂一张本页根本没有图的页面 → `modality:"unknown"`、
  `confidence:"low"`，不硬编出一张图；真实网络超时 → `status:"timeout"`，
  返回体里没有 `figure`/`modality` 字段（6 次调用零例外，另有 21 条离线单测锁死该契约）。

## 1. 调用环境

| 项 | 值 |
| --- | --- |
| Python | WorkBuddy 托管 venv `default`（含 mcp<2 / numpy / pymupdf / matplotlib） |
| 入口 | 直接 `import sci_data` 调 `parse_figure()`（不经过网关，排除传输层噪声） |
| Key | 从本机 `~/.openclaw/openclaw.json` 读进 `INTERN_API_KEY` 环境变量；长度 51，全程未打印 |
| 端点 | `https://chat.intern-ai.org.cn/api/v1/chat/completions`（必须 `chat.` 域名） |
| 采样 | `temperature=0`，图以内联 `image_url` base64 data URI 传入 |
| 图像 | 合成谱图 48,418 B（dpi=150, 7.2×4.0 in）→ b64 64,560 字符；论文整页 269,025 B（dpi=110, 935×1210）→ b64 358,700 字符 |

脚本与工作目录都在仓库外（`%TEMP%/gewu_vl_e2e*.py`），产物不入库。

## 2. 第一组：有真值的合成 LIBS 谱图

真值（脚本自造，5 个高斯峰，σ=1.1 nm，x 轴 200–800 nm，叠加 σ=0.006 噪声）：

| 真峰位 (nm) | 真相对强度 |
| --- | --- |
| 247.8 | 0.62 |
| 393.4 | 1.00 |
| 450.1 | 0.33 |
| 656.3 | 0.85 |
| 777.4 | 0.48 |

图里**没有任何刻度数字**，只有 `Wavelength (nm)` / `Intensity (a.u.)` / 标题，
所以模型给出的每个数都是估读——这正是检查它会不会拿"典型谱线"来补全的场景。

三次独立运行：

| 运行 | 墙钟 | tokens (prompt/completion/total) | 读出峰位 (nm) | 读出强度 | `label_in_figure` | confidence |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 34.58 s | 1233 / 1075 / 2308 | 250, 400, 450, 650, 780 | 0.6, 1.0, 0.4, 0.9, 0.5 | 5/5 自标"估读" | high |
| 2 | 34.09 s | 1233 / 1263 / 2496 | 250, 400, 450, 650, 780 | 0.65, 1.0, 0.35, 0.9, 0.5 | 4/5 自标"估读" | high |
| 3 | 26.42 s | 1233 / 1165 / 2398 | 250, 400, 450, 650, 780 | 0.65, 1.0, 0.35, 0.9, 0.5 | 5/5 自标"估读" | medium |

判定（脚本自动逐条比对）：

- 检出：`读出峰位数 5 / 真值 5`，三次一致。
- 峰位误差：Δ = +2.2, +6.6, −0.1, −6.3, +2.6 nm → 最大 **6.6 nm**，均方根 **4.36 nm**。
  三次完全相同的读数说明 `temperature=0` 下输出稳定，误差是系统性的"取整"而非随机抖动。
- 强度误差：运行 1 为 −0.02, 0.00, +0.07, +0.05, +0.02；运行 2/3 为 +0.03, 0.00, +0.02, +0.05, +0.02
  → 最大 **0.07**（450.1 nm 真值 0.33 → 读 0.4）。
- **幻觉峰：0 个**——每个读数在 ±7 nm 内都能对上真峰，模型没有从元素表/典型谱线里
  补出第 6 条峰（这条是反幻觉契约的关键，占位版本永远"成功"，压根测不出这件事）。
- 轴与文字：`x_axis` = Wavelength/nm/200–800、`y_axis` = Intensity/a.u.、
  `text_in_figure` 3 条逐字命中、`key_numbers` 为空、`unreadable` 为空。

## 3. 第二组：真实论文原页图（公开 arXiv 1905.12226）

选第 6 页 Figure 3（MIL 论文，双栏矢量图，Train-Test risk vs Epoch，左右两个 y 轴），
整页 dpi=110 渲染后直接喂 `parse_figure`，question 限定"只处理本页最大的那张图"。
交叉对照口径：模型读出的数字逐个与**同一页正文文本层**出现的数字比对。

结果（成功那次）：**32.53 s、4949 tokens（prompt 3804 / completion 1145）、`modality:"curve"`**。

| 项 | 图上真值（文本层/人工看图） | 模型读数 | 判定 |
| --- | --- | --- | --- |
| caption | `Figure 3: Train-Test risk using different loss functions L over epochs, on (a) SVHN Dataset and (b) 20Newsgroup Dataset.` | 逐字一致 | ✅ |
| 图例 | CE train / MSE train / CE test / MSE test | 4 条全对，并区分实线/虚线、蓝/橙 | ✅ |
| x 轴 | Epoch，0–1000，刻度 200/400/600/800 | 一致 | ✅ |
| 数字 | 16 个刻度值 | 16 个**全部**命中同页文本层，"只在图里出现的"= 0 | ✅ 零编造 |
| `peaks` | 该图无峰 | `[]`（没有把曲线拐点编成峰） | ✅ |
| 左 y 轴标签 | 文本层是 `L-Risk`（花体 ℒ） | **`Z-Risk`** | ❌ 真实误读 |
| 双 y 轴 | 左 `L-Risk` 0.0–0.8、右 `Bayes Risk` 0.00–0.30 | 合并成单个 `y_axis`，label 写成 `Risk`，min/max 为 null（两套刻度退到 `key_numbers` 里） | ⚠️ 结构损失 |
| confidence | — | `high`（尽管存在上面两处错误） | ⚠️ 不可自证 |

**这一组恰恰是本次取证最有价值的部分**：模型不会靠编数来"完成"任务（16/16 命中、
peaks 留空），但会在**字符级视觉辨认**上出错并且**自己不知道**。所以
"parse_figure 的输出只能作为定位与假设，落结论前必须与文本层/原图二次对照"
是工具契约的一部分，而不是可选建议——`docs/verification/anti-hallucination.md`
里的二次对照纪律由此从"文档要求"变成"有实测支撑的结论"。

## 4. 附：喂一张根本没有图的页（第 4 页）

同一篇论文第 4 页只有公式与小节标题。`parse_figure` 返回：
`status:"ok"`、**`modality:"unknown"`**、`confidence:"low"`、`title:null`、两轴全空、
`peaks:[]`；`key_numbers` 12 个全部是同页可见的公式编号与小节号（16/17/18、4.2/4.3/5.1/5.2…），
**"只在图里出现、正文没有的"= 0**；墙钟 18.5 s、4443 tokens。
即：拿不到图时它把"看到的文字"如实标注来源，而不是伪造一张谱图的形状。

## 5. 附：一次真实超时（不是模拟）

第 6 页整页图第一次请求在默认 180 s 天花板内未返回：

```json
{"status": "timeout", "error": "请求超时（180s 内未返回）", "latency_s": 180.29,
 "path": "%TEMP%\\gewu_vl_e2e_paper\\page_006.png"}
```

返回体没有 `figure`/`modality`/`usage`——Agent 看到的是明确失败，而不是可被误当读数的空结构。
同一张图把 `GEWU_VL_TIMEOUT_S` 放到 300 s 后 32.5 s 就成功（§3），说明是服务端排队抖动，
而非图像尺寸必然导致超时。纪律：内部天花板上限 480 s 必须留在 sci-data 的
`requestTimeoutMs=600000` 客户端闸门之下，否则模型只会看到 `-32001`，丢掉全部错误语义
（该不变量已由 `tests/test_parse_figure.py::test_timeout_is_clamped_below_the_mcp_client_gate`
直接读模板断言，改配置就会红）。

## 6. 部署侧实测：Key 怎么进到 MCP 子进程

这一条是实装过程中撞出来的、会直接卡住"换机器复现"的事实：

- openclaw 起 stdio MCP 子进程时**只给 15 个键的环境白名单**（PATH/TEMP/USERPROFILE/
  SYSTEMROOT 那一类），所以**只在 shell 里 `export INTERN_API_KEY` 到不了子进程**——
  实测两个 MCP 客户端子进程都拿到 `missing_key`。
- `mcp.servers.<name>.env` **会**被合并进子进程环境，且其中 `${VAR}` 会用父环境插值；
  但**未解析的 `${VAR}` 会让整个 server 静默不启动**（`openclaw mcp probe` 无输出、退出码 0），
  同时模板里 `apiKey: "${INTERN_API_KEY}"` 解析不了时 `config validate|probe|doctor`
  也会全部静默——排查时很容易误判成"网关坏了"。
- 因此 `scripts/bootstrap_openclaw_config.py --intern-api-key sk-xxx --write` 只在拿到真值时
  才把 `env: { INTERN_API_KEY: "..." }` 注入生成的（仓库外）配置；不给就保留占位并由检查报
  `warn`（parse_figure 会返回 `missing_key`，其余 4 个 sci-data 工具不受影响）。
  注入后的配置实测：`openclaw config validate` → Config valid，`openclaw mcp probe` →
  `sci-data: 5 tools`；连续两次生成逐字节一致；打印与落盘内容里 Key 一律脱敏为
  `sk-***REDACTED(len=…)***`。

## 7. 已知缺口（本次没修，如实记）

1. **`pdf_page_map` 认不出矢量图页**：这篇论文 9 页、每页 `get_images()` 都是 0，
   于是 `figure_pages=[]`、`suggested_pages=""`——它的启发式只看内嵌栅格，
   对矢量绘图的 PDF（学界主流）会系统性漏页。本次靠人工定位到第 6 页。
   影响面：Agent 若照 `pdf_page_map` 的推荐渲染，会拿到"无图页"。
2. **双 y 轴 / 多子图的结构性读丢**：见 §3，模型能读出两套刻度，但会把它们塞进
   `key_numbers` 而不区分所属子图/轴，`series` 也没有子图归属字段。
3. **`confidence` 不可信**：`high` 与两处实际错误共存，不能当作可用性判据。
4. 整页 dpi=110 的图 b64 约 36 万字符，接近 `GEWU_VL_MAX_B64` 默认 60 万的一半以上；
   建议先裁图或降 dpi，工具在超限时返回 `too_large` 而不是硬发。

## 8. 复现命令

```bash
# 合成谱组（真值自造，可判命中）——脚本放仓库外，读本机 live config 里的 Key
PYTHONIOENCODING=utf-8 python %TEMP%/gewu_vl_e2e.py

# 论文原页组（默认第 6 页；PAGES=4 可复现"无图页"降级）
PAGES=6 PYTHONIOENCODING=utf-8 python %TEMP%/gewu_vl_e2e_paper2.py

# 离线单测（不联网，锁死降级契约）
PYTHONIOENCODING=utf-8 python -m pytest tests/test_parse_figure.py -q   # 21 passed
PYTHONIOENCODING=utf-8 python -m pytest tests -q                        # 89 passed / 0 skipped
```
