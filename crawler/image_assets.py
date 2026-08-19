"""
물건 사진(경매물건 이미지) 자산 규칙 — 순수 로직, 외부 의존성 없음.

`crawler/doc_paths.py`가 문서(spec/status/appraisal)에 대해 하는 일을 사진에 대해 한다.
같은 이유로 selenium/DB/fastapi를 import하지 않는다 — 경로 규칙과 파싱만 필요한 쪽
(회귀 테스트, `api/v1/images.py`의 서빙)이 selenium 설치를 강요받지 않아야 한다.
selenium이 필요한 실제 수집은 `crawler/image_crawler.py`가 담당한다.

## 2026-08-17 Sprint 144 — 법원 원천 실측으로 확정한 사실

`courtauction.go.kr` 물건상세(PGJ151F00) 페이지의 사진 캐러셀을 실제 브라우저로 열어
DOM을 직접 확인했다(3개 사건 표본: 2024타경3528 / 2022타경101244 / 2023타경110870).

    DIV.img_slider
      UL#mf_wfm_mainFrame_gen_pic.list
        LI
          A#mf_wfm_mainFrame_gen_pic_<N>_grp_imgPopup
            IMG#mf_wfm_mainFrame_gen_pic_<N>_img_reltPic
                alt = "<종류>_<순번>"      예: "전경도_1", "위치도_4", "관련사진_5"
                src = "data:image/png;base64,...."

★ 결정적으로 중요한 두 가지 —

1. **다운로드할 URL이 없다.** 사진은 별도 파일 URL이 아니라 **페이지 안에 base64
   data URI로 박혀서** 온다. 그래서 이 파이프라인에는 "URL 획득 → HTTP 다운로드"
   단계가 **존재하지 않는다**(문서 수집과 근본적으로 다른 점이다). DOM에서 문자열을
   읽어 디코드하면 그것이 곧 원본 바이트다. 추가 HTTP 요청이 0회라 법원 서버에
   주는 부하도 늘지 않는다.

2. **선언된 MIME이 틀렸다.** src는 `data:image/png;base64,`라고 선언하는데 실제
   바이트는 전부 JPEG였다(base64가 `/9j/`로 시작 = `FF D8 FF`). 표본 15장 전부
   그랬다. 그래서 확장자를 **선언값에서 가져오면 안 된다** — `.png`로 저장된 JPEG
   파일이 쌓이고, 나중에 확장자를 믿는 코드가 조용히 틀린다. 이 모듈은 항상
   **매직 바이트로 판정**한다(`sniff_image_ext`).

크기 실측: 장당 base64 150KB~640KB(디코드 후 약 110KB~475KB), 물건당 5장 기준
합계 1.3MB~1.9MB. 규모 추정은 docs/SPRINT144_ASSET_PIPELINE.md 참고.
"""
import os
import re
import base64
import struct
from typing import Optional, Tuple, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCUMENT_ROOT = os.path.join(PROJECT_ROOT, "documents")

# 사진은 문서와 같은 물건 디렉터리 **아래 한 단계**에 모은다.
#   documents/<법원>/<사건>/<물건>/images/01.jpg
# 문서 파일(spec.pdf/status.html/...)과 같은 폴더에 섞지 않는 이유는 개수가 다르기
# 때문이다 — 문서는 종류당 1개로 고정이지만 사진은 0~N개라, 같은 폴더에 두면
# `doc_exists()` 계열의 "이 폴더에 무엇이 있나" 판정이 사진 개수에 따라 흔들린다.
IMAGE_DIR_NAME = "images"

# alt 텍스트에서 읽어내는 사진 종류. 실측에서 확인된 값들이다.
# 여기 없는 종류가 와도 **버리지 않는다** — 원문 그대로 kind에 담는다(아래 parse_image_alt).
# 법원이 새 종류를 추가했을 때 조용히 사진을 잃는 것이 가장 나쁜 실패 방식이기 때문이다.
KNOWN_IMAGE_KINDS = ("전경도", "위치도", "관련사진", "내부구조도", "지적도", "구조도")

