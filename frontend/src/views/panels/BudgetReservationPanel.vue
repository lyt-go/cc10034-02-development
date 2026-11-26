<template>
  <section class="panel" data-testid="reservation-panel">
    <div class="panel-head">
      <div>
        <h3>预算预约</h3>
        <p class="page-desc">为待执行的差分查询预留额度：已确认预约的合计不会超过可用额度。</p>
      </div>
      <button class="btn primary" data-testid="open-reserve" type="button" @click="openForm">
        预约额度
      </button>
    </div>

    <table class="data-table" data-testid="reservation-table">
      <thead>
        <tr>
          <th>预约编号</th>
          <th>数据集名称</th>
          <th>申请费用</th>
          <th>申请人</th>
          <th>申请时间</th>
          <th>当前状态</th>
          <th>拒绝原因</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="item in reservations"
          :key="item.id"
          :data-testid="`reservation-row-${item.id}`"
          :data-status="item.status"
        >
          <td>{{ item.预约编号 }}</td>
          <td>{{ item.数据集名称 }}</td>
          <td>{{ item.申请费用 }}</td>
          <td>{{ item.申请人 }}</td>
          <td>{{ item.申请时间 }}</td>
          <td data-testid="reservation-status">{{ item.status }}</td>
          <td>{{ item.拒绝原因 || '—' }}</td>
          <td>
            <button
              v-if="item.status === '已确认'"
              class="link"
              type="button"
              :data-testid="`cancel-reserve-${item.id}`"
              @click="cancel(item)"
            >
              取消预约
            </button>
            <span v-else>—</span>
          </td>
        </tr>
        <tr v-if="!reservations.length">
          <td colspan="8" class="empty-state">暂无预算预约，可点击「预约额度」为差分查询留额度</td>
        </tr>
      </tbody>
    </table>

    <div v-if="receipt" class="receipt" data-testid="reserve-receipt" :data-status="receipt.status">
      <h4>预算预约回执</h4>
      <dl class="receipt-grid">
        <dt>预约编号</dt>
        <dd data-testid="receipt-预约编号">{{ receipt.预约编号 }}</dd>
        <dt>数据集名称</dt>
        <dd>{{ receipt.数据集名称 }}</dd>
        <dt>申请费用</dt>
        <dd>{{ receipt.申请费用 }}</dd>
        <dt>回执状态</dt>
        <dd data-testid="receipt-status" :class="receipt.status === '已确认' ? 'status-ok' : 'status-bad'">
          {{ receipt.status }}
        </dd>
        <dt>决策时可用额度</dt>
        <dd>{{ receipt.可用额度 }}</dd>
        <dt v-if="receipt.拒绝原因">拒绝原因</dt>
        <dd v-if="receipt.拒绝原因" class="status-bad" data-testid="receipt-reason">
          {{ receipt.拒绝原因 }}
        </dd>
      </dl>
    </div>

    <p v-if="message" class="panel-message" data-testid="reservation-message">{{ message }}</p>

    <div v-if="showForm" class="modal-backdrop" data-testid="reserve-modal">
      <form class="modal" @submit.prevent="submit">
        <h3>预算预约表单</h3>
        <label class="create-field">
          <span>数据集名称</span>
          <select v-model="form.数据集名称" data-testid="reserve-数据集名称" required>
            <option value="" disabled>请选择已登记预算的数据集</option>
            <option v-for="budget in budgets" :key="budget.id" :value="String(budget.数据集名称)">
              {{ budget.数据集名称 }}（可用 {{ availableOf(budget) }}）
            </option>
          </select>
        </label>
        <label class="create-field">
          <span>申请费用（Epsilon）</span>
          <input v-model="form.申请费用" data-testid="reserve-申请费用" required placeholder="如 0.3" />
        </label>
        <label class="create-field">
          <span>申请人</span>
          <input v-model="form.申请人" data-testid="reserve-申请人" placeholder="如 数据分析师-张三" />
        </label>
        <label class="create-field">
          <span>用途说明</span>
          <input v-model="form.用途说明" data-testid="reserve-用途说明" placeholder="待执行差分查询的用途" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showForm = false">取消</button>
          <button class="btn primary" data-testid="submit-reserve" type="submit" :disabled="submitting">
            {{ submitting ? '提交中…' : '提交预约' }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import type { EntryRow } from '@/data/types'
import {
  cancelReservation,
  createReservation,
  listReservations,
  type Reservation,
} from '@/domain/privacy_budget'

const props = defineProps<{ budgets: EntryRow[] }>()
const emit = defineEmits<{ changed: [] }>()

const reservations = ref<Reservation[]>([])
const receipt = ref<Reservation | null>(null)
const message = ref('')
const showForm = ref(false)
const submitting = ref(false)
const form = ref<Record<string, string>>({})

function heldOf(budget: EntryRow): number {
  return reservations.value
    .filter((item) => item.预算编号 === budget.预算编号 && item.status === '已确认')
    .reduce((sum, item) => sum + Number(item.申请费用 || 0), 0)
}

function availableOf(budget: EntryRow): string {
  const total = Number(budget.总预算Epsilon || 0)
  const consumed = Number(budget.已消耗Epsilon || 0)
  const available = total - consumed - heldOf(budget)
  return String(Number(available.toFixed(4)))
}

function openForm() {
  form.value = { 数据集名称: '', 申请费用: '', 申请人: '', 用途说明: '' }
  message.value = ''
  showForm.value = true
}

async function submit() {
  submitting.value = true
  message.value = ''
  try {
    const result = await createReservation(form.value)
    if (result.entry) receipt.value = result.entry
    message.value = result.message
    showForm.value = false
    await reload()
    emit('changed')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '预约提交失败'
  } finally {
    submitting.value = false
  }
}

async function cancel(item: Reservation) {
  message.value = ''
  try {
    const result = await cancelReservation(item.id)
    message.value = result.message
    await reload()
    emit('changed')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '取消预约失败'
  }
}

async function reload() {
  reservations.value = await listReservations()
}

onMounted(reload)
</script>
