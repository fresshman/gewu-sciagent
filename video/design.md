# 格物 · gewu-sciagent 项目介绍视频 — 设计系统

## 品牌

「格物」科研工作台：书生大模型 × OpenClaw，AI for Science 赛道。
气质：科研严谨、深空蓝、克制的金色成果感。

## 调色板（Dark / Premium，深蓝系）

| 用途 | 色值 |
|---|---|
| 背景 bg | `#0D1B2A` |
| 卡片/面板 surface | `#1B263B` |
| 面板高亮边/线条 line | `#415A77` |
| 次级文字 muted | `#778DA9`（24px+ 大字） / `#A9B8CB`（深底小字，过 WCAG AA） |
| 主文字 fg | `#E0E1DD` |
| 强调 accent | `#FCA311` |
| 强调暗版（渐变/glow 低层） | `rgba(252,163,17,0.14)` |

禁止：纯 `#000`/`#fff`、青色霓虹、紫蓝渐变、per-scene 造色。

## 字体

- 标题：`"Noto Sans SC"` 900（fallback: "Microsoft YaHei"）
- 正文/标签：`"Noto Sans SC"` 400/300（fallback: "Microsoft YaHei"）
- 数字/代码：`"JetBrains Mono", monospace`，`font-variant-numeric: tabular-nums`
- 标题 ≥ 64px，正文 ≥ 22px，数据标签 ≥ 16px

## 深度

- 背景层：每场景 2–4 个装饰（accent 色 radial glow 低透明呼吸、8% ghost 大字、
  32px 网格线 3% 透明度、hairline 分隔线）
- 卡片：`border: 1px solid rgba(65,90,119,.45)`；`border-radius: 12px`
- 不用大面积阴影，用 1px 线 + glow

## 动效

- 入场 0.3–0.7s，ease 至少三种：`power3.out` / `expo.out` / `power2.out` / `back.out(1.4)`
- 场景切换：金色窄条 wipe 扫屏（0.9s 总长，跨场景边界）
- 数字卡：`back.out(1.4)` 缩放入场 + 一次金色脉冲
- 录屏段落：只加常驻角标与章节字幕，不遮挡 1920×1080 画面主体
