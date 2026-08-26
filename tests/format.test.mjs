// ================================================================
// 표시 금액 포맷 회귀 테스트 (Sprint 81 신규)
//
// 왜 지금 생겼나 — `src/lib/format.ts`에는 **소스 계약만** 있었다.
// `tests/source-contract.test.mjs`가 "formatWon이 한 곳에만 정의되는가",
// "마이페이지가 formatWon을 쓰는가"를 확인하지만, **그 함수들이 실제로 무엇을
// 출력하는지는 한 번도 검증된 적이 없었다.**
//
// 이 세 함수는 화면에 그대로 찍히는 문자열을 만든다. 특히 `formatWon()`은
// **사용자에게 실제로 청구되는 금액**이라 축약되면 안 된다 — 그 이유가 파일 주석에
// 적혀 있는데도(`formatPrice(12900)`은 "1만"이 되어 2,900원 어긋난다) 그 불변식이
// 코드로 고정돼 있지 않았다.
//
// rights-analysis.test.mjs와 같은 방식: 순수 함수를 직접 호출해 계약을 고정한다.
// (Node 내장 TypeScript type stripping — 새 의존성/빌드 단계 없음)
//
// ★ 표기 기준 자체는 바꾸지 않는다. `formatPrice`와 `formatPriceEok`가 공존하는 것은
//   파일 주석이 적어 둔 대로 **미결정 상태**이고, 어느 쪽으로 통일할지는 화면 숫자가
//   바뀌는 UX 결정이다. 여기서는 지금 동작을 그대로 못박기만 한다.
// ================================================================

import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { formatPrice, formatPriceEok, formatWon, parseArea, formatArea, SQM_PER_PYEONG } from '../src/lib/format.ts'

describe('formatPrice — 물건 시세(억/만 축약)', () => {
  test('0과 falsy는 하이픈으로 표시한다', () => {
    // 감정가/최저가가 없는 물건을 "0원"으로 보여주면 실제로 0원인 것처럼 읽힌다.
    assert.equal(formatPrice(0), '-')
    assert.equal(formatPrice(NaN), '-')
  })

  test('1만 미만은 원 단위 그대로', () => {
    assert.equal(formatPrice(999), '999')
    assert.equal(formatPrice(9999), '9999')
  })

  test('1만 경계에서 만 단위로 바뀐다', () => {
    assert.equal(formatPrice(9999), '9999')
    assert.equal(formatPrice(10000), '1만')
  })

  test('1억 경계에서 억 단위로 바뀐다', () => {
    // 1억 직전은 아직 만 단위다(10000만). 경계가 밀리면 여기서 먼저 깨진다.
    assert.equal(formatPrice(99999999), '10000만')
    assert.equal(formatPrice(100000000), '1.0억')
  })

  test('억 단위는 소수 첫째 자리까지', () => {
    assert.equal(formatPrice(150000000), '1.5억')
    assert.equal(formatPrice(1234567890), '12.3억')
  })

  test('만 단위는 반올림한다', () => {
    assert.equal(formatPrice(12900), '1만')
    assert.equal(formatPrice(15000), '2만')
  })
})

describe('formatPriceEok — 억 고정 표기', () => {
  test('0도 하이픈이 아니라 0.0억이다', () => {
    // formatPrice와 다른 점이 바로 이것이다(파일 주석의 서술과 일치해야 한다).
    assert.equal(formatPriceEok(0), '0.0억')
    assert.notEqual(formatPriceEok(0), formatPrice(0))
  })

  test('1억 미만도 억 단위로 쓴다', () => {
    assert.equal(formatPriceEok(5000000), '0.1억')
  })

  test('1억 이상은 formatPrice와 같은 결과', () => {
    for (const v of [100000000, 150000000, 1234567890]) {
      assert.equal(formatPriceEok(v), formatPrice(v), `${v}에서 두 표기가 갈렸습니다`)
    }
  })
})

