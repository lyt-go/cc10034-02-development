/** 隐私预算预约：预约表单、预约回执、取消与扣费记录的纯前端领域层。 */
import { request } from '@/api/client'

export type Reservation = {
  id: number
  预约编号: string
  预算编号: string
  数据集名称: string
  申请费用: string
  申请人: string
  用途说明: string
  申请时间: string
  可用额度: string
  拒绝原因: string
  status: string
  执行回执: ExecuteReceipt | null
  扣费编号: string
}

export type ExecuteReceipt = {
  执行编号: string
  预约编号: string
  查询编号: string
  扣费编号: string
  数据集名称: string
  查询语句: string
  查询用户: string
  扣费Epsilon: string
  预算剩余: string
  执行时间: string
  结论: string
}

export type ReservationResult = {
  ok: boolean
  message: string
  entry: Reservation | null
}

export async function listReservations(status?: string): Promise<Reservation[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  const response = await request(`/api/privacy_budget/reservations${query}`)
  if (!response.ok) throw new Error('预约列表读取失败')
  const payload = (await response.json()) as { items: Reservation[] }
  return payload.items
}

export async function createReservation(
  values: Record<string, string>,
): Promise<ReservationResult> {
  const response = await request('/api/privacy_budget/reservations', {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return (await response.json()) as ReservationResult
}

export async function cancelReservation(id: number): Promise<ReservationResult> {
  const response = await request(`/api/privacy_budget/reservations/${id}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ action: '取消预约' }),
  })
  return (await response.json()) as ReservationResult
}
