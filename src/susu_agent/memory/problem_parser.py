"""在不增加模型调用的情况下构造保守的题目结构投影。"""

import re
from hashlib import sha256

from susu_agent.schemas.problem_representation import ProblemRepresentation
from susu_agent.schemas.solution import Solution


def build_problem_representation(
    problem: str,
    *,
    subject: str,
    solution: Solution | None = None,
) -> ProblemRepresentation:
    normalized = problem.strip()
    variables = list(
        dict.fromkeys(
            re.findall(r"(?<![A-Za-z])[a-zA-Z](?![A-Za-z])", normalized)
        )
    )
    goal_type = _classify_goal(normalized)
    problem_type = _classify_problem(normalized)
    concept_ids = list(
        dict.fromkeys(
            concept
            for step in (solution.steps if solution is not None else [])
            for concept in step.concept_ids
        )
    )
    if goal_type != "unknown" and goal_type not in concept_ids:
        concept_ids.append(goal_type)
    condition_markers = re.split(r"[，,；;。\n]", normalized)
    conditions = list(
        dict.fromkeys(
            segment.strip()
            for segment in condition_markers
            if any(
                marker in segment
                for marker in ("满足", "已知", "若", "当", "定义域", "subject to")
            )
        )
    )
    digest = sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return ProblemRepresentation(
        problem_id=f"problem_{digest}",
        subject=subject,
        goal_type=goal_type,
        problem_type=problem_type,
        objects=variables,
        conditions=conditions,
        goal=solution.goal if solution is not None else normalized,
        structural_features={
            "degrees_of_freedom": len(variables),
            "symmetry": "present" if "对称" in normalized else "unknown",
        },
        concept_ids=concept_ids,
    )


def _classify_goal(text: str) -> str:
    if any(value in text for value in ("最大", "最小", "最值", "extrem")):
        return "extremum"
    if any(value in text for value in ("证明", "prove", "show that")):
        return "proof"
    if any(value in text for value in ("求值", "计算", "calculate", "evaluate")):
        return "calculation"
    if any(value in text for value in ("构造", "construct")):
        return "construction"
    return "unknown"


def _classify_problem(text: str) -> str:
    if any(value in text for value in ("不等式", "inequality", "≤", "≥")):
        return "inequality"
    if any(value in text for value in ("函数", "function")):
        return "function"
    if any(value in text for value in ("几何", "三角形", "圆", "geometry")):
        return "geometry"
    if any(value in text for value in ("方程", "equation", "=")):
        return "equation"
    return "unknown"
