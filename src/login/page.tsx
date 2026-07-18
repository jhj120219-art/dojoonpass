'use client'

import { useState } from 'react'
import { loginAction, signUpAction } from './actions'

export default function LoginPage() {
  // 로그인/회원가입 모드 전환
  const [mode, setMode] = useState<'login' | 'signup'>('login')

  // URL 파라미터에서 에러/안내 메시지 읽기
  const searchParams = new URLSearchParams(
    typeof window !== 'undefined' ? window.location.search : ''
  )
  const errorMessage = searchParams.get('error')
  const successMessage = searchParams.get('message')

  return (
    <div className="min-h-screen bg-white flex flex-col justify-center px-6">

      {/* 로고 및 타이틀 */}
      <div className="mb-10 text-center">
        <div className="w-14 h-14 bg-blue-500 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <span className="text-white text-2xl font-bold">도</span>
        </div>
        <h1 className="text-2xl font-bold text-gray-900">도준 경매 패스</h1>
        <p className="text-sm text-gray-400 mt-1">
          {mode === 'login' ? '반갑습니다! 로그인해주세요' : '새 계정을 만들어보세요'}
        </p>
      </div>

      {/* 에러 메시지 */}
      {errorMessage && (
        <div className="mb-4 p-4 bg-red-50 border border-red-100 rounded-2xl">
          <p className="text-sm text-red-500 text-center">{errorMessage}</p>
        </div>
      )}

      {/* 성공 메시지 */}
      {successMessage && (
        <div className="mb-4 p-4 bg-blue-50 border border-blue-100 rounded-2xl">
          <p className="text-sm text-blue-500 text-center">{successMessage}</p>
        </div>
      )}

      {/* 폼 */}
      <form action={mode === 'login' ? loginAction : signUpAction}>
        <div className="space-y-3">

          {/* 이메일 입력 */}
          <input
            type="email"
            name="email"
            placeholder="이메일"
            required
            className="w-full px-4 py-4 bg-gray-50 border border-gray-100 rounded-2xl text-gray-900 text-base placeholder:text-gray-400 focus:outline-none focus:border-blue-400 focus:bg-white transition-all duration-200"
          />

          {/* 비밀번호 입력 */}
          <input
            type="password"
            name="password"
            placeholder="비밀번호"
            required
            minLength={6}
            className="w-full px-4 py-4 bg-gray-50 border border-gray-100 rounded-2xl text-gray-900 text-base placeholder:text-gray-400 focus:outline-none focus:border-blue-400 focus:bg-white transition-all duration-200"
          />

          {/* 제출 버튼 */}
          <button
            type="submit"
            className="w-full py-4 mt-2 bg-blue-500 hover:bg-blue-600 active:bg-blue-700 text-white text-base font-semibold rounded-2xl transition-all duration-200 shadow-sm"
          >
            {mode === 'login' ? '로그인' : '회원가입'}
          </button>

        </div>
      </form>

      {/* 모드 전환 */}
      <div className="mt-6 text-center">
        <button
          onClick={() => setMode(mode === 'login' ? 'signup' : 'login')}
          className="text-sm text-gray-400 hover:text-blue-500 transition-colors duration-200"
        >
          {mode === 'login'
            ? '아직 계정이 없으신가요? 회원가입'
            : '이미 계정이 있으신가요? 로그인'}
        </button>
      </div>

      {/* 하단 안내 */}
      <p className="mt-10 text-xs text-gray-300 text-center">
        로그인 시 서비스 이용약관 및 개인정보처리방침에 동의하게 됩니다
      </p>

    </div>
  )
}