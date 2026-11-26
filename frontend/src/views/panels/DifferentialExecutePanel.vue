<template>
  <section class="panel" data-testid="execute-panel">
    <div class="panel-head">
      <div>
        <h3>差分执行</h3>
        <p class="page-desc">凭隐私预算页的有效预约提交执行；同一预约的执行回执只确认一次费用。</p>
      </div>
      <button class="btn primary" data-testid="open-execute" type="button" @click="openForm">
        执行差分查询
      </button>
    </div>

    <p v-if="!validReservations.length" class="panel-message" data-testid="execute-no-valid">
      暂无有效（已确认）预算预约，请先在隐私预算页预约额度后再提交执行。
    </p>
    <p v-else class="panel-message" data-testid="execute-valid-count">
      当前可用有效预约 {{ validReservations.length }} 笔。
    </p>

    <div v-if="receipt" class="receipt" data-testid="execute-receipt">
      <h4>执行回执</h4>
      <dl class="receipt-grid">
        <dt>执行编号</dt>
        <dd data-testid="execute-receipt-执行编号">{{ receipt.执行编号 }}</dd>
        <dt>预约编号</dt>
        <dd>{{ receipt.预约编号 }}</dd>
        <dt>查询编号</dt>
        <dd data-testid="execute-receipt-查询编号">{{ receipt.查询编号 }}</dd>
        <dt>扣费编号</dt>
        <dd>{{ receipt.扣费编号 }}</dd>
        <dt>扣费Epsilon</dt>
        <dd data-testid="execute-receipt-扣费">{{ receipt.扣费Epsilon }}</dd>
        <dt>预算剩余</dt>
        <dd>{{ receipt.预算剩余 }}</dd>
        <dt>执行时间</dt>
        <dd>{{ receipt.执行时间 }}</dd>
        <dt>结论</dt>
        <dd class="status-ok">{{ receipt.结论 }}</dd>
      </dl>
    </div>

    <p v-if="message" class="panel-message" data-testid="execute-message">{{ message }}</p>
    <p v-if="errorMessage" class="error-text" data-testid="execute-error">{{ errorMessage }}</p>

    <div v-if="showForm" class="modal-backdrop" data-testid="execute-modal">
      <form class="modal" @submit.prevent="submit">
        <h3>执行差分查询</h3>
        <label class="create-field">
          <span>预约编号</span>
          <input
            v-model="form.预约编号"
            data-testid="execute-预约编号"
            list="valid-reservation-codes"
            required
            placeholder="填写或选择已确认的预约编号"
          />
          <datalist id="valid-reservation-codes">
            <option
              v-for="item in validReservations"
              :key="item.id"
              :value="item.预约编号"
            >
              {{ item.数据集名称 }} · 费用 {{ item.申请费用 }}
            </option>
          </datalist>
        </label>
        <label class="create-field">
          <span>查询语句</span>
          <input
            v-model="form.查询语句"
            data-testid="execute-查询语句"
            required
            placeholder="SELECT COUNT(*) FROM ..."
          />
        </label>
        <label class="create-field">
          <span>查询用户</span>
          <input v-model="form.查询用户" data-testid="execute-查询用户" required placeholder="如 数据分析师-张三" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showForm = false">取消</button>
          <button
            class="btn primary"
            data-testid="submit-execute"
            type="submit"
            :disabled="submitting || !form.预约编号"
          >
            {{ submitting ? '执行中…' : '提交执行' }}
          </button>
        </div>
        <p v-if="errorMessage" class="error-text" data-testid="execute-modal-error">{{ errorMessage }}</p>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { executeQuery, type ExecutePayload } from '@/domain/differential_sql'
import { listReservations, type ExecuteReceipt, type Reservation } from '@/domain/privacy_budget'

const emit = defineEmits<{ changed: [] }>()

const validReservations = ref<Reservation[]>([])
const receipt = ref<ExecuteReceipt | null>(null)
const message = ref('')
const errorMessage = ref('')
const showForm = ref(false)
const submitting = ref(false)
const form = ref<Record<string, string>>({})

async function openForm() {
  form.value = { 预约编号: '', 查询语句: '', 查询用户: '' }
  errorMessage.value = ''
  await reloadValid()
  showForm.value = true
}

async function submit() {
  submitting.value = true
  message.value = ''
  errorMessage.value = ''
  try {
    const result = await executeQuery(form.value)
    const payload = result.entry as ExecutePayload | null
    if (result.ok && payload) {
      receipt.value = payload.回执
      message.value = result.message
      showForm.value = false
    } else {
      errorMessage.value = result.message
    }
    await reloadValid()
    emit('changed')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '执行提交失败'
  } finally {
    submitting.value = false
  }
}

async function reloadValid() {
  validReservations.value = await listReservations('已确认')
}

onMounted(reloadValid)
</script>
