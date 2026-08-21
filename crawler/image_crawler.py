"""
물건 사진 수집 (selenium 의존 부분).

순수 규칙(경로/파싱/판정)은 전부 `crawler/image_assets.py`에 있다 — 이 파일은
"열려 있는 상세페이지 DOM에서 사진을 꺼내 디스크에 쓴다"만 한다.
`crawler/doc_crawler.py`가 문서에 대해 갖는 위치와 같고, 반환 형식도 그 모듈의
`_empty_result()` 계약을 그대로 따른다(doc_worker가 한 가지 모양만 다루면 되도록).

## 문서 수집과 근본적으로 다른 점

문서(spec/status/appraisal)는 **버튼을 눌러야** 나온다 — 새 탭이 열리거나 오버레이가
뜨고, 그래서 `config/settings.py:get_doc_button_id()`가 필요하다.
사진은 **버튼이 없다.** 상세페이지에 진입한 순간 캐러셀이 이미 DOM에 들어 있고,
각 `<img>`의 src가 곧 원본 바이트다(base64 data URI). 그래서 이 수집기는
클릭도, 탭 전환도, 다운로드 폴더 감시도 하지 않는다 — `wait_for_download()`류의
타이밍 문제 자체가 존재하지 않는다.

법원 서버에 추가 요청을 **한 번도** 보내지 않는다는 뜻이기도 하다(이미 받은 페이지를
읽을 뿐이다).
"""
import os
import time
import logging
import hashlib
from typing import Dict, List

from selenium.webdriver.common.by import By

from crawler.image_assets import (
    parse_image_alt,
    decode_image_data_uri,
    sniff_image_ext,
    read_image_dimensions,
    ensure_image_dir,
    image_filename,
    image_path,
    list_stored_images,
    ALLOWED_IMAGE_EXTS,
    MIN_IMAGE_BYTES,
)

logger = logging.getLogger(__name__)

# 캐러셀 이미지 요소. 실측으로 확인한 id 규칙
# (`mf_wfm_mainFrame_gen_pic_<N>_img_reltPic`)에서 **변하지 않는 꼬리**만 쓴다.
# 앞의 `mf_wfm_mainFrame_gen_pic_<N>`은 WebSquare가 붙이는 접두사+순번이라 화면 구성이
# 바뀌면 흔들릴 수 있지만, `_img_reltPic`은 컴포넌트 자체의 이름이다.
# (이 저장소의 "id를 추측하지 않는다" 원칙 — 실제로 본 것만 쓴다.)
IMAGE_ELEMENT_CSS = "img[id*='_img_reltPic']"

# 사진이 비동기로 채워질 수 있으므로 잠깐 기다린다. 문서 오버레이(15초)보다 짧게 잡는
# 이유는 사진이 페이지 본문과 함께 오는 것이라 늦게 와도 몇 초 안이기 때문이다.
IMAGE_WAIT_SECONDS = 6
IMAGE_POLL_INTERVAL = 0.5


def _empty_image_result() -> Dict:
    return {
        "success": False,
        "storage_type": "image",
        "files_saved": [],
        "images": [],
        "image_count": 0,
        "previous_hash": "",
        "new_hash": "",
        "partial": False,
        "no_asset": False,
    }


def _wait_for_images(driver) -> List:
    """캐러셀 이미지 요소가 나타날 때까지 잠깐 기다린다. 없으면 빈 리스트.

    **빈 리스트가 실패를 뜻하지 않는다** — 법원에 사진이 아예 없는 물건이 실제로 있다.
    그 구분은 호출부(`collect_images`)가 `no_asset`으로 표현한다.
    """
    waited = 0.0
    while waited < IMAGE_WAIT_SECONDS:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, IMAGE_ELEMENT_CSS)
        except Exception as e:
            logger.warning("사진 요소 조회 실패: %s", str(e))
            return []
        if els:
            return els
        time.sleep(IMAGE_POLL_INTERVAL)
        waited += IMAGE_POLL_INTERVAL
    return []