# "전경도_1" / "위치도_4" — 종류와 **전체 순번**(종류별이 아니라 캐러셀 전체 기준)이다.
# 실측: 전경도_1, 전경도_2, 전경도_3, 관련사진_4, 관련사진_5 — 4,5가 관련사진의
# 1,2가 아니라 캐러셀 전체의 4번째/5번째다. 그래서 이 숫자를 그대로 정렬 키로 쓸 수 있다.
_ALT_PATTERN = re.compile(r"^\s*(?P<kind>.+?)\s*_\s*(?P<seq>\d+)\s*$")

_DATA_URI_PATTERN = re.compile(r"^data:(?P<mime>[^;,]*)(?P<params>;[^,]*)?,", re.I)

# 매직 바이트 -> 확장자. 순서가 있다(webp는 RIFF 검사가 필요해 따로 다룬다).
_MAGIC = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
)

# 이 파이프라인이 저장을 허용하는 확장자. 여기 없는 것은 저장하지 않는다 —
# 매직으로 판정하지 못한 바이트를 "일단 .bin으로 저장"해 두면 뷰어가 서빙할 수 없는
# 파일이 READY로 기록되는, 이 저장소가 반복해 잡아 온 그 결함이 된다.
ALLOWED_IMAGE_EXTS = ("jpg", "png", "gif", "bmp", "webp")

IMAGE_MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "webp": "image/webp",
}

# 한 장이 이보다 작으면 정상 사진이 아니라고 본다(잘린 다운로드/투명 1px 스페이서 등).
# `doc_paths.doc_exists()`가 "0바이트 초과"를 완료 기준으로 삼는 것과 같은 계열의 방어이고,
# 사진은 문서와 달리 **의미 없는 초소형 이미지가 실제로 페이지에 섞여 있으므로** 하한을
# 0이 아니라 실측 기반으로 잡는다(실측 최소 장당 약 110KB, 안전하게 그 1/100 수준).
MIN_IMAGE_BYTES = 1024


def parse_image_alt(alt: str) -> Optional[Tuple[str, int]]:
    """`alt` 문자열 -> (종류, 순번). 규칙에 맞지 않으면 None.

    None을 돌려주는 것은 "이 요소는 물건 사진이 아니다"라는 뜻이다 — 호출부는 건너뛴다.
    캐러셀 밖의 아이콘(`ico_new_window.png` 등)이 섞여 들어오는 것을 여기서 거른다.
    """
    if not alt:
        return None
    m = _ALT_PATTERN.match(alt)
    if not m:
        return None
    kind = m.group("kind").strip()
    if not kind:
        return None
    try:
        seq = int(m.group("seq"))
    except (TypeError, ValueError):
        return None
    if seq <= 0:
        return None
    return kind, seq


def sniff_image_ext(data: bytes) -> Optional[str]:
    """실제 바이트로 이미지 형식을 판정한다. 모르면 None.

    ★ 선언된 MIME(`data:image/png`)을 절대 믿지 않는다 — 법원 페이지는 JPEG를
    image/png로 선언한다(위 모듈 주석의 실측). 판정하지 못하면 None을 돌려
    호출부가 **저장하지 않도록** 한다.
    """
    if not data:
        return None
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    # WebP: "RIFF" + 4바이트 크기 + "WEBP"
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def decode_image_data_uri(src: str) -> Optional[bytes]:
    """`data:...;base64,....` -> 원본 바이트. data URI가 아니거나 깨졌으면 None.

    base64가 아닌 data URI(퍼센트 인코딩)나 외부 http(s) URL은 여기서 다루지 않는다 —
    실측상 법원은 base64만 쓰고, 지원하지 않는 형태를 조용히 추측해 처리하면
    엉뚱한 바이트를 사진으로 저장하게 된다.
    """
    if not src:
        return None
    m = _DATA_URI_PATTERN.match(src)
    if not m:
        return None
    params = (m.group("params") or "").lower()
    if "base64" not in params:
        return None
    payload = src[m.end():]
    if not payload:
        return None
    try:
        # validate=False: 실제 페이지의 base64에 줄바꿈/공백이 섞여 있어도 받아들인다.
        decoded = base64.b64decode(payload)
    except Exception:
        return None
    # ★ 2026-08-17 Sprint 155: 빈 결과는 실패로 돌려준다.
    #
    # `validate=False`는 base64 알파벳이 아닌 글자를 **조용히 버린다.** 그래서
    # `"@@@@"`처럼 통째로 쓰레기인 payload도 예외 없이 `b""`를 준다. 예전에는 그것을
    # 그대로 반환해서, 바로 위 "payload가 비면 None"과 **같은 상황에 다른 값**을 줬다.
    #
    # 호출부는 `Optional[bytes]`로 성공/실패를 가른다. `b""`는 "디코딩에 성공했고 내용이
    # 없다"로 읽히는데 실제로는 실패다. 지금은 `MIN_IMAGE_BYTES` 검사가 하류에서 걸러
    # 주므로 사진이 잘못 저장되지는 않지만, 이 모듈의 규칙은 **판정하지 못한 바이트를
    # 넘기지 않는 것**이다. 경계를 여기서 지킨다.
    if not decoded:
        return None
    return decoded


