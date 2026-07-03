<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { BookOpen, Boxes, Plus, Search, Settings2, Trash2, UserPlus, Users, X } from '@lucide/vue'
import { api, ApiError, postJson } from '@/api/http'
import EmptyState from '@/components/EmptyState.vue'
import type { KnowledgeBase, KnowledgeBaseMember } from '@/types'

const rows = ref<KnowledgeBase[]>([])
const members = ref<KnowledgeBaseMember[]>([])
const selectedKb = ref<KnowledgeBase | null>(null)
const search = ref('')
const loading = ref(true)
const showCreate = ref(false)
const memberLoading = ref(false)
const saving = ref(false)
const memberSaving = ref(false)
const error = ref('')
const memberError = ref('')
const form = ref({ name: '', description: '', chunkSize: 500, overlap: 50 })
const memberForm = ref({ username: '', role: 'viewer' as KnowledgeBaseMember['role'] })
const filtered = computed(() => rows.value.filter((item) => `${item.name} ${item.description || ''}`.toLowerCase().includes(search.value.toLowerCase())))
const canManageMembers = computed(() => ['owner', 'admin'].includes(selectedKb.value?.role || ''))

async function load() {
  loading.value = true
  try { rows.value = await api<KnowledgeBase[]>('/kb') }
  catch (reason) { error.value = reason instanceof ApiError ? reason.message : '知识库加载失败。' }
  finally { loading.value = false }
}

async function create() {
  if (!form.value.name.trim()) return
  saving.value = true
  error.value = ''
  try {
    const created = await postJson<KnowledgeBase>('/kb', {
      name: form.value.name.trim(),
      description: form.value.description.trim() || null,
      chunk_config: JSON.stringify({ chunk_size: form.value.chunkSize, chunk_overlap: form.value.overlap }),
    })
    rows.value.unshift(created)
    showCreate.value = false
    form.value = { name: '', description: '', chunkSize: 500, overlap: 50 }
  } catch (reason) { error.value = reason instanceof ApiError ? reason.message : '创建失败。' }
  finally { saving.value = false }
}

function roleName(role: KnowledgeBase['role'] | KnowledgeBaseMember['role']) {
  return ({ owner: '所有者', admin: '管理员', editor: '编辑者', viewer: '查看者' } as Record<string, string>)[role || ''] || '共享可见'
}

async function openMembers(kb: KnowledgeBase) {
  selectedKb.value = kb
  memberError.value = ''
  memberForm.value = { username: '', role: 'viewer' }
  await loadMembers(kb.id)
}

async function loadMembers(kbId: number) {
  memberLoading.value = true
  try { members.value = await api<KnowledgeBaseMember[]>(`/kb/${kbId}/members`) }
  catch (reason) { memberError.value = reason instanceof ApiError ? reason.message : '成员加载失败。' }
  finally { memberLoading.value = false }
}

async function addMember() {
  if (!selectedKb.value || !memberForm.value.username.trim() || memberSaving.value) return
  memberSaving.value = true
  memberError.value = ''
  try {
    const created = await postJson<KnowledgeBaseMember>(`/kb/${selectedKb.value.id}/members`, {
      username: memberForm.value.username.trim(),
      role: memberForm.value.role,
    })
    members.value.push(created)
    memberForm.value = { username: '', role: 'viewer' }
    selectedKb.value.member_count += 1
  } catch (reason) { memberError.value = reason instanceof ApiError ? reason.message : '添加成员失败。' }
  finally { memberSaving.value = false }
}

async function updateMemberRole(member: KnowledgeBaseMember, role: KnowledgeBaseMember['role']) {
  if (!selectedKb.value || member.role === role || member.role === 'owner') return
  memberError.value = ''
  try {
    const updated = await api<KnowledgeBaseMember>(`/kb/${selectedKb.value.id}/members/${member.user_id}`, {
      method: 'PUT',
      body: JSON.stringify({ role }),
    })
    member.role = updated.role
  } catch (reason) { memberError.value = reason instanceof ApiError ? reason.message : '更新角色失败。' }
}

async function removeMember(member: KnowledgeBaseMember) {
  if (!selectedKb.value || member.role === 'owner') return
  if (!confirm(`移除成员“${member.username}”？`)) return
  memberError.value = ''
  try {
    await api(`/kb/${selectedKb.value.id}/members/${member.user_id}`, { method: 'DELETE' })
    members.value = members.value.filter((item) => item.user_id !== member.user_id)
    selectedKb.value.member_count = Math.max(0, selectedKb.value.member_count - 1)
  } catch (reason) { memberError.value = reason instanceof ApiError ? reason.message : '移除成员失败。' }
}

onMounted(load)
</script>

