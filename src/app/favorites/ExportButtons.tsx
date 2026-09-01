'use client'
import { useState } from 'react'
import {
  buildCsv,
  buildTsv,
  exportFileName,
  UTF8_BOM,
  type ExportRow,
} from '@/lib/exportList'
import { todayInDisplayZone } from '@/lib/format'

/**
 * 마이리스트(관심물건) 내보내기 버튼 (2026-08-20 Sprint 227).
 *
 * ## 왜 서버를 거치지 않는가
 *
 * 목록은 이미 화면이 받아 놓았다. 같은 것을 다시 받아 오면 **그 사이에 바뀐 데이터가
 * 화면과 파일에서 달라진다** — 사용자가 보고 있는 것과 내려받은 것이 어긋나는 게 더 나쁘다.
 * 지금 보고 있는 그 목록을 그대로 낸다.
 *
 * ## 무엇을 만들지 않았는가
 *
 * 상대 서비스(지지옥션·탱크옥션 등) 전용 포맷은 **만들지 않는다.**
 * 실제 입력 형식을 확인하지 못했고(`docs/SPRINT219B_MYLIST_EXPORT_FEASIBILITY.md`),
 * 추측해서 내보내면 "붙여넣었는데 안 들어간다"가 된다 — 그 실패는 우리 쪽에서 보이지 않는다.
 *
 * ## 결과를 말해 준다
 *
 * 복사는 **아무 화면 변화가 없는 동작**이라 성공했는지 알 수 없다. 그래서 결과를
 * `role="status"` 로 알린다(스크린리더도 읽는다). 클립보드 API 는 권한·비보안 컨텍스트에서
 * 실패할 수 있으므로 **실패도 정직하게** 말한다 — 조용히 성공한 척하지 않는다.
 */
export default function ExportButtons({
  rows,
  disabled,
}: {
  rows: ExportRow[]
  disabled?: boolean
}) {
  const [message, setMessage] = useState('')

  function download() {
    // BOM 을 붙인다 — 없으면 한국어 Windows 엑셀이 cp949 로 읽어 주소·법원명이 전부 깨진다.
    // (실측 2026-08-20: 이 CSV 를 cp949 로 읽으면 UnicodeDecodeError 가 난다.)
    const blob = new Blob([UTF8_BOM + buildCsv(rows)], {
      type: 'text/csv;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    // 파일명의 날짜도 **한국 시각**이다. `new Date().toISOString()` 은 UTC 라
    // KST 09:00 이전에 내려받으면 어제 날짜가 붙었다(`ymdPlusDays` 주석과 같은 결함).
    a.download = exportFileName('관심물건', todayInDisplayZone())
    document.body.appendChild(a)
    a.click()
    a.remove()
    // 해제하지 않으면 탭이 살아 있는 동안 메모리를 붙들고 있다.
    URL.revokeObjectURL(url)
    setMessage(`CSV ${rows.length}건을 내려받았습니다`)
  }

  async function copy() {
    const text = buildTsv(rows)
    try {
      await navigator.clipboard.writeText(text)
      setMessage(`${rows.length}건을 복사했습니다 (표 프로그램에 붙여넣기)`)
    } catch {
      // 권한 거부 / http 컨텍스트 등. 감추지 않는다.
      setMessage('복사하지 못했습니다 — 브라우저가 클립보드 접근을 막았습니다')
    }
  }

  /* 글자 크기는 `text-sm`(14px) 이다. 저장소에 `text-xs`(12px) 사용 상한이 걸려 있는데,
     그것은 "작은 글자를 더 늘리지 말자"는 약속이라 **새 UI 를 만들며 상한을 올리는 것은
     약속을 어기는 쪽**이다. 14px 는 접근성으로도 낫다(docs/SPRINT219 개선안 3번). */
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={download}
        disabled={disabled}
        className="rounded-xl border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 disabled:opacity-40"
      >
        CSV 내려받기
      </button>
      <button
        type="button"
        onClick={copy}
        disabled={disabled}
        className="rounded-xl border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 disabled:opacity-40"
      >
        복사
      </button>
      {/* ★ 항상 존재하는 한 줄이 **그대로 보이는 줄**이다.

          처음에는 sr-only 한 줄 + 보이는 한 줄(aria-hidden) 둘로 나눴는데 그러면
          (1) 보이는 줄이 조건부라 나타나는 순간을 스크린리더가 놓칠 수 있고
          (2) 같은 말을 두 노드로 관리해 한쪽만 바뀌는 어긋남이 생긴다.
          노드는 그대로 두고 **글자만** 바꾼다 — 비어 있을 때는 아무것도 보이지 않는다
          (Sprint 223 이 검색 결과 알림에서 택한 것과 같은 방식).

          `text-gray-600` 은 흰 배경에서 7.56:1 로 AA(4.5:1)를 넘는다(실측 Sprint 225).
          같은 자리에 흔히 쓰이던 `text-gray-400` 은 2.6:1 이라 쓰지 않았다. */}
      <span role="status" aria-live="polite" className="text-sm text-gray-600">
        {message}
      </span>
    </div>
  )
}
