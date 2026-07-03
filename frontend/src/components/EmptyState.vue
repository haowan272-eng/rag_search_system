<script setup lang="ts">
defineProps<{ title: string; description: string }>()
</script>
<template><div class="empty-state"><div class="empty-orbit"><span></span></div><h3>{{ title }}</h3><p>{{ description }}</p><slot /></div></template>
