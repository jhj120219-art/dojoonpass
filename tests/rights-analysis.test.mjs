// ================================================================
// 권리분석 ViewModel 회귀 테스트 (Sprint 54 신규)
//
// 왜 지금 생겼나: `rightsAnalysis.ts`는 순수 로직인데도 테스트가 **하나도 없었다**.
// 그 사이 신뢰도 등급이 조용히 뒤집혀 있었다(BUGS #44) — 근거가 가장 빈약한 물건이
// 가장 높은 신뢰도로 표시됐고, HTTP 블랙박스 테스트로는 잡히지 않았다
// (`/properties/[id]`는 로그인 필수 + 클라이언트 렌더).
//
// nav-context.test.mjs와 같은 방식: 순수 함수를 직접 호출해 계약을 고정한다.
// (Node 24 내장 TypeScript type stripping — 새 의존성/빌드 단계 없음)
// ================================================================

import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import {
  assembleRightsAnalysis,
  canCrossCheck,
  mapStatusView,
  mapSpecView,
} from '../src/app/properties/[id]/rightsAnalysis.ts'

// --- 픽스처 -------------------------------------------------------------
// 실제 DB 컬럼명을 그대로 쓴다. 스키마가 바뀌면 여기서 먼저 깨져야 한다.
function summary(overrides = {}) {
  return {
    total_tenant_count: 2,
    is_vacant: 0,
    occupancy_status: '임차인 점유',
    occupancy_difficulty: 'NORMAL',
    risk_level: null,
    estimated_inheritance: null,
    ...overrides,
  }
}

function specTenant(overrides = {}) {
  return {
    tenant_name: '홍길동',
    occupied_area: '전부',
    deposit: 50000000,
    monthly_rent: null,
    move_in_date: '2023-01-01',
    fixed_date: '2023-01-02',
    demand_date: null,
    has_demand: 0,
    source: 'SPEC',
    ...overrides,
  }
}

function statusTenant(overrides = {}) {
  return { ...specTenant(), source: 'STATUS', ...overrides }
}

// ------------------------------------------------------------------------
describe('신뢰도는 "대조됐는가"를 반영한다 (BUGS #44 회귀)', () => {
  // 2026-08-11 실측: 권리 정보원이 하나라도 있는 180건 중 81건(STATUS만 63 + SPEC만 18)이
  // 정보원 1개짜리였고, 전부 HIGH로 표시되고 있었다. 바로 옆 경고문과 정면으로 모순됐다.
  test('현황조사서만 있으면 HIGH가 아니다', () => {
    const vm = assembleRightsAnalysis(summary(), [], false)
    assert.deepEqual(vm.sources, ['STATUS'])
    assert.notEqual(vm.confidence, 'HIGH', '대조 상대가 없는데 신뢰도 HIGH로 표시됩니다')
    assert.equal(vm.confidence, 'MEDIUM')
  })

  test('명세서만 있으면 HIGH가 아니다', () => {
    const vm = assembleRightsAnalysis(null, [specTenant()], true)
    assert.deepEqual(vm.sources, ['SPEC'])
    assert.notEqual(vm.confidence, 'HIGH', '대조 상대가 없는데 신뢰도 HIGH로 표시됩니다')
    assert.equal(vm.confidence, 'MEDIUM')
  })

  test('정보원이 아예 없어도 HIGH가 아니다', () => {
    const vm = assembleRightsAnalysis(null, [], false)
    assert.deepEqual(vm.sources, [])
    assert.equal(vm.confidence, 'MEDIUM')
  })

  test('두 정보원이 일치할 때만 HIGH', () => {
    // 현황조사서 2명 / 명세서 2명 -> 대조 성공, 일치
    const vm = assembleRightsAnalysis(
      summary({ total_tenant_count: 2 }),
      [specTenant({ tenant_name: 'A' }), specTenant({ tenant_name: 'B' })],
      true
    )
    assert.deepEqual(vm.sources, ['STATUS', 'SPEC'])
    assert.equal(vm.conflicts.length, 0)
    assert.equal(vm.confidence, 'HIGH')
  })

  test('신뢰도 HIGH와 "정보 없음" 경고는 동시에 나올 수 없다', () => {
    // 화면에 실제로 보였던 모순을 계약으로 고정한다.
    const cases = [
      assembleRightsAnalysis(summary(), [], false),
      assembleRightsAnalysis(summary(), [], true),
      assembleRightsAnalysis(null, [specTenant()], true),
      assembleRightsAnalysis(null, [], false),
      assembleRightsAnalysis(summary({ total_tenant_count: 2 }), [specTenant(), specTenant()], true),
    ]
    for (const vm of cases) {
      const missing = vm.warnings.filter(
        (w) => w.code === 'MISSING_SPEC' || w.code === 'SPEC_NOT_PARSED' || w.code === 'MISSING_STATUS'
      )
      if (vm.confidence === 'HIGH') {
        assert.equal(
          missing.length,
          0,
          `신뢰도 HIGH인데 정보원 누락 경고가 함께 표시됩니다: ${missing.map((w) => w.code).join(',')}`
        )
      }
    }
  })
})

