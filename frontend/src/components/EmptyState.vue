<script setup lang="ts">
import AppIcon from "@/components/AppIcon.vue";

/**
 * 空状态：解释"这里为什么是空的" + 一个主操作。
 * 不允许只写一句「暂无数据」。
 */
withDefaults(
  defineProps<{
    icon?: string;
    title: string;
    reason?: string;
    actionLabel?: string;
    secondaryLabel?: string;
  }>(),
  { icon: "layers" },
);

defineEmits<{ (e: "action"): void; (e: "secondary"): void }>();
</script>

<template>
  <div class="empty">
    <span class="empty__mark"><AppIcon :name="icon" :size="22" /></span>
    <p class="empty__title">{{ title }}</p>
    <p v-if="reason" class="empty__reason" :title="reason">{{ reason }}</p>
    <div v-if="actionLabel || secondaryLabel" class="empty__actions">
      <el-button v-if="actionLabel" type="primary" @click="$emit('action')">
        {{ actionLabel }}
      </el-button>
      <el-button v-if="secondaryLabel" @click="$emit('secondary')">
        {{ secondaryLabel }}
      </el-button>
    </div>
    <div v-if="$slots.default" class="empty__extra"><slot /></div>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: var(--s6) var(--s5);
  text-align: center;
}

.empty__mark {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  margin-bottom: var(--s2);
  border-radius: var(--radius);
  border: 1px solid var(--ice-3);
  background: var(--ice-2);
  color: var(--ink-3);
}

.empty__title {
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--ink-1);
}

.empty__reason {
  display: -webkit-box;
  max-width: 42ch;
  font-size: var(--fs-xs);
  line-height: 1.55;
  color: var(--ink-3);
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.empty__actions {
  display: flex;
  gap: var(--s2);
  margin-top: var(--s2);
}

.empty__extra {
  margin-top: var(--s3);
  width: 100%;
}
</style>
