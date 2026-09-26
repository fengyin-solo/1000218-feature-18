<template>
  <section class="page" data-module="expense">
    <header class="page-head">
      <div>
        <h2>费用报销管理</h2>
        <p class="page-desc">维护报销单，围绕报销单号、报销人、费用类别、发生日期做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记报销单</button>
        <button class="btn" type="button" @click="exportRows">导出费用报销清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <!-- 未提交草稿提示：离开后重新进入可一键恢复 -->
    <div v-if="activeDrafts.length" class="banner info">
      <span>
        有 {{ activeDrafts.length }} 张报销单存在未提交的处理草稿：
        <template v-for="(draft, index) in activeDrafts" :key="draft.entry_id">
          <button class="link" type="button" @click="resumeDraft(draft)">{{ draft.entry_no || `报销单 ${draft.entry_id}` }}</button>
          <span v-if="index < activeDrafts.length - 1">、</span>
        </template>
      </span>
      <button class="btn" type="button" @click="reloadDrafts">刷新草稿</button>
    </div>

    <!-- 网络失败未送达的提交：重新进入后可继续重试 -->
    <div v-if="pendingQueue.length" class="banner warn">
      <span>
        有 {{ pendingQueue.length }} 笔处理提交因网络失败未送达，原处理内容已保留，
        <button class="link" type="button" @click="retryAll">点此重试</button>
      </span>
      <span v-if="retryHint" class="error-text">{{ retryHint }}</span>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <template v-if="row.status === '已打款'">
              <span class="muted-text">已打款，记录不可改</span>
            </template>
            <template v-else>
              <button class="link" type="button" @click="openPanel(row)">处理</button>
              <span v-if="draftMap[Number(row.id)]" class="badge warn">未提交草稿</span>
            </template>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无费用报销数据，可先登记报销单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条费用报销记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 处理面板：动作选择、补充说明与当前位置都会持久化为草稿 -->
    <div v-if="panel.open" class="modal-mask" @click.self="closePanel">
      <div class="modal" role="dialog" aria-modal="true" aria-label="报销处理">
        <div class="modal-head">
          <strong>处理报销单 · {{ panel.entryNo }}</strong>
          <span class="muted-text">当前状态：{{ panel.entryStatus }}</span>
        </div>

        <div ref="panelBody" class="modal-body" @scroll="onPanelScroll">
          <div v-if="panel.invalid" class="banner warn inline">
            <span>{{ panel.invalidReason || '该报销单已被正式处理，原草稿已失效。' }}</span>
          </div>

          <div class="form-block">
            <span class="form-label">
              处理动作
              <span v-if="panel.isDraft" class="badge warn">未提交</span>
            </span>
            <label v-for="action in actionOptions" :key="action" class="radio-item">
              <input v-model="panel.action" type="radio" name="expense-action" :value="action" :disabled="panel.invalid" />
              {{ action }}
            </label>
          </div>

          <div class="form-block">
            <span class="form-label">补充说明</span>
            <textarea
              v-model="panel.note"
              class="note-input"
              rows="4"
              placeholder="填写本次处理的补充说明，未提交前会自动存为草稿"
              :disabled="panel.invalid"
            ></textarea>
          </div>

          <div class="form-block">
            <span class="form-label">
              处理记录
              <span class="muted-text">只增不改，随时可查</span>
            </span>
            <ul v-if="historyItems.length" class="history-list">
              <li v-for="item in historyItems" :key="item.id">
                <span class="history-title">{{ item.acted_at }} · {{ item.operator }} · {{ item.action }}</span>
                <span class="history-flow">{{ item.before_status }} → {{ item.after_status }}</span>
                <span v-if="item.note" class="history-note">{{ item.note }}</span>
              </li>
            </ul>
            <p v-else class="muted-text">暂无正式处理记录。</p>
          </div>
        </div>

        <footer class="modal-foot">
          <span class="save-hint" :class="{ failed: panel.saveHintFailed }">{{ panel.saveHint || '内容会自动保存为草稿' }}</span>
          <div class="modal-actions">
            <button class="btn ghost" type="button" @click="discardDraft" :disabled="panel.submitting">丢弃草稿</button>
            <button class="btn" type="button" @click="closePanel" :disabled="panel.submitting">稍后继续</button>
            <button
              class="btn primary"
              type="button"
              :disabled="panel.invalid || panel.submitting || !panel.action"
              @click="submitAction"
            >
              {{ panel.submitting ? '提交中…' : '正式提交' }}
            </button>
          </div>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null>

