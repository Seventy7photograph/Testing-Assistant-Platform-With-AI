<script setup lang="ts">
import { useRouter } from "vue-router";

import AppIcon from "@/components/AppIcon.vue";
import SectionCard from "@/components/SectionCard.vue";

const router = useRouter();
</script>

<template>
  <div class="nf">
    <SectionCard>
      <div class="nf__inner">
        <span class="nf__glyph" aria-hidden="true">404</span>
        <h2 class="nf__title">页面不存在</h2>
        <p class="nf__text">返回总览或使用快速跳转。</p>
        <div class="nf__actions">
          <el-button type="primary" @click="router.push('/')">
            <AppIcon name="gauge" :size="15" /> 回到总览
          </el-button>
          <el-button @click="router.back()">返回上一页</el-button>
        </div>
      </div>
    </SectionCard>
  </div>
</template>

<style scoped>
.nf {
  max-width: 640px;
  margin: var(--s7) auto 0;
}

.nf__inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s2);
  padding: var(--s7) var(--s5);
  text-align: center;
}

.nf__glyph {
  font-family: var(--font-data);
  font-size: 56px;
  font-weight: 500;
  letter-spacing: -0.04em;
  color: var(--glacier-tint);
}

.nf__title {
  font-size: var(--fs-lg);
  font-weight: 600;
  letter-spacing: -0.015em;
}

.nf__text {
  max-width: 52ch;
  font-size: var(--fs-sm);
  line-height: 1.72;
  color: var(--ink-2);
}

.nf__actions {
  display: flex;
  gap: var(--s2);
  margin-top: var(--s3);
}
</style>
