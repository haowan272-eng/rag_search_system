import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, postJson, tokenStore } from '@/api/http'
import type { TokenPair } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const username = ref(tokenStore.username() || '')
  const authenticated = computed(() => Boolean(tokenStore.access()))

  async function login(name: string, password: string) {
    const tokens = await postJson<TokenPair>('/login', { username: name, password })
    tokenStore.set(tokens, name)
    username.value = name
  }

  async function register(name: string, password: string) {
    await postJson('/register', { username: name, password })
    await login(name, password)
  }

  function logout() {
    tokenStore.clear()
    username.value = ''
  }

  async function verify() {
    if (!authenticated.value) return false
    try {
      await api('/profile')
      return true
    } catch {
      logout()
      return false
    }
  }

  return { username, authenticated, login, register, logout, verify }
})
