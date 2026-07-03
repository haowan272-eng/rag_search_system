<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowUp, BookOpen, ChevronRight, FileText, LoaderCircle, MessageSquarePlus, PanelRightClose, PanelRightOpen, Search, Sparkles, Trash2 } from '@lucide/vue'
import { api, ApiError, postSse } from '@/api/http'
import AnswerContent from '@/components/AnswerContent.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { Citation, Conversation, KnowledgeBase, MemoryItem, Message, RagAnswer } from '@/types'

const route = useRoute()
const router = useRouter()
const conversations = ref<Conversation[]>([])
const knowledgeBases = ref<KnowledgeBase[]>([])
const messages = ref<Message[]>([])
const query = ref('')
const selectedKb = ref<number | null>(null)
const activeCitations = ref<Citation[]>([])
const focusedCitation = ref<number | null>(null)
const sending = ref(false)
const loadingMessages = ref(false)
const historySearch = ref('')
const evidenceOpen = ref(true)
const useMemory = ref(true)
const error = ref('')
const messageList = ref<HTMLElement | null>(null)

const conversationId = computed(() => {
  const raw = route.params.conversationId
  return raw ? Number(raw) : null
})
const activeConversation = computed(() => conversations.value.find((item) => item.id === conversationId.value))
const filteredConversations = computed(() => conversations.value.filter((item) => item.title.toLowerCase().includes(historySearch.value.toLowerCase())))
const canSend = computed(() => query.value.trim().length > 0 && !sending.value)

function parseCitations(raw?: string | null): Citation[] {
  if (!raw) return []
  try { return JSON.parse(raw) as Citation[] } catch { return [] }
}

function parseMemory(raw?: string | null): MemoryItem[] {
  if (!raw) return []
  try { return JSON.parse(raw) as MemoryItem[] } catch { return [] }
}

async function loadSidebar() {
  const [conversationRows, kbRows] = await Promise.all([
    api<Conversation[]>('/conversations'),
    api<KnowledgeBase[]>('/kb'),
  ])
  conversations.value = conversationRows
  knowledgeBases.value = kbRows
}

async function loadMessages(id: number | null) {
  error.value = ''
  activeCitations.value = []
  focusedCitation.value = null
  if (!id) { messages.value = []; return }
  loadingMessages.value = true
  try {
    const rows = await api<Message[]>(`/conversations/${id}/messages`)
    messages.value = rows.map((item) => ({
      ...item,
      citations: parseCitations(item.citations_json),
      memory_used: parseMemory(item.memory_json),
    }))
    const lastWithSources = [...messages.value].reverse().find((item) => item.citations?.length)
    activeCitations.value = lastWithSources?.citations || []
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '无法读取对话。'
  } finally {
    loadingMessages.value = false
    await scrollToBottom()
  }
}

async function scrollToBottom() {
  await nextTick()
  messageList.value?.scrollTo({ top: messageList.value.scrollHeight, behavior: 'smooth' })
}

function createMessageStreamer(message: Message) {
  let target = message.content || ''
  let frame: number | null = null
  let stopped = false
  const idleWaiters: Array<() => void> = []

  const resolveIdle = () => {
    if (frame !== null || message.content.length < target.length) return
    while (idleWaiters.length) idleWaiters.shift()?.()
  }

  const schedule = () => {
    if (stopped || frame !== null) return
    frame = window.requestAnimationFrame(tick)
  }

  const tick = () => {
    frame = null
    if (stopped) return
    const remaining = target.length - message.content.length
    if (remaining <= 0) {
      resolveIdle()
      return
    }
    const batchSize = remaining > 500 ? 4 : remaining > 180 ? 3 : remaining > 60 ? 2 : 1
    message.content += target.slice(message.content.length, message.content.length + batchSize)
    scrollToBottom()
    schedule()
  }

  return {
    append(text: string) {
      if (!text) return
      target += text
      schedule()
    },
    setFinal(text: string) {
      if (message.content.length > text.length || !text.startsWith(message.content)) {
        message.content = ''
      }
      target = text
      schedule()
    },
    waitUntilIdle() {
      if (frame === null && message.content.length >= target.length) return Promise.resolve()
      return new Promise<void>((resolve) => idleWaiters.push(resolve))
    },
    stop() {
      stopped = true
      if (frame !== null) window.cancelAnimationFrame(frame)
      frame = null
      target = message.content
      resolveIdle()
    },
  }
}

function newConversation() {
  messages.value = []
  activeCitations.value = []
  focusedCitation.value = null
  selectedKb.value = null
  router.push('/chat')
}

