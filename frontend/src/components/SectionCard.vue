<script setup lang="ts">
import AppIcon from "@/components/AppIcon.vue";

/** 冰面卡片：标题 + 可选说明 + 操作区 + 内容。 */
withDefaults(
  defineProps<{
    title?: string;
    sub?: string;
    icon?: string;
    /** 内容区去掉内边距（表格类内容自己管间距） */
    flush?: boolean;
    sunk?: boolean;
  }>(),
  { flush: false, sunk: false },
);
</script>

<template>
  <section class="card" :class="{ 'card--sunk': sunk }">
    <header v-if="title || $slots.head || $slots.actions" class="card__head">
      <div class="card__id">
        <span v-if="icon" class="card__icon"><AppIcon :name="icon" :size="16" /></span>
        <div>
          <p v-if="title" class="card__title">{{ title }}</p>
          <p v-if="sub" class="card__sub">{{ sub }}</p>
        </div>
        <slot name="head" />
      </div>
      <div v-if="$slots.actions" class="card__actions"><slot name="actions" /></div>
    </header>
    <div class="card__body" :class="{ 'card__body--flush': flush }">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.card__id {
  display: flex;
  align-items: center;
  gap: var(--s3);
  min-width: 0;
}

.card__icon {
  display: grid;
  place-items: center;
  flex: none;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: var(--glacier-wash);
  color: var(--glacier-deep);
}

.card__actions {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex: none;
}

.card__body--flush {
  padding: 0;
}
</style>
