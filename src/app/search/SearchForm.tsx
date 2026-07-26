'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import type { SearchQueryParams } from './types'

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

type SearchFormState = {
  sido: string
  sigungu: string
  dong: string
  addressDetail: string
  courtName: string
  caseYear: string
  caseNo: string
  propertyType: string
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
  propertyType: '',
  status: '',
  failCountMin: '',
  failCountMax: '',
  auctionDateFrom: '',
  auctionDateTo: '',
  appraisalMin: '',
  appraisalMax: '',
  bidPriceMin: '',
  bidPriceMax: '',
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

  function update<K extends keyof SearchFormState>(key: K, value: SearchFormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
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
    if (form.sido) query.sido = form.sido
    if (form.sigungu) query.sigungu = form.sigungu
    if (form.dong) query.dong = form.dong
    if (form.addressDetail) query.address_detail = form.addressDetail
    if (form.courtName) query.court_name = form.courtName
    if (form.caseYear && form.caseNo) query.case_no = `${form.caseYear}타경${form.caseNo}`
    else if (form.caseNo) query.case_no = form.caseNo
    if (form.propertyType) query.property_type = form.propertyType
    if (form.status) query.status = form.status
    if (form.failCountMin) query.min_fail_count = Number(form.failCountMin)
    if (form.failCountMax) query.max_fail_count = Number(form.failCountMax)
    if (form.auctionDateFrom) query.auction_date_from = form.auctionDateFrom
    if (form.auctionDateTo) query.auction_date_to = form.auctionDateTo
    if (form.appraisalMin) query.min_appraisal = Number(form.appraisalMin)
    if (form.appraisalMax) query.max_appraisal = Number(form.appraisalMax)
    if (form.bidPriceMin) query.min_bid_price = Number(form.bidPriceMin)
    if (form.bidPriceMax) query.max_bid_price = Number(form.bidPriceMax)
    if (form.buildingAreaMin) query.min_building_area = Number(form.buildingAreaMin)
    if (form.buildingAreaMax) query.max_building_area = Number(form.buildingAreaMax)
    if (form.landAreaMin) query.min_land_area = Number(form.landAreaMin)
    if (form.landAreaMax) query.max_land_area = Number(form.landAreaMax)
    // bid_rate는 DB에 0~1 비율로 저장되어 있어 입력받은 %값을 100으로 나눠 전달한다
    if (form.bidRateMin) query.min_bid_rate = Number(form.bidRateMin) / 100
    if (form.bidRateMax) query.max_bid_rate = Number(form.bidRateMax) / 100
    if (form.specialConditions.length > 0) query.special_conditions = form.specialConditions
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
    <div className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100 mb-3 space-y-4">
      {/* 주소 */}
      <div>
        <span className={labelClass}>주소</span>
        <div className="grid grid-cols-2 gap-2 mb-2">
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

      {/* 법원 / 사건번호 */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <span className={labelClass}>법원</span>
          <input
            type="text"
            placeholder="법원명"
            value={form.courtName}
            onChange={(e) => update('courtName', e.target.value)}
            className={inputClass}
          />
        </div>
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
      </div>

      {/* 물건종류 / 진행상태 */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <span className={labelClass}>물건종류</span>
          <input
            type="text"
            placeholder="예: 아파트, 오피스텔"
            value={form.propertyType}
            onChange={(e) => update('propertyType', e.target.value)}
            className={inputClass}
          />
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
      </div>

      {/* 유찰횟수 */}
      <div>
        <span className={labelClass}>유찰횟수</span>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            placeholder="최소"
            value={form.failCountMin}
            onChange={(e) => update('failCountMin', e.target.value)}
            className={inputClass}
          />
          <span className="text-xs text-gray-400">~</span>
          <input
            type="number"
            min={0}
            placeholder="최대"
            value={form.failCountMax}
            onChange={(e) => update('failCountMax', e.target.value)}
            className={inputClass}
          />
        </div>
      </div>

      {/* 매각기일 범위 */}
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
      </div>

      {/* 감정가 범위 */}
      <div>
        <span className={labelClass}>감정가 (원)</span>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            placeholder="최소"
            value={form.appraisalMin}
            onChange={(e) => update('appraisalMin', e.target.value)}
            className={inputClass}
          />
          <span className="text-xs text-gray-400">~</span>
          <input
            type="number"
            min={0}
            placeholder="최대"
            value={form.appraisalMax}
            onChange={(e) => update('appraisalMax', e.target.value)}
            className={inputClass}
          />
        </div>
      </div>

      {/* 최저입찰가 범위 */}
      <div>
        <span className={labelClass}>최저입찰가 (원)</span>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            placeholder="최소"
            value={form.bidPriceMin}
            onChange={(e) => update('bidPriceMin', e.target.value)}
            className={inputClass}
          />
          <span className="text-xs text-gray-400">~</span>
          <input
            type="number"
            min={0}
            placeholder="최대"
            value={form.bidPriceMax}
            onChange={(e) => update('bidPriceMax', e.target.value)}
            className={inputClass}
          />
        </div>
      </div>

      {/* 건물면적 / 토지면적 */}
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

      {/* 감정가 대비율 */}
      <div>
        <span className={labelClass}>감정가 대비율 (%)</span>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            max={100}
            placeholder="최소"
            value={form.bidRateMin}
            onChange={(e) => update('bidRateMin', e.target.value)}
            className={inputClass}
          />
          <span className="text-xs text-gray-400">~</span>
          <input
            type="number"
            min={0}
            max={100}
            placeholder="최대"
            value={form.bidRateMax}
            onChange={(e) => update('bidRateMax', e.target.value)}
            className={inputClass}
          />
        </div>
      </div>

      {/* 특수조건 */}
      <div>
        <span className={labelClass}>특수조건</span>
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

      <button
        type="button"
        onClick={handleSearch}
        className="w-full rounded-xl bg-blue-500 py-2.5 text-sm font-medium text-white active:bg-blue-600 transition-colors"
      >
        검색
      </button>
    </div>
  )
}
