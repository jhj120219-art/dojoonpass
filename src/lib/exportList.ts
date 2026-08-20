/**
 * 마이리스트(관심물건) 내보내기 — **형식 중립** (2026-08-20 Sprint 227).
 *
 * ## 무엇을 만들고, 무엇을 만들지 않는가
 *
 * `docs/SPRINT219B_MYLIST_EXPORT_FEASIBILITY.md` 가 실측으로 정리한 결론을 그대로 따른다.
 *
 *   만든다      CSV 내려받기 / 탭 구분 클립보드 복사 — 우리 필드를 **그대로** 낸다
 *   만들지 않는다  지지옥션·탱크옥션 등 **상대 서비스 전용 포맷**
 *
 * 상대의 실제 입력 형식은 **확인하지 못했다**(사람의 확인이 필요하다).
 * 추측해서 만들면 "붙여넣었는데 안 들어간다"가 되고, 그 실패는 우리 쪽에서 보이지 않는다 —
 * 이 저장소가 반복해서 경계해 온 "조용한 실패"의 전형이다.
 * 사람이 열에서 골라 쓸 수 있게 **원본 그대로** 내는 것이 지금 할 수 있는 최선이다.
 *
 * ## 병합 사건을 쪼개지 않는다
 *
 * 실측: `auction_item` 1,876행 중 **425행(22.7%)** 의 `case_no` 가
 * `2008타경25092 / 2015타경19958` 같은 **병합 사건**이다.
 * 어느 쪽이 대표인지는 법원 원천이 정하지 않았으므로 **우리가 정하면 안 된다.**
 * 원본 문자열을 그대로 내보내고, 판단은 사람에게 남긴다.
 *
 * ## 왜 값을 가공하지 않는가
 *
 * 화면은 `formatPrice()` 로 "3.8억"처럼 줄여 보여 준다. 내보내기는 **숫자 원본**을 낸다 —
 * 축약은 12,900원을 "1만"으로 만들어(-22%) 계산에 쓸 수 없게 만든다
 * (`tests/source-contract.test.mjs` 가 같은 이유로 마이페이지 금액을 지키고 있다).
 */

/** 내보내기가 읽는 최소 계약. 관심물건 API 응답이 이 필드를 준다. */
export type ExportRow = {
  court_name: string | null
  case_no: string
  item_no: string | null
  full_address: string | null
  sido?: string | null
  sigungu?: string | null
  property_type: string | null
  appraisal_price: number | null
  minimum_bid_price: number | null
  auction_date: string | null
  status: string | null
  fail_count: number | null
}

/**
 * 열 정의. **헤더와 값 추출기를 한 곳에 묶어 둔다** — 둘을 따로 적으면 열이 밀려도
 * 아무도 모른다(이 저장소가 CSV 열 불일치를 기본값으로 감추지 말라고 못박은 이유다).
 */
export const COLUMNS: ReadonlyArray<{ header: string; get: (r: ExportRow) => string }> = [
  { header: '법원', get: (r) => str(r.court_name) },
  // 병합 사건은 원본 그대로. 쪼개지 않는다.
  { header: '사건번호', get: (r) => str(r.case_no) },
  { header: '물건번호', get: (r) => str(r.item_no) },
  { header: '물건종류', get: (r) => str(r.property_type) },
  {
    header: '소재지',
    get: (r) =>
      str(r.full_address) || [r.sido, r.sigungu].filter(Boolean).join(' '),
  },
  { header: '감정가', get: (r) => num(r.appraisal_price) },
  { header: '최저입찰가', get: (r) => num(r.minimum_bid_price) },
  { header: '매각기일', get: (r) => str(r.auction_date) },
  { header: '상태', get: (r) => str(r.status) },
  { header: '유찰횟수', get: (r) => num(r.fail_count) },
]

/**
 * 값이 없으면 **빈 칸**이다. `'-'` 나 `0` 같은 대체값을 넣지 않는다 —
 * "값이 없음"과 "값이 0"은 다른 사실이고, 표에서 그 둘이 섞이면 되돌릴 수 없다.
 */
