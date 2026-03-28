<template>
  <!-- Mermaid フローチャートプレビューコンポーネント -->
  <div class="mermaid-preview">
    <!-- グラフ定義が空の場合はプレースホルダを表示する -->
    <div v-if="!hasValidGraph" class="mermaid-placeholder">
      <v-icon size="48" color="grey-lighten-1">mdi-graph-outline</v-icon>
      <p class="text-grey text-body-2 mt-2">グラフ定義が入力されると、ここにフローチャートが表示されます</p>
    </div>
    <!-- レンダリング中のローディング表示 -->
    <div v-else-if="isRendering" class="mermaid-loading">
      <v-progress-circular indeterminate color="primary" size="32" />
      <p class="text-grey text-body-2 mt-2">グラフを描画中...</p>
    </div>
    <!-- レンダリングエラー表示 -->
    <div v-else-if="renderError" class="mermaid-error">
      <v-icon size="32" color="error">mdi-alert-circle-outline</v-icon>
      <p class="text-error text-body-2 mt-1">グラフの描画に失敗しました: {{ renderError }}</p>
    </div>
    <!-- SVG 描画領域 -->
    <div v-show="!isRendering && !renderError && hasValidGraph" ref="mermaidContainer" class="mermaid-container" />
  </div>
</template>

<script setup>
import mermaid from 'mermaid'
import { ref, computed, watch, onMounted, nextTick } from 'vue'

// ============================================================
// Props
// ============================================================
const props = defineProps({
  /** グラフ定義オブジェクト（null または graph_definition の JSON オブジェクト） */
  graphDefinition: {
    type: Object,
    default: null,
  },
})

// ============================================================
// 内部状態
// ============================================================
/** SVG を描画するコンテナ要素の参照 */
const mermaidContainer = ref(null)
/** レンダリング中フラグ */
const isRendering = ref(false)
/** レンダリングエラーメッセージ（なければ空文字） */
const renderError = ref('')
/** mermaid の初期化済みフラグ */
let mermaidInitialized = false
/** レンダリング ID カウンター（重複防止用） */
let renderCount = 0

// ============================================================
// 算出プロパティ
// ============================================================

/** 有効なグラフ定義が渡されているかどうか */
const hasValidGraph = computed(() => {
  const g = props.graphDefinition
  if (!g || typeof g !== 'object') return false
  const nodes = g.nodes
  return Array.isArray(nodes) && nodes.length > 0
})

// ============================================================
// Mermaid 初期化
// ============================================================

/**
 * mermaid ライブラリを一度だけ初期化する。
 * テーマは neutral を使用し、セキュアモードを無効化して SVG レンダリングを許可する。
 */
function initMermaid() {
  if (mermaidInitialized) return
  mermaid.initialize({
    startOnLoad: false,
    theme: 'neutral',
    securityLevel: 'loose',
    flowchart: {
      useMaxWidth: true,
      htmlLabels: false,
    },
  })
  mermaidInitialized = true
}

// ============================================================
// Mermaid 文字列生成（Python 実装と同一ロジック）
// ============================================================

/**
 * ノード種別に応じた Mermaid ノード定義行を生成する。
 * @param {string} nodeId - ノード識別子
 * @param {string} label - ノード表示ラベル
 * @param {string} nodeType - ノード種別（agent / executor / condition）
 * @param {string} state - ノード状態（pending 固定）
 * @returns {string} Mermaid ノード定義文字列
 */
