'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import type { SearchQueryParams } from './types'
import PriceRangeSelect from '@/components/PriceRangeSelect'
import SearchAccordionSection from '@/components/SearchAccordionSection'
import PropertyTypeTree from '@/components/PropertyTypeTree'

const SIDO_LIST = [
  '서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종',
  '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주',
]

const SPECIAL_CONDITIONS = [
  { value: 'lien', label: '유치권' },
  { value: 'lien_excluded', label: '유치권 배제' },
  { value: 'statutory_superficies', label: '법정지상권' },
  { value: 'grave_right', label: '분묘기지권' },
  { value: 'senior_provisional_registration', label: '선순위 가등기' },
  { value: 'senior_provisional_disposition', label: '선순위 가처분' },
  { value: 'partial_bid', label: '지분입찰 물건' },
]

// Tank Auction의 splSrchType 라디오(적용 안함/선택 1개 이상 포함/선택 모두 포함/선택 제외)와 동일 구성.
// TODO(API 미지원): 백엔드 special_conditions 필터 자체가 아직 구현되지 않아, 이 라디오는
// UI만 제공하고 검색 쿼리에는 반영하지 않는다.
const SPECIAL_SEARCH_TYPES = [
  { value: '0', label: '적용 안함' },
  { value: '1', label: '선택 1개 이상 포함' },
  { value: '2', label: '선택 모두 포함' },
  { value: '4', label: '선택 제외' },
] as const

// Tank Auction의 fbCntBgn/fbCntEnd select(0~10, 자유 숫자입력 아님)와 동일 구성.
const FAIL_COUNT_OPTIONS = Array.from({ length: 11 }, (_, i) => String(i))

// Tank Auction의 minbPctBgn/minbPctEnd select(10~100, 10 단위)와 동일 구성.
const BID_RATE_OPTIONS = Array.from({ length: 10 }, (_, i) => String((i + 1) * 10))

type SearchFormState = {
  sido: string
  sigungu: string
  dong: string
  addressDetail: string
  courtName: string
  caseYear: string
  caseNo: string
  status: string
  failCountMin: string
  failCountMax: string
  auctionDateFrom: string
  auctionDateTo: string
  appraisalMin: string
  appraisalMax: string
  bidPriceMin: string
  bidPriceMax: string
  buildingAreaMin: string
  buildingAreaMax: string
  landAreaMin: string
  landAreaMax: string
  bidRateMin: string
  bidRateMax: string
  specialConditions: string[]
}

const INITIAL_STATE: SearchFormState = {
  sido: '',
  sigungu: '',
  dong: '',
  addressDetail: '',
  courtName: '',
  caseYear: '',
  caseNo: '',
  status: '',
  failCountMin: '',
  failCountMax: '',
  auctionDateFrom: '',
  auctionDateTo: '',
  // PriceRangeSelect의 프리셋 select 값은 '0'을 "제한없음" sentinel로 사용한다
  appraisalMin: '0',
  appraisalMax: '0',
  bidPriceMin: '0',
  bidPriceMax: '0',
  buildingAreaMin: '',
  buildingAreaMax: '',
  landAreaMin: '',
  landAreaMax: '',
  bidRateMin: '',
  bidRateMax: '',
  specialConditions: [],
}

