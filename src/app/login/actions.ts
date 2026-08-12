'use server'

import { redirect } from 'next/navigation'
import { createServerSupabaseClient } from '@/lib/supabaseServer'

// 기본 복귀 경로는 첫 화면(=검색 화면)이다(docs/FRONTEND_MASTER_SPEC.md §3.4).
// 예전 값이던 '/properties'는 Supabase 직접 조회 레거시 목록 화면이라, 로그인 성공의
// 기본 착지점으로는 더 이상 맞지 않는다.
const DEFAULT_REDIRECT = '/'

// src/proxy.ts가 만드는 `/login?redirect=<pathname + search>`의 값을 검증한다.
// (Sprint 50에 middleware.ts -> proxy.ts로 파일명이 바뀌었다. 로직은 동일하다.)
// 외부 URL로 리다이렉트되는 Open Redirect를 막기 위해 '/'로 시작하는 내부 상대경로만
// 허용하고, '//evil.com'이나 '/\evil.com'처럼 프로토콜-상대 URL로 해석될 수 있는
// 패턴은 전부 거부해 기본값(DEFAULT_REDIRECT = '/')으로 되돌린다.
// (쿼리스트링이 붙은 값도 '/'로 시작하므로 그대로 허용된다 — 상세 복귀에 필요하다.)
function sanitizeRedirectPath(value: FormDataEntryValue | null): string {
  if (typeof value !== 'string' || value.length === 0) return DEFAULT_REDIRECT
  if (!value.startsWith('/') || /^\/[\/\\]/.test(value)) return DEFAULT_REDIRECT
  return value
}

export async function loginAction(prevState: { error: string } | null, formData: FormData) {
  const supabase = await createServerSupabaseClient()

  const email = formData.get('email') as string
  const password = formData.get('password') as string

  const { error } = await supabase.auth.signInWithPassword({
    email,
    password,
  })

  if (error) {
    return { error: '이메일 또는 비밀번호가 올바르지 않습니다' }
  }

  redirect(sanitizeRedirectPath(formData.get('redirect')))
}

export async function signUpAction(
  prevState: { error: string } | { message: string } | null,
  formData: FormData
) {
  const supabase = await createServerSupabaseClient()

  const email = formData.get('email') as string
  const password = formData.get('password') as string

  const { error } = await supabase.auth.signUp({
    email,
    password,
  })

  if (error) {
    return { error: '회원가입에 실패했습니다. 다시 시도해주세요' }
  }

  return { message: '이메일을 확인하여 가입을 완료해주세요' }
}