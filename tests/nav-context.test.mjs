// ================================================================
// 상세 화면 "이전/다음 물건" 컨텍스트 회귀 테스트 (Sprint 49 신규)
//
// 왜 별도 파일인가: `/properties/[id]`는 로그인 필수 + 클라이언트 렌더라
// frontend-contract.test.mjs의 HTTP 블랙박스로는 이 UI를 관찰할 수 없다.
// 계산 자체는 순수 함수(src/app/properties/[id]/navContext.ts)로 분리돼 있으므로
// 여기서 직접 호출해 고정한다. (Node 24의 내장 TypeScript type stripping 사용 —
// 새 의존성/빌드 단계 없음)
//
// 고정하는 계약(docs/FRONTEND_MASTER_SPEC.md §9.2):
//   검색 결과에서 넘어온 경우에만 이전/다음 버튼을 노출한다. 컨텍스트가 없으면 숨긴다.
// ================================================================

import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { resolveNavContext } from '../src/app/properties/[id]/navContext.ts'

describe('목록 컨텍스트가 없으면 이동 UI를 숨긴다 (Sprint 49 회귀)', () => {
  // Sprint 49에서 실제 브라우저로 발견한 결함:
  // `/favorites`·`/properties/recent`의 카드는 `/properties/{id}`로만 링크하는데,
  // `''.split(',')`가 `['']`를 주고 `Number('')`가 0이라 ids=[0]으로 해석되어
  // "← 이전 물건 / 1 / 1 / 다음 물건 →" 바가 양쪽 다 비활성인 채로 떠 있었다.
  test('ids/i가 모두 없으면 index가 -1이다', () => {
    const ctx = resolveNavContext(null, null)
    assert.deepEqual(ctx.ids, [], 'ids가 비어 있지 않습니다')
    assert.equal(ctx.index, -1, '컨텍스트가 없는데 이동 UI가 노출됩니다')
    assert.equal(ctx.prevId, null)
    assert.equal(ctx.nextId, null)
  })

  test('빈 문자열 ids도 컨텍스트 없음으로 본다', () => {
    assert.equal(resolveNavContext('', null).index, -1)
    assert.equal(resolveNavContext('', '0').index, -1)
    assert.equal(resolveNavContext(',,', '0').index, -1)
  })

  test('ids만 있고 i가 없으면 이동 UI를 노출하지 않는다', () => {
    // Number(null) === 0이라 예전에는 "0번째"로 오인됐다.
    assert.equal(resolveNavContext('84,85,86', null).index, -1)
  })
})

describe('목록 컨텍스트가 있으면 정확한 이전/다음을 준다', () => {
  test('가운데 물건은 이전/다음이 모두 있다', () => {
    const ctx = resolveNavContext('84,85,86', '1')
    assert.deepEqual(ctx.ids, [84, 85, 86])
    assert.equal(ctx.index, 1)
    assert.equal(ctx.prevId, 84)
    assert.equal(ctx.nextId, 86)
  })

  test('첫 물건은 이전이 없고, 마지막 물건은 다음이 없다', () => {
    const first = resolveNavContext('84,85,86', '0')
    assert.equal(first.prevId, null, '첫 물건에 이전이 생겼습니다')
    assert.equal(first.nextId, 85)

    const last = resolveNavContext('84,85,86', '2')
    assert.equal(last.prevId, 85)
    assert.equal(last.nextId, null, '마지막 물건에 다음이 생겼습니다')
  })

  test('물건이 1건뿐이면 양쪽 다 없다(바는 뜨되 이동 대상 없음)', () => {
    const ctx = resolveNavContext('84', '0')
    assert.equal(ctx.index, 0)
    assert.equal(ctx.prevId, null)
    assert.equal(ctx.nextId, null)
  })

  test('범위를 벗어난 i는 이동 UI를 숨긴다', () => {
    assert.equal(resolveNavContext('84,85,86', '3').index, -1, '범위 초과 i가 통과했습니다')
    assert.equal(resolveNavContext('84,85,86', '-1').index, -1, '음수 i가 통과했습니다')
    assert.equal(resolveNavContext('84,85,86', 'abc').index, -1, '숫자가 아닌 i가 통과했습니다')
    assert.equal(resolveNavContext('84,85,86', '1.5').index, -1, '정수가 아닌 i가 통과했습니다')
  })

  test('숫자가 아닌 id는 목록에서 제외한다', () => {
    const ctx = resolveNavContext('84,abc,86', '1')
    assert.deepEqual(ctx.ids, [84, 86], '숫자가 아닌 id가 목록에 남았습니다')
  })
})