def _existing_set_hash(court_code: str, case_no: str, item_no: str) -> str:
    """지금 디스크에 있는 사진 집합의 지문. 없으면 "".

    `collect_images()` 가 끝에서 만드는 `new_hash` 와 **같은 공식**이어야 한다 —
    파일별 sha256을 순번 순으로 이어 붙여 다시 sha256. 공식이 갈라지면 매 수집이
    "변경됨"으로 보이거나(거짓 개정) 영원히 "같음"으로 보인다(개정 누락).

    왜 필요한가 — 예전에는 `previous_hash` 가 항상 "" 였다. 그래서
    `mark_queue_done()` 의 변경 감지 조건 `if previous_hash and previous_hash != new_hash`
    가 **이미지에서는 영원히 거짓**이었고, 재수집을 켜도 사진 교체가
    `document_version_log` 에 남지 않았다. 문서 수집기는 같은 자리에서 이미
    `calc_file_hash()` 로 계산하고 있다(`crawler/doc_crawler.py`).

    DB가 아니라 파일시스템을 근거로 삼는다 — 이 모듈은 크롤러 계층이라 storage 에
    의존하지 않고, "실제로 서빙되는 바이트"가 곧 비교 대상이기 때문이다.
    """
    rows = list_stored_images(court_code, case_no, item_no)
    if not rows:
        return ""
    # 같은 순번이 두 파일로 존재하면 비교 자체를 포기한다 (2026-08-18 Sprint 189, BUGS #120).
    #
    # 수집 쪽 `new_hash`는 **순번당 한 장**을 전제로 만들어진다(`saved_images`는 seq를
    # 중복 없이 담는다). 그런데 디스크에는 확장자가 다른 같은 순번 파일이 남을 수 있었다 —
    # 법원이 사진을 다른 형식으로 바꿔 끼우면 `01.jpg` 옆에 `01.png`가 생겼다. 그 상태로
    # 이어 붙이면 디스크 쪽은 2개, 수집 쪽은 1개를 해시해 **두 공식이 영원히 갈라진다**
    # (매 수집이 거짓 개정이 되어 진짜 개정을 찾을 수 없다 — 이 함수 docstring의 바로 그 경고).
    #
    # 아래 `_write_image_atomically()`가 이제 그 잔재를 만들지 않지만, 이 함수 자체도
    # "반쪽 지문으로 비교하지 않는다"는 같은 규칙을 지킨다(OSError 분기와 같은 판단).
    seqs = [r["seq"] for r in rows]
    if len(set(seqs)) != len(seqs):
        dup = sorted({q for q in seqs if seqs.count(q) > 1})
        logger.warning(
            "[%s-%s] 같은 순번의 사진 파일이 둘 이상이다(순번 %s) - 지문 비교를 건너뛴다",
            case_no, item_no, dup)
        return ""
    digests = []
    for r in rows:
        try:
            with open(r["path"], "rb") as f:
                digests.append(hashlib.sha256(f.read()).hexdigest())
        except OSError:
            # 읽을 수 없는 파일이 있으면 비교 자체를 포기한다. 반쪽 지문으로
            # 비교하면 바뀌지 않았는데 "변경됨"으로 기록된다.
            return ""
    return hashlib.sha256("".join(digests).encode("ascii")).hexdigest()


