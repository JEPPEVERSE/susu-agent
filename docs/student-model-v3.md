# StudentModel v3

StudentModel v3 是跨题目、跨会话持久化的学生长期模型。它只记录相对稳定且可追踪的信息；单轮教学的临时判断仍保存在 TeachingState。

## 顶层结构

```text
StudentModel
├── identity                # 年级、班级、学校等身份信息
├── learning_profile        # 跨学科学习特点与表达偏好
├── subjects                # 六科独立档案
│   ├── math
│   ├── chinese
│   ├── english
│   ├── physics
│   ├── chemistry
│   └── biology
├── learning_history        # 长期错误模式和近期尝试
├── academic_records        # 成绩序列与后续批量导入信息
├── education_goals         # 高考目标和目标院校
├── meta_knowledge_cards    # 元知识卡
└── extensions              # 后续实验的命名空间扩展
```

每个学科档案同时保存：

- `level`：该学科的有限状态、置信度与证据；
- `strengths` / `weaknesses`：学科内相对稳定的优势和薄弱方向；
- `knowledge_graph.nodes`：知识点掌握状态及证据；
- `knowledge_graph.edges`：知识点的前置、相关或从属关系。

## 学科水平有限状态机

```text
unassessed -> foundation -> developing -> proficient -> advanced
```

- 初次形成可靠评价时，`unassessed` 可以进入任一已评估状态。
- 已评估状态每次长期更新最多上升或下降一级。
- 无 evidence ID 或低置信度的更新不会写入长期模型。
- 低置信度的已有水平记录按 `unassessed` 处理，不会触发跳题。
- 单个知识点的一次回答不能直接代表整门学科水平。

TeachingPlanner 运行前，代码会根据当前学科状态生成 `subject_level_policy`：

- `unassessed` / `foundation`：保留基础问题，从第一层检查开始；
- `developing` / `proficient`：默认跳过 `foundation` 问题，从标准问题进入；
- `advanced`：优先从 `advanced` 问题进入；若本题没有高级问题，则回退到题目中实际存在的最高难度。

代码选出的 `recommended_entry_question_id` 和对应 SolutionStep 是策略图的强制入口。被跳过的问题仍可作为回答错误、部分正确或不会时的补救分支。

## 问题难度

Solution Agent 为每个 TutorQuestion 标注：

- `foundation`：题意、基本定义、直接识别；
- `standard`：本题正常解法所需的核心步骤；
- `advanced`：关键建模、综合推导、方法比较或迁移。

难度描述的是“这个问题在当前题目中的教学层级”，不是对学生能力的永久评价。

## 成绩与目标扩展

`academic_records.score_history` 已预留考试名称、考试类型、满分、班级排名、年级排名和记录时间，可直接作为未来成绩曲线的数据源。`latest_import_id` 与 `latest_imported_at` 用于后续 CSV、Excel 或教务系统批量导入的幂等控制。

`education_goals` 已预留：

- 高考年份与目标总分；
- 六科目标分数；
- 冲刺、目标、保底院校及专业方向。

这些目标当前只存储，不会直接覆盖基于学习证据得到的学科水平。

## 持久化与版本记录

SQLite 使用两层存储：

- `student_models` 保存每名学生的最新完整模型，并记录 Schema 版本、模型版本、创建时间和更新时间；
- `student_model_versions` 在每次创建、人工保存、Schema 迁移或总结更新时保存不可变快照，供审计和问题定位。

总结更新通过数据库事务和 `model_version` 乐观锁提交。如果另一进程已经更新同一学生，旧版本写入会被拒绝，避免静默覆盖。StudentModel JSON 是当前唯一业务数据源；成绩曲线等扩展暂时保存在模型内，避免在功能尚未稳定时形成两套互相冲突的数据。

可创建一个用于 v0.2 测试的中等偏上、数学偏好学生：

```powershell
.\.venv\Scripts\python.exe scripts\create_test_student.py --student-id v02_test_student
```

若需覆盖同名测试实例，显式追加 `--overwrite`。网页使用哪个学生由 `.env` 中的 `STUDENT_ID` 决定。

## 迁移策略

StudentModel v1/v2 会在读取时自动迁移到 v3：

- 顶层 `grade` 迁入 `identity.grade`；
- 旧的扁平 `concept_mastery` 按 subject 分发到六科知识图谱；
- `score_map.recent_scores` 迁入 `academic_records.score_history`；
- 拼写错误的 `prefered_style` 迁入 `learning_profile.preferences`；
- 旧 StudentModel 的 `model_version` 保持不变，Schema 迁移不伪装成一次学习进展更新。
