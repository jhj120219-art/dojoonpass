'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import { useState } from 'react'
import type { SearchQueryParams } from './types'
import PriceRangeSelect from '@/components/PriceRangeSelect'
import RangeSelect from '@/components/RangeSelect'
import SearchAccordionSection from '@/components/SearchAccordionSection'
import PropertyTypeTree from '@/components/PropertyTypeTree'

const SIDO_LIST = [
  '서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종',
  '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주',
]

// config/courts.py(ALL_COURTS)의 실제 법원 마스터 데이터를 그대로 옮겼다 — 같은 목록을
// 두 곳에서 관리하므로, config/courts.py가 바뀌면 이 목록도 함께 갱신해야 한다.
// court_name은 Backend에서 LIKE 매칭이라 정식 법원명을 그대로 보내도 기존 계약과 호환된다.
type CourtInfo = { name: string; region: string }
const COURT_LIST: CourtInfo[] = [
  { name: '서울중앙지방법원', region: '서울' },
  { name: '서울동부지방법원', region: '서울' },
  { name: '서울서부지방법원', region: '서울' },
  { name: '서울남부지방법원', region: '서울' },
  { name: '서울북부지방법원', region: '서울' },
  { name: '의정부지방법원', region: '경기' },
  { name: '고양지원', region: '경기' },
  { name: '남양주지원', region: '경기' },
  { name: '인천지방법원', region: '인천' },
  { name: '부천지원', region: '인천' },
  { name: '수원지방법원', region: '경기' },
  { name: '성남지원', region: '경기' },
  { name: '여주지원', region: '경기' },
  { name: '평택지원', region: '경기' },
  { name: '안산지원', region: '경기' },
  { name: '안양지원', region: '경기' },
  { name: '춘천지방법원', region: '강원' },
  { name: '강릉지원', region: '강원' },
  { name: '원주지원', region: '강원' },
  { name: '속초지원', region: '강원' },
  { name: '영월지원', region: '강원' },
  { name: '청주지방법원', region: '충북' },
  { name: '충주지원', region: '충북' },
  { name: '제천지원', region: '충북' },
  { name: '영동지원', region: '충북' },
  { name: '대전지방법원', region: '대전' },
  { name: '홍성지원', region: '충남' },
  { name: '논산지원', region: '충남' },
  { name: '천안지원', region: '충남' },
  { name: '공주지원', region: '충남' },
  { name: '서산지원', region: '충남' },
  { name: '대구지방법원', region: '대구' },
  { name: '안동지원', region: '경북' },
  { name: '경주지원', region: '경북' },
  { name: '김천지원', region: '경북' },
  { name: '상주지원', region: '경북' },
  { name: '의성지원', region: '경북' },
  { name: '영덕지원', region: '경북' },
  { name: '포항지원', region: '경북' },
  { name: '대구서부지원', region: '대구' },
  { name: '부산지방법원', region: '부산' },
  { name: '부산동부지원', region: '부산' },
  { name: '부산서부지원', region: '부산' },
  { name: '울산지방법원', region: '울산' },
  { name: '창원지방법원', region: '경남' },
  { name: '마산지원', region: '경남' },
  { name: '진주지원', region: '경남' },
  { name: '통영지원', region: '경남' },
  { name: '밀양지원', region: '경남' },
  { name: '거창지원', region: '경남' },
  { name: '광주지방법원', region: '광주' },
  { name: '목포지원', region: '전남' },
  { name: '장흥지원', region: '전남' },
  { name: '순천지원', region: '전남' },
  { name: '해남지원', region: '전남' },
  { name: '전주지방법원', region: '전북' },
  { name: '군산지원', region: '전북' },
  { name: '정읍지원', region: '전북' },
  { name: '남원지원', region: '전북' },
  { name: '제주지방법원', region: '제주' },
]
const COURT_REGIONS = Array.from(new Set(COURT_LIST.map((c) => c.region)))

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

type SpecialSearchType = (typeof SPECIAL_SEARCH_TYPES)[number]['value']

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

// buildSearchQuery()가 생성하는 쿼리 파라미터 중 검색조건(필터)에 해당하는 키 전체.
// sort_by/sort_order/page/size는 검색조건이 아니라 표시 설정이므로 여기 포함하지 않는다
// (SortBar.tsx/Pagination.tsx가 별도로 관리) — SearchForm은 이 키들의 값이 실제로
// 바뀔 때만 폼을 URL 기준으로 다시 초기화해야, 정렬/페이지 이동만으로 아코디언 열림상태 등
// 폼의 UI 상태가 불필요하게 리셋되지 않는다.
export const FILTER_PARAM_KEYS = [
  'sido', 'sigungu', 'dong', 'address_detail', 'court_name', 'case_no',
  'property_type', 'status', 'min_fail_count', 'max_fail_count',
  'auction_date_from', 'auction_date_to', 'min_appraisal', 'max_appraisal',
  'min_bid_price', 'max_bid_price', 'min_bid_rate', 'max_bid_rate',
  'min_building_area', 'max_building_area', 'min_land_area', 'max_land_area',
  'special_conditions',
] as const

