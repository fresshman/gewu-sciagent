import { useEffect, useRef, useState } from "react";
import type { AskBlock } from "../lib/ask";
import { answerText } from "../lib/ask";

// 一页一题的问卷。替用户把「用文字描述一个选择题」这件事从输入框里拿掉。
//
// 键盘按需求给的四组键来：↑↓ 换项、Space 选中（多选用）、Enter 提交、
// ←→ 同样换项（单选用得多的人习惯左右也走）。鼠标点选等价，不做「只能键盘」。
//
// 两个安全阀：
// 1. 超过 8 个选项已在解析层截断，这里只负责不要撑破布局；
// 2. 无论问卷写得多糟，用户都能「改为自由输入」——问卷不能把人锁在门外。

export function AskUserCard({
  block,
  onAnswer,
  onBypass,
  answered,
  locked,
}: {
  block: AskBlock;
  onAnswer: (text: string) => void;
  onBypass?: () => void;
  /** 已回答过：只回显选择，不再可交互 */
  answered?: string;
  /** 这一问已经翻篇（用户当时用自由输入跳过了）：只回显，不假装还能点 */
  locked?: boolean;
}) {
  const [active, setActive] = useState(0);
  const [picked, setPicked] = useState<number[]>([]);
  const boxRef = useRef<HTMLDivElement | null>(null);

  const done = Boolean(answered);
  // 冻结 = 已答 或 已跳过。渲染、键盘、按钮三处都看这一个值，
  // 否则会出现「看着能点、点了没反应」的死按钮
  const frozen = done || Boolean(locked);
  const n = block.options.length;

  const submit = () => {
    if (frozen) return;
    const text = answerText(block, picked);
    if (text) onAnswer(text);
  };

  const move = (d: number) => {
    if (frozen) return;
    setActive((i) => (i + d + n) % n);
  };

  const choose = (i: number) => {
    if (frozen) return;
    setActive(i);
    if (block.multi) {
      setPicked((p) => (p.includes(i) ? p.filter((x) => x !== i) : [...p, i]));
    } else {
      setPicked([i]);
    }
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (frozen) return;
    switch (e.key) {
      case "ArrowDown":
      case "ArrowRight":
        e.preventDefault();
        move(1);
        break;
      case "ArrowUp":
      case "ArrowLeft":
        e.preventDefault();
        move(-1);
        break;
      case " ":
        e.preventDefault();
        if (block.multi) choose(active);
        else {
          // 单选：Space 等同于「就选这个」，但还要 Enter 才提交，避免手滑
          setPicked([active]);
        }
        break;
      case "Enter":
        e.preventDefault();
        if (block.multi) {
          if (picked.length) submit();
          else choose(active); // 什么都没选时，回车先把当前项打上
        } else {
          if (picked[0] === active || picked.length === 0) {
            setPicked([active]);
            onAnswer(answerText(block, [active]));
          } else submit();
        }
        break;
      default: {
        // 选项右边印着 1/2/3，就得真的能按。数字只做「选中」，不直接提交：
        // 多选里连按 1 2 是常规动作，一下提交会把第二次按键吃掉。
        if (/^[1-9]$/.test(e.key)) {
          const i = Number(e.key) - 1;
          if (i < n) {
            e.preventDefault();
            choose(i);
          }
        }
        break;
      }
    }
  };

  // 挂载即接键盘，用户不用先点一下问卷
  useEffect(() => {
    if (frozen) return;
    boxRef.current?.focus();
  }, [frozen]);

  return (
    <div
      ref={boxRef}
      className={`ask ${done ? "is-done" : ""} ${locked ? "is-locked" : ""}`}
      role={block.multi ? "group" : "radiogroup"}
      aria-label={block.question}
      tabIndex={frozen ? -1 : 0}
      onKeyDown={onKey}
    >
      <div className="ask__head">
        <span className="ask__badge">{block.multi ? "多选" : "单选"}</span>
        <span className="ask__q">{block.question}</span>
      </div>
      {block.why && <div className="ask__why">{block.why}</div>}

      <div className="ask__opts">
        {block.options.map((o, i) => {
          const on = picked.includes(i);
          return (
            <button
              key={`${o.label}-${i}`}
              type="button"
              className={`ask__opt ${on ? "is-on" : ""} ${i === active && !frozen ? "is-active" : ""}`}
              aria-checked={on}
              role={block.multi ? "checkbox" : "radio"}
              disabled={frozen}
              // onMouseDown 而不是 click：避免按钮拿到焦点后问卷的键盘上下文丢失
              onMouseDown={(e) => {
                e.preventDefault();
                choose(i);
              }}
              onMouseEnter={() => !frozen && setActive(i)}
            >
              <span className="ask__mark">{on ? (block.multi ? "☑" : "●") : block.multi ? "☐" : "○"}</span>
              <span className="ask__body">
                <span className="ask__label">{o.label}</span>
                {o.desc && <span className="ask__desc">{o.desc}</span>}
              </span>
              <span className="ask__key">{i + 1}</span>
            </button>
          );
        })}
      </div>

      <div className="ask__foot">
        {done ? (
          <span className="ask__picked">已回答：{answered}</span>
        ) : locked ? (
          <span className="ask__skipped">未回答（这一问已跳过）</span>
        ) : (
          <>
            <button className="ask__submit" type="button" onClick={submit} disabled={!picked.length}>
              提交{picked.length > 1 ? `（${picked.length}）` : ""}
            </button>
            <span className="ask__hint">↑↓ 换项 · Space 选中 · Enter 提交 · 数字键直选</span>
            {onBypass && (
              <button className="ask__bypass" type="button" onClick={onBypass}>
                改为自由输入
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
