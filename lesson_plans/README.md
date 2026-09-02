# 教案目录

`lesson_plans` 按学科保存 Tutor Agent 使用的基础教案。每个学科使用一个英文目录名，例如：

```text
lesson_plans/
└── math/
    ├── lesson_plan.json
    ├── math_tutor_core.md
    ├── math_problem_solving_framework.md
    └── patches/
        ├── instruction/
        └── context/
```

每个学科必须提供 `lesson_plan.json`。其中：

- `lesson_plan_version`：教案内容的语义版本，采用 `MAJOR.MINOR.PATCH`；
- `instruction_files`：需要合并进 Agent instruction 的有序文件列表；
- `context_files`：可供 `ContextBuilder` 检索的理论资料文件；
- `always_include_context_headings`：每一步都需要提供的 Markdown 章节标题；
- `steps`：稳定步骤 ID、显示名称及该步骤需要检索的章节标题。

## 添加补丁

先将 Markdown 文件放入对应补丁目录，再把相对路径添加到 `lesson_plan.json` 的相应数组中。数组顺序就是最终合并顺序，程序不会自动扫描目录。例如：

```json
{
  "instruction_files": [
    "math_tutor_core.md",
    "patches/instruction/010_function.md"
  ],
  "context_files": [
    "math_problem_solving_framework.md",
    "patches/context/010_function_examples.md"
  ],
  "always_include_context_headings": [
    "总纲"
  ],
  "steps": [
    {
      "id": "S1",
      "name": "理解任务",
      "context_headings": ["函数问题的审题方法"]
    }
  ]
}
```

没有写入清单的文件不会进入模型输入，因此 `_README.md` 等维护文档可以安全保留。补丁应尽量只写增量规则或知识，避免复制基础文件；若补丁与基础内容冲突，应在补丁中明确适用范围和替代条款。

业务代码统一通过 `susu_agent.lesson_plan_loader.load_lesson_plan(subject)` 读取清单。通常不需要修改这个函数；增加、删除或调整教案顺序时，只维护对应学科的 JSON 即可。

`context_headings` 必须与 `context_files` 中二至四级 Markdown 标题的正文完全一致。运行时只注入总纲和当前步骤对应的章节，不再把整份理论文档重复发送给模型。步骤 `id` 是 TeachingState 使用的稳定标识；修改显示名称时应保留原 `id`。

教案内容发生正式变更时同步提高 `lesson_plan_version`。当前 v0.1 约定教师在会话外维护教案，不支持学生端或单轮对话过程中的热更新。

新增学科时，复制 `math` 的目录结构，修改清单中的 `subject` 和文件路径，并为该学科单独编写教案。
