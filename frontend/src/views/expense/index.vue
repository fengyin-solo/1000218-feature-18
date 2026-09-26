<template>
  <section class="page" data-module="expense">
    <header class="page-head">
      <div>
        <h2>费用报销管理</h2>
        <p class="page-desc">维护报销单，保存未完成处理，正式提交后自动清除草稿并保留完整处理记录。</p>
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

    <div v-if="drafts.length" class="draft-banner">
      <div>
        <strong>有 {{ drafts.length }} 份未提交处理草稿</strong>
        <span>最近保存：{{ latestDraft?.updated_at || '本地待同步' }}</span>
      </div>
      <button class="btn" type="button" @click="restoreLatestDraft">恢复最近草稿</button>
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
          <th>处理状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span class="status-pill" :class="{ paid: row.status === '已打款' }">{{ row.status }}</span>
            <span v-if="draftMap.get(Number(row.id))" class="draft-pill">未提交草稿</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openEditor(row)">处理</button>
            <button class="link" type="button" @click="openHistory(row)">处理记录</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无费用报销数据，可先登记报销单</td>
        </tr>
      </tbody>
    </table>

    <div v-if="editorOpen" class="modal-mask" @click.self="closeEditor">
      <section class="modal-card" role="dialog" aria-modal="true" aria-label="报销处理">
        <header class="modal-head">
          <div>
            <h3>处理报销单 {{ currentEntry?.['报销单号'] }}</h3>
            <p>当前状态：{{ currentEntry?.status }}，版本：{{ currentEntry?.version }}</p>
          </div>
          <button class="modal-close" type="button" @click="closeEditor">×</button>
        </header>

        <div v-if="editorDraftDirty" class="sync-tip">草稿已保存在本机，网络恢复后将自动同步。</div>

        <label class="form-block">
          <span>处理选择 <em>*</em></span>
          <select v-model="editorForm.action" @change="persistDraftLocally">
            <option value="" disabled>请选择处理动作</option>
            <option v-for="action in availableActions" :key="action" :value="action">{{ action }}</option>
          </select>
        </label>
        <label class="form-block">
          <span>补充说明</span>
          <textarea
            v-model="editorForm.remark"
            rows="4"
            maxlength="500"
            placeholder="填写审批意见、驳回原因或打款说明；未提交前会持续保存"
            @input="scheduleDraftSave"
          ></textarea>
        </label>
        <label class="form-block">
          <span>当前所在位置</span>
          <input v-model="editorForm.location" placeholder="例如：列表第 2 条 / 审核意见区域" @input="scheduleDraftSave" />
        </label>

        <footer class="modal-foot">
          <button class="btn ghost danger" type="button" :disabled="submitting" @click="discardDraft">放弃草稿</button>
          <div class="modal-actions">
            <button class="btn" type="button" :disabled="submitting" @click="saveCurrentDraft(false)">保存草稿</button>
            <button class="btn primary" type="button" :disabled="submitting" @click="submitAction">
              {{ submitting ? '提交中…' : '正式提交' }}
            </button>
          </div>
        </footer>
      </section>
    </div>

    <div v-if="historyOpen" class="modal-mask" @click.self="historyOpen = false">
      <section class="modal-card history-card" role="dialog" aria-modal="true" aria-label="处理记录">
        <header class="modal-head">
          <div>
            <h3>处理记录 {{ currentEntry?.['报销单号'] }}</h3>
            <p>记录只追加、不覆盖；重试请求不会重复生成日志。</p>
          </div>
          <button class="modal-close" type="button" @click="historyOpen = false">×</button>
        </header>
        <table class="data-table history-table">
          <thead>
            <tr>
              <th>序号</th>
              <th>动作</th>
              <th>状态变化</th>
              <th>处理人</th>
              <th>补充说明</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in historyRows" :key="`${item.seq}-${item.request_id ?? 'base'}`">
              <td>{{ item.seq }}</td>
              <td>{{ item.action }}</td>
              <td>{{ item.from_status || '—' }} → {{ item.to_status }}</td>
              <td>{{ item.operator }}</td>
              <td>{{ item.remark || '—' }}</td>
              <td>{{ item.created_at }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条费用报销记录</span>
      <span v-if="infoMessage" class="info-text">{{ infoMessage }}</span>
      <span v-else-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Scalar = string | number | boolean | null
type Row = Record<string, Scalar>
type Draft = {
  entry_id: number
  operator: string
  action: string
  remark: string
  location: string
  entry_version: number
  updated_at: string
  dirty?: boolean
}
type HistoryRow = {
  seq: number
  request_id: string | null
  action: string
  from_status: string | null
  to_status: string
  remark: string
  operator: string
  created_at: string
}
type ActionResponse = {
  ok: boolean
  message: string
  entry?: Row | null
  conflict?: boolean
  duplicate?: boolean
  request_id?: string | null
}

const ENDPOINT = '/api/expense'
const DRAFT_STORAGE_KEY = 'expense:drafts:v1'
const REQUEST_STORAGE_KEY = 'expense:request-ids:v1'
const LOCATION_STORAGE_KEY = 'expense:last-location:v1'
const columns = ['报销单号', '报销人', '费用类别', '发生日期', '报销金额', '票据张数', '所属科目', '报销状态']
const statuses = ['待提交', '待审核', '已通过', '已驳回', '已打款']
const session = useSessionStore()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const infoMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const drafts = ref<Draft[]>([])
const historyRows = ref<HistoryRow[]>([])
const editorOpen = ref(false)
const historyOpen = ref(false)
const submitting = ref(false)
const currentEntry = ref<Row | null>(null)
const editorForm = ref({ action: '', remark: '', location: '' })
const editorDraftDirty = ref(false)
let draftSaveTimer: number | undefined

const stats = computed(() => [
  { label: '待审核报销', value: rows.value.filter((row) => row.status === '待审核').length },
  { label: '未提交草稿', value: drafts.value.length },
  { label: '已打款报销', value: rows.value.filter((row) => row.status === '已打款').length },
])
const draftMap = computed(() => new Map(drafts.value.map((draft) => [draft.entry_id, draft])))
const latestDraft = computed(() => drafts.value[0] ?? null)
const availableActions = computed(() => {
  const status = String(currentEntry.value?.status ?? '')
  if (status === '待提交') return ['提交报销']
  if (status === '待审核') return ['审核通过', '驳回报销']
  if (status === '已通过') return ['确认打款']
  return ['审核通过', '驳回报销']
})

function operatorHeaders(init: HeadersInit = {}): HeadersInit {
  return { ...init, 'X-Operator': encodeURIComponent(session.operator || '值班管理员') }
}

function readJsonStorage<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function writeJsonStorage(key: string, value: unknown) {
  window.localStorage.setItem(key, JSON.stringify(value))
}

function localDrafts(): Draft[] {
  return readJsonStorage<Draft[]>(DRAFT_STORAGE_KEY, []).filter((draft) => draft.operator === session.operator)
}

function saveLocalDrafts(nextDrafts: Draft[]) {
  const others = readJsonStorage<Draft[]>(DRAFT_STORAGE_KEY, []).filter((draft) => draft.operator !== session.operator)
  writeJsonStorage(DRAFT_STORAGE_KEY, [...others, ...nextDrafts])
}

function upsertLocalDraft(draft: Draft) {
  const nextDrafts = localDrafts().filter((item) => item.entry_id !== draft.entry_id)
  nextDrafts.unshift({ ...draft, dirty: true, updated_at: draft.updated_at || new Date().toISOString() })
  saveLocalDrafts(nextDrafts)
  mergeDrafts()
}

function removeLocalDraft(entryId: number) {
  saveLocalDrafts(localDrafts().filter((draft) => draft.entry_id !== entryId))
  mergeDrafts()
}

function rememberRequest(entryId: number, requestId: string) {
  const values = readJsonStorage<Record<string, string>>(REQUEST_STORAGE_KEY, {})
  values[String(entryId)] = requestId
  writeJsonStorage(REQUEST_STORAGE_KEY, values)
}

function takeRequestId(entryId: number): string {
  const values = readJsonStorage<Record<string, string>>(REQUEST_STORAGE_KEY, {})
  const existing = values[String(entryId)]
  if (existing) return existing
  const requestId = (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`)
  values[String(entryId)] = requestId
  writeJsonStorage(REQUEST_STORAGE_KEY, values)
  return requestId
}

function clearRequestId(entryId: number) {
  const values = readJsonStorage<Record<string, string>>(REQUEST_STORAGE_KEY, {})
  delete values[String(entryId)]
  writeJsonStorage(REQUEST_STORAGE_KEY, values)
}

function mergeDrafts(serverDrafts: Draft[] = []) {
  const local = localDrafts()
  const merged = new Map<number, Draft>()
  for (const draft of [...local, ...serverDrafts]) {
    const existing = merged.get(draft.entry_id)
    if (!existing || draft.updated_at > existing.updated_at) merged.set(draft.entry_id, draft)
  }
  drafts.value = [...merged.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
}

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

function persistLocation() {
  writeJsonStorage(LOCATION_STORAGE_KEY, {
    path: window.location.pathname,
    scrollY: Math.round(window.scrollY),
    saved_at: new Date().toISOString(),
  })
}

async function reloadDrafts() {
  try {
    const response = await request(`${ENDPOINT}/drafts`, { headers: operatorHeaders() })
    if (!response.ok) throw new Error('服务端草稿读取失败')
    const serverDrafts = (await response.json()) as Draft[]
    const rowMap = new Map(rows.value.map((row) => [Number(row.id), row]))
    const validIds = new Set(serverDrafts.map((draft) => draft.entry_id))
    const survivingLocal = localDrafts().filter((draft) => {
      const row = rowMap.get(draft.entry_id)
      if (!row) return true
      const status = String(row.status)
      return status === '待提交' || status === '待审核' || validIds.has(draft.entry_id)
    })
    if (survivingLocal.length !== localDrafts().length) saveLocalDrafts(survivingLocal)
    mergeDrafts(serverDrafts)
    return serverDrafts
  } catch (error) {
    mergeDrafts()
    throw error
  }
}

async function reload() {
  errorMessage.value = ''
  infoMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) throw new Error('报销单列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '费用报销列表读取失败'
  }
}

async function restoreRow(row: Row | null): Promise<Row | null> {
  if (!row) return null
  try {
    const response = await request(`${ENDPOINT}/${row.id}`, { headers: operatorHeaders() })
    if (!response.ok) return row
    return (await response.json()) as Row
  } catch {
    return row
  }
}

async function openEditor(row: Row, draft?: Draft) {
  errorMessage.value = ''
  infoMessage.value = ''
  currentEntry.value = await restoreRow(row)
  let activeDraft = draft ?? draftMap.value.get(Number(row.id))
  if (!activeDraft) {
    try {
      const response = await request(`${ENDPOINT}/${row.id}/draft`, { headers: operatorHeaders() })
      const payload = (await response.json()) as ActionResponse
      if (response.ok && payload.entry) activeDraft = payload.entry as Draft
    } catch {
      // 没有网络时继续使用本地草稿。
    }
  }
  editorForm.value = {
    action: activeDraft?.action ?? '',
    remark: activeDraft?.remark ?? '',
    location: activeDraft?.location ?? `列表中的「${String(currentEntry.value?.['报销单号'] ?? row['报销单号'])}」`,
  }
  editorDraftDirty.value = Boolean(activeDraft?.dirty)
  editorOpen.value = true
}

function closeEditor() {
  if (draftSaveTimer) window.clearTimeout(draftSaveTimer)
  editorOpen.value = false
  currentEntry.value = null
}

function persistDraftLocally() {
  if (!currentEntry.value) return
  const draft: Draft = {
    entry_id: Number(currentEntry.value.id),
    operator: session.operator || '值班管理员',
    action: editorForm.value.action,
    remark: editorForm.value.remark,
    location: editorForm.value.location,
    entry_version: Number(currentEntry.value.version ?? 1),
    updated_at: new Date().toISOString(),
  }
  upsertLocalDraft(draft)
  editorDraftDirty.value = true
}

function scheduleDraftSave() {
  persistDraftLocally()
  if (draftSaveTimer) window.clearTimeout(draftSaveTimer)
  draftSaveTimer = window.setTimeout(() => void saveCurrentDraft(true), 500)
}

async function saveCurrentDraft(silent: boolean) {
  if (!currentEntry.value) return
  if (!editorForm.value.action) {
    errorMessage.value = '请先选择处理动作，再保存草稿'
    return
  }
  persistDraftLocally()
  try {
    const response = await request(`${ENDPOINT}/${currentEntry.value.id}/draft`, {
      method: 'PUT',
      headers: operatorHeaders(),
      body: JSON.stringify({
        values: {
          action: editorForm.value.action,
          remark: editorForm.value.remark,
          location: editorForm.value.location,
        },
      }),
    })
    const payload = (await response.json()) as ActionResponse
    if (!response.ok || !payload.ok) throw new Error(payload.message || '草稿同步失败')
    if (payload.entry) {
      const syncedDraft = payload.entry as Draft
      const next = localDrafts().map((draft) =>
        draft.entry_id === syncedDraft.entry_id
          ? { ...syncedDraft, dirty: false }
          : draft,
      )
      saveLocalDrafts(next)
      mergeDrafts()
    }
    editorDraftDirty.value = false
    if (!silent) infoMessage.value = '草稿已保存，可随时离开后恢复'
  } catch (error) {
    editorDraftDirty.value = true
    if (!silent) errorMessage.value = error instanceof Error ? error.message : '草稿已保存在本机，稍后可重试同步'
  }
}

async function discardDraft() {
  if (!currentEntry.value) return
  const entryId = Number(currentEntry.value.id)
  try {
    await request(`${ENDPOINT}/${entryId}/draft`, { method: 'DELETE', headers: operatorHeaders() })
  } catch {
    // 本地仍会清理；下次联网后不再同步这份草稿。
  }
  removeLocalDraft(entryId)
  closeEditor()
  infoMessage.value = '草稿已放弃'
}

async function submitAction() {
  if (!currentEntry.value) return
  if (!editorForm.value.action) {
    errorMessage.value = '请选择处理动作'
    return
  }
  if (!availableActions.value.includes(editorForm.value.action)) {
    errorMessage.value = `当前状态「${currentEntry.value.status}」不能执行「${editorForm.value.action}」，请刷新后查看最新处理结果`
    return
  }

  submitting.value = true
  errorMessage.value = ''
  infoMessage.value = ''
  const entryId = Number(currentEntry.value.id)
  const requestId = takeRequestId(entryId)
  try {
    const response = await request(`${ENDPOINT}/${entryId}/actions`, {
      method: 'POST',
      headers: operatorHeaders({ 'X-Request-Id': requestId }),
      body: JSON.stringify({
        values: {
          action: editorForm.value.action,
          expected_version: currentEntry.value.version,
          request_id: requestId,
        },
        remark: editorForm.value.remark,
      }),
    })
    const payload = (await response.json()) as ActionResponse
    if (!response.ok || !payload.ok) throw new Error(payload.message || '费用报销动作未生效')
    removeLocalDraft(entryId)
    clearRequestId(entryId)
    closeEditor()
    await Promise.all([reload(), reloadDrafts().catch(() => undefined)])
    infoMessage.value = payload.duplicate
      ? '该请求此前已生效，本次为重试结果，未重复生成记录'
      : payload.message
  } catch (error) {
    persistDraftLocally()
    errorMessage.value = `${error instanceof Error ? error.message : '费用报销操作失败'}；草稿已保留，可稍后重试`
  } finally {
    submitting.value = false
  }
}

async function restoreLatestDraft() {
  const draft = latestDraft.value
  if (!draft) return
  const row = rows.value.find((item) => Number(item.id) === draft.entry_id)
  if (row) {
    await openEditor(row, draft)
    return
  }
  const fresh = await restoreRow({ id: draft.entry_id } as Row)
  if (fresh?.id) {
    rows.value.unshift(fresh)
    await openEditor(fresh, draft)
  }
}

async function openHistory(row: Row) {
  currentEntry.value = row
  historyRows.value = []
  historyOpen.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/history`, { headers: operatorHeaders() })
    if (!response.ok) throw new Error('处理记录读取失败')
    historyRows.value = (await response.json()) as HistoryRow[]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '处理记录读取失败'
  }
}

async function restoreLocation() {
  const location = readJsonStorage<{ path: string; scrollY: number } | null>(LOCATION_STORAGE_KEY, null)
  if (location?.path !== window.location.pathname) return
  window.requestAnimationFrame(() => window.scrollTo({ top: location.scrollY || 0 }))
}

async function init() {
  mergeDrafts()
  await Promise.all([reload(), reloadDrafts().catch(() => undefined)])
  void restoreLocation()
}

let scrollTimer: number | undefined
function handleScroll() {
  if (scrollTimer) window.clearTimeout(scrollTimer)
  scrollTimer = window.setTimeout(persistLocation, 200)
}

onMounted(() => {
  void init()
  window.addEventListener('scroll', handleScroll, { passive: true })
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', handleScroll)
  if (draftSaveTimer) window.clearTimeout(draftSaveTimer)
  if (scrollTimer) window.clearTimeout(scrollTimer)
})
</script>
