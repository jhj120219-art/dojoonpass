'use client'

import { useState, useActionState } from 'react'
import { loginAction, signUpAction } from './actions'

export default function LoginPage() {
  const [mode, setMode] = useState('login')
  const [loginState, loginFormAction] = useActionState(loginAction, null)
  const [signupState, signupFormAction] = useActionState(signUpAction, null)
  const currentState = mode === 'login' ? loginState : signupState
  const currentAction = mode === 'login' ? loginFormAction : signupFormAction

  return (
    <div className="min-h-screen bg-white flex flex-col justify-center px-6">
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
        <div className="mb-4 p-4 bg-red-50 border border-red-100 rounded-2xl">
          <p className="text-sm text-red-500 text-center">{currentState.error}</p>
        </div>
      )}
      {currentState?.message && (
        <div className="mb-4 p-4 bg-blue-50 border border-blue-100 rounded-2xl">
          <p className="text-sm text-blue-500 text-center">{currentState.message}</p>
        </div>
      )}
      <form action={currentAction}>
        <div className="space-y-3">
          <input type="email" name="email" placeholder="이메일" required className="w-full px-4 py-4 bg-gray-50 border border-gray-100 rounded-2xl text-gray-900 text-base placeholder:text-gray-400 focus:outline-none focus:border-blue-400 focus:bg-white transition-all duration-200" />
          <input type="password" name="password" placeholder="비밀번호" required minLength={6} className="w-full px-4 py-4 bg-gray-50 border border-gray-100 rounded-2xl text-gray-900 text-base placeholder:text-gray-400 focus:outline-none focus:border-blue-400 focus:bg-white transition-all duration-200" />
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
      <p className="mt-10 text-xs text-gray-300 text-center">로그인 시 서비스 이용약관 및 개인정보처리방침에 동의하게 됩니다</p>
    </div>
  )
}