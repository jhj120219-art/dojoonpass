'use server'

import { redirect } from 'next/navigation'
import { createServerSupabaseClient } from '@/lib/supabaseServer'

const DEFAULT_REDIRECT = '/properties'

// middleware.ts가 만드는 `/login?redirect=<pathname>`의 값을 검증한다.
// 외부 URL로 리다이렉트되는 Open Redirect를 막기 위해 '/'로 시작하는 내부 상대경로만
// 허용하고, '//evil.com'이나 '/\evil.com'처럼 프로토콜-상대 URL로 해석될 수 있는
// 패턴은 전부 거부해 기본값(/properties)으로 되돌린다.
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