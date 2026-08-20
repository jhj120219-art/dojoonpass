// ================================================================
// 마이리스트 내보내기 순수 로직 회귀 (2026-08-20 Sprint 227 신설)
//
// 이 저장소의 프런트 검사는 지금까지 **소스 문자열 대조**(source-contract)와
// **HTTP 블랙박스**(frontend-contract) 둘뿐이었다. 내보내기는 값을 만드는 순수 함수라
// 그 둘로는 "쉼표가 든 주소를 제대로 감쌌는가" 같은 것을 볼 수 없다.
//
// Node 24 는 TypeScript 를 **기본으로 타입 스트리핑**해서 실행한다
// (`process.features.typescript === 'strip'` 로 확인). 그래서 새 라이브러리·번들러 없이
// `.ts` 를 그대로 import 해 실제로 호출한다 —
// docs/CLAUDE.md 의 "새 라이브러리 설치는 승인 필요"를 지키면서 진짜 실행 검증을 얻는다.
//
// 실행:  npm run test:frontend   (서버 불필요)
// ================================================================

import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  COLUMNS,
  buildCsv,
  buildTsv,
  buildDelimitedText,
  exportFileName,
  UTF8_BOM,
} from '../src/lib/exportList.ts'

/** 실제 DB 에서 관측된 모양을 그대로 본뜬 표본(SPRINT219B 실측 기준). */
const ROW = {
  court_name: '서울중앙지방법원',
  case_no: '2024타경117502',
  item_no: '1',
  full_address: '서울특별시 종로구 성균관로7길 37(명륜3가) 2층202호',
  sido: '서울',
  sigungu: '종로구',
  property_type: '연립주택,다세대,빌라', // ← 쉼표가 **값 안에** 있다
  appraisal_price: 380000000,
  minimum_bid_price: 304000000,
  auction_date: '2026-08-19',
  status: '유찰 8회',
  fail_count: 8,
}

/** 실측 22.7% 를 차지하는 병합 사건. */
const MERGED = {
  ...ROW,
  case_no: '2008타경25092 / 2015타경19958',
  item_no: '2',
}

function lines(text) {
  return text.split('\r\n')
}

describe('열 정의', () => {
  test('헤더와 값 추출기가 한 곳에 묶여 있다', () => {
    assert.ok(COLUMNS.length >= 8, `열이 ${COLUMNS.length}개뿐입니다`)
    for (const c of COLUMNS) {
      assert.equal(typeof c.header, 'string')
      assert.equal(typeof c.get, 'function')
    }
  })

  test('모든 행이 헤더와 **같은 칸 수**를 낸다', () => {
    // 열이 밀리면 감정가 자리에 매각기일이 들어간다 — 조용히 틀린 표가 된다.
    const text = buildCsv([ROW, MERGED, {}])
    const counts = lines(text).map((l) => splitCsv(l).length)
    assert.deepEqual(
      [...new Set(counts)],
      [COLUMNS.length],
      `칸 수가 행마다 다릅니다: ${JSON.stringify(counts)}`
    )
  })
})

describe('CSV 이스케이프 (RFC 4180)', () => {
  test('값 안의 쉼표는 따옴표로 감싼다', () => {
    const body = lines(buildCsv([ROW]))[1]
    assert.ok(
      body.includes('"연립주택,다세대,빌라"'),
      `쉼표가 감싸지지 않았습니다: ${body}`
    )
    // 감싸지 않으면 열이 2칸 밀린다 — 그것을 직접 확인한다.
    assert.equal(splitCsv(body).length, COLUMNS.length)
  })

  test('값 안의 큰따옴표는 두 번 써서 이스케이프한다', () => {
    const text = buildCsv([{ ...ROW, status: '특별매각조건 "보증금 20%"' }])
    const body = lines(text)[1]
    assert.ok(body.includes('""보증금 20%""'), body)
    assert.equal(splitCsv(body).length, COLUMNS.length)
  })

  test('값 안의 개행이 행을 쪼개지 않는다', () => {
    const text = buildCsv([{ ...ROW, full_address: '서울시\n종로구' }])
    // 따옴표 안의 개행은 한 행이다. 헤더 1 + 데이터 1 = 물리적으로는 3줄이지만
    // 파싱하면 2행이어야 한다.
    assert.equal(parseCsvRows(text).length, 2)
    assert.equal(parseCsvRows(text)[1][4], '서울시\n종로구')
  })

  test('구분자가 없는 평범한 값은 감싸지 않는다(불필요한 따옴표 없음)', () => {
    const body = lines(buildCsv([{ ...ROW, property_type: '아파트' }]))[1]
    assert.ok(body.includes(',아파트,'), body)
  })
})

