+++
patch_id = "math.example_topic"
version = "1.0.0"
kind = "context"
title = "补丁标题"
summary = "一句话说明补丁解决什么教学问题，以及何时应检索它。"
target_agents = ["teaching_planner", "teaching_executor"]
step_ids = ["S2", "S7"]
concept_ids = ["stable_concept_id"]
keywords = ["学生或题目中可能出现的词", "同义表达"]
priority = 50
enabled = true
knowledge = [
  "概念A | 需要检查 | 条件B",
  "条件B | 决定 | 结论C",
]
+++

# 补丁标题

在这里写供 Agent 使用的完整补丁正文。一个文件只解决一个清晰主题。

## 适用边界

- 说明什么时候适用。
- 说明什么时候不适用。

## 教学或推理规则

写出可执行、无歧义的规则；不要复制主教案已有内容。
