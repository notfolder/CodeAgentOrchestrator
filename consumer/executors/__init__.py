"""
Executor群パッケージ

ワークフローグラフ内で使用される各種 Executor クラスを提供する。
各 Executor は BaseExecutor を継承し、handle() メソッドを実装する。

CLASS_IMPLEMENTATION_SPEC.md § 3（Executor群）に準拠する。
"""

from __future__ import annotations

from consumer.executors.base_executor import BaseExecutor
from consumer.executors.branch_merge_executor import BranchMergeExecutor
from consumer.executors.content_transfer_executor import ContentTransferExecutor
from consumer.executors.exec_env_setup_executor import ExecEnvSetupExecutor
from consumer.executors.plan_env_setup_executor import PlanEnvSetupExecutor
from consumer.executors.progress_finalize_executor import ProgressFinalizeExecutor
from consumer.executors.task_context_init_executor import TaskContextInitExecutor

__all__ = [
    "BaseExecutor",
    "BranchMergeExecutor",
    "ContentTransferExecutor",
    "ExecEnvSetupExecutor",
    "PlanEnvSetupExecutor",
    "ProgressFinalizeExecutor",
    "TaskContextInitExecutor",
]
