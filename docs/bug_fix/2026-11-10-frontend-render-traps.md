# 前端渲染四个坑（都是「看起来没事、截图才发现」）

## 一、新视图不写 `.pw-view--xxx` 就被塞进左栏

`.pw` 是三栏网格的子项，`.pw-view` 本身是 `display:flex`（**默认 row**，写作台要左右三栏）。
新加一个 tab 如果只写 `className="pw-view pw-view--claims"` 而不定义
`.pw-view--claims { flex-direction: column }`，页头和卡片会并排挤在左侧，
右侧大片空白——而且**不报错**，只是难看。

同类前科：`.paper-reader-full` 忘了 `grid-column`，被自动放进 280px 左栏。

**约束**：新增任何 `pw-view--*` 变体，必须同时给出三件套：

```css
.pw-view--xxx {
  flex-direction: column;   /* 上下结构的视图 */
  min-height: 0;            /* 否则 flex 子项撑高整页 */
  overflow: auto;           /* 滚动归这一层，内层不许再滚 */
}
```

对应窄屏还要检查 `grid-column: span N` 有没有超出实际列数——`span 3` 落在
2 列网格里会撑出隐式列，表现为横向滚动条。

## 二、带 `/g` 的正则不许在递归函数里复用实例

```ts
const INLINE = /.../g;          // 模块级，带 g
function renderInline(text) {
  while ((m = INLINE.exec(text))) { ... renderInline(inner) ... }  // 内层改了 lastIndex
}
```

内层递归调用会把共享实例的 `lastIndex` 挪走，外层循环随即从错位置继续，
表现为「某些行内标记漏渲染」——偶发，且输入越长越容易中。

**约束**：正则含 `/g` 或 `/y` 且函数会递归/重入时，每次进函数新建实例：

```ts
const re = new RegExp(INLINE.source, "g");
```

## 三、浮点数尾巴直接上屏

`214.5699 × 0.01 = 2.1456990000000002`，容忍度一栏就显示成
`2.1861080000000004`，看着像程序坏了。

**约束**：数值展示必须定一个精度策略，不能 `String(n)` 了事。
现用策略（`ClaimCard.tsx` 的 `fmtNum`）：

- `|n| < 1e-3` → 科学计数法两位（`1.10e-5`）
- 数字字符数 > 8 → `toPrecision(6)` 去掉尾巴
- 其余原样（`214.5699` 不能被顺手四舍五入掉——那是真精度）

## 四、断言 `<p` 会匹配到 `<pre>`

`assert.strictEqual(out.includes("<p"), false)` 在正确输出上也会失败，
因为 `<pre class="md-pre">` 以 `<p` 开头。写测试时踩过一次，白查了十分钟。

**约束**：断言 HTML 片段要带完整标签或类名，不要用前缀：

```js
out.includes('<p class="md-p"')   // ✅
out.includes("<p")                // ❌
```

## 怎么验证

```sh
cd web && npm test          # 87 passed（markdown 16 条覆盖渲染结构）
```

视觉上必须两个宽度各看一眼，光靠单测发现不了第 1 条：

```sh
msedge --headless=new --window-size=1600,1000 --screenshot=a.png "http://localhost:3112/#claims"
msedge --headless=new --window-size=760,1100  --screenshot=b.png "http://localhost:3112/#claims"
```

## 5. 内部枚举直出界面（`success` / `aborted`）

会话结束原因 `disposition` 是协议字段，取值 `success` / `timeout` / `aborted`。
三处（任务圆环、消息内执行行、执行面板）都直接把它铺到界面上，于是中文界面里
出现 `结束 · success`。

**约束**：协议字段进界面前必须有显式映射，且映射失败要**原样显示**，不许猜。
`dispositionText()` 就是这么写的：认不出来的值一字不改地返回——宁可露出内部字段，
也不要把它翻成「成功」。同理，给行定色不能反读中文标签，要另一条 `dispositionTone()`，
否则翻译改一个字，颜色就跟着变。

```ts
dispositionText("success")           // 成功
dispositionText("cancelled_by_user") // 取消（含 cancel 就该认）
dispositionText("partial")           // partial（不猜）
```

**踩坑提醒**：写这条测试时我先断言 `cancelled_by_user` 原样返回，测挂了——
是实现对、断言错。判「认不认得出」要用真没规则的词（`partial`），
不能用带后缀的复合值。
