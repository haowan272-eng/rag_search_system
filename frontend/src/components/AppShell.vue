<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { BookOpen, FileStack, LogOut, Menu, MessageSquareText, X } from '@lucide/vue'
import BrandMark from './BrandMark.vue'
import { useAuthStore } from '@/stores/auth'

const open = ref(false)
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const items = [
  { to: '/chat', label: '知识问答', caption: '检索与引用', icon: MessageSquareText },
  { to: '/knowledge', label: '知识空间', caption: '配置与成员', icon: BookOpen },
  { to: '/documents', label: '文档中心', caption: '上传与索引', icon: FileStack },
]

function active(path: string) {
  return route.path.startsWith(path)
}

function logout() {
  auth.logout()
  router.replace('/login')
}
</script>

<template>
  <div class="app-frame">
    <button class="mobile-menu icon-button" aria-label="打开导航" @click="open = true"><Menu :size="20" /></button>
    <div v-if="open" class="mobile-scrim" @click="open = false"></div>
    <aside class="sidebar" :class="{ open }">
      <div class="sidebar-head">
        <RouterLink to="/chat" class="brand"><BrandMark /><span>Atlas</span></RouterLink>
        <button class="mobile-close icon-button" aria-label="关闭导航" @click="open = false"><X :size="18" /></button>
      </div>
      <p class="eyebrow sidebar-eyebrow">WORKSPACE</p>
      <nav class="primary-nav" aria-label="主要导航">
        <RouterLink v-for="item in items" :key="item.to" :to="item.to" :class="{ active: active(item.to) }" @click="open = false">
          <component :is="item.icon" :size="19" />
          <span><strong>{{ item.label }}</strong><small>{{ item.caption }}</small></span>
        </RouterLink>
      </nav>
      <div class="sidebar-note">
        <span class="status-dot"></span>
        <div><strong>共享知识已连接</strong><small>回答将附带原文引用</small></div>
      </div>
      <div class="account-card">
        <div class="avatar">{{ auth.username.slice(0, 1).toUpperCase() }}</div>
        <div class="account-copy"><strong>{{ auth.username }}</strong><small>已通过 JWT 验证</small></div>
        <button class="icon-button" title="退出登录" @click="logout"><LogOut :size="17" /></button>
      </div>
    </aside>
    <main class="app-main"><RouterView /></main>
  </div>
</template>
