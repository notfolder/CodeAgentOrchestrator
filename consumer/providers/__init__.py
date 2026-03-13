"""
consumer/providers パッケージ

LLM会話履歴・プランニング履歴・ツール実行結果・タスク継承データの
永続化および取得を担うカスタムProvider群と、コンテキスト圧縮・ストレージ管理
サービスを提供する。

各クラスの概要:
    - PostgreSqlChatHistoryProvider: LLM会話履歴をPostgreSQLに永続化するProvider
    - PlanningContextProvider: プランニング履歴をPostgreSQLに保存しエージェントへ提供するProvider
    - ToolResultContextProvider: ツール実行結果をファイル＋DBに保存しエージェントへ提供するProvider
    - TaskInheritanceContextProvider: 同一Issue/MRの過去タスクの継承データをエージェントへ提供するProvider
    - ContextCompressionService: context_messagesのトークン数を監視して古いメッセージを要約圧縮するサービス
    - ContextStorageManager: 各Providerとリポジトリへの参照を集約する統合管理クラス
"""
