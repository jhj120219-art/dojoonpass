import Link from 'next/link'
import type { SearchResponse, SearchResultItem } from './types'
import FavoriteButton from './FavoriteButton'
import { formatPrice, formatNumber, formatDday, formatBidRate, displayArea, formatArea } from '@/lib/format'
import ResultThumbnail from '@/components/ResultThumbnail'

function ResultItemRow({ item, navQuery }: { item: SearchResultItem; navQuery: string }) {
  const location = item.full_address || [item.sido, item.sigungu, item.dong].filter(Boolean).join(' ')
  // 서버가 준 면적(검색 필터가 쓰는 값)이 먼저다. 없으면 주소 원문에서 읽는다.
  // 두 구현이 갈라져 카드와 필터가 다른 사실을 말하던 문제 — src/lib/format.ts 주석 참고.
  const area = displayArea(item)
  const dday = formatDday(item.auction_date)

  return (
    // ★ `min-w-0` — 이 Link 가 **grid 항목**이다 (2026-08-21 Sprint 240).
    //
    //   grid/flex 항목의 `min-width` 기본값은 `auto` 라서 트랙이 항목의 min-content
    //   아래로 줄어들지 못한다. 카드 안에는 `truncate`(= white-space:nowrap) 문단이
    //   있어 그 min-content 가 **문자열 전체 폭**이다. 그래서 좁은 화면에서 그리드
    //   컨테이너는 257px 인데 트랙이 278px 로 벌어져 페이지가 가로로 스크롤됐다.
    //
    //   실측(2026-08-21, 실제 320px 창): 컨테이너 257px vs 트랙 277.6px,
    //   카드 오른쪽 끝 294px vs 뷰포트 289px. `min-w-0` 을 주면 트랙이 컨테이너에
    //   맞춰지고 `truncate` 가 제 역할(말줄임)을 한다 — 재측정 넘침 0.
    //
    //   같은 결함이 /favorites 와 /properties/recent 에도 그대로 있었다(같은 카드 구조).
    <Link href={`/properties/${item.id}?${navQuery}`} className="block min-w-0">
    <div className="bg-white rounded-2xl p-4 shadow-sm hover:shadow-md transition-shadow border border-gray-100">
      {/* 물건 그룹: 물건종류를 가장 먼저 눈에 띄게, 그 다음 사건번호/주소/면적.

          대표 이미지 (2026-08-17 Sprint 145):
          예전 주석은 "auction_item에 이미지 컬럼이 없어 항상 빈 placeholder만 차지하므로
          넣지 않는다"였다. **그 전제가 바뀌었다** — Sprint 144에 `auction_image`와
          사진 서빙 엔드포인트가 생겼고, 검색 API가 대표 사진 URL을 함께 준다.

          다만 그 주석의 판단 자체는 여전히 옳다: 사진이 없는 물건에 빈 자리를 만들면
          안 된다(현재 사진 보유 물건은 전체의 극히 일부다). 그래서 **`thumbnail_url`이
          있을 때만** 썸네일을 그리고, 없으면 종전과 완전히 같은 텍스트 전용 레이아웃을
          유지한다. 사진이 채워질수록 자연스럽게 카드가 풍부해진다. */}
      <div className="min-w-0 flex gap-3">
        {/* 이 파일은 **서버 컴포넌트**라 이벤트 핸들러를 붙일 수 없다. 사진이 깨졌을 때
            자리를 숨기려면 onError가 필요하므로 썸네일만 클라이언트 섬으로 떼어냈다
            (같은 카드의 FavoriteButton과 같은 방식). 자세한 사유는 ResultThumbnail.tsx.
            (2026-08-20 Sprint 224: 관심물건/최근 본 물건도 같은 컴포넌트를 쓰게 되어
             src/components/ 로 옮겼다 — 세 화면의 썸네일 규칙이 갈라지지 않게 한다.) */}
        {item.thumbnail_url && <ResultThumbnail url={item.thumbnail_url} />}
        <div className="min-w-0 flex-1">
        {/* ★ `flex-wrap` — 좁은 화면에서 물건종류 배지가 **세로 한 글자씩** 쪼개지는 것을 막는다
            (2026-08-21 Sprint 242).

            이 줄은 `justify-between` 으로 [물건종류 배지] / [D-day + 하트] 를 양끝에 두는데,
            오른쪽 묶음이 `shrink-0` 이라 줄어들지 않는다. 그래서 폭이 모자라면 **왼쪽 배지만**
            계속 짜부라진다.

            실제 320px 뷰포트 실측(audit_viewport.py, 2026-08-21):

                가용 폭 147px  =  배지 37px + gap 8 + 오른쪽 묶음 110px(고정)
                배지 37px 안에서 "연립주택,다세대,빌라" 가 **9줄**로 접힌다
                -> 한 글자씩 세로로 늘어선 기둥이 되고 카드 높이가 403px 로 부푼다
                -> 오른쪽 묶음은 부모 박스를 7px 넘어간다

                360px -> 3줄 / 390px -> 2줄 / 430px -> 2줄  (좁을수록 급격히 나빠진다)

            페이지가 가로로 스크롤되지는 않아서, "가로 넘침만" 보던 이전 검사들은
            이것을 전부 놓쳤다. 부모 박스 넘침을 보게 되면서 드러났다.

            고침은 **줄바꿈 허용뿐**이다 — 색·글자크기·간격(gap)은 그대로다. 한 줄에
            들어가는 폭에서는 wrap 이 발동하지 않으므로 넓은 화면 렌더는 변하지 않는다.
            같은 구조가 /favorites·/properties/recent 에도 있어 함께 고쳤다. */}
        <div className="flex flex-wrap items-start justify-between gap-2 mb-1">
          <span className="text-sm font-bold text-blue-600 bg-blue-50 px-2.5 py-1 rounded-lg">
            {item.property_type || '-'}
          </span>
          <div className="flex items-center gap-2 shrink-0">
            {dday && (
              <span className="shrink-0 text-xs font-medium text-orange-500 bg-orange-50 px-2 py-1 rounded-lg">
                {dday}
              </span>
            )}
            <FavoriteButton itemId={item.id} initialFavorited={item.is_favorited} />
          </div>
        </div>
        <p className="text-sm font-bold text-gray-900 truncate">
          {item.case_no}{item.item_no ? ` (${item.item_no})` : ''}
        </p>
        <p className="text-xs text-gray-400 line-clamp-2 break-all">{location || '-'}</p>
        {area && <p className="text-xs text-gray-400 mt-0.5">{formatArea(area)}</p>}
        </div>
      </div>

      {/* 가격 그룹: 실입찰 기준가인 최저입찰가를 가장 크게, 감정가는 대비용으로 보조 표시 */}
      <div className="mt-3 flex items-end justify-between border-t border-gray-50 pt-3">
        <div>
          <p className="text-[0.6875rem] text-gray-400">최저입찰가</p>
          <p className="text-lg font-bold text-blue-600 leading-tight">{formatPrice(item.minimum_bid_price)}</p>
          <p className="text-[0.6875rem] text-gray-400 mt-0.5">감정가 {formatPrice(item.appraisal_price)}</p>
        </div>
        <div className="flex gap-1.5 shrink-0">
          <span className="text-xs font-medium text-gray-600 bg-gray-50 px-2 py-1 rounded-lg">
            최저가율 {formatBidRate(item.bid_rate)}
          </span>
          <span className="text-xs font-medium text-gray-600 bg-gray-50 px-2 py-1 rounded-lg">
            유찰 {item.fail_count}회
          </span>
        </div>
      </div>

      {/* 일정 그룹: 절대 매각기일 + 법원, 상대일수는 위 물건 그룹 배지로 이미 노출됨.
          법원명 길이가 들쭉날쭉해도 이 줄이 항상 한 줄로 유지되도록, 가변 길이인 법원명만
          truncate로 줄이고 나머지 고정 길이 항목은 줄바꿈되지 않게 고정한다.

          "조회수 -" 제거(2026-08-11 Sprint 52): `auction_table`에 조회수 컬럼이 없어
          **어떤 물건에서도 값이 채워질 수 없는** 자리였다. 값이 생길 가능성이 있는 빈 칸이
          아니라 구조적으로 항상 "-"인 죽은 UI라, 사용자에게 "집계가 안 되고 있다"는
          잘못된 인상만 주고 카드 폭을 차지했다. 조회수 기능이 실제로 생기면(스키마 + 집계)
          그때 다시 넣는다. */}
      <div className="mt-2 flex items-center justify-between gap-2 text-xs text-gray-400">
        <span className="min-w-0 truncate">{item.court_name || '-'}</span>
        <span className="shrink-0 whitespace-nowrap">{item.auction_date || '-'} 매각 · {item.status || '-'}</span>
      </div>
    </div>
    </Link>
  )
}