interface DraftShape {
  id?: number
  entry_id: number
  entry_no?: string
  operator: string
  action: string | null
  note: string
  position: number
  active?: boolean
  updated_at?: string
  valid?: boolean
  entry_status?: string | null
}

interface HistoryItem {
  id: number
  entry_id: number
  operator: string
  action: string
  before_status: string
  after_status: string
  note: string
  acted_at: string
  request_id?: string | null
  message: string
}

interface PendingItem {
  request_id: string
  entry_id: number
  entry_no: string
  action: string
  note: string
  operator: string
}

const ENDPOINT = '/api/expense'
const columns = ['报销单号', '报销人', '费用类别', '发生日期', '报销金额', '票据张数', '所属科目', '报销状态']
const actionOptions = ['提交报销', '审核通过', '驳回报销', '确认打款']
const stats = [
  { label: '待审核报销', value: 0 },
  { label: '本月报销额', value: 0 },
  { label: '已驳回报销', value: 0 },
]

const session = useSessionStore()
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const serverDrafts = ref<DraftShape[]>([])
const localDrafts = ref<DraftShape[]>([])
const pendingQueue = ref<PendingItem[]>([])
const retryHint = ref('')
const historyItems = ref<HistoryItem[]>([])
const panelBody = ref<HTMLElement | null>(null)

const panel = reactive({
  open: false,
  entryId: 0,
  entryNo: '',
  entryStatus: '',
  action: '',
  note: '',
  position: 0,
  isDraft: false,
  invalid: false,
  invalidReason: '',
  saveHint: '',
  saveHintFailed: false,
  submitting: false,
  requestId: '',
})

let saveTimer: ReturnType<typeof setTimeout> | undefined
let positionTimer: ReturnType<typeof setTimeout> | undefined
let lastSentPosition = 0
let lastSavedPosition = 0
let restoring = false

// ---------------------------------------------------------------------------
// 本地兜底存储：接口暂时不可达时，草稿和待提交动作仍保留在本机，下次进入可继续。
// ---------------------------------------------------------------------------
function mirrorKey() {
  return `expense:draft-mirror:${session.operator}`
}
function pendingKey() {
  return `expense:pending-submissions:${session.operator}`
}

function readMirrors(): DraftShape[] {
  try {
    const raw = localStorage.getItem(mirrorKey())
    const parsed: unknown = raw ? JSON.parse(raw) : {}
    return parsed && typeof parsed === 'object' ? Object.values(parsed as Record<string, DraftShape>) : []
  } catch {
    return []
  }
}

function syncMirrorRef() {
  localDrafts.value = readMirrors()
}

function writeMirror(draft: DraftShape) {
  const raw = localStorage.getItem(mirrorKey())
  let map: Record<string, DraftShape> = {}
  try {
    map = raw ? (JSON.parse(raw) as Record<string, DraftShape>) : {}
  } catch {
    map = {}
  }
  map[String(draft.entry_id)] = draft
  localStorage.setItem(mirrorKey(), JSON.stringify(map))
  syncMirrorRef()
}

function removeMirror(entryId: number) {
  const raw = localStorage.getItem(mirrorKey())
  if (!raw) {
    syncMirrorRef()
    return
  }
  let map: Record<string, DraftShape> = {}
  try {
    map = JSON.parse(raw) as Record<string, DraftShape>
  } catch {
    map = {}
  }
  delete map[String(entryId)]
  localStorage.setItem(mirrorKey(), JSON.stringify(map))
  syncMirrorRef()
}

function readPendingQueue(): PendingItem[] {
  try {
    const raw = localStorage.getItem(pendingKey())
    const parsed: unknown = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? (parsed as PendingItem[]) : []
  } catch {
    return []
  }
}

function writePendingQueue(items: PendingItem[]) {
  pendingQueue.value = items
  localStorage.setItem(pendingKey(), JSON.stringify(items))
}

