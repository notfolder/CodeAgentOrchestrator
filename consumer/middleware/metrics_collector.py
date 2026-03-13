"""
MetricsCollector モジュール

OpenTelemetry 経由でメトリクスを送信するユーティリティクラスを定義する。
opentelemetry ライブラリが存在しない場合はダミー実装にフォールバックする。

CLASS_IMPLEMENTATION_SPEC.md § 5.6（MetricsCollector）に準拠する。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# opentelemetry をオプション依存として扱い、存在しない場合はダミーを使用する
try:
    from opentelemetry.metrics import Counter, Meter, MeterProvider, get_meter_provider

    _OPENTELEMETRY_AVAILABLE = True
except ImportError:
    _OPENTELEMETRY_AVAILABLE = False

    class Counter:  # type: ignore[no-redef]
        """opentelemetry が存在しない場合のダミーカウンター"""

        def add(self, value: float, attributes: dict[str, str] | None = None) -> None:
            """メトリクス加算（何もしない）"""
            pass

    class Meter:  # type: ignore[no-redef]
        """opentelemetry が存在しない場合のダミーメーター"""

        def create_counter(self, name: str, **kwargs: Any) -> Counter:
            """カウンターを生成する（ダミーを返す）"""
            return Counter()

    class MeterProvider:  # type: ignore[no-redef]
        """opentelemetry が存在しない場合のダミー MeterProvider"""

        def get_meter(self, name: str, **kwargs: Any) -> Meter:
            """メーターを取得する（ダミーを返す）"""
            return Meter()

    def get_meter_provider() -> MeterProvider:  # type: ignore[misc]
        """グローバル MeterProvider を取得する（ダミーを返す）"""
        return MeterProvider()


class MetricsCollector:
    """
    メトリクスコレクター

    OpenTelemetry 経由でメトリクスを送信するユーティリティクラス。
    opentelemetry ライブラリが存在しない場合はダミー実装を使用し、
    送信失敗時はログ記録のみ行って例外を伝播させない。

    Attributes:
        meter_provider: OpenTelemetry MeterProvider（または互換ダミー）
        meter: メトリクス収集メーター
        counters: カウンター名 → カウンターのマッピング
    """

    def __init__(self, meter_provider: MeterProvider | None = None) -> None:
        """
        初期化

        Args:
            meter_provider: 使用する MeterProvider。None の場合はグローバルプロバイダーを使用する。
        """
        # グローバルプロバイダーが未指定の場合は取得する
        if meter_provider is None:
            self.meter_provider: MeterProvider = get_meter_provider()
        else:
            self.meter_provider = meter_provider

        self.meter: Meter = self.meter_provider.get_meter(
            name="automata_codex",
            version="0.1.0",
        )
        # カウンター名 → Counter インスタンスのマッピング
        self.counters: dict[str, Counter] = {}

        if not _OPENTELEMETRY_AVAILABLE:
            logger.debug("opentelemetry が存在しないため、ダミー MetricsCollector を使用する")

    def send_metric(
        self,
        metric_name: str,
        labels: dict[str, str],
        value: float = 1.0,
    ) -> None:
        """
        メトリクスを送信する

        metric_name に対応するカウンターを取得または生成し、
        指定された値を加算する。送信失敗時はログ記録のみ行う。

        Args:
            metric_name: メトリクス名（カウンター名）
            labels: メトリクスに付与するラベル（属性）
            value: 加算する値（デフォルト 1.0）
        """
        try:
            # カウンターが未生成の場合は新規に生成する
            if metric_name not in self.counters:
                self.counters[metric_name] = self.meter.create_counter(
                    name=metric_name,
                    description=f"AutomataCodex メトリクス: {metric_name}",
                )

            counter = self.counters[metric_name]
            counter.add(value, attributes=labels)

        except Exception as exc:
            # 送信失敗はワークフローに影響させないためログのみ記録する
            logger.warning(
                "メトリクス送信に失敗した: metric_name=%s, labels=%s, error=%s",
                metric_name,
                labels,
                exc,
            )