describe('formatWon — 청구 금액(축약 금지)', () => {
  test('천 단위 구분 쉼표와 원 단위를 그대로 쓴다', () => {
    assert.equal(formatWon(12900), '12,900원')
    assert.equal(formatWon(0), '0원')
    assert.equal(formatWon(1234567), '1,234,567원')
    assert.equal(formatWon(198000), '198,000원')
  })

  test('★ 절대 축약하지 않는다 — 실제 청구액과 어긋나면 안 된다', () => {
    // 이 파일이 존재하는 이유. formatPrice(12900)은 "1만"이 되어 2,900원(22%) 어긋난다.
    // 구독료/환불액에 축약 표기를 쓰면 같은 결제가 화면마다 다른 금액으로 보인다.
    for (const amount of [12900, 22900, 154800, 198000, 274800]) {
      const shown = formatWon(amount)
      assert.ok(!/[억만]/.test(shown), `청구 금액이 축약됐습니다: ${amount} -> ${shown}`)
      // 표시 문자열에서 숫자만 남기면 원래 금액과 정확히 같아야 한다.
      assert.equal(
        Number(shown.replace(/[^\d]/g, '')),
        amount,
        `표시 금액이 실제 금액과 다릅니다: ${amount} -> ${shown}`
      )
    }
  })

  test('실제 구독 가격 전부가 정확히 표시된다', () => {
    // api/v1/payments.py:PLAN_CATALOG의 확정 가격(docs/decision-log.md).
    // 이 값들이 화면에서 축약되거나 반올림되면 결제 화면이 거짓말을 한다.
    assert.equal(formatWon(12900), '12,900원')   // BASIC 월간
    assert.equal(formatWon(154800), '154,800원') // BASIC 연간
    assert.equal(formatWon(22900), '22,900원')   // PRO 월간
    assert.equal(formatWon(198000), '198,000원') // PRO 연간(할인가)
  })
})

describe('세 함수의 역할 구분', () => {
  test('청구 금액과 시세 표기는 서로 다른 함수여야 한다', () => {
    // 같은 값을 넣으면 결과가 달라야 한다 — 같아지면 구분이 사라진 것이다.
    assert.notEqual(formatWon(12900), formatPrice(12900))
  })
})

// ================================================================
// 물건 면적 파싱 (parseArea / formatArea) — 2026-08-21 Sprint 248 신설
//
// ## 왜 지금 생겼나
//
// 이 두 함수는 **검색 결과 카드마다 찍히는 값**을 만든다. 그런데 원래
// `src/app/search/ResultList.tsx`(JSX) 안에 있어서 Node 의 타입 스트리핑으로
// import 할 수 없었고, 그래서 **동작이 한 번도 검증된 적이 없었다.**
// `src/lib/format.ts` 로 옮기면서 계약을 고정한다.
//
// 아래 입력은 전부 **운영 DB 의 실제 full_address**다(2026-08-21 전수 조회에서
// 그대로 가져왔다). 지어낸 문자열로는 이 함수가 실제로 마주치는 형태를 못 덮는다.
//
// 전수 실측 분포 (auction_item 1,876행, 제품 함수를 소스에서 꺼내 그대로 실행):
//     정상 파싱(면적 1개)    1,807  96.32%
//     정상 파싱(다층 합산)       43   2.29%
//     파싱 불가(면적 개념 없음)   14   0.75%   차량 10 / 선박 2 / 기타 1 / 건설기계 1
//     파싱 불가(단위가 '평')       8   0.43%   면적은 있는데 못 읽는다(알려진 한계)
//     라벨 오분류                 0   0.00%
// ================================================================

