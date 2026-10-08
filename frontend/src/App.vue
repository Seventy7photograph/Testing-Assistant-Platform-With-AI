<script setup lang="ts">
import { onMounted } from "vue";

import AppShell from "@/components/AppShell.vue";
import { useHealthStore } from "@/stores/health";

const health = useHealthStore();

onMounted(() => {
  void health.load();
  void health.loadLlmConfig();
});
</script>

<template>
  <AppShell />
</template>
