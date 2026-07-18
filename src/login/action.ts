'use server'

import { redirect } from 'next/navigation'
import { createServerSupabaseClient } from '@/lib/supabaseServer'

// ----------------------------------------------------------------
// 로그인 액션
// ----------------------------------------------------------------
export async function loginAction(formData: FormData) {
  const supabase = await createServerSupabaseClient()

  const email = formData.get('email') as string
  const password = formData.get('password') as string

  const { error } = await supabase.auth.signInWithPassword({
    email,
    password,
  })

  if (error) {
    redirect('/login?error=이메일 또는 비밀번호가 올바르지 않습니다')
  }

  redirect('/properties')
}

// ----------------------------------------------------------------
// 회원가입 액션
// ----------------------------------------------------------------
export async function signUpAction(formData: FormData) {
  const supabase = await createServerSupabaseClient()

  const email = formData.get('email') as string
  const password = formData.get('password') as string

  const { error } = await supabase.auth.signUp({
    email,
    password,
  })

  if (error) {
    redirect('/login?error=회원가입에 실패했습니다. 다시 시도해주세요')
  }

  redirect('/login?message=이메일을 확인하여 가입을 완료해주세요')
}