def read_image_dimensions(data: bytes) -> Tuple[Optional[int], Optional[int]]:
    """(width, height). 읽어내지 못하면 (None, None).

    Pillow를 쓰지 않는다 — 이 모듈은 무의존이어야 하고(테스트가 그대로 돌아야 한다),
    가로/세로 두 값을 얻자고 이미지 라이브러리 전체를 끌어올 이유가 없다.
    실패해도 예외를 던지지 않는다: 크기를 모르는 것은 사진을 못 쓰는 사유가 아니다.
    """
    if not data:
        return None, None
    ext = sniff_image_ext(data)
    try:
        if ext == "png":
            # 8바이트 시그니처 + 4바이트 길이 + "IHDR" + width(4) + height(4)
            if len(data) >= 24 and data[12:16] == b"IHDR":
                w, h = struct.unpack(">II", data[16:24])
                return int(w), int(h)
            return None, None

        if ext == "gif":
            if len(data) >= 10:
                w, h = struct.unpack("<HH", data[6:10])
                return int(w), int(h)
            return None, None

        if ext == "bmp":
            if len(data) >= 26:
                w, h = struct.unpack("<ii", data[18:26])
                return int(abs(w)), int(abs(h))
            return None, None

        if ext == "jpg":
            return _read_jpeg_dimensions(data)

        if ext == "webp":
            return _read_webp_dimensions(data)
    except Exception:
        return None, None
    return None, None


def _read_jpeg_dimensions(data: bytes) -> Tuple[Optional[int], Optional[int]]:
    """JPEG 세그먼트를 훑어 SOF 마커에서 크기를 읽는다."""
    i = 2  # SOI(FFD8) 다음부터
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        # 패딩(FF FF)과 독립 마커는 길이 필드가 없다
        if marker == 0xFF:
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xD9:  # EOI
            break
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        # SOF0~SOF15 중 DHT(C4)/JPGA(C8)/DAC(CC)는 크기 정보가 아니다
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return int(w), int(h)
        if seg_len < 2:
            break
        i += 2 + seg_len
    return None, None


def _read_webp_dimensions(data: bytes) -> Tuple[Optional[int], Optional[int]]:
    """VP8/VP8L/VP8X 세 형식의 헤더에서 크기를 읽는다."""
    if len(data) < 30:
        return None, None
    fourcc = data[12:16]
    if fourcc == b"VP8 ":
        w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return int(w), int(h)
    if fourcc == b"VP8L":
        bits = struct.unpack("<I", data[21:25])[0]
        return int((bits & 0x3FFF) + 1), int(((bits >> 14) & 0x3FFF) + 1)
    if fourcc == b"VP8X":
        w = int.from_bytes(data[24:27], "little") + 1
        h = int.from_bytes(data[27:30], "little") + 1
        return w, h
    return None, None


