'use server'

import { createServerSupabaseClient } from '@/lib/supabaseServer'

export async function decreaseViewCount(propertyId: number) {
  const supabase = await createServerSupabaseClient()

  // 현재 로그인한 유저 확인
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return { error: '로그인이 필요합니다' }

  // 이번 달 년도/월 계산
  const now = new Date()
  const year = now.getFullYear()
  const month = now.getMonth() + 1

  // 이번 달 열람 횟수 조회
  const { data: viewCount } = await supabase
    .from('view_counts')
    .select('*')
    .eq('user_id', user.id)
    .eq('year', year)
    .eq('month', month)
    .single()

  // 이번 달 첫 열람 → 새 행 생성 (잔여 4회, 사용 1회)
  if (!viewCount) {
    await supabase.from('view_counts').insert({
      user_id: user.id,
      year,
      month,
      remaining_views: 4,
      total_used: 1,
    })
    return { success: true, remaining: 4 }
  }

  // 잔여 횟수가 0이면 차단
  if (viewCount.remaining_views <= 0) {
    return { error: '이번 달 열람 횟수를 모두 소진하셨습니다', remaining: 0 }
  }

  // 잔여 횟수 1 차감
  await supabase
    .from('view_counts')
    .update({
      remaining_views: viewCount.remaining_views - 1,
      total_used: viewCount.total_used + 1,
    })
    .eq('id', viewCount.id)

  return { success: true, remaining: viewCount.remaining_views - 1 }
}

export async function getViewCount() {
  const supabase = await createServerSupabaseClient()

  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return null

  const now = new Date()
  const year = now.getFullYear()
  const month = now.getMonth() + 1

  const { data: viewCount } = await supabase
    .from('view_counts')
    .select('*')
    .eq('user_id', user.id)
    .eq('year', year)
    .eq('month', month)
    .single()

  // 이번 달 첫 조회면 잔여 5회
  return viewCount ? viewCount.remaining_views : 5
}