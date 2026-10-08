<script setup lang="ts">
import AppIcon from "@/components/AppIcon.vue";

/**
 * 错误说明：失败必须在发生的位置说明原因与恢复路径。
 */
withDefaults(
  defineProps<{
    title?: string;
    message: string;
    code?: string;
    recovery?: string;
  }>(),
  { title: "这一步没有完成" },
);

defineEmits<{ (e: "retry"): void }>();
</script>

<template>
  <div class="note" role="alert">
    <span class="note__icon"><AppIcon name="alert" :size="17" /></span>
    <div class="note__body">
      <p class="note__title">{{ title }}</p>
      <p class="note__message">{{ message }}</p>
      <p v-if="recovery" class="note__recovery">{{ recovery }}</p>
      <p v-if="code" class="note__code mono">错误码 {{ code }}</p>
    </div>
    <el-button v-if="$attrs.onRetry" size="small" @click="$emit('retry')">重试</el-button>
  </div>
</template>

<style scoped>
.note {
  display: flex;
  align-items: flex-start;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  border: 1px solid var(--fail-line);
  border-radius: var(--radius);
  background: var(--fail-wash);
}

.note__icon {
  display: grid;
  place-items: center;
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-sm);
  background: var(--note-icon-face);
  color: var(--fail);
}

.note__body {
  flex: 1 1 auto;
  min-width: 0;
}

.note__title {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--fail);
}

.note__message {
  margin-top: 2px;
  font-size: var(--fs-sm);
  line-height: 1.65;
  color: var(--ink-1);
  word-break: break-word;
}

.note__recovery {
  margin-top: 4px;
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--ink-2);
}

.note__code {
  margin-top: 4px;
  font-size: 10.5px;
  color: var(--ink-3);
}
</style>
