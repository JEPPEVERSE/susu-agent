# 教案目录标准

`lesson_plans` 按学科保存 Agent 使用的教学规则。每个学科采用相同的扁平结构：

```text
lesson_plans/
├── README.md
└── <subject>/
    ├── lesson_plan.json
    ├── instruction.md
    ├── context.md
    └── patches/
        ├── instruction/
        └── context/
```

## 文件职责

- `lesson_plan.json`：唯一清单，声明版本、文件、稳定步骤 ID 及上下文标题映射。
- `instruction.md`：短而稳定的执行规则，规定解题 Agent、Tutor 与状态更新器必须怎样行动。
- `context.md`：完整理论、方法边界、路线说明和教学参考；运行时只按标题选择当前步骤需要的章节。
- `patches/instruction/`：可选的执行规则补丁目录。
- `patches/context/`：可选的专题理论补丁目录。

主干内容应直接合并进职责对应的规范文件；过时、重复或冲突的内容应删除。补丁机制用于独立专题、实验性规则或需要单独启停的内容，不用于保存历史版本或规避主文件整理。补丁目录当前可以没有补丁文件；仓库仅用 `.gitkeep` 保留空目录结构。

补丁文件使用稳定、可描述内容的名称，例如 `function_extrema.md`，不要使用纯日期或 `final_v2` 一类名称。每个补丁只承担一个明确主题，并在开头说明适用范围、触发条件及与主文件的关系。

## `lesson_plan.json` 约束

- `lesson_plan_version` 使用 `MAJOR.MINOR.PATCH`。改变步骤语义、文件结构或核心理论时提高主版本；兼容性扩充提高次版本；文字修正提高补丁版本。
- `instruction_files` 与 `context_files` 必须显式列出文件，数组顺序就是合并顺序。主文件必须排在第一位，启用的补丁随后列出；空补丁目录不需要登记。
- `always_include_context_headings` 保存每一步都必须加载的总纲标题。
- `steps` 中的 `id` 是 TeachingState 的稳定标识。修改显示名称或理论内容时尽量保留 ID。
- `context_headings` 必须与上下文文件中的二至四级 Markdown 标题完全一致。
- 未登记文件不会被加载，但学科目录中不应保留无人使用的草稿、备份或说明文件。

## 内容维护流程

1. 判断新内容属于执行规则还是理论上下文。
2. 判断它应进入主文件，还是作为可独立启停的单主题补丁。
3. 在对应文件中去重并解决冲突；补丁需加入清单才会生效。
4. 如上下文标题变化，同步更新 `lesson_plan.json` 的步骤映射。
5. 提高教案版本。
6. 运行教案加载、指令拼装、上下文选择和教学状态相关测试。

业务代码统一通过 `susu_agent.lesson_plan_loader.load_lesson_plan(subject)` 加载教案。新增学科时复制标准三文件结构，不复制某一学科的具体理论内容。
