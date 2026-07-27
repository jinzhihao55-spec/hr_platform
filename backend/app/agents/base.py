"""Agent 基类。此处的"Agent"是把确定性流水线步骤与可选 LLM skill 调用组合起来的
轻量编排器。Agent 绝不编造任何数字——所有上报的数字都来自确定性引擎。

按需授权：每个 Agent 仅能加载/调用 **自己白名单内** 的 Skill 与场景
（见 app/agents/skill_registry.py），不会拿到全部 Skill。"""
from __future__ import annotations

import abc
from typing import Any

from app.agents.skill_registry import AGENT_REFERENCE_SKILLS, AGENT_SCENARIOS
from app.core.logging import get_logger
from app.llm import scenarios as _scenarios
from app.llm.skill_loader import load_skill


class BaseAgent(abc.ABC):
    name: str = "agent"

    def __init__(self) -> None:
        self.log = get_logger(f"agent.{self.name}")
        self.allowed_skills: list[str] = AGENT_REFERENCE_SKILLS.get(self.name, [])
        self.allowed_scenarios: list[str] = AGENT_SCENARIOS.get(self.name, [])

    # ---- 受控的 Skill / 场景访问（白名单强制） ----
    def load_reference_skill(self, name: str) -> str | None:
        """加载本 Agent 白名单内的参考口径文档；越权抛 PermissionError。"""
        if name not in self.allowed_skills:
            raise PermissionError(
                f"Agent[{self.name}] 无权加载 Skill「{name}」（仅限：{self.allowed_skills}）"
            )
        return load_skill(name)

    def run_scenario(self, name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """调用本 Agent 白名单内的 LLM 场景；越权抛 PermissionError。"""
        if name not in self.allowed_scenarios:
            raise PermissionError(
                f"Agent[{self.name}] 无权调用场景「{name}」（仅限：{self.allowed_scenarios}）"
            )
        return _scenarios.SCENARIOS[name](*args, **kwargs)

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """默认入口。各 Agent 可覆写为自己的入口（如 ExtractionAgent.run），
        或提供更细的入口（如 CalculationAgent.run_daily / run_weekly）。"""
        raise NotImplementedError(f"Agent[{self.name}] 未实现 run()")