export default function SearchForm() {
  const router = useRouter()
  const [form, setForm] = useState<SearchFormState>(INITIAL_STATE)

  // Tank Auction의 주소선택 toggleBtn(주소/법원)과 동일한 2-way 탭. UI 전용 상태(mock).
  const [addressMode, setAddressMode] = useState<'address' | 'court'>('address')
  // Tank Auction의 splSrchType 라디오. UI 전용 상태(mock, TODO 참고).
  const [specialSearchType, setSpecialSearchType] = useState<string>('0')
  // Tank Auction의 물건종류 체크박스 트리 선택값. TODO 참고(단일 선택시에만 API 연동).
  const [propertyCategories, setPropertyCategories] = useState<string[]>([])

  function update<K extends keyof SearchFormState>(key: K, value: SearchFormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  // Tank Auction의 매각기일 퀵버튼(당일/+7/+14/X, js-set-bid-dt)과 동일한 동작.
  // 오늘 날짜를 시작일로, 오늘+N일을 종료일로 채운다. null이면 두 필드 모두 비운다(X 버튼).
  function setQuickAuctionDate(days: number | null) {
    if (days === null) {
      setForm((prev) => ({ ...prev, auctionDateFrom: '', auctionDateTo: '' }))
      return
    }
    const toISODate = (d: Date) => d.toISOString().slice(0, 10)
    const today = new Date()
    const end = new Date(today)
    end.setDate(end.getDate() + days)
    setForm((prev) => ({ ...prev, auctionDateFrom: toISODate(today), auctionDateTo: toISODate(end) }))
  }

  function toggleSpecialCondition(value: string) {
    setForm((prev) => ({
      ...prev,
      specialConditions: prev.specialConditions.includes(value)
        ? prev.specialConditions.filter((v) => v !== value)
        : [...prev.specialConditions, value],
    }))
  }

  function buildSearchQuery(): SearchQueryParams {
    const query: SearchQueryParams = {}
    if (addressMode === 'address') {
      if (form.sido) query.sido = form.sido
      if (form.sigungu) query.sigungu = form.sigungu
      if (form.dong) query.dong = form.dong
      if (form.addressDetail) query.address_detail = form.addressDetail
    } else {
      if (form.courtName) query.court_name = form.courtName
    }
    if (form.caseYear && form.caseNo) query.case_no = `${form.caseYear}타경${form.caseNo}`
    else if (form.caseNo) query.case_no = form.caseNo
    // property_type은 자유텍스트 단일 컬럼(LIKE)이라 다중 카테고리 선택을 표현할 수 없음.
    // 정확히 1개만 선택된 경우에만 best-effort로 매핑한다 (PropertyTypeTree.tsx 참고).
    if (propertyCategories.length === 1) query.property_type = propertyCategories[0]
    if (form.status) query.status = form.status
    if (form.failCountMin) query.min_fail_count = Number(form.failCountMin)
    if (form.failCountMax) query.max_fail_count = Number(form.failCountMax)
    if (form.auctionDateFrom) query.auction_date_from = form.auctionDateFrom
    if (form.auctionDateTo) query.auction_date_to = form.auctionDateTo
    // '0'(제한없음) sentinel이므로 truthy 문자열 체크가 아니라 수치 비교로 판정해야 한다
    if (Number(form.appraisalMin) > 0) query.min_appraisal = Number(form.appraisalMin)
    if (Number(form.appraisalMax) > 0) query.max_appraisal = Number(form.appraisalMax)
    if (Number(form.bidPriceMin) > 0) query.min_bid_price = Number(form.bidPriceMin)
    if (Number(form.bidPriceMax) > 0) query.max_bid_price = Number(form.bidPriceMax)
    // TODO(API 미지원): auction_item에 대응 컬럼이 없어 백엔드가 이 파라미터를 읽지 않는다
    if (form.buildingAreaMin) query.min_building_area = Number(form.buildingAreaMin)
    if (form.buildingAreaMax) query.max_building_area = Number(form.buildingAreaMax)
    if (form.landAreaMin) query.min_land_area = Number(form.landAreaMin)
    if (form.landAreaMax) query.max_land_area = Number(form.landAreaMax)
    // bid_rate는 DB에 0~1 비율로 저장되어 있어 입력받은 %값을 100으로 나눠 전달한다
    if (form.bidRateMin) query.min_bid_rate = Number(form.bidRateMin) / 100
    if (form.bidRateMax) query.max_bid_rate = Number(form.bidRateMax) / 100
    // TODO(API 미지원): 백엔드에 special_conditions 필터가 아직 구현되지 않음
    if (form.specialConditions.length > 0) query.special_conditions = form.specialConditions
    // TODO(API 미지원): specialSearchType(AND/OR/제외 조합 방식)은 백엔드에 대응 개념이 없어 미전송
    return query
  }

  function handleSearch() {
    const query = buildSearchQuery()
    const params = new URLSearchParams()
    Object.entries(query).forEach(([key, value]) => {
      if (value === undefined) return
      params.set(key, Array.isArray(value) ? value.join(',') : String(value))
    })

    const qs = params.toString()
    router.push(qs ? `/search?${qs}` : '/search')
  }

  const inputClass =
    'w-full rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200'
  const labelClass = 'text-xs font-medium text-gray-500 mb-1 block'

  return (
    <div className="bg-white rounded-2xl px-4 shadow-sm border border-gray-100 mb-3">
      {/* 주소/법원 토글 — Tank Auction의 toggleBtn(주소/법원 탭) 참고 */}
      <div className="pt-4">
        <div className="flex rounded-full overflow-hidden border border-gray-200 mb-2">
          <button
            type="button"
            onClick={() => setAddressMode('address')}
            className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
              addressMode === 'address' ? 'bg-blue-500 text-white' : 'bg-gray-50 text-gray-500'
            }`}
          >
            주소
          </button>
          <button
            type="button"
            onClick={() => setAddressMode('court')}
            className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
              addressMode === 'court' ? 'bg-blue-500 text-white' : 'bg-gray-50 text-gray-500'
            }`}
          >
            법원
          </button>
        </div>

        {addressMode === 'address' ? (
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-2">
              <select
                value={form.sido}
                onChange={(e) => update('sido', e.target.value)}
                className={inputClass}
              >
                <option value="">시/도 전체</option>
                {SIDO_LIST.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
              <input
                type="text"
                placeholder="시/군/구"
                value={form.sigungu}
                onChange={(e) => update('sigungu', e.target.value)}
                className={inputClass}
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input
                type="text"
                placeholder="읍/면/동"
                value={form.dong}
                onChange={(e) => update('dong', e.target.value)}
                className={inputClass}
              />
              <input
                type="text"
                placeholder="세부주소 (건물명/지번)"
                value={form.addressDetail}
                onChange={(e) => update('addressDetail', e.target.value)}
                className={inputClass}
              />
            </div>
          </div>
        ) : (
          <input
            type="text"
            placeholder="법원명"
            value={form.courtName}
            onChange={(e) => update('courtName', e.target.value)}
            className={inputClass}
          />
        )}
      </div>

      <SearchAccordionSection title="물건정보">
        <div>
          <span className={labelClass}>사건번호</span>
          <div className="flex items-center gap-1">
            <input
              type="text"
              placeholder="연도"
              value={form.caseYear}
              onChange={(e) => update('caseYear', e.target.value)}
              className={inputClass}
            />
            <span className="text-xs text-gray-400 shrink-0">타경</span>
            <input
              type="text"
              placeholder="번호"
              value={form.caseNo}
              onChange={(e) => update('caseNo', e.target.value)}
              className={inputClass}
            />
          </div>
        </div>

        <div>
          <span className={labelClass}>진행상태</span>
          <input
            type="text"
            placeholder="예: 유찰, 신건"
            value={form.status}
            onChange={(e) => update('status', e.target.value)}
            className={inputClass}
          />
        </div>

        <div>
          <span className={labelClass}>
            물건종류
            {propertyCategories.length >= 2 && (
              <span className="text-amber-500 font-normal"> (2개 이상 선택 시 검색에는 미반영 — API 연동 예정)</span>
            )}
          </span>
          <PropertyTypeTree selected={propertyCategories} onChange={setPropertyCategories} />
        </div>
      </SearchAccordionSection>

      <SearchAccordionSection title="가격 조건">
        <PriceRangeSelect
          label="감정가"
          minValue={form.appraisalMin}
          maxValue={form.appraisalMax}
          onMinChange={(v) => update('appraisalMin', v)}
          onMaxChange={(v) => update('appraisalMax', v)}
          selectClassName={inputClass}
          labelClassName={labelClass}
        />
        <PriceRangeSelect
          label="최저입찰가"
          minValue={form.bidPriceMin}
          maxValue={form.bidPriceMax}
          onMinChange={(v) => update('bidPriceMin', v)}
          onMaxChange={(v) => update('bidPriceMax', v)}
          selectClassName={inputClass}
          labelClassName={labelClass}
        />
        <div>
          <span className={labelClass}>감정가 대비율 (최저가율)</span>
          <div className="grid grid-cols-2 gap-2">
            <select
              value={form.bidRateMin}
              onChange={(e) => update('bidRateMin', e.target.value)}
              className={inputClass}
            >
              <option value="">최소 선택 안함</option>
              {BID_RATE_OPTIONS.map((v) => (
                <option key={`brmin-${v}`} value={v}>최소 {v}%</option>
              ))}
            </select>
            <select
              value={form.bidRateMax}
              onChange={(e) => update('bidRateMax', e.target.value)}
              className={inputClass}
            >
              <option value="">최대 선택 안함</option>
              {BID_RATE_OPTIONS.map((v) => (
                <option key={`brmax-${v}`} value={v}>최대 {v}%</option>
              ))}
            </select>
          </div>
        </div>
      </SearchAccordionSection>

      <SearchAccordionSection title="일정 · 유찰횟수">
        <div>
          <span className={labelClass}>매각기일</span>
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={form.auctionDateFrom}
              onChange={(e) => update('auctionDateFrom', e.target.value)}
              className={inputClass}
            />
            <span className="text-xs text-gray-400">~</span>
            <input
              type="date"
              value={form.auctionDateTo}
              onChange={(e) => update('auctionDateTo', e.target.value)}
              className={inputClass}
            />
          </div>
          <div className="flex gap-1 mt-1.5">
            <button
              type="button"
              onClick={() => setQuickAuctionDate(0)}
              className="rounded-full px-2.5 py-1 text-xs font-medium bg-blue-50 text-blue-500"
            >
              당일
            </button>
            <button
              type="button"
              onClick={() => setQuickAuctionDate(7)}
              className="rounded-full px-2.5 py-1 text-xs font-medium bg-blue-50 text-blue-500"
            >
              +7
            </button>
            <button
              type="button"
              onClick={() => setQuickAuctionDate(14)}
              className="rounded-full px-2.5 py-1 text-xs font-medium bg-blue-50 text-blue-500"
            >
              +14
            </button>
            <button
              type="button"
              onClick={() => setQuickAuctionDate(null)}
              className="rounded-full px-2.5 py-1 text-xs font-medium bg-gray-100 text-gray-500"
            >
              X
            </button>
          </div>
        </div>

        <div>
          <span className={labelClass}>유찰횟수</span>
          <div className="grid grid-cols-2 gap-2">
            <select
              value={form.failCountMin}
              onChange={(e) => update('failCountMin', e.target.value)}
              className={inputClass}
            >
              <option value="">최소 선택 안함</option>
              {FAIL_COUNT_OPTIONS.map((v) => (
                <option key={`fcmin-${v}`} value={v}>최소 {v}회</option>
              ))}
            </select>
            <select
              value={form.failCountMax}
              onChange={(e) => update('failCountMax', e.target.value)}
              className={inputClass}
            >
              <option value="">최대 선택 안함</option>
              {FAIL_COUNT_OPTIONS.map((v) => (
                <option key={`fcmax-${v}`} value={v}>최대 {v}회</option>
              ))}
            </select>
          </div>
        </div>
      </SearchAccordionSection>

      <SearchAccordionSection title="면적 조건" defaultOpen={false}>
        <p className="text-xs text-amber-500">
          건물면적/토지면적은 auction_item에 대응 컬럼이 없어 API 연동 예정입니다 (TODO)
        </p>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <span className={labelClass}>건물면적 (㎡)</span>
            <div className="flex items-center gap-1">
              <input
                type="number"
                min={0}
                placeholder="최소"
                value={form.buildingAreaMin}
                onChange={(e) => update('buildingAreaMin', e.target.value)}
                className={inputClass}
              />
              <span className="text-xs text-gray-400">~</span>
              <input
                type="number"
                min={0}
                placeholder="최대"
                value={form.buildingAreaMax}
                onChange={(e) => update('buildingAreaMax', e.target.value)}
                className={inputClass}
              />
            </div>
          </div>
          <div>
            <span className={labelClass}>토지면적 (㎡)</span>
            <div className="flex items-center gap-1">
              <input
                type="number"
                min={0}
                placeholder="최소"
                value={form.landAreaMin}
                onChange={(e) => update('landAreaMin', e.target.value)}
                className={inputClass}
              />
              <span className="text-xs text-gray-400">~</span>
              <input
                type="number"
                min={0}
                placeholder="최대"
                value={form.landAreaMax}
                onChange={(e) => update('landAreaMax', e.target.value)}
                className={inputClass}
              />
            </div>
          </div>
        </div>
      </SearchAccordionSection>

      <SearchAccordionSection title="특수조건" defaultOpen={false}>
        <p className="text-xs text-amber-500">
          아래 적용방식(라디오)과 특수조건 매칭은 API 연동 예정입니다 (TODO)
        </p>
        <div>
          <span className={labelClass}>적용방식</span>
          <div className="flex flex-col gap-1.5">
            {SPECIAL_SEARCH_TYPES.map((opt) => (
              <label key={opt.value} className="flex items-center gap-1.5 text-sm text-gray-600">
                <input
                  type="radio"
                  name="specialSearchType"
                  checked={specialSearchType === opt.value}
                  onChange={() => setSpecialSearchType(opt.value)}
                />
                {opt.label}
              </label>
            ))}
          </div>
        </div>
        <div>
          <span className={labelClass}>특수조건 항목</span>
          <div className="grid grid-cols-2 gap-y-1">
            {SPECIAL_CONDITIONS.map((cond) => (
              <label key={cond.value} className="flex items-center gap-1.5 text-sm text-gray-600">
                <input
                  type="checkbox"
                  checked={form.specialConditions.includes(cond.value)}
                  onChange={() => toggleSpecialCondition(cond.value)}
                />
                {cond.label}
              </label>
            ))}
          </div>
        </div>
      </SearchAccordionSection>

      <div className="py-4">
        <button
          type="button"
          onClick={handleSearch}
          className="w-full rounded-xl bg-blue-500 py-2.5 text-sm font-medium text-white active:bg-blue-600 transition-colors"
        >
          검색
        </button>
      </div>
    </div>
  )
}
