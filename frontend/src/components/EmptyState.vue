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
    reason: string;
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
    <p class="empty__reason">{{ reason }}</p>
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
  gap: var(--s2);
  padding: var(--s7) var(--s5);
  text-align: center;
}

.empty__mark {
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  margin-bottom: var(--s2);
  border-radius: 14px;
  border: 1px dashed var(--ice-4);
  background: var(--ice-1);
  color: var(--ink-3);
}

.empty__title {
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--ink-1);
}

.empty__reason {
  max-width: 46ch;
  font-size: var(--fs-sm);
  line-height: 1.7;
  color: var(--ink-3);
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