function makeNodeDef(nodeId, label, nodeType, state) {
  // HTML タグを含む文字列を安全にエスケープする
  const safeLabel = String(label).replace(/"/g, "'")
  if (nodeType === 'condition') {
    return `${nodeId}{"${safeLabel}"}:::${state}`
  }
  if (nodeType === 'executor') {
    return `${nodeId}(["${safeLabel}"]):::${state}`
  }
  return `${nodeId}["${safeLabel}"]:::${state}`
}

/**
 * グラフ定義から Mermaid フローチャート文字列を生成する。
 * 全ノードを pending 状態としてレンダリングする。
 * @param {Object} graphDef - グラフ定義オブジェクト
 * @returns {string} Mermaid フローチャート文字列
 */
function buildMermaidString(graphDef) {
  const nodes = graphDef.nodes || []
  const edges = graphDef.edges || []

  // ノード情報を ID でインデックス化する
  const nodeMap = Object.fromEntries(nodes.map((n) => [n.id, n]))
  const nodeTypeMap = Object.fromEntries(nodes.map((n) => [n.id, n.type || 'agent']))

  // ① 並列グループ検出（Python 実装と同一ロジック）
  // 同一 from ノードから出るエッジを集計する
  const fromToMap = {}
  for (const edge of edges) {
    if (!fromToMap[edge.from]) fromToMap[edge.from] = []
    fromToMap[edge.from].push(edge.to)
  }

  // condition 以外の from ノードで 2 つ以上の to ノードを持つものを並列グループとする
  const parallelGroups = {}
  for (const [fromId, toIds] of Object.entries(fromToMap)) {
    if (toIds.length >= 2 && nodeTypeMap[fromId] !== 'condition') {
      parallelGroups[fromId] = toIds
    }
  }

  // 並列グループに属する to ノードの集合
  const parallelTargetNodes = new Set(Object.values(parallelGroups).flat())

  // ② ノード定義行の生成
  const lines = ['flowchart TD']

  // 並列グループに属さないノードを先に出力する
  for (const node of nodes) {
    if (parallelTargetNodes.has(node.id)) continue
    const label = node.label || node.id
    const nodeType = node.type || 'agent'
    lines.push(`  ${makeNodeDef(node.id, label, nodeType, 'pending')}`)
  }

  // 並列グループのノードを subgraph でまとめて出力する
  let groupIdx = 1
  for (const [, toIds] of Object.entries(parallelGroups)) {
    lines.push(`  subgraph parallel${groupIdx}["並列処理${groupIdx}"]`)
    lines.push('    direction LR')
    for (const nodeId of toIds) {
      const node = nodeMap[nodeId] || { id: nodeId, label: nodeId, type: 'agent' }
      const label = node.label || node.id
      const nodeType = node.type || 'agent'
      lines.push(`    ${makeNodeDef(nodeId, label, nodeType, 'pending')}`)
    }
    lines.push('  end')
    groupIdx++
  }

  // ③ エッジ定義行の生成
  const processedParallelFrom = new Set()
  for (const edge of edges) {
    const fromId = edge.from
    const toId = edge.to
    const edgeLabel = edge.label || ''

    if (parallelGroups[fromId]) {
      if (processedParallelFrom.has(fromId)) continue
      // 並列ファンアウト: A --> B & C 形式でまとめて出力する
      const toStr = parallelGroups[fromId].join(' & ')
      lines.push(`  ${fromId} --> ${toStr}`)
      processedParallelFrom.add(fromId)
    } else if (edgeLabel) {
      lines.push(`  ${fromId} -- ${edgeLabel} --> ${toId}`)
    } else {
      lines.push(`  ${fromId} --> ${toId}`)
    }
  }

  // ④ classDef 行の生成（全状態種別を常に出力する）
  lines.push('  classDef pending fill:#9e9e9e,color:#fff,stroke:#616161')
  lines.push('  classDef running fill:#ff9800,color:#fff,stroke:#e65100,stroke-width:3px')
  lines.push('  classDef done fill:#4caf50,color:#fff,stroke:#388e3c')
  lines.push('  classDef error fill:#f44336,color:#fff,stroke:#b71c1c')
  lines.push('  classDef skipped fill:#eeeeee,color:#9e9e9e,stroke:#bdbdbd,stroke-dasharray:4')

  return lines.join('\n')
}

// ============================================================
// SVG レンダリング
// ============================================================

/**
 * Mermaid フローチャートを SVG としてコンテナにレンダリングする。
 */
async function renderMermaid() {
  if (!hasValidGraph.value) return

  isRendering.value = true
  renderError.value = ''
  renderCount++
  const currentCount = renderCount

  await nextTick()

  try {
    initMermaid()
    const mermaidStr = buildMermaidString(props.graphDefinition)
    const rendererId = `mermaid-preview-${currentCount}`

    // mermaid.render() で SVG 文字列を生成する
    const { svg } = await mermaid.render(rendererId, mermaidStr)

    // 非同期処理中に新しいレンダリングが開始された場合は破棄する
    if (currentCount !== renderCount) return

    if (mermaidContainer.value) {
      mermaidContainer.value.innerHTML = svg
    }
  } catch (err) {
    if (currentCount !== renderCount) return
    console.error('[MermaidPreview] レンダリングエラー:', err)
    renderError.value = err.message || 'グラフ構文エラー'
  } finally {
    if (currentCount === renderCount) {
      isRendering.value = false
    }
  }
}

// ============================================================
// ライフサイクル / ウォッチ
// ============================================================

onMounted(() => {
  if (hasValidGraph.value) {
    renderMermaid()
  }
})

// graphDefinition が変化するたびに再レンダリングする
watch(
  () => props.graphDefinition,
  () => {
    if (hasValidGraph.value) {
      renderMermaid()
    } else {
      renderError.value = ''
      isRendering.value = false
      if (mermaidContainer.value) {
        mermaidContainer.value.innerHTML = ''
      }
    }
  },
  { deep: true },
)
</script>

<style scoped>
.mermaid-preview {
  width: 100%;
  min-height: 120px;
}

.mermaid-placeholder,
.mermaid-loading,
.mermaid-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px;
  min-height: 120px;
  background-color: #f5f5f5;
  border-radius: 4px;
}

.mermaid-container {
  width: 100%;
  overflow: auto;
}

/* mermaid が生成する SVG を横幅いっぱいに広げる */
.mermaid-container :deep(svg) {
  max-width: 100%;
  height: auto;
}
</style>