// basePath: 이 검색 화면이 렌더된 경로(`/` 또는 `/search`). Empty State의 "조건 없이 다시 보기"가
// 사용자를 다른 화면으로 옮기지 않고 **지금 있는 화면의 조건만** 비우도록 하기 위해 받는다
// (docs/FRONTEND_MASTER_SPEC.md §8.2 "검색 실행이 현재 pathname을 유지한다"와 같은 규칙).
//
// firstPageHref: 현재 검색조건은 그대로 두고 page만 뗀 URL. 아래 "페이지 범위 초과" 안내의
// 복구 동선으로 쓴다.
//
// hasFilters: 지금 검색조건이 하나라도 걸려 있는가(page/size/정렬은 조건으로 세지 않는다).
// 결과 0건일 때 "조건이 좁아서"인지 "살아있는 물건이 아예 없어서"인지 가르는 데 쓴다.
export default function ResultList({
  data,
  basePath,
  firstPageHref,
  hasFilters = true,
}: {
  data: SearchResponse
  basePath: string
  firstPageHref: string
  hasFilters?: boolean
}) {
  if (data.items.length === 0) {
    // 결과가 0건인 것과 **페이지 번호가 범위를 벗어난 것**은 원인도 해결책도 다르다.
    // 조건에 맞는 물건이 41건 있는데도 `?page=9`로 들어오면 예전에는 "검색 결과가 없습니다 /
    // 조건을 줄여보세요"라는 틀린 안내가 나오고, 복구 동선인 "조건 없이 전체 물건 보기"는
    // 사용자의 검색조건까지 버렸다. 북마크·공유 URL에서 실제로 도달한다 — 기본 필터가
    // `auction_date >= 오늘`이라 결과 건수가 매일 줄어들어, 어제 유효했던 3페이지 링크가
    // 오늘은 범위 밖이 될 수 있기 때문이다.
    if (data.total > 0) {
      return (
        <div className="text-center py-20">
          <p className="text-gray-500 font-medium">이 페이지에는 표시할 물건이 없습니다</p>
          <p className="mt-1 text-sm text-gray-400">
            조건에 맞는 물건은 총 {formatNumber(data.total)}건이지만, 요청한 페이지
            ({data.page}페이지)가 마지막 페이지({Math.max(data.total_pages, 1)}페이지)를 넘어섰습니다
          </p>
          <Link
            href={firstPageHref}
            className="mt-4 inline-block rounded-xl bg-blue-500 px-4 py-2 text-sm font-medium text-white"
          >
            검색조건 유지하고 1페이지로 이동
          </Link>
        </div>
      )
    }
    // 조건이 하나도 없는데 0건이면 원인은 사용자가 아니라 **데이터**다. 이때 "조건을
    // 줄여보세요"는 틀린 안내이고, "조건 없이 전체 물건 보기"는 이미 조건 없는 화면이라
    // 같은 빈 화면으로 되돌아오는 막다른 링크가 된다. 그래서 문구도 동선도 갈라 놓는다.
    // (기본 필터가 `auction_date >= 오늘`이라, 크롤이 멈추면 도달하는 상태다.)
    if (!hasFilters) {
      return (
        <div className="text-center py-20">
          <p className="text-gray-500 font-medium">현재 공개된 경매 물건이 없습니다</p>
          <p className="mt-1 text-sm text-gray-400">
            검색조건 때문이 아닙니다 — 매각기일이 남은 물건이 아직 등록되지 않았습니다.
            <br />
            새 물건은 법원 공고에 맞춰 갱신되니 잠시 후 다시 확인해 주세요
          </p>
        </div>
      )
    }
    // Empty State: 예전에는 회색 한 줄만 덩그러니 떠 있어서, 조건을 잘못 넣은 사용자가
    // 무엇을 해야 하는지도 어떻게 되돌리는지도 알 수 없었다. 원인 안내 + 복구 동선을 준다.
    return (
      <div className="text-center py-20">
        <p className="text-gray-500 font-medium">검색 결과가 없습니다</p>
        <p className="mt-1 text-sm text-gray-400">
          검색조건을 줄이거나 지역·가격 범위를 넓혀보세요
        </p>
        <Link
          href={basePath}
          className="mt-4 inline-block rounded-xl bg-gray-100 px-4 py-2 text-sm font-medium text-gray-600"
        >
          조건 없이 전체 물건 보기
        </Link>
      </div>
    )
  }

  // 같은 페이지 안에서 "다음/이전 물건"으로 이동할 수 있도록, 현재 결과 목록의 id 순서와
  // 클릭한 아이템의 인덱스를 Detail로 넘긴다. 페이지를 넘어가는 이동은 다루지 않는다
  // (다음 페이지 데이터는 이 화면이 아직 모르므로, 새 API 호출 없이는 알 수 없음).
  const ids = data.items.map((item) => item.id).join(',')

  return (
    <div>
      <p className="mb-2 px-1">
        <span className="text-sm font-bold text-blue-600">총 {formatNumber(data.total)}건</span>
        <span className="text-xs font-medium text-gray-600"> ({data.page}/{data.total_pages}페이지)</span>
      </p>
      {/* 목록 밀도(FRONTEND_MASTER_SPEC.md §6): 모바일 1열 / 태블릿 2열 / 데스크톱 3열.
          카드 자체의 정보 구성은 그대로 두고 배치만 바꾼다(§12.4 1단계). 카드 간격은
          카드의 mb-4 대신 grid gap으로 준다 — 열이 여러 개일 때 세로 간격만 남던 문제 방지.
          items-start: 같은 행에서 짧은 카드가 억지로 늘어나지 않게 한다. */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 items-start">
        {data.items.map((item, index) => (
          <ResultItemRow key={item.id} item={item} navQuery={`ids=${ids}&i=${index}`} />
        ))}
      </div>
    </div>
  )
}
