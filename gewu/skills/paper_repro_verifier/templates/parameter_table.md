# 可执行参数表模板

> 三源：论文正文/附录、配置文件、代码默认值。**冲突不要悄悄选一个**。
> `source_class`：`paper_explicit` | `code_inferred` | `self_set` | `unresolved`。

| 参数 | 论文值（页码） | 附录/配置值（文件:行） | 代码默认（文件:行） | 采用值 | source_class | 冲突 | 裁决依据 |
|---|---|---|---|---|---|---|---|
| lr |  |  |  |  |  | ☐ |  |
| batch_size |  |  |  |  |  | ☐ |  |
| epochs |  |  |  |  |  | ☐ |  |
| seed |  |  |  |  |  | ☐ |  |
| n_folds |  |  |  |  |  | ☐ |  |

规则：论文明确给出 > 补充材料/配置 > 代码默认 > 自行设定。
「自行设定」必须在 `change_records` 写明为什么、有没有做敏感性检查。
导出可执行形式：把采用值写成 `params_resolved.json` 交复现命令读取。
