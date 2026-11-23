<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import musicUrl from '../assets/annual-event-pop-stars.mp3'

const audio = ref(null)
const playing = ref(false)
const pending = ref(false)
const failed = ref(false)
function savedVolume() {
  try {
    const saved = localStorage.getItem('annual_event_music_volume')
    const value = saved === null ? 30 : Number(saved)
    return Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : 30
  } catch { return 30 }
}
const volume = ref(savedVolume())
const status = computed(() => pending.value ? '加载中' : failed.value ? '点击重试' : playing.value ? '播放中' : '点击播放')
function setVolume() {
  if (audio.value) audio.value.volume = volume.value / 100
  try { localStorage.setItem('annual_event_music_volume', String(volume.value)) } catch { /* Storage may be disabled. */ }
}
async function toggle() {
  const player = audio.value
  if (!player || pending.value) return
  if (!player.paused) { player.pause(); return }
  failed.value = false
  pending.value = true
  player.volume = volume.value / 100
  try { await player.play() }
  catch { failed.value = true; playing.value = false }
  finally { pending.value = false }
}
function onError() { playing.value = false; failed.value = true; pending.value = false }
onBeforeUnmount(() => audio.value?.pause())
</script>

<template>
  <section class="event-music" aria-label="赛事背景音乐">
    <audio ref="audio" :src="musicUrl" preload="none" loop playsinline @play="playing=true" @pause="playing=false" @error="onError" />
    <button class="music-toggle" :class="{playing}" :aria-label="playing ? '暂停背景音乐' : '播放背景音乐'" :aria-pressed="playing" :disabled="pending" @click="toggle">
      <span class="music-icon" aria-hidden="true">♫</span>
      <span class="music-copy"><small>{{ pending ? "加载中" : failed ? "重试" : "音乐" }}</small></span>
    </button>
    <label class="music-volume"><span>音量</span><input v-model.number="volume" aria-label="背景音乐音量" type="range" min="0" max="100" step="1" @input="setVolume"></label>
  </section>
</template>

<style scoped>
.event-music{position:fixed;left:16px;bottom:24px;z-index:23;display:flex;align-items:center;gap:16px;padding:9px 13px;border:1px solid #50738d70;border-radius:7px;background:#0c2234ed;color:#cce3f4;box-shadow:0 4px 22px #0003;backdrop-filter:blur(12px)}
.music-toggle{display:flex;align-items:center;gap:10px;padding:0;border:0;background:transparent;color:inherit;text-align:left;cursor:pointer;font:inherit}.music-toggle:disabled{cursor:wait}.music-icon{font-size:25px;color:#83bce3}.playing .music-icon{color:#b4e1ff}.music-copy{display:flex;flex-direction:column;gap:3px}.music-copy strong{font-size:12px;letter-spacing:1px;font-weight:600}.music-copy small{font-size:10px;color:#8eaac0}.music-volume{display:flex;flex-direction:column;gap:5px;font-size:10px;color:#8eaac0;border-left:1px solid #50738d45;padding-left:14px}.music-volume input{width:74px;height:14px;margin:0;accent-color:#82bae0;cursor:pointer}.music-toggle:focus-visible,.music-volume input:focus-visible{outline:2px solid #aed9f7;outline-offset:4px}
@media(max-width:650px){.event-music{left:10px;bottom:14px;gap:11px;padding:8px 10px}.music-volume{padding-left:10px}.music-volume input{width:58px}.music-icon{font-size:22px}}
</style>

<style scoped>
.event-music{position:relative;left:auto;bottom:auto;padding:0;gap:0;border:0;border-radius:0;background:transparent;box-shadow:none;backdrop-filter:none;align-items:stretch}
.music-toggle{flex-direction:column;justify-content:center;gap:3px;min-width:46px;padding:10px 8px;border:1px solid #4d709158;background:#10273beb;color:#b5d3e9;text-align:center}.music-toggle:hover{background:#285271}.music-icon{font-size:21px;line-height:1;color:inherit}.music-copy small{font-size:10px;color:inherit}.playing{background:#234761;color:#b4e1ff}
.music-volume{position:absolute;bottom:calc(100% + 8px);right:0;flex-direction:row;align-items:center;gap:8px;padding:12px;border:1px solid #4d709158;border-radius:5px;background:#10273bf5;white-space:nowrap;visibility:hidden;opacity:0;transition:opacity .15s ease}.event-music:hover .music-volume,.event-music:focus-within .music-volume{visibility:visible;opacity:1}.event-music::before{content:"";position:absolute;bottom:100%;right:0;width:140px;height:10px}
@media(max-width:650px){.event-music{left:auto;bottom:auto;padding:0;gap:0}.music-toggle{padding:8px 6px}.music-volume{padding:12px}}
</style>
