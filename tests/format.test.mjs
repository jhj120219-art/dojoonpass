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
import { formatPrice, formatPriceEok, formatWon } from '../src/lib/format.ts'

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
