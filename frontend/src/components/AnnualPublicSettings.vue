<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import QRCode from 'qrcode'
const props = defineProps({ modelValue: Boolean, settings: Object, busy: Boolean, runCommand: Function })
const emit = defineEmits(['update:modelValue'])
const enabled = ref(false)
const showNames = ref(false)
const drawEnabled = ref(false)
const lotterySwitches=ref({second:false,opening:false,playin:false,qualifier:false,semi:false})
const lotteryLabels={opening:'首轮签位抽取',second:'10进5对阵抽取',playin:'突围挑战队伍抽取',qualifier:'四强突围对阵抽取',semi:'四强半决赛对阵抽取'}
const qr = ref('')
const url = computed(() => props.settings?.token ? `${location.origin}/events/annual-games` : '')
const localOnly = computed(() => ['127.0.0.1', 'localhost'].includes(location.hostname))
watch(() => props.modelValue, value => { if (value) { enabled.value = !!props.settings?.enabled; showNames.value = !!props.settings?.show_names; drawEnabled.value = !!props.settings?.draw_enabled;for(const key of Object.keys(lotterySwitches.value))lotterySwitches.value[key]=props.settings?.[key+'_draw_enabled']??drawEnabled.value } })
watch(url, async value => { qr.value = value ? await QRCode.toDataURL(value, { width: 240, margin: 2 }) : '' }, { immediate: true })
async function save() {
  if (await props.runCommand('tournament-public', { enabled: enabled.value, show_names: showNames.value, draw_enabled: drawEnabled.value, ...Object.fromEntries(Object.entries(lotterySwitches.value).map(([key,value])=>[key+'_draw_enabled',value])) })) ElMessage.success('公开设置已保存')
}
async function copy() {
  try { await navigator.clipboard.writeText(url.value); ElMessage.success('链接已复制') }
  catch { ElMessage.info('请选中下方链接复制') }
}
</script>
<template>
  <el-dialog :model-value="modelValue" title="公开观赛页" width="min(520px, 94vw)" @update:model-value="emit('update:modelValue', $event)">
    <div class="settings-content">
    <p>外部观众无需登录，可查看正式赛事赛程、比分和Ban。任何拿到链接的人都能转发访问。</p>
    <div class="setting"><span>开启公开访问</span><el-switch v-model="enabled" :disabled="busy" aria-label="开启公开访问" /></div>
    <div class="setting"><span>公开队员姓名与比赛位置</span><el-switch v-model="showNames" :disabled="busy" aria-label="公开队员姓名与比赛位置" /></div>
    <div class="setting"><span>队伍人员抽取</span><el-switch v-model="drawEnabled" :disabled="busy" aria-label="队伍人员抽取" /></div>
    <div v-for="(label,key) in lotteryLabels" :key="key" class="setting"><span>{{label}}</span><el-switch v-model="lotterySwitches[key]" :disabled="busy" :aria-label="label" /></div>
    <p class="muted">主持人需登录管理账号，观众只能观看。以上开关独立控制，各阶段互不影响。队伍抽齐后可关闭人员抽取，仅开启首轮签位；测试时可“重置签位，保留队伍”，无需重新抽人。自动保存进度，完整抽选最多保留5次。重新组队前请先放弃本次抽选。</p>
    <p class="muted">默认仅公开队名。部门、段位、内部评分与演练数据均不公开。关闭后原链接立即停止提供赛事数据。</p>
    <section v-if="settings?.enabled && url" class="sharing"><el-alert v-if="localOnly" title="当前是本地预览链接，部署到外网域名后才能发给外部观众。" type="info" :closable="false" /><img v-if="qr" :src="qr" alt="公开观赛二维码" /><el-input :model-value="url" readonly aria-label="公开观赛链接" /><div><el-button @click="copy">复制链接</el-button><el-button tag="a" :href="url" target="_blank" rel="noopener">预览观赛页</el-button></div></section>
    </div>
    <template #footer><el-button @click="emit('update:modelValue', false)">关闭</el-button><el-button type="primary" :loading="busy" @click="save">保存设置</el-button></template>
  </el-dialog>
</template>
<style scoped>
.settings-content{max-height:65dvh;overflow-y:auto;padding-right:8px}.settings-content::-webkit-scrollbar{width:6px}.settings-content::-webkit-scrollbar-thumb{background:#6b879d70;border-radius:8px}.settings-content::-webkit-scrollbar-track{background:transparent}.settings-content::-webkit-scrollbar-button{display:none}p{line-height:1.8;font-size:13px}.setting{display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid var(--el-border-color-lighter)}.muted{color:var(--el-text-color-secondary);font-size:12px}.sharing{display:flex;align-items:center;flex-direction:column;gap:14px}.sharing img{width:200px;height:200px}.sharing>div:last-child{display:flex;gap:8px}
</style>