describe('충돌 등급은 기존 의미를 유지한다', () => {
  test('공실(0명) vs 명세서 임차인 있음 -> DIRECT_CONFLICT / LOW', () => {
    const vm = assembleRightsAnalysis(summary({ total_tenant_count: 0, is_vacant: 1 }), [specTenant()], true)
    assert.equal(vm.conflicts.length, 1)
    assert.equal(vm.conflicts[0].type, 'DIRECT_CONFLICT')
    assert.equal(vm.confidence, 'LOW')
  })

  test('인원수 집계 차이 -> AGGREGATION_DIFFERENCE / MEDIUM', () => {
    const vm = assembleRightsAnalysis(summary({ total_tenant_count: 3 }), [specTenant()], true)
    assert.equal(vm.conflicts.length, 1)
    assert.equal(vm.conflicts[0].type, 'AGGREGATION_DIFFERENCE')
    assert.equal(vm.confidence, 'MEDIUM')
  })

  test('LOW는 반박된 경우에만 쓴다 — 미확인은 LOW가 아니다', () => {
    // 단일 정보원을 LOW로 낮추면 "정면으로 어긋남"과 "확인 못 함"이 다시 뒤섞인다.
    assert.notEqual(assembleRightsAnalysis(summary(), [], false).confidence, 'LOW')
  })
})

describe('canCrossCheck는 detectConflicts의 비교 조건과 같아야 한다', () => {
  // 두 조건이 갈라지면 BUGS #44가 그대로 재발한다.
  test('정보원이 둘 다 있어야 대조 가능', () => {
    const sv = mapStatusView(summary())
    const pv = mapSpecView([specTenant()])
    assert.equal(canCrossCheck(sv, pv), true)
    assert.equal(canCrossCheck(sv, undefined), false)
    assert.equal(canCrossCheck(undefined, pv), false)
    assert.equal(canCrossCheck(undefined, undefined), false)
  })

  test('임차인 수가 NULL이면 정보원이 둘이어도 대조 불가 -> HIGH 금지', () => {
    // 현재 DB에서는 total_tenant_count가 162/162 채워져 있어 발생하지 않지만,
    // 비교값이 없으면 비교한 적 없는 것이므로 같은 규칙이 적용돼야 한다.
    const sv = mapStatusView(summary({ total_tenant_count: null }))
    const pv = mapSpecView([specTenant()])
    assert.equal(canCrossCheck(sv, pv), false)
    const vm = assembleRightsAnalysis(summary({ total_tenant_count: null }), [specTenant()], true)
    assert.equal(vm.conflicts.length, 0, '비교값이 없는데 충돌을 판정했습니다')
    assert.notEqual(vm.confidence, 'HIGH', '비교값이 NULL인데 신뢰도 HIGH로 표시됩니다')
  })
})