type SearchParamsLike = ReturnType<typeof useSearchParams>

// 위 필터 키들만으로 만든 안정적인 문자열. SearchFormInner의 React key로 사용해
// "필터 조건이 실제로 바뀐 시점에만 폼 상태를 URL에서 다시 읽어온다"를 구현한다.
function filterKeyFromParams(searchParams: SearchParamsLike): string {
  return FILTER_PARAM_KEYS.map((key) => `${key}=${searchParams.get(key) ?? ''}`).join('&')
}

// bid_rate는 URL/API에는 0~1 비율로 실리지만 폼에는 %(BID_RATE_OPTIONS, 10 단위) 문자열로 표시한다.
// SearchForm.buildSearchQuery()의 "/100" 변환을 역으로 되돌린다.
function ratioToPercentString(ratio: string | null): string {
  if (!ratio) return ''
  const num = Number(ratio)
  if (Number.isNaN(num)) return ''
  return String(Math.round(num * 100))
}

// case_no는 buildSearchQuery()에서 `${caseYear}타경${caseNo}` 형태로 합쳐 전송된다.
// 그 포맷을 역으로 분리한다. "타경"이 없으면(연도 없이 번호만 입력했던 경우) 전체를 caseNo로 취급한다.
function splitCaseNo(caseNo: string | null): { caseYear: string; caseNo: string } {
  if (!caseNo) return { caseYear: '', caseNo: '' }
  const match = caseNo.match(/^(.*)타경(.*)$/)
  if (!match) return { caseYear: '', caseNo }
  return { caseYear: match[1], caseNo: match[2] }
}

function parseFormState(searchParams: SearchParamsLike): SearchFormState {
  const { caseYear, caseNo } = splitCaseNo(searchParams.get('case_no'))
  const specialConditionsRaw = searchParams.get('special_conditions')
  return {
    sido: searchParams.get('sido') ?? '',
    sigungu: searchParams.get('sigungu') ?? '',
    dong: searchParams.get('dong') ?? '',
    addressDetail: searchParams.get('address_detail') ?? '',
    courtName: searchParams.get('court_name') ?? '',
    caseYear,
    caseNo,
    status: searchParams.get('status') ?? '',
    failCountMin: searchParams.get('min_fail_count') ?? '',
    failCountMax: searchParams.get('max_fail_count') ?? '',
    auctionDateFrom: searchParams.get('auction_date_from') ?? '',
    auctionDateTo: searchParams.get('auction_date_to') ?? '',
    appraisalMin: searchParams.get('min_appraisal') ?? '0',
    appraisalMax: searchParams.get('max_appraisal') ?? '0',
    bidPriceMin: searchParams.get('min_bid_price') ?? '0',
    bidPriceMax: searchParams.get('max_bid_price') ?? '0',
    buildingAreaMin: searchParams.get('min_building_area') ?? '',
    buildingAreaMax: searchParams.get('max_building_area') ?? '',
    landAreaMin: searchParams.get('min_land_area') ?? '',
    landAreaMax: searchParams.get('max_land_area') ?? '',
    bidRateMin: ratioToPercentString(searchParams.get('min_bid_rate')),
    bidRateMax: ratioToPercentString(searchParams.get('max_bid_rate')),
    specialConditions: specialConditionsRaw ? specialConditionsRaw.split(',').filter(Boolean) : [],
  }
}

// court_name이 있으면 법원 탭, 없으면 주소 탭으로 복원한다. addressMode 자체는 URL에
// 별도 파라미터로 실리지 않으므로(주소/법원 탭은 court_name 유무로만 구분 가능) 이 방식이 유일한 근거다.
function parseAddressMode(searchParams: SearchParamsLike): 'address' | 'court' {
  return searchParams.get('court_name') ? 'court' : 'address'
}

// property_type은 buildSearchQuery()에서 선택된 항목 전부가 콤마join되어 전송된다
// (special_conditions와 동일한 URL 인코딩 방식). 역으로 복원할 때도 콤마로 분리한다.
function parsePropertyCategories(searchParams: SearchParamsLike): string[] {
  const propertyType = searchParams.get('property_type')
  return propertyType ? propertyType.split(',').filter(Boolean) : []
}

