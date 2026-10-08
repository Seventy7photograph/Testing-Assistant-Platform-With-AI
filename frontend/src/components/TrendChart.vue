<script setup lang="ts">
import { computed } from "vue";

import type { TrendPoint } from "@/api";

/**
 * 趋势刻度：只画最近若干轮，判读线跟随配置的阈值。
 * 纯 SVG，无图表库；点悬停给出完整读数。
 */
const props = withDefaults(
  defineProps<{
    points: TrendPoint[];
    passLine?: number;
    height?: number;
  }>(),
  { passLine: 0.95, height: 210 },
);

const W = 720;
const PAD = { top: 18, right: 18, bottom: 30, left: 42 };

const innerW = W - PAD.left - PAD.right;
const innerH = computed(() => props.height - PAD.top - PAD.bottom);

const domain = computed(() => {
  const rates = props.points.map((p) => p.pass_rate);
  const low = Math.min(...rates, props.passLine, 0.9);
  const high = Math.max(...rates, props.passLine, 0.92);
  return { min: Math.max(0, low - 0.03), max: Math.min(1, high + 0.02) };
});

function xOf(index: number): number {
  const total = props.points.length;
  if (total <= 1) return PAD.left + innerW / 2;
  return PAD.left + (index / (total - 1)) * innerW;
}

function yOf(rate: number): number {
  const { min, max } = domain.value;
  const span = max - min || 1;
  return PAD.top + innerH.value - ((rate - min) / span) * innerH.value;
}

const linePath = computed(() =>
  props.points.map((p, i) => `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)} ${yOf(p.pass_rate).toFixed(1)}`).join(" "),
);

const areaPath = computed(() => {
  if (!props.points.length) return "";
  const base = PAD.top + innerH.value;
  return `${linePath.value} L${xOf(props.points.length - 1).toFixed(1)} ${base} L${xOf(0).toFixed(1)} ${base} Z`;
});

const passLineY = computed(() => yOf(props.passLine));

const ticks = computed(() => {
  const { min, max } = domain.value;
  return [max, (max + min) / 2, min].map((value) => ({ value, y: yOf(value) }));
});
</script>

<template>
  <div class="chart">
    <svg :viewBox="`0 0 ${W} ${height}`" class="chart__svg" role="img" aria-label="通过率趋势">
      <defs>
        <linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--glacier)" stop-opacity="0.22" />
          <stop offset="100%" stop-color="var(--glacier)" stop-opacity="0" />
        </linearGradient>
      </defs>

      <g v-for="tick in ticks" :key="tick.value">
        <line
          :x1="PAD.left"
          :x2="W - PAD.right"
          :y1="tick.y"
          :y2="tick.y"
          stroke="var(--ice-3)"
          stroke-width="1"
        />
        <text :x="PAD.left - 8" :y="tick.y + 4" text-anchor="end" class="chart__tick">
          {{ (tick.value * 100).toFixed(0) }}%
        </text>
      </g>

      <line
        :x1="PAD.left"
        :x2="W - PAD.right"
        :y1="passLineY"
        :y2="passLineY"
        stroke="var(--glacier)"
        stroke-width="1"
        stroke-dasharray="3 4"
        opacity="0.65"
      />
      <text :x="W - PAD.right" :y="passLineY - 6" text-anchor="end" class="chart__tick chart__tick--accent">
        判读线 {{ (passLine * 100).toFixed(0) }}%
      </text>

      <path v-if="points.length" :d="areaPath" fill="url(#trend-fill)" />
      <path
        v-if="points.length"
        :d="linePath"
        fill="none"
        stroke="var(--glacier)"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
      />

      <g v-for="(point, index) in points" :key="point.id">
        <circle
          :cx="xOf(index)"
          :cy="yOf(point.pass_rate)"
          r="3.6"
          fill="var(--ice-0)"
          stroke="var(--glacier)"
          stroke-width="1.8"
        >
          <title>
            {{ point.label }} · {{ (point.pass_rate * 100).toFixed(1) }}% · 用例 {{ point.total }} · 判定
            {{ point.verdict_label }}
          </title>
        </circle>
      </g>
    </svg>

    <ul class="chart__axis">
      <li v-for="(point, index) in points" :key="point.id">
        <span v-if="index === 0 || index === points.length - 1 || points.length <= 8" class="chart__axisLabel mono">
          {{ point.label }}
        </span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.chart {
  position: relative;
  width: 100%;
}

.chart__svg {
  display: block;
  width: 100%;
  height: auto;
}

.chart__tick {
  font-family: var(--font-data);
  font-size: 10px;
  fill: var(--ink-3);
}

.chart__tick--accent {
  fill: var(--glacier-deep);
}

.chart__axis {
  position: absolute;
  left: 0;
  right: 0;
  bottom: -4px;
  display: flex;
  justify-content: space-between;
  list-style: none;
  margin: 0;
  padding: 0 var(--s4);
  pointer-events: none;
}

.chart__axis li {
  flex: 1 1 0;
  text-align: left;
}

.chart__axis li:last-child {
  text-align: right;
}

.chart__axisLabel {
  font-size: 10px;
  color: var(--ink-3);
}
</style>
