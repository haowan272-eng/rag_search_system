<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { CheckCircle2, CircleAlert, Clock3, File, FileImage, FileText, LoaderCircle, Search, Trash2, UploadCloud, X } from '@lucide/vue'
import { api, ApiError } from '@/api/http'
import EmptyState from '@/components/EmptyState.vue'
import type { DocumentItem, KnowledgeBase } from '@/types'

const route = useRoute()
const rows = ref<DocumentItem[]>([])
const knowledgeBases = ref<KnowledgeBase[]>([])
const initialKb = route.query.kb ? Number(route.query.kb) : null
const filterKb = ref<number | null>(initialKb)
const uploadKb = ref<number | null>(null)
const search = ref('')
const loading = ref(true)
const uploading = ref(false)
const uploadName = ref('')
const uploadError = ref('')
const dragging = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
let timer: number | undefined

const filtered = computed(() => rows.value.filter((item) => {
  const matchesSearch = item.file_name.toLowerCase().includes(search.value.toLowerCase())
  return matchesSearch && (filterKb.value === null || item.kb_id === filterKb.value)
}))
const writableKnowledgeBases = computed(() => knowledgeBases.value.filter((kb) => ['owner', 'admin', 'editor'].includes(kb.role || '')))
const processingCount = computed(() => rows.value.filter((item) => ['uploaded', 'processing'].includes(item.status)).length)

async function load() {
  try {
    const [documents, kbs] = await Promise.all([api<DocumentItem[]>('/document/list'), api<KnowledgeBase[]>('/kb')])
    rows.value = documents
    knowledgeBases.value = kbs
    if (uploadKb.value === null && initialKb && kbs.some((kb) => kb.id === initialKb && ['owner', 'admin', 'editor'].includes(kb.role || ''))) uploadKb.value = initialKb
  } finally { loading.value = false }
}

async function upload(file?: File) {
  if (!file || uploading.value) return
  uploadError.value = ''
  uploadName.value = file.name
  uploading.value = true
  const body = new FormData()
  body.append('file', file)
  if (uploadKb.value !== null) body.append('kb_id', String(uploadKb.value))
  try {
    await api('/document/upload', { method: 'POST', body })
    await load()
  } catch (reason) {
    uploadError.value = reason instanceof ApiError ? reason.message : '上传失败，请稍后重试。'
  } finally {
    uploading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function onDrop(event: DragEvent) {
  dragging.value = false
  upload(event.dataTransfer?.files[0])
}

async function remove(item: DocumentItem) {
  if (!confirm(`删除“${item.file_name}”及其全部索引数据？`)) return
  try {
    await api(`/document/${item.id}`, { method: 'DELETE' })
    rows.value = rows.value.filter((row) => row.id !== item.id)
  } catch (reason) { uploadError.value = reason instanceof ApiError ? reason.message : '删除失败。' }
}

function size(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function iconFor(item: DocumentItem) {
  if (item.content_type?.startsWith('image/')) return FileImage
  if (item.file_name.toLowerCase().endsWith('.pdf')) return FileText
  return File
}

function statusInfo(status: string) {
  if (status === 'indexed') return { label: '已完成索引', class: 'success', icon: CheckCircle2 }
  if (status === 'failed') return { label: '索引失败', class: 'danger', icon: CircleAlert }
  if (status === 'processing') return { label: '正在解析', class: 'working', icon: LoaderCircle }
  return { label: '等待处理', class: 'pending', icon: Clock3 }
}

onMounted(async () => {
  try { await load() } catch (reason) { uploadError.value = reason instanceof ApiError ? reason.message : '文档加载失败。' }
  timer = window.setInterval(() => { if (processingCount.value) load() }, 5000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page-shell">
    <header class="page-header"><div><p class="eyebrow">DOCUMENT PIPELINE</p><h1>文档中心</h1><p>上传多格式资料，跟踪异步解析、分块与向量索引状态。</p></div><button class="primary-button" @click="fileInput?.click()"><UploadCloud :size="17" />上传文档</button></header>
    <input ref="fileInput" class="visually-hidden" type="file" accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.webp,.pptx,.xlsx,.html,.csv,.json" @change="upload(($event.target as HTMLInputElement).files?.[0])" />
    <section class="upload-zone" :class="{ dragging, uploading }" @dragenter.prevent="dragging = true" @dragover.prevent @dragleave.prevent="dragging = false" @drop.prevent="onDrop" @click="!uploading && fileInput?.click()">
      <div class="upload-icon"><LoaderCircle v-if="uploading" :size="25" class="spin" /><UploadCloud v-else :size="25" /></div>
      <div><h2>{{ uploading ? `正在上传 ${uploadName}` : '拖放文档到这里' }}</h2><p>{{ uploading ? '上传完成后将进入 Redis 异步索引队列' : '或点击选择文件 · 支持 PDF、Word、图片、Markdown 等格式' }}</p></div>
      <label class="upload-target" @click.stop><span>上传到</span><select v-model="uploadKb"><option :value="null">个人空间</option><option v-for="kb in writableKnowledgeBases" :key="kb.id" :value="kb.id">{{ kb.name }}</option></select></label>
    </section>
    <p v-if="uploadError" class="inline-error closable">{{ uploadError }}<button @click="uploadError = ''"><X :size="15" /></button></p>
    <div class="toolbar document-toolbar"><div class="wide-search"><Search :size="17" /><input v-model="search" placeholder="搜索文件名" /></div><select v-model="filterKb"><option :value="null">全部可访问文档</option><option v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">{{ kb.name }}</option></select><span>{{ filtered.length }} 份文档</span></div>

    <div v-if="loading" class="table-skeleton"><div v-for="n in 5" :key="n"></div></div>
    <EmptyState v-else-if="!filtered.length" title="这里还没有文档" description="上传第一份资料，后台 Worker 会自动完成提取、Markdown 转换、分块和索引。" />
    <div v-else class="document-table-wrap">
      <table class="document-table"><thead><tr><th>文件</th><th>所属知识库</th><th>大小</th><th>索引状态</th><th>上传时间</th><th></th></tr></thead>
        <tbody><tr v-for="item in filtered" :key="item.id"><td><div class="file-cell"><div><component :is="iconFor(item)" :size="19" /></div><span><strong>{{ item.file_name }}</strong><small>{{ item.content_type || '未知类型' }}</small></span></div></td><td>{{ knowledgeBases.find((kb) => kb.id === item.kb_id)?.name || '个人空间' }}</td><td>{{ size(item.file_size) }}</td><td><span class="status-badge" :class="statusInfo(item.status).class"><component :is="statusInfo(item.status).icon" :size="14" :class="{ spin: item.status === 'processing' }" />{{ statusInfo(item.status).label }}</span></td><td>{{ new Date(item.created_at).toLocaleDateString('zh-CN') }}</td><td><button class="icon-button danger-action" title="删除文档" @click="remove(item)"><Trash2 :size="16" /></button></td></tr></tbody>
      </table>
    </div>
  </div>
</template>

