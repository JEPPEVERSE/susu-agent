# Instruction 补丁入口

这里存放需要直接改变数学 Tutor 教学决策的增量规则。

- 使用 `010_名称.md`、`020_名称.md` 等易于维护的文件名；
- 将文件相对路径按期望顺序加入 `lesson_plans/math/lesson_plan.json` 的 `instruction_files`；
- 若补丁新增或调整教学步骤，同步维护 JSON 中的 `steps`，并保持已有步骤 ID 稳定；
- 只写增量内容，并说明适用题型、触发条件和退出条件；
- 不要在这里放长篇例题或原始课件，那些内容应放入 `context` 补丁；
- 本说明文件没有登记在 JSON 清单中，因此不会被加载。