def _same_bytes_on_disk(dest: str, digest: str) -> bool:
    """목적지 파일의 내용이 `digest`(sha256)와 같으면 True. 읽을 수 없으면 False.

    False는 "다르다"가 아니라 **"같다고 말할 수 없다"**는 뜻이다 — 그때는 호출부가
    정상 저장 경로로 떨어진다(판단이 안 서면 받은 것을 쓰는 쪽이 안전하다).
    """
    try:
        if not os.path.isfile(dest):
            return False
        with open(dest, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest() == digest
    except OSError:
        return False



def collect_images(driver, court_code: str, case_no: str, item_no: str,
                   overwrite: bool = False) -> Dict:
    """열려 있는 상세페이지에서 물건 사진을 전부 저장한다.

    돌려주는 값은 `doc_crawler._empty_result()`와 같은 모양에 사진 전용 필드가 붙은 것:

        success      한 장이라도 저장했거나, **사진이 없다는 사실을 확인**했으면 True
        no_asset     법원에 사진이 한 장도 없어서 저장할 것이 없었으면 True
                     (실패가 아니다 — 재시도해도 결과가 같다)
        images       [{"seq","kind","path","file_size","file_hash","width","height"}, ...]
        partial      일부만 저장됐으면 True(나머지는 다음 수집 때 다시 시도된다)

    부분 성공을 전체 성공으로 뭉개지 않는다 — 5장 중 3장만 저장됐다면 success=True,
    partial=True다. 큐에서는 종결되지만 로그와 반환값에 사실이 남는다.
    """
    result = _empty_image_result()

    # 수집(=덮어쓰기) **전에** 기존 집합의 지문을 떠 둔다. 저장이 시작된 뒤에 재면
    # 이미 새 바이트라 항상 같은 값이 나온다.
    result["previous_hash"] = _existing_set_hash(court_code, case_no, item_no)

    els = _wait_for_images(driver)
    if not els:
        # 사진 요소가 하나도 없다. 재시도로 달라지지 않는 정상 상태다.
        logger.info("[%s-%s] 물건 사진 없음(법원 원천에 사진 미제공)", case_no, item_no)
        result["success"] = True
        result["no_asset"] = True
        return result

    # 같은 순번을 두 요소가 주장하면(캐러셀이 썸네일까지 같은 id 규칙으로 그리는 경우 등)
    # 먼저 나온 것을 쓴다. 순번은 `UNIQUE(item_id, seq)`의 키라 조용히 덮어쓰면
    # 어느 사진이 남았는지 알 수 없게 된다.
    written = 0        # 이번에 **실제로 디스크에 쓴** 장수
    unchanged = 0      # 바이트가 같아 건드리지 않은 장수
    saved_images: List[Dict] = []

    # ------------------------------------------------------------------
    # 1차 통과 — 후보를 모으고 **순번마다 가장 큰 것**을 고른다
    #
    # ## 왜 "먼저 나온 것"이 아니라 "가장 큰 것"인가 (2026-08-21 Sprint 243)
    #
    # 예전에는 같은 순번이 두 번 나오면 **먼저 나온 것을 쓰고 뒤엣것을 버렸다.**
    # 그런데 이 파일의 옛 주석이 그 위험을 이미 적어 두고 있었다 —
    # *"캐러셀이 썸네일까지 같은 id 규칙으로 그리는 경우"*. 그 경우 DOM 순서상
    # **썸네일이 먼저** 나오는 것이 자연스럽고, 그러면 우리는 큰 사진을 눈앞에 두고
    # 작은 것을 저장한다. 조용히, 로그도 남기지 않고.
    #
    # 크기 비교로 고르면 그 위험이 사라진다. 후보가 하나뿐이면 동작은 **완전히 같다**
    # (지금 운영 데이터가 그 상태다 - 2026-08-21 실측 45장 전부 긴 변 700px 단일 후보).
    #
    # ## 동시에 이것은 **증거 수집기**다
    #
    # "법원이 더 큰 원본을 주는데 우리가 썸네일을 받는가?"(B/C 가설)는 지금 저장된
    # 파일만으로는 판정할 수 없다. 실제 법원 페이지를 다시 열어야 하는데 그것은
    # 승인 영역이다. 그래서 **다음 실크롤이 스스로 답하게** 만든다 —
    # 순번마다 후보가 둘 이상이면 각각의 해상도를 로그에 남긴다.
    # ------------------------------------------------------------------
    candidates = {}          # seq -> list of dict(가장 큰 것을 고른다)
    # ★ `attempted` 는 **alt 가 사진으로 파싱된 순번의 수**다 - 디코드/저장 실패까지
    #   포함한다. 이것이 `partial`(= 저장한 장수 < 시도한 장수)의 분모이기 때문이다.
    #   후보 수(`len(candidates)`)로 세면 **디코드에 실패한 장이 시도에서 빠져**
    #   5장 중 3장만 저장돼도 partial=False 가 된다(2026-08-21 회귀로 확인).
    seen_seq = set()
    skipped_alt = []         # alt 규칙에 안 맞아 건너뛴 요소(형태만 기록)
    skipped_src = []         # data URI 가 아니어서 건너뛴 요소

    for el in els:
        try:
            alt = el.get_attribute("alt") or ""
            src = el.get_attribute("src") or ""
        except Exception as e:
            logger.warning("[%s-%s] 사진 속성 읽기 실패: %s", case_no, item_no, str(e))
            continue

        parsed = parse_image_alt(alt)
        if not parsed:
            # 캐러셀 밖의 아이콘 등. 사진이 아니므로 시도 횟수에도 세지 않는다.
            # ★ 다만 **무엇을 건너뛰었는지는 남긴다** - 법원이 더 큰 사진을 다른 alt
            #   규칙으로 붙이기 시작하면 그 사실이 로그에 드러나야 한다.
            if src.startswith("data:image") and len(src) > 5000:
                skipped_alt.append((alt[:40], len(src)))
            continue
        kind, seq = parsed
        seen_seq.add(seq)

        data = decode_image_data_uri(src)
        if data is None:
            logger.warning("[%s-%s] 사진 %d: data URI가 아니거나 디코드 실패(앞 40자=%r)",
                           case_no, item_no, seq, src[:40])
            skipped_src.append((seq, src[:40]))
            continue

        if len(data) < MIN_IMAGE_BYTES:
            logger.warning("[%s-%s] 사진 %d: 너무 작다(%d바이트) - 저장하지 않는다",
                           case_no, item_no, seq, len(data))
            continue

        # ★ 선언된 MIME이 아니라 실제 바이트로 확장자를 정한다.
        #   법원은 JPEG를 image/png로 선언한다(image_assets.py 모듈 주석의 실측).
        ext = sniff_image_ext(data)
        if not ext:
            logger.warning("[%s-%s] 사진 %d: 알 수 없는 이미지 형식 - 저장하지 않는다",
                           case_no, item_no, seq)
            continue

        w, h = read_image_dimensions(data)
        candidates.setdefault(seq, []).append(
            {"kind": kind, "data": data, "ext": ext, "alt": alt,
             "w": w or 0, "h": h or 0, "area": (w or 0) * (h or 0)})

    if skipped_alt:
        logger.warning("[%s-%s] alt 규칙에 맞지 않는 **큰 data:image 요소** %d개를 건너뛰었다 "
                       "(법원 DOM 변경/고해상도 변형 가능성): %s",
                       case_no, item_no, len(skipped_alt), skipped_alt[:3])

    attempted = len(seen_seq)
    chosen = {}
    for seq, cands in candidates.items():
        # 가장 큰 면적 -> 같으면 바이트가 큰 것. 결정적으로 고른다(DOM 순서에 의존하지 않는다).
        best = max(cands, key=lambda c: (c["area"], len(c["data"])))
        chosen[seq] = best
        if len(cands) > 1:
            logger.warning(
                "[%s-%s] 사진 %d: 후보 %d개 - **가장 큰 것을 고른다** %s -> %dx%d(%dB)",
                case_no, item_no, seq, len(cands),
                ["%dx%d(%dB)" % (c["w"], c["h"], len(c["data"])) for c in cands],
                best["w"], best["h"], len(best["data"]))

    # ------------------------------------------------------------------
    # 2차 통과 — 고른 것만 디스크에 쓴다 (아래 로직은 종전과 동일)
    # ------------------------------------------------------------------
    for seq in sorted(chosen):
        best = chosen[seq]
        kind, data, ext = best["kind"], best["data"], best["ext"]

        dest = image_path(court_code, case_no, item_no, seq, ext)
        if not overwrite and os.path.isfile(dest) and os.path.getsize(dest) >= MIN_IMAGE_BYTES:
            # 이미 받아 둔 사진은 다시 쓰지 않는다(불필요한 중복 다운로드/디스크 쓰기 방지).
            # 그래도 DB에는 실체를 다시 알려 줘야 한다 — 파일은 있는데 `auction_image`
            # 행만 없는 상태(이 저장소의 단골 결함)를 여기서 스스로 복구한다.
            existing = _describe_existing(dest, seq, kind)
            if existing:
                saved_images.append(existing)
                unchanged += 1
            continue

        digest = hashlib.sha256(data).hexdigest()

        # ★ 재수집이어도 **바이트가 같으면 쓰지 않는다** (2026-08-18 Sprint 189).
        #
        #   법원 사진은 base64로 페이지에 박혀 오므로 "다시 받는 비용"은 0이다. 그런데
        #   같은 바이트를 다시 쓰면 **mtime이 바뀐다.** 서빙 쪽 ETag는 Starlette가
        #   (mtime, size)로 만들기 때문에(`api/v1/images.py`), 내용이 그대로여도
        #   **모든 브라우저 캐시가 무효화되어 물건당 약 1.3~1.9MB를 다시 내려받는다**
        #   (`api/http_cache.py`가 조건부 요청으로 아끼려던 바로 그 바이트다).
        #   재수집 대상 물건은 정의상 "사용자가 지금 보고 있는" 물건이라 체감도 크다.
        #
        #   그래서 재수집에서도 **실제로 달라진 장만** 쓴다. 판정은 확장자가 아니라
        #   바이트 지문으로 한다 — 크기만 비교하면 같은 크기의 다른 사진을 놓친다.
        if overwrite and _same_bytes_on_disk(dest, digest):
            existing = _describe_existing(dest, seq, kind)
            if existing:
                saved_images.append(existing)
                unchanged += 1
                continue
            # 읽지 못했으면 판단 근거가 없다 -> 아래 정상 저장 경로로 떨어진다.

        if not _write_image_atomically(dest, data, court_code, case_no,
                                       item_no, seq, ext):
            continue
        written += 1

        w, h = best["w"], best["h"]
        saved_images.append({
            "seq": seq,
            "kind": kind,
            "path": dest,
            "file_size": len(data),
            "file_hash": digest,
            "width": w,
            "height": h,
        })

    result["images"] = sorted(saved_images, key=lambda r: r["seq"])
    result["files_saved"] = [r["path"] for r in result["images"]]
    result["image_count"] = len(result["images"])
    # 호출부/회귀가 "실제로 썼는가"를 로그 파싱 없이 확인할 수 있게 한다.
    result["written"] = written
    result["unchanged"] = unchanged

    if attempted == 0:
        # 사진처럼 보이는 요소는 있었지만 alt 규칙에 맞는 것이 하나도 없었다.
        # 이것은 "사진 없음"이 아니라 **DOM 규칙이 바뀌었다**는 신호다 — 조용히 성공으로
        # 넘기면 그날 이후 모든 물건의 사진이 사라진 것을 아무도 모르게 된다.
        logger.error("[%s-%s] 사진 요소 %d개를 찾았지만 alt 규칙(<종류>_<순번>)에 맞는 것이 "
                     "하나도 없다 - 법원 DOM 변경 가능성. 실패로 처리한다",
                     case_no, item_no, len(els))
        return result

    if not result["images"]:
        logger.warning("[%s-%s] 사진 %d장을 시도했지만 한 장도 저장하지 못했다",
                       case_no, item_no, attempted)
        return result

    result["success"] = True
    result["partial"] = len(result["images"]) < attempted

    # ★ 법원이 사진 수를 줄였으면 **파일도** 정리한다 (2026-08-18 Sprint 191, BUGS #127).
    #
    #   `save_auction_images()`는 DB 행만 지운다. 파일은 아무도 안 지웠다. 그 결과:
    #
    #     고아 파일   auction_image 가 가리키지 않는 파일이 디스크에 영원히 남는다
    #     거짓 개정   `_existing_set_hash()`는 **파일시스템**을 근거로 삼으므로 옛 파일까지
    #                 세고, 수집 쪽 공식(이번에 받은 것만)과 갈라진다
    #                 -> 이후 매 수집이 "변경됨" (BUGS #120과 **완전히 같은 실패 방식**)
    #
    #   재현(2026-08-18): 5장 -> 3장으로 줄인 뒤 재수집하면 디스크에 5개가 그대로 남고
    #   previous_hash(5장 기준) != new_hash(3장 기준)가 영구히 성립했다.
    #
    #   **부분 수집이면 절대 지우지 않는다** — `save_auction_images(complete=)`가 DB에서
    #   지키는 것과 같은 규칙이다. "법원이 줄였다"와 "일부만 받아졌다"는 구별할 수 없을 때
    #   남기는 쪽이 안전하다(지운 파일은 되돌릴 수 없다).
    if not result["partial"]:
        _remove_files_not_in(court_code, case_no, item_no,
                             {r["seq"] for r in result["images"]})
    # 사진 집합 전체의 지문. 개별 파일 해시를 순번 순으로 이어 붙여 다시 해시한다 —
    # 한 장이라도 바뀌면 값이 바뀌므로 `document_version_log`의 변경 감지가 그대로 동작한다.
    result["new_hash"] = hashlib.sha256(
        "".join(r["file_hash"] for r in result["images"]).encode("ascii")
    ).hexdigest()

    if result["partial"]:
        logger.warning("[%s-%s] 사진 부분 수집: %d/%d장",
                       case_no, item_no, len(result["images"]), attempted)
    else:
        # ★ 로그가 사실이 아닌 것을 말하지 않게 한다 (2026-08-18 Sprint 190).
        #   무변경 스킵이 생긴 뒤로는 "5장 저장 완료"가 **한 장도 안 썼을 때도** 찍혔다.
        #   이 저장소가 BUGS #47(배치가 실패를 성공으로 보고) 이래 반복해 잡아 온
        #   "로그가 거짓을 말한다" 부류다 — 실측으로 실제 실행에서 확인했다.
        logger.info("[%s-%s] 사진 %d장 확보 (신규/변경 %d장 기록, 무변경 %d장 그대로)",
                    case_no, item_no, len(result["images"]), written, unchanged)
    return result


def _describe_existing(dest: str, seq: int, kind: str):
    """이미 있는 파일을 다시 읽어 DB에 넣을 정보를 만든다. 실패하면 None."""
    try:
        with open(dest, "rb") as f:
            data = f.read()
    except OSError as e:
        logger.warning("기존 사진 파일을 읽지 못했다 (%s): %s", dest, str(e))
        return None
    w, h = read_image_dimensions(data)
    return {
        "seq": seq,
        "kind": kind,
        "path": dest,
        "file_size": len(data),
        "file_hash": hashlib.sha256(data).hexdigest(),
        "width": w,
        "height": h,
    }


def _remove_files_not_in(court_code: str, case_no: str, item_no: str,
                         keep_seqs) -> int:
    """이번에 확보한 순번에 **없는** 사진 파일을 지운다. 지운 개수를 돌려준다.

    2026-08-18 Sprint 191 (BUGS #127). `_remove_other_ext_for_seq()`가 "같은 순번의
    다른 확장자"를 맡는다면, 이 함수는 "이제 존재하지 않는 순번"을 맡는다. 둘을 합치면
    **디스크의 사진 집합 == 이번에 법원이 준 사진 집합**이 되고, 그래야
    `_existing_set_hash()`(파일시스템 근거)와 수집 쪽 `new_hash`가 같은 것을 센다.

    `seq > max_seq`가 아니라 **집합 차집합**으로 판단한다 — 법원이 가운데 순번을 빼는
    경우(1,2,4)를 `>` 비교는 못 잡는다. `save_auction_images()`의 DB 행 삭제도 같은
    기준으로 맞춰 두 근거가 갈라지지 않게 했다.

    호출부가 `partial` 여부를 이미 판단하고 부르므로 여기서는 다시 보지 않는다 —
    판단이 두 곳에 있으면 갈라진다.
    """
    removed = 0
    for row in list_stored_images(court_code, case_no, item_no):
        if row["seq"] in keep_seqs:
            continue
        try:
            os.remove(row["path"])
            removed += 1
            logger.info("[%s-%s] 사진 %d: 법원 원천에서 사라져 파일 정리(%s)",
                        case_no, item_no, row["seq"], os.path.basename(row["path"]))
        except OSError as e:
            # 지우지 못해도 이번 수집 자체는 성공이다. 다만 다음 지문 비교가 중복/잉여
            # 순번을 발견해 경고를 남기므로 조용히 묻히지는 않는다.
            logger.warning("[%s-%s] 사진 %d: 옛 파일 정리 실패(%s): %s",
                           case_no, item_no, row["seq"], row["path"], str(e))
    return removed


def _remove_other_ext_for_seq(dest: str, court_code: str, case_no: str, item_no: str,
                              seq: int, ext: str) -> int:
    """같은 순번의 **다른 확장자** 파일을 지운다. 지운 개수를 돌려준다.

    2026-08-18 Sprint 189 (BUGS #120). 파일 이름이 `<순번>.<확장자>`라 확장자가 곧
    이름의 일부다. 법원이 같은 자리 사진을 다른 형식으로 바꿔 끼우면
    (`sniff_image_ext()`는 **선언된 MIME이 아니라 실제 바이트**로 판정하므로 그 변화를
    그대로 따라간다) 새 파일은 `01.png`에 쓰이고 **옛 `01.jpg`는 그대로 남았다.**

    남는 것만으로 끝나지 않는다:

        auction_image   UNIQUE(item_id, seq)라 DB는 새 경로 한 줄만 갖는다
                        -> 옛 파일은 아무도 가리키지 않는 고아가 된다
        지문 비교        `_existing_set_hash()`가 같은 순번을 두 번 세어
                        수집 쪽 공식과 갈라진다 -> **매 수집이 거짓 개정**

    즉 재수집을 켜는 순간(=이번 Sprint의 목표) 곧바로 도달하는 경로다. 쓰기 성공
    **직후**에 정리한다 — 먼저 지우면 새 파일 쓰기가 실패했을 때 사용자가 보던 사진이
    사라진다(부분 수집 보호와 같은 원칙: 판단할 수 없을 때는 남기는 쪽).
    """
    removed = 0
    for other in ALLOWED_IMAGE_EXTS:
        if other == ext:
            continue
        stale = image_path(court_code, case_no, item_no, seq, other)
        if stale == dest or not os.path.isfile(stale):
            continue
        try:
            os.remove(stale)
            removed += 1
            logger.info("[%s-%s] 사진 %d: 형식이 %s -> %s로 바뀌어 옛 파일 정리(%s)",
                        case_no, item_no, seq, other, ext, os.path.basename(stale))
        except OSError as e:
            # 지우지 못해도 새 파일 저장 자체는 성공이다. 다만 위 지문 비교가
            # 중복 순번을 발견해 경고를 남기므로 조용히 묻히지는 않는다.
            logger.warning("[%s-%s] 사진 %d: 옛 파일 정리 실패(%s): %s",
                           case_no, item_no, seq, stale, str(e))
    return removed


def _write_image_atomically(dest: str, data: bytes, court_code: str, case_no: str,
                            item_no: str, seq: int, ext: str) -> bool:
    """임시 파일에 쓰고 `os.replace()`로 원자적 교체.

    `doc_crawler.collect_status()`가 status.html/json에 쓰는 것과 **같은 불변식**이다:
    목적지에 직접 쓰면 쓰는 도중 프로세스가 죽었을 때(전원 차단·OOM kill 등 except로
    잡을 수 없는 죽음) 잘린 파일이 목적지에 남는다. 그러면 다음 수집이
    "이미 있다"고 판정해 **깨진 사진이 영구히 남는다** — 이 저장소가 BUGS #22/#50/#61로
    반복해 겪은 함정이다. os.replace()는 같은 파일시스템 안에서 원자적이라
    그 중간 상태 자체가 존재할 수 없다.
    """
    try:
        ensure_image_dir(court_code, case_no, item_no)
        tmp = dest + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        _remove_other_ext_for_seq(dest, court_code, case_no, item_no, seq, ext)
        return True
    except OSError as e:
        logger.warning("사진 저장 실패 (%s, seq=%d, %s): %s",
                       case_no, seq, image_filename(seq, ext), str(e))
        try:
            os.remove(dest + ".tmp")
        except OSError:
            pass
        return False