async function send() {
  const text = query.value.trim()
  if (!text || sending.value) return
  query.value = ''
  error.value = ''
  messages.value.push({ role: 'user', content: text })
  const pending: Message = { role: 'assistant', content: '', pending: true }
  messages.value.push(pending)
  const streamer = createMessageStreamer(pending)
  sending.value = true
  await scrollToBottom()
  try {
    const streamState: { final?: RagAnswer } = {}
    await postSse('/embedding/rag/answer/stream', {
      query: text,
      kb_id: selectedKb.value,
      conversation_id: conversationId.value,
      top_k: 5,
      bm25_weight: 0.4,
      use_memory: useMemory.value,
    }, (event, data) => {
      if (event === 'token') {
        streamer.append(String((data as { delta?: string }).delta || ''))
      } else if (event === 'final') {
        const answer = data as RagAnswer
        streamState.final = answer
        streamer.setFinal(answer.answer)
        pending.citations = answer.citations
        pending.memory_used = answer.memory_used
        pending.degraded = answer.degraded
        pending.context_compacted = answer.context_compacted
        activeCitations.value = answer.citations
        focusedCitation.value = answer.citations[0]?.source_id || null
      } else if (event === 'error') {
        throw new ApiError(
          Number((data as { status_code?: number }).status_code || 500),
          String((data as { detail?: string }).detail || '回答生成失败'),
        )
      }
    })
    const finalAnswer = streamState.final
    await streamer.waitUntilIdle()
    pending.pending = false
    if (!finalAnswer) throw new ApiError(502, '流式回答未返回最终结果')
    if (finalAnswer.conversation_id && finalAnswer.conversation_id !== conversationId.value) {
      await loadSidebar()
      await router.replace(`/chat/${finalAnswer.conversation_id}`)
    }
  } catch (reason) {
    streamer.stop()
    pending.pending = false
    pending.error = true
    pending.content = reason instanceof ApiError ? reason.message : '回答生成失败，请稍后重试。'
  } finally {
    sending.value = false
    await scrollToBottom()
  }
}