function str(v: string | null | undefined): string {
  return v == null ? '' : String(v)
}

function num(v: number | null | undefined): string {
  // 0 은 유효한 값이다(유찰 0회). `!v` 로 판정하면 0 이 빈 칸이 되어 사실이 바뀐다.
  return v == null || Number.isNaN(v) ? '' : String(v)
}

/**
 * CSV 한 칸을 RFC 4180 규칙으로 감싼다.
 *
 * 감싸야 하는 경우: 구분자·큰따옴표·개행이 들어 있을 때. 큰따옴표는 두 번 써서 이스케이프한다.
 * 주소에는 쉼표가 흔하고(`서울특별시 종로구 ..., 2층202호`) 상태 문자열에도 들어갈 수 있어
 * **실제로 걸리는 경우다.**
 *
 * 앞뒤 공백이 있으면 스프레드시트가 잘라 버리는 구현이 있어 그때도 감싼다.
 */
function csvCell(value: string, delimiter: string): string {
  const needsQuote =
    value.includes(delimiter) ||
    value.includes('"') ||
    value.includes('\n') ||
    value.includes('\r') ||
    value !== value.trim()
  if (!needsQuote) return value
  return '"' + value.replace(/"/g, '""') + '"'
}

/** 열 정의로부터 한 행을 만든다. 헤더와 같은 순서·같은 개수가 보장된다. */
function rowCells(row: ExportRow): string[] {
  return COLUMNS.map((c) => c.get(row))
}

export type BuildOptions = {
  /** 기본은 CSV(`,`). 클립보드용 탭 구분은 `'\t'`. */
  delimiter?: string
  /** 헤더 줄을 넣을지. 클립보드로 스프레드시트에 붙일 때는 보통 넣는다. */
  header?: boolean
}

/**
 * 구분자 기반 텍스트를 만든다.
 *
 * 줄바꿈은 `\r\n` 이다 — RFC 4180 이고, Windows 엑셀과 구글 시트 둘 다 안전하다.
 * 목록이 비어도 **헤더는 낸다**: 빈 파일은 "실패"와 구별되지 않지만,
 * 헤더만 있는 파일은 "담은 물건이 없다"를 분명히 말한다.
 */
export function buildDelimitedText(rows: ExportRow[], options: BuildOptions = {}): string {
  const delimiter = options.delimiter ?? ','
  const withHeader = options.header ?? true
  const lines: string[] = []
  if (withHeader) {
    lines.push(COLUMNS.map((c) => csvCell(c.header, delimiter)).join(delimiter))
  }
  for (const row of rows) {
    lines.push(rowCells(row).map((v) => csvCell(v, delimiter)).join(delimiter))
  }
  return lines.join('\r\n')
}

/** 내려받기용 CSV. */
export function buildCsv(rows: ExportRow[]): string {
  return buildDelimitedText(rows, { delimiter: ',', header: true })
}

/** 클립보드용 탭 구분(TSV). 스프레드시트에 그대로 붙는다. */
export function buildTsv(rows: ExportRow[]): string {
  return buildDelimitedText(rows, { delimiter: '\t', header: true })
}

/**
 * 엑셀이 한글을 깨뜨리지 않도록 **UTF-8 BOM** 을 붙인다.
 *
 * BOM 이 없으면 한국어 Windows 의 엑셀이 CSV 를 cp949 로 읽어 소재지·법원명이 전부 깨진다.
 * 이 저장소가 "BOM 파일을 utf-8 로 읽고 조용히 넘어가지 말라"고 적어 둔 것과 같은 사안의
 * **쓰는 쪽**이다 — 읽는 쪽이 BOM 을 기대하므로 쓸 때 붙여 준다.
 * (구글 시트·LibreOffice·`utf-8-sig` 로 읽는 파이썬은 BOM 을 알아서 무시한다.)
 */
export const UTF8_BOM = '﻿'

/** 파일명. 콜론 등 파일명에 못 쓰는 문자를 만들지 않는다. */
export function exportFileName(prefix: string, isoDate: string): string {
  const day = (isoDate || '').slice(0, 10) || 'unknown'
  return `${prefix}_${day}.csv`
}
