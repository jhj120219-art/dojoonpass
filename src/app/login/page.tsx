'use client'

import { useState, useActionState, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { loginAction, signUpAction } from './actions'

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginPageInner />
    </Suspense>
  )
}

// src/proxy.ts가 붙이는 `?redirect=` 쿼리를 읽으려면 useSearchParams가 필요하고,
// 이 훅은 Suspense 경계 안에서만 정적 렌더링과 함께 안전하게 쓸 수 있어 별도 컴포넌트로 분리했다.
function LoginPageInner() {
  const searchParams = useSearchParams()
  const redirectParam = searchParams.get('redirect')
  const [mode, setMode] = useState('login')
  const [loginState, loginFormAction] = useActionState(loginAction, null)
  const [signupState, signupFormAction] = useActionState(signUpAction, null)
  const currentState = mode === 'login' ? loginState : signupState
  const currentAction = mode === 'login' ? loginFormAction : signupFormAction

  return (
    <main className="min-h-screen bg-white flex flex-col justify-center px-6">
      {/* 로그인 폼이 데스크톱에서 화면 전체 폭으로 늘어나 입력칸이 1920px를 가로지르던 문제를
          막는다. 이건 페이지 컨테이너(1320px)가 아니라 **폼 한 줄의 가독 폭**이라 별도 값을 쓴다
          — Master Spec §5.2가 금지하는 "새 페이지 max-width"에 해당하지 않는다. */}
      <div className="w-full max-w-md mx-auto">
      <div className="mb-10 text-center">
        <div className="w-14 h-14 bg-blue-500 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <span className="text-white text-2xl font-bold">콕</span>
        </div>
        <h1 className="text-2xl font-bold text-gray-900">콕찰</h1>
        <p className="text-sm text-gray-400 mt-1">
          {mode === 'login' ? '반갑습니다! 로그인해주세요' : '새 계정을 만들어보세요'}
        </p>
      </div>
      {currentState?.error && (
        <div role="alert" className="mb-4 p-4 bg-red-50 border border-red-100 rounded-2xl">
          <p className="text-sm text-red-500 text-center">{currentState.error}</p>
        </div>
      )}
      {currentState && 'message' in currentState && currentState.message && (
        <div role="status" className="mb-4 p-4 bg-blue-50 border border-blue-100 rounded-2xl">
          <p className="text-sm text-blue-500 text-center">{currentState.message}</p>
        </div>
      )}
      <form action={currentAction}>
        <div className="space-y-3">
          <input type="email" name="email" placeholder="이메일" aria-label="이메일" required className="w-full px-4 py-4 bg-gray-50 border border-gray-100 rounded-2xl text-gray-900 text-base placeholder:text-gray-400 focus:outline-none focus:border-blue-400 focus:bg-white transition-all duration-200" />
          <input type="password" name="password" placeholder="비밀번호" aria-label="비밀번호" required minLength={6} className="w-full px-4 py-4 bg-gray-50 border border-gray-100 rounded-2xl text-gray-900 text-base placeholder:text-gray-400 focus:outline-none focus:border-blue-400 focus:bg-white transition-all duration-200" />
          {redirectParam && <input type="hidden" name="redirect" value={redirectParam} />}
          <button type="submit" className="w-full py-4 mt-2 bg-blue-500 hover:bg-blue-600 active:bg-blue-700 text-white text-base font-semibold rounded-2xl transition-all duration-200 shadow-sm">
            {mode === 'login' ? '로그인' : '회원가입'}
          </button>
        </div>
      </form>
      <div className="mt-6 text-center">
        <button onClick={() => setMode(mode === 'login' ? 'signup' : 'login')} className="text-sm text-gray-400 hover:text-blue-500 transition-colors duration-200">
          {mode === 'login' ? '아직 계정이 없으신가요? 회원가입' : '이미 계정이 있으신가요? 로그인'}
        </button>
      </div>
      <div className="mt-3 text-center">
        {/* 첫 화면(`/`)이 곧 검색 화면이므로 둘러보기 대상도 `/`로 통일한다 */}
        <Link href="/" className="text-xs text-gray-400 hover:text-blue-500 transition-colors duration-200">
          로그인 없이 둘러보기
        </Link>
      </div>
      <p className="mt-10 text-xs text-gray-300 text-center">로그인 시 서비스 이용약관 및 개인정보처리방침에 동의하게 됩니다</p>
      </div>
    </main>
  )
}