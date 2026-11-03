<script setup>
import { computed } from 'vue'
import MonthlySupplyActions from './MonthlySupplyActions.vue'
const props=defineProps({artifact:Object,month:String})
const data=computed(()=>props.artifact?.snapshot?.datasets||{})

</script>
<template>
 <article class="report-paper report-conclusion">
  <h2>九、下月经营核查清单</h2>
  <MonthlySupplyActions :data="data" />
  <p v-for="note in data.report_quality_notes||[]" :key="note.scope" class="quality-note">{{ note.text }}</p>
 </article>
</template>
<style scoped>
.report-conclusion { box-sizing: border-box; width: min(960px,100%); margin: auto; padding: 36px; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 10px; }
h2 { font-size: 22px; margin: 0 0 24px; }
.review-table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 15px; line-height: 1.8; }
.review-table th, .review-table td { border-bottom: 1px solid var(--border); padding: 16px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
.review-table thead th { color: var(--muted); }
.review-table th:first-child { width: 11%; } .review-table th:nth-child(2) { width: 32%; } .review-table th:nth-child(3) { width: 34%; }
.review-scroll { overflow-x: auto; }
.quality-note { margin: 24px 0 0; font-size: 15px; line-height: 1.8; color: var(--muted); }
.is-exporting { width: 794px; min-width: 794px; max-width: none; padding: 28px; border: 0; background: #fff; color: #17202a; }
.is-exporting .review-table { min-width: 0; font-size: 15px; }
@media (max-width:640px) { .report-conclusion { padding: 20px; } .review-table { min-width: 720px; } }
@media print { .report-conclusion { break-before: page; border: 0; width: 100%; padding: 0; } }
</style>
