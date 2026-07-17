<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const headingVisible = ref(false)
const form = reactive({
  username: 'jiajie',
  password: '',
})

const heading = 'Beauty commerce\nmade beautifully clear.'
const charDelay = 30
const initialDelay = 200
const headingLines = computed(() =>
  heading.split('\n').map((line, lineIndex, lines) => {
    const previousLength = lines.slice(0, lineIndex).reduce((total, item) => total + item.length, 0)
    return {
      text: line,
      chars: [...line].map((char, charIndex) => ({
        char: char === ' ' ? '\u00A0' : char,
        delay: initialDelay + (previousLength + charIndex) * charDelay,
      })),
    }
  }),
)

onMounted(() => {
  window.setTimeout(() => {
    headingVisible.value = true
  }, 40)
})

async function submit() {
  loading.value = true
  try {
    await auth.login(form)
    ElMessage.success('登录成功')
    router.push('/dashboard')
  } catch (error) {
    if (error?.response?.status === 401) {
      ElMessage.error('账号或密码错误，请重新输入')
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-hero">
    <video
      class="login-hero__video"
      src="https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260403_050628_c4e32401-fab4-4a27-b7a8-6e9291cd5959.mp4"
      autoplay
      loop
      muted
      playsinline
    />

    <div class="login-hero__shell">
      <header class="login-nav login-nav--simple">
        <div class="login-nav__logo">Jiajieco BI</div>
      </header>

      <section class="login-hero__content">
        <div class="login-hero__grid">
          <div class="login-hero__copy">
            <h1 class="login-hero__heading" aria-label="Beauty commerce made beautifully clear.">
              <span v-for="(line, lineIndex) in headingLines" :key="line.text" class="login-hero__line">
                <span
                  v-for="(item, charIndex) in line.chars"
                  :key="`${lineIndex}-${charIndex}`"
                  class="login-hero__char"
                  :class="{ 'is-visible': headingVisible }"
                  :style="{ transitionDelay: `${item.delay}ms` }"
                >
                  {{ item.char }}
                </span>
              </span>
            </h1>
            <p class="login-hero__subtitle">
              Real-time sales, inventory, and customer signals for a modern beauty e-commerce team.
            </p>
          </div>

          <div class="login-card-wrap">
            <section class="login-card liquid-glass" aria-label="登录">
              <div class="login-card__head">
                <h2>登录枷捷 BI</h2>
              </div>
              <el-form class="login-form login-form--glass" label-position="top" @submit.prevent="submit">
                <el-form-item label="账号">
                  <el-input v-model="form.username" size="large" autocomplete="username" />
                </el-form-item>
                <el-form-item label="密码">
                  <el-input
                    v-model="form.password"
                    size="large"
                    type="password"
                    autocomplete="current-password"
                    show-password
                  />
                </el-form-item>
                <el-button type="primary" size="large" :loading="loading" @click="submit">登录</el-button>
              </el-form>
            </section>
          </div>
        </div>
      </section>
    </div>
  </main>
</template>