# ---------------------------------------------------------------------------
# 경로 규칙
#
# `crawler/doc_paths.py`와 **같은 방식**으로 나눈다: 경로 계산은 디스크를 건드리지 않고
# (`_image_dir_path`), 디렉터리 생성은 쓰기 직전에만 한다(`ensure_image_dir`).
# 그 파일의 주석이 적어 둔 사고 — 조회 함수가 `os.makedirs()`를 불러 documents/ 아래
# 빈 디렉터리 1,681개를 만든 일 — 을 사진 쪽에서 반복하지 않기 위해서다.
# ---------------------------------------------------------------------------

def _image_dir_path(court_code: str, case_no: str, item_no: str = "1") -> str:
    """사진 디렉터리 경로만 계산한다. **디스크를 건드리지 않는다.**

    court_code 인자명 주의: `doc_paths.py`와 같은 이유로 이름은 code지만 실제 값은
    한글 법원명이다(그 파일의 상단 주석 참고). 두 모듈이 같은 물건 디렉터리를
    가리켜야 하므로 정규화 규칙도 똑같이 맞춘다 — 2026-08-17 Sprint 145부터 규칙을
    베끼지 않고 `doc_paths.sanitize_path_segment()`를 **그대로 가져다 쓴다**
    (같은 치환이 세 곳에 각자 적혀 있었고, 그것이 이 저장소가 반복해 겪은
    "쓰는 곳과 읽는 곳이 다른 경로를 보는" 결함의 씨앗이다).
    """
    from crawler.doc_paths import sanitize_path_segment
    safe_case_no = sanitize_path_segment(case_no)
    safe_item_no = sanitize_path_segment(item_no or "1")
    return os.path.join(DOCUMENT_ROOT, court_code, safe_case_no, safe_item_no,
                        IMAGE_DIR_NAME)


def ensure_image_dir(court_code: str, case_no: str, item_no: str = "1") -> str:
    """사진 디렉터리 경로. **없으면 만든다.** 쓰기 직전에만 부른다."""
    path = _image_dir_path(court_code, case_no, item_no)
    os.makedirs(path, exist_ok=True)
    return path


def image_filename(seq: int, ext: str) -> str:
    """`3, "jpg"` -> `"03.jpg"`.

    순번을 0으로 채우는 이유는 파일 이름을 그냥 정렬해도 캐러셀 순서가 유지되게 하기
    위해서다(1, 10, 2 순으로 섞이지 않는다). 순번은 DB에도 그대로 들어가므로 화면
    정렬은 DB가 책임지지만, 사람이 폴더를 열어 볼 때 순서가 맞는 편이 훨씬 낫다.
    """
    if ext not in ALLOWED_IMAGE_EXTS:
        raise ValueError("허용되지 않은 이미지 확장자: %r (가능: %s)"
                         % (ext, ", ".join(ALLOWED_IMAGE_EXTS)))
    if not isinstance(seq, int) or seq <= 0:
        raise ValueError("순번은 1 이상의 정수여야 한다: %r" % (seq,))
    return "%02d.%s" % (seq, ext)


def image_path(court_code: str, case_no: str, item_no: str, seq: int, ext: str) -> str:
    """저장/서빙에 쓰는 최종 사진 경로. **디스크를 건드리지 않는다.**"""
    return os.path.join(_image_dir_path(court_code, case_no, item_no),
                        image_filename(seq, ext))


def image_exists(court_code: str, case_no: str, item_no: str, seq: int, ext: str) -> bool:
    """이 사진이 "쓸 수 있는 상태"로 저장돼 있는지.

    `doc_paths.doc_exists()`와 같은 기준을 쓴다 — 존재 + 크기가 하한 초과.
    쓰는 쪽과 읽는 쪽의 "있다" 정의가 갈라지면 "화면은 READY인데 뷰어는 404"가 된다.
    """
    path = image_path(court_code, case_no, item_no, seq, ext)
    try:
        return os.path.isfile(path) and os.path.getsize(path) >= MIN_IMAGE_BYTES
    except OSError:
        return False