describe('Mapper는 원본을 왜곡하지 않는다', () => {
  test('STATUS 행은 명세서 뷰에 섞이지 않는다', () => {
    const pv = mapSpecView([statusTenant(), statusTenant()])
    assert.equal(pv, undefined, '현황조사서 행이 매각물건명세서 임차인으로 표시됩니다')
  })

  test('is_vacant 0/1/null을 boolean/null로 정확히 옮긴다', () => {
    assert.equal(mapStatusView(summary({ is_vacant: 1 })).isVacant, true)
    assert.equal(mapStatusView(summary({ is_vacant: 0 })).isVacant, false)
    assert.equal(mapStatusView(summary({ is_vacant: null })).isVacant, null)
  })

  test('rights_summary가 없으면 statusView 자체가 없다', () => {
    assert.equal(mapStatusView(null), undefined)
  })
})

describe('sourceStatus는 실제 문서 존재 여부를 그대로 전달한다', () => {
  test('SPEC 문서 없음이 available:false로 나온다', () => {
    const vm = assembleRightsAnalysis(summary(), [], false)
    const spec = vm.sourceStatus.find((s) => s.source === 'SPEC')
    assert.equal(spec.available, false)
  })

  test('등기부(REGISTRY)는 아직 항상 미제공', () => {
    const vm = assembleRightsAnalysis(summary(), [specTenant()], true)
    assert.equal(vm.sourceStatus.find((s) => s.source === 'REGISTRY').available, false)
    assert.equal(vm.registryView, undefined)
  })
})

describe('명세서 "문서 없음"과 "파싱 안 됨"을 구분한다 (Sprint 55)', () => {
  // BUGS #50으로 문서 수집 상태가 화면에 제대로 반영되기 시작하자 드러난 모호함이다.
  // 물건 54에서 실제로 이렇게 보였다:
  //     정보원  SPEC ✓ 확보
  //     경고    [MISSING_SPEC] 매각물건명세서에서 확인 가능한 임차인 상세정보가 없습니다.
  // 둘 다 사실이지만(문서는 있고 파싱 결과는 없다) 같은 단어를 써서 모순으로 읽힌다.
  // 두 상황은 해야 할 일이 다르다 — 전자는 수집, 후자는 파서 점검.

  test('문서가 없으면 MISSING_SPEC', () => {
    const vm = assembleRightsAnalysis(summary(), [], false)
    const codes = vm.warnings.map((w) => w.code)
    assert.ok(codes.includes('MISSING_SPEC'), `실제: ${codes.join(',')}`)
    assert.ok(!codes.includes('SPEC_NOT_PARSED'))
  })

  test('문서는 있는데 파싱 결과가 없으면 SPEC_NOT_PARSED', () => {
    const vm = assembleRightsAnalysis(summary(), [], true)
    const codes = vm.warnings.map((w) => w.code)
    assert.ok(
      codes.includes('SPEC_NOT_PARSED'),
      `문서를 확보했는데 "명세서가 없다"고 안내합니다: ${codes.join(',')}`
    )
    assert.ok(!codes.includes('MISSING_SPEC'))
    // 문구도 "확보했으나"임을 못 박는다 — 코드만 바꾸고 문장이 그대로면 화면은 그대로다.
    const w = vm.warnings.find((x) => x.code === 'SPEC_NOT_PARSED')
    assert.match(w.message, /확보/, `문구가 여전히 "없습니다"입니다: ${w.message}`)
  })

  test('파싱 결과가 있으면 둘 다 나오지 않는다', () => {
    const vm = assembleRightsAnalysis(summary(), [specTenant()], true)
    const codes = vm.warnings.map((w) => w.code)
    assert.ok(!codes.includes('MISSING_SPEC') && !codes.includes('SPEC_NOT_PARSED'),
      `실제: ${codes.join(',')}`)
  })

  test('문서 확보 여부가 신뢰도를 바꾸지는 않는다', () => {
    // 신뢰도는 **파싱된 정보원끼리의 대조**로 정한다. 문서 파일이 있다는 사실만으로
    // 대조가 되는 것은 아니다 — 여기가 흔들리면 BUGS #44가 다른 경로로 재발한다.
    const withDoc = assembleRightsAnalysis(summary(), [], true)
    const withoutDoc = assembleRightsAnalysis(summary(), [], false)
    assert.equal(withDoc.confidence, withoutDoc.confidence)
    assert.equal(withDoc.confidence, 'MEDIUM')
  })
})
