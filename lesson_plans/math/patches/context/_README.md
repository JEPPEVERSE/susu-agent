# Context 补丁入口

这里存放数学理论体系、专题方法卡、典型边界和例题等增量资料。

- 使用 `010_名称.md`、`020_名称.md` 等易于维护的文件名；
- 将文件相对路径按期望顺序加入 `lesson_plans/math/lesson_plan.json` 的 `context_files`；
- 将需要检索的二至四级 Markdown 标题登记到对应步骤的 `context_headings`；
- 尽量注明适用范围、前提、反例和检验方法；
- 需要强制改变 Tutor 行为的规则应放入 `instruction` 补丁；
- 本说明文件没有登记在 JSON 清单中，因此不会被加载。