describe('parseArea — 주소 대괄호에서 면적 읽기 (실제 DB 문자열)', () => {
  test('집합건물: 면적 1개를 읽고 라벨은 건물이다', () => {
    const r = parseArea('서울특별시 관악구 난곡로66가길 19 2층202호 [집합건물 철근콘크리트구조 17.08㎡]')
    assert.deepEqual(r, { label: '건물', sqm: 17.08 })
  })

  test('토지: 라벨이 토지다', () => {
    const r = parseArea('서울특별시 종로구 평창동 445-1 [토지 대 420㎡]')
    assert.deepEqual(r, { label: '토지', sqm: 420 })
  })

  test('다층 건물: 층별 면적을 **합산**한다', () => {
    // id=508 (실제 데이터). 첫 값만 쓰면 82.95 로 4배 넘게 과소 표시된다.
    const a = '서울특별시 관악구 봉천로33가길 36-3 (봉천동,클로토) [건물 철근콘트리트구조 기타지붕 4층 ' +
      '단독주택 및 제2종근린생활시설 지1층 82.95㎡ 1층 68.45㎡ 2층 61.66㎡ 3층 61.66㎡ 4층 42.4㎡ ' +
      '옥탑1층 20.1㎡ 옥탑2층 20.1㎡]'
    const r = parseArea(a)
    assert.equal(r.label, '건물')
    assert.ok(Math.abs(r.sqm - 357.32) < 0.005, `합계가 357.32 여야 하는데 ${r.sqm}`)
  })

  // ★ 회귀의 핵심 — 중첩 대괄호
  //
  // 예전 정규식 `/\[([^\]]*)\]\s*$/` 는 `[^\]]*` 가 안쪽 `]` 를 넘지 못해
  // 이 네 건에서 **통째로 실패**했다(면적이 멀쩡히 적혀 있는데 화면에 아무것도 안 나옴).
  // 전체 1,876행 대조 결과: 새로 파싱 4건 / 값 변경 0건 / 파싱 상실 0건.
  describe('중첩 대괄호 (Sprint 248 수정)', () => {
    test('안쪽 대괄호가 있어도 토지 면적을 읽는다 (id=258)', () => {
      const r = parseArea('전라남도 함평군 손불면 학산리 661 [토지 전[현황:묵전(죽림)] 105㎡ ' +
        '채무자겸소유자 백부덕 지분 36분의3, 김상용, 김학수, 김희숙 지분 각 36분의2 전부]')
      assert.deepEqual(r, { label: '토지', sqm: 105 })
    })

    test('여는 괄호가 어긋나 있어도 읽는다 (id=259)', () => {
      const r = parseArea('전라남도 함평군 손불면 학산리 1018-9 [토지 전[(현황:전 및 묵전(임야)] 694㎡ ' +
        '채무자겸소유자 백부덕 지분 18분의3, 김상용, 김학수, 김희숙 지분 각 18분의2 전부]')
      assert.deepEqual(r, { label: '토지', sqm: 694 })
    })

    test('끝이 중첩 대괄호로 닫혀도 읽는다 (id=1610)', () => {
      const r = parseArea('제주특별자치도 제주시 구좌읍 세화리 산44-2 [토지 임야 6571㎡ 5178분의 4657 ' +
        '[전체 지분 중 갑구 6번 고혜선 소유지분(갑구 20번 주식회사신라종합건설) 5178분의 521 제외]]')
      assert.deepEqual(r, { label: '토지', sqm: 6571 })
    })

    test('중첩 대괄호 + 다층 합산이 함께 동작한다 (id=6273)', () => {
      const r = parseArea('경상북도 상주시 중동면 간상3길 3-3 [건물 시멘트벽돌조 슬래브지붕 단층 주택 97.58㎡ ' +
        '시멘트벽돌조 슬래브지붕 단층 창고 46.4㎡ [현황: 멸실]]')
      assert.equal(r.label, '건물')
      assert.ok(Math.abs(r.sqm - 143.98) < 0.005, `합계가 143.98 여야 하는데 ${r.sqm}`)
    })
  })

  // ★ 대지권(垈地權) — 2026-08-21 Sprint 249
  //
  // 집합건물 등기에는 전유부분 면적 뒤에 **대지권**(건물이 깔고 앉은 토지 **전체** 면적)이
  // 함께 적히는 형식이 있다. 층별 합산 규칙을 그대로 적용하면 아파트 한 채가 토지 전체를
  // 가진 것처럼 부풀어 오른다.
  //
  // 실측 id=6442 (부산 동래구 동래에코하임 901호):
  //     고치기 전  건물 574.55㎡ (173.80평)   <- 74.5482 + 500
  //     고친 뒤    건물  74.55㎡ ( 22.55평)   <- 전유부분만
  //
  // 전체 1,876행 대조에서 값이 바뀌는 행은 이 1건뿐이고 파싱을 잃은 행은 0이었다.
  describe('대지권 표기 (Sprint 249)', () => {
    const REAL = '부산광역시 동래구 명안로10번길 34 9층901호 (안락동,동래에코하임) ' +
      '[집합건물 철근콘크리트조 74.5482㎡ 대지권의 표시 토지의 표시 : 부산광역시 동래구 안락동 308 ' +
      '대 500㎡ 대지권 종류 : 소유권대지권 대지권 비율 : 500분의 21.7849]'

    test('대지권 토지 면적을 전유부분에 더하지 않는다 (id=6442)', () => {
      const r = parseArea(REAL)
      assert.equal(r.label, '건물')
      assert.ok(Math.abs(r.sqm - 74.5482) < 0.0001,
        `전유부분 74.5482㎡ 여야 하는데 ${r.sqm} (500㎡ 대지권을 더했는지 확인)`)
    })

    test('화면 문구도 전유부분 기준이다', () => {
      assert.equal(formatArea(parseArea(REAL)), '건물 74.55㎡ (22.55평)')
    })

    test('대지권이 없는 집합건물은 영향이 없다', () => {
      const r = parseArea('서울특별시 관악구 난곡로66가길 19 2층202호 [집합건물 철근콘크리트구조 17.08㎡]')
      assert.deepEqual(r, { label: '건물', sqm: 17.08 })
    })

    // 대지권 잘라내기가 **다층 합산까지** 망가뜨리면 안 된다.
    // (마커가 없으면 예전과 똑같이 전부 더해야 한다)
    test('다층 합산은 그대로 유지된다', () => {
      const a = '서울특별시 관악구 봉천로33가길 36-3 (봉천동,클로토) [건물 철근콘트리트구조 기타지붕 4층 ' +
        '단독주택 및 제2종근린생활시설 지1층 82.95㎡ 1층 68.45㎡ 2층 61.66㎡ 3층 61.66㎡ 4층 42.4㎡ ' +
        '옥탑1층 20.1㎡ 옥탑2층 20.1㎡]'
      assert.ok(Math.abs(parseArea(a).sqm - 357.32) < 0.005)
    })

    test('마커가 면적보다 앞에 오면 면적이 없는 것으로 본다(과대표시 방지)', () => {
      // 전유부분 면적 없이 대지권만 적힌 가상 형식. 500㎡ 를 이 물건 면적으로
      // 보여 주는 것보다 아무것도 안 보여 주는 편이 안전하다.
      assert.equal(parseArea('서울시 어딘가 [집합건물 대지권의 표시 토지의 표시 : 대 500㎡]'), null)
    })
  })

  describe('면적을 표시하지 않아야 하는 경우', () => {
    test('차량은 null (면적 개념이 없다)', () => {
      assert.equal(parseArea('사용본거지 : 인천 부평구 백범로456번길 20-24 (십정동) [카니발 2016년식 승용차]'), null)
    })

    test('선박은 null', () => {
      assert.equal(parseArea('선적항 : 완도군 완도읍 [선박 동력선, 동어호]'), null)
    })

    test('null/빈 문자열은 null', () => {
      assert.equal(parseArea(null), null)
      assert.equal(parseArea(''), null)
    })

    test('대괄호가 없으면 null', () => {
      assert.equal(parseArea('서울특별시 종로구 평창동 445-1'), null)
    })

    // 알려진 한계를 **고정**한다. 고치는 순간 이 검사가 실패하므로,
    // 그때 위 주석의 위험(id=6495 의 '192평6홉9작' 중복 층 목록)을 함께 검토하게 된다.
    test('단위가 평이면 아직 읽지 않는다 (알려진 한계, 실측 8건)', () => {
      assert.equal(parseArea('경상북도 포항시 북구 죽장면 월평리 690 [토지 전 1048평]'), null)
    })
  })
})

