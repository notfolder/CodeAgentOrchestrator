"""
プロンプト定義ドメインモデル定義

各エージェントノードで使用するLLMのシステムプロンプトとパラメータを
表すPydanticモデルを定義する。
PROMPT_DEFINITION_SPEC.md § 3（JSON形式の仕様）に準拠する。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LLMParams(BaseModel):
    """
    LLMパラメータ設定

    各エージェントのLLM呼び出しパラメータ。
    default_llm_params で全体のデフォルトを定義し、各プロンプト定義で上書き可能。
    """

    model: str | None = Field(
        default=None,
        description=(
            "使用するモデル名（省略時はuser_configsテーブルの設定に従う）"
        ),
    )
    temperature: float | None = Field(
        default=None, ge=0.0, le=2.0, description="生成の多様性（0.0〜2.0）"
    )
    max_tokens: int | None = Field(
        default=None, ge=1, description="最大生成トークン数"
    )
    top_p: float | None = Field(
        default=None, ge=0.0, le=1.0, description="nucleus samplingのしきい値"
    )


class PromptConfig(BaseModel):
    """
    プロンプト設定

    PROMPT_DEFINITION_SPEC.md § 3.3 に準拠したエージェント1件分のプロンプト定義。
    エージェント定義の prompt_id をキーとして AgentFactory が参照する。
    """

    id: str = Field(
        description=(
            "プロンプトの一意識別子"
            "（エージェント定義の prompt_id と一致させる）"
        )
    )
    description: str | None = Field(default=None, description="プロンプトの説明文")
    system_prompt: str = Field(description="LLMに渡すシステムプロンプト")
    llm_params: LLMParams | None = Field(
        default=None,
        description="このエージェント固有のLLMパラメータ（default_llm_params を上書き）",
    )

    def get_effective_llm_params(
        self, defaults: LLMParams | None = None
    ) -> LLMParams:
        """
        デフォルトパラメータとエージェント固有パラメータをマージして返す。

        エージェント固有パラメータが None でないフィールドのみデフォルトを上書きする。

        Args:
            defaults: デフォルトLLMパラメータ（PromptDefinition.default_llm_params）

        Returns:
            マージされたLLMParams
        """
        if defaults is None:
            effective = LLMParams()
        else:
            effective = defaults.model_copy()

        if self.llm_params is not None:
            override = self.llm_params.model_dump(exclude_none=True)
            effective = effective.model_copy(update=override)

        return effective


class PromptDefinition(BaseModel):
    """
    プロンプト定義

    PROMPT_DEFINITION_SPEC.md § 3.1 に準拠したプロンプト定義全体。
    workflow_definitions テーブルの prompt_definition カラム（JSONB）に保存される。
    """

    version: str = Field(description="定義フォーマットバージョン（例: '1.0'）")
    default_llm_params: LLMParams | None = Field(
        default=None,
        description="全エージェント共通のデフォルトLLMパラメータ",
    )
    prompts: list[PromptConfig] = Field(
        description="各エージェントのプロンプト定義配列"
    )

    def get_prompt(self, prompt_id: str) -> PromptConfig | None:
        """指定されたIDのプロンプト設定を返す。存在しない場合はNoneを返す。"""
        for prompt in self.prompts:
            if prompt.id == prompt_id:
                return prompt
        return None

    def get_effective_llm_params(self, prompt_id: str) -> LLMParams:
        """
        指定されたプロンプトIDの有効なLLMパラメータを返す。

        デフォルトパラメータとエージェント固有パラメータをマージして返す。

        Args:
            prompt_id: プロンプトID

        Returns:
            有効なLLMParams（プロンプトが存在しない場合はデフォルト値を返す）
        """
        prompt = self.get_prompt(prompt_id)
        if prompt is None:
            return self.default_llm_params or LLMParams()
        return prompt.get_effective_llm_params(self.default_llm_params)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PromptDefinition":
        """辞書からPromptDefinitionインスタンスを生成する。"""
        return cls.model_validate(data)
