/** 差分查询执行：凭有效预算预约提交执行并领取执行回执。 */
import { request } from '@/api/client'
import type { EntryRow } from '@/data/types'
import type { ExecuteReceipt, Reservation } from './privacy_budget'

export type ExecutePayload = {
  回执: ExecuteReceipt
  查询记录: EntryRow | null
  预约: Reservation
}

export type ExecuteResult = {
  ok: boolean
  message: string
  entry: ExecutePayload | null
}

export async function executeQuery(
  values: Record<string, string>,
): Promise<ExecuteResult> {
  const response = await request('/api/differential_sql/execute', {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return (await response.json()) as ExecuteResult
}