<template>
  <div class="page-shell">
    <header class="page-header">
      <div><p class="eyebrow">KNOWLEDGE SPACES</p><h1>知识空间</h1><p>组织共享语料、分块策略与协作权限。</p></div>
      <button class="primary-button" @click="showCreate = true"><Plus :size="17" />新建知识库</button>
    </header>
    <div class="toolbar"><div class="wide-search"><Search :size="17" /><input v-model="search" placeholder="搜索知识库名称或描述" /></div><span>{{ rows.length }} 个空间</span></div>
    <p v-if="error" class="inline-error">{{ error }}</p>
    <div v-if="loading" class="skeleton-grid"><div v-for="n in 3" :key="n" class="skeleton-card"></div></div>
    <EmptyState v-else-if="!filtered.length" title="创建第一个知识空间" description="将同一业务主题下的资料归为一个知识库，便于控制检索范围和分块参数。"><button class="secondary-button" @click="showCreate = true"><Plus :size="16" />新建知识库</button></EmptyState>
    <section v-else class="kb-grid">
      <article v-for="kb in filtered" :key="kb.id" class="kb-card">
        <div class="kb-card-top"><div class="kb-icon"><BookOpen :size="21" /></div><span class="role-pill">{{ roleName(kb.role) }}</span></div>
        <h2>{{ kb.name }}</h2><p>{{ kb.description || '尚未添加知识库说明。' }}</p>
        <div class="kb-stats"><button class="member-stat" @click="openMembers(kb)"><Users :size="15" />{{ kb.member_count }} 位成员</button><span><Boxes :size="15" />BGE 中文向量</span></div>
        <div class="kb-card-foot"><small>更新于 {{ new Date(kb.updated_at).toLocaleDateString('zh-CN') }}</small><RouterLink :to="`/documents?kb=${kb.id}`">查看文档 <Settings2 :size="15" /></RouterLink></div>
      </article>
    </section>

    <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
      <form class="modal-card" @submit.prevent="create">
        <div class="modal-head"><div><p class="eyebrow">NEW SPACE</p><h2>新建知识库</h2></div><button type="button" class="icon-button" @click="showCreate = false"><X :size="18" /></button></div>
        <label><span>知识库名称</span><input v-model="form.name" maxlength="255" placeholder="例如：产品与售后规范" autofocus /></label>
        <label><span>描述</span><textarea v-model="form.description" rows="3" maxlength="2000" placeholder="说明收录哪些资料、服务什么问题"></textarea></label>
        <div class="form-grid"><label><span>分块长度</span><input v-model.number="form.chunkSize" type="number" min="100" max="2000" /></label><label><span>重叠长度</span><input v-model.number="form.overlap" type="number" min="0" max="500" /></label></div>
        <div class="config-note"><Settings2 :size="17" /><span>默认使用 Markdown 结构感知分块与 BAAI/bge-large-zh-v1.5 向量模型。</span></div>
        <div class="modal-actions"><button type="button" class="ghost-button" @click="showCreate = false">取消</button><button class="primary-button" :disabled="saving">{{ saving ? '正在创建...' : '创建知识库' }}</button></div>
      </form>
    </div>

    <div v-if="selectedKb" class="modal-backdrop" @click.self="selectedKb = null">
      <section class="modal-card member-modal">
        <div class="modal-head"><div><p class="eyebrow">MEMBERS</p><h2>{{ selectedKb.name }}</h2></div><button type="button" class="icon-button" @click="selectedKb = null"><X :size="18" /></button></div>
        <p v-if="memberError" class="inline-error">{{ memberError }}</p>
        <form v-if="canManageMembers" class="member-add" @submit.prevent="addMember">
          <input v-model="memberForm.username" placeholder="输入用户名" />
          <select v-model="memberForm.role"><option value="viewer">查看者</option><option value="editor">编辑者</option><option value="admin">管理员</option></select>
          <button class="primary-button" :disabled="memberSaving"><UserPlus :size="16" />添加</button>
        </form>
        <div v-if="memberLoading" class="center-loader"><Users :size="18" />正在加载成员</div>
        <div v-else class="member-list">
          <article v-for="member in members" :key="member.user_id" class="member-row">
            <div class="avatar">{{ member.username.slice(0, 1).toUpperCase() }}</div>
            <div class="member-copy"><strong>{{ member.username }}</strong><small>加入于 {{ new Date(member.created_at).toLocaleDateString('zh-CN') }}</small></div>
            <select :value="member.role" :disabled="!canManageMembers || member.role === 'owner'" @change="updateMemberRole(member, ($event.target as HTMLSelectElement).value as KnowledgeBaseMember['role'])">
              <option value="owner" disabled>所有者</option><option value="admin">管理员</option><option value="editor">编辑者</option><option value="viewer">查看者</option>
            </select>
            <button class="icon-button danger-action" :disabled="!canManageMembers || member.role === 'owner'" title="移除成员" @click="removeMember(member)"><Trash2 :size="16" /></button>
          </article>
        </div>
      </section>
    </div>
  </div>
</template>