function useCitation(citations: Citation[] | undefined, id: number) {
  activeCitations.value = citations || []
  focusedCitation.value = id
  evidenceOpen.value = true
  nextTick(() => document.getElementById(`citation-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }))
}

async function removeConversation(item: Conversation) {
  if (!confirm(`删除对话“${item.title}”？此操作不可撤销。`)) return
  await api(`/conversations/${item.id}`, { method: 'DELETE' })
  conversations.value = conversations.value.filter((row) => row.id !== item.id)
  if (conversationId.value === item.id) newConversation()
}

function onComposerKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}

onMounted(async () => {
  try {
    await loadSidebar()
    await loadMessages(conversationId.value)
    if (activeConversation.value?.kb_id) selectedKb.value = activeConversation.value.kb_id
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '工作区加载失败。'
  }
})

watch(conversationId, async (id, old) => {
  if (id === old) return
  await loadMessages(id)
  selectedKb.value = activeConversation.value?.kb_id || null
})
</script>

<template>
  <div class="chat-layout" :class="{ 'evidence-closed': !evidenceOpen }">
    <aside class="history-panel">
      <div class="panel-heading"><div><p class="eyebrow">PRIVATE THREADS</p><h2>我的对话</h2></div><button class="icon-button elevated" title="新建对话" @click="newConversation"><MessageSquarePlus :size="18" /></button></div>
      <div class="mini-search"><Search :size="15" /><input v-model="historySearch" placeholder="搜索对话" /></div>
      <div class="conversation-list">
        <button v-for="item in filteredConversations" :key="item.id" class="conversation-row" :class="{ active: item.id === conversationId }" @click="router.push(`/chat/${item.id}`)">
          <span><strong>{{ item.title }}</strong><small>{{ new Date(item.updated_at).toLocaleDateString('zh-CN') }}</small></span>
          <Trash2 class="row-delete" :size="15" @click.stop="removeConversation(item)" />
        </button>
        <p v-if="!filteredConversations.length" class="list-empty">还没有历史对话</p>
      </div>
      <div class="scope-hint"><BookOpen :size="15" /><span>文档共享检索<br /><small>对话仅你可见</small></span></div>
    </aside>

    <section class="chat-workspace">
      <header class="chat-header">
        <div><p class="eyebrow">GROUNDED ANSWERS</p><h1>{{ activeConversation?.title || '新的知识问答' }}</h1></div>
        <div class="header-actions">
          <label class="kb-select"><span>检索范围</span><select v-model="selectedKb" :disabled="Boolean(activeConversation?.kb_id)"><option :value="null">个人空间</option><option v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">{{ kb.name }}</option></select></label>
          <label class="memory-toggle"><input v-model="useMemory" type="checkbox" /><span>使用私人记忆</span></label>
          <button class="icon-button" :title="evidenceOpen ? '收起证据' : '展开证据'" @click="evidenceOpen = !evidenceOpen"><PanelRightClose v-if="evidenceOpen" :size="19" /><PanelRightOpen v-else :size="19" /></button>
        </div>
      </header>

      <div ref="messageList" class="message-list">
        <div v-if="loadingMessages" class="center-loader"><LoaderCircle :size="22" class="spin" />正在读取对话</div>
        <EmptyState v-else-if="!messages.length" title="从一个值得追问的问题开始" description="系统会先检索共享知识，再基于原文生成回答。每个结论都可以追溯到文件、页码与片段。">
          <div class="prompt-suggestions">
            <button @click="query = '总结这个知识库的核心内容'">总结知识库的核心内容 <ChevronRight :size="15" /></button>
            <button @click="query = '这些文档中有哪些关键规则？'">提取文档中的关键规则 <ChevronRight :size="15" /></button>
          </div>
        </EmptyState>
        <template v-else>
          <article v-for="(message, index) in messages" :key="message.id || index" class="message" :class="message.role">
            <div v-if="message.role === 'assistant'" class="assistant-mark"><Sparkles :size="16" /></div>
            <div class="message-body">
              <p class="message-author">{{ message.role === 'user' ? '你' : 'Atlas' }}</p>
              <div v-if="message.pending && !message.content" class="thinking"><span></span><span></span><span></span><em>正在检索并组织证据</em></div>
              <p v-else-if="message.role === 'user'" class="user-text">{{ message.content }}</p>
              <AnswerContent v-else :content="message.content" :class="{ 'error-answer': message.error, 'streaming-answer': message.pending }" @citation="(id) => useCitation(message.citations, id)" />
              <div v-if="message.role === 'assistant' && message.pending && message.content" class="thinking streaming"><span></span><span></span><span></span><em>正在生成回答</em></div>
              <div v-if="message.role === 'assistant' && !message.pending" class="answer-status">
                <span v-if="message.memory_used?.length">使用 {{ message.memory_used.length }} 条私人记忆</span>
                <span v-if="message.context_compacted">已压缩较早对话上下文</span>
                <span v-if="message.degraded" class="degraded-badge">模型降级：已展示检索原文</span>
              </div>
              <button v-if="message.citations?.length" class="sources-link" @click="activeCitations = message.citations; evidenceOpen = true"><FileText :size="14" />{{ message.citations.length }} 条引用来源</button>
            </div>
          </article>
        </template>
        <p v-if="error" class="inline-error">{{ error }}</p>
      </div>

      <footer class="composer-wrap">
        <div class="composer">
          <textarea v-model="query" rows="1" maxlength="2000" placeholder="向共享知识库提问…" @keydown="onComposerKeydown"></textarea>
          <button class="send-button" :disabled="!canSend" aria-label="发送问题" @click="send"><LoaderCircle v-if="sending" :size="18" class="spin" /><ArrowUp v-else :size="19" /></button>
        </div>
        <p>Enter 发送 · Shift + Enter 换行 · 回答可能有误，请核验引用原文</p>
      </footer>
    </section>

    <aside class="evidence-panel">
      <div class="evidence-head"><div><p class="eyebrow">EVIDENCE</p><h2>引用证据</h2></div><span>{{ activeCitations.length }}</span></div>
      <div v-if="activeCitations.length" class="evidence-list">
        <article v-for="citation in activeCitations" :id="`citation-${citation.source_id}`" :key="citation.source_id" class="evidence-card" :class="{ focused: citation.source_id === focusedCitation }">
          <div class="evidence-meta"><span>[{{ citation.source_id }}]</span><small>重排分 {{ citation.score.toFixed(2) }}</small></div>
          <h3>{{ citation.filename }}</h3>
          <p class="evidence-location"><span v-if="citation.page_start">第 {{ citation.page_start }} 页</span><span v-if="citation.heading_path">{{ citation.heading_path }}</span><span v-if="citation.source_type">{{ citation.source_type.toUpperCase() }}</span></p>
          <blockquote>{{ citation.quote }}</blockquote>
        </article>
      </div>
      <div v-else class="evidence-empty"><div><FileText :size="22" /></div><h3>证据将在这里出现</h3><p>生成回答后，点击正文中的引用编号查看原文片段。</p></div>
    </aside>
  </div>
</template>