def list_stored_images(court_code: str, case_no: str, item_no: str) -> List[dict]:
    """디스크에 실제로 있는 사진 목록을 순번 순으로 돌려준다.

    DB(`auction_image`)가 아니라 **파일시스템**이 근거다. 두 근거가 어긋났을 때
    어느 쪽이 틀렸는지 대조하는 감사 용도이며, 화면 서빙은 DB를 쓴다
    (파일시스템을 매 요청 훑으면 물건 수만큼 디렉터리를 스캔하게 된다).
    """
    d = _image_dir_path(court_code, case_no, item_no)
    out: List[dict] = []
    if not os.path.isdir(d):
        return out
    for name in os.listdir(d):
        stem, dot, ext = name.rpartition(".")
        if not dot or ext.lower() not in ALLOWED_IMAGE_EXTS:
            continue
        if not stem.isdigit():
            continue
        full = os.path.join(d, name)
        try:
            size = os.path.getsize(full)
        except OSError:
            continue
        out.append({"seq": int(stem), "ext": ext.lower(), "path": full, "file_size": size})
    out.sort(key=lambda r: r["seq"])
    return out


def is_inside_document_root(path: str) -> bool:
    """이 경로가 `documents/` 안인가. 밖이면 False.

    2026-08-18 Sprint 192 (BUGS #131). `api/v1/images.py` 는 **서빙**할 때 이미 같은
    검사를 한다 — 그 파일의 주석이 이유를 적어 두었다: *"DB 값에서 경로를 만들기 때문에
    문서 쪽보다 오히려 더 필요하다(관리 도구나 옛 마이그레이션이 넣은 값이 항상
    얌전하다고 가정하지 않는다)."*

    **지우는 쪽에는 그 검사가 없었다.** 읽기보다 쓰기/삭제가 더 위험한데 방어는 읽기에만
    있었던 셈이다. `auction_image.storage_path` 가 어떤 이유로든 `..` 를 품으면
    `remove_stored_image_files()` 가 `documents/` 밖의 파일을 지운다.
    """
    try:
        real_root = os.path.realpath(DOCUMENT_ROOT)
        real_path = os.path.realpath(path)
        return os.path.commonpath([real_root, real_path]) == real_root
    except (OSError, ValueError):
        # 드라이브가 다르면 commonpath 가 ValueError 를 낸다 — 그것도 "밖"이다.
        return False


def remove_stored_image_files(paths) -> int:
    """지정한 사진 파일들을 지운다. 실제로 지운 개수를 돌려준다.

    2026-08-18 Sprint 191 (BUGS #128). DB 행을 먼저 지운 **뒤** 그 행이 가리키던 파일을
    지우는 순서를 지키기 위해 호출부가 경로 목록을 받아 넘긴다 — 반대 순서로 하면
    "DB 는 있다는데 파일이 없다"는, 이 저장소가 반복해 잡아 온 어긋남이 생긴다.

    ★ `documents/` **밖은 절대 지우지 않는다** (2026-08-18 Sprint 192, BUGS #131).
      경로의 출처가 DB(`auction_image.storage_path`)라 값이 항상 얌전하다고 가정할 수
      없다. 서빙 쪽(`api/v1/images.py`)은 이미 같은 검사를 하고 있었고, **더 위험한
      삭제 쪽에만 없었다.** 밖을 가리키는 값은 지우지 않고 경고만 남긴다.

    지우지 못한 파일이 있어도 예외를 올리지 않는다(정리는 부수 작업이고, 그 실패로
    수집 결과를 뒤집을 이유가 없다). 대신 경고를 남긴다.
    """
    import logging
    log = logging.getLogger(__name__)
    removed = 0
    for path in (paths or ()):
        if not is_inside_document_root(path):
            log.warning("사진 파일 정리 거부: documents/ 밖을 가리킨다 (%s)", path)
            continue
        try:
            os.remove(path)
            removed += 1
        except FileNotFoundError:
            pass          # 이미 없다 — 목표 상태와 같다
        except OSError as e:
            log.warning("사진 파일 정리 실패 (%s): %s", path, str(e))
    return removed
