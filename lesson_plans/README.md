# 教案目录标准

`lesson_plans` 按学科保存 Agent 使用的教学规则。每个学科采用相同的扁平结构：

```text
lesson_plans/
├── README.md
└── <subject>/
    ├── lesson_plan.json
    ├── instruction.md
    ├── context.md
    ├── memory_cards.json
    └── patches/
        ├── instruction/
        └── context/
```

## 文件职责

- `lesson_plan.json`：唯一清单，声明版本、文件、稳定步骤 ID 及上下文标题映射。
- `instruction.md`：短而稳定的执行规则，规定 v0.3 五层 Agent、代码状态机与记忆引用必须怎样行动。
- `context.md`：完整理论、方法边界、路线说明和教学参考；运行时只按标题选择当前步骤需要的章节。
- `memory_cards.json`：人工维护的 Question Card 与 Misconception Card；每张 Card 必须声明稳定 ID、适用条件、检索文本和教学检查点。
- `patches/instruction/`：可选的执行规则补丁目录；既可由清单常驻加载，也可作为 RAG 候选。
- `patches/context/`：可选的专题理论补丁目录；既可由清单常驻加载，也可作为 RAG 候选。

主干内容应直接合并进职责对应的规范文件；过时、重复或冲突的内容应删除。补丁机制用于独立专题、实验性规则或需要单独启停的内容，不用于保存历史版本或规避主文件整理。补丁目录当前可以没有补丁文件；仓库仅用 `.gitkeep` 保留空目录结构。

补丁文件使用稳定、可描述内容的名称，例如 `function_extrema.md`，不要使用纯日期或 `final_v2` 一类名称。每个补丁只承担一个明确主题。可复制 [`PATCH_TEMPLATE.md`](PATCH_TEMPLATE.md) 开始编写 RAG 补丁。

## 两类补丁

- **常驻补丁**：显式加入 `lesson_plan.json` 的 `instruction_files` 或 `context_files`，随主教案加载，适用于所有相关题目的稳定规则。
- **RAG 补丁**：放入对应 `patches/` 目录但不加入清单，按题目、当前步骤、知识概念和目标 Agent 动态检索。RAG 补丁必须包含 `+++` 包围的 TOML 元数据。

两类机制互斥：已在清单登记的文件不会再次进入 RAG 索引，避免同一内容被重复注入。

RAG 元数据中的 `patch_id` 和 `concept_ids` 使用稳定的小写英文 ID；`target_agents` 只能取 `solution_agent`、`solution_verifier`、`teaching_planner`、`teaching_executor`、`student_model_summarizer`；`step_ids` 必须来自当前学科清单。`knowledge` 使用 `head | relation | tail` 表示显式知识边，用于最多三跳的候选扩展。`enabled = false` 可停用补丁而不删除文件。

运行时通过 `LessonPlanPatchRAG.retrieve(PatchQuery(...), lesson_plan)` 检索，再调用结果的 `to_prompt()` 生成带来源、版本、得分和推理路径的有限上下文。当前实现使用确定性中文词法召回与知识边扩展，不依赖外部模型或向量数据库；接口边界允许以后替换召回器，而无需改变补丁格式。

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
3. 在对应文件中去重并解决冲突；常驻补丁加入清单，RAG 补丁填写检索元数据但不加入清单。
4. 如上下文标题变化，同步更新 `lesson_plan.json` 的步骤映射。
5. 提高教案版本。
6. 运行教案加载、指令拼装、上下文选择和教学状态相关测试。

业务代码统一通过 `susu_agent.lesson_plan_loader.load_lesson_plan(subject)` 加载教案。新增学科时复制标准三文件结构，不复制某一学科的具体理论内容。
