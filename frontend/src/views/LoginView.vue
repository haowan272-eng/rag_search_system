<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Eye, EyeOff, FileSearch, LockKeyhole, ShieldCheck } from '@lucide/vue'
import BrandMark from '@/components/BrandMark.vue'
import { ApiError } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const visible = ref(false)
const loading = ref(false)
const error = ref(route.query.expired ? '登录已过期，请重新验证身份。' : '')
const title = computed(() => mode.value === 'login' ? '欢迎回来' : '创建工作区账号')

async function submit() {
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和密码。'
    return
  }
  loading.value = true
  try {
    if (mode.value === 'login') await auth.login(username.value.trim(), password.value)
    else await auth.register(username.value.trim(), password.value)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/chat'
    await router.replace(redirect)
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '暂时无法连接服务，请检查后端是否启动。'
  } finally {
    loading.value = false
  }
}

function switchMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  error.value = ''
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-story">
      <div class="auth-grid"></div>
      <header class="auth-brand"><BrandMark /><span>Atlas</span></header>
      <div class="story-copy">
        <p class="eyebrow">PRIVATE RAG WORKSPACE</p>
        <h1>让每一个答案，<br />都能回到原文。</h1>
        <p>统一检索文字、图片与多格式文档。答案不是黑盒结论，而是一条可以核验的证据链。</p>
        <div class="story-features">
          <div><FileSearch :size="20" /><span><strong>多模态知识检索</strong><small>PDF、Word、图片统一入库</small></span></div>
          <div><ShieldCheck :size="20" /><span><strong>共享知识，私有对话</strong><small>语料协作，会话按用户隔离</small></span></div>
        </div>
      </div>
      <footer>POSTGRESQL · QDRANT · REDIS</footer>
    </section>

    <section class="auth-panel">
      <form class="auth-form" @submit.prevent="submit">
        <div class="auth-mobile-brand"><BrandMark /><span>Atlas</span></div>
        <p class="eyebrow">SECURE ACCESS</p>
        <h2>{{ title }}</h2>
        <p class="form-intro">{{ mode === 'login' ? '登录后继续访问你的知识库和私有对话。' : '账号将用于隔离你的问答记录与操作权限。' }}</p>

        <label><span>用户名</span><input v-model="username" autocomplete="username" placeholder="请输入用户名" autofocus /></label>
        <label><span>密码</span><div class="password-input"><LockKeyhole :size="17" /><input v-model="password" :type="visible ? 'text' : 'password'" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" placeholder="请输入密码" /><button type="button" :aria-label="visible ? '隐藏密码' : '显示密码'" @click="visible = !visible"><EyeOff v-if="visible" :size="17" /><Eye v-else :size="17" /></button></div></label>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button class="primary-button auth-submit" :disabled="loading">
          <span>{{ loading ? '正在验证…' : mode === 'login' ? '进入知识工作台' : '注册并进入' }}</span><ArrowRight v-if="!loading" :size="18" />
        </button>
        <p class="auth-switch">{{ mode === 'login' ? '还没有账号？' : '已经拥有账号？' }} <button type="button" @click="switchMode">{{ mode === 'login' ? '立即注册' : '返回登录' }}</button></p>
        <div class="security-hint"><ShieldCheck :size="15" />访问令牌仅保存在当前浏览器会话中</div>
      </form>
    </section>
  </main>
</template>
