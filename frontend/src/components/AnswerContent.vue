<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ content: string }>()
const emit = defineEmits<{ citation: [id: number] }>()

const segments = computed(() => {
  const parts: Array<{ type: 'text' | 'citation'; value: string; id?: number }> = []
  const regex = /\[(\d+)\]/g
  let cursor = 0
  let match: RegExpExecArray | null
  while ((match = regex.exec(props.content))) {
    if (match.index > cursor) parts.push({ type: 'text', value: props.content.slice(cursor, match.index) })
    parts.push({ type: 'citation', value: match[0], id: Number(match[1]) })
    cursor = regex.lastIndex
  }
  if (cursor < props.content.length) parts.push({ type: 'text', value: props.content.slice(cursor) })
  return parts
})
</script>

<template>
  <p class="answer-text">
    <template v-for="(part, index) in segments" :key="index">
      <span v-if="part.type === 'text'">{{ part.value }}</span>
      <button v-else class="citation-chip" :aria-label="`查看引用 ${part.id}`" @click="emit('citation', part.id!)">{{ part.value }}</button>
    </template>
  </p>
</template>
