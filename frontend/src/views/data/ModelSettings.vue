<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getModelSettings, testModelSettings, updateModelSettings } from '../../api/modelSettings'

const loading = ref(false)
const testing = ref(false)
const configured = ref(false)
const maskedKey = ref('')
const updatedAt = ref('')
const configError = ref('')
const form = reactive({
  base_url: '',
  model_id: '',
  api_key: '',
})

async function fetchSettings() {
  loading.value = true
  try {
    const result = await getModelSettings()
    form.base_url = result.data.base_url
    form.model_id = result.data.model_id
    form.api_key = ''
    configured.value = result.data.configured
    maskedKey.value = result.data.api_key_masked
    updatedAt.value = result.data.updated_at
    configError.value = result.data.error || ''
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  loading.value = true
  try {
    await updateModelSettings({
      base_url: form.base_url.trim(),
      model_id: form.model_id.trim(),
      api_key: form.api_key.trim() || null,
    })
    ElMessage.success('模型配置已保存')
    await fetchSettings()
  } finally {
    loading.value = false
  }
}

async function testConnection() {
  testing.value = true
  try {
    const result = await testModelSettings()
    ElMessage.success(result.data.response || '连接成功')
  } finally {
    testing.value = false
  }
}

onMounted(fetchSettings)
</script>

<template>
  <div class="page-stack model-settings-page" v-loading="loading">
    <section class="panel model-settings-panel">
      <header>
        <h2>大模型连接<span class="panel-source">（OpenAI Compatible）</span></h2>
        <el-tag :type="configured ? 'success' : 'warning'" effect="plain">{{ configured ? '已配置' : '未配置' }}</el-tag>
      </header>
      <el-form label-position="top" class="model-settings-form" @submit.prevent>
        <el-form-item label="接口地址">
          <el-input v-model="form.base_url" placeholder="https://example.com/v1" />
        </el-form-item>
        <el-form-item label="模型 ID">
          <el-input v-model="form.model_id" placeholder="model-id" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="maskedKey ? `当前密钥：${maskedKey}，留空表示不修改` : '输入 API Key'"
          />
        </el-form-item>
        <el-alert
          v-if="configError"
          type="warning"
          :closable="false"
          show-icon
          title="当前 API Key 无法读取，请重新输入完整 API Key 后保存"
        />
        <div class="model-settings-actions">
          <el-button type="primary" :icon="'Check'" @click="saveSettings">保存配置</el-button>
          <el-button :loading="testing" :icon="'Connection'" @click="testConnection">测试连接</el-button>
          <span v-if="updatedAt">最近更新：{{ String(updatedAt).slice(0, 19).replace('T', ' ') }}</span>
        </div>
      </el-form>
    </section>

    <section class="model-security-note">
      <el-icon><Lock /></el-icon>
      <div>
        <strong>密钥安全</strong>
        <p>API Key 仅在后端加密保存，页面不会读取或返回完整密钥。留空保存时沿用当前密钥。</p>
      </div>
    </section>
  </div>
</template>