describe('값의 의미를 바꾸지 않는다', () => {
  test('가격은 축약하지 않고 숫자 원본을 낸다', () => {
    const cells = parseCsvRows(buildCsv([ROW]))[1]
    assert.ok(cells.includes('380000000'), cells.join('|'))
    assert.ok(cells.includes('304000000'), cells.join('|'))
    // "3.8억" 같은 축약이 들어가면 계산에 못 쓴다.
    assert.ok(!cells.some((c) => c.includes('억')), cells.join('|'))
  })

  test('병합 사건을 쪼개지 않는다', () => {
    const cells = parseCsvRows(buildCsv([MERGED]))[1]
    assert.ok(
      cells.includes('2008타경25092 / 2015타경19958'),
      `병합 사건이 변형됐습니다: ${cells.join('|')}`
    )
  })

  test('유찰 0회는 빈 칸이 아니라 0 이다', () => {
    // `!v` 로 판정하면 0 이 빈 칸이 되어 "유찰 없음"이 "모름"으로 바뀐다.
    const cells = parseCsvRows(buildCsv([{ ...ROW, fail_count: 0 }]))[1]
    const idx = COLUMNS.findIndex((c) => c.header === '유찰횟수')
    assert.equal(cells[idx], '0')
  })

  test('값이 없으면 대체값이 아니라 빈 칸이다', () => {
    const cells = parseCsvRows(buildCsv([{ ...ROW, court_name: null, status: null }]))[1]
    const courtIdx = COLUMNS.findIndex((c) => c.header === '법원')
    const statusIdx = COLUMNS.findIndex((c) => c.header === '상태')
    assert.equal(cells[courtIdx], '')
    assert.equal(cells[statusIdx], '')
    // '-' 나 '0' 으로 채우면 "없음"과 "그 값"이 섞인다.
    assert.ok(!cells.includes('-'), cells.join('|'))
  })

  test('full_address 가 없으면 시/도 + 시/군/구로 채운다', () => {
    const cells = parseCsvRows(buildCsv([{ ...ROW, full_address: null }]))[1]
    const idx = COLUMNS.findIndex((c) => c.header === '소재지')
    assert.equal(cells[idx], '서울 종로구')
  })
})

describe('빈 목록과 파일 이름', () => {
  test('목록이 비어도 헤더는 낸다', () => {
    // 빈 파일은 "실패"와 구별되지 않는다. 헤더만 있는 파일은 "담은 것이 없다"를 말한다.
    const text = buildCsv([])
    const rows = parseCsvRows(text)
    assert.equal(rows.length, 1)
    assert.deepEqual(rows[0], COLUMNS.map((c) => c.header))
  })

  test('엑셀이 한글을 깨뜨리지 않도록 BOM 상수를 제공한다', () => {
    assert.equal(UTF8_BOM.charCodeAt(0), 0xfeff)
    assert.equal(UTF8_BOM.length, 1)
  })

  test('파일 이름에 파일명 금지 문자가 없다', () => {
    const name = exportFileName('관심물건', '2026-08-20T09:12:33.000Z')
    assert.equal(name, '관심물건_2026-08-20.csv')
    assert.ok(!/[:*?"<>|/\\]/.test(name), name)
  })
})

describe('클립보드용 TSV', () => {
  test('탭으로 구분한다', () => {
    const body = buildTsv([ROW]).split('\r\n')[1]
    assert.ok(body.includes('\t'), body)
    assert.equal(body.split('\t').length >= COLUMNS.length, true)
  })

  test('탭 구분에서는 쉼표를 감싸지 않는다(불필요한 따옴표가 붙지 않는다)', () => {
    // 스프레드시트에 붙일 때 따옴표가 그대로 보이면 안 된다.
    const body = buildTsv([ROW]).split('\r\n')[1]
    assert.ok(body.includes('연립주택,다세대,빌라'), body)
    assert.ok(!body.includes('"연립주택'), body)
  })

  test('값에 탭이 들어 있으면 탭 구분에서도 감싼다', () => {
    const body = buildDelimitedText([{ ...ROW, status: 'a\tb' }], {
      delimiter: '\t',
    }).split('\r\n')[1]
    assert.ok(body.includes('"a\tb"'), JSON.stringify(body))
  })
})

// ---------------------------------------------------------------------------
// 검사용 CSV 파서.
//
// ★ 검사 도구 자체를 known-good 표본으로 먼저 검증한다 — 파서가 틀리면 위의 모든 단언이
//   거짓 신호가 된다(이 저장소가 여러 번 겪은 함정이다).
// ---------------------------------------------------------------------------
function parseCsvRows(text) {
  const rows = []
  let row = []
  let cell = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"'
          i++
        } else {
          quoted = false
        }
      } else {
        cell += ch
      }
      continue
    }
    if (ch === '"') {
      quoted = true
    } else if (ch === ',') {
      row.push(cell)
      cell = ''
    } else if (ch === '\r' && text[i + 1] === '\n') {
      row.push(cell)
      rows.push(row)
      row = []
      cell = ''
      i++
    } else {
      cell += ch
    }
  }
  row.push(cell)
  rows.push(row)
  return rows
}

function splitCsv(line) {
  return parseCsvRows(line)[0]
}

describe('★ 검사 도구(CSV 파서) 자체 검증', () => {
  test('평범한 행', () => {
    assert.deepEqual(parseCsvRows('a,b,c'), [['a', 'b', 'c']])
  })
  test('감싼 칸 안의 쉼표', () => {
    assert.deepEqual(parseCsvRows('a,"b,c",d'), [['a', 'b,c', 'd']])
  })
  test('이스케이프된 큰따옴표', () => {
    assert.deepEqual(parseCsvRows('a,"say ""hi""",c'), [['a', 'say "hi"', 'c']])
  })
  test('감싼 칸 안의 개행은 행을 쪼개지 않는다', () => {
    assert.deepEqual(parseCsvRows('a,"x\ny",c'), [['a', 'x\ny', 'c']])
  })
  test('여러 행', () => {
    assert.deepEqual(parseCsvRows('a,b\r\nc,d'), [
      ['a', 'b'],
      ['c', 'd'],
    ])
  })
  test('빈 칸을 잃지 않는다', () => {
    assert.deepEqual(parseCsvRows('a,,c'), [['a', '', 'c']])
  })
})