describe('formatArea — 화면에 찍히는 문자열', () => {
  test('㎡ 와 평을 함께 보여준다', () => {
    assert.equal(formatArea({ label: '건물', sqm: 84.5 }), '건물 84.50㎡ (25.56평)')
  })

  test('토지 라벨이 그대로 실린다', () => {
    assert.equal(formatArea({ label: '토지', sqm: 420 }), '토지 420.00㎡ (127.05평)')
  })

  test('소수 둘째 자리로 고정한다(들쭉날쭉한 자릿수 방지)', () => {
    assert.equal(formatArea({ label: '건물', sqm: 17.08 }), '건물 17.08㎡ (5.17평)')
  })

  test('1평 환산 상수가 공식값이다', () => {
    assert.equal(SQM_PER_PYEONG, 3.305785)
    // 1평을 넣으면 정확히 1.00평으로 되돌아와야 한다(환산이 자기모순이 아닌지)
    assert.equal(formatArea({ label: '토지', sqm: SQM_PER_PYEONG }), '토지 3.31㎡ (1.00평)')
  })
})

describe('parseArea — 천단위 쉼표 (BUGS #240)', () => {
  // 예전 정규식 `[0-9]+` 는 쉼표에서 끊겨 **쉼표 뒤부터** 매치됐다.
  // 화면에는 오류도 빈칸도 아닌 **그럴듯한 작은 숫자**가 찍혀서 알아챌 방법이 없었다.
  test('★ 쉼표가 있어도 앞자리를 잃지 않는다', () => {
    assert.deepEqual(parseArea('서울 x [건물 1층 3,005.35㎡]'), { label: '건물', sqm: 3005.35 })
    assert.deepEqual(parseArea('서울 x [건물 1층 12,345.67㎡]'), { label: '건물', sqm: 12345.67 })
    assert.deepEqual(parseArea('서울 x [토지 대 1,048㎡]'), { label: '토지', sqm: 1048 })
  })

  test('★ 쉼표 뒤가 0 뿐이어도 0㎡ 가 되지 않는다', () => {
    // `1,000㎡` -> 0 이 나오던 자리. 면적이 **0 으로 보이는** 최악의 표시였다.
    assert.deepEqual(parseArea('서울 x [건물 1층 1,000㎡]'), { label: '건물', sqm: 1000 })
    assert.deepEqual(parseArea('서울 x [건물 1층 2,000.00㎡]'), { label: '건물', sqm: 2000 })
  })

  test('★ 쉼표가 섞인 다층 합산이 맞는다 (실데이터 id=443)', () => {
    // 지1층 3,005.35 + 1층 6,110.75 + 2층 5,322.75 = 14,438.85
    const addr =
      '경기도 평택시 청북읍 드림산단2로 80 (제넨코어센터피동) [건물 일반철골구조 ' +
      '(철근)콘크리트지붕 공장 지1층 3,005.35㎡ 1층 6,110.75㎡ 2층 5,322.75㎡ ' +
      '공장 및 광업재단 저당법 제6조 목록 제2022-66호, 제2022-112호]'
    assert.deepEqual(parseArea(addr), { label: '건물', sqm: 14438.85 })
  })

  test('쉼표가 없는 기존 표기는 그대로다 (회귀 없음)', () => {
    assert.deepEqual(parseArea('서울 x [건물 999.5㎡]'), { label: '건물', sqm: 999.5 })
    assert.deepEqual(parseArea('서울 x [집합건물 17.08㎡]'), { label: '건물', sqm: 17.08 })
    assert.equal(parseArea('서울 x [카니발 2016년식 승용차]'), null)
  })

  test('★ 백엔드(normalizer.extract_areas)와 같은 숫자를 낸다', () => {
    // 같은 규칙의 두 구현이 갈라져 있던 것이 결함의 정체다(BUGS #204/#240).
    // 파이썬을 여기서 부를 수는 없으므로, **파이썬이 내는 값을 기대값으로 못박는다.**
    // (그 값은 `test_normalizer.py` 가 파이썬 쪽에서 같은 입력으로 고정한다 —
    //  한쪽만 고치면 다른 쪽이 붉어진다.)
    const pairs = [
      ['서울 x [건물 1층 3,005.35㎡ 2층 1,000㎡]', 4005.35],
      ['서울 x [토지 대 1,048㎡]', 1048],
      ['서울 x [건물 1층 75.6㎡ 2층 70.2㎡]', 145.8],
    ]
    for (const [addr, expected] of pairs) {
      const got = parseArea(addr)
      assert.ok(got, `면적을 못 뽑았습니다: ${addr}`)
      assert.equal(
        Number(got.sqm.toFixed(4)), expected,
        `백엔드와 다른 값입니다: ${addr}`
      )
    }
  })
})