// 合并服务端草稿与本地兜底草稿（服务端优先），用于顶部提示和行内角标。
const activeDrafts = computed<DraftShape[]>(() => {
  const merged = new Map<number, DraftShape>()
  for (const draft of localDrafts.value) {
    merged.set(draft.entry_id, draft)
  }
  for (const draft of serverDrafts.value) {
    merged.set(draft.entry_id, { ...draft, entry_no: merged.get(draft.entry_id)?.entry_no })
  }
  return [...merged.values()].sort((a, b) => a.entry_id - b.entry_id)
})

const draftMap = computed<Record<number, DraftShape>>(() => {
  const map: Record<number, DraftShape> = {}
  for (const draft of activeDrafts.value) {
    map[draft.entry_id] = draft
  }
  return map
})

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '报销单登记入口尚未接入审批流'
}

// ---------------------------------------------------------------------------
// 列表与草稿加载
// ---------------------------------------------------------------------------
async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('报销单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '费用报销列表读取失败'
  }
}

async function reloadDrafts() {
  try {
    const response = await request(`${ENDPOINT}/drafts?operator=${encodeURIComponent(session.operator)}`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    serverDrafts.value = (payload.items ?? []) as DraftShape[]
    // 服务端确认已失效的草稿，清掉本地兜底副本。
    const liveIds = new Set(serverDrafts.value.map((item) => item.entry_id))
    for (const draft of readMirrors()) {
      if (!liveIds.has(draft.entry_id)) {
        removeMirror(draft.entry_id)
      }
    }
  } catch {
    // 网络不可用时仅展示本地兜底草稿，不打断页面。
  }
}

// 重新进入页面时，把仅留在本机的草稿补发到服务端，随后统一拉取。
async function reconcileMirrors() {
  for (const draft of readMirrors()) {
    try {
      await persistDraft(draft, { silent: true })
    } catch {
      // 仍不可达就继续保留本地副本。
    }
  }
  await reloadDrafts()
}

// ---------------------------------------------------------------------------
// 处理面板与草稿保存
// ---------------------------------------------------------------------------
async function openPanel(row: Row) {
  const entryId = Number(row.id)
  preparePanel(entryId, String(row['报销单号'] ?? entryId), String(row.status ?? ''))
  await hydratePanel(entryId)
}

async function resumeDraft(draft: DraftShape) {
  preparePanel(draft.entry_id, draft.entry_no || `报销单 ${draft.entry_id}`, draft.entry_status ?? '')
  await hydratePanel(draft.entry_id)
}

function preparePanel(entryId: number, entryNo: string, entryStatus: string) {
  panel.open = true
  panel.entryId = entryId
  panel.entryNo = entryNo
  panel.entryStatus = entryStatus
  panel.action = ''
  panel.note = ''
  panel.position = 0
  panel.isDraft = false
  panel.invalid = false
  panel.invalidReason = ''
  panel.saveHint = ''
  panel.saveHintFailed = false
  panel.submitting = false
  panel.requestId = ''
  lastSavedPosition = 0
  historyItems.value = []
}

async function hydratePanel(entryId: number) {
  restoring = true
  void loadHistory(entryId)
  let restored: DraftShape | null = null
  try {
    const response = await request(`${ENDPOINT}/${entryId}/drafts?operator=${encodeURIComponent(session.operator)}`)
    if (response.ok) {
      const payload = await response.json()
      if (payload.ok) {
        restored = payload.draft as DraftShape
      } else if (payload.draft) {
        // 草稿已失效（报销单已被正式处理）：标明原因并禁止继续提交。
        panel.invalid = true
        panel.invalidReason = payload.draft.invalid_reason || payload.message
        panel.entryStatus = payload.draft.entry_status ?? panel.entryStatus
        historyItems.value = []
        removeMirror(entryId)
      }
    }
  } catch {
    const local = readMirrors().find((item) => item.entry_id === entryId)
    if (local) {
      restored = local
      panel.saveHint = '服务暂不可达，当前展示本机暂存草稿'
      panel.saveHintFailed = true
    }
  }

  if (restored) {
    applyDraft(restored)
  } else {
    restoring = false
  }
  await nextTick()
  if (panelBody.value && panel.position > 0) {
    panelBody.value.scrollTop = panel.position
  }
}

function applyDraft(draft: DraftShape) {
  panel.action = draft.action ?? ''
  panel.note = draft.note ?? ''
  panel.position = draft.position ?? 0
  lastSavedPosition = panel.position
  panel.isDraft = Boolean(draft.action || draft.note)
  panel.requestId = ''
  if (draft.entry_status) {
    panel.entryStatus = draft.entry_status
  }
  restoring = false
  void nextTick(() => {
    if (panelBody.value) {
      panelBody.value.scrollTop = panel.position
    }
  })
}

async function loadHistory(entryId: number) {
  try {
    const response = await request(`${ENDPOINT}/${entryId}/history`)
    if (response.ok) {
      const payload = await response.json()
      historyItems.value = (payload.items ?? []) as HistoryItem[]
    }
  } catch {
    // 历史不影响主流程，留空即可。
  }
}

// 动作或说明变化后自动保存（防抖，避免逐字请求）。
watch(
  () => [panel.action, panel.note],
  () => {
    if (!panel.open || restoring || panel.invalid) {
      return
    }
    panel.isDraft = Boolean(panel.action || panel.note)
    if (saveTimer) {
      clearTimeout(saveTimer)
    }
    saveTimer = setTimeout(() => {
      void persistDraft(currentDraft())
    }, 600)
  },
)

function currentDraft(): DraftShape {
  return {
    entry_id: panel.entryId,
    entry_no: panel.entryNo,
    operator: session.operator,
    action: panel.action || null,
    note: panel.note,
    position: panel.position,
  }
}

async function persistDraft(draft: DraftShape, options: { silent?: boolean } = {}): Promise<void> {
  writeMirror(draft)
  try {
    const response = await request(`${ENDPOINT}/${draft.entry_id}/drafts`, {
      method: 'PUT',
      body: JSON.stringify({
        action: draft.action,
        note: draft.note,
        position: draft.position,
        operator: draft.operator,
      }),
    })
    const payload = response.ok ? await response.json() : null
    if (!payload?.ok) {
      throw new Error(payload?.message ?? '草稿保存失败')
    }
    const saved = { ...(payload.entry as DraftShape), entry_no: draft.entry_no }
    writeMirror(saved)
    if (!options.silent && panel.entryId === draft.entry_id) {
      panel.saveHint = `草稿已保存（${new Date().toLocaleTimeString()}），离开后可恢复`
      panel.saveHintFailed = false
    }
    if (panel.entryId === draft.entry_id) {
      lastSavedPosition = draft.position
    }
    void reloadDrafts()
  } catch (error) {
    if (!options.silent && panel.entryId === draft.entry_id) {
      panel.saveHint = error instanceof Error ? `${error.message}，已暂存本机` : '草稿已暂存本机，网络恢复后自动补发'
      panel.saveHintFailed = true
    }
  }
}

// 面板滚动位置即“当前所在位置”，节流保存。
function onPanelScroll() {
  if (!panelBody.value) {
    return
  }
  panel.position = Math.round(panelBody.value.scrollTop)
  if (Math.abs(panel.position - lastSentPosition) < 40) {
    return
  }
  if (positionTimer) {
    clearTimeout(positionTimer)
  }
  positionTimer = setTimeout(() => {
    lastSentPosition = panel.position
    void persistDraft(currentDraft(), { silent: true }).catch(() => undefined)
  }, 500)
}

function closePanel() {
  // 位置滚动过或有未提交内容时，离开前把草稿落盘。
  if (panel.action || panel.note || panel.position !== lastSavedPosition) {
    void persistDraft(currentDraft(), { silent: true })
  }
  panel.open = false
  void reloadDrafts()
}

async function discardDraft() {
  try {
    await request(`${ENDPOINT}/${panel.entryId}/drafts?operator=${encodeURIComponent(session.operator)}`, {
      method: 'DELETE',
    })
  } catch {
    // 即便删除请求未送达，也先清掉本机副本；服务端草稿可在恢复时再处理。
  }
  removeMirror(panel.entryId)
  panel.open = false
  await reloadDrafts()
}

// ---------------------------------------------------------------------------
// 正式提交：幂等 request_id 保证网络失败可安全重试；以后提交为准，但不覆盖打款。
// ---------------------------------------------------------------------------
function newRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

async function submitAction() {
  if (!panel.action) {
    return
  }
  panel.submitting = true
  panel.saveHint = ''
  const requestId = panel.requestId || newRequestId()
  panel.requestId = requestId
  const item: PendingItem = {
    request_id: requestId,
    entry_id: panel.entryId,
    entry_no: panel.entryNo,
    action: panel.action,
    note: panel.note,
    operator: session.operator,
  }
  try {
    const outcome = await postAction(item)
    if (outcome === 'done') {
      finishSubmitted(item)
      panel.open = false
      await Promise.all([reload(), reloadDrafts()])
    } else {
      // 已被他人打款：终态不可覆盖，本地动作不再重试，原打款记录保持可查。
      writePendingQueue(readPendingQueue().filter((queued) => queued.request_id !== requestId))
      removeMirror(item.entry_id)
      panel.open = false
      errorMessage.value = `报销单 ${item.entry_no} 已被打款，本次「${item.action}」未覆盖任何记录`
      await Promise.all([reload(), reloadDrafts()])
    }
  } catch (error) {
    // 网络失败：动作进入待重试队列，原草稿保持可继续编辑。
    const queue = readPendingQueue().filter((queued) => queued.request_id !== requestId)
    queue.push(item)
    writePendingQueue(queue)
    panel.saveHint = error instanceof Error
      ? `${error.message}；提交已保留，可在顶部横幅重试`
      : '网络失败，提交未送达；已保留，可在顶部横幅重试'
    panel.saveHintFailed = true
  } finally {
    panel.submitting = false
  }
}

async function postAction(item: PendingItem): Promise<'done' | 'terminal'> {
  const response = await request(`${ENDPOINT}/${item.entry_id}/actions`, {
    method: 'POST',
    body: JSON.stringify({
      action: item.action,
      note: item.note,
      operator: item.operator,
      request_id: item.request_id,
    }),
  })
  if (!response.ok) {
    throw new Error(`服务返回 ${response.status}，提交未送达`)
  }
  const payload = await response.json()
  if (!payload.ok) {
    // 已被他人打款属于确定性结果，不再重试，提示并收尾。
    if (String(payload.message).includes('已打款')) {
      return 'terminal'
    }
    throw new Error(payload.message)
  }
  return 'done'
}

function finishSubmitted(item: PendingItem) {
  removeMirror(item.entry_id)
  writePendingQueue(readPendingQueue().filter((queued) => queued.request_id !== item.request_id))
  retryHint.value = ''
}

async function retryAll() {
  retryHint.value = ''
  let terminalCount = 0
  const queue = readPendingQueue()
  for (const item of queue) {
    try {
      const outcome = await postAction(item)
      if (outcome === 'done') {
        finishSubmitted(item)
      } else {
        // 已被他人打款：从队列移除，不覆盖打款记录。
        writePendingQueue(readPendingQueue().filter((queued) => queued.request_id !== item.request_id))
        terminalCount += 1
      }
    } catch (error) {
      retryHint.value = error instanceof Error ? error.message : '仍有提交未送达，请稍后重试'
    }
  }
  await Promise.all([reload(), reloadDrafts()])
  const remaining = readPendingQueue().length
  if (remaining === 0) {
    retryHint.value = terminalCount
      ? `重试完成，其中 ${terminalCount} 笔因报销单已打款未覆盖原记录`
      : '未送达的提交已全部处理完成'
  }
}

// 关闭/刷新标签页时来不及请求后端，先把当前内容落到本机，下次进入自动补发。
function flushMirrorOnUnload() {
  if (panel.open && (panel.action || panel.note)) {
    writeMirror(currentDraft())
  }
}

onMounted(async () => {
  pendingQueue.value = readPendingQueue()
  syncMirrorRef()
  window.addEventListener('beforeunload', flushMirrorOnUnload)
  await Promise.all([reload(), reconcileMirrors()])
  if (readPendingQueue().length) {
    retryHint.value = '检测到上次有未送达的提交，可直接重试'
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', flushMirrorOnUnload)
  if (saveTimer) {
    clearTimeout(saveTimer)
  }
  if (positionTimer) {
    clearTimeout(positionTimer)
  }
})
</script>
