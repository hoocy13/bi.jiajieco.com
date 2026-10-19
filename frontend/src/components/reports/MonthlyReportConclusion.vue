<script setup>
import { computed } from 'vue'
import { buildManagementReview } from '../../utils/monthlyReportDecision'
const props=defineProps({artifact:Object,month:String})
const data=computed(()=>props.artifact?.snapshot?.datasets||{})
const review=computed(()=>buildManagementReview(data.value,props.month))
</script>
<template>
 <article class="report-paper report-conclusion">
  <h2>九、经营判断与下月重点</h2>
  <div class="review-scroll"><table class="review-table"><thead><tr><th>重点</th><th>已核实事实</th><th>建议动作（待确认）</th><th>下月核对</th></tr></thead><tbody>
   <tr v-for="row in review" :key="row.topic" class="review-row"><th>{{ row.topic }}</th><td>{{ row.fact }}</td><td>{{ row.advice }}</td><td>{{ row.metric }}</td></tr>
  </tbody></table></div>
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
