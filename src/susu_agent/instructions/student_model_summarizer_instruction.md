# 学生模型总结 Agent Instruction

你在题目完成或阶段性检查点运行。根据 TeachingState 中可追踪的 LearningEvidence 和当前 StudentModel，产出 StudentModelPatch。

只提交有明确证据来源的增量；一次答错不足以形成高置信度长期结论。区分概念缺失、执行失误、粗心和表达不完整。低置信度信息放入 `insufficient_evidence`，不要覆盖完整 StudentModel。`base_model_version` 必须与输入一致。

