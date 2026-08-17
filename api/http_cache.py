"""조건부 요청(304 Not Modified) 처리 — 2026-08-17 Sprint 146 신설.

## 왜 필요한가 (실측)

`api/v1/images.py` / `api/v1/documents.py`는 둘 다 Starlette `FileResponse`로 파일을
내려준다. `FileResponse`는 `etag`와 `last-modified`를 **자동으로 붙여 주지만**,
조건부 요청을 **해석하지는 않는다**(설치본 확인: `starlette 1.3.1`의 `FileResponse`
소스에 `if-none-match` / `304` 처리가 없다 — `if-range`만 다룬다).

그래서 브라우저가 검증자를 그대로 되보내도 서버가 전체 본문을 다시 보낸다.
2026-08-17 실측:

    GET  /api/v1/item/502/images/1                    200  70,100 bytes
    GET  같은 URL + If-None-Match: <그 etag>          200  70,100 bytes   <- 304여야 한다
    GET  /api/v1/item/502/documents/APPRAISAL         200  2,528,908 bytes
    GET  같은 URL + If-None-Match: <그 etag>          200  2,528,908 bytes
    GET  같은 URL + If-Modified-Since: <그 날짜>      200  2,528,908 bytes

`Cache-Control`도 없어서 브라우저는 휴리스틱 캐싱에 맡겨진다.

영향이 가장 큰 곳은 **검색 결과 목록**이다. 검색 카드의 썸네일이 원본 사진을 그대로
쓰므로(서버 측 썸네일 생성은 Pillow 미선언으로 SKIP 상태), 실측 기준 1페이지가
평균 104 KB × 20 = **약 2 MB**다. 조건부 요청이 동작하지 않으면 같은 사진을 페이지를
넘길 때마다 **매번 다시 받는다.**

## 무엇을 하고 무엇을 하지 않는가

- **한다**: 클라이언트가 보낸 검증자가 현재 파일의 것과 같으면 본문 없이 `304`를 준다.
  바이트만 아끼고 **신선도 판단은 바꾸지 않는다** — 클라이언트는 여전히 매번 서버에
  물어본다. 그래서 "오래된 문서가 보인다" 같은 부작용이 원리적으로 없다.
- **하지 않는다**: `Cache-Control: max-age=...`를 임의로 정하지 않는다. 그것은 "사용자가
  며칠 지난 사진을 봐도 되는가"라는 **제품 판단**이고, 재수집 정책이 아직 미정이다
  (`document_version_log`가 구조적으로 도달 불가인 상태 — Sprint 145 §6). 정해지면
  이 모듈에 한 줄로 붙일 수 있다.

RFC 9110 §13.1.1~13.1.3을 따른다 — `If-None-Match`가 있으면 그것만 보고,
없을 때만 `If-Modified-Since`를 본다(둘 다 있으면 전자가 우선).
"""
from __future__ import annotations

import email.utils
from typing import Optional

from fastapi import Request, Response


def _parse_if_none_match(value: str) -> list[str]:
    """`If-None-Match` 헤더를 ETag 목록으로. `W/` 접두사는 떼고 비교한다.

    약한 비교(weak comparison)를 쓴다 — RFC 9110 §13.1.2가 `If-None-Match`에는
    약한 비교를 쓰라고 정한다. 우리는 Range 요청을 이 경로로 처리하지 않으므로
    강한 검증자가 필요 없다.
    """
    out = []
    for part in value.split(","):
        tag = part.strip()
        if tag.startswith(("W/", "w/")):
            tag = tag[2:]
        if tag:
            out.append(tag)
    return out


def _http_date_to_timestamp(value: str) -> Optional[float]:
    """HTTP-date -> epoch. 파싱 실패하면 None(= 조건을 무시하고 200을 준다)."""
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    return parsed.timestamp()


def not_modified(request: Request, response: Response) -> Optional[Response]:
    """이 요청에 304를 줘도 되면 304 응답을, 아니면 None을 돌려준다.

    `response`는 **이미 만들어진 `FileResponse`**여야 한다 — 검증자(`etag`/
    `last-modified`)를 그 응답이 계산해 헤더에 넣어 두기 때문이다. 즉 이 함수는
    검증자를 새로 만들지 않는다(규칙이 두 벌이 되는 것을 피한다).

    304 응답에는 검증자를 그대로 다시 실어 준다 — RFC 9110 §15.4.5가 요구한다.
    본문은 넣지 않는다(`Response(status_code=304)`는 본문 없는 응답이다).

    ## HEAD에는 304를 주지 않는다 (의도된 예외)

    HEAD 응답에는 **애초에 본문이 없으므로 304로 아낄 바이트가 0이다.** 반면 위험은
    있다 — 프런트가 문서 뷰어를 열기 전에 존재 확인을 이렇게 한다:

        fetch(`.../documents/${type}`, { method: 'HEAD' })
          .then(res => res.ok ? 'ok' : 'notfound')      // src/app/properties/[id]/page.tsx

    `res.ok`는 200~299에서만 참이다. 브라우저는 `cache: "default"`에서 재검증 304를
    JS에 노출하지 않고 캐시된 200을 돌려주므로 **정상 경로에서는 문제가 없지만**,
    이득이 0인 자리에 그 의존을 남길 이유가 없다. 얻는 것이 없으면 위험도 만들지 않는다.
    """
    if request.method.upper() == "HEAD":
        return None

    etag = response.headers.get("etag")
    last_modified = response.headers.get("last-modified")

    matched = False
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None:
        # `*`는 "표현이 존재하기만 하면 조건 실패" — 여기까지 왔다는 것은 파일이
        # 실제로 있다는 뜻이므로 304다.
        candidates = _parse_if_none_match(if_none_match)
        matched = "*" in candidates or (etag is not None and etag in candidates)
    else:
        # If-None-Match가 **없을 때만** If-Modified-Since를 본다(RFC 9110 §13.1.3).
        if_modified_since = request.headers.get("if-modified-since")
        if if_modified_since is not None and last_modified is not None:
            client_ts = _http_date_to_timestamp(if_modified_since)
            file_ts = _http_date_to_timestamp(last_modified)
            # 초 단위로만 비교한다 — HTTP-date의 해상도가 1초다.
            if client_ts is not None and file_ts is not None:
                matched = file_ts <= client_ts

    if not matched:
        return None

    headers = {}
    if etag:
        headers["etag"] = etag
    if last_modified:
        headers["last-modified"] = last_modified
    return Response(status_code=304, headers=headers)
