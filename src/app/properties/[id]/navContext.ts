// ================================================================
// 상세 화면의 "이전/다음 물건" 이동 컨텍스트 해석 (순수 함수)
//
// page.tsx 안에 인라인으로 있던 계산을 동작 변경 없이 그대로 옮긴 것이다.
// 분리한 이유는 회귀 테스트 때문이다 — 상세 화면은 로그인 필수 + 클라이언트 렌더라
// HTTP 블랙박스 테스트(tests/frontend-contract.test.mjs)로는 이 로직을 볼 수 없다.
// `crawler/resume.py:resume_start_idx()`를 같은 이유로 분리했던 것과 동일한 판단.
//
// 계약(docs/FRONTEND_MASTER_SPEC.md §9.2):
//   검색 결과에서 넘어온 경우(`?ids=`,`?i=`)에만 이전/다음 버튼을 노출한다.
//   컨텍스트가 없으면 **버튼 자체를 숨긴다**(비활성 버튼을 남기지 않는다).
// ================================================================

export type NavContext = {
  /** 목록 내 물건 id 순서. 컨텍스트가 없으면 빈 배열 */
  ids: number[]
  /** 현재 물건의 인덱스. 컨텍스트가 없거나 범위를 벗어나면 -1 (= 이동 UI 숨김) */
  index: number
  /** 이전 물건 id. 없으면 null */
  prevId: number | null
  /** 다음 물건 id. 없으면 null */
  nextId: number | null
}

export function resolveNavContext(idsParam: string | null, indexParam: string | null): NavContext {
  // 빈 세그먼트를 먼저 걸러야 한다. `''.split(',')`는 `['']`를 돌려주고 `Number('')`는 0이라,
  // 예전 구현은 **ids 파라미터가 아예 없을 때도** ids=[0]으로 판단했다. 그래서
  // `/favorites`·`/properties/recent`의 카드처럼 목록 컨텍스트 없이 들어온 상세에서
  // "← 이전 물건 / 1 / 1 / 다음 물건 →" 바가 양쪽 다 비활성인 채로 떠 있었다.
  const ids = (idsParam ?? '')
    .split(',')
    .filter((v) => v !== '')
    .map((v) => Number(v))
    .filter((n) => Number.isInteger(n))

  // `i`가 없을 때 Number(null)이 0이 되어 "0번째"로 오인되지 않도록 명시적으로 구분한다.
  const raw = indexParam === null ? -1 : Number(indexParam)
  const index = Number.isInteger(raw) && raw >= 0 && raw < ids.length ? raw : -1

  return {
    ids,
    index,
    prevId: index > 0 ? ids[index - 1] : null,
    nextId: index >= 0 && index < ids.length - 1 ? ids[index + 1] : null,
  }
}
