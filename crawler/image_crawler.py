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
    seen_seq = set()
    attempted = 0
    saved_images: List[Dict] = []

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
            continue
        kind, seq = parsed

        if seq in seen_seq:
            logger.warning("[%s-%s] 사진 순번 중복(seq=%d, alt=%r) - 뒤엣것을 무시",
                           case_no, item_no, seq, alt)
            continue
        seen_seq.add(seq)
        attempted += 1

        data = decode_image_data_uri(src)
        if data is None:
            logger.warning("[%s-%s] 사진 %d: data URI가 아니거나 디코드 실패(앞 40자=%r)",
                           case_no, item_no, seq, src[:40])
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

        dest = image_path(court_code, case_no, item_no, seq, ext)
        if not overwrite and os.path.isfile(dest) and os.path.getsize(dest) >= MIN_IMAGE_BYTES:
            # 이미 받아 둔 사진은 다시 쓰지 않는다(불필요한 중복 다운로드/디스크 쓰기 방지).
            # 그래도 DB에는 실체를 다시 알려 줘야 한다 — 파일은 있는데 `auction_image`
            # 행만 없는 상태(이 저장소의 단골 결함)를 여기서 스스로 복구한다.
            existing = _describe_existing(dest, seq, kind)
            if existing:
                saved_images.append(existing)
            continue

        written = _write_image_atomically(dest, data, court_code, case_no, item_no, seq, ext)
        if not written:
            continue

        w, h = read_image_dimensions(data)
        saved_images.append({
            "seq": seq,
            "kind": kind,
            "path": dest,
            "file_size": len(data),
            "file_hash": hashlib.sha256(data).hexdigest(),
            "width": w,
            "height": h,
        })

    result["images"] = sorted(saved_images, key=lambda r: r["seq"])
    result["files_saved"] = [r["path"] for r in result["images"]]
    result["image_count"] = len(result["images"])

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
    # 사진 집합 전체의 지문. 개별 파일 해시를 순번 순으로 이어 붙여 다시 해시한다 —
    # 한 장이라도 바뀌면 값이 바뀌므로 `document_version_log`의 변경 감지가 그대로 동작한다.
    result["new_hash"] = hashlib.sha256(
        "".join(r["file_hash"] for r in result["images"]).encode("ascii")
    ).hexdigest()

    if result["partial"]:
        logger.warning("[%s-%s] 사진 부분 수집: %d/%d장",
                       case_no, item_no, len(result["images"]), attempted)
    else:
        logger.info("[%s-%s] 사진 %d장 저장 완료", case_no, item_no, len(result["images"]))
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
        return True
    except OSError as e:
        logger.warning("사진 저장 실패 (%s, seq=%d, %s): %s",
                       case_no, seq, image_filename(seq, ext), str(e))
        try:
            os.remove(dest + ".tmp")
        except OSError:
            pass
        return False