export default function SearchForm() {
  const searchParams = useSearchParams()
  // 필터 조건이 바뀔 때만 SearchFormInner를 새로 마운트해 URL 기준으로 폼을 재초기화한다.
  // 정렬/페이지 변경(FILTER_PARAM_KEYS에 없는 파라미터)은 key가 그대로라 리마운트되지 않는다.
  return <SearchFormInner key={filterKeyFromParams(searchParams)} searchParams={searchParams} />
}

function SearchFormInner({ searchParams }: { searchParams: SearchParamsLike }) {
  const router = useRouter()
  const [form, setForm] = useState<SearchFormState>(() => parseFormState(searchParams))

  // Tank Auction의 주소선택 toggleBtn(주소/법원)과 동일한 2-way 탭.
  const [addressMode, setAddressMode] = useState<'address' | 'court'>(() => parseAddressMode(searchParams))
  // Tank Auction의 splSrchType 라디오. UI 전용 상태(mock, TODO 참고) — URL에 실리지 않으므로 URL 복원 대상이 아니다.
  const [specialSearchType, setSpecialSearchType] = useState<SpecialSearchType>('0')
  // Tank Auction의 물건종류 체크박스 트리 선택값. TODO 참고(단일 선택시에만 API 연동).
  const [propertyCategories, setPropertyCategories] = useState<string[]>(() => parsePropertyCategories(searchParams))

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

  // Tank Auction의 btnRest("다 시")와 동일한 전체 초기화. 검색은 실행하지 않고
  // 폼 상태만 최초값으로 되돌린다 (API 호출/router.push 없음).
  function resetForm() {
    setForm(INITIAL_STATE)
    setAddressMode('address')
    setSpecialSearchType('0')
    setPropertyCategories([])
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
    // Backend가 콤마로 구분된 여러 property_type을 OR 조건으로 검색한다 (api/v1/search.py 참고).
    if (propertyCategories.length > 0) query.property_type = propertyCategories
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
    // 정렬(sort_by/sort_order)과 페이지 크기(size)는 검색조건이 아니라 표시 설정이므로
    // 새 검색을 실행해도 유지한다. page는 새 검색이므로 항상 1페이지부터 시작(파라미터 생략).
    const sortBy = searchParams.get('sort_by')
    const sortOrder = searchParams.get('sort_order')
    const size = searchParams.get('size')
    if (sortBy) params.set('sort_by', sortBy)
    if (sortOrder) params.set('sort_order', sortOrder)
    if (size) params.set('size', size)
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
      <div className="pt-4 pb-3 border-b border-gray-100">
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
          <select
            value={form.courtName}
            onChange={(e) => update('courtName', e.target.value)}
            className={inputClass}
          >
            <option value="">법원 전체</option>
            {COURT_REGIONS.map((region) => (
              <optgroup key={region} label={region}>
                {COURT_LIST.filter((c) => c.region === region).map((c) => (
                  <option key={c.name} value={c.name}>{c.name}</option>
                ))}
              </optgroup>
            ))}
          </select>
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
          <span className={labelClass}>물건종류</span>
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
        <RangeSelect
          label="감정가 대비율 (최저가율)"
          minValue={form.bidRateMin}
          maxValue={form.bidRateMax}
          onMinChange={(v) => update('bidRateMin', v)}
          onMaxChange={(v) => update('bidRateMax', v)}
          options={BID_RATE_OPTIONS.map((v) => ({ value: v, label: `${v}%` }))}
          placeholder="선택 안함"
          selectClassName={inputClass}
          labelClassName={labelClass}
        />
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

        <RangeSelect
          label="유찰횟수"
          minValue={form.failCountMin}
          maxValue={form.failCountMax}
          onMinChange={(v) => update('failCountMin', v)}
          onMaxChange={(v) => update('failCountMax', v)}
          options={FAIL_COUNT_OPTIONS.map((v) => ({ value: v, label: `${v}회` }))}
          placeholder="선택 안함"
          selectClassName={inputClass}
          labelClassName={labelClass}
        />
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

      <div className="py-4 flex gap-2">
        <button
          type="button"
          onClick={resetForm}
          className="shrink-0 rounded-xl bg-gray-100 px-4 py-2.5 text-sm font-medium text-gray-500 active:bg-gray-200 transition-colors"
        >
          초기화
        </button>
        <button
          type="button"
          onClick={handleSearch}
          className="flex-1 rounded-xl bg-blue-500 py-2.5 text-sm font-medium text-white active:bg-blue-600 transition-colors"
        >
          검색
        </button>
      </div>
    </div>
  )
}
