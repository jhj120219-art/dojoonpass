"""물건 사진 + 문서 실체(Asset Pipeline) 회귀 테스트 (2026-08-17 Sprint 144 신설).

이 스프린트가 새로 만든 계층 전체를 덮는다:

    법원 원천(base64 data URI)
      -> crawler/image_assets.py   파싱·판정·경로 (순수)
      -> crawler/image_crawler.py  저장           (selenium 부분은 가짜 드라이버로 대체)
      -> storage/database.py       auction_image / doc_raw 기록
      -> api/v1/item.py            상세 응답 계약
      -> api/v1/images.py          사진 서빙

selenium 없이 실행된다 — `collect_images()`가 driver에게 요구하는 것은
`find_elements()`와 요소의 `get_attribute()` 둘뿐이라 가짜 객체로 충분하다.
실제 `auction.db` / `documents/`는 건드리지 않는다(임시 DB + 임시 문서 루트).

    python test_asset_pipeline.py
"""
import base64
import hashlib
import contextlib
import io
import os
import shutil
import struct
import sys
import tempfile
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 관심물건/최근 본 물건은 로그인이 필요한 화면이라 이 파일에서도 토큰이 필요해졌다
# (2026-08-20 Sprint 224). `api/auth.py` 가 모듈 최상단에서 한 번만 읽으므로 **import 전**에
# 넣는다. `.env` 에 진짜 값이 이미 있으면 그것을 그대로 쓰고(운영 값을 조용히 덮어쓰지
# 않는다), 없을 때만 이 프로세스 안에서만 유효한 합성 값을 쓴다 —
# `test_api_regression.py` 가 쓰는 것과 같은 방식이다.
if not os.environ.get("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "asset-pipeline-local-only-" + hashlib.sha256(
        b"asset-pipeline").hexdigest()[:16]

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, ("" if cond else " -- " + str(detail))))
    if not cond:
        failures.append(name)


# ---------------------------------------------------------------------------
# 표본 이미지 바이트
#
# 실제 파일을 저장소에 넣지 않는다 — 테스트가 외부 파일에 의존하면 그 파일이 사라졌을 때
# 조용히 못 돌게 된다. 대신 각 형식의 **진짜 헤더**를 코드로 만든다(크기 판정까지 검증된다).
# ---------------------------------------------------------------------------

# 픽스처 사진의 최소 pad (2026-08-19 Sprint 218, BUGS #148).
# ---------------------------------------------------------------------------
# 서빙 계층은 `MIN_IMAGE_BYTES`(1,024) 미만을 **404 로 거절한다**
# (`api/v1/images.py`, `image_exists()`). 그런데 이 파일의 픽스처들은 오랫동안
# 100~200바이트짜리 사진으로 "auction_image 2행 / images_status=READY" 를
# 단언하고 있었다 — **그 사진들은 실제로는 한 장도 서빙될 수 없는 크기**다.
#
# 즉 픽스처가 파이프라인 전체가 받아들이지 않는 데이터로 "정상"을 그리고 있었다.
# 저장 계층이 같은 하한을 갖게 되면서(BUGS #148) 그 사실이 드러났다.
# 여기서 한 번에 올려 둔다 — 개별 pad 는 "서로 다른 바이트"를 만들기 위한 것이므로
# 하한만 더해 주면 의도는 그대로다.
MIN_FIXTURE_PAD = 2048


def make_jpeg(width=525, height=700, pad=2048):
    """SOI + APP0 + SOF0(크기 포함) + EOI. 실제 JPEG 파서가 크기를 읽을 수 있는 최소 형태."""
    sof = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", height, width) \
        + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    return b"\xff\xd8\xff" + app0[3:] if False else (
        b"\xff\xd8" + app0 + sof + b"\x00" * pad + b"\xff\xd9")


def make_png(width=100, height=50, pad=2048):
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_body = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    ihdr = struct.pack(">I", len(ihdr_body)) + b"IHDR" + ihdr_body \
        + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_body) & 0xFFFFFFFF)
    filler = struct.pack(">I", pad) + b"tEXt" + b"\x00" * pad + struct.pack(">I", 0)
    return sig + ihdr + filler


def make_gif(width=676, height=700, pad=2048):
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00\x00\x00" + b"\x00" * pad


def data_uri(payload: bytes, mime="image/png") -> str:
    """법원이 실제로 보내는 형태 — **선언은 png인데 바이트는 JPEG**인 경우를 그대로 흉내낸다."""
    return "data:%s;base64,%s" % (mime, base64.b64encode(payload).decode("ascii"))


# ---------------------------------------------------------------------------
# 가짜 selenium
# ---------------------------------------------------------------------------

class FakeElement:
    def __init__(self, attrs):
        self._attrs = attrs

    def get_attribute(self, name):
        return self._attrs.get(name)


class FakeDriver:
    """`find_elements(By.CSS_SELECTOR, ...)`만 답하면 된다."""

    def __init__(self, elements, raise_on_find=False):
        self._elements = elements
        self._raise = raise_on_find
        self.find_calls = 0

    def find_elements(self, by, selector):
        self.find_calls += 1
        if self._raise:
            raise RuntimeError("DOM 조회 실패(가짜)")
        return list(self._elements)


def img_el(kind, seq, payload, mime="image/png"):
    return FakeElement({"alt": "%s_%d" % (kind, seq), "src": data_uri(payload, mime)})


# ---------------------------------------------------------------------------
# 환경
# ---------------------------------------------------------------------------

class Env:
    """임시 DB + 임시 documents 루트. 스키마는 실제 부트스트랩 절차로 만든다."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="qa_asset_")
        self.docs = os.path.join(self.dir, "documents")
        os.makedirs(self.docs)

        import storage.database as dbmod
        import crawler.doc_paths as dp
        import crawler.image_assets as ia
        import api.v1.images as apiimg
        # ★ 문서 서빙 모듈도 **자기 DOCUMENT_ROOT 를 따로 들고 있다**
        #   (2026-08-19 Sprint 217). 이것을 안 바꾸면 픽스처가 임시 루트에 파일을
        #   써 놓고 API 는 운영 `documents/` 를 뒤져 **항상 404** 가 된다 —
        #   그리고 그 404 는 "파일이 없다"는 정상 응답과 구별되지 않는다.
        #   실제로 12-L 을 쓰다가 이 함정에 빠졌다(뷰어가 200 이어야 하는데 404).
        import api.v1.documents as apidoc
        self.dbmod, self.dp, self.ia, self.apiimg = dbmod, dp, ia, apiimg
        self.apidoc = apidoc
        self._orig = (dbmod.DB_PATH, dp.DOCUMENT_ROOT, ia.DOCUMENT_ROOT,
                      apiimg.DOCUMENT_ROOT, apiimg.PROJECT_ROOT,
                      apidoc.DOCUMENT_ROOT, apidoc.PROJECT_ROOT)
        dbmod.DB_PATH = os.path.join(self.dir, "t.db")
        dp.DOCUMENT_ROOT = self.docs
        ia.DOCUMENT_ROOT = self.docs
        apiimg.DOCUMENT_ROOT = self.docs
        apiimg.PROJECT_ROOT = self.dir
        apidoc.DOCUMENT_ROOT = self.docs
        apidoc.PROJECT_ROOT = self.dir

        # 스키마는 실제 부트스트랩 3단계 그대로(테스트가 스키마를 손으로 베끼지 않는다 —
        # `test_collect_documents.py`가 같은 이유로 같은 방식을 쓴다).
        import storage.migrate_v4_1 as mig
        import storage.migrations.run_migrations as runmig
        with contextlib.redirect_stdout(io.StringIO()):
            dbmod.init_db()
            mig.migrate()
            runmig.run()

    def close(self):
        (self.dbmod.DB_PATH, self.dp.DOCUMENT_ROOT, self.ia.DOCUMENT_ROOT,
         self.apiimg.DOCUMENT_ROOT, self.apiimg.PROJECT_ROOT,
         self.apidoc.DOCUMENT_ROOT, self.apidoc.PROJECT_ROOT) = self._orig
        shutil.rmtree(self.dir, ignore_errors=True)

    def conn(self):
        return self.dbmod.get_connection()

    def seed_item(self, item_id=1, court="서울중앙지방법원", case_no="2024타경1", item_no="1"):
        c = self.conn()
        try:
            case_id = c.execute("INSERT INTO auction_case (court_code, case_no) VALUES (?,?)",
                                (court, case_no)).lastrowid
            c.execute("INSERT INTO auction_item (id,case_id,court_name,case_no,item_no)"
                      " VALUES (?,?,?,?,?)", (item_id, case_id, court, case_no, item_no))
            c.commit()
        finally:
            c.close()
        return court, case_no, item_no

    def enqueue(self, court, case_no, item_no, doc_type):
        c = self.conn()
        try:
            qid = c.execute(
                "INSERT INTO document_queue (court_code, case_no, item_no, doc_type, priority,"
                " auction_date, status, retry_count, enqueued_at)"
                " VALUES (?,?,?,?,1,'2099-01-01','pending',0,'2026-08-17T00:00:00')",
                (court, case_no, item_no, doc_type)).lastrowid
            c.commit()
            return qid
        finally:
            c.close()

    def images_of(self, item_id):
        c = self.conn()
        try:
            return [dict(r) for r in c.execute(
                "SELECT seq, kind, storage_path, file_size, width, height, file_hash"
                " FROM auction_image WHERE item_id=? ORDER BY seq", (item_id,))]
        finally:
            c.close()

    def status_of(self, item_id, doc_type):
        c = self.conn()
        try:
            row = c.execute("SELECT status FROM document_status WHERE item_id=? AND doc_type=?",
                            (item_id, doc_type)).fetchone()
            return row["status"] if row else None
        finally:
            c.close()


# ===========================================================================
# 1. 순수 파싱/판정 (crawler/image_assets.py)
# ===========================================================================


def _webp(fourcc, tail):
    """RIFF 컨테이너로 감싼 최소 webp 바이트."""
    body = b"WEBP" + fourcc + tail
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _bmp(width, height):
    """크기 필드만 채운 최소 BMP(26바이트)."""
    return b"BM" + b"\x00" * 16 + struct.pack("<ii", width, height)


def test_image_format_edge_cases():
    """형식 판정과 크기 읽기의 분기를 전부 훑는다 (2026-08-17 Sprint 155).

    커버리지 실측에서 `crawler/image_assets.py`가 72%였다. 빠진 47문장은 전부 순수
    분기라 브라우저 없이 검증할 수 있었다 — 특히 **webp 크기 읽기(VP8/VP8L/VP8X)는
    통째로 0%**였다.

    이 저장소는 법원 페이지가 **선언 MIME으로 거짓말하는** 것을 이미 겪었다(image/png이라
    적어 놓고 실제로는 JPEG/GIF). 그래서 판정은 매직 바이트로만 하고, 판정 못 한 바이트는
    저장하지 않는다. 그 규칙의 경계값들을 여기서 고정한다.
    """
    print("\n--- 1-B. 형식 판정/크기 읽기 경계값 (Sprint 155) ---")
    from crawler.image_assets import (
        parse_image_alt, sniff_image_ext, decode_image_data_uri,
        read_image_dimensions, ALLOWED_IMAGE_EXTS,
    )

    # --- alt 파싱: 형태가 어긋나면 None ---
    check("alt 정상", parse_image_alt("전경도_3"), ("전경도", 3))
    check("alt 공백 허용", parse_image_alt("  관련사진 _ 12 "), ("관련사진", 12))
    check("alt 종류가 비면 None", parse_image_alt("_5"), None)
    check("alt 순번이 숫자가 아니면 None", parse_image_alt("전경도_x"), None)
    check("alt 순번 0은 None(1부터 시작한다)", parse_image_alt("전경도_0"), None)
    check("alt 언더바 없으면 None", parse_image_alt("전경도3"), None)
    check("alt 빈 문자열은 None", parse_image_alt(""), None)

    # --- 매직 판정 ---
    check("jpg 매직", sniff_image_ext(b"\xff\xd8\xff\xe0rest"), "jpg")
    check("png 매직", sniff_image_ext(b"\x89PNG\r\n\x1a\nrest"), "png")
    check("gif87a 매직", sniff_image_ext(b"GIF87a" + b"\x00" * 10), "gif")
    check("gif89a 매직", sniff_image_ext(b"GIF89a" + b"\x00" * 10), "gif")
    check("bmp 매직", sniff_image_ext(_bmp(4, 5)), "bmp")
    check("webp는 RIFF+WEBP를 함께 봐야 한다",
          sniff_image_ext(_webp(b"VP8 ", b"\x00" * 20)), "webp")
    check("RIFF지만 WEBP가 아니면 None(예: wav)",
          sniff_image_ext(b"RIFF" + b"\x00" * 4 + b"WAVEfmt " + b"\x00" * 10), None)
    check("알 수 없는 바이트는 None", sniff_image_ext(b"NOTANIMAGE12345"), None)
    check("너무 짧으면 None", sniff_image_ext(b"\xff"), None)
    check_true("판정 결과는 항상 허용 목록 안이다",
               all(sniff_image_ext(b) in ALLOWED_IMAGE_EXTS
                   for b in (b"\xff\xd8\xff", b"GIF89a" + b"\x00" * 10, _bmp(1, 1))))

    # --- data URI 디코딩 ---
    ok = decode_image_data_uri("data:image/png;base64,R0lGODdh")
    check_true("정상 data URI는 바이트를 준다", isinstance(ok, bytes) and len(ok) > 0, ok)
    check("base64 파라미터가 없으면 None",
          decode_image_data_uri("data:image/png,ABC"), None)
    check("payload가 비면 None", decode_image_data_uri("data:image/png;base64,"), None)
    check("data URI가 아니면 None", decode_image_data_uri("https://x/y.png"), None)
    check("망가진 base64는 None이지 예외가 아니다",
          decode_image_data_uri("data:image/png;base64,@@@@"), None)

    # --- 크기 읽기 ---
    check("png 크기", read_image_dimensions(make_png(120, 45)), (120, 45))
    check("gif 크기", read_image_dimensions(make_gif(676, 700)), (676, 700))
    check("jpg 크기", read_image_dimensions(make_jpeg(525, 700)), (525, 700))
    check("bmp 크기", read_image_dimensions(_bmp(64, 32)), (64, 32))
    check("bmp 음수 높이(하향식 비트맵)도 절대값으로 읽는다",
          read_image_dimensions(_bmp(64, -32)), (64, 32))

    # --- ★ 손으로 만든 fixture 는 **가장 쉬운 경로만** 지나간다 (2026-08-24 Sprint 254) ---
    #
    # 위 `make_jpeg()` 는 SOI 다음에 곧바로 SOF0 를 놓는다. 그래서 마커 순회 루프
    # (`_read_jpeg_dimensions`)의 대부분 — 패딩(FF FF), 독립 마커, 재시작 마커, EOI,
    # 길이 필드가 이상한 세그먼트 — 가 **한 번도 실행되지 않았다**(합산 커버리지 실측).
    # 진짜 카메라/브라우저가 만든 JPEG 은 APP0/JFIF, DQT, DHT 를 앞에 달고 오므로
    # 그 경로를 반드시 지난다.
    #
    # 그래서 (1) 실제 인코더가 만든 파일과 대조하고 (2) 경계값은 손으로 만든다.
    #
    # ★ 인코더 대조는 **선택**이다. `crawler/image_assets.py` 는 "Pillow 를 쓰지 않는다"를
    #   설계 원칙으로 못 박고 있고(그 모듈 주석 참고), 그 원칙을 테스트가 뒤집으면 안 된다.
    #   Pillow 는 `pdfplumber`(고정 의존)를 통해 들어와 있어 보통은 존재하지만,
    #   없으면 **건너뛴 사실을 출력**한다 — 조용히 통과시키지 않는다.
    # ★ 실제 인코더 출력과의 대조는 **의존을 남기지 않고** 한 번 재서 결과만 남겼다.
    #
    #   Pillow 로 JPEG(baseline/progressive) / PNG / GIF / BMP /
    #   WEBP(VP8 · VP8L · VP8X) 를 6가지 크기로 만들어 대조했다:
    #   **48건 중 불일치 0건**(2026-08-24 실측). 운영 DB 의 사진 45장과도
    #   판독기·DB 저장값이 **45/45 일치**한다.
    #
    #   그런데 그 대조를 검사에 남기지는 않는다. `PIL` 은
    #   `requirements.txt` 에 선언되지 않은 **전이 의존**이고
    #   (`pdfplumber` 를 통해 우연히 들어있다), `crawler/image_assets.py` 는
    #   "Pillow 를 쓰지 않는다 - 검사가 그대로 돌아야 한다"를 설계 원칙으로
    #   적어 둔다. 검사가 제품의 원칙을 뒤집으면 안 된다 -
    #   `test_schema_hygiene.py` 의 "선언되지 않은 third-party" 가드가 실제로 이것을
    #   잡았다. 아래 바이트 수준 경계값은 의존 없이 같은 분기를 덤는다.

    # --- JPEG 마커 순회 경계값(손으로 만든다) ---
    #
    # 크기를 못 읽는 것 자체는 치명적이지 않다(제품이 (None, None) 을 허용한다).
    # 하지만 **틀린 값**을 읽으면 상세 화면이 그 값으로 자리를 잡아 레이아웃이 튄다
    # (`src/app/properties/[id]/page.tsx` 가 width/height 를 그대로 쓴다).
    # 그래서 "못 읽음"과 "틀리게 읽음"을 갈라서 본다.
    def _sof(w, h):
        return b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, h, w, 3) + b"\x00" * 6

    def _jpeg(*chunks):
        return b"\xff\xd8" + b"".join(chunks) + _sof(321, 123) + b"\xff\xd9"

    # 마커가 아닌 바이트 위에 서 있으면 한 칸씩 전진한다 ―
    # 손상된 파일에서도 멈추지 않고 SOF 를 찾아간다.
    check("★ 마커가 아닌 바이트를 건너뛴다",
          read_image_dimensions(_jpeg(b"\xff\xe0" + struct.pack(">H", 4) + b"\x00" * 2 + b"\x00" * 3)), (321, 123))
    check("★ 패딩(FF FF)을 건너뛰고 SOF 를 찾는다",
          read_image_dimensions(_jpeg(b"\xff\xff\xff\xff")), (321, 123))
    check("★ 독립 마커(FF 01)를 건너뛴다",
          read_image_dimensions(_jpeg(b"\xff\x01")), (321, 123))
    check("★ 재시작 마커(FF D0~D7)를 건너뛴다",
          read_image_dimensions(_jpeg(b"\xff\xd0" + b"\xff\xd7")), (321, 123))
    check("★ 길이 필드가 있는 세그먼트(APP0)를 건너뛴다",
          read_image_dimensions(_jpeg(b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9)),
          (321, 123))
    check("★ DHT(FFC4)는 SOF 가 아니다 ― 크기로 오독하지 않는다",
          read_image_dimensions(_jpeg(b"\xff\xc4" + struct.pack(">H", 6) + b"\x00" * 4)),
          (321, 123))
    # EOI 를 먼저 만나면 거기서 멈춘다 — 뒤에 SOF 가 있어도 읽지 않는다.
    check("★ EOI 뒤의 데이터를 크기로 읽지 않는다",
          read_image_dimensions(b"\xff\xd8" + b"\xff\xd9" + _sof(999, 888)), (None, None))
    # 길이 필드가 2보다 작으면 더 나아갈 수 없다(무한 루프 방지).
    check("★ 망가진 길이 필드에서 멈춘다(무한 루프가 되지 않는다)",
          read_image_dimensions(b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 0)
                                + b"\x00" * 40), (None, None))
    check("★ SOF 가 없으면 (None, None)", read_image_dimensions(b"\xff\xd8" + b"\x00" * 40),
          (None, None))
    check("잘린 JPEG 도 예외를 던지지 않는다", read_image_dimensions(b"\xff\xd8\xff"), (None, None))
    check("빈 바이트열", read_image_dimensions(b""), (None, None))
    check("형식을 모르는 바이트열", read_image_dimensions(b"qa-not-an-image" * 4), (None, None))

    # webp 세 형식 — 이 분기는 커버리지 0%였다
    # 청크 크기 4바이트(16:20)를 반드시 채워야 본문이 20부터 시작한다.
    # VP8  : 본문 20 + 프레임태그3 + 싱크코드3 = 26 부터 width/height
    vp8 = _webp(b"VP8 ", b"\x00" * 4 + b"\x00" * 6 + struct.pack("<HH", 300, 200))
    check("webp VP8 크기", read_image_dimensions(vp8), (300, 200))
    # VP8L : 본문 20 + 서명 1바이트 -> 21:25 에 (height-1)<<14 | (width-1)
    vp8l_bits = ((200 - 1) << 14) | (300 - 1)
    vp8l = _webp(b"VP8L", b"\x00" * 4 + b"\x2f" + struct.pack("<I", vp8l_bits) + b"\x00" * 8)
    check("webp VP8L 크기", read_image_dimensions(vp8l), (300, 200))
    # VP8X : 본문 20 + 플래그 4바이트 -> 24:27 width-1, 27:30 height-1 (3바이트 리틀엔디안)
    vp8x = _webp(b"VP8X", b"\x00" * 4 + b"\x00" * 4 + (300 - 1).to_bytes(3, "little")
                 + (200 - 1).to_bytes(3, "little") + b"\x00" * 6)
    check("webp VP8X 크기", read_image_dimensions(vp8x), (300, 200))

    # 잘린 입력 — 예외가 아니라 (None, None)
    check("잘린 png는 (None, None)", read_image_dimensions(b"\x89PNG\r\n\x1a\n"), (None, None))
    check("잘린 gif는 (None, None)", read_image_dimensions(b"GIF89a"), (None, None))
    check("잘린 bmp는 (None, None)", read_image_dimensions(b"BM" + b"\x00" * 5), (None, None))
    check("잘린 webp는 (None, None)",
          read_image_dimensions(b"RIFF" + b"\x00" * 4 + b"WEBP"), (None, None))
    check("빈 바이트는 (None, None)", read_image_dimensions(b""), (None, None))
    check("알 수 없는 형식은 (None, None)", read_image_dimensions(b"NOTANIMAGE1234567890"), (None, None))


def test_alt_parsing():
    print("\n--- 1. alt 파싱 ---")
    from crawler.image_assets import parse_image_alt
    check("전경도_1", parse_image_alt("전경도_1"), ("전경도", 1))
    check("위치도_4", parse_image_alt("위치도_4"), ("위치도", 4))
    check("내부구조도_12", parse_image_alt("내부구조도_12"), ("내부구조도", 12))
    check("공백 허용", parse_image_alt("  관련사진 _ 5 "), ("관련사진", 5))
    # 사진이 아닌 것은 확실히 걸러야 한다 — 캐러셀 밖 아이콘이 사진으로 저장되면 안 된다.
    check("빈 문자열", parse_image_alt(""), None)
    check("None", parse_image_alt(None), None)
    check("순번 없음", parse_image_alt("전경도"), None)
    check("순번이 숫자가 아님", parse_image_alt("전경도_a"), None)
    check("순번 0은 거부", parse_image_alt("전경도_0"), None)
    check("종류가 비었다", parse_image_alt("_3"), None)
    check("아이콘 alt", parse_image_alt("지도검색 새 창"), None)


def test_magic_sniffing_beats_declared_mime():
    """★ 이 스프린트의 핵심 실측: 법원은 JPEG를 image/png로 선언한다."""
    print("\n--- 2. 형식 판정은 선언이 아니라 매직 바이트 ---")
    from crawler.image_assets import sniff_image_ext, decode_image_data_uri

    jpg = make_jpeg()
    uri = data_uri(jpg, "image/png")          # 선언은 png, 실체는 jpeg (실제 법원 응답 형태)
    decoded = decode_image_data_uri(uri)
    check_true("data URI 디코드가 원본 바이트를 복원한다", decoded == jpg,
               "len=%s" % (len(decoded) if decoded else None))
    check("선언(png)을 무시하고 jpg로 판정", sniff_image_ext(decoded), "jpg")

    check("png 판정", sniff_image_ext(make_png()), "png")
    check("gif 판정", sniff_image_ext(make_gif()), "gif")
    check("빈 바이트", sniff_image_ext(b""), None)
    check("이미지가 아닌 바이트", sniff_image_ext(b"%PDF-1.4 hello"), None)

    # 지원하지 않는 형태는 조용히 추측하지 않는다
    check("base64가 아닌 data URI", decode_image_data_uri("data:image/png,abc"), None)
    check("http URL", decode_image_data_uri("https://x/y.png"), None)
    check("빈 src", decode_image_data_uri(""), None)


def test_dimension_reading():
    print("\n--- 3. 크기 판정(무의존 헤더 파싱) ---")
    from crawler.image_assets import read_image_dimensions
    check("jpeg 525x700", read_image_dimensions(make_jpeg(525, 700)), (525, 700))
    check("jpeg 700x391", read_image_dimensions(make_jpeg(700, 391)), (700, 391))
    check("png 100x50", read_image_dimensions(make_png(100, 50)), (100, 50))
    check("gif 676x700", read_image_dimensions(make_gif(676, 700)), (676, 700))
    # 크기를 모르는 것은 사진을 못 쓰는 사유가 아니다 — 예외 없이 (None, None)
    check("알 수 없는 바이트", read_image_dimensions(b"nonsense"), (None, None))
    check("빈 바이트", read_image_dimensions(b""), (None, None))


def test_path_rules():
    print("\n--- 4. 경로 규칙 ---")
    from crawler import image_assets as ia
    env = Env()
    try:
        p = ia.image_path("서울중앙지방법원", "2024타경1 / 2024타경2", "3", 7, "jpg")
        check_true("사건번호의 '/'는 '_'로 치환된다", "2024타경1 _ 2024타경2" in p, p)
        check_true("images 하위 폴더", os.sep + "images" + os.sep in p, p)
        check_true("순번은 0으로 채워진다", p.endswith("07.jpg"), p)
        check("파일명 규칙", ia.image_filename(3, "png"), "03.png")

        # 조회가 디스크를 건드리면 안 된다 — documents/ 아래 빈 디렉터리 1,681개를
        # 만들었던 그 사고(doc_paths.doc_exists)를 사진 쪽에서 반복하지 않는지 본다.
        before = sum(len(d) for _, d, _ in os.walk(env.docs))
        ia.image_path("없는법원", "2099타경9999", "1", 1, "jpg")
        ia.image_exists("없는법원", "2099타경9999", "1", 1, "jpg")
        ia.list_stored_images("없는법원", "2099타경9999", "1")
        after = sum(len(d) for _, d, _ in os.walk(env.docs))
        check("조회만으로 디렉터리가 생기지 않는다", after, before)

        # 허용하지 않는 확장자는 조용히 통과시키지 않는다
        raised = False
        try:
            ia.image_filename(1, "exe")
        except ValueError:
            raised = True
        check_true("허용되지 않은 확장자는 예외", raised)
    finally:
        env.close()


# ===========================================================================
# 5. 수집기 (crawler/image_crawler.py)
# ===========================================================================

def test_collect_images_happy_path():
    print("\n--- 5. 사진 수집 정상 경로 ---")
    from crawler.image_crawler import collect_images
    from crawler.image_assets import list_stored_images
    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        driver = FakeDriver([
            img_el("전경도", 1, make_jpeg(525, 700)),
            img_el("전경도", 2, make_jpeg(525, 700)),
            img_el("위치도", 3, make_gif(676, 700)),
            # 캐러셀 밖 아이콘 — 사진이 아니므로 저장 대상이 아니다
            FakeElement({"alt": "지도검색 새 창", "src": data_uri(make_png(16, 16))}),
        ])
        res = collect_images(driver, court, case_no, item_no)

        check("성공", res["success"], True)
        check("자산 없음 아님", res["no_asset"], False)
        check("부분 성공 아님", res["partial"], False)
        check("수집 장수", res["image_count"], 3)
        check("종류", [i["kind"] for i in res["images"]], ["전경도", "전경도", "위치도"])
        check("순번", [i["seq"] for i in res["images"]], [1, 2, 3])
        check("크기 파싱", [(i["width"], i["height"]) for i in res["images"]],
              [(525, 700), (525, 700), (676, 700)])

        stored = list_stored_images(court, case_no, item_no)
        check("디스크에 3장", len(stored), 3)
        check("확장자는 실제 형식대로", [s["ext"] for s in stored], ["jpg", "jpg", "gif"])
        check_true("집합 해시가 생긴다", bool(res["new_hash"]), res["new_hash"])
        check_true("임시 파일이 남지 않는다",
                   not any(f.endswith(".tmp") for s in stored
                           for f in os.listdir(os.path.dirname(s["path"]))))
    finally:
        env.close()



def test_image_write_failure_leaves_no_partial_file():
    """사진 저장이 실패하면 `.tmp`도 목적지도 남기지 않는다 (2026-08-17 Sprint 162).

    `_write_image_atomically()`는 임시 파일에 쓰고 `os.replace()`로 바꾼다. 그 이유는
    모듈 주석에 적혀 있다 — 목적지에 직접 쓰면 쓰는 도중 죽었을 때 잘린 파일이 남고,
    다음 수집이 "이미 있다"고 판정해 **깨진 사진이 영구히 남는다**(BUGS #22/#50/#61).

    그런데 커버리지 실측에서 **실패 경로(except OSError)가 통째로 비어 있었다.** 성공만
    검증하면 "실패했을 때 뒷정리가 되는가"는 아무도 보지 않는다. 여기서는 교체 단계를
    강제로 실패시켜 두 가지를 고정한다.

      (a) False를 돌려준다 (호출부가 실패를 인지한다)
      (b) `.tmp`가 남지 않는다 — 남으면 디스크가 조용히 차고, 더 나쁘게는 나중에
          누군가 그것을 실물로 착각한다
    """
    print("\n--- 6-B. 사진 저장 실패가 부분 파일을 남기지 않는다 (Sprint 162) ---")
    import crawler.image_crawler as ic

    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        d = os.path.join(env.docs, court, case_no, item_no, "images")
        os.makedirs(d, exist_ok=True)
        dest = os.path.join(d, "01.jpg")
        data = make_jpeg(10, 10)

        # 대조군 — 정상 경로에서는 목적지가 생기고 .tmp는 사라진다
        ok = ic._write_image_atomically(dest, data, court, case_no, item_no, 1, "jpg")
        check("대조군: 정상 저장은 True", ok, True)
        check("대조군: 목적지 파일이 생긴다", os.path.exists(dest), True)
        check("대조군: .tmp가 남지 않는다", os.path.exists(dest + ".tmp"), False)
        os.remove(dest)

        # 실패 경로 — 교체 단계에서 OSError
        orig_replace = ic.os.replace

        def boom(a, b):
            raise OSError("qa-simulated-replace-failure")

        ic.os.replace = boom
        try:
            failed = ic._write_image_atomically(dest, data, court, case_no, item_no, 1, "jpg")
        finally:
            ic.os.replace = orig_replace

        check("교체 실패는 False를 돌려준다", failed, False)
        check("실패 후 목적지 파일이 없다", os.path.exists(dest), False)
        check("실패 후 .tmp도 남지 않는다", os.path.exists(dest + ".tmp"), False)
    finally:
        env.close()



def test_overwrite_enables_recollection():
    """이미 받은 자산을 **강제로 다시 받는 경로**가 실제로 동작하는가 (2026-08-17 Sprint 184).

    법원 자료는 절차 진행에 따라 바뀐다(재감정, 현황조사서 갱신, 사진 교체). 그래서
    "이미 있으면 건너뛴다"만으로는 최신 상태를 따라갈 수 없고, 언젠가 다시 받아야 한다.

    코드에는 그 능력이 **이미 배선돼 있다** — `collect_spec/status/appraisal/images` 와
    디스패처 `collect_document` 가 전부 `overwrite` 를 받는다. 그런데 **아무도 True 를
    넘기지 않고 테스트도 없었다.** 그래서 "재수집 정책을 정하면 곧바로 쓸 수 있는가"가
    미지수였다. 이 검사가 그 미지수를 없앤다 — 정책은 제품이 정하되, **기계가 동작한다는
    사실은 여기서 고정**한다.

    함께 고정하는 것:
      - 기본값(overwrite=False)은 **다시 받지 않는다** — 중복 다운로드 방지가 깨지면
        매일 전체를 다시 받게 된다.
      - overwrite=True 는 바이트가 실제로 바뀐다 — 스킵만 우회하고 저장은 안 하면 의미가 없다.
      - 순번/개수 계약은 재수집 뒤에도 그대로다.
    """
    print("\n--- 5-B. overwrite 로 재수집이 되는가 (Sprint 184) ---")
    from crawler.image_crawler import collect_images
    from crawler.image_assets import list_stored_images

    env = Env()
    try:
        court, case_no, item_no = env.seed_item()

        # 1차 수집 — 원본 사진
        first = collect_images(FakeDriver([
            img_el("전경도", 1, make_jpeg(525, 700)),
            img_el("전경도", 2, make_jpeg(525, 700)),
        ]), court, case_no, item_no)
        check("1차 수집 성공", first["success"], True)
        check("1차 장수", first["image_count"], 2)

        # ★ 바이트를 그대로 비교하지 않는다 — 실패 메시지에 JPEG 원본이 통째로 찍혀
        #   로그가 수십 KB로 부풀고, 정작 무엇이 다른지 읽을 수 없다. 해시로 비교한다.
        def _digests():
            rows = sorted(list_stored_images(court, case_no, item_no), key=lambda x: x["seq"])
            return [hashlib.sha256(open(r["path"], "rb").read()).hexdigest()[:12] for r in rows]

        stored = sorted(list_stored_images(court, case_no, item_no), key=lambda x: x["seq"])
        check("1차 저장 파일 수", len(stored), 2)
        before_bytes = _digests()
        before_hash = first["new_hash"]

        # 2차 — 법원이 사진을 **교체**했다고 가정(다른 크기 = 다른 바이트).
        #      기본값(overwrite 없음)이면 기존 파일을 그대로 두어야 한다.
        changed = [
            img_el("전경도", 1, make_jpeg(300, 400)),
            img_el("전경도", 2, make_jpeg(300, 400)),
        ]
        skipped = collect_images(FakeDriver(list(changed)), court, case_no, item_no)
        check("기본값은 다시 받지 않는다(중복 다운로드 방지)", _digests(), before_bytes)
        check("기본 경로도 성공으로 끝난다", skipped["success"], True)

        # 3차 — overwrite=True 면 실제로 갈아끼워야 한다.
        forced = collect_images(FakeDriver(list(changed)), court, case_no, item_no,
                                overwrite=True)
        check("재수집 성공", forced["success"], True)
        check("재수집 후 장수 계약 유지", forced["image_count"], 2)

        after = sorted(list_stored_images(court, case_no, item_no), key=lambda x: x["seq"])
        after_bytes = _digests()
        check("재수집 후 파일 수 동일", len(after), 2)
        check_true("재수집이 바이트를 실제로 바꿨다", after_bytes != before_bytes,
                   "overwrite=True 인데 파일이 그대로다 - 스킵만 우회하고 저장이 안 된다")
        check("순번 계약 유지", [s["seq"] for s in after], [1, 2])
        check_true("집합 해시도 바뀐다(변경 감지에 쓰는 값)",
                   forced["new_hash"] != before_hash,
                   (before_hash, forced["new_hash"]))
    finally:
        env.close()



def test_image_change_detection():
    """사진이 **바뀌었는지**를 수집기가 판별할 수 있는가 (2026-08-17 Sprint 186).

    ## 왜 이 검사가 생겼나

    `collect_images()` 는 `previous_hash` 를 항상 `""` 로 두고 끝내 계산하지 않았다.
    그런데 `mark_queue_done()` 의 변경 감지 조건은 이렇다:

        if previous_hash and previous_hash != new_hash:  -> document_version_log 기록

    `previous_hash` 가 늘 빈 문자열이면 이 조건은 **이미지에서 영원히 거짓**이다.
    즉 재수집을 켜도 사진 교체가 어디에도 기록되지 않는다. 문서 수집기는 같은 자리에서
    이미 `calc_file_hash()` 로 계산하고 있었다 — 이미지만 빠져 있었다.

    ## 이 검사가 고정하는 것

    세 경우가 서로 다른 결과를 내야 한다. 하나라도 뭉개지면 변경 감지가 무의미해진다.

        최초 수집       previous_hash == ""            (비교할 이전 상태가 없다)
        같은 사진 재수집 previous_hash == new_hash      (거짓 개정을 만들지 않는다)
        다른 사진 재수집 previous_hash != new_hash      (개정을 놓치지 않는다)

    ★ 두 번째가 특히 중요하다. 그것이 통과하려면 **디스크에서 계산한 공식과 수집
      결과에서 계산한 공식이 정확히 같아야** 한다. 공식이 갈라지면 매 수집이 "변경됨"이
      되어 진짜 개정을 찾을 수 없게 된다.
    """
    print("\n--- 5-C. 사진 변경 감지 (Sprint 186) ---")
    from crawler.image_crawler import collect_images

    env = Env()
    try:
        court, case_no, item_no = env.seed_item()

        same = [img_el("전경도", 1, make_jpeg(525, 700)),
                img_el("전경도", 2, make_jpeg(525, 700))]

        # (1) 최초 수집 — 비교할 이전 상태가 없다
        first = collect_images(FakeDriver(list(same)), court, case_no, item_no)
        check("최초 수집 성공", first["success"], True)
        check("최초에는 이전 지문이 없다", first["previous_hash"], "")
        check_true("새 지문은 만들어진다", bool(first["new_hash"]), first["new_hash"])

        # (2) 같은 사진으로 재수집 — 이전 지문이 새 지문과 같아야 한다.
        #     (같으면 mark_queue_done 이 개정으로 기록하지 않는다)
        again = collect_images(FakeDriver(list(same)), court, case_no, item_no,
                               overwrite=True)
        check("재수집도 성공", again["success"], True)
        check("이전 지문이 1차의 새 지문과 같다", again["previous_hash"], first["new_hash"])
        check("내용이 같으면 지문도 같다(거짓 개정 없음)",
              again["previous_hash"], again["new_hash"])

        # (3) 사진이 교체된 상태로 재수집 — 지문이 달라야 한다.
        changed = [img_el("전경도", 1, make_jpeg(300, 400)),
                   img_el("전경도", 2, make_jpeg(300, 400))]
        third = collect_images(FakeDriver(list(changed)), court, case_no, item_no,
                               overwrite=True)
        check("교체 후에도 성공", third["success"], True)
        check("이전 지문은 2차 시점 값이다", third["previous_hash"], again["new_hash"])
        check_true("내용이 바뀌면 지문도 바뀐다(개정 감지)",
                   third["previous_hash"] != third["new_hash"],
                   (third["previous_hash"], third["new_hash"]))

        # (4) 그 값이 실제로 개정 기록으로 이어지는가 — mark_queue_done 계약과 연결한다.
        from storage.database import mark_queue_done
        qid = env.enqueue(court, case_no, item_no, "image")
        mark_queue_done(qid, court, case_no, item_no, "image",
                        third["previous_hash"], third["new_hash"],
                        status="READY", files_saved=[i["path"] for i in third["images"]])
        c = env.conn()
        try:
            n = c.execute("SELECT COUNT(*) FROM document_version_log"
                          " WHERE case_no=? AND doc_type='image'", (case_no,)).fetchone()[0]
        finally:
            c.close()
        check("지문이 다르면 개정 이력이 남는다", n, 1)
    finally:
        env.close()


def test_format_change_leaves_no_ghost_file():
    """법원이 같은 자리 사진을 **다른 형식**으로 바꿔 끼운 경우 (2026-08-18 Sprint 189, BUGS #120).

    ## 왜 이 검사가 생겼나

    파일 이름이 `<순번>.<확장자>`라 확장자가 곧 이름의 일부다. `sniff_image_ext()`는
    선언된 MIME이 아니라 **실제 바이트**로 형식을 판정하므로(법원은 JPEG를
    `image/png`로 선언한다), 원본이 JPEG -> PNG로 바뀌면 저장 경로도 `01.jpg` -> `01.png`로
    함께 바뀐다. 그런데 **옛 `01.jpg`를 아무도 지우지 않았다.**

    결과가 둘 다 나쁘다:

        고아 파일   `auction_image`는 UNIQUE(item_id, seq)라 새 경로 한 줄만 갖는다
                    -> 옛 파일은 아무도 가리키지 않은 채 디스크에 영원히 남는다
        거짓 개정   `_existing_set_hash()`가 같은 순번을 **두 번** 세어, 순번당 한 장을
                    전제로 만든 수집 쪽 `new_hash`와 공식이 갈라진다
                    -> 이후 매 수집이 "변경됨"이 되어 **진짜 개정을 찾을 수 없다**

    두 번째가 치명적이다. 바로 위 5-C가 지키는 불변식("내용이 같으면 지문도 같다")을
    **형식 변경 한 번으로 영구히 깨뜨린다.** 재수집(Sprint 189)을 켜는 순간 도달하는 경로다.
    """
    print("\n--- 5-D. 형식이 바뀌어도 같은 순번에 파일이 하나만 남는다 (Sprint 189) ---")
    from crawler.image_crawler import collect_images, _existing_set_hash
    from crawler.image_assets import list_stored_images

    env = Env()
    try:
        court, case_no, item_no = env.seed_item()

        # (1) JPEG로 최초 수집
        first = collect_images(FakeDriver([img_el("전경도", 1, make_jpeg(525, 700))]),
                               court, case_no, item_no)
        check("최초 수집 성공", first["success"], True)
        check("저장 파일 1개", [os.path.basename(r["path"])
                                for r in list_stored_images(court, case_no, item_no)],
              ["01.jpg"])

        # (2) 같은 순번을 PNG로 교체해 재수집
        second = collect_images(FakeDriver([img_el("전경도", 1, make_png(300, 200))]),
                                court, case_no, item_no, overwrite=True)
        check("교체 수집 성공", second["success"], True)

        names = sorted(os.path.basename(r["path"])
                       for r in list_stored_images(court, case_no, item_no))
        check("같은 순번에 파일이 하나만 남는다(옛 확장자 정리)", names, ["01.png"])

        # (3) 결정적 검사 — 디스크 공식과 수집 공식이 여전히 일치하는가.
        #     고아가 남으면 여기서 두 값이 갈라진다(그리고 이후 모든 수집이 거짓 개정이 된다).
        check("교체 뒤에도 디스크 지문 == 방금 수집한 지문",
              _existing_set_hash(court, case_no, item_no), second["new_hash"])

        # (4) 같은 PNG로 한 번 더 — 거짓 개정이 생기지 않아야 한다.
        third = collect_images(FakeDriver([img_el("전경도", 1, make_png(300, 200))]),
                               court, case_no, item_no, overwrite=True)
        check("내용이 같으면 지문도 같다(형식 변경 이후에도 유지)",
              third["previous_hash"], third["new_hash"])

        # (5) DB가 가리키는 경로가 실제 파일이다(고아 경로를 들고 있지 않다).
        c = env.conn()
        try:
            rows = c.execute("SELECT seq, storage_path FROM auction_image"
                             " WHERE item_id=1 ORDER BY seq").fetchall()
        finally:
            c.close()
        from storage.database import save_auction_images
        save_auction_images(court, case_no, item_no, third["images"], complete=True)
        c = env.conn()
        try:
            rows = c.execute("SELECT seq, storage_path FROM auction_image"
                             " WHERE item_id=1 ORDER BY seq").fetchall()
        finally:
            c.close()
        check("DB 행도 순번당 하나", [r["seq"] for r in rows], [1])
        check_true("DB가 가리키는 파일이 실제로 있다",
                   all(os.path.isfile(os.path.join(env.dir, r["storage_path"])) for r in rows),
                   [r["storage_path"] for r in rows])
    finally:
        env.close()


def test_duplicate_seq_on_disk_refuses_to_fingerprint():
    """같은 순번 파일이 둘이면 지문 비교를 **포기**한다 (2026-08-18 Sprint 189).

    위 5-D가 이제 그런 잔재를 만들지 않지만, 과거 수집이 남긴 것이 있을 수 있다.
    반쪽 지문으로 비교하면 바뀌지 않았는데 "변경됨"으로 기록된다 — `OSError` 분기가
    같은 이유로 이미 `""`를 돌려주는 것과 같은 판단이다.
    """
    print("\n--- 5-E. 같은 순번 중복 파일이면 지문을 만들지 않는다 (Sprint 189) ---")
    from crawler.image_crawler import _existing_set_hash
    from crawler.image_assets import image_path, ensure_image_dir

    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        ensure_image_dir(court, case_no, item_no)
        with open(image_path(court, case_no, item_no, 1, "jpg"), "wb") as f:
            f.write(make_jpeg(100, 100))
        check_true("한 장이면 지문이 나온다",
                   bool(_existing_set_hash(court, case_no, item_no)))

        with open(image_path(court, case_no, item_no, 1, "png"), "wb") as f:
            f.write(make_png(100, 100))
        check("같은 순번이 둘이면 빈 지문(비교 포기)",
              _existing_set_hash(court, case_no, item_no), "")
    finally:
        env.close()


def test_refresh_does_not_rewrite_identical_photos():
    """재수집이어도 **바이트가 같으면 파일을 다시 쓰지 않는다** (2026-08-18 Sprint 189).

    ## 왜 이 검사가 생겼나

    법원 사진은 base64 로 페이지에 박혀 오므로 "다시 받는 비용"은 0이다. 그래서 재수집을
    켤 때 `overwrite=True` 로 무조건 다시 쓰는 것이 자연스러워 보인다. 그런데 같은 바이트를
    다시 쓰면 **mtime 이 바뀐다.** 서빙 쪽 ETag 는 Starlette 가 (mtime, size) 로 만들기
    때문에(`api/v1/images.py` + `api/http_cache.py`), 내용이 그대로여도 **모든 브라우저
    캐시가 무효화되어 물건당 약 1.3~1.9MB 를 다시 내려받는다.**

    재수집 대상은 정의상 "사용자가 지금 보고 있는" 물건이라 체감이 가장 큰 자리다.
    목표 문서의 상황 A("이미지가 동일함 -> 재다운로드/불필요한 변경 최소화")가 정확히 이것이다.

    ★ 대조군을 함께 고정한다 — 사진이 **바뀌면** 반드시 쓴다. 구분하지 못하면 이 검사는
      "아무것도 안 하는 재수집"을 통과시켜 버린다.
    """
    print("\n--- 5-F. 재수집이어도 같은 사진은 다시 쓰지 않는다 (Sprint 189) ---")
    from crawler.image_crawler import collect_images
    from crawler.image_assets import image_path

    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        same_bytes = make_jpeg(525, 700)

        first = collect_images(FakeDriver([img_el("전경도", 1, same_bytes),
                                          img_el("전경도", 2, same_bytes)]),
                               court, case_no, item_no)
        check("최초 수집 성공", first["success"], True)

        p1 = image_path(court, case_no, item_no, 1, "jpg")
        p2 = image_path(court, case_no, item_no, 2, "jpg")
        before = (os.stat(p1).st_mtime_ns, os.stat(p2).st_mtime_ns)

        # 같은 사진으로 재수집 — 파일을 건드리면 안 된다.
        again = collect_images(FakeDriver([img_el("전경도", 1, same_bytes),
                                          img_el("전경도", 2, same_bytes)]),
                               court, case_no, item_no, overwrite=True)
        check("재수집도 성공", again["success"], True)
        check("지문이 같다(개정 아님)", again["previous_hash"], again["new_hash"])
        check("mtime 이 그대로다(ETag 보존)",
              (os.stat(p1).st_mtime_ns, os.stat(p2).st_mtime_ns), before)
        # DB 갱신에 필요한 정보는 그대로 돌려줘야 한다 — 안 그러면 auction_image 가
        # "이번에 아무것도 안 왔다"로 오해해 옛 행을 지운다(부분수집 보호와 충돌).
        check("사진 목록은 그대로 돌려준다", [i["seq"] for i in again["images"]], [1, 2])
        check("파일 크기도 담겨 있다",
              [i["file_size"] for i in again["images"]], [len(same_bytes)] * 2)

        # 대조군 — 2번만 바뀌면 2번만 다시 쓴다.
        other = make_jpeg(300, 400)
        third = collect_images(FakeDriver([img_el("전경도", 1, same_bytes),
                                          img_el("전경도", 2, other)]),
                               court, case_no, item_no, overwrite=True)
        check("변경 수집 성공", third["success"], True)
        # ★ 방향에 따라 근거를 다르게 쓴다.
        #   "안 썼다"는 mtime 으로 확실히 말할 수 있다(쓰지 않았으면 절대 안 바뀐다).
        #   "썼다"는 mtime 으로 말할 수 없다 — Windows 파일시스템의 타임스탬프 갱신
        #   간격보다 두 쓰기가 더 가까우면 같은 값이 나온다(실측으로 실제 플레이크를
        #   겪었다). 그래서 그쪽은 **내용**으로 확인한다.
        check("바뀌지 않은 1번은 mtime 유지", os.stat(p1).st_mtime_ns, before[0])
        check("바뀌지 않은 1번은 내용도 그대로",
              hashlib.sha256(open(p1, "rb").read()).hexdigest(),
              hashlib.sha256(same_bytes).hexdigest())
        check("2번 내용이 실제로 교체된다",
              hashlib.sha256(open(p2, "rb").read()).hexdigest(),
              hashlib.sha256(other).hexdigest())
        check_true("집합 지문이 바뀐다(개정 감지)",
                   third["previous_hash"] != third["new_hash"],
                   (third["previous_hash"], third["new_hash"]))

        # ★ 로그/반환값이 **사실**을 말하는가 (2026-08-18 Sprint 190).
        #   무변경 스킵이 생긴 뒤로 완료 로그가 "5장 저장 완료"를 **한 장도 안 썼을 때도**
        #   찍고 있었다(실 브라우저 실행에서 실측). BUGS #47 이래 이 저장소가 반복해
        #   잡아 온 "로그가 거짓을 말한다" 부류라, 숫자를 반환값에도 담아 고정한다.
        check("무변경 재수집: 쓴 장수 0 / 그대로 둔 장수 2",
              (again["written"], again["unchanged"]), (0, 2))
        check("1장만 바뀐 재수집: 쓴 장수 1 / 그대로 둔 장수 1",
              (third["written"], third["unchanged"]), (1, 1))
        check("최초 수집: 쓴 장수 2 / 그대로 둔 장수 0",
              (first["written"], first["unchanged"]), (2, 0))
    finally:
        env.close()


def test_reduced_photo_count_removes_files_too():
    """법원이 사진 수를 줄이면 **파일까지** 정리되는가 (2026-08-18 Sprint 191, BUGS #127).

    ## 왜 이 검사가 생겼나

    `save_auction_images()`는 DB 행만 지운다. **파일은 아무도 안 지웠다.** 그래서
    5장 -> 3장으로 줄면 04/05 파일이 디스크에 영원히 남았다. 결과는 둘 다 나쁘다:

        고아 파일   auction_image 가 가리키지 않는 파일이 계속 쌓인다
        거짓 개정   `_existing_set_hash()`는 **파일시스템**을 근거로 삼으므로 옛 파일까지
                    세고, 수집 쪽 공식(이번에 받은 것만)과 갈라진다
                    -> 이후 매 수집이 "변경됨"

    두 번째가 BUGS #120과 **완전히 같은 실패 방식**이다. #120을 고칠 때 "같은 순번의 다른
    확장자"만 봤고, "이제 존재하지 않는 순번"은 놓쳤다 — 그래서 계열 전수 검색으로 찾았다.

    재현(2026-08-18, 수정 전): 5장 -> 3장 재수집 후 디스크에 5개가 그대로 남고
    `previous_hash`(5장 기준) != `new_hash`(3장 기준)가 영구히 성립했다.

    ## 대조군이 핵심이다

    "지운다"만 검사하면 **부분 수집에서도 지우는** 구현이 통과한다. 그건 사용자가 보던
    사진을 잃는, 고치려던 것보다 나쁜 결함이다. 그래서 세 경우를 함께 고정한다.
    """
    print("\n--- 5-G. 사진이 줄면 파일도 정리된다 (Sprint 191, BUGS #127) ---")
    from crawler.image_crawler import collect_images, _existing_set_hash
    from crawler.image_assets import list_stored_images

    def names(court, case_no, item_no):
        return sorted(os.path.basename(r["path"])
                      for r in list_stored_images(court, case_no, item_no))

    # (D) 법원이 실제로 줄였다 -> 파일도 정리된다
    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        five = [img_el("전경도", i, make_jpeg(100 + i, 200)) for i in range(1, 6)]
        first = collect_images(FakeDriver(list(five)), court, case_no, item_no)
        check("최초 5장", len(first["images"]), 5)
        check("디스크 5개", names(court, case_no, item_no),
              ["01.jpg", "02.jpg", "03.jpg", "04.jpg", "05.jpg"])

        three = [img_el("전경도", i, make_jpeg(100 + i, 200)) for i in range(1, 4)]
        second = collect_images(FakeDriver(list(three)), court, case_no, item_no,
                                overwrite=True)
        check("재수집 3장", len(second["images"]), 3)
        check("부분 수집이 아니다", second["partial"], False)
        check("디스크도 3개로 줄었다", names(court, case_no, item_no),
              ["01.jpg", "02.jpg", "03.jpg"])
        # ★ 결정적 검사 — 두 공식이 다시 일치하는가(고아가 남으면 여기서 갈라진다)
        check("디스크 지문 == 방금 수집한 지문",
              _existing_set_hash(court, case_no, item_no), second["new_hash"])

        # 같은 3장으로 한 번 더 — 거짓 개정이 생기지 않아야 한다
        third = collect_images(FakeDriver(list(three)), court, case_no, item_no,
                               overwrite=True)
        check("줄어든 뒤에도 무변경이면 지문이 같다",
              third["previous_hash"], third["new_hash"])
    finally:
        env.close()

    # (B) 부분 수집이면 **절대** 지우지 않는다
    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        five = [img_el("전경도", i, make_jpeg(100 + i, 200)) for i in range(1, 6)]
        collect_images(FakeDriver(list(five)), court, case_no, item_no)
        check("최초 디스크 5개", len(names(court, case_no, item_no)), 5)

        # 3장은 정상, 2장은 디코드 실패 -> attempted 5 / saved 3 -> partial
        broken = ([img_el("전경도", i, make_jpeg(100 + i, 200)) for i in range(1, 4)]
                  + [img_el("전경도", i, b"") for i in (4, 5)])
        part = collect_images(FakeDriver(broken), court, case_no, item_no, overwrite=True)
        check("부분 수집으로 판정된다", part["partial"], True)
        check("부분 수집이면 파일을 지우지 않는다", names(court, case_no, item_no),
              ["01.jpg", "02.jpg", "03.jpg", "04.jpg", "05.jpg"])
    finally:
        env.close()

    # (C) 전체 실패면 아무것도 잃지 않는다
    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        five = [img_el("전경도", i, make_jpeg(100 + i, 200)) for i in range(1, 6)]
        collect_images(FakeDriver(list(five)), court, case_no, item_no)

        allbad = [img_el("전경도", i, b"") for i in range(1, 6)]
        fail = collect_images(FakeDriver(allbad), court, case_no, item_no, overwrite=True)
        check("전체 실패는 success=False", fail["success"], False)
        check("전체 실패에도 기존 사진 전부 보존", names(court, case_no, item_no),
              ["01.jpg", "02.jpg", "03.jpg", "04.jpg", "05.jpg"])
    finally:
        env.close()


def test_court_removed_all_photos_needs_two_sightings():
    """법원이 사진을 **전부** 내렸을 때 (2026-08-18 Sprint 191, BUGS #128).

    ## 왜 이 경로만 빠져 있었나

    사진 감소는 `save_auction_images()`가 처리하는데, `doc_worker` 는
    `if result.get("images")` 로 가드하므로 **0장으로 줄어드는 경우만 그 함수에 도달하지
    않는다**(빈 목록은 전체 실패와 구별되지 않으니 그 가드 자체는 옳다). 그래서:

        법원이 전부 내림 -> document_status = NO_IMAGE (상태만 바뀜)
                        -> auction_image 행/파일은 그대로
                        -> `_images_status()` 는 "행이 있으면 무조건 READY"
                        -> **사용자는 법원이 내린 사진을 영원히 본다**

    ## 두 번 확인 규칙

    "법원이 내렸다"와 "이번 관측이 실패했다"는 한 번으로 구별할 수 없고, 사진을 전부
    지우는 것은 이 파이프라인에서 가장 파괴적인 동작이다. 그래서 1회차는 남기고
    2회차에 정리한다. 1회차 기억은 `document_status` 자체가 한다(새 컬럼 없음).
    """
    print("\n--- 5-H. 법원이 사진을 전부 내렸다: 2회 확인 후 정리 (Sprint 191, BUGS #128) ---")
    from storage.database import (clear_images_if_absence_confirmed,
                                  save_auction_images, _set_document_status,
                                  get_connection)
    from crawler.image_assets import remove_stored_image_files, image_path, ensure_image_dir

    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        ensure_image_dir(court, case_no, item_no)
        imgs = []
        for seq in (1, 2, 3):
            pth = image_path(court, case_no, item_no, seq, "jpg")
            with open(pth, "wb") as f:
                f.write(make_jpeg(100 + seq, 200))
            imgs.append({"seq": seq, "kind": "전경도", "path": pth,
                         "file_hash": "h%d" % seq, "width": 1, "height": 1})
        save_auction_images(court, case_no, item_no, imgs)
        check("사진 3장 기록", len(env.images_of(1)), 3)

        # --- 1회차: 상태가 아직 READY 인데 no_asset 이 관측됐다 -> 남긴다 ---
        first = clear_images_if_absence_confirmed(court, case_no, item_no)
        check("1회차는 지우지 않는다", first["cleared"], 0)
        check("1회차임을 알린다", first["first_sighting"], True)
        check("사진 3장 그대로", len(env.images_of(1)), 3)
        check("파일도 그대로", len(os.listdir(os.path.dirname(imgs[0]["path"]))), 3)

        # doc_worker 는 이어서 mark_queue_done(status='NO_IMAGE') 을 부른다 — 그 효과를 재현
        conn = get_connection()
        try:
            _set_document_status(conn, court, case_no, item_no, "image", "NO_IMAGE")
            conn.commit()
        finally:
            conn.close()

        # --- 2회차: 이미 NO_IMAGE 인데 또 no_asset -> 이제 정리한다 ---
        second = clear_images_if_absence_confirmed(court, case_no, item_no)
        check("2회차에 정리한다", second["cleared"], 3)
        check("2회차는 1회차가 아니다", second["first_sighting"], False)
        check("DB 행이 비었다", len(env.images_of(1)), 0)

        gone = remove_stored_image_files(second["paths"])
        check("파일도 정리된다", gone, 3)
        check("디렉터리가 비었다",
              os.listdir(os.path.dirname(imgs[0]["path"])), [])

        # --- 3회차: 지울 것이 없으면 조용히 0 ---
        third = clear_images_if_absence_confirmed(court, case_no, item_no)
        check("이미 비었으면 아무 일도 없다", (third["cleared"], third["first_sighting"]),
              (0, False))

        # --- 정리 후 화면 상태가 정직해진다 (핵심 사용자 영향) ---
        from api.v1.item import _images_status
        rows = [{"doc_type": "IMAGE", "status": "NO_IMAGE"}]
        check("행이 사라지면 화면도 '사진 없음'으로 답한다",
              _images_status(rows, 0), "NO_IMAGE")
        check("행이 남아 있는 동안에는 READY(볼 수 있는 것은 사실이다)",
              _images_status(rows, 3), "READY")
    finally:
        env.close()


def test_three_sources_never_diverge():
    """★ 구조적 가드: **수집 결과 / 디스크 / DB** 세 근거가 절대 갈라지지 않는다.

    ## 왜 목록이 아니라 불변식인가

    이 저장소의 사진 결함은 전부 **같은 한 문장**으로 요약된다 —
    *"세 근거 중 둘이 갈라졌다."*

        BUGS #113  수집 결과에는 지문이 있는데 비교 대상(디스크)을 안 봤다
        BUGS #114  디스크는 줄었는데 DB를 지웠다(부분 수집인데)
        BUGS #120  형식이 바뀌자 디스크에 순번이 둘이 됐다(수집 결과는 하나)
        BUGS #127  DB는 줄었는데 디스크가 안 줄었다
        BUGS #128  법원은 0장인데 DB/디스크가 그대로였다

    개별 검사를 하나씩 늘리는 방식은 **다음 인스턴스를 못 잡는다**(#120을 고칠 때
    #127을 놓친 것이 그 증거다). 그래서 시나리오를 표로 돌리며 매 단계 불변식을 건다.
    새 시나리오는 표에 한 줄만 추가하면 된다.

    ## 불변식

        완전 수집(partial=False)이면:
            set(디스크 순번) == set(수집 결과 순번) == set(DB 순번)
        부분 수집(partial=True)이면:
            디스크/DB 는 **줄어들지 않는다**(사용자가 보던 것을 잃지 않는다)
    """
    print("\n--- 5-I. 세 근거(수집/디스크/DB)가 갈라지지 않는다 (Sprint 191) ---")
    from crawler.image_crawler import collect_images
    from crawler.image_assets import list_stored_images
    from storage.database import save_auction_images

    # (라벨, 법원이 이번에 주는 것)  — payload=None 이면 깨진 데이터(디코드 실패)
    JPG = lambda n: make_jpeg(100 + n, 200)
    PNG = lambda n: make_png(100 + n, 200)
    SCENARIOS = [
        ("신규 3장",            [(1, JPG), (2, JPG), (3, JPG)]),
        ("동일 재수집",          [(1, JPG), (2, JPG), (3, JPG)]),
        ("2번만 형식 변경",       [(1, JPG), (2, PNG), (3, JPG)]),
        ("1장 추가",             [(1, JPG), (2, PNG), (3, JPG), (4, JPG)]),
        ("가운데 1장 삭제",       [(1, JPG), (2, PNG), (4, JPG)]),
        ("뒤 2장 삭제",          [(1, JPG), (2, PNG)]),
        ("부분 수집(4중 2 실패)",  [(1, JPG), (2, PNG), (3, None), (4, None)]),
        ("다시 완전 수집 4장",     [(1, JPG), (2, JPG), (3, JPG), (4, JPG)]),
    ]

    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        prev_disk, prev_db = set(), set()

        for label, spec in SCENARIOS:
            els = [img_el("전경도", seq, (fn(seq) if fn else b""))
                   for seq, fn in spec]
            res = collect_images(FakeDriver(els), court, case_no, item_no,
                                 overwrite=True)
            if res.get("images"):
                save_auction_images(court, case_no, item_no, res["images"],
                                    complete=not res.get("partial"))

            collected = {r["seq"] for r in res.get("images", [])}
            disk = {r["seq"] for r in list_stored_images(court, case_no, item_no)}
            dbseq = {r["seq"] for r in env.images_of(1)}

            if res.get("partial"):
                # 부분 수집: 잃지 않는 것이 규칙이다(정확히 같아질 필요는 없다).
                check_true("[%s] 부분 수집은 디스크를 잃지 않는다" % label,
                           prev_disk <= disk, (sorted(prev_disk), sorted(disk)))
                check_true("[%s] 부분 수집은 DB를 잃지 않는다" % label,
                           prev_db <= dbseq, (sorted(prev_db), sorted(dbseq)))
            else:
                check("[%s] 수집결과 == 디스크" % label, sorted(disk), sorted(collected))
                check("[%s] 수집결과 == DB" % label, sorted(dbseq), sorted(collected))

            # 어떤 경우든 DB가 가리키는 파일은 실제로 존재해야 한다.
            missing = [r["storage_path"] for r in env.images_of(1)
                       if not os.path.isfile(env.apiimg.resolve_stored_path(
                           r["storage_path"]))]
            check("[%s] DB가 가리키는 파일이 전부 존재한다" % label, missing, [])

            prev_disk, prev_db = disk, dbseq

        # 마지막 상태가 실제로 의미 있는 값인지 — 표가 통째로 no-op 이 아니었음을 보증
        check_true("시나리오를 실제로 통과했다(마지막 4장)", prev_db == {1, 2, 3, 4},
                   sorted(prev_db))
    finally:
        env.close()


def test_no_photos_is_not_a_failure():
    """법원이 사진을 안 주는 물건 — 실패로 기록하면 영원히 재시도된다."""
    print("\n--- 6. 사진 없음은 실패가 아니다 ---")
    from crawler.image_crawler import collect_images
    import crawler.image_crawler as ic
    env = Env()
    saved = ic.IMAGE_WAIT_SECONDS
    ic.IMAGE_WAIT_SECONDS = 0.1     # 없는 것을 기다리느라 테스트가 느려지지 않게
    try:
        court, case_no, item_no = env.seed_item()
        res = collect_images(FakeDriver([]), court, case_no, item_no)
        check("성공으로 종결", res["success"], True)
        check("자산 없음 표시", res["no_asset"], True)
        check("저장 0장", res["image_count"], 0)
        check("저장 파일 없음", res["files_saved"], [])
    finally:
        ic.IMAGE_WAIT_SECONDS = saved
        env.close()


def test_dom_change_is_a_failure_not_silent_success():
    """사진 요소는 있는데 alt 규칙에 하나도 안 맞으면 **실패**여야 한다.

    조용히 성공으로 넘기면 법원이 DOM을 바꾼 날 이후 모든 물건의 사진이
    사라진 것을 아무도 모르게 된다.
    """
    print("\n--- 7. DOM 규칙 변경은 조용히 성공하지 않는다 ---")
    from crawler.image_crawler import collect_images
    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        driver = FakeDriver([
            FakeElement({"alt": "알수없는형태", "src": data_uri(make_jpeg())}),
            FakeElement({"alt": "", "src": data_uri(make_jpeg())}),
        ])
        res = collect_images(driver, court, case_no, item_no)
        check("실패로 처리", res["success"], False)
        check("자산 없음으로 오해하지 않는다", res["no_asset"], False)
        check("저장 0장", res["image_count"], 0)
    finally:
        env.close()


def test_bad_payloads_are_rejected():
    print("\n--- 8. 못 쓰는 데이터는 저장하지 않는다 ---")
    from crawler.image_crawler import collect_images
    from crawler.image_assets import list_stored_images
    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        driver = FakeDriver([
            img_el("전경도", 1, make_jpeg()),                       # 정상
            FakeElement({"alt": "전경도_2", "src": "https://x/y.jpg"}),   # data URI 아님
            img_el("전경도", 3, b"%PDF-1.4 not an image" + b"\x00" * 4096),  # 이미지 아님
            img_el("전경도", 4, b"\xff\xd8\xff" + b"\x00" * 10),      # 너무 작다
        ])
        res = collect_images(driver, court, case_no, item_no)
        check("한 장만 저장", res["image_count"], 1)
        check("부분 성공으로 표시", res["partial"], True)
        check("성공(한 장이라도 건졌다)", res["success"], True)
        check("디스크에도 한 장만", len(list_stored_images(court, case_no, item_no)), 1)
    finally:
        env.close()


NL = chr(10)


def test_duplicate_seq_defense():
    """같은 순번의 후보가 여럿이면 **가장 큰 것**을 쓴다 (2026-08-21 Sprint 243 규칙 변경).

    ## 왜 "먼저 나온 것"에서 바꿨나

    예전 규칙은 "먼저 나온 것을 쓰고 뒤엣것을 버린다"였다. 그런데 이 파일이 검사하는
    수집기(`crawler/image_crawler.py`)의 주석이 그 위험을 이미 적어 두고 있었다 -
    "캐러셀이 썸네일까지 같은 id 규칙으로 그리는 경우".

    그 경우 DOM 순서상 **썸네일이 먼저** 오는 것이 자연스럽다. 즉 옛 규칙은
    **큰 사진을 눈앞에 두고 작은 것을 저장**할 수 있었고, 그것이 조용히 일어났다
    (로그도 "뒤엣것을 무시"라고만 남았다).

    크기로 고르면 그 위험이 사라진다. 후보가 하나뿐인 경우 동작은 완전히 같다 -
    2026-08-21 실측에서 운영 사진 45장은 전부 단일 후보였고 전부 긴 변 700px 였다.

    ## 이 검사가 잠그는 것

    "중복이면 하나만"(옛 계약)은 그대로 유지하면서, **어느 것을 남기는가**를
    크기 기준으로 고정한다. DOM 순서에 의존하지 않는다는 뜻이기도 하다.
    """
    print(NL + "--- 9. 같은 순번 중복: 가장 큰 것을 채택 ---")
    from crawler.image_crawler import collect_images
    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        small, big = make_jpeg(100, 100), make_jpeg(200, 200)
        # (1) 작은 것이 **먼저** 와도 큰 것을 남긴다 (옛 규칙이라면 작은 것을 남겼다)
        driver = FakeDriver([img_el("전경도", 1, small), img_el("위치도", 1, big)])
        res = collect_images(driver, court, case_no, item_no)
        check("순번 중복은 하나만 채택", res["image_count"], 1)
        check("★ 작은 것이 먼저 와도 **큰 것**을 남긴다",
              (res["images"][0]["width"], res["images"][0]["height"]), (200, 200))
        check("남긴 것의 종류도 큰 쪽의 것이다", res["images"][0]["kind"], "위치도")
    finally:
        env.close()

    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        small, big = make_jpeg(100, 100), make_jpeg(200, 200)
        # (2) 순서를 뒤집어도 결과가 같다 - DOM 순서에 의존하지 않는다
        driver = FakeDriver([img_el("위치도", 1, big), img_el("전경도", 1, small)])
        res = collect_images(driver, court, case_no, item_no)
        check("순번 중복은 하나만 채택(역순)", res["image_count"], 1)
        check("★ 순서를 뒤집어도 큰 것을 남긴다(DOM 순서 비의존)",
              (res["images"][0]["width"], res["images"][0]["height"]), (200, 200))
    finally:
        env.close()


def test_rerun_is_idempotent_and_recovers_db():
    """두 번 돌려도 파일이 두 벌 쌓이지 않고, 파일만 있고 DB가 빈 상태를 스스로 복구한다."""
    print("\n--- 10. 재실행 멱등성 / DB 자가복구 ---")
    from crawler.image_crawler import collect_images
    from storage.database import save_auction_images
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        els = [img_el("전경도", 1, make_jpeg()), img_el("위치도", 2, make_gif())]

        r1 = collect_images(FakeDriver(els), court, case_no, item_no)
        save_auction_images(court, case_no, item_no, r1["images"])
        check("1차 DB 행", len(env.images_of(1)), 2)

        # DB만 지우고 다시 수집 — 파일은 이미 있으므로 다시 쓰지 않지만,
        # DB 행은 다시 만들어져야 한다("파일은 있는데 DB가 없는" 상태의 자가복구).
        c = env.conn()
        c.execute("DELETE FROM auction_image")
        c.commit()
        c.close()

        r2 = collect_images(FakeDriver(els), court, case_no, item_no)
        check("2차에도 2장을 보고한다(기존 파일 재사용)", r2["image_count"], 2)
        save_auction_images(court, case_no, item_no, r2["images"])
        check("DB 행이 복구된다", len(env.images_of(1)), 2)

        # 파일 개수가 늘지 않았는지
        d = os.path.dirname(r1["images"][0]["path"])
        check("파일이 두 벌 쌓이지 않는다", len(os.listdir(d)), 2)
    finally:
        env.close()


# ===========================================================================
# 11. 저장 계층 (storage/database.py)
# ===========================================================================

def test_case_level_status_reuse():
    """사건 단위 문서(현황조사서)를 형제 물건에서 재사용하는가 (2026-08-17 Sprint 145).

    ## 왜 이 최적화가 정당한가 (실측 근거)

    같은 사건의 물건 1과 물건 2에 대해 **각각 따로** 실제 수집을 돌려 대조했다:

        status.html   40,596 B  해시 동일
        status.json   12,014 B  해시는 다르지만 `fields` 115개 키가 완전 일치
                                (차이는 우리가 찍는 extracted_at 하나뿐)

    비용: 사건 1,384 / 물건 1,876 -> 초과 수집 492회 x 약 22초 = **약 3시간**
    (doc_worker 가동 창 2시간을 넘긴다). 용량은 13.4MB로 무의미하다.

    ★ **저장 구조는 바뀌지 않는다** — 파일은 종전과 같은 경로에 같은 내용으로 놓이고,
      달라지는 것은 "그 바이트를 어디서 얻는가"뿐이다.
    """
    print("\n--- 10-B. 사건 단위 문서 형제 재사용 (Sprint 145) ---")
    import crawler.doc_crawler as dc
    from crawler.doc_paths import find_sibling_case_document, CASE_LEVEL_DOC_TYPES

    env = Env()
    try:
        court, case_no = "서울중앙지방법원", "2025타경311"
        # 물건 1에 정상 현황조사서를 심는다(사건번호가 들어 있어야 빈 캡처가 아니다)
        d1 = os.path.join(env.docs, court, case_no, "1")
        os.makedirs(d1)
        html = "<div id='curstExmndcPopUp'>사건번호 2025타경311 조사일시 ...</div>"
        payload = '{"extracted_at": "2026-08-17T02:00:00", "fields": {"a": "1"}}'
        with open(os.path.join(d1, "status.html"), "w", encoding="utf-8") as f:
            f.write(html)
        with open(os.path.join(d1, "status.json"), "w", encoding="utf-8") as f:
            f.write(payload)

        # --- 탐색기 자체
        found = find_sibling_case_document(court, case_no, "2", "status")
        check("물건2에서 물건1의 문서를 찾는다", os.path.basename(found or ""), "1")
        check("자기 자신은 형제로 치지 않는다",
              find_sibling_case_document(court, case_no, "1", "status"), None)
        check("사건 단위가 아닌 종류는 찾지 않는다",
              find_sibling_case_document(court, case_no, "2", "spec"), None)
        check("사건 단위 종류 목록", CASE_LEVEL_DOC_TYPES, ("status",))

        # 나이 제한: 아주 짧게 주면 재사용 대상이 아니다
        os.utime(os.path.join(d1, "status.json"), (0, 0))
        check("오래된 형제는 재사용하지 않는다",
              find_sibling_case_document(court, case_no, "2", "status", max_age_seconds=60),
              None)
        # 되돌린다
        import time as _t
        now = _t.time()
        os.utime(os.path.join(d1, "status.json"), (now, now))

        # --- 거절 조건 나머지 (2026-08-24 Sprint 254) ---
        #
        # 여기서 잘못 통과시키면 **남의 문서나 빈 파일**을 이 물건의 것으로 재사용한다.
        # 찾는 쪽이 틀리면 한 번 더 받으면 그만이지만, 거절이 틀리면 화면이 거짓을 말한다.
        check("사건 디렉터리가 아예 없으면 None",
              find_sibling_case_document(court, "2025타경999999", "2", "status"), None)

        # 형제 자리에 **디렉터리가 아닌 것**이 있으면 건너뛴다.
        with open(os.path.join(env.docs, court, case_no, "not-a-dir"), "w",
                  encoding="utf-8") as f:
            f.write("qa")
        check("형제 자리의 파일을 디렉터리로 착각하지 않는다",
              os.path.basename(find_sibling_case_document(court, case_no, "2", "status") or ""),
              "1")

        # 대표 파일이 **없는** 형제(디렉터리만 있다) -> 건너뛴다.
        empty_sib = os.path.join(env.docs, court, case_no, "0")
        os.makedirs(empty_sib)
        found2 = find_sibling_case_document(court, case_no, "2", "status")
        check("대표 파일이 없는 형제는 재사용하지 않는다",
              os.path.basename(found2 or ""), "1")

        # 대표 파일이 **0바이트**인 형제 -> 건너뛴다(빈 파일은 문서가 아니다).
        with open(os.path.join(empty_sib, "status.json"), "w", encoding="utf-8"):
            pass
        found3 = find_sibling_case_document(court, case_no, "2", "status")
        check("0바이트 대표 파일은 재사용하지 않는다",
              os.path.basename(found3 or ""), "1")

        # 쓸 만한 형제가 하나도 남지 않으면 None 이다(공허하지 않은 대조군).
        os.utime(os.path.join(d1, "status.json"), (0, 0))
        check("쓸 만한 형제가 없으면 None",
              find_sibling_case_document(court, case_no, "2", "status",
                                         max_age_seconds=60), None)
        os.utime(os.path.join(d1, "status.json"), (now, now))

        # --- 실제 복사 (driver를 절대 쓰지 않는다: None을 넘겨 확인한다)
        res = dc.collect_status(None, court, case_no, "2", "qa-btn-unused")
        check("브라우저 없이 성공한다", res["success"], True)
        check("재사용 출처가 기록된다", os.path.basename(res.get("reused_from") or ""), "1")
        check("두 파일이 저장된다", len(res["files_saved"]), 2)

        d2 = os.path.join(env.docs, court, case_no, "2")
        with open(os.path.join(d2, "status.html"), encoding="utf-8") as f:
            check("html 내용이 원본과 같다", f.read(), html)
        with open(os.path.join(d2, "status.json"), encoding="utf-8") as f:
            check("json 내용이 원본과 같다", f.read(), payload)
        check_true("임시 파일이 남지 않는다",
                   not any(x.endswith(".tmp") for x in os.listdir(d2)), os.listdir(d2))

        # --- 이미 있으면 아예 건드리지 않는다(기존 스킵 경로가 먼저 잡는다)
        before = {n: os.stat(os.path.join(d2, n)) for n in os.listdir(d2)}
        res2 = dc.collect_status(None, court, case_no, "2", "qa-btn-unused")
        check("이미 있으면 스킵한다(성공)", res2["success"], True)
        # 스킵 경로는 `_empty_result()`를 그대로 돌려주므로 `reused_from` 키 자체가 없다.
        # 즉 "재사용도 하지 않았다"가 키 부재로 드러난다 — 그것을 고정한다.
        check_true("스킵 경로는 재사용을 타지 않는다(reused_from 키 없음)",
                   "reused_from" not in res2, sorted(res2))

        # ★ 2026-08-19 Sprint 217 (BUGS #144): 예전에는 이 자리에서
        #   `files_saved == []` 를 확인했다. 그 단언의 **의도**는 "다시 쓰지 않는다"인데,
        #   빈 목록을 그 증거로 삼은 것이 문제였다 — 그러다 보니 `_record_doc_raw()` 가
        #   `if not files_saved: return` 으로 실체 기록을 통째로 건너뛰는 결함
        #   (파일은 있는데 doc_raw 0행, 화면은 READY)을 이 검사가 **오히려 고정하고
        #   있었다.** 의도를 그대로 두고 증거만 바꾼다: 다시 쓰지 않았다는 것은
        #   **파일이 그대로라는 사실**로 확인하고, `files_saved` 는 이제
        #   "이번 판정의 근거가 된 실체 파일"을 가리킨다.
        after = {n: os.stat(os.path.join(d2, n)) for n in os.listdir(d2)}
        check("스킵 경로는 파일을 다시 쓰지 않는다(mtime/크기 그대로)",
              {n: (v.st_mtime_ns, v.st_size) for n, v in after.items()},
              {n: (v.st_mtime_ns, v.st_size) for n, v in before.items()})
        check("스킵 경로도 이미 가진 실체를 가리킨다",
              sorted(os.path.basename(x) for x in res2["files_saved"]),
              ["status.html", "status.json"])

        # --- ★ 형제가 빈 캡처면 퍼뜨리지 않는다
        d3dir = os.path.join(env.docs, court, "2025타경999", "1")
        os.makedirs(d3dir)
        with open(os.path.join(d3dir, "status.html"), "w", encoding="utf-8") as f:
            f.write("<div>사건번호 조사일시 검색결과가 없습니다</div>")   # 사건번호 값이 없다
        with open(os.path.join(d3dir, "status.json"), "w", encoding="utf-8") as f:
            f.write('{"fields": {}}')
        sib = find_sibling_case_document(court, "2025타경999", "2", "status")
        check_true("빈 캡처 형제도 탐색에는 걸린다(내용 검증은 복사 직전)", bool(sib), sib)
        out = dc._reuse_sibling_status(sib, os.path.join(env.docs, "x.html"),
                                       os.path.join(env.docs, "x.json"),
                                       court, "2025타경999", "2")
        check("빈 캡처는 복사하지 않는다(None -> 직접 수집)", out, None)
        check_true("빈 캡처가 퍼지지 않았다",
                   not os.path.exists(os.path.join(env.docs, "x.html")))
    finally:
        env.close()


def test_image_failure_retries_then_fails_permanently():
    """사진 수집이 실패하면 **재시도**되고, 재시도를 소진해야 FAILED가 되는가.

    2026-08-17 Sprint 145 신설. Sprint 144가 사진을 기존 큐에 편입했지만, 그 종류의
    **실패 경로**(재시도 -> 최종 실패 -> 화면 상태)는 검증된 적이 없었다.
    문서와 같은 규약을 그대로 타야 한다 — 중간 재시도는 화면을 건드리지 않고,
    마지막 실패만 FAILED로 보인다.
    """
    print("\n--- 12-B. 사진 수집 실패의 재시도/최종실패 (Sprint 145) ---")
    import storage.database as dbmod
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        qid = env.enqueue(court, case_no, item_no, "image")

        # 중간 재시도: 큐는 pending 으로 돌아오고 화면 상태는 아직 바뀌지 않는다.
        for attempt in range(1, dbmod.MAX_DOC_RETRY):
            dbmod.mark_queue_failed(qid, attempt - 1)
            c = env.conn()
            try:
                row = c.execute("SELECT status, retry_count FROM document_queue WHERE id=?",
                                (qid,)).fetchone()
            finally:
                c.close()
            check("재시도 %d회차: 큐는 pending" % attempt, row["status"], "pending")
            check("재시도 %d회차: retry_count 증가" % attempt, row["retry_count"], attempt)
            check_true("재시도 중에는 화면을 FAILED로 바꾸지 않는다",
                       env.status_of(1, "IMAGE") != "FAILED", env.status_of(1, "IMAGE"))

        # 마지막 실패: 큐 failed + 화면 FAILED
        dbmod.mark_queue_failed(qid, dbmod.MAX_DOC_RETRY - 1)
        c = env.conn()
        try:
            row = c.execute("SELECT status, retry_count FROM document_queue WHERE id=?",
                            (qid,)).fetchone()
        finally:
            c.close()
        check("재시도 소진 후 큐는 failed", row["status"], "failed")
        check("재시도 소진 후 화면은 FAILED", env.status_of(1, "IMAGE"), "FAILED")

        # 하루 지나면 되살아나 다시 시도할 수 있다(영구 사망이 아니다).
        c = env.conn()
        c.execute("UPDATE document_queue SET last_attempt_at="
                  "datetime(last_attempt_at,'-2 day') WHERE id=?", (qid,))
        c.commit(); c.close()
        dbmod.reset_stale_queue()
        c = env.conn()
        try:
            row = c.execute("SELECT status, retry_count FROM document_queue WHERE id=?",
                            (qid,)).fetchone()
        finally:
            c.close()
        check("하루 지난 failed는 되살아난다", row["status"], "pending")
        check("되살아나면 재시도 예산도 초기화된다", row["retry_count"], 0)
    finally:
        env.close()



def test_doc_raw_refuses_to_record_false_success():
    """저장했다고 **주장**하지만 실체가 없으면 doc_raw를 남기지 않는다 (Sprint 157).

    커버리지 실측에서 `_record_doc_raw()`의 방어 분기가 통째로 비어 있었다. 이 분기들이
    막는 것이 하필 이 저장소가 반복해 겪은 **"거짓 성공"** 이다 — 큐는 done이고 화면은
    수집완료인데 파일이 없거나 0바이트인 상태(BUGS #61 계열).

    `doc_raw`는 파일의 실체(크기·버전·쪽수)를 담는 표라, 여기에 행이 생기면 그 자체가
    "실물이 있다"는 주장이 된다. 그러므로 실물이 없을 때는 **행을 만들지 않는 쪽**이
    맞다 — 0으로 채운 행을 남기면 뒤따르는 어떤 검사도 그것을 실물로 오인한다.
    """
    print("\n--- 12-B. doc_raw가 거짓 성공을 기록하지 않는다 (Sprint 157) ---")
    from storage.database import mark_queue_done

    def doc_raw_rows(env, item_id=1):
        c = env.conn()
        try:
            return c.execute("SELECT * FROM doc_raw WHERE item_id=?", (item_id,)).fetchall()
        finally:
            c.close()

    # (a) 저장했다는 파일이 실제로 없다
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        qid = env.enqueue(court, case_no, item_no, "spec")
        ghost = os.path.join(env.docs, court, case_no, item_no, "spec.pdf")  # 만들지 않는다
        mark_queue_done(qid, court, case_no, item_no, "spec", "", "h", files_saved=[ghost])
        check("파일이 없으면 doc_raw 행을 만들지 않는다", len(doc_raw_rows(env)), 0)
        c = env.conn()
        try:
            st = c.execute("SELECT status FROM document_queue WHERE id=?", (qid,)).fetchone()
        finally:
            c.close()
        check("그래도 큐 종결은 진행된다(무한 재시도 방지)", st["status"], "done")
    finally:
        env.close()

    # (b) 0바이트 파일
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        qid = env.enqueue(court, case_no, item_no, "spec")
        d = os.path.join(env.docs, court, case_no, item_no)
        os.makedirs(d, exist_ok=True)
        empty = os.path.join(d, "spec.pdf")
        open(empty, "wb").close()
        mark_queue_done(qid, court, case_no, item_no, "spec", "", "h", files_saved=[empty])
        check("0바이트 파일은 doc_raw를 만들지 않는다", len(doc_raw_rows(env)), 0)
    finally:
        env.close()

    # (c) files_saved 자체가 비었다
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        qid = env.enqueue(court, case_no, item_no, "spec")
        mark_queue_done(qid, court, case_no, item_no, "spec", "", "h", files_saved=[])
        check("저장 목록이 비면 doc_raw 없음", len(doc_raw_rows(env)), 0)
    finally:
        env.close()

    # (d) 사진은 doc_raw가 아니라 auction_image가 담당한다
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        qid = env.enqueue(court, case_no, item_no, "image")
        d = os.path.join(env.docs, court, case_no, item_no, "images")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "01.jpg")
        with open(p, "wb") as f:
            f.write(make_jpeg(10, 10))
        mark_queue_done(qid, court, case_no, item_no, "image", "", "h", files_saved=[p])
        check("사진은 doc_raw에 들어가지 않는다(0~N장이라 1행 표에 못 담는다)",
              len(doc_raw_rows(env)), 0)
    finally:
        env.close()

    # (e) 대조군 — 실체가 있으면 반드시 기록한다(위 검사들이 '항상 0'이 아님을 보인다)
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        qid = env.enqueue(court, case_no, item_no, "spec")
        d = os.path.join(env.docs, court, case_no, item_no)
        os.makedirs(d, exist_ok=True)
        real = os.path.join(d, "spec.pdf")
        with open(real, "wb") as f:
            f.write(b"%PDF-1.4 " + b"x" * 500)
        mark_queue_done(qid, court, case_no, item_no, "spec", "", "h", files_saved=[real])
        rows = doc_raw_rows(env)
        check("대조군: 실물이 있으면 doc_raw 1행", len(rows), 1)
        if rows:
            check("기록된 크기가 실제 파일 크기와 같다",
                  rows[0]["file_size"], os.path.getsize(real))
    finally:
        env.close()


def test_worker_restart_does_not_redownload_images():
    """worker가 다시 돌아도 이미 받은 사진을 **다시 내려받지 않는다.**

    2026-08-17 Sprint 145 신설. §10이 "파일이 두 벌 쌓이지 않는가"를 봤다면, 여기서는
    **네트워크/디코드 작업 자체를 건너뛰는가**를 본다 — 파일의 mtime이 그대로여야 한다.
    사진은 물건당 5장 x 수십~수백 KB라, 재실행마다 다시 받으면 가동 창을 그대로 먹는다.
    """
    print("\n--- 12-C. worker 재실행 시 사진 재다운로드 없음 (Sprint 145) ---")
    from crawler.image_crawler import collect_images
    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        els = [img_el("전경도", 1, make_jpeg()), img_el("위치도", 2, make_gif())]

        d1 = FakeDriver(els)
        r1 = collect_images(d1, court, case_no, item_no)
        check("1차 수집 2장", r1["image_count"], 2)
        paths = [i["path"] for i in r1["images"]]
        before = {p: os.stat(p).st_mtime_ns for p in paths}

        # mtime 해상도 때문에 즉시 다시 쓰면 구분이 안 될 수 있으므로 과거로 밀어 둔다
        for p in paths:
            os.utime(p, (1_000_000, 1_000_000))
        before = {p: os.stat(p).st_mtime_ns for p in paths}

        d2 = FakeDriver(els)
        r2 = collect_images(d2, court, case_no, item_no)
        after = {p: os.stat(p).st_mtime_ns for p in paths}

        check("2차에도 2장을 보고한다", r2["image_count"], 2)
        check_true("파일을 다시 쓰지 않았다(mtime 불변)", before == after,
                   {p: (before[p], after[p]) for p in paths if before[p] != after[p]})
        check("파일 개수는 그대로", len(os.listdir(os.path.dirname(paths[0]))), 2)
    finally:
        env.close()


def test_relative_storage_path_rule():
    """DB에는 **프로젝트 루트 기준 상대경로**가 들어가야 한다.

    절대경로를 넣으면 배포 위치가 바뀌는 순간 전 행이 못 쓰게 된다 — 이 저장소가
    `.bat`/Task Scheduler에서 실제로 겪은 사고(존재하지 않는 절대경로 하드코딩)를
    DB로 옮기지 않기 위한 규칙이다.
    """
    print("\n--- 11-A. storage_path 상대경로 규칙 ---")
    from storage.database import to_relative_storage_path
    import api.v1.images as imgmod
    root = os.path.dirname(os.path.abspath(__file__))

    inside = os.path.join(root, "documents", "서울중앙지방법원", "2024타경1", "1", "spec.pdf")
    rel = to_relative_storage_path(inside)
    check("루트 안쪽 경로는 상대경로가 된다",
          rel, "documents/서울중앙지방법원/2024타경1/1/spec.pdf")
    check_true("구분자는 항상 '/'", "\\" not in rel, rel)
    # 되돌리면 원래 파일을 가리켜야 한다(서빙 계층과의 왕복이 이 규칙의 존재 이유다)
    check("서빙 계층이 되돌린 경로가 원본과 같다",
          os.path.normpath(imgmod.resolve_stored_path(rel)), os.path.normpath(inside))

    # 루트 밖은 추측해서 잘라내지 않는다(잘못 자르면 엉뚱한 파일을 가리킨다)
    outside = os.path.join(os.path.dirname(root), "elsewhere", "x.pdf")
    check("루트 밖 경로는 원본을 유지한다", to_relative_storage_path(outside), outside)


def test_save_auction_images_defenses():
    print("\n--- 11. auction_image 기록 방어선 ---")
    from storage.database import save_auction_images
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        d = os.path.join(env.docs, court, case_no, item_no, "images")
        os.makedirs(d)
        real = os.path.join(d, "01.jpg")
        with open(real, "wb") as f:
            f.write(make_jpeg())

        stat = save_auction_images(court, case_no, item_no, [
            {"seq": 1, "kind": "전경도", "path": real, "file_hash": "h1",
             "width": 525, "height": 700},
            # 디스크에 없는 것은 기록하지 않는다 (DB만 앞서가지 않게)
            {"seq": 2, "kind": "위치도", "path": os.path.join(d, "02.jpg"),
             "file_hash": "h2", "width": 1, "height": 1},
        ])
        check("저장 1건", stat["saved"], 1)
        check("없는 파일 1건 건너뜀", stat["skipped_missing"], 1)
        rows = env.images_of(1)
        check("DB에 1행", len(rows), 1)
        # storage_path는 **서빙 계층이 다시 파일로 풀 수 있어야** 한다는 것이 진짜 불변식이다.
        # (상대/절대 여부 자체는 `to_relative_storage_path()`의 단위 테스트가 따로 본다 —
        #  이 임시 환경은 프로젝트 루트 밖이라 설계대로 절대경로가 유지된다.)
        check_true("저장된 경로를 서빙 계층이 실제 파일로 되돌린다",
                   os.path.isfile(env.apiimg.resolve_stored_path(rows[0]["storage_path"])),
                   rows[0]["storage_path"])

        # 중복 자산 방어: 같은 seq를 다시 넣어도 행이 늘지 않는다
        save_auction_images(court, case_no, item_no,
                            [{"seq": 1, "kind": "전경도", "path": real, "file_hash": "h1b",
                              "width": 525, "height": 700}])
        rows = env.images_of(1)
        check("같은 순번은 덮어쓴다(행이 늘지 않는다)", len(rows), 1)
        check("덮어쓴 값이 반영된다", rows[0]["file_hash"], "h1b")

        # 법원이 사진을 줄이면 옛 행이 남으면 안 된다
        #
        # ★ 2026-08-18 Sprint 191 정정 — 이 블록은 예전에 `save_auction_images()`를
        #   **누적 빌더처럼** 쓰고 있었다({1,2} 저장 -> {1,3} 저장 -> 행이 1,2,3이 되기를
        #   기대). 그것이 통과하려면 "이번에 안 준 순번(2)의 행을 남긴다"가 참이어야 하는데,
        #   그건 이 함수가 막으려는 바로 그 상태다. 옛 구현이 `seq > max_seq`로만 지웠기 때문에
        #   우연히 통과하던 것이고, 검사가 **약한 semantics를 굳히고 있었다.**
        #   이제는 한 번의 호출이 곧 "지금 법원이 주는 전부"이므로 집합 차집합으로 정리한다.
        paths = {}
        for seq in (2, 3, 4):
            pth = os.path.join(d, "0%d.jpg" % seq)
            with open(pth, "wb") as f:
                f.write(make_jpeg())
            paths[seq] = pth

        def _img(seq, path):
            return {"seq": seq, "kind": "전경도", "path": path, "file_hash": "h",
                    "width": 1, "height": 1}

        save_auction_images(court, case_no, item_no,
                            [_img(1, real)] + [_img(s_, paths[s_]) for s_ in (2, 3, 4)])
        check("4장 기록(1,2,3,4)", [r["seq"] for r in env.images_of(1)], [1, 2, 3, 4])

        # ★ 가운데 순번이 빠지는 경우 — `seq > max_seq` 비교로는 절대 못 잡는다.
        #   법원이 1,2,4만 주면 3번 행은 살아남고, 그 행이 가리키는 파일은 이미 사라져 있다
        #   (= 화면은 있다는데 열면 404). 집합 차집합이라야 정리된다.
        stat_gap = save_auction_images(
            court, case_no, item_no,
            [_img(1, real), _img(2, paths[2]), _img(4, paths[4])])
        check("가운데가 빠지면 그 행만 정리된다(1,2,4)",
              [r["seq"] for r in env.images_of(1)], [1, 2, 4])
        check("정리된 행 수", stat_gap["removed_stale"], 1)

        save_auction_images(court, case_no, item_no, [_img(1, real)])
        check("사진이 줄면 옛 행이 정리된다", [r["seq"] for r in env.images_of(1)], [1])

        # 부분 수집이면 여전히 지우지 않는다(보호가 새 규칙에도 그대로 살아 있는가)
        save_auction_images(court, case_no, item_no,
                            [_img(1, real)] + [_img(s_, paths[s_]) for s_ in (2, 3, 4)])
        stat_part = save_auction_images(court, case_no, item_no, [_img(1, real)],
                                        complete=False)
        check("부분 수집은 집합이 줄어도 지우지 않는다", stat_part["removed_stale"], 0)
        check("사용자가 보던 4장이 그대로다",
              [r["seq"] for r in env.images_of(1)], [1, 2, 3, 4])
    finally:
        env.close()


def test_mark_queue_done_records_doc_raw():
    """★ Sprint 144가 고친 결함: 운영 경로가 doc_raw를 전혀 쓰지 않았다."""
    print("\n--- 12. mark_queue_done이 doc_raw를 남긴다 ---")
    from storage.database import mark_queue_done
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        qid = env.enqueue(court, case_no, item_no, "spec")

        d = os.path.join(env.docs, court, case_no, item_no)
        os.makedirs(d, exist_ok=True)
        spec = os.path.join(d, "spec.pdf")
        with open(spec, "wb") as f:
            f.write(b"%PDF-1.4 " + b"x" * 500)

        mark_queue_done(qid, court, case_no, item_no, "spec", "", "h1", files_saved=[spec])

        c = env.conn()
        try:
            rows = c.execute("SELECT * FROM doc_raw WHERE item_id=1").fetchall()
        finally:
            c.close()
        check("doc_raw 1행", len(rows), 1)
        check("doc_type은 대문자 표기", rows[0]["doc_type"], "SPEC")
        check("버전 1", rows[0]["doc_version"], 1)
        check("파일 크기 기록", rows[0]["file_size"], os.path.getsize(spec))
        check_true("해시 기록", bool(rows[0]["file_hash"]))
        check_true("기록한 경로를 서빙 계층이 파일로 되돌린다",
                   os.path.isfile(env.apiimg.resolve_stored_path(rows[0]["storage_path"])),
                   rows[0]["storage_path"])
        check("document_status도 READY", env.status_of(1, "SPEC"), "READY")

        # 두 번째 수집이면 버전이 올라간다 — 단, **내용이 실제로 바뀌어야** 한다
        # (Sprint 187 이후: 판정 근거는 이 함수에 넘어온 hash 인자가 아니라 저장된
        # 파일 자체의 sha256이다 — 아래에서 파일 내용을 실제로 바꾼다).
        # "내용이 같으면 버전이 그대로인가"는 별도 검사(12b)가 전담한다.
        # 큐 행은 새로 만들지 않는다 — 018 마이그레이션의 UNIQUE(법원,사건,물건,종류)
        # 때문에 애초에 만들 수 없고, 운영에서도 재수집은 `reset_stale_queue()`가
        # **같은 행**을 pending으로 되살리는 방식이다.
        with open(spec, "wb") as f:
            f.write(b"%PDF-1.4 " + b"z" * 900)
        mark_queue_done(qid, court, case_no, item_no, "spec", "h1", "h2", files_saved=[spec])
        c = env.conn()
        try:
            vs = [r["doc_version"] for r in
                  c.execute("SELECT doc_version FROM doc_raw WHERE item_id=1 ORDER BY doc_version")]
        finally:
            c.close()
        check("재수집 시 버전 증가", vs, [1, 2])
    finally:
        env.close()


def test_doc_raw_version_does_not_bump_on_unchanged_content():
    """★ Sprint 187이 고친 결함: 내용이 같아도 재수집마다 doc_raw 버전이 올랐다.

    `document_version_log`는 `previous_hash != new_hash`로 이미 변경 여부를 가리는데,
    같은 함수(`mark_queue_done`)가 여는 같은 트랜잭션에서 `doc_raw`는 그 판단 없이
    항상 새 행을 쌓았다 — `api/v1/item.py`가 그대로 응답에 싣는 `doc_version`이
    재수집을 켜는 순간 내용과 무관하게 매일 올라가게 된다(이미지 BUGS #113과 같은 계열).

    파일 내용을 실제로 바꾸지 않고 두 번째 `mark_queue_done()`을 부른다(재수집 시나리오 B) —
    버전이 그대로여야 한다. 이어서 내용을 실제로 바꿔 세 번째로 부른다(시나리오 C) —
    이번에는 버전이 올라야 한다. 반대 상황을 한 검사 안에서 구분하므로 공허할 수 없다.
    """
    print("\n--- 12b. 내용이 같으면 doc_raw 버전이 오르지 않는다 ---")
    from storage.database import mark_queue_done
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        qid = env.enqueue(court, case_no, item_no, "spec")

        d = os.path.join(env.docs, court, case_no, item_no)
        os.makedirs(d, exist_ok=True)
        spec = os.path.join(d, "spec.pdf")
        with open(spec, "wb") as f:
            f.write(b"%PDF-1.4 " + b"x" * 500)

        # 시나리오 A: 최초 수집.
        mark_queue_done(qid, court, case_no, item_no, "spec", "", "h1", files_saved=[spec])

        def versions():
            c = env.conn()
            try:
                return [r["doc_version"] for r in
                        c.execute("SELECT doc_version FROM doc_raw WHERE item_id=1 "
                                  "ORDER BY doc_version")]
            finally:
                c.close()

        check("최초 수집 - 버전 1", versions(), [1])

        # 시나리오 B: 재수집인데 파일 내용은 그대로다(같은 바이트를 다시 씀 - 법원
        # 원본이 안 바뀐 정상 재수집을 흉내낸다). previous_hash/new_hash는 doc_crawler가
        # 계산해 넘기는 값이라 실제 재수집에서도 둘 다 "h1"로 같을 것이다.
        with open(spec, "wb") as f:
            f.write(b"%PDF-1.4 " + b"x" * 500)
        mark_queue_done(qid, court, case_no, item_no, "spec", "h1", "h1", files_saved=[spec])
        check("내용 불변 재수집 - 버전 그대로", versions(), [1])

        # 시나리오 C: 이번에는 실제로 내용이 바뀐다 - 진짜 개정은 여전히 잡아야 한다.
        with open(spec, "wb") as f:
            f.write(b"%PDF-1.4 " + b"y" * 700)
        mark_queue_done(qid, court, case_no, item_no, "spec", "h1", "h2", files_saved=[spec])
        check("내용 변경 재수집 - 버전 증가", versions(), [1, 2])

        c = env.conn()
        try:
            latest = c.execute(
                "SELECT file_size, file_hash FROM doc_raw WHERE item_id=1 "
                "ORDER BY doc_version DESC LIMIT 1"
            ).fetchone()
        finally:
            c.close()
        check("최신 행이 실제 최신 파일 크기를 가리킨다", latest["file_size"], os.path.getsize(spec))
    finally:
        env.close()


def test_mark_queue_done_missing_file_is_not_recorded():
    print("\n--- 13. 저장했다는 파일이 없으면 doc_raw를 남기지 않는다 ---")
    from storage.database import mark_queue_done
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        qid = env.enqueue(court, case_no, item_no, "spec")
        ghost = os.path.join(env.docs, court, case_no, item_no, "spec.pdf")
        mark_queue_done(qid, court, case_no, item_no, "spec", "", "h", files_saved=[ghost])
        c = env.conn()
        try:
            n = c.execute("SELECT COUNT(*) n FROM doc_raw").fetchone()["n"]
        finally:
            c.close()
        check("doc_raw 0행", n, 0)
    finally:
        env.close()


def test_image_queue_type_does_not_crash_legacy_update():
    """'image'는 레거시 auction 테이블에 대응 컬럼이 없다 — 예전 코드라면 KeyError."""
    print("\n--- 14. image 종류가 레거시 플래그 갱신을 깨지 않는다 ---")
    from storage.database import mark_queue_done, QUEUE_TO_DOC_STATUS_TYPE
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        qid = env.enqueue(court, case_no, item_no, "image")
        check_true("큐 타입 매핑에 image가 있다", QUEUE_TO_DOC_STATUS_TYPE.get("image") == "IMAGE",
                   QUEUE_TO_DOC_STATUS_TYPE)
        mark_queue_done(qid, court, case_no, item_no, "image", "", "h",
                        status="NO_IMAGE", files_saved=[])
        check("document_status는 NO_IMAGE", env.status_of(1, "IMAGE"), "NO_IMAGE")
        c = env.conn()
        try:
            check("큐는 done", c.execute("SELECT status FROM document_queue WHERE id=?",
                                        (qid,)).fetchone()["status"], "done")
            check("doc_raw에는 사진을 넣지 않는다",
                  c.execute("SELECT COUNT(*) n FROM doc_raw").fetchone()["n"], 0)
        finally:
            c.close()
    finally:
        env.close()


def test_enqueue_includes_image():
    print("\n--- 15. enqueue가 image까지 적재한다 ---")
    from storage.database import enqueue_documents
    env = Env()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            enqueue_documents([{"court_code": "서울중앙지방법원", "case_no": "2024타경1",
                                "item_no": "1", "auction_date": "2099-01-01"}])
        c = env.conn()
        try:
            types = sorted(r["doc_type"] for r in
                           c.execute("SELECT doc_type FROM document_queue"))
        finally:
            c.close()
        check("4종류가 적재된다", types, ["appraisal", "image", "spec", "status"])
    finally:
        env.close()


# ===========================================================================
# 15-B. 큐의 매각기일이 실제와 어긋났을 때 (Sprint 145)
# ===========================================================================

def test_reconcile_queue_auction_date():
    """진행 중 물건이 큐의 옛 날짜 때문에 종결되지 않아야 한다.

    실측 재현(2026-08-17): item 1533 = 2024타경122092-1은 실제 기일이 2026-08-19인
    **검색에 노출되는 진행 중 물건**인데, 큐가 2026-07-15을 들고 있어 worker의 2차
    방어선이 SKIPPED_EXPIRED로 종결시킨다 -> 문서가 영원히 수집되지 않는다.
    """
    print("\n--- 15-B. 큐 매각기일 정정 (Sprint 145) ---")
    from storage.database import reconcile_queue_auction_date
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)

        # 실제 기일을 미래로 둔다(진행 중 물건).
        c = env.conn()
        try:
            c.execute("UPDATE auction_item SET auction_date='2099-01-01' WHERE id=1")
            c.commit()
        finally:
            c.close()

        qid = env.enqueue(court, case_no, item_no, "spec")
        # 큐만 과거 날짜로 되돌린다(06:00 이후 기일이 재지정된 상황).
        c = env.conn()
        try:
            c.execute("UPDATE document_queue SET auction_date='2020-01-01' WHERE id=?", (qid,))
            c.commit()
        finally:
            c.close()

        with contextlib.redirect_stdout(io.StringIO()):
            resolved = reconcile_queue_auction_date(qid, case_no, item_no, "2020-01-01", court)

        check("권위 있는 값을 돌려준다", resolved, "2099-01-01")

        c = env.conn()
        try:
            row = c.execute("SELECT auction_date, status FROM document_queue WHERE id=?",
                            (qid,)).fetchone()
        finally:
            c.close()
        check("큐 행도 정정된다", row["auction_date"], "2099-01-01")
        # status는 재수집 정책이라 건드리지 않는다(mark_queue_* 계열의 규약과 동일).
        check("status는 건드리지 않는다", row["status"], "pending")

        # 진짜로 지난 기일은 그대로 지나가야 한다(과잉 구제 방지).
        c = env.conn()
        try:
            c.execute("UPDATE auction_item SET auction_date='2020-01-01' WHERE id=1")
            c.commit()
        finally:
            c.close()
        qid2 = env.enqueue(court, case_no, item_no, "appraisal")
        c = env.conn()
        try:
            c.execute("UPDATE document_queue SET auction_date='2020-01-01' WHERE id=?", (qid2,))
            c.commit()
        finally:
            c.close()
        with contextlib.redirect_stdout(io.StringIO()):
            still_past = reconcile_queue_auction_date(qid2, case_no, item_no, "2020-01-01", court)
        check("실제로 지난 기일은 그대로 과거", still_past, "2020-01-01")

        # 매칭되는 물건이 없으면 판단을 바꾸지 않는다.
        with contextlib.redirect_stdout(io.StringIO()):
            unknown = reconcile_queue_auction_date(qid2, "없는사건", "9", "2020-01-01", court)
        check("물건이 없으면 큐 값 유지", unknown, "2020-01-01")
    finally:
        env.close()


def test_worker_consults_authoritative_date_before_expiring():
    """doc_worker가 종결 전에 reconcile을 호출하는지 소스로 고정한다.

    함수만 있고 배선되지 않으면 결함이 그대로 남으므로 호출 지점을 검사한다
    (이 파일의 다른 계약 검사들과 같은 방식).
    """
    print("\n--- 15-C. worker 배선 (Sprint 145) ---")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "doc_worker.py"), encoding="utf-8-sig").read()
    check_true("reconcile_queue_auction_date를 import한다",
               "reconcile_queue_auction_date" in src.split("def main")[0])
    # 종결 호출보다 먼저 나와야 한다.
    i_rec = src.find("reconcile_queue_auction_date(", src.find("def main"))
    i_skip = src.find("mark_queue_skipped_expired(", src.find("def main"))
    check_true("종결(mark_queue_skipped_expired)보다 먼저 호출된다",
               0 < i_rec < i_skip, "rec=%s skip=%s" % (i_rec, i_skip))


# ===========================================================================
# 16. API 계약
# ===========================================================================


def test_partial_collection_does_not_delete_old_photos():
    """부분 수집이 **사용자가 보던 사진을 지우지 않는가** (2026-08-17 Sprint 186).

    `save_auction_images()` 는 이번에 저장된 최대 순번보다 큰 옛 행을 지운다. 그 의도는
    옳다 — 법원이 사진을 5장에서 3장으로 줄이면 옛 4,5번 행이 **없는 사진**을 가리킨다.

    문제는 이 함수만 보면 두 상황이 똑같아 보인다는 것이다. 둘 다 순번 3까지만 들어온다.

        법원이 줄였다    -> 옛 4,5번을 지우는 것이 맞다
        일부만 받아졌다  -> 지우면 사용자가 보던 사진 2장이 사라지고,
                            그 파일들은 디스크에 고아로 남는다

    구별할 수 있는 것은 호출부다(`collect_images` 의 `partial`). 그래서 `complete`
    플래그를 받아 **판단할 수 없을 때는 남기는 쪽**을 택한다 — 남은 행은 여전히 실제
    파일을 가리키고 다음 정상 수집이 정리하지만, 지운 행은 되돌릴 수 없다.

    ★ 지금까지 부분 수집은 실제로 일어난 적이 없다(2026-08-17 실측: 경고 0건, 9물건
      전부 5장, seq 결번 0). 그러나 재수집을 켜는 순간 도달 가능해지는 경로다.
    """
    print("\n--- 7-B. 부분 수집이 옛 사진을 지우지 않는다 (Sprint 186) ---")
    from storage.database import save_auction_images

    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        d = os.path.join(env.docs, court, case_no, item_no, "images")
        os.makedirs(d, exist_ok=True)

        def _mk(seq):
            p = os.path.join(d, "%02d.jpg" % seq)
            with open(p, "wb") as f:
                f.write(make_jpeg(100 + seq, 200))
            return {"seq": seq, "kind": "전경도", "path": p,
                    "file_hash": "h%d" % seq, "width": 100 + seq, "height": 200}

        def _rows():
            c = env.conn()
            try:
                return [r["seq"] for r in c.execute(
                    "SELECT seq FROM auction_image WHERE item_id=1 ORDER BY seq")]
            finally:
                c.close()

        # (1) 정상 수집 5장
        five = [_mk(i) for i in range(1, 6)]
        st = save_auction_images(court, case_no, item_no, five)
        check("1차 저장 5장", st["saved"], 5)
        check("행도 5개", _rows(), [1, 2, 3, 4, 5])

        # (2) 부분 수집 — 3장만 받아졌다. 옛 4,5번을 **지우면 안 된다**.
        st2 = save_auction_images(court, case_no, item_no, five[:3], complete=False)
        check("부분 수집 저장 3장", st2["saved"], 3)
        check("부분 수집은 옛 행을 지우지 않는다", st2["removed_stale"], 0)
        check("사용자가 보던 5장이 그대로다", _rows(), [1, 2, 3, 4, 5])

        # (3) 법원이 실제로 3장으로 줄였다 — 이때는 지우는 것이 맞다.
        st3 = save_auction_images(court, case_no, item_no, five[:3], complete=True)
        check("완전 수집 저장 3장", st3["saved"], 3)
        check("옛 4,5번을 지운다", st3["removed_stale"], 2)
        check("행이 3개로 줄었다", _rows(), [1, 2, 3])

        # (4) 전체 실패(저장 0장)는 어느 쪽이든 지우지 않는다.
        st4 = save_auction_images(court, case_no, item_no, [], complete=True)
        check("저장 0장이면 삭제도 0", st4["removed_stale"], 0)
        check("전체 실패에도 기존 사진 보존", _rows(), [1, 2, 3])

        # (5) 법원이 사진을 **추가**했다 — 2026-08-18 Sprint 189에 명시적으로 추가한 경우다.
        #     (2)(3)(4)가 "줄었다/일부만 받았다/전부 실패했다"를 각각 고정하는데, 정작
        #     가장 흔한 변경인 **늘어남**은 어느 검사도 이름을 붙여 두지 않았다.
        #     늘어날 때는 지울 것이 없어야 하고(옛 행은 전부 살아 있는 사진이다),
        #     새 순번이 그대로 붙어야 한다.
        seven = five[:3] + [_mk(6), _mk(7)]
        st5 = save_auction_images(court, case_no, item_no, seven, complete=True)
        check("추가 수집 저장 5장", st5["saved"], 5)
        check("추가일 때는 지울 것이 없다", st5["removed_stale"], 0)
        check("새 순번이 그대로 붙는다", _rows(), [1, 2, 3, 6, 7])
    finally:
        env.close()


def test_api_contract():
    print("\n--- 16. API 응답 계약 ---")
    from fastapi.testclient import TestClient
    from storage.database import save_auction_images
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        d = os.path.join(env.docs, court, case_no, item_no, "images")
        os.makedirs(d)
        paths = []
        for seq, mk in ((1, make_jpeg(525, 700)), (2, make_gif(676, 700))):
            p = os.path.join(d, "%02d.%s" % (seq, "jpg" if seq == 1 else "gif"))
            with open(p, "wb") as f:
                f.write(mk)
            paths.append(p)
        save_auction_images(court, case_no, item_no, [
            {"seq": 1, "kind": "전경도", "path": paths[0], "file_hash": "a",
             "width": 525, "height": 700},
            {"seq": 2, "kind": "위치도", "path": paths[1], "file_hash": "b",
             "width": 676, "height": 700},
        ])
        c = env.conn()
        c.execute("INSERT INTO document_status (item_id,doc_type,status) VALUES (1,'SPEC','READY')")
        c.execute("INSERT INTO document_status (item_id,doc_type,status)"
                  " VALUES (1,'APPRAISAL','COLLECTING')")
        c.execute("INSERT INTO doc_raw (item_id,doc_type,storage_path,file_size,doc_version,page_count)"
                  " VALUES (1,'SPEC','documents/x/spec.pdf',1234,1,7)")
        c.commit()
        c.close()

        # ★ 서빙 파일을 실제로 만든다 (2026-08-25, BUGS #198).
        #   예전에는 `document_status=READY` 행만 넣고 파일은 만들지 않은 채
        #   "열람 가능 표시 = True" 를 기대했다. 그런데 그 상태는 **운영에서
        #   일어나면 안 되는 상태**다 - 광고한 `viewer_url` 이 404 가 난다.
        #   API 가 이제 그 자기모순을 COLLECTING 으로 낮추므로(사진의 §17 과 같은
        #   2차 방어선), 픽스처도 **운영과 같은 상태**를 만든다.
        #   실물 200물건 비교에서 응답이 달라진 물건은 0건이었다 - 이 픽스처만
        #   파일 없이 READY 였다.
        import crawler.doc_paths as _dp
        _spec_dir = _dp.get_doc_dir(court, case_no, item_no)
        os.makedirs(_spec_dir, exist_ok=True)
        with open(os.path.join(_spec_dir, "spec.pdf"), "wb") as _f:
            _f.write(b"%PDF-1.4 fixture" + b"x" * 40)

        from api_server import app
        client = TestClient(app)
        r = client.get("/api/v1/item/1")
        check("200", r.status_code, 200)
        body = r.json()

        # --- 기존 계약이 그대로인가 (Breaking Change 금지) ---
        for key in ("id", "case_no", "item_no", "court_name", "documents", "tenants",
                    "rights_summary", "is_favorited", "case"):
            check_true("기존 키 유지: %s" % key, key in body, sorted(body))
        spec = next(d for d in body["documents"] if d["doc_type"] == "SPEC")
        check_true("documents 항목에 doc_type/status가 그대로 있다",
                   "doc_type" in spec and "status" in spec, spec)

        # --- 새 계약 ---
        check("image_count", body["image_count"], 2)
        check("images_status", body["images_status"], "READY")
        check("대표 이미지 순번", body["representative_image"]["seq"], 1)
        check("이미지 URL", body["images"][0]["url"], "/api/v1/item/1/images/1")
        check("썸네일 URL 필드 존재", body["images"][0]["thumbnail_url"],
              "/api/v1/item/1/images/1")
        check("이미지 순서", [i["seq"] for i in body["images"]], [1, 2])
        check("이미지 종류", [i["kind"] for i in body["images"]], ["전경도", "위치도"])
        check("쪽수 노출", spec["page_count"], 7)
        check("열람 가능 표시", spec["available"], True)
        check("뷰어 URL", spec["viewer_url"], "/api/v1/item/1/documents/SPEC")
        appr = next(d for d in body["documents"] if d["doc_type"] == "APPRAISAL")
        check("수집중 문서는 available=False", appr["available"], False)
        check("수집중 문서에는 URL을 주지 않는다", appr["viewer_url"], None)
        check("메타 없는 문서의 쪽수는 None(0으로 뭉개지 않는다)", appr["page_count"], None)

        # --- 사진 서빙 ---
        r = client.get("/api/v1/item/1/images/1")
        check("사진 200", r.status_code, 200)
        check("jpeg content-type", r.headers["content-type"], "image/jpeg")
        r = client.get("/api/v1/item/1/images/2")
        check("gif content-type", r.headers["content-type"], "image/gif")
        check("없는 순번은 404", client.get("/api/v1/item/1/images/99").status_code, 404)
        check("없는 물건은 404", client.get("/api/v1/item/999/images/1").status_code, 404)
        check("HEAD도 동작", client.head("/api/v1/item/1/images/1").status_code, 200)

        # --- 파일이 사라지면 200을 주면 안 된다 (이 저장소의 단골 결함) ---
        os.remove(paths[0])
        check("DB에는 있지만 파일이 없으면 404",
              client.get("/api/v1/item/1/images/1").status_code, 404)
    finally:
        env.close()


def test_search_thumbnail_contract():
    """검색 결과가 대표 사진 URL을 주는가, 그리고 **N+1이 아닌가** (2026-08-17 Sprint 145).

    사용자 흐름의 첫 칸이다: 검색 -> 상세 -> 사진. 예전에는 검색 응답에 사진 정보가
    아예 없어서(`SELECT *` + ResultList에 img 0개) 목록이 전부 텍스트였다.

    ★ N+1이 특히 중요하다 — 물건마다 따로 물으면 페이지 크기(최대 100)에 비례해
      쿼리가 늘어난다. 바로 옆 favorites 배치 조회와 같은 패턴이어야 한다.
    """
    print("\n--- 16-B. 검색 결과 대표 사진 계약 (Sprint 145) ---")
    from fastapi.testclient import TestClient
    from storage.database import save_auction_images
    import api.v1.search as searchmod
    env = Env()
    try:
        # 사진이 있는 물건 1개, 없는 물건 1개
        court, case_no, item_no = env.seed_item(item_id=1, case_no="2024타경1", item_no="1")
        env.seed_item(item_id=2, case_no="2024타경2", item_no="1")
        c = env.conn()
        for iid in (1, 2):
            c.execute("UPDATE auction_item SET auction_date='2099-01-01', sido='서울',"
                      " minimum_bid_price=1, appraisal_price=1, bid_rate=1, fail_count=0"
                      " WHERE id=?", (iid,))
        c.commit(); c.close()

        d = os.path.join(env.docs, court, case_no, item_no, "images")
        os.makedirs(d)
        paths = []
        for seq in (2, 3):        # 일부러 1번이 없는 상태 — 대표는 MIN(seq)여야 한다
            p = os.path.join(d, "%02d.jpg" % seq)
            with open(p, "wb") as f:
                f.write(make_jpeg())
            paths.append((seq, p))
        save_auction_images(court, case_no, item_no, [
            {"seq": s, "kind": "전경도", "path": p, "file_hash": "h%d" % s,
             "width": 525, "height": 700} for s, p in paths])

        from api_server import app
        client = TestClient(app)
        r = client.get("/api/v1/search?include_closed=true&size=50")
        check("검색 200", r.status_code, 200)
        items = {i["id"]: i for i in r.json()["items"]}

        check_true("사진 있는 물건에 thumbnail_url", bool(items[1]["thumbnail_url"]),
                   items[1].get("thumbnail_url"))
        check("대표는 가장 앞선 순번(MIN(seq)=2)", items[1]["thumbnail_url"],
              "/api/v1/item/1/images/2")
        check("사진 없는 물건은 null", items[2]["thumbnail_url"], None)
        check_true("키 자체는 항상 존재한다(프런트 분기 단순화)",
                   all("thumbnail_url" in i for i in items.values()))

        # 기존 계약이 그대로인가 (Breaking Change 금지)
        for key in ("id", "case_no", "item_no", "court_name", "property_type", "sido",
                    "sigungu", "dong", "full_address", "appraisal_price",
                    "minimum_bid_price", "bid_rate", "auction_date", "status",
                    "fail_count", "validation_status", "crawl_date", "is_favorited"):
            check_true("검색 기존 키 유지: %s" % key, key in items[1], sorted(items[1]))

        # 그 URL이 실제로 열리는가
        check("대표 사진이 실제로 서빙된다",
              client.get(items[1]["thumbnail_url"]).status_code, 200)

        # ★ N+1 검사 — 페이지 크기를 키워도 쿼리 수가 늘면 안 된다
        orig = searchmod.get_connection
        counter = {"n": 0}

        class Counting:
            def __init__(self, inner):
                self._i = inner

            def execute(self, q, *a, **k):
                counter["n"] += 1
                return self._i.execute(q, *a, **k)

            def __getattr__(self, n):
                return getattr(self._i, n)

        searchmod.get_connection = lambda: Counting(orig())
        try:
            counts = []
            for size in (1, 20, 100):
                counter["n"] = 0
                client.get("/api/v1/search?include_closed=true&size=%d" % size)
                counts.append(counter["n"])
        finally:
            searchmod.get_connection = orig
        check_true("페이지 크기가 늘어도 쿼리 수가 같다(N+1 아님)",
                   len(set(counts)) == 1, dict(zip((1, 20, 100), counts)))
    finally:
        env.close()



def test_favorites_and_recent_thumbnail_contract():
    """관심물건·최근 본 물건도 대표 사진을 주는가 (2026-08-20 Sprint 224).

    ## 왜 이 검사인가

    사용자는 검색목록에서 **사진을 보고** 물건을 담는다. 그런데 관심물건 화면을 열면
    사진이 사라져 있었다 — `thumbnail_url` 을 주는 API 가 `search.py` 하나뿐이었다.
    같은 물건이 화면마다 달라 보이면 어느 것이 어느 것인지 알아보기 어렵다.

    ## 무엇을 고정하는가

        1. 두 API 모두 `thumbnail_url` 키를 **항상** 준다(사진이 없으면 null).
        2. 대표는 `MIN(seq)` — 일부러 1번을 비우고 2,3번만 넣어 확인한다.
        3. 그 URL 이 **실제로 200 으로 열린다**(저장 성공 != 서빙 성공).
        4. 네 화면(검색목록/관심물건/최근 본 물건/상세)이 **글자 그대로 같은 URL** 을 준다.
        5. 기존 키가 하나도 사라지지 않았다(Breaking Change 금지).
        6. 건수가 늘어도 쿼리 수가 늘지 않는다(N+1 아님).

    6번이 특히 중요하다 — N+1 이 되어도 **화면은 똑같이 잘 보인다. 느려질 뿐이다.**
    결과 기반 검사로는 절대 잡히지 않으므로 쿼리 수를 직접 센다.
    """
    print("\n--- 16-B2. 관심물건/최근 본 물건 대표 사진 계약 (Sprint 224) ---")
    from fastapi.testclient import TestClient
    from jose import jwt
    from storage.database import save_auction_images
    import api.v1.favorites as favmod
    import api.v1.recent_items as recmod

    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1, case_no="2024타경1", item_no="1")
        env.seed_item(item_id=2, case_no="2024타경2", item_no="1")

        # 사진은 물건 1번에만, 그리고 **1번 순번을 비운 채** 2·3번만 넣는다.
        d = os.path.join(env.docs, court, case_no, item_no, "images")
        os.makedirs(d)
        payload = []
        for seq in (2, 3):
            fp = os.path.join(d, "%02d.jpg" % seq)
            with open(fp, "wb") as f:
                f.write(make_jpeg())
            payload.append({"seq": seq, "kind": "전경도", "path": fp,
                            "file_hash": "h%d" % seq, "width": 525, "height": 700})
        save_auction_images(court, case_no, item_no, payload)

        USER = "qa-thumb-user"
        c = env.conn()
        try:
            for iid in (1, 2):
                c.execute("INSERT INTO favorites (user_id,item_id,created_at) VALUES (?,?,?)",
                          (USER, iid, "2026-08-%02dT00:00:00" % (10 + iid)))
                c.execute("INSERT INTO recent_items (user_id,item_id,viewed_at) VALUES (?,?,?)",
                          (USER, iid, "2026-08-%02dT00:00:00" % (10 + iid)))
            c.commit()
        finally:
            c.close()

        from api.auth import SUPABASE_JWT_SECRET
        from api_server import app
        client = TestClient(app)
        headers = {"Authorization": "Bearer " + jwt.encode(
            {"sub": USER}, SUPABASE_JWT_SECRET, algorithm="HS256")}

        seen = {}
        for label, path in (("관심물건", "/api/v1/favorites"),
                            ("최근 본 물건", "/api/v1/recent-items")):
            r = client.get(path, headers=headers)
            check("%s 200" % label, r.status_code, 200)
            rows = {i["id"]: i for i in (r.json().get("data") or [])}
            check_true("%s: 두 물건이 다 돌아왔다(검사가 공허하지 않다)" % label,
                       set(rows) == {1, 2}, sorted(rows))
            check_true("%s: 키 자체는 항상 존재한다" % label,
                       all("thumbnail_url" in i for i in rows.values()),
                       sorted(rows.get(1, {})))
            check("%s: 대표는 가장 앞선 순번(MIN(seq)=2)" % label,
                  rows[1]["thumbnail_url"], "/api/v1/item/1/images/2")
            check("%s: 사진 없는 물건은 null" % label, rows[2]["thumbnail_url"], None)
            # 저장 성공과 서빙 성공은 다른 사실이다 — 실제로 열어 본다.
            check("%s: 그 URL 이 실제로 열린다" % label,
                  client.get(rows[1]["thumbnail_url"]).status_code, 200)
            seen[label] = rows[1]["thumbnail_url"]

            extra = "favorited_at" if label == "관심물건" else "viewed_at"
            for key in ("id", "case_no", "item_no", "court_name", "property_type", "sido",
                        "sigungu", "full_address", "appraisal_price", "minimum_bid_price",
                        "bid_rate", "auction_date", "status", "fail_count", extra):
                check_true("%s 기존 키 유지: %s" % (label, key), key in rows[1], sorted(rows[1]))

        # 검색목록·상세와 **글자 그대로** 같은가 — 갈라지면 "목록엔 뜨는데 열면 404" 다.
        c = env.conn()
        try:
            c.execute("UPDATE auction_item SET auction_date='2099-01-01', sido='서울',"
                      " minimum_bid_price=1, appraisal_price=1, bid_rate=1, fail_count=0")
            c.commit()
        finally:
            c.close()
        search_items = client.get("/api/v1/search?include_closed=true&size=50").json()["items"]
        search_url = {i["id"]: i["thumbnail_url"] for i in search_items}[1]
        # 상세는 envelope 없이 본문을 그대로 준다(이 파일의 16-A 도 같은 방식으로 읽는다).
        detail_url = client.get("/api/v1/item/1", headers=headers).json()["images"][0]["url"]
        urls = {"검색목록": search_url, "상세": detail_url}
        urls.update(seen)
        check_true("네 화면이 같은 URL 을 준다", len(set(urls.values())) == 1, urls)

        # ★ N+1 — 건수를 늘려도 쿼리 수가 같아야 한다.
        counter = {"n": 0}

        class Counting:
            def __init__(self, inner):
                self._i = inner

            def execute(self, q, *a, **k):
                counter["n"] += 1
                return self._i.execute(q, *a, **k)

            def __getattr__(self, n):
                return getattr(self._i, n)

        def measure(mod, path):
            orig = mod.get_connection
            mod.get_connection = lambda _o=orig: Counting(_o())
            try:
                counter["n"] = 0
                n_rows = len(client.get(path, headers=headers).json()["data"])
                return n_rows, counter["n"]
            finally:
                mod.get_connection = orig

        before = {"관심물건": measure(favmod, "/api/v1/favorites"),
                  "최근 본 물건": measure(recmod, "/api/v1/recent-items")}
        # seed_item() 은 자기 커넥션을 따로 열고 커밋한다 — 바깥에서 쓰기 트랜잭션을
        # 붙들고 있으면 "database is locked" 가 난다. 그래서 **먼저 다 심고** 그 다음에
        # 관심물건/최근 본 물건 행을 한 커넥션으로 넣는다.
        extra_ids = [100 + n for n in range(8)]
        for iid in extra_ids:
            env.seed_item(item_id=iid, case_no="2024타경%d" % iid, item_no="1")
        c = env.conn()
        try:
            for iid in extra_ids:
                c.execute("INSERT INTO favorites (user_id,item_id,created_at) VALUES (?,?,?)",
                          (USER, iid, "2026-08-20T00:00:00"))
                c.execute("INSERT INTO recent_items (user_id,item_id,viewed_at) VALUES (?,?,?)",
                          (USER, iid, "2026-08-20T00:00:00"))
            c.commit()
        finally:
            c.close()
        after = {"관심물건": measure(favmod, "/api/v1/favorites"),
                 "최근 본 물건": measure(recmod, "/api/v1/recent-items")}

        for label in ("관심물건", "최근 본 물건"):
            check_true("%s: 건수가 실제로 늘었다(검사가 공허하지 않다)" % label,
                       after[label][0] > before[label][0], (before[label], after[label]))
            check_true("%s: 건수가 늘어도 쿼리 수가 같다(N+1 아님)" % label,
                       before[label][1] == after[label][1], (before[label], after[label]))
        print("    (건수, 쿼리수)  전 %s / 후 %s" % (before, after))
    finally:
        env.close()


def test_item_detail_is_not_n_plus_one():
    """상세 응답의 쿼리 수가 **사진 개수에 비례해 늘지 않는가** (2026-08-17 Sprint 154).

    검색 쪽에는 이미 쿼리 수를 세는 가드가 있는데(16-B) 상세에는 없었다. 상세는 한 물건에
    사진 N장 + 문서 3종을 실어 주므로, 사진마다 또는 문서마다 따로 물으면 조용히 N+1이 된다.

    ★ 결과 기반 검사로는 절대 잡히지 않는다 — 응답 본문은 완전히 같고 쿼리 수만 늘어난다.
      이 저장소는 같은 함정을 BUGS #104에서 이미 겪었다(재사용 최적화가 비싼 단계 뒤에
      있어 결과는 같고 성능만 26배 나빴다). 그래서 **구조를 직접 고정**한다.
    """
    print("\n--- 16-C. 상세 응답이 N+1이 아니다 (Sprint 154) ---")
    from fastapi.testclient import TestClient
    from storage.database import save_auction_images
    import api.v1.item as itemmod

    def measure(photo_count):
        env = Env()
        try:
            court, case_no, item_no = env.seed_item(item_id=1)
            d = os.path.join(env.docs, court, case_no, item_no, "images")
            os.makedirs(d)
            rows = []
            for seq in range(1, photo_count + 1):
                p = os.path.join(d, "%02d.jpg" % seq)
                with open(p, "wb") as f:
                    f.write(make_jpeg(525, 700))
                rows.append({"seq": seq, "kind": "전경도", "path": p,
                             "file_hash": "h%d" % seq, "width": 525, "height": 700})
            save_auction_images(court, case_no, item_no, rows)

            c = env.conn()
            for dt in ("SPEC", "STATUS", "APPRAISAL"):
                c.execute("INSERT INTO document_status (item_id,doc_type,status)"
                          " VALUES (1,?,'READY')", (dt,))
                c.execute("INSERT INTO doc_raw (item_id,doc_type,storage_path,file_size,"
                          "doc_version,page_count) VALUES (1,?,'documents/x/f',1,1,3)", (dt,))
            c.commit()
            c.close()

            from api_server import app
            client = TestClient(app)

            counter = {"n": 0}
            orig = itemmod.get_connection

            class Counting:
                def __init__(self, inner):
                    self._i = inner

                def execute(self, q, *a, **k):
                    counter["n"] += 1
                    return self._i.execute(q, *a, **k)

                def __getattr__(self, n):
                    return getattr(self._i, n)

            itemmod.get_connection = lambda: Counting(orig())
            try:
                r = client.get("/api/v1/item/1")
                body = r.json()
                return r.status_code, counter["n"], body.get("image_count")
            finally:
                itemmod.get_connection = orig
        finally:
            env.close()

    code_a, q_a, n_a = measure(1)
    code_b, q_b, n_b = measure(8)

    check("사진 1장 상세 200", code_a, 200)
    check("사진 8장 상세 200", code_b, 200)
    check("사진 수는 실제로 다르다(검사가 무의미해지지 않도록)", (n_a, n_b), (1, 8))
    check_true("사진이 8배로 늘어도 쿼리 수가 같다(N+1 아님)",
               q_a == q_b, {"사진1장": q_a, "사진8장": q_b})
    print("   쿼리 수: 사진 1장 %d회 / 사진 8장 %d회" % (q_a, q_b))


def test_api_images_status_variants():
    print("\n--- 17. images_status 분기 ---")
    from fastapi.testclient import TestClient
    env = Env()
    try:
        env.seed_item(item_id=1)
        from api_server import app
        client = TestClient(app)

        # 행이 아예 없으면 아직 수집 전이다 — "사진 없음"으로 단정하지 않는다
        check("IMAGE 행 없음 -> COLLECTING",
              client.get("/api/v1/item/1").json()["images_status"], "COLLECTING")

        c = env.conn()
        c.execute("INSERT INTO document_status (item_id,doc_type,status) VALUES (1,'IMAGE','NO_IMAGE')")
        c.commit()
        c.close()
        body = client.get("/api/v1/item/1").json()
        check("NO_IMAGE 그대로 전달", body["images_status"], "NO_IMAGE")
        check("사진 0장", body["image_count"], 0)
        check("대표 이미지 없음", body["representative_image"], None)

        # ★ READY 인데 볼 사진이 0장인 자기모순은 그대로 전달하지 않는다 (Sprint 208).
        #
        #   같은 스프린트에서 이 상태를 실제로 만들어 냈다 — `doc_worker` 가 성공을 먼저
        #   기록하고 사진 기록에서 실패하면 `document_status`=READY, `auction_image`=0행이
        #   된다. 그 순서는 바로잡았지만 여기는 **두 번째 방어선**이다.
        #   그대로 내보내면 화면이 "사진 있음"이라 말하고 목록은 빈 상태가 된다.
        c = env.conn()
        c.execute("UPDATE document_status SET status='READY' WHERE doc_type='IMAGE'")
        c.commit()
        c.close()
        body = client.get("/api/v1/item/1").json()
        check("★ READY 기록 + 사진 0장 -> READY라고 답하지 않는다",
              body["images_status"], "COLLECTING")
        check("그때도 사진은 0장 그대로", body["image_count"], 0)

        # 대조군 - FAILED 는 낮추지 않는다("볼 사진 없음"과 모순되지 않는다)
        c = env.conn()
        c.execute("UPDATE document_status SET status='FAILED' WHERE doc_type='IMAGE'")
        c.commit()
        c.close()
        check("대조군: FAILED는 그대로 전달",
              client.get("/api/v1/item/1").json()["images_status"], "FAILED")

        # 대조군 - 사진이 실제로 있으면 READY 가 맞다
        c = env.conn()
        c.execute("UPDATE document_status SET status='READY' WHERE doc_type='IMAGE'")
        c.execute("INSERT INTO auction_image (item_id,seq,kind,storage_path,file_hash,"
                  "file_size,width,height,crawl_date) "
                  "VALUES (1,1,'전경도','documents/x/1.jpg','h',100,10,10,'2026-08-18')")
        c.commit()
        c.close()
        body = client.get("/api/v1/item/1").json()
        check("대조군: 사진이 있으면 READY", body["images_status"], "READY")
        check("대조군: 개수도 함께 오른다", body["image_count"], 1)
    finally:
        env.close()



def test_ready_document_without_served_file_is_not_advertised():
    """`document_status=READY` 인데 **서빙 파일이 없으면** 열람 가능이라고 답하지 않는다
    (2026-08-25, docs/BUGS.md #198).

    ## 왜 이 검사가 생겼나 - 사진에는 있고 문서에만 없던 2차 방어선

    바로 위 §17 이 사진에 대해 잠근 규칙("READY 인데 볼 사진이 0장이면 COLLECTING")이
    **문서에는 없었다.** 그래서 `document_status` 가 READY 이기만 하면 파일이 실제로
    없어도 `available=true` 에 `viewer_url` 까지 줬다. 실측(2026-08-25, 합성 물건):

        SPEC  status=READY  available=True  file_size=None
              viewer_url=/api/v1/item/<id>/documents/SPEC
        그 URL 을 실제로 요청 -> **HTTP 404**

    판단 근거는 이미 응답을 만드는 그 함수가 갖고 있었다 - `file_size` 는 **서빙 경로에서
    직접 잰 값**이라 파일이 없으면 None 이다. 그 값을 표시에만 쓰고 판정에는 쓰지 않았다.

    ## 운영 데이터에는 이 상태가 없다(그래서 예방이다)

    수정 전후로 실물 200물건 556문서의 응답을 통째로 비교했다 - **다른 물건 0건**,
    `available=true` 문서 수 556 -> 556. 즉 지금 데이터를 바꾸는 수정이 아니라,
    `doc_worker` 바깥 경로나 파일 유실로 그 상태가 생겼을 때를 위한 방어선이다.
    """
    print("\n--- 17b. READY 인데 서빙 파일이 없는 문서 (BUGS #198) ---")
    from fastapi.testclient import TestClient
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        from api_server import app
        client = TestClient(app)

        c = env.conn()
        for dt in ("SPEC", "APPRAISAL", "STATUS"):
            c.execute("INSERT INTO document_status (item_id,doc_type,status)"
                      " VALUES (1,?, 'READY')", (dt,))
        c.commit()
        c.close()

        docs = {d["doc_type"]: d for d in client.get("/api/v1/item/1").json()["documents"]}
        for dt in ("SPEC", "APPRAISAL", "STATUS"):
            d = docs.get(dt)
            check_true("%s 문서가 응답에 있다" % dt, d is not None)
            if d is None:
                continue
            check("★ %s 파일이 없으면 available=False" % dt, d["available"], False)
            check("★ %s 파일이 없으면 viewer_url 없음" % dt, d["viewer_url"], None)
            check("★ %s 파일이 없으면 download_url 없음" % dt, d["download_url"], None)
            check("%s 상태는 COLLECTING 으로 낮춘다" % dt, d["status"], "COLLECTING")
            check("%s file_size 는 모른다(None)" % dt, d["file_size"], None)

        # --- 대조군 1: 파일이 실제로 있으면 그대로 READY 다 --------------------
        #     이것이 없으면 "전부 available=False" 로도 통과해 검사가 공허해진다.
        import crawler.doc_paths as _dp
        d1 = _dp.get_doc_dir(court, case_no, item_no)
        os.makedirs(d1, exist_ok=True)
        with open(os.path.join(d1, "spec.pdf"), "wb") as fh:
            fh.write(b"%PDF-1.4 real" + b"x" * 50)
        docs = {d["doc_type"]: d for d in client.get("/api/v1/item/1").json()["documents"]}
        check("대조군: 파일이 있으면 available=True", docs["SPEC"]["available"], True)
        check("대조군: 그때는 READY 그대로", docs["SPEC"]["status"], "READY")
        check_true("대조군: viewer_url 을 준다", bool(docs["SPEC"]["viewer_url"]))
        check("대조군: file_size 는 실제 크기", docs["SPEC"]["file_size"],
              os.path.getsize(os.path.join(d1, "spec.pdf")))
        # 광고한 URL 이 실제로 열려야 한다 (advertise != serve 가 이 저장소의 반복 결함이다)
        check("대조군: 광고한 URL 이 실제로 200",
              client.get(docs["SPEC"]["viewer_url"]).status_code, 200)
        # 옆 문서는 여전히 낮춰진 상태여야 한다(한 파일이 다른 문서를 구제하지 않는다)
        check("한 파일이 다른 종류를 구제하지 않는다", docs["APPRAISAL"]["available"], False)

        # --- 대조군 2: 0바이트는 '있다'로 치지 않는다 -------------------------
        with open(os.path.join(d1, "appraisal.pdf"), "wb") as fh:
            fh.write(b"")
        docs = {d["doc_type"]: d for d in client.get("/api/v1/item/1").json()["documents"]}
        check("0바이트 파일은 available=False", docs["APPRAISAL"]["available"], False)

        # --- 대조군 3: READY 가 아닌 상태는 건드리지 않는다 -------------------
        c = env.conn()
        c.execute("UPDATE document_status SET status='FAILED' WHERE doc_type='STATUS'")
        c.commit()
        c.close()
        docs = {d["doc_type"]: d for d in client.get("/api/v1/item/1").json()["documents"]}
        check("FAILED 는 그대로 전달한다", docs["STATUS"]["status"], "FAILED")

        # --- 대조군 4: IMAGE 는 이 방어의 대상이 아니다 ----------------------
        #     사진은 서빙 파일이 하나로 정해지지 않는다(0~N장) - `DOC_TYPE_FILES` 에
        #     없으므로 크기를 잴 수 없고, 그것을 "없다"로 읽으면 **볼 수 있는 사진이
        #     있는 물건까지 수집중으로 가린다.** 판정은 `_images_status()` 가 한다.
        #
        #     ★ `READY` 로 두고 확인해야 한다. NO_IMAGE/FAILED 로 두면 애초에
        #       측정 분기(status==READY)에 들어가지 않아 **이 대조군이 공허해진다**
        #       (2026-08-25 mutation 에서 실제로 그랬다 - 적용 범위를 IMAGE 까지
        #        넓히는 변이를 못 잡았다).
        c = env.conn()
        c.execute("INSERT INTO document_status (item_id,doc_type,status)"
                  " VALUES (1,'IMAGE','READY')")
        c.commit()
        c.close()
        docs = {d["doc_type"]: d for d in client.get("/api/v1/item/1").json()["documents"]}
        check("★ IMAGE 는 READY 여도 문서 방어선이 낮추지 않는다",
              docs["IMAGE"]["status"], "READY")
        c = env.conn()
        c.execute("UPDATE document_status SET status='NO_IMAGE' WHERE doc_type='IMAGE'")
        c.commit()
        c.close()
        docs = {d["doc_type"]: d for d in client.get("/api/v1/item/1").json()["documents"]}
        check("IMAGE 의 NO_IMAGE 도 그대로 전달", docs["IMAGE"]["status"], "NO_IMAGE")
    finally:
        env.close()

def test_oversized_ids_are_404_not_500():
    """SQLite INTEGER 범위를 벗어난 id에 **인증 없이 500을 만들 수 있었다.**

    2026-08-17 Sprint 144 보안 감사에서 실측. 파이썬 int는 무한 정밀도인데 SQLite
    INTEGER는 64비트라, `/api/v1/item/999999999999999999999`가 그대로 sqlite3에
    바인딩되어 `OverflowError`로 터졌다. 데이터가 새지는 않지만 **없는 물건을 물었을 때
    404가 아니라 500이 나가고** 서버 로그에 스택 트레이스가 쌓인다.

    ★ 이 스프린트가 만든 결함이 아니다 — `/item/{id}`와 `/documents/`에 **이미 있었고**
      새로 만든 `/images/`가 같은 모양을 물려받은 것이다. 셋을 함께 고쳤다.
    """
    print("\n--- 18-A. 범위를 벗어난 id는 404 (500 아님) ---")
    from fastapi.testclient import TestClient
    from api.constants import is_sqlite_int, SQLITE_MAX_INT
    env = Env()
    try:
        env.seed_item(item_id=1)
        from api_server import app
        # raise_server_exceptions=False 여야 500을 예외가 아니라 응답으로 관찰할 수 있다.
        client = TestClient(app, raise_server_exceptions=False)
        big = SQLITE_MAX_INT + 1
        for label, url in (
            ("item detail", "/api/v1/item/%d" % big),
            ("documents", "/api/v1/item/%d/documents/SPEC" % big),
            ("images(item)", "/api/v1/item/%d/images/1" % big),
            ("images(seq)", "/api/v1/item/1/images/%d" % big),
            ("음수 초과", "/api/v1/item/%d" % (-big)),
        ):
            check("%s -> 404" % label, client.get(url).status_code, 404)

        # 경계값은 정상 처리돼야 한다(과잉 차단이 아님을 확인)
        check("경계값 자체는 404(500 아님)",
              client.get("/api/v1/item/%d" % SQLITE_MAX_INT).status_code, 404)
        check("정상 id는 그대로 200", client.get("/api/v1/item/1").status_code, 200)

        check("범위 판정 함수: 1", is_sqlite_int(1), True)
        check("범위 판정 함수: 경계", is_sqlite_int(SQLITE_MAX_INT), True)
        check("범위 판정 함수: 초과", is_sqlite_int(SQLITE_MAX_INT + 1), False)
    finally:
        env.close()


def test_deletion_never_escapes_document_root():
    """삭제가 `documents/` 밖으로 나가지 않는다 (2026-08-18 Sprint 192, BUGS #131).

    ## 왜 이 검사가 생겼나

    `api/v1/images.py` 는 **서빙**할 때 이미 경로 봉쇄를 한다. 그 파일의 주석이 이유를
    적어 두었다: *"DB 값에서 경로를 만들기 때문에 문서 쪽보다 오히려 더 필요하다
    (관리 도구나 옛 마이그레이션이 넣은 값이 항상 얌전하다고 가정하지 않는다)."*

    그런데 Sprint 191 이 추가한 `remove_stored_image_files()` 는 **같은 출처
    (`auction_image.storage_path`)의 값으로 파일을 지우면서 그 검사가 없었다.**
    읽기보다 삭제가 더 위험한데 방어는 읽기에만 있었던 셈이다.

    ## 전수 가드도 함께 건다

    "이 함수만 고쳤다"로 끝내지 않는다. 소스 트리의 **모든 삭제 지점**을 AST 로 찾아,
    DB/외부에서 온 경로를 지우는 곳이 봉쇄 없이 남아 있지 않은지 확인한다.
    """
    print("\n--- 18-B. 삭제는 documents/ 밖으로 못 나간다 (Sprint 192, BUGS #131) ---")
    import crawler.image_assets as ia
    from crawler.image_assets import remove_stored_image_files, is_inside_document_root

    tmp = tempfile.mkdtemp(prefix="qa_del_guard_")
    docs = os.path.join(tmp, "documents")
    os.makedirs(docs)
    saved = ia.DOCUMENT_ROOT
    ia.DOCUMENT_ROOT = docs
    try:
        inside_dir = os.path.join(docs, "법원", "사건", "1", "images")
        os.makedirs(inside_dir)
        inside = os.path.join(inside_dir, "01.jpg")
        with open(inside, "wb") as f:
            f.write(b"x" * 100)

        outside = os.path.join(tmp, "SECRET.txt")
        with open(outside, "wb") as f:
            f.write(b"do-not-delete")
        # ★ `..` 개수를 손으로 세지 않는다 — 처음 작성했을 때 한 단계 모자라
        #   `documents/` 안에 머무는 경로를 만들어 놓고 "탈출"이라 부르고 있었다.
        #   실제 목표 파일까지의 상대경로를 계산해 **반드시 탈출하는** 경로를 만든다.
        traversal = os.path.join(inside_dir, os.path.relpath(outside, inside_dir))
        check_true("탈출 경로가 실제로 바깥 파일을 가리킨다",
                   os.path.realpath(traversal) == os.path.realpath(outside),
                   (traversal, outside))

        check("안쪽 경로는 안쪽으로 판정", is_inside_document_root(inside), True)
        check("바깥 경로는 바깥으로 판정", is_inside_document_root(outside), False)
        check("`..` 로 빠져나가는 경로도 바깥",
              is_inside_document_root(traversal), False)

        removed = remove_stored_image_files([inside, outside, traversal])
        check("안쪽 하나만 지운다", removed, 1)
        check_true("안쪽 파일은 지워졌다", not os.path.exists(inside))
        check_true("바깥 파일은 그대로다", os.path.exists(outside))

        # 없는 파일은 조용히 넘어간다(목표 상태와 같으므로 실패가 아니다)
        check("이미 없는 파일은 0", remove_stored_image_files([inside]), 0)
        check("빈 입력은 0", remove_stored_image_files([]), 0)
        check("None 입력도 0", remove_stored_image_files(None), 0)
    finally:
        ia.DOCUMENT_ROOT = saved
        shutil.rmtree(tmp, ignore_errors=True)

    # --- 전수: 소스의 모든 삭제 지점이 안전한 출처를 쓰는가 ---
    #
    # DB 에서 온 경로를 지우는 곳은 `remove_stored_image_files()` 하나여야 한다.
    # 나머지는 전부 **코드가 구성한 경로**(다운로드 폴더 / image_path() / *.tmp / 상수)다.
    import ast as _ast

    root = os.path.dirname(os.path.abspath(__file__))
    DELETERS = {"remove", "unlink", "rmdir", "rmtree"}
    sites = []
    unparsed = []      # 못 읽은/못 판 파일 — **조용히 넘기지 않는다**
    for rel in ("crawler", "storage", "api"):
        base = os.path.join(root, rel)
        for dp_, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d != "__pycache__"]
            for f_ in fn:
                if not f_.endswith(".py"):
                    continue
                path = os.path.join(dp_, f_)
                # ★ `utf-8-sig` 여야 한다 (2026-08-18 Sprint 195, BUGS #133).
                #   이 저장소의 소스 70개에 UTF-8 BOM 이 있고, `encoding="utf-8"` 로 읽으면
                #   BOM 이 `\ufeff` 로 남아 `ast.parse` 가 거부한다. 그걸 `except SyntaxError:
                #   continue` 로 넘기면 **그 파일들이 감사에서 통째로 사라진다** —
                #   실측: 이 스캔 범위(crawler/storage/api) 안에서만 16개가 빠졌고, 그중
                #   `crawler/image_crawler.py` 에는 실제 삭제 지점이 3곳 있었다.
                #   (기존 가드들은 전부 utf-8-sig 를 쓰고 있었다. 이 둘만 빠져 있었다.)
                try:
                    with open(path, encoding="utf-8-sig") as fh:
                        tree = _ast.parse(fh.read())
                except (OSError, UnicodeDecodeError, SyntaxError) as exc:
                    unparsed.append("%s (%s)" % (
                        os.path.relpath(path, root).replace(os.sep, "/"),
                        type(exc).__name__))
                    continue
                for node in _ast.walk(tree):
                    if (isinstance(node, _ast.Call)
                            and isinstance(node.func, _ast.Attribute)
                            and node.func.attr in DELETERS
                            and isinstance(node.func.value, _ast.Name)
                            and node.func.value.id in ("os", "shutil")):
                        sites.append((os.path.relpath(path, root).replace(os.sep, "/"),
                                      node.lineno))

    # ★ 못 본 파일이 하나라도 있으면 이 검사의 결론은 성립하지 않는다.
    check("스캔 범위의 모든 파일을 실제로 읽고 팠다", unparsed, [])
    check_true("삭제 지점을 실제로 찾았다", len(sites) >= 5, sites)
    # 봉쇄가 있어야 하는 파일(= DB 값을 지우는 곳)에 실제로 봉쇄 함수가 있는지 확인한다.
    guard_src = open(os.path.join(root, "crawler", "image_assets.py"),
                     encoding="utf-8-sig").read()
    check_true("삭제 함수가 봉쇄를 호출한다",
               "if not is_inside_document_root(path)" in guard_src,
               "remove_stored_image_files 에 봉쇄가 없다")
    print("    삭제 지점 %d곳: %s"
          % (len(sites), ", ".join("%s:%d" % x for x in sorted(sites))))


def test_image_path_traversal_blocked():
    print("\n--- 18. 경로 탐색 차단 ---")
    from fastapi.testclient import TestClient
    env = Env()
    try:
        env.seed_item(item_id=1)
        outside = os.path.join(env.dir, "secret.jpg")
        with open(outside, "wb") as f:
            f.write(make_jpeg())
        c = env.conn()
        c.execute("INSERT INTO auction_image (item_id,seq,kind,storage_path,file_size)"
                  " VALUES (1,1,'전경도',?,100)", ("../secret.jpg",))
        c.commit()
        c.close()
        from api_server import app
        r = TestClient(app).get("/api/v1/item/1/images/1")
        check("documents/ 밖을 가리키면 404", r.status_code, 404)
    finally:
        env.close()


# ===========================================================================
# 19. 소스 간 규약 대조 (문자열이 갈라지면 "READY인데 404"가 된다)
# ===========================================================================

def test_worker_skips_navigation_when_sibling_reuse_possible():
    """사건 단위 문서를 형제에서 복사할 수 있으면 **브라우저 이동 자체를 건너뛰는가**
    (2026-08-17 Sprint 147).

    ## 왜 이 검사가 필요한가 (실측)

    Sprint 145가 `collect_status()` 안에 형제 재사용을 넣었지만, `doc_worker`의 루프가
    `go_to_case_detail()`을 **무조건 먼저** 불러서 정작 비싼 부분이 그대로 들었다:

        navigation   15.2초   <- 재사용해도 그대로 들던 비용
        overlay 수집  0.6초   <- 재사용이 아끼던 전부
        형제 복사     0.002초

    절감이 물건당 0.6초(4%)뿐이었다. Sprint 145 문서의 "약 3시간 절감"은 navigation까지
    건너뛴다고 **가정한** 값이라 틀렸다(실제 5분). 순서를 바꾸자 실 worker에서 2건 처리가
    41.1초 -> 23.8초가 됐다.

    이 검사는 **호출 순서**를 고정한다 — 재사용이 가능하면 `go_to_case_detail`이
    호출되지 않아야 한다. 순서가 되돌아가면 성능만 조용히 26배 나빠지고 결과는 같아서
    아무도 모른다.
    """
    print("\n--- 12-E. 재사용 가능하면 브라우저 이동을 건너뛴다 (Sprint 147) ---")
    import doc_worker
    env = Env()
    try:
        court, case_no = "서울중앙지방법원", "2025타경311"
        # 물건1에 정상 현황조사서를 심어 둔다(형제 재사용 대상)
        d1 = os.path.join(env.docs, court, case_no, "1")
        os.makedirs(d1)
        html = "<div id='curstExmndcPopUp'>사건번호 2025타경311 조사일시 ...</div>"
        with open(os.path.join(d1, "status.html"), "w", encoding="utf-8") as f:
            f.write(html)
        with open(os.path.join(d1, "status.json"), "w", encoding="utf-8") as f:
            f.write('{"extracted_at":"2026-08-17T02:00:00","fields":{"a":"1"}}')

        c = env.conn()
        c.execute("INSERT INTO auction_case (id,court_code,case_no) VALUES (1,?,?)", (court, case_no))
        c.execute("INSERT INTO auction_item (id,case_id,court_name,case_no,item_no,auction_date)"
                  " VALUES (1,1,?,?,'2',NULL)", (court, case_no))
        c.execute("INSERT INTO document_queue (court_code,case_no,item_no,doc_type,priority,"
                  "auction_date,status,retry_count,enqueued_at)"
                  " VALUES (?,?,'2','status',1,'2099-01-01','pending',0,'x')", (court, case_no))
        c.commit(); c.close()

        nav_calls = []
        collect_drivers = []
        real_collect = doc_worker.collect_document

        def spy_go_to_case_detail(driver, court_code, case_no_, item_no=None):
            nav_calls.append((case_no_, item_no))
            return True

        def spy_collect_document(driver, *a, **kw):
            collect_drivers.append(driver)
            return real_collect(driver, *a, **kw)

        originals = {}
        for name, val in (("go_to_case_detail", spy_go_to_case_detail),
                          ("collect_document", spy_collect_document),
                          ("init_db", lambda: None),
                          ("reset_stale_queue", lambda: None),
                          ("build_download_driver", lambda: object()),
                          ("restart_download_driver", lambda d: object())):
            originals[name] = getattr(doc_worker, name)
            setattr(doc_worker, name, val)
        orig_sleep = doc_worker.time_module.sleep
        doc_worker.time_module.sleep = lambda *_a, **_k: None
        os.environ["DOC_WORKER_TEST_MODE"] = "1"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = doc_worker.main()
        finally:
            for name, val in originals.items():
                setattr(doc_worker, name, val)
            doc_worker.time_module.sleep = orig_sleep

        check("worker 종료 코드", rc, 0)
        check("★ 브라우저 이동을 호출하지 않았다", nav_calls, [])
        check_true("collect_document에 driver=None으로 넘겼다",
                   collect_drivers == [None], collect_drivers)

        d2 = os.path.join(env.docs, court, case_no, "2")
        with open(os.path.join(d2, "status.html"), encoding="utf-8") as f:
            check("복사된 내용이 원본과 같다", f.read(), html)
        check("큐가 done으로 종결된다", env.conn().execute(
            "SELECT status FROM document_queue").fetchone()["status"], "done")
        check("화면 상태도 READY", env.status_of(1, "STATUS"), "READY")
    finally:
        env.close()


def test_reconcile_uses_court_in_identity_key():
    """큐 기일 정정이 **법원까지 포함해** 물건을 특정하는가 (2026-08-17 Sprint 146).

    법원마다 사건번호를 독립 채번하므로 같은 `2024타경4973`이 여러 법원에 존재한다.
    `reconcile_queue_auction_date()`는 처음에 `case_no + item_no`로만 찾았고, 그 근거는
    *"(case_no, item_no)는 auction_item에서 유일하다"* 였다 — **틀린 것을 확인한 것**이다.
    `auction_item` 안에서 유일한 것과, **큐 행이 자기 법원의 물건과 맺어지는가**는 다르다.

    실측(2026-08-17): 큐의 (사건,물건)이 다른 법원의 auction_item과 매칭되는 행이 **18행**
    (그중 pending 12행). 정정하려던 함수가 엉뚱한 사건의 날짜를 덮어쓸 수 있었다 —
    `docs/BUGS.md` #18/#14가 같은 저장소에서 두 번 잡은 "법원 없는 식별키" 함정의 재발이다.
    """
    print("\n--- 12-D. 큐 기일 정정의 식별키에 법원이 포함되는가 (Sprint 146) ---")
    import storage.database as dbmod
    env = Env()
    try:
        c = env.conn()
        # 같은 사건번호를 쓰는 서로 다른 두 법원
        c.execute("INSERT INTO auction_case (id,court_code,case_no) VALUES (1,'성남지원','2024타경4973')")
        c.execute("INSERT INTO auction_case (id,court_code,case_no) VALUES (2,'통영지원','2024타경4973')")
        c.execute("INSERT INTO auction_item (id,case_id,court_name,case_no,item_no,auction_date)"
                  " VALUES (1,1,'성남지원','2024타경4973','1','2026-07-20')")
        c.execute("INSERT INTO auction_item (id,case_id,court_name,case_no,item_no,auction_date)"
                  " VALUES (2,2,'통영지원','2024타경4973','1','2026-08-10')")
        qid = c.execute(
            "INSERT INTO document_queue (court_code,case_no,item_no,doc_type,priority,"
            "auction_date,status,retry_count,enqueued_at)"
            " VALUES ('성남지원','2024타경4973','1','spec',1,'2026-07-20','pending',0,'x')"
        ).lastrowid
        c.commit(); c.close()

        # 성남지원 큐를 정정하면 성남 물건(2026-07-20)을 봐야 한다.
        # 법원을 안 보면 통영 물건(2026-08-10)에 걸려 엉뚱하게 덮어쓴다.
        got = dbmod.reconcile_queue_auction_date(qid, '2024타경4973', '1', '2026-07-20', '성남지원')
        check("자기 법원 물건을 본다(값 변경 없음)", got, '2026-07-20')
        check_true("다른 법원 기일로 오염되지 않았다", got != '2026-08-10', got)

        c = env.conn()
        try:
            final = c.execute("SELECT auction_date FROM document_queue WHERE id=?",
                              (qid,)).fetchone()["auction_date"]
        finally:
            c.close()
        check("큐 행도 오염되지 않았다", final, '2026-07-20')

        # 법원을 못 받으면 **추측하지 않는다**(잘못 고치느니 안 고친다)
        got2 = dbmod.reconcile_queue_auction_date(qid, '2024타경4973', '1', '2026-07-20', None)
        check("법원 미지정이면 정정하지 않는다", got2, '2026-07-20')

        # 실제로 정정이 필요한 경우는 여전히 동작해야 한다(과잉 방어가 아님을 확인)
        c = env.conn()
        c.execute("UPDATE document_queue SET auction_date='2026-01-01' WHERE id=?", (qid,))
        c.commit(); c.close()
        got3 = dbmod.reconcile_queue_auction_date(qid, '2024타경4973', '1', '2026-01-01', '성남지원')
        check("진짜 드리프트는 여전히 정정한다", got3, '2026-07-20')

        # 호출부가 법원을 넘기는지 소스로 고정한다
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "doc_worker.py"),
                   encoding="utf-8-sig").read()
        check_true("doc_worker가 court_code를 넘긴다",
                   "item_no, auction_date, court_code" in src.replace("\n", " ").replace("  ", " "),
                   "호출 형태가 바뀌었다면 법원 전달을 다시 확인할 것")
    finally:
        env.close()


def test_path_segment_rule_is_single_sourced():
    """경로 조각 정규화 규칙이 **쓰는 쪽과 읽는 쪽에서 같은가** (2026-08-17 Sprint 146).

    Sprint 145에 `sanitize_path_segment()`가 신설되면서 쓰는 쪽(`crawler.doc_paths`)은
    역슬래시까지 치환하게 됐는데 **읽는 쪽(`api/v1/documents.py`)만 옛 규칙으로 남아
    있었다.** 사건번호에 역슬래시가 섞이면 크롤러는 `a_b`에 쓰고 API는 `a\\b`를 찾아
    같은 문서를 두 경로로 보게 된다 — 이 저장소가 BUGS #50/#64로 반복해 겪은 어긋남이다.

    현재 실데이터에 역슬래시는 0건이라 지금 터지는 버그는 아니었지만, **규칙이 두 벌인
    상태 자체**가 결함이다. 두 구현이 같은 답을 내는지 직접 대조해 고정한다.
    """
    print("\n--- 19-B. 경로 조각 규칙 단일화 (Sprint 146) ---")
    from api.v1.documents import get_doc_dir as api_dir
    from crawler.doc_paths import _doc_dir_path as crawler_dir, sanitize_path_segment

    samples = [
        ("서울중앙지방법원", "2024타경1 / 2024타경2", "1"),   # 실데이터의 22.7%가 '/' 포함
        ("서울중앙지방법원", "2024타경3528", "1"),
        ("고양지원", "2024\\타경1", "2"),                     # Windows 경로 구분자
        ("A법원", "..", "1"),                                  # 상위 디렉터리 탈출 시도
        ("A법원", "", "1"),                                    # 빈 조각
        ("A법원", "2024타경1", ""),                            # 빈 물건번호
    ]
    for court, case, item in samples:
        check("쓰는 쪽/읽는 쪽 경로 일치 (case=%r item=%r)" % (case, item),
              api_dir(court, case, item), crawler_dir(court, case, item))

    # ★ **루트 자체**도 같은가 (2026-08-19 Sprint 217 보강).
    #   위 비교는 전체 경로라 루트가 갈라지면 어차피 걸린다. 그런데 두 모듈이 각자
    #   `DOCUMENT_ROOT` 를 들고 있다는 사실은 **경로가 같아도 그대로 남는 위험**이다 —
    #   실제로 테스트 하네스가 한쪽만 갈아 끼워 서빙이 항상 404 가 된 적이 있다
    #   (12-L 을 쓰다가 걸렸다). 사본이 몇 개인지 여기서 눈에 보이게 못 박는다.
    import api.v1.documents as _apidoc
    import api.v1.images as _apiimg
    import crawler.doc_paths as _dp
    import crawler.image_assets as _ia
    roots = {
        "api.v1.documents": _apidoc.DOCUMENT_ROOT,
        "api.v1.images": _apiimg.DOCUMENT_ROOT,
        "crawler.doc_paths": _dp.DOCUMENT_ROOT,
        "crawler.image_assets": _ia.DOCUMENT_ROOT,
    }
    # ★ `PROJECT_ROOT` 도 **6개 모듈이 각자 계산한다** (2026-08-19 Sprint 217 보강).
    #   디렉터리 깊이가 달라 식이 서로 다른 것은 정상이다 —
    #   `os.path.dirname(...)` 을 두 번 감는 것과 세 번 감는 것이 섞여 있다.
    #   위험한 것은 **파일이 옮겨졌을 때 조용히 다른 곳을 가리키는 것**이다:
    #   `storage/database.py` 의 값은 `to_relative_storage_path()` 가 저장 경로를
    #   상대경로로 접는 기준이라, 어긋나면 DB 에 적힌 경로가 아무 데도 안 맞게 된다.
    #   식이 아니라 **결과**를 대조한다.
    import api.v1.registry as _apireg
    import storage.database as _dbmod
    project_roots = {
        "api.v1.documents": _apidoc.PROJECT_ROOT,
        "api.v1.images": _apiimg.PROJECT_ROOT,
        "api.v1.registry": _apireg.PROJECT_ROOT,
        "crawler.doc_paths": _dp.PROJECT_ROOT,
        "crawler.image_assets": _ia.PROJECT_ROOT,
        "storage.database": _dbmod.PROJECT_ROOT,
    }
    check_true("PROJECT_ROOT 를 계산하는 모듈을 실제로 찾았다(검사가 공허하지 않다)",
               len(project_roots) >= 6, len(project_roots))
    check("PROJECT_ROOT 6곳이 같은 곳을 가리킨다",
          sorted(set(os.path.normcase(os.path.abspath(v))
                     for v in project_roots.values())),
          [os.path.normcase(os.path.abspath(_dp.PROJECT_ROOT))])

    check("문서 루트를 들고 있는 모듈 4곳이 같은 값을 본다",
          sorted(set(os.path.normcase(os.path.abspath(v)) for v in roots.values())),
          [os.path.normcase(os.path.abspath(_dp.DOCUMENT_ROOT))])

    # 정규화 함수 자체의 계약
    check("슬래시는 밑줄로", sanitize_path_segment("a/b"), "a_b")
    check("역슬래시도 밑줄로", sanitize_path_segment("a\\b"), "a_b")
    check_true("상위 이동 조각은 그대로 쓰지 않는다",
               sanitize_path_segment("..") not in ("", ".", ".."),
               sanitize_path_segment(".."))
    check_true("빈 값도 그대로 쓰지 않는다",
               sanitize_path_segment("") not in ("", ".", ".."),
               sanitize_path_segment(""))

    # 조각이 DOCUMENT_ROOT 밖을 가리키지 못한다
    import os as _os
    from crawler.doc_paths import DOCUMENT_ROOT
    for bad in ("..", "../..", "..\\..", "/etc", "\\windows"):
        p = _os.path.realpath(crawler_dir("법원", bad, "1"))
        root = _os.path.realpath(DOCUMENT_ROOT)
        check_true("case_no=%r 가 documents/ 밖으로 못 나간다" % bad,
                   _os.path.commonpath([root, p]) == root, p)


def test_image_success_is_not_recorded_before_the_photos_are():
    """사진을 DB에 적기 **전에** 성공을 먼저 기록하지 않는가 (Sprint 208).

    ## 무엇이 문제였나

    `doc_worker` 의 성공 분기는 이 순서였다.

        mark_queue_done(...)        # 큐 done + document_status READY
        save_auction_images(...)    # auction_image 행

    뒤엣것이 실패하면(DB 잠금, 파일 접근 실패 등) 바깥 `except` 가 큐를 되돌려
    재시도는 되지만 **`document_status` 는 이미 READY 로 덮여 있다.**
    화면은 "사진 있음"이라고 말하는데 `auction_image` 는 0행이다.
    재시도가 소진되면(`MAX_DOC_RETRY`) 그 거짓말이 영구가 된다.

    fixture 재현 결과(수정 전):

        document_queue   pending (retry 1)
        document_status  IMAGE / READY      <- 볼 수 있다고 말한다
        auction_image    0행                <- 가리킬 사진이 없다

    ## 문서와 사진의 비대칭이 원인이다

    문서(spec/status/appraisal)의 실체 기록인 `doc_raw` 는 `mark_queue_done()` 이
    **여는 트랜잭션 안에서** 쓰인다 - 원자적이라 이 창이 없다.
    사진만 `save_auction_images()` 가 트랜잭션 밖에 있었다.

    ## 이 검사가 고정하는 것

    사진 기록이 실패하면 **성공 표시가 남지 않는다.** 순서를 되돌리면 즉시 FAIL 한다.

    남는 창 하나는 그대로 인정한다 - 사진을 먼저 적고 `mark_queue_done()` 이 실패하면
    `auction_image` 에 행이 있고 성공 표시는 없다. 그 방향은 **안전한 쪽**이다
    (화면이 거짓말하지 않고, 재시도가 `INSERT OR REPLACE` 로 덮는다).
    """
    print("\n--- 12-F. 사진을 적기 전에 성공을 먼저 기록하지 않는다 (Sprint 208) ---")
    import doc_worker

    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        env.enqueue(court, case_no, item_no, "image")

        img_dir = os.path.join(env.docs, court, case_no, item_no, "images")
        os.makedirs(img_dir)
        images = []
        for i in (1, 2):
            p = os.path.join(img_dir, "%02d.jpg" % i)
            with open(p, "wb") as fh:
                fh.write(make_jpeg(pad=MIN_FIXTURE_PAD + 64 * i))
            images.append({"seq": i, "kind": "전경도", "path": p,
                           "file_size": os.path.getsize(p),
                           "file_hash": hashlib.sha256(open(p, "rb").read()).hexdigest(),
                           "width": 1, "height": 1})

        def fake_collect(driver, court_code, case_no_, item_no_, doc_type, btn_id,
                         overwrite=False):
            return {"success": True, "previous_hash": None, "new_hash": "h1",
                    "files_saved": 2, "images": images, "partial": False,
                    "no_asset": False}

        def exploding_save(*a, **kw):
            raise RuntimeError("사진 기록 실패 (주입)")

        originals = {}
        for name, val in (("collect_document", fake_collect),
                          ("save_auction_images", exploding_save),
                          ("go_to_case_detail", lambda *a, **k: True),
                          ("init_db", lambda: None),
                          ("reset_stale_queue", lambda: None),
                          ("build_download_driver", lambda: object()),
                          ("restart_download_driver", lambda d: object())):
            originals[name] = getattr(doc_worker, name)
            setattr(doc_worker, name, val)
        orig_sleep = doc_worker.time_module.sleep
        doc_worker.time_module.sleep = lambda *a, **k: None
        os.environ["DOC_WORKER_TEST_MODE"] = "1"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                doc_worker.main()
        finally:
            for name, val in originals.items():
                setattr(doc_worker, name, val)
            doc_worker.time_module.sleep = orig_sleep

        c = env.conn()
        try:
            statuses = [r["status"] for r in
                        c.execute("SELECT status FROM document_status").fetchall()]
            n_img = c.execute("SELECT COUNT(*) FROM auction_image").fetchone()[0]
            q = c.execute("SELECT status, retry_count FROM document_queue").fetchone()
        finally:
            c.close()

        check("사진 기록이 실패했으므로 auction_image는 0행", n_img, 0)
        # ★ 본론: 볼 수 있다고 말하는 상태가 남으면 안 된다.
        claimed = [st for st in statuses if st in ("READY", "NO_IMAGE")]
        check("★ '볼 수 있다'는 상태를 남기지 않았다", claimed, [])
        check_true("큐는 재시도 대상으로 남는다 (%s/retry=%s)" % (q["status"], q["retry_count"]),
                   q["status"] in ("pending", "failed") and q["retry_count"] >= 1,
                   dict(q))

        # 대조군 - 사진 기록이 성공하면 정상적으로 READY + 행이 함께 생긴다.
        #
        # ★ 큐를 손으로 되돌린 뒤 돌린다. `mark_queue_failed()` 가 `last_attempt_at` 을
        #   지금으로 찍어 두고, 클레임은 `RETRY_INTERVAL_MINUTES` 안에 다시 집지 않는다.
        #   그것은 옳은 동작이고 여기서 검증하려는 것이 아니다(재시도 간격은
        #   `test_document_queue.py` 소관). 이 대조군이 보려는 것은 **성공 경로에서
        #   사진과 상태가 함께 생기는가** 하나다. 되돌리지 않으면 이 검사가
        #   "0장"을 보고 결함이라고 오해한다 - 실제로 한 번 그렇게 실패했다.
        c = env.conn()
        try:
            c.execute("UPDATE document_queue SET status='pending', retry_count=0,"
                      " last_attempt_at=NULL")
            c.commit()
        finally:
            c.close()

        for name, val in (("collect_document", fake_collect),
                          ("go_to_case_detail", lambda *a, **k: True),
                          ("init_db", lambda: None),
                          ("reset_stale_queue", lambda: None),
                          ("build_download_driver", lambda: object()),
                          ("restart_download_driver", lambda d: object())):
            originals[name] = getattr(doc_worker, name)
            setattr(doc_worker, name, val)
        doc_worker.time_module.sleep = lambda *a, **k: None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                doc_worker.main()
        finally:
            for name, val in originals.items():
                setattr(doc_worker, name, val)
            doc_worker.time_module.sleep = orig_sleep

        c = env.conn()
        try:
            statuses2 = [r["status"] for r in
                         c.execute("SELECT status FROM document_status").fetchall()]
            n_img2 = c.execute("SELECT COUNT(*) FROM auction_image").fetchone()[0]
        finally:
            c.close()
        check("대조군: 정상 처리면 사진이 기록된다", n_img2, 2)
        check_true("대조군: 그때는 READY가 생긴다", "READY" in statuses2, statuses2)
    finally:
        env.close()


def _run_image_worker_case(env, court, case_no, item_no, qid,
                           collect_result, save_mode=None, new_seqs=(1, 2),
                           make_files=True):
    """한 시나리오를 `doc_worker.main()` 으로 끝까지 흘려보내고 최종 상태를 돌려준다.

    "예외가 났다"로 판정하지 않는다 — **큐 최종 상태**까지 본다.
    """
    import doc_worker

    img_dir = os.path.join(env.docs, court, case_no, item_no, "images")
    if not os.path.isdir(img_dir):
        os.makedirs(img_dir)

    images = []
    for i in new_seqs:
        p = os.path.join(img_dir, "%02d.jpg" % i)
        if make_files:
            with open(p, "wb") as fh:
                fh.write(make_jpeg(pad=MIN_FIXTURE_PAD + 64 * i))
        size = os.path.getsize(p) if os.path.exists(p) else 999
        digest = (hashlib.sha256(open(p, "rb").read()).hexdigest()
                  if os.path.exists(p) else "0" * 64)
        images.append({"seq": i, "kind": "전경도", "path": p, "file_size": size,
                       "file_hash": digest, "width": 1, "height": 1})

    result = dict(collect_result)
    if result.get("images") == "USE":
        result["images"] = images

    def fake_collect(driver, cc, cn, ino, dt, btn, overwrite=False):
        return result

    real_save = doc_worker.save_auction_images
    if save_mode == "raise":
        def patched(*a, **k):
            raise RuntimeError("DB asset 기록 실패 (주입)")
    elif save_mode == "zero":
        def patched(*a, **k):
            return {"saved": 0, "skipped_missing": 0, "removed_stale": 0}
    else:
        patched = real_save

    originals = {}
    for name, val in (("collect_document", fake_collect),
                      ("save_auction_images", patched),
                      ("go_to_case_detail", lambda *a, **k: True),
                      ("init_db", lambda: None),
                      ("reset_stale_queue", lambda: None),
                      ("build_download_driver", lambda: object()),
                      ("restart_download_driver", lambda d: object())):
        originals[name] = getattr(doc_worker, name)
        setattr(doc_worker, name, val)
    orig_sleep = doc_worker.time_module.sleep
    doc_worker.time_module.sleep = lambda *a, **k: None
    os.environ["DOC_WORKER_TEST_MODE"] = "1"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            doc_worker.main()
    finally:
        for name, val in originals.items():
            setattr(doc_worker, name, val)
        doc_worker.time_module.sleep = orig_sleep

    c = env.conn()
    try:
        q = c.execute("SELECT status FROM document_queue WHERE id=?", (qid,)).fetchone()
        n = c.execute("SELECT COUNT(*) FROM auction_image").fetchone()[0]
        st = [r["status"] for r in
              c.execute("SELECT status FROM document_status").fetchall()]
    finally:
        c.close()
    return {"queue": q["status"], "images": n, "status": st}


def test_image_done_requires_actual_asset_record():
    """이미지 성공판정 A~F — **큐가 done 이 되는 조건**을 표로 고정한다 (Sprint 214).

    ## 왜 필요한가

    Sprint 208 이 순서를 바로잡았다(실체 기록 -> 성공 기록). 그것만으로는 부족했다.
    `save_auction_images()` 는 **예외를 던지지 않고** 0장을 기록할 수 있다 —
    디스크에 파일이 없으면 그 항목을 건너뛰고 `saved=0` 을 돌려준다.
    호출부가 그 반환값을 **로그로만** 써서, 한 장도 남기지 못한 실행이
    `done` + `READY` 로 끝났다. fixture 로 두 경로를 재현했다.

        C 수집기가 준 경로에 파일이 없다   -> done/READY/0행   (수정 전)
        E save 가 saved=0 을 돌려준다      -> done/READY/0행   (수정 전)

    "함수를 불렀다"와 "성공했다"는 다르다.

    ## 표

        A 다운로드 실패(success=False)   done 아님
        B 부분 수집(partial=True)        **done** — 문서화된 계약이다(아래 참고)
        C 파일이 디스크에 없다            done 아님
        D 기록 중 예외                   done 아님
        E 기록이 0장                     done 아님
        F 전체 성공                      done

    ## B 가 done 인 것은 결함이 아니라 계약이다

    `crawler/image_crawler.collect_images()` 의 docstring 이 명시한다 —
    "부분 성공을 전체 성공으로 뭉개지 않는다 ... **큐에서는 종결되지만** 로그와
    반환값에 사실이 남는다." 한 장이라도 남으면 사용자가 볼 것이 생기고,
    실패로 돌리면 재시도 예산을 태우다 결국 `failed` 로 끝난다.
    이 검사는 그 계약을 **그대로 고정**한다 — 바꾸려면 여기가 먼저 실패해야 한다.

    ## 기존 asset 보존도 함께 본다

    A/C/D/E 는 전부 실패지만, **이미 갖고 있던 사진 2장은 그대로 남아야 한다.**
    `save_auction_images()` 가 `saved and complete` 일 때만 지우므로 저장소 계층에서
    이미 보장되지만, 호출부를 바꿀 때 깨질 수 있어 여기서 함께 잠근다.
    """
    print("\n--- 12-G. 이미지 성공판정 A~F (Sprint 214) ---")
    from storage.database import save_auction_images

    OK = {"success": True, "previous_hash": None, "new_hash": "h1",
          "files_saved": 2, "images": "USE", "partial": False, "no_asset": False}

    # (라벨, collect 결과, save 주입, 새 순번, 파일 생성, 기대 큐 상태)
    CASES = [
        ("A 다운로드 실패", dict(OK, success=False, images=[], files_saved=0),
         None, (1, 2), True, "pending"),
        ("B 부분 수집(계약상 성공)", dict(OK, partial=True), None, (1, 2), True, "done"),
        ("C 파일이 디스크에 없다", dict(OK), None, (3, 4), False, "pending"),
        ("D 기록 중 예외", dict(OK), "raise", (1, 2), True, "pending"),
        ("E 기록이 0장", dict(OK), "zero", (1, 2), True, "pending"),
        ("F 전체 성공", dict(OK), None, (1, 2), True, "done"),
    ]

    for seeded in (False, True):
        for label, res, mode, seqs, mkfiles, expect in CASES:
            env = Env()
            try:
                court, case_no, item_no = env.seed_item()
                qid = env.enqueue(court, case_no, item_no, "image")

                if seeded:
                    # 이미 정상 수집돼 있던 사진 2장(순번 1,2)
                    d = os.path.join(env.docs, court, case_no, item_no, "images")
                    os.makedirs(d)
                    olds = []
                    for i in (1, 2):
                        p = os.path.join(d, "%02d.jpg" % i)
                        with open(p, "wb") as fh:
                            fh.write(make_jpeg(pad=MIN_FIXTURE_PAD + 8 * i))
                        olds.append({"seq": i, "kind": "전경도", "path": p,
                                     "file_size": os.path.getsize(p),
                                     "file_hash": hashlib.sha256(
                                         open(p, "rb").read()).hexdigest(),
                                     "width": 1, "height": 1})
                    save_auction_images(court, case_no, item_no, olds, complete=True)
                    # ★ 실물에서는 화면 상태도 함께 있다 — `mark_queue_done()` 이
                    #   `auction_image` 와 `document_status` 를 같이 남기기 때문이다.
                    #   `save_auction_images()` 만 부르면 화면 상태가 없어 실물보다
                    #   좁은 픽스처가 된다(처음에 그렇게 만들어 기대값을 헛짚었다).
                    c = env.conn()
                    try:
                        c.execute("INSERT INTO document_status (item_id, doc_type, status)"
                                  " VALUES (1,'IMAGE','READY')")
                        c.commit()
                    finally:
                        c.close()

                got = _run_image_worker_case(env, court, case_no, item_no, qid,
                                             res, mode, seqs, mkfiles)
                tag = "기존있음" if seeded else "기존없음"
                check("%s [%s] 큐 최종 상태" % (label, tag), got["queue"], expect)

                # 실패 시나리오에서 이미 갖고 있던 사진을 잃지 않는다.
                if seeded and expect != "done":
                    check_true("%s [%s] ★ 기존 사진 2장을 잃지 않았다" % (label, tag),
                               got["images"] >= 2, got["images"])
                    # 실패가 **이미 볼 수 있던 것**을 빼앗지 않는다 (BUGS #122 계열).
                    check("%s [%s] 이미 READY 이던 화면 상태를 유지한다" % (label, tag),
                          [x for x in got["status"] if x in ("READY", "NO_IMAGE")],
                          ["READY"])
            finally:
                env.close()


def test_document_done_requires_the_file_to_exist():
    """문서: **저장했다는 파일이 실제로 있어야** done 이다 (Sprint 214 §2).

    사진에서 고친 것과 **같은 계열**이다. `_record_doc_raw()` 의 docstring 이
    이미 이 상태를 적고 있었다 —

        "파일이 없으면 ... doc_raw 행을 만들지 않는다 — 큐/상태는 **이미 done/READY로
         갔지만** ... 여기서 뒤집지는 않는다 (뒤집으려면 collect_document() 의 성공
         판정을 고쳐야 한다)."

    fixture 로 재현했다(수정 전):

        queue=done  document_status=SPEC/READY  doc_raw=0행
        API        available=true + viewer_url  (열면 없는 파일)

    ## 검사 범위를 좁게 잡은 이유

    - `files_saved` 가 **비어 있으면 검사하지 않는다**. "이미 존재. 스킵" 경로가
      정상적으로 빈 목록을 돌려준다 — 그 문서는 이전 실행에서 이미 받아 뒀다.
      여기서 실패로 뒤집으면 **정상 동작을 실패로 만든다**(반대 방향 결함).
    - `doc_exists()` 로 완성도를 요구하지 않는다. 문서에도 부분 성공
      (원본만 저장, 구조화 실패)이 계약으로 있어서, 그것까지 뒤집으면 정책 변경이 된다.
    """
    print(chr(10) + "--- 12-H. 문서는 저장했다는 파일이 있어야 done (Sprint 214) ---")
    import doc_worker

    def run(files, make, expect_queue):
        env = Env()
        try:
            court, case_no, item_no = env.seed_item()
            qid = env.enqueue(court, case_no, item_no, "spec")
            d = os.path.join(env.docs, court, case_no, item_no)
            os.makedirs(d, exist_ok=True)
            paths = [os.path.join(d, f) for f in files]
            if make:
                for p in paths:
                    with open(p, "wb") as fh:
                        fh.write(b"%PDF-1.4" + b"x" * 400)

            def fake_collect(driver, cc, cn, ino, dt, btn, overwrite=False):
                return {"success": True, "previous_hash": None, "new_hash": "h1",
                        "files_saved": paths, "partial": False, "no_asset": False}

            originals = {}
            for name, val in (("collect_document", fake_collect),
                              ("go_to_case_detail", lambda *a, **k: True),
                              ("init_db", lambda: None),
                              ("reset_stale_queue", lambda: None),
                              ("build_download_driver", lambda: object()),
                              ("restart_download_driver", lambda dd: object())):
                originals[name] = getattr(doc_worker, name)
                setattr(doc_worker, name, val)
            orig_sleep = doc_worker.time_module.sleep
            doc_worker.time_module.sleep = lambda *a, **k: None
            os.environ["DOC_WORKER_TEST_MODE"] = "1"
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    doc_worker.main()
            finally:
                for name, val in originals.items():
                    setattr(doc_worker, name, val)
                doc_worker.time_module.sleep = orig_sleep

            c = env.conn()
            try:
                q = c.execute("SELECT status FROM document_queue WHERE id=?",
                              (qid,)).fetchone()["status"]
                st = [r["status"] for r in
                      c.execute("SELECT status FROM document_status").fetchall()]
                raw = c.execute("SELECT COUNT(*) FROM doc_raw").fetchone()[0]
            finally:
                c.close()
            return q, st, raw
        finally:
            env.close()

    q, st, raw = run(["spec.pdf"], True, "done")
    check("정상: 큐 done", q, "done")
    check("정상: 화면 READY", st, ["READY"])
    check("정상: doc_raw 1행", raw, 1)

    q, st, raw = run(["spec.pdf"], False, "pending")
    check("★ 저장했다는 파일이 없으면 done 이 아니다", q, "pending")
    check("★ '볼 수 있다'는 상태를 만들지 않는다", st, [])
    check("doc_raw 도 남지 않는다", raw, 0)

    # 대조군 — "이미 존재. 스킵" 은 files_saved 가 비어 있다. 실패로 뒤집으면 안 된다.
    q, st, raw = run([], False, "done")
    check("대조군: files_saved 가 비면(스킵 경로) 그대로 done", q, "done")


def app_for_tests():
    """`api_server.app` 을 필요한 순간에만 가져온다(모듈 최상단 import 를 늘리지 않는다)."""
    from api_server import app
    return app


def _run_doc_worker_real_collector(env, court, case_no, item_no, qid):
    """`collect_document()` 를 **가짜로 바꾸지 않고** worker 를 한 바퀴 돌린다.

    12-H 는 수집기를 가짜로 바꿔 성공판정만 봤다. 여기서 보려는 것은 그 반대다 —
    **실제 수집기의 "이미 존재. 스킵" 분기**가 무엇을 돌려주고, 그것이 DB 에
    어떻게 남는가. 스킵 분기는 driver 를 건드리기 전에 return 하므로
    브라우저 없이도 진짜 코드가 그대로 돈다.
    """
    import doc_worker

    originals = {}
    for name, val in (("go_to_case_detail", lambda *a, **k: True),
                      ("init_db", lambda: None),
                      ("reset_stale_queue", lambda: None),
                      ("build_download_driver", lambda: object()),
                      ("restart_download_driver", lambda dd: object())):
        originals[name] = getattr(doc_worker, name)
        setattr(doc_worker, name, val)
    orig_sleep = doc_worker.time_module.sleep
    doc_worker.time_module.sleep = lambda *a, **k: None
    os.environ["DOC_WORKER_TEST_MODE"] = "1"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            doc_worker.main()
    finally:
        for name, val in originals.items():
            setattr(doc_worker, name, val)
        doc_worker.time_module.sleep = orig_sleep

    c = env.conn()
    try:
        q = c.execute("SELECT status FROM document_queue WHERE id=?",
                      (qid,)).fetchone()["status"]
        st = [(r["doc_type"], r["status"]) for r in
              c.execute("SELECT doc_type,status FROM document_status ORDER BY doc_type")]
        raw = [dict(r) for r in c.execute(
            "SELECT doc_type, doc_version, storage_path, file_size, file_hash"
            " FROM doc_raw ORDER BY doc_type, doc_version")]
        ver = c.execute("SELECT COUNT(*) FROM document_version_log").fetchone()[0]
    finally:
        c.close()
    return {"queue": q, "status": st, "raw": raw, "version_log": ver}


def test_queue_write_failure_after_the_photos_are_recorded():
    """실체는 남았는데 **큐 성공기록이 실패**하면? 그리고 그 뒤 재시도는? (Sprint 217)

    Sprint 208/214 는 순서(실체 -> 성공)와 판정(결과를 본다)을 고쳤다. 남은 칸이 있다 —
    **그 둘 사이**에서 죽는 경우다. `save_auction_images()` 는 이미 커밋했는데
    `mark_queue_done()` 이 실패한다(DB 잠금, 디스크 가득, 프로세스 kill 직전 등).

    ## 이 검사가 고정하는 것

        [3] 큐 성공기록 실패
            큐        pending / retry 1      재시도 가능하다
            사진      2행 그대로             이미 확보한 실체를 잃지 않는다
            화면      IMAGE 행이 **없다**    거짓 READY 를 만들지 않는다
            개정이력  0행                    끝나지 않은 실행이 이력을 남기지 않는다
            API       사진 2장 / READY       실제로 볼 수 있으니 이것은 거짓이 아니다

        [3-b] **즉시** 다시 돌려도 집어가지 않는다
            `RETRY_INTERVAL_MINUTES` 가 지나기 전에는 claim 되지 않는다.
            (뜨거운 재시도 루프로 법원 서버를 두드리지 않는다 — BUGS #101 계열)

        [5] 재시도 성공
            사진      여전히 2행             INSERT OR REPLACE 라 두 벌 쌓이지 않는다
            디스크    파일 2개 / .tmp 없음   고아 파일이 생기지 않는다
            큐        done / 화면 READY
            개정이력  0행                    **바이트가 그대로면 거짓 개정을 남기지 않는다**

    마지막 줄이 특히 중요하다 — 재시도는 "다시 저장"이지 "개정"이 아니다.
    """
    print(chr(10) + "--- 12-J. 큐 성공기록 실패와 그 뒤의 재시도 (Sprint 217) ---")
    from datetime import datetime as _dt, timedelta as _td
    from fastapi.testclient import TestClient
    import doc_worker

    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        qid = env.enqueue(court, case_no, item_no, "image")
        d = os.path.join(env.docs, court, case_no, item_no, "images")
        os.makedirs(d)
        images = []
        for i in (1, 2):
            p = os.path.join(d, "%02d.jpg" % i)
            with open(p, "wb") as fh:
                fh.write(make_jpeg(pad=MIN_FIXTURE_PAD + 64 * i))
            with open(p, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            images.append({"seq": i, "kind": "전경도", "path": p,
                           "file_size": os.path.getsize(p), "file_hash": digest,
                           "width": 1, "height": 1})
        set_hash = hashlib.sha256(
            "".join(i["file_hash"] for i in images).encode("ascii")).hexdigest()

        calls = []

        def run(done_raises, previous_hash):
            """`collect_images()` 가 실제로 돌려주는 모양 그대로 흘려보낸다."""
            def fake_collect(driver, cc, cn, ino, dt, btn, overwrite=False):
                calls.append(overwrite)
                return {"success": True, "previous_hash": previous_hash,
                        "new_hash": set_hash, "files_saved": [i["path"] for i in images],
                        "images": list(images), "partial": False, "no_asset": False}

            real_done = doc_worker.mark_queue_done

            def done_patch(*a, **k):
                if done_raises:
                    raise RuntimeError("큐 성공기록 실패 (주입)")
                return real_done(*a, **k)

            originals = {}
            for name, val in (("collect_document", fake_collect),
                              ("mark_queue_done", done_patch),
                              ("go_to_case_detail", lambda *a, **k: True),
                              ("init_db", lambda: None),
                              ("reset_stale_queue", lambda: None),
                              ("build_download_driver", lambda: object()),
                              ("restart_download_driver", lambda dd: object())):
                originals[name] = getattr(doc_worker, name)
                setattr(doc_worker, name, val)
            orig_sleep = doc_worker.time_module.sleep
            doc_worker.time_module.sleep = lambda *a, **k: None
            os.environ["DOC_WORKER_TEST_MODE"] = "1"
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    doc_worker.main()
            finally:
                for name, val in originals.items():
                    setattr(doc_worker, name, val)
                doc_worker.time_module.sleep = orig_sleep

        def snap():
            c = env.conn()
            try:
                q = c.execute("SELECT status, retry_count FROM document_queue WHERE id=?",
                              (qid,)).fetchone()
                return {
                    "queue": q["status"], "retry": q["retry_count"],
                    "rows": c.execute("SELECT COUNT(*) FROM auction_image").fetchone()[0],
                    "seqs": [r["seq"] for r in c.execute(
                        "SELECT seq FROM auction_image ORDER BY seq")],
                    "status": [r["status"] for r in c.execute(
                        "SELECT status FROM document_status")],
                    "vlog": c.execute(
                        "SELECT COUNT(*) FROM document_version_log").fetchone()[0],
                }
            finally:
                c.close()

        # --- [3] 사진은 기록됐는데 큐 성공기록이 실패한다 (첫 수집이라 previous_hash="")
        run(done_raises=True, previous_hash="")
        got = snap()
        check("[3] 큐는 재시도 대기로 돌아간다", got["queue"], "pending")
        check("[3] 재시도 횟수가 1 올랐다", got["retry"], 1)
        check("[3] ★ 이미 기록된 사진 2행을 잃지 않는다", got["rows"], 2)
        check("[3] ★ 거짓 READY 를 만들지 않는다(화면 상태 없음)", got["status"], [])
        check("[3] 끝나지 않은 실행이 개정 이력을 남기지 않는다", got["vlog"], 0)
        body = TestClient(app_for_tests()).get("/api/v1/item/1").json()
        check("[3] API 사진 수", body["image_count"], 2)
        check("[3] API 상태(실제로 볼 수 있으므로 READY 가 맞다)",
              body["images_status"], "READY")

        # --- [3-b] 재시도 간격 전에는 집어가지 않는다
        before_calls = len(calls)
        run(done_raises=False, previous_hash=set_hash)
        check("[3-b] ★ 재시도 간격 전에는 수집기를 부르지 않는다",
              len(calls) - before_calls, 0)
        check("[3-b] 큐도 그대로", snap()["queue"], "pending")

        # --- [5] 간격이 지난 뒤 재시도: 같은 사진을 다시 기록한다
        c = env.conn()
        try:
            c.execute("UPDATE document_queue SET last_attempt_at=? WHERE id=?",
                      ((_dt.now() - _td(hours=3)).isoformat(), qid))
            c.commit()
        finally:
            c.close()
        run(done_raises=False, previous_hash=set_hash)   # 디스크가 그대로이므로 지문도 같다
        got = snap()
        check("[5] 큐 done", got["queue"], "done")
        check("[5] 화면 READY", got["status"], ["READY"])
        check("[5] ★ 사진 행이 두 벌 쌓이지 않는다", got["rows"], 2)
        check("[5] 순번도 그대로", got["seqs"], [1, 2])
        check("[5] ★ 바이트가 같으면 거짓 개정을 남기지 않는다", got["vlog"], 0)
        check("[5] 디스크에 고아/임시 파일이 없다", sorted(os.listdir(d)),
              ["01.jpg", "02.jpg"])
        body = TestClient(app_for_tests()).get("/api/v1/item/1").json()
        check("[5] API 사진 수", body["image_count"], 2)
        check("[5] API 상태", body["images_status"], "READY")
    finally:
        env.close()


def test_skip_path_records_the_document_it_already_has():
    """"이미 존재. 스킵" 이 **실체 기록까지 건너뛰지는 않는다** (Sprint 217, BUGS #144).

    ## 재현한 상태 (수정 전)

        파일 spec.pdf 는 디스크에 있다
        doc_raw 는 0행이다          (앞선 실행의 mark_queue_done 이 롤백됐다 등)
          -> 재시도가 스킵 분기를 탄다 -> files_saved=[]
          -> mark_queue_done -> _record_doc_raw 가 `if not files_saved: return`
          -> 큐 done / 화면 READY / **doc_raw 0행**
          -> API available=true 인데 page_count/file_size/doc_version 이 **영구 null**

    영구인 이유가 핵심이다 — 다음 수집도 파일이 있으니 **같은 스킵 분기**를 탄다.
    스스로 회복되는 경로가 없다. 사진 쪽은 같은 자리를 이미 복구하고 있었다
    (`image_crawler._describe_existing()`: "파일은 있는데 auction_image 행만 없는
    상태를 여기서 스스로 복구한다"). 문서만 그 복구가 없었다.

    ## 함께 고정하는 것

    - 반복 실행이 **doc_version 을 부풀리지 않는다** (내용이 같으면 새 행 없음, Sprint 187)
    - 바뀐 것이 없으므로 `document_version_log` 에 **거짓 개정을 남기지 않는다**
    - status(파일 2개)는 대표가 **json** 이다 (`_PRIMARY_EXT`)
    - API 가 실제로 쪽수/크기/버전을 답한다 (근거가 DB 가 아니라 응답이다)
    """
    print(chr(10) + "--- 12-I. 스킵 경로도 실체를 기록한다 (Sprint 217) ---")
    from crawler.doc_paths import existing_doc_files

    # (doc_type, 만들 파일들, 대표로 기록돼야 할 파일)
    CASES = [
        ("spec", ["spec.pdf"], "spec.pdf"),
        ("appraisal", ["appraisal.pdf"], "appraisal.pdf"),
        ("status", ["status.html", "status.json"], "status.json"),
    ]

    for doc_type, files, primary in CASES:
        env = Env()
        try:
            court, case_no, item_no = env.seed_item()
            d = os.path.join(env.docs, court, case_no, item_no)
            os.makedirs(d, exist_ok=True)
            for f in files:
                with open(os.path.join(d, f), "wb") as fh:
                    fh.write(b"%PDF-1.4" if f.endswith("pdf") else b"{}")
                    fh.write(b"x" * 300)

            # 헬퍼 자체가 `doc_exists()` 와 같은 목록을 본다.
            got_files = existing_doc_files(court, case_no, item_no, doc_type)
            check("%s: 이미 있는 파일 목록" % doc_type,
                  sorted(os.path.basename(p) for p in got_files), sorted(files))

            # ★ 모르는 종류는 **빈 목록이 아니라 예외**다 (2026-08-24 Sprint 254).
            #
            #   빈 목록을 돌려주면 호출부는 그것을 "파일이 없다"로 읽는다. 그러면
            #   오타 난 doc_type 이 조용히 "아직 안 받은 문서"로 처리되고, 큐는
            #   영원히 같은 자리를 맴돈다. `mark_queue_done()` 이 같은 이유로
            #   `.get()` 대신 `[doc_type]` 을 고집하는 것과 같은 규칙이다
            #   (그 함수 주석: "오타 난 doc_type 이 조용히 성공 처리되어...").
            raised = None
            try:
                existing_doc_files(court, case_no, item_no, "qa-unknown-doc-type")
            except Exception as exc:  # noqa: BLE001 - 예외가 나는 것이 검사 대상이다
                raised = exc
            check("★ 모르는 doc_type 은 예외다(빈 목록으로 조용히 넘기지 않는다)",
                  type(raised).__name__, "ValueError")
            check_true("★ 예외가 가능한 값을 알려 준다(디버깅 가능해야 한다)",
                       "qa-unknown-doc-type" in str(raised) and doc_type in str(raised),
                       str(raised))

            qid = env.enqueue(court, case_no, item_no, doc_type)
            r1 = _run_doc_worker_real_collector(env, court, case_no, item_no, qid)

            check("%s: 스킵이어도 큐는 done" % doc_type, r1["queue"], "done")
            check_true("%s: 화면 READY" % doc_type,
                       ("READY" in [s for _, s in r1["status"]]), r1["status"])
            check("%s: ★ doc_raw 가 1행 남는다(수정 전 0행)" % doc_type,
                  len(r1["raw"]), 1)
            # 앞 단언이 깨져도 **뒤 단언까지 함께 보이도록** 인덱싱하지 않는다 —
            # 변이 주입 때 IndexError 로 죽어 나머지 검사가 가려졌다(그 자체가 맹점이다).
            first = r1["raw"][0] if r1["raw"] else {}
            check("%s: 대표 파일" % doc_type,
                  os.path.basename(first.get("storage_path") or ""), primary)
            check_true("%s: 크기가 실제 파일 크기다" % doc_type,
                       first.get("file_size") == os.path.getsize(
                           os.path.join(d, primary)),
                       first.get("file_size"))
            check("%s: 바뀐 것이 없으니 개정 이력은 0행" % doc_type, r1["version_log"], 0)

            # 두 번째 실행 — 같은 파일, 같은 스킵. 버전이 오르면 안 된다.
            #   큐 행을 새로 만들지 않고 **되돌린다** — migration 018 의
            #   UNIQUE(court,case,item,doc_type) 때문에 같은 항목은 한 행뿐이고,
            #   실제로도 재시도는 그 한 행이 pending 으로 돌아오는 방식이다.
            c = env.conn()
            try:
                c.execute("UPDATE document_queue SET status='pending' WHERE id=?", (qid,))
                c.commit()
            finally:
                c.close()
            r2 = _run_doc_worker_real_collector(env, court, case_no, item_no, qid)
            check("%s: 재실행 후에도 doc_raw 1행(중복 없음)" % doc_type, len(r2["raw"]), 1)
            check("%s: doc_version 유지" % doc_type,
                  (r2["raw"][0]["doc_version"] if r2["raw"] else None), 1)
            check("%s: 재실행이 거짓 개정을 남기지 않는다" % doc_type, r2["version_log"], 0)
        finally:
            env.close()

    # --- API 가 실제로 답하는가 (근거를 DB 가 아니라 응답에 둔다) ---
    from fastapi.testclient import TestClient
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        d = os.path.join(env.docs, court, case_no, item_no)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "spec.pdf"), "wb") as fh:
            fh.write(b"%PDF-1.4" + b"x" * 400)
        qid = env.enqueue(court, case_no, item_no, "spec")
        _run_doc_worker_real_collector(env, court, case_no, item_no, qid)

        from api_server import app
        body = TestClient(app).get("/api/v1/item/1").json()
        spec = next((x for x in body["documents"] if x["doc_type"] == "SPEC"), {})
        check("API: available", spec.get("available"), True)
        check("API: ★ 파일 크기가 null 이 아니다", spec.get("file_size"), 408)
        check("API: ★ doc_version 이 null 이 아니다", spec.get("doc_version"), 1)
    finally:
        env.close()


def test_document_revision_survives_a_queue_write_failure():
    """개정이 **롤백을 건너 살아남는가** — 그리고 무엇은 살아남지 못하는가 (Sprint 217).

    12-J 가 사진에 대해 본 자리를 문서로 옮긴다. 다만 문서에는 사진에 없는 것이 있다 —
    `doc_raw` 의 **버전**이다. 순서를 그대로 흘려보내면 이렇게 된다.

    ```
    1회차  옛 문서 수집            doc_raw v1(H0)
    2회차  법원이 바꿈 -> 재수집    디스크는 H1 이 됐는데 mark_queue_done() 이 실패
                                  -> 트랜잭션 롤백: version_log 0행, doc_raw 는 v1 그대로
    3회차  재시도                  디스크가 이미 H1 이라 수집기가 재는 previous_hash 도 H1
                                  -> `previous_hash == new_hash` -> **개정 이력을 안 남긴다**
                                  -> 그러나 `_record_doc_raw()` 는 자기 마지막 행(H0)과
                                     비교하므로 **v2(H1) 를 제대로 쌓는다**
    ```

    ## 실측 (대조군과 나란히)

    ```
    정상                    queue=done  version_log 1행  doc_raw v1,v2
    큐 기록 실패 후 재시도   queue=done  version_log 0행  doc_raw v1,v2
    ```

    **잃는 것은 `document_version_log` 한 행뿐이고, 바뀌었다는 사실 자체는 `doc_raw`
    가 지킨다.** 그 테이블은 이 저장소에 **제품 독자가 없다**(쓰는 곳은
    `mark_queue_done()` 하나, 읽는 곳은 일회성 리포트 스크립트뿐).

    그래서 여기서 고치지 않는다 — 되살리려면 수집 **전에** 지문을 큐에 적어 둬야 하고,
    그것은 사용자 영향이 0인 이력 한 행을 위해 큐 구조를 바꾸는 일이다.
    대신 **알고 있다는 것을 이 검사로 고정한다.** 나중에 그 테이블에 독자가 생기면
    이 단언이 그때의 결정을 강제한다(0행이 계약인지 결함인지 여기서 다시 정해야 한다).
    """
    print(chr(10) + "--- 12-K. 개정은 롤백을 건너 살아남는가 (Sprint 217) ---")
    from datetime import datetime as _dt, timedelta as _td
    import doc_worker

    def run(env, court, case_no, item_no, content, prev, new, done_raises):
        d = os.path.join(env.docs, court, case_no, item_no)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "spec.pdf")

        def fake_collect(driver, cc, cn, ino, dt, btn, overwrite=False):
            with open(path, "wb") as fh:      # 수집기는 실제로 디스크를 바꾼다
                fh.write(content)
            return {"success": True, "previous_hash": prev, "new_hash": new,
                    "files_saved": [path], "partial": False, "no_asset": False}

        real_done = doc_worker.mark_queue_done

        def done_patch(*a, **k):
            if done_raises:
                raise RuntimeError("큐 성공기록 실패 (주입)")
            return real_done(*a, **k)

        originals = {}
        for name, val in (("collect_document", fake_collect),
                          ("mark_queue_done", done_patch),
                          ("go_to_case_detail", lambda *a, **k: True),
                          ("init_db", lambda: None),
                          ("reset_stale_queue", lambda: None),
                          ("build_download_driver", lambda: object()),
                          ("restart_download_driver", lambda dd: object())):
            originals[name] = getattr(doc_worker, name)
            setattr(doc_worker, name, val)
        orig_sleep = doc_worker.time_module.sleep
        doc_worker.time_module.sleep = lambda *a, **k: None
        os.environ["DOC_WORKER_TEST_MODE"] = "1"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                doc_worker.main()
        finally:
            for name, val in originals.items():
                setattr(doc_worker, name, val)
            doc_worker.time_module.sleep = orig_sleep

    def age(env, qid, status=None):
        c = env.conn()
        try:
            if status:
                c.execute("UPDATE document_queue SET status=?, last_attempt_at=? WHERE id=?",
                          (status, (_dt.now() - _td(hours=3)).isoformat(), qid))
            else:
                c.execute("UPDATE document_queue SET last_attempt_at=? WHERE id=?",
                          ((_dt.now() - _td(hours=3)).isoformat(), qid))
            c.commit()
        finally:
            c.close()

    OLD = b"%PDF-1.4" + b"OLD" * 100
    NEW = b"%PDF-1.4" + b"NEW" * 100
    H0 = hashlib.sha256(OLD).hexdigest()
    H1 = hashlib.sha256(NEW).hexdigest()

    for label, crashed in (("정상(대조군)", False), ("큐 기록 실패 후 재시도", True)):
        env = Env()
        try:
            court, case_no, item_no = env.seed_item()
            qid = env.enqueue(court, case_no, item_no, "spec")
            run(env, court, case_no, item_no, OLD, "", H0, False)      # 1회차
            age(env, qid, "refresh")
            run(env, court, case_no, item_no, NEW, H0, H1, crashed)    # 2회차
            if crashed:
                age(env, qid)
                run(env, court, case_no, item_no, NEW, H1, H1, False)  # 3회차(재시도)

            c = env.conn()
            try:
                q = c.execute("SELECT status FROM document_queue WHERE id=?",
                              (qid,)).fetchone()["status"]
                vlog = c.execute(
                    "SELECT COUNT(*) FROM document_version_log").fetchone()[0]
                raw = [(r["doc_version"], r["file_hash"]) for r in c.execute(
                    "SELECT doc_version, file_hash FROM doc_raw ORDER BY doc_version")]
            finally:
                c.close()

            check("[%s] 큐는 결국 done" % label, q, "done")
            check("[%s] ★ 바뀌었다는 사실은 doc_raw 가 지킨다" % label,
                  [v for v, _h in raw], [1, 2])
            check("[%s] 최신 doc_raw 가 새 내용을 가리킨다" % label,
                  raw[-1][1] if raw else None, H1)
            check("[%s] document_version_log 행 수" % label, vlog, 0 if crashed else 1)
        finally:
            env.close()


def test_document_partial_collection_contract():
    r"""문서 **부분 수집**이 어디서 끝나는가 (Sprint 217, 문서 시나리오 4).

    사진에는 12-G B 가 있다(부분 수집은 계약상 done). 문서에도 같은 계약이 있는데
    그것을 고정한 검사가 없었다. `collect_status()` 의 except 절이 그 경로다 —

        html 은 원본이라 이미 저장됐으면 "부분 성공"으로 처리하고
        재시도 큐에는 남기지 않는다 (json 구조화만 나중에 별도로 재시도하면 되므로)

    ## 이 검사가 고정하는 것

        큐            done          (계약: 부분 성공도 종결이다)
        화면          READY
        doc_raw       1행 — 대표는 **status.html**(json 이 없으니 files_saved[0])
        page_count    None          (html 은 쪽수 개념이 없다. 0 으로 뭉개지 않는다)
        API           available=true + viewer_url
        뷰어 실체     `status.html` 이 **실제로 있다** -> 거짓말이 아니다
        doc_exists()  **False**     (json 이 없으므로 "완성"은 아니다)

    ## 마지막 두 줄이 함께 있는 것이 핵심이다

    큐는 done 인데 `doc_exists()` 는 False 다. 즉 **이 상태는 스스로 끝나지 않는다** —
    재수집(overwrite) 트리거가 걸리기 전까지 json 은 영원히 없다. 그것이 결함인지
    계약인지는 제품 판단이라 여기서 정하지 않는다(재시도를 켜면 정책 변경이다).
    대신 **상태가 그렇다는 사실을 코드로 고정**한다.

    운영 실측(2026-08-19): STATUS 1,876행 중 html-only 는 **0건**이다.
    지금 터져 있는 상태가 아니라, 도달 가능한 경로를 잠가 두는 것이다.
    """
    print(chr(10) + "--- 12-L. 문서 부분 수집의 계약 (Sprint 217) ---")
    from crawler.doc_paths import doc_exists
    from fastapi.testclient import TestClient
    import doc_worker

    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        qid = env.enqueue(court, case_no, item_no, "status")
        d = os.path.join(env.docs, court, case_no, item_no)
        os.makedirs(d, exist_ok=True)
        html_path = os.path.join(d, "status.html")
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write("<div>2024타경1 조사일시 2026-08-19</div>")

        def fake_collect(driver, cc, cn, ino, dt, btn, overwrite=False):
            # `collect_status()` 의 except 절이 돌려주는 모양 그대로
            return {"success": True, "partial": True, "no_asset": False,
                    "files_saved": [html_path], "previous_hash": "",
                    "new_hash": "h-html"}

        originals = {}
        for name, val in (("collect_document", fake_collect),
                          ("go_to_case_detail", lambda *a, **k: True),
                          ("init_db", lambda: None),
                          ("reset_stale_queue", lambda: None),
                          ("build_download_driver", lambda: object()),
                          ("restart_download_driver", lambda dd: object())):
            originals[name] = getattr(doc_worker, name)
            setattr(doc_worker, name, val)
        orig_sleep = doc_worker.time_module.sleep
        doc_worker.time_module.sleep = lambda *a, **k: None
        os.environ["DOC_WORKER_TEST_MODE"] = "1"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                doc_worker.main()
        finally:
            for name, val in originals.items():
                setattr(doc_worker, name, val)
            doc_worker.time_module.sleep = orig_sleep

        c = env.conn()
        try:
            q = c.execute("SELECT status FROM document_queue WHERE id=?",
                          (qid,)).fetchone()["status"]
            st = [(r["doc_type"], r["status"]) for r in
                  c.execute("SELECT doc_type,status FROM document_status")]
            raw = [dict(r) for r in c.execute(
                "SELECT doc_type, storage_path, page_count FROM doc_raw")]
        finally:
            c.close()

        check("부분 수집도 큐에서는 종결된다(계약)", q, "done")
        check("화면 상태", st, [("STATUS", "READY")])
        check("doc_raw 1행", len(raw), 1)
        check("대표 파일은 html(json 이 없으므로)",
              os.path.basename(raw[0]["storage_path"]) if raw else None, "status.html")
        check("html 에는 쪽수가 없다(0 으로 뭉개지 않는다)",
              raw[0]["page_count"] if raw else "no-row", None)
        check_true("★ 큐는 done 인데 doc_exists() 는 False 다(스스로 끝나지 않는 상태)",
                   not doc_exists(court, case_no, item_no, "status"), "doc_exists=True")

        body = TestClient(app_for_tests()).get("/api/v1/item/1").json()
        entry = next((x for x in body["documents"] if x["doc_type"] == "STATUS"), {})
        check("API available", entry.get("available"), True)
        check("API viewer_url", entry.get("viewer_url"),
              "/api/v1/item/1/documents/STATUS")
        # ★ available=true 가 **거짓말이 아닌지** 실제로 열어 본다.
        r = TestClient(app_for_tests()).get("/api/v1/item/1/documents/STATUS")
        check("뷰어가 실제로 200 을 준다(available 이 거짓말이 아니다)", r.status_code, 200)
    finally:
        env.close()

def test_court_removed_photos_end_to_end_through_the_worker():
    r"""법원이 사진을 전부 내린 경우를 **doc_worker 로 관통**한다 (Sprint 217).

    ## 5-H 와 무엇이 다른가

    5-H 는 `clear_images_if_absence_confirmed()` 를 **직접** 부르고, 그 뒤에 오는
    `mark_queue_done(status=NO_IMAGE)` 는 손으로 흉내 냈다("그 효과를 재현").
    즉 저장소 계층의 규칙은 고정했지만 **호출부가 그 규칙을 실제로 쓰는지**는
    코드를 읽어서만 알 수 있었다. 이 저장소가 반복해 구분해 온 것이 정확히 그 둘이다 —

        함수가 있다  !=  호출된다  !=  올바른 순서로 호출된다

    여기서는 `doc_worker.main()` 을 세 번 돌린다. 대역은 수집기 하나뿐이다.

    ## 순서가 결과를 바꾼다

    `clear_images_if_absence_confirmed()` 는 **1회차인지 2회차인지를
    `document_status` 로 판단한다.** 그런데 `mark_queue_done()` 이 그 값을
    `NO_IMAGE` 로 덮는다. 그래서 정리는 **반드시 mark_queue_done 보다 먼저** 와야 한다.
    순서가 뒤집히면 **1회차에 곧바로 지운다** — 한 번의 관측 실패로 사용자가 보던
    사진이 전부 사라지는, 이 파이프라인에서 가장 파괴적인 동작이다.

    **변이로 실제로 확인했다**(추측이 아니다). 정리 블록을 `mark_queue_done()` 뒤로
    옮기면 1회차에서 이 검사가 운다:

        [1회차] 사진 3행을 지우지 않는다   0  (기대 3)
        [1회차] 파일도 그대로              [] (기대 3개)
        [1회차] API 는 아직 3장을 준다      0  (기대 3)

    호출을 아예 없애면 2회차에서 운다(FAIL 6건).
    """
    print(chr(10) + "--- 12-M. 사진 전부 내림: worker 관통 2회 확인 (Sprint 217) ---")
    from datetime import datetime as _dt, timedelta as _td
    from fastapi.testclient import TestClient
    from storage.database import save_auction_images
    import doc_worker

    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        qid = env.enqueue(court, case_no, item_no, "image")
        d = os.path.join(env.docs, court, case_no, item_no, "images")
        os.makedirs(d)
        olds = []
        for i in (1, 2, 3):
            path = os.path.join(d, "%02d.jpg" % i)
            with open(path, "wb") as fh:
                fh.write(make_jpeg(pad=MIN_FIXTURE_PAD + 32 * i))
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            olds.append({"seq": i, "kind": "전경도", "path": path,
                         "file_size": os.path.getsize(path), "file_hash": digest,
                         "width": 1, "height": 1})
        save_auction_images(court, case_no, item_no, olds, complete=True)
        c = env.conn()
        try:
            c.execute("INSERT INTO document_status (item_id, doc_type, status)"
                      " VALUES (1,'IMAGE','READY')")
            c.commit()
        finally:
            c.close()

        def fake_collect(driver, cc, cn, ino, dt, btn, overwrite=False):
            # `collect_images()` 가 사진 요소를 하나도 못 찾았을 때의 반환 모양
            return {"success": True, "no_asset": True, "images": [], "files_saved": [],
                    "partial": False, "previous_hash": "", "new_hash": ""}

        def run():
            originals = {}
            for name, val in (("collect_document", fake_collect),
                              ("go_to_case_detail", lambda *a, **k: True),
                              ("init_db", lambda: None),
                              ("reset_stale_queue", lambda: None),
                              ("build_download_driver", lambda: object()),
                              ("restart_download_driver", lambda dd: object())):
                originals[name] = getattr(doc_worker, name)
                setattr(doc_worker, name, val)
            orig_sleep = doc_worker.time_module.sleep
            doc_worker.time_module.sleep = lambda *a, **k: None
            os.environ["DOC_WORKER_TEST_MODE"] = "1"
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    doc_worker.main()
            finally:
                for name, val in originals.items():
                    setattr(doc_worker, name, val)
                doc_worker.time_module.sleep = orig_sleep

        def requeue():
            cc = env.conn()
            try:
                cc.execute("UPDATE document_queue SET status='pending', last_attempt_at=?"
                           " WHERE id=?", ((_dt.now() - _td(hours=3)).isoformat(), qid))
                cc.commit()
            finally:
                cc.close()

        def snap():
            files = sorted(os.listdir(d)) if os.path.isdir(d) else []
            cc = env.conn()
            try:
                q = cc.execute("SELECT status FROM document_queue WHERE id=?",
                               (qid,)).fetchone()["status"]
            finally:
                cc.close()
            return {"queue": q, "rows": len(env.images_of(1)), "files": files,
                    "status": env.status_of(1, "IMAGE")}

        # --- 1회차: 상태만 바뀌고 사진은 남는다
        run()
        got = snap()
        check("[1회차] 큐 done(실패가 아니다 - 재시도해도 같다)", got["queue"], "done")
        check("[1회차] 화면 상태 NO_IMAGE", got["status"], "NO_IMAGE")
        check("[1회차] ★ 사진 3행을 지우지 않는다", got["rows"], 3)
        check("[1회차] 파일도 그대로", got["files"], ["01.jpg", "02.jpg", "03.jpg"])
        body = TestClient(app_for_tests()).get("/api/v1/item/1").json()
        check("[1회차] API 는 아직 3장을 준다", body["image_count"], 3)
        check("[1회차] 볼 수 있으므로 READY", body["images_status"], "READY")

        # --- 2회차: 같은 관측이 한 번 더 -> 그때 정리한다
        requeue()
        run()
        got = snap()
        check("[2회차] 큐 done", got["queue"], "done")
        check("[2회차] ★ 사진 행이 정리된다", got["rows"], 0)
        check("[2회차] ★ 파일도 정리된다(고아 파일 없음)", got["files"], [])
        check("[2회차] 화면 상태 NO_IMAGE", got["status"], "NO_IMAGE")
        body = TestClient(app_for_tests()).get("/api/v1/item/1").json()
        check("[2회차] API 사진 0장", body["image_count"], 0)
        check("[2회차] ★ 없는 사진을 READY 라고 하지 않는다",
              body["images_status"], "NO_IMAGE")
        check("[2회차] 대표 이미지도 없다", body["representative_image"], None)

        # --- 3회차: 이미 비었으면 아무 일도 일어나지 않는다
        requeue()
        run()
        got = snap()
        check("[3회차] 아무 일도 없다", (got["queue"], got["rows"], got["status"]),
              ("done", 0, "NO_IMAGE"))
    finally:
        env.close()


def test_list_and_detail_show_the_same_photo():
    r"""검색목록 썸네일과 상세페이지 대표 사진이 **같은 것을 가리키는가** (Sprint 218).

    ## 왜 따로 봐야 하나

    두 화면은 **서로 다른 코드**로 대표 사진을 고른다.

        검색목록   api/v1/search.py    `SELECT item_id, MIN(seq) ... GROUP BY item_id`
        상세페이지 api/v1/item.py      `ORDER BY seq` 로 읽어 `images[0]`

    같은 규칙("가장 앞선 순번")을 **두 벌로 구현**한 것이다. 이 저장소가 반복해 겪은
    모양이고(BUGS #107/#112/#136/#161), 한쪽만 바뀌면 **목록과 상세가 다른 사진을
    보여 준다** — 사용자에게는 "클릭했더니 다른 집이 나온다"로 보인다.

    16번은 상세만, 17번은 목록만 본다. **둘을 나란히 놓고 대조한 검사는 없었다.**

    ## 함께 보는 것

        물건 ID 혼선     A 의 썸네일이 B 를 가리키지 않는가 (순번이 서로 다른 두 물건)
        사진 없는 물건    깨진 이미지가 아니라 **키는 있고 값이 null**
        실제 서빙        목록이 준 URL 과 상세가 준 URL 이 **같은 바이트**를 준다
        목록 견고성      DB 행이 가리키는 파일이 사라져도 **목록 자체는 200**
    """
    print(chr(10) + "--- 12-N. 목록 썸네일 == 상세 대표 사진 (Sprint 218) ---")
    from fastapi.testclient import TestClient
    from storage.database import save_auction_images

    env = Env()
    try:
        # 순번을 일부러 어긋나게 만든다 — A 는 2,3 / B 는 1,4 / C 는 사진 없음.
        # 두 구현이 각자 "가장 앞선 순번"을 고르지 않으면 여기서 갈라진다.
        court = "서울중앙지방법원"
        seeded = {}
        c = env.conn()
        try:
            case_id = c.execute(
                "INSERT INTO auction_case (court_code, case_no) VALUES (?,?)",
                (court, "2024타경100")).lastrowid
            for item_id, item_no in ((1, "1"), (2, "2"), (3, "3")):
                c.execute("INSERT INTO auction_item"
                          " (id,case_id,court_name,case_no,item_no,auction_date)"
                          " VALUES (?,?,?,?,?,?)",
                          (item_id, case_id, court, "2024타경100", item_no, "2099-01-01"))
            c.commit()
        finally:
            c.close()

        for item_id, item_no, seqs in ((1, "1", (2, 3)), (2, "2", (1, 4))):
            d = os.path.join(env.docs, court, "2024타경100", item_no, "images")
            os.makedirs(d)
            payload = []
            for seq in seqs:
                path = os.path.join(d, "%02d.jpg" % seq)
                # 물건마다 다른 바이트 — 섞이면 크기로 드러난다.
                # pad 는 MIN_IMAGE_BYTES(1,024) 를 넉넉히 넘겨야 한다 —
                # 그 아래는 저장 계층이 아예 기록하지 않는다(BUGS #148).
                with open(path, "wb") as fh:
                    fh.write(make_jpeg(pad=4096 + 100 * item_id + seq))
                with open(path, "rb") as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()
                payload.append({"seq": seq, "kind": "전경도", "path": path,
                                "file_size": os.path.getsize(path),
                                "file_hash": digest, "width": 1, "height": 1})
            save_auction_images(court, "2024타경100", item_no, payload, complete=True)
            seeded[item_id] = payload

        client = TestClient(app_for_tests())

        # --- 목록
        r = client.get("/api/v1/search?include_closed=true&size=50")
        check("검색 200", r.status_code, 200)
        items = {it["id"]: it for it in r.json()["items"]}
        check("세 물건이 모두 목록에 있다", sorted(items), [1, 2, 3])

        check("A(순번 2,3) 의 대표는 2", items[1]["thumbnail_url"],
              "/api/v1/item/1/images/2")
        check("B(순번 1,4) 의 대표는 1", items[2]["thumbnail_url"],
              "/api/v1/item/2/images/1")
        check("사진 없는 물건은 null(키는 있다)", items[3]["thumbnail_url"], None)
        check_true("★ 썸네일 URL 이 자기 물건 id 를 가리킨다",
                   all(items[i]["thumbnail_url"].split("/")[4] == str(i)
                       for i in (1, 2)),
                   {i: items[i]["thumbnail_url"] for i in (1, 2)})

        # --- 상세와 대조
        for item_id in (1, 2):
            body = client.get("/api/v1/item/%d" % item_id).json()
            rep = body["representative_image"]
            check("[물건 %d] ★ 목록 썸네일 == 상세 대표 사진" % item_id,
                  items[item_id]["thumbnail_url"], rep["url"])
            check("[물건 %d] 상세 대표도 thumbnail_url 과 같다" % item_id,
                  rep["thumbnail_url"], items[item_id]["thumbnail_url"])

        detail3 = client.get("/api/v1/item/3").json()
        check("사진 없는 물건은 상세에도 대표가 없다",
              detail3["representative_image"], None)
        check("사진 없는 물건의 상태는 COLLECTING(아직 안 해 본 것)",
              detail3["images_status"], "COLLECTING")

        # --- 두 URL 이 정말 같은 바이트를 주는가
        for item_id in (1, 2):
            a = client.get(items[item_id]["thumbnail_url"])
            b = client.get(client.get("/api/v1/item/%d" % item_id)
                           .json()["representative_image"]["url"])
            check("[물건 %d] 목록 URL 서빙 200" % item_id, a.status_code, 200)
            check("[물건 %d] ★ 목록과 상세가 같은 바이트" % item_id,
                  a.content == b.content, True)
            check("[물건 %d] 다른 물건의 바이트가 아니다" % item_id,
                  len(a.content), seeded[item_id][0]["file_size"])

        # --- 목록 견고성: DB 는 있는데 파일이 사라져도 목록 자체는 살아 있어야 한다
        os.remove(seeded[1][0]["path"])
        r = client.get("/api/v1/search?include_closed=true&size=50")
        check("★ 파일이 사라져도 검색 목록은 200", r.status_code, 200)
        gone = {it["id"]: it for it in r.json()["items"]}
        check("URL 자체는 그대로 준다(프런트가 onError 로 감춘다)",
              gone[1]["thumbnail_url"], "/api/v1/item/1/images/2")
        check("그 URL 은 404 다(200 으로 거짓말하지 않는다)",
              client.get(gone[1]["thumbnail_url"]).status_code, 404)
        check("다른 물건은 영향을 받지 않는다",
              client.get(gone[2]["thumbnail_url"]).status_code, 200)
    finally:
        env.close()


def test_list_thumbnail_reflects_a_changed_photo():
    r"""사진이 바뀌면 **검색목록도 새 사진을 보여 주는가** (Sprint 218).

    URL 은 `/images/{순번}` 이라 사진이 교체돼도 **주소가 바뀌지 않는다.**
    그래서 "목록이 최신을 보여 주는가"는 전적으로 **조건부 캐시**에 달려 있다.

        같은 바이트   -> ETag 동일 -> 304, 브라우저는 캐시를 재사용한다 (아끼는 것)
        바뀐 바이트   -> ETag 변경 -> 200 + 새 바이트 (보여 줘야 하는 것)

    두 번째가 깨지면 사용자는 **옛 사진을 영원히 본다.** 그리고 그 상태는
    "정상 캐시 적중"과 화면상 구별되지 않는다.

    ETag 는 Starlette 가 (mtime, size) 로 만든다. 그래서 **크기가 같은 다른 사진**으로
    바꿔 본다 — 크기만 보는 구현이면 여기서 잡힌다.
    """
    print(chr(10) + "--- 12-O. 사진 교체가 목록에 반영되는가 (Sprint 218) ---")
    from fastapi.testclient import TestClient
    from storage.database import save_auction_images

    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        d = os.path.join(env.docs, court, case_no, item_no, "images")
        os.makedirs(d)
        path = os.path.join(d, "01.jpg")
        first = make_jpeg(width=100, height=200, pad=4096)
        with open(path, "wb") as fh:
            fh.write(first)
        save_auction_images(court, case_no, item_no, [{
            "seq": 1, "kind": "전경도", "path": path,
            "file_size": os.path.getsize(path),
            "file_hash": hashlib.sha256(first).hexdigest(),
            "width": 100, "height": 200}], complete=True)

        client = TestClient(app_for_tests())
        url = "/api/v1/item/1/images/1"

        r1 = client.get(url)
        check("첫 요청 200", r1.status_code, 200)
        etag1 = r1.headers.get("etag")
        check_true("ETag 가 있다", bool(etag1), r1.headers)

        # --- 바뀌지 않았으면 304 (캐시를 아낀다)
        r2 = client.get(url, headers={"If-None-Match": etag1})
        check("내용이 그대로면 304", r2.status_code, 304)
        check("304 는 바이트를 보내지 않는다", len(r2.content), 0)

        # --- 같은 **크기**의 다른 사진으로 교체한다
        second = make_jpeg(width=300, height=400, pad=4096)
        check("교체본은 크기가 같다(크기만 보는 구현을 걸러낸다)",
              len(second), len(first))
        check_true("교체본은 내용이 다르다", second != first)
        time.sleep(0.01)
        with open(path, "wb") as fh:
            fh.write(second)

        r3 = client.get(url, headers={"If-None-Match": etag1})
        check("★ 사진이 바뀌면 304 가 아니라 200 이다", r3.status_code, 200)
        check("★ 새 바이트를 준다", r3.content == second, True)
        etag2 = r3.headers.get("etag")
        check_true("★ ETag 도 바뀐다(옛 캐시가 무효화된다)", etag1 != etag2,
                   (etag1, etag2))

        # --- 목록이 주는 URL 도 같은 자리를 가리킨다(주소는 안 바뀐다)
        s = client.get("/api/v1/search?include_closed=true").json()["items"]
        me = next(it for it in s if it["id"] == 1)
        check("목록 URL 은 그대로다(교체돼도 주소는 안 바뀐다)",
              me["thumbnail_url"], url)
        check("목록 URL 을 다시 받으면 새 사진이다",
              client.get(me["thumbnail_url"]).content == second, True)
    finally:
        env.close()


def test_recorded_photo_is_always_servable():
    r"""기록된 사진은 **반드시 서빙될 수 있어야** 한다 (Sprint 218, BUGS #148).

    ## 발견 경위

    검색목록 썸네일 관통 검사를 쓰다가 서빙이 404 를 냈다. 원인은 픽스처의 사진이
    작아서였는데, 그 과정에서 **저장 계층과 서빙 계층의 "있다" 기준이 다르다**는
    것이 드러났다.

        save_auction_images()          size <= 0 만 거절        <- 행을 만드는 곳
        image_exists()                 >= MIN_IMAGE_BYTES
        api/v1/images.py (서빙)         >= MIN_IMAGE_BYTES

    즉 1~1,023바이트 파일은 이렇게 끝났다(실측 재현):

        auction_image 1행  ->  API image_count=1 / images_status=READY
                           ->  검색목록도 그 URL 을 썸네일로 준다
                           ->  그 URL 은 **404**

    `image_exists()` 의 docstring 이 이미 규약을 적어 두고 있었다 —
    *"쓰는 쪽과 읽는 쪽의 '있다' 정의가 갈라지면 화면은 READY 인데 뷰어는 404 가 된다"*.
    정작 **행을 만드는 함수만** 그 규약 밖에 있었다.

    ## 운영 영향

    실측(2026-08-19): `auction_image` 45행의 최소 크기 **35,746바이트** — 영향 0건.
    수집기가 이미 같은 하한으로 걸러내므로 정상 경로로는 도달하지 않는다.
    막는 것은 잘린 파일 · 수동 조작 · 옛 backfill 이 남길 수 있는 행이다.

    ## 이 검사가 고정하는 것

        저장       하한 미만은 기록하지 않는다(`skipped_missing` 으로 센다)
        API        기록이 없으므로 image_count=0, 대표 없음, 목록 썸네일 null
        기준 일치   세 곳이 **같은 상수**를 본다 (규칙이 두 벌이 되지 않게)
    """
    print(chr(10) + "--- 12-P. 기록된 사진은 서빙될 수 있어야 한다 (Sprint 218) ---")
    from fastapi.testclient import TestClient
    from storage.database import save_auction_images
    from crawler.image_assets import MIN_IMAGE_BYTES, image_exists

    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        d = os.path.join(env.docs, court, case_no, item_no, "images")
        os.makedirs(d)

        def record(seq, nbytes):
            path = os.path.join(d, "%02d.jpg" % seq)
            data = make_jpeg(pad=max(0, nbytes - 60))
            with open(path, "wb") as fh:
                fh.write(data)
            return path, save_auction_images(court, case_no, item_no, [{
                "seq": seq, "kind": "전경도", "path": path,
                "file_size": os.path.getsize(path),
                "file_hash": hashlib.sha256(data).hexdigest(),
                "width": 1, "height": 1}], complete=False)

        # --- 하한 미만
        small_path, stat = record(1, 300)
        check_true("픽스처가 실제로 하한 미만이다",
                   os.path.getsize(small_path) < MIN_IMAGE_BYTES,
                   os.path.getsize(small_path))
        check("★ 하한 미만은 기록하지 않는다", stat["saved"], 0)
        check("건너뛴 것으로 센다(조용히 사라지지 않는다)", stat["skipped_missing"], 1)
        check("auction_image 행이 없다", len(env.images_of(1)), 0)
        check("image_exists() 도 없다고 답한다",
              image_exists(court, case_no, item_no, 1, "jpg"), False)

        client = TestClient(app_for_tests())
        body = client.get("/api/v1/item/1").json()
        check("API 사진 0장", body["image_count"], 0)
        check("대표 이미지 없음", body["representative_image"], None)
        check("★ 없는 사진을 READY 라고 하지 않는다", body["images_status"], "COLLECTING")
        listed = client.get("/api/v1/search?include_closed=true").json()["items"]
        me = next((it for it in listed if it["id"] == 1), None)
        check_true("검색 목록에 물건은 나온다", me is not None, listed)
        check("★ 목록 썸네일도 null(깨진 자리를 만들지 않는다)",
              (me or {}).get("thumbnail_url"), None)

        # --- 하한 이상은 그대로 기록되고 실제로 서빙된다 (대조군)
        big_path, stat2 = record(2, MIN_IMAGE_BYTES * 3)
        check("대조군: 하한 이상은 기록된다", stat2["saved"], 1)
        body = client.get("/api/v1/item/1").json()
        check("대조군: API 1장", body["image_count"], 1)
        rep = body["representative_image"]
        check("대조군: 대표는 순번 2", rep["seq"], 2)
        r = client.get(rep["url"])
        check("★ 대조군: 기록된 사진은 실제로 서빙된다", r.status_code, 200)
        check("바이트가 파일과 같다", len(r.content), os.path.getsize(big_path))
        listed = client.get("/api/v1/search?include_closed=true").json()["items"]
        me = next(it for it in listed if it["id"] == 1)
        check("대조군: 목록 썸네일도 그 사진", me["thumbnail_url"], rep["url"])
    finally:
        env.close()


def test_existence_rule_is_single_sourced():
    r"""사진이 "있다"를 판정하는 **모든 자리가 같은 상수**를 보는가 (Sprint 218).

    12-P 가 시나리오를 잡는다면 이 검사는 **모양**을 잡는다. 판정처가 셋이다:

        storage/database.py  save_auction_images()   행을 만든다
        crawler/image_assets.py  image_exists()      수집기가 "이미 있다"를 판단한다
        api/v1/images.py                              사용자에게 내준다

    셋 중 하나만 느슨해지면 "화면은 있다는데 열면 404" 가 돌아온다.
    숫자를 각자 적어 두면 언젠가 갈라지므로 **상수 이름**을 참조하는지 본다.
    (`test_false_success.py` 4 가 문서 쪽에서 이미 같은 방식으로 지키고 있다.)
    """
    print(chr(10) + "--- 12-Q. 사진 '있다' 기준의 단일화 (Sprint 218) ---")
    import ast

    root = os.path.dirname(os.path.abspath(__file__))
    SOURCE_MODULE = "crawler.image_assets"
    DECIDERS = [
        (os.path.join("storage", "database.py"), "save_auction_images"),
        (os.path.join("crawler", "image_assets.py"), "image_exists"),
        (os.path.join("api", "v1", "images.py"), "get_item_image"),
    ]

    def func_node(tree, name):
        for n in ast.walk(tree):
            if isinstance(n, ast.FunctionDef) and n.name == name:
                return n
        return None

    for rel, fname in DECIDERS:
        path = os.path.join(root, rel)
        tree = ast.parse(open(path, encoding="utf-8-sig").read(), filename=path)
        fn = func_node(tree, fname)
        check_true("%s:%s 를 찾았다" % (rel, fname), fn is not None, fname)
        if fn is None:
            continue
        body = ast.unparse(fn)
        check_true("%s:%s 가 MIN_IMAGE_BYTES 를 쓴다" % (rel, fname),
                   "MIN_IMAGE_BYTES" in body,
                   "숫자를 따로 적으면 언젠가 갈라진다")

        # ★ **이름만 같고 값을 따로 적는** 복제를 잡는다 (2026-08-19 Sprint 218).
        #   처음 쓴 이 검사는 문자열 포함만 봤고, 변이(`_MIN_IMAGE_BYTES = 1024` 를
        #   함수 안에 박음)가 **그대로 통과했다.** 부분 문자열이 이름을 덮었기 때문이다.
        #   숫자로 정의하는 대입이 있으면 그 자체가 규칙 이중화다.
        literal_defs = []
        for n in ast.walk(fn):
            if not isinstance(n, ast.Assign) or len(n.targets) != 1:
                continue
            target = n.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if "MIN_IMAGE_BYTES" not in target.id:
                continue
            if isinstance(n.value, ast.Constant):
                literal_defs.append("%s = %r" % (target.id, n.value.value))
        check("%s:%s 안에서 하한을 숫자로 다시 정의하지 않는다" % (rel, fname),
              literal_defs, [])

        # 그 이름이 **단일 소스에서 왔는가** — 모듈 최상단이든 함수 안이든
        # `crawler.image_assets` 에서 import 한 흔적이 있어야 한다.
        imported = False
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and (n.module or "") == SOURCE_MODULE:
                if any(a.name == "MIN_IMAGE_BYTES" for a in n.names):
                    imported = True
                    break
        own = rel.replace(os.sep, "/").endswith("crawler/image_assets.py")
        check_true("%s 의 하한이 단일 소스(%s)에서 온다" % (rel, SOURCE_MODULE),
                   own or imported,
                   "import 흔적이 없다 - 값을 따로 들고 있을 가능성")

    # 상수가 실제로 하나인지(재정의가 없는지) 확인한다.
    import crawler.image_assets as ia
    defs = [l for l in open(os.path.join(root, "crawler", "image_assets.py"),
                            encoding="utf-8-sig").read().splitlines()
            if l.startswith("MIN_IMAGE_BYTES")]
    check("상수 정의는 한 곳뿐", len(defs), 1)
    check_true("상수 값이 양수다", ia.MIN_IMAGE_BYTES > 0, ia.MIN_IMAGE_BYTES)
    print("    MIN_IMAGE_BYTES = %d / 판정처 %d곳" % (ia.MIN_IMAGE_BYTES, len(DECIDERS)))


def test_download_of_another_case_is_refused():
    """내려받은 파일이 **다른 사건의 것**이면 저장하지 않는다 (2026-08-20 Sprint 228).

    ## 어떻게 남의 파일이 들어오는가

    `wait_for_download()` 는 "다운로드 폴더에 **새로 생긴** PDF" 를 집는다.
    어느 사건의 것인지는 보지 않는다. 그래서 이런 순서가 가능하다.

        1. 사건 A 수집 -> 30초 안에 안 옴 -> 포기(타임아웃). 다운로드는 계속 진행 중
        2. 사건 B 수집 시작 -> before_files 스냅샷 (A 의 것은 아직 .crdownload)
        3. A 의 다운로드 완료 -> A.pdf 가 생긴다 = **새 파일**
        4. wait_for_download() 가 그것을 집는다 -> **A 의 문서가 B 로 저장된다**

    타임아웃은 실제로 일어난다 - `docs/SPRINT199` 가 실행 중에 겪었고,
    `downloads/` 의 고아 파일 8개가 그 흔적이다(그중 5개는 같은 파일이 4번 쌓였다).

    ## 왜 결과 검사로는 절대 안 잡히나

    저장된 것은 **진짜 PDF** 다. 크기도 정상이고 해시도 계산되고 상태는 READY 가 된다.
    화면에서도 정상으로 보인다. 사용자는 **다른 사건의 매각물건명세서를 보고 입찰을
    판단하게 된다.** 그래서 파일이 들어오는 **입구**에서 막아야 한다.

    ## 판정 규칙 (확실할 때만 막는다)

        파일명에 사건번호가 있다 + 다르다  -> 거부
        파일명에 사건번호가 있다 + 같다    -> 통과
        파일명에 사건번호가 없다           -> 통과 (감정평가서는 업체 코드라 없다)
    """
    print("\n--- 21. 남의 사건 파일을 저장하지 않는다 (Sprint 228) ---")
    from crawler.doc_crawler import (
        downloaded_file_case_no,
        downloaded_file_belongs_to_case,
    )

    # 실측 근거: downloads/ 에 실제로 남아 있던 고아 파일들의 이름 (2026-08-20)
    SPEC_A = "2023타경103287_2026.06.17_매각물건명세서(재작성,6)_참여_김윤회.pdf"
    SPEC_B = "2023타경118942_2026.06.16_매각물건명세서(재작성,1)_참여_오해주.pdf"
    SPEC_B_DUP = "2023타경118942_2026.06.16_매각물건명세서(재작성,1)_참여_오해주 (3).pdf"
    APPRAISAL = "HR2025-0609-0001.pdf"        # 업체 코드 - 사건번호가 없다

    check("실제 파일명에서 사건번호를 뽑는다", downloaded_file_case_no(SPEC_A), "2023타경103287")
    check("Chrome 이 붙인 ' (3)' 중복 접미사에도 뽑힌다",
          downloaded_file_case_no(SPEC_B_DUP), "2023타경118942")
    check("사건번호가 없는 파일명은 None", downloaded_file_case_no(APPRAISAL), None)

    # ★ 핵심 - 남의 사건 파일은 거부
    check("★ 다른 사건의 파일은 거부한다",
          downloaded_file_belongs_to_case(SPEC_A, "2023타경118942"), False)
    check("같은 사건의 파일은 통과한다",
          downloaded_file_belongs_to_case(SPEC_A, "2023타경103287"), True)
    check("중복 접미사가 붙어도 같은 사건이면 통과",
          downloaded_file_belongs_to_case(SPEC_B_DUP, "2023타경118942"), True)

    # 판단 근거가 없으면 막지 않는다 - "없으면 거부"로 만들면 감정평가서가 전부 막힌다
    check("사건번호가 없는 파일명은 막지 않는다(모르는 것은 막지 않는다)",
          downloaded_file_belongs_to_case(APPRAISAL, "2023타경118942"), True)

    # 병합 사건 - 구성요소 각각과 정확히 비교 (실측 22.7%)
    merged = "2008타경25092 / 2015타경19958"
    check("병합 사건의 앞쪽과 일치하면 통과",
          downloaded_file_belongs_to_case("2008타경25092_x.pdf", merged), True)
    check("병합 사건의 뒤쪽과 일치해도 통과",
          downloaded_file_belongs_to_case("2015타경19958_x.pdf", merged), True)
    check("병합 사건 어느 쪽과도 다르면 거부",
          downloaded_file_belongs_to_case("2024타경1_x.pdf", merged), False)

    # ★ 부분 문자열 함정 - 이 저장소가 이미 두 번 당한 자리
    check("★ 접두 부분 문자열을 같은 사건으로 보지 않는다",
          downloaded_file_belongs_to_case("2024타경100920_x.pdf", "2024타경1009"), False)
    check("★ 반대 방향도 마찬가지",
          downloaded_file_belongs_to_case("2024타경1009_x.pdf", "2024타경100920"), False)

    # 경로가 섞여 들어와도 파일명만 본다
    check("디렉터리 경로에 든 사건번호에 속지 않는다",
          downloaded_file_case_no(os.path.join("2024타경999", APPRAISAL)), None)

    # 방어선이 실제로 배선돼 있는가 - 함수만 있고 안 쓰면 아무 일도 안 일어난다
    src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "crawler", "doc_crawler.py"), encoding="utf-8-sig").read()
    wired = src.count("if not downloaded_file_belongs_to_case(")
    check("★ 두 다운로드 경로(spec/appraisal)에 전부 배선돼 있다", wired, 2)


def test_photos_are_not_taken_from_the_wrong_item():
    """물건번호를 특정하지 못하면 **사진은 수집하지 않는다** (2026-08-20 Sprint 230).

    ## 왜 사진만 다른가

    `crawler/base_crawler.py:go_to_case_detail()` 의 docstring 이 이미 적어 두었다 —

        문서(spec/appraisal)  버튼 id 에 물건번호가 붙어 있어 어느 물건의 페이지에서
                              눌러도 그 물건의 문서가 나온다(실측: 다중물건 22건에서
                              서로 다른 물건이 같은 바이트인 경우 0건)
        사진(image)           **버튼이 없다.** 상세페이지에 그려진 캐러셀을 그대로 읽는다
                              -> 물건이 틀리면 사진도 틀린다

    ## 무엇이 문제였나

    목록에서 그 물건 행을 못 찾으면 코드는 `logger.warning` 만 남기고
    **첫 일치 항목으로 진행**했다. 경고는 아무도 읽지 않고, 저장된 사진은 진짜 사진이라
    `audit_asset_integrity.py` 의 어떤 항목에도 걸리지 않는다.
    사용자는 **다른 물건의 사진**을 보게 된다.

    (2026-08-17 실측 기록: 2025타경311 은 물건 1과 2의 사진이 실제로 같았다 —
     같은 건물이라 법원이 같은 전경도를 준다. 즉 그 표본에서는 **우연히** 결과가 같았을 뿐이다.)

    ## 그렇다고 항상 거부하지는 않는다

    목록의 물건번호 표기가 조금만 달라져도 사진 수집이 통째로 멈추면 안 된다.
    **모호할 때만** 거부한다.

        후보가 1개                -> 모호하지 않다. 그대로 진행
        후보 여러 개 + 정확 일치   -> 그 행으로 진행
        후보 여러 개 + 불일치      -> **거부**(사진일 때만)
        목록이 물건번호를 안 준다   -> 판단 근거가 없다. 막지 않는다
    """
    print("\n--- 22. 물건이 모호하면 사진을 수집하지 않는다 (Sprint 230) ---")
    import crawler.base_crawler as bc

    calls = {"moved": []}

    class FakeDriver:
        def execute_script(self, script):
            calls["moved"].append(script)

    def install(list_items, detail_ok=True):
        """목록/진입 단계를 대체한다 - 이 검사의 관심사는 **어느 행을 고르는가** 다."""
        bc.go_to_schedule = lambda driver, court: (True, True)
        bc.collect_list_items = lambda driver, limit: list_items
        bc.wait_for_detail = lambda driver, case_no: detail_ok

    orig = (bc.go_to_schedule, bc.collect_list_items, bc.wait_for_detail)
    try:
        from config.courts import ALL_COURTS
        court_code = ALL_COURTS[0].code

        def row(case_no, obj_no, idx):
            return {"case_no": case_no, "obj_no": obj_no, "dtl_idx": idx}

        CASE = "2025타경311"

        # (1) 후보 여러 개 + 요청 물건이 목록에 없다 -> 사진은 거부
        install([row(CASE, "1", 10), row(CASE, "2", 11)])
        calls["moved"] = []
        got = bc.go_to_case_detail(FakeDriver(), court_code, CASE, "3",
                                   require_exact_item=True)
        check("★ 모호할 때 사진 수집은 진입하지 않는다", got, False)
        check("★ 거부하면 상세로 이동조차 하지 않는다", calls["moved"], [])

        # (2) 같은 상황에서 **문서**는 종전대로 진행한다(버튼 id 가 물건을 특정한다)
        install([row(CASE, "1", 10), row(CASE, "2", 11)])
        calls["moved"] = []
        got = bc.go_to_case_detail(FakeDriver(), court_code, CASE, "3",
                                   require_exact_item=False)
        check("문서는 종전대로 첫 일치로 진행한다", got, True)
        check_true("문서는 상세로 이동한다", len(calls["moved"]) == 1, calls["moved"])

        # (3) 정확히 일치하는 행이 있으면 **그 행**으로 간다
        install([row(CASE, "1", 10), row(CASE, "2", 11)])
        calls["moved"] = []
        got = bc.go_to_case_detail(FakeDriver(), court_code, CASE, "2",
                                   require_exact_item=True)
        check("정확 일치가 있으면 진입한다", got, True)
        check("★ 첫 행이 아니라 요청한 물건의 행으로 간다",
              calls["moved"], ["moveDtlPage(11)"])

        # (4) 후보가 하나뿐이면 모호하지 않다 - 막지 않는다
        install([row(CASE, "1", 10)])
        calls["moved"] = []
        got = bc.go_to_case_detail(FakeDriver(), court_code, CASE, "9",
                                   require_exact_item=True)
        check("후보가 하나면 모호하지 않다(막지 않는다)", got, True)

        # (5) 목록이 물건번호를 아예 주지 않으면 판단 근거가 없다 - 막지 않는다
        install([row(CASE, "", 10), row(CASE, "", 11)])
        calls["moved"] = []
        got = bc.go_to_case_detail(FakeDriver(), court_code, CASE, "2",
                                   require_exact_item=True)
        check("물건번호 정보가 없으면 막지 않는다(모르는 것은 막지 않는다)", got, True)

        # (6) 배선 확인 - doc_worker 가 사진일 때만 정확 일치를 요구하는가
        #
        # 2026-08-20 Sprint 236: 예전에는 doc_worker 소스를 grep 해서
        # "require_exact_item=(doc_type ==" 문자열이 있는지만 봤다. 그 방식은
        # **문자열이 그대로 있으면서 실행 경로가 끊겨도 통과한다** - 이 저장소가
        # 반복해 경계하는 "grep 결과만으로 실행 경로 판정"이다. 실제로 이번에
        # 물건 단위 batching 이 들어오면서 호출이 `_ensure_detail_page()` 를
        # 거치게 됐고, 그때 이 검사는 정확히 그 이유로 울었다.
        #
        # 이제는 **실제로 불러 본다.** 사진일 때만 엄격하게 들어가는지,
        # 그리고 batching 이 그 엄격함을 깨뜨리지 않는지를 함께 본다.
        import doc_worker as dw

        src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "doc_worker.py"), encoding="utf-8-sig").read()
        flat = " ".join(src.split())
        check_true("★ doc_worker 가 사진일 때만 정확 일치를 요구한다(호출부)",
                   'require_exact=(doc_type == "image")' in flat,
                   [l.strip() for l in src.splitlines() if "require_exact" in l][:4])

        seen = []
        dw_orig = (dw.go_to_case_detail, dw.wait_for_detail)
        try:
            def spy_go(driver, court_code, case_no, item_no=None,
                       require_exact_item=False):
                seen.append(require_exact_item)
                return True

            dw.go_to_case_detail = spy_go
            dw.wait_for_detail = lambda driver, case_no: True

            # 사진 -> 엄격
            st = {}
            dw._ensure_detail_page(object(), st, "B1", "2024타경1", "1",
                                   require_exact=True)
            check("★ 사진은 엄격하게 들어간다", seen, [True])

            # 같은 물건의 문서는 그 엄격한 페이지를 **재사용**한다(이동 없음)
            dw._ensure_detail_page(object(), st, "B1", "2024타경1", "1",
                                   require_exact=False)
            check("★ 엄격한 페이지를 문서가 재사용한다(이동 추가 없음)", seen, [True])
            check("재사용 횟수가 기록된다", st.get("reused"), 1)

            # ★ 반대 방향은 재사용하지 않는다 - 느슨하게 들어간 페이지를
            #   사진이 그대로 쓰면 Sprint 230 이 막은 "다른 물건의 사진"이 돌아온다.
            seen[:] = []
            st2 = {}
            dw._ensure_detail_page(object(), st2, "B2", "2024타경2", "1",
                                   require_exact=False)
            dw._ensure_detail_page(object(), st2, "B2", "2024타경2", "1",
                                   require_exact=True)
            check("★ 느슨한 페이지를 사진이 재사용하지 않는다", seen, [False, True])

            # 다른 물건이면 당연히 다시 들어간다
            seen[:] = []
            st3 = {}
            dw._ensure_detail_page(object(), st3, "B3", "2024타경3", "1",
                                   require_exact=False)
            dw._ensure_detail_page(object(), st3, "B3", "2024타경3", "2",
                                   require_exact=False)
            check("다른 물건이면 다시 들어간다", len(seen), 2)

            # 화면을 벗어나 있으면(수집기가 원래 창으로 못 돌아온 경우) 다시 들어간다
            seen[:] = []
            st4 = {}
            dw._ensure_detail_page(object(), st4, "B4", "2024타경4", "1",
                                   require_exact=False)
            dw.wait_for_detail = lambda driver, case_no: False
            dw._ensure_detail_page(object(), st4, "B4", "2024타경4", "1",
                                   require_exact=False)
            check("★ 페이지를 벗어나 있으면 재사용하지 않고 다시 들어간다", len(seen), 2)
        finally:
            dw.go_to_case_detail, dw.wait_for_detail = dw_orig
    finally:
        bc.go_to_schedule, bc.collect_list_items, bc.wait_for_detail = orig


def test_url_rules_match_between_modules():
    print("\n--- 19. API URL 규칙이 라우트와 일치한다 ---")
    import api.v1.item as itemmod
    import api.v1.images as imgmod
    import api.v1.documents as docmod

    # item.py가 만드는 URL과 실제 라우트 경로가 같은 모양인가
    img_routes = [r.path for r in imgmod.router.routes]
    doc_routes = [r.path for r in docmod.router.routes]
    check_true("사진 라우트 존재", "/item/{item_id}/images/{seq}" in img_routes, img_routes)
    check_true("문서 라우트 존재", "/item/{item_id}/documents/{doc_type}" in doc_routes,
               doc_routes)
    check("사진 URL 생성 규칙", itemmod._image_url(5, 3), "/api/v1/item/5/images/3")
    check("문서 URL 생성 규칙", itemmod._document_url(5, "SPEC"),
          "/api/v1/item/5/documents/SPEC")

    # 미디어 타입 표가 허용 확장자를 전부 덮는가 — 빠지면 브라우저가 사진을 내려받기로 처리한다
    from crawler.image_assets import ALLOWED_IMAGE_EXTS, IMAGE_MEDIA_TYPES
    missing = [e for e in ALLOWED_IMAGE_EXTS if e not in IMAGE_MEDIA_TYPES]
    check("허용 확장자 전부에 media type이 있다", missing, [])


def test_frontend_contract():
    """프런트가 실제로 읽는 필드를 서버가 준다는 것을 소스 대조로 고정한다.

    프런트를 실행하지 않고도(브라우저/로그인 없이) 계약이 갈라지는 것을 잡는다 —
    이 저장소가 프런트/백엔드 사이에서 반복해 겪은 어긋남을 막는 가장 싼 방법이다.
    """
    print("\n--- 20. 프런트/백엔드 계약 ---")
    root = os.path.dirname(os.path.abspath(__file__))
    page = os.path.join(root, "src", "app", "properties", "[id]", "page.tsx")
    src = open(page, encoding="utf-8-sig").read()

    for field in ("images_status", "representative_image", "thumbnail_url",
                  "page_count", "download_url", "viewer_url"):
        check_true("프런트가 %s를 쓴다" % field, field in src)

    item_src = open(os.path.join(root, "api", "v1", "item.py"), encoding="utf-8-sig").read()
    for field in ("images_status", "representative_image", "thumbnail_url",
                  "image_count", "page_count", "viewer_url", "download_url", "available"):
        check_true("서버가 %s를 준다" % field, '"%s"' % field in item_src)

    # 프런트가 아는 상태 라벨이 서버가 실제로 쓰는 값을 덮는가
    for status in ("READY", "COLLECTING", "FAILED", "NO_IMAGE"):
        check_true("프런트에 %s 라벨이 있다" % status, status in src)


def test_missing_auction_image_table_degrades_not_crashes():
    """`auction_image` 테이블이 없어도 검색/상세/사진 서빙이 500으로 죽지 않는다
    (2026-08-21 Sprint 239, `docs/BUGS.md` #177).

    migration 020 미적용 로컬 환경에서 검색 API 전체가 500이 되는 것을 진짜
    프로세스 + curl로 재현했다(원인: `fetch_thumbnail_seqs()` / `item.py`의 사진 쿼리 /
    `images.py`의 서빙 쿼리, 셋 다 `sqlite3.OperationalError`를 그대로 위로 흘려보냄).
    여기서는 그 결손을 **의도적으로 재현**(DROP TABLE)해서 세 지점이 "사진 없음"과
    같은 모양으로 되돌아가는지 확인하고, 동시에 **다른 종류의 OperationalError는
    여전히 새어 나가는지**(narrow catch — 이 결손 하나만 흡수하고 다른 결함을 가리지
    않는지)도 함께 잠근다.
    """
    print("\n--- 21. auction_image 결손이 API 전체를 죽이지 않는다 (Sprint 239) ---")
    import sqlite3
    from fastapi.testclient import TestClient

    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1, case_no="2024타경1", item_no="1")
        c = env.conn()
        c.execute("UPDATE auction_item SET auction_date='2099-01-01', sido='서울',"
                  " minimum_bid_price=1, appraisal_price=1, bid_rate=1, fail_count=0"
                  " WHERE id=1")
        c.commit()
        # migration 020 미적용을 그대로 재현한다 — 다른 어떤 것도 손대지 않는다.
        c.execute("DROP TABLE auction_image")
        c.commit()
        c.close()

        from api_server import app
        client = TestClient(app)

        r = client.get("/api/v1/search?include_closed=true&size=50")
        check("★ 테이블이 없어도 검색은 200", r.status_code, 200)
        items = {i["id"]: i for i in r.json()["items"]}
        check("★ 썸네일은 사진 없음과 같은 모양(null)", items[1]["thumbnail_url"], None)

        r2 = client.get("/api/v1/item/1")
        check("★ 테이블이 없어도 상세는 200", r2.status_code, 200)
        check("★ images는 빈 목록", r2.json()["images"], [])

        r3 = client.get("/api/v1/item/1/images/1")
        check("★ 사진 서빙은 500이 아니라 404", r3.status_code, 404)

        # ★ narrow catch 검증 — **실제 함수**를 그대로 부르되, 커넥션만 가짜로 바꿔
        # auction_image가 아닌 다른 테이블 결손을 흉내낸다. 여기서 함수 자체를
        # 몽키패치로 갈아치우면(이전 버전의 실수) 테스트가 진짜 코드의 분기를 전혀
        # 지나가지 않아 mutation을 못 잡는 공허한 검사가 된다 — 실제로 그렇게 써서
        # `except ... raise`를 지웠는데도 통과하는 것을 이번 세션에서 직접 확인했다.
        import api.v1.thumbnails as th

        class _FakeConnOtherTableMissing:
            def execute(self, *a, **kw):
                raise sqlite3.OperationalError("no such table: some_other_table")

        try:
            th.fetch_thumbnail_seqs(_FakeConnOtherTableMissing(), [1])
            check_true("★ 다른 테이블 결손은 삼키지 않고 다시 던진다(narrow catch)",
                       False, "예외 없이 반환됐다")
        except sqlite3.OperationalError as e:
            check_true("★ 다른 테이블 결손은 삼키지 않고 다시 던진다(narrow catch)",
                       "some_other_table" in str(e), str(e))
    finally:
        env.close()




def test_file_size_describes_what_download_url_serves():
    """`file_size` 는 **`download_url` 이 주는 바로 그 파일**의 크기여야 한다.

    ## 무엇이 틀려 있었나 (2026-08-21 Sprint 241)

    `_document_entry()` 는 `file_size` 를 `doc_raw` 에서 그대로 퍼왔다. 그런데
    `doc_raw` 가 실체로 기록하는 파일과 API 가 **서빙하는** 파일이 STATUS 에서 다르다.

        doc_raw.storage_path   status.json    <- 구조화 산출물(변경 감지 지문의 출처)
        서빙 파일               status.html    <- api/v1/documents.py DOC_TYPE_FILES

    운영 데이터 실측(READY 문서 45건 전수, 2026-08-21):

        SPEC / APPRAISAL   33건  doc_raw 파일 == 서빙 파일  -> 크기 일치
        STATUS             12건  **전부 불일치**  (예: 광고 12,827B / 실제 45,747B ≈ 3.6배)

    즉 API 가 `download_url` 옆에서 **다른 파일의 크기**를 광고하고 있었다.
    지금은 화면이 이 값을 그리지 않아 사용자에게 보이지 않지만, 쓰는 쪽이 생기는
    순간(용량 표시·진행률·사전 할당) 조용히 틀린다.

    ## 이 검사가 잠그는 것

    STATUS 를 **반드시 포함**한다 — SPEC 만 검사하면 두 파일이 같아서 통과해 버리고,
    그것이 이 결함이 오래 살아남은 이유다(검사가 공허해지는 지점을 여기서 못 박는다).
    """
    print("\n--- 41. file_size 가 download_url 이 주는 파일을 설명하는가 (Sprint 241) ---")
    from fastapi.testclient import TestClient
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        doc_dir = os.path.join(env.docs, court, case_no, item_no)
        os.makedirs(doc_dir, exist_ok=True)

        # 서빙되는 파일과 doc_raw 가 가리키는 파일을 **일부러 다른 크기로** 만든다.
        spec_bytes = b"%PDF-1.4 " + b"S" * 500
        html_bytes = b"<html><body>" + b"H" * 4000 + b"</body></html>"
        json_bytes = b'{"fields":{}}' + b" " * 100          # html 과 크기가 확연히 다르다
        with open(os.path.join(doc_dir, "spec.pdf"), "wb") as f:
            f.write(spec_bytes)
        with open(os.path.join(doc_dir, "status.html"), "wb") as f:
            f.write(html_bytes)
        with open(os.path.join(doc_dir, "status.json"), "wb") as f:
            f.write(json_bytes)

        c = env.conn()
        c.execute("INSERT INTO document_status (item_id,doc_type,status) VALUES (1,'SPEC','READY')")
        c.execute("INSERT INTO document_status (item_id,doc_type,status) VALUES (1,'STATUS','READY')")
        c.execute("INSERT INTO document_status (item_id,doc_type,status)"
                  " VALUES (1,'APPRAISAL','COLLECTING')")
        # doc_raw 는 **구조화 산출물**을 가리킨다 - 이것이 실제 규약이다
        c.execute("INSERT INTO doc_raw (item_id,doc_type,storage_path,file_size,doc_version,page_count)"
                  " VALUES (1,'SPEC',?,?,1,7)",
                  (os.path.join(doc_dir, "spec.pdf"), len(spec_bytes)))
        c.execute("INSERT INTO doc_raw (item_id,doc_type,storage_path,file_size,doc_version,page_count)"
                  " VALUES (1,'STATUS',?,?,1,NULL)",
                  (os.path.join(doc_dir, "status.json"), len(json_bytes)))
        c.commit()
        c.close()

        from api_server import app
        client = TestClient(app)
        body = client.get("/api/v1/item/1").json()
        docs = {d["doc_type"]: d for d in body["documents"]}

        # 전제: 두 파일 크기가 실제로 다르다(검사가 공허하지 않다)
        check_true("★ status.html 과 status.json 의 크기가 다르다(전제)",
                   len(html_bytes) != len(json_bytes),
                   "%d vs %d" % (len(html_bytes), len(json_bytes)))

        for doc_type in ("SPEC", "STATUS"):
            d = docs[doc_type]
            check("%s available" % doc_type, d["available"], True)
            served = client.get(d["download_url"])
            check("%s 서빙 200" % doc_type, served.status_code, 200)
            check("★ %s file_size == download_url 이 준 바이트 수" % doc_type,
                  d["file_size"], len(served.content))

        # ★ 핵심: STATUS 는 doc_raw 값(status.json)을 그대로 쓰면 안 된다
        check_true("★ STATUS file_size 가 doc_raw(status.json) 값이 아니다",
                   docs["STATUS"]["file_size"] != len(json_bytes),
                   "doc_raw 값 %d 를 그대로 퍼왔다 - 다른 파일을 설명하고 있다"
                   % len(json_bytes))
        check("★ STATUS file_size 는 서빙되는 status.html 의 크기다",
              docs["STATUS"]["file_size"], len(html_bytes))

        # READY 가 아니면 URL 도 크기도 주지 않는다(잴 대상이 없다).
        #
        # ★ 이 검사가 공허해지지 않도록 **파일을 실제로 만들어 둔다.**
        #   재수집(overwrite) 중에는 상태가 COLLECTING 인데 **옛 파일이 디스크에 그대로**
        #   남아 있다 - 실제로 자주 있는 상태다. 파일이 없으면 어느 구현이든 None 이
        #   나와서, "READY 일 때만 잰다"는 규칙을 지우는 mutation 이 통과해 버린다.
        with open(os.path.join(doc_dir, "appraisal.pdf"), "wb") as f:
            f.write(b"%PDF-1.4 " + b"A" * 2000)
        docs = {d["doc_type"]: d for d in client.get("/api/v1/item/1").json()["documents"]}
        check_true("재수집 중인 문서의 옛 파일이 디스크에 있다(전제)",
                   os.path.getsize(os.path.join(doc_dir, "appraisal.pdf")) > 0)
        check("수집중 문서는 URL 없음", docs["APPRAISAL"]["download_url"], None)
        check_true("★ 수집중 문서는 옛 파일이 있어도 file_size 를 주지 않는다",
                   docs["APPRAISAL"]["file_size"] is None,
                   "file_size=%r - 받을 수 없는(URL 없는) 문서의 크기를 광고하고 있다"
                   % (docs["APPRAISAL"]["file_size"],))

        # doc_raw 는 건드리지 않았다 - 변경 감지의 실체 기록은 그대로여야 한다
        c = env.conn()
        raw = {r[0]: r[1] for r in c.execute(
            "SELECT doc_type, file_size FROM doc_raw WHERE item_id=1")}
        c.close()
        check("doc_raw 의 STATUS 크기는 여전히 status.json 것이다(의미 불변)",
              raw["STATUS"], len(json_bytes))

        # ★ 0바이트 서빙 파일은 "있다"가 아니다 - `documents.py` 가 그런 파일에
        #   404 를 주기 때문이다(Sprint 98: "있다의 기준을 크롤러와 같게 맞춘다").
        #   그 상태에서 크기를 0으로 광고하면 "받을 수 있는데 0바이트"라는 뜻이 되어
        #   실제 동작(404)과 어긋난다. 두 모듈의 기준을 하나로 유지한다.
        with open(os.path.join(doc_dir, "status.html"), "wb") as f:
            f.write(b"")
        body0 = client.get("/api/v1/item/1").json()
        st0 = {d["doc_type"]: d for d in body0["documents"]}["STATUS"]
        check("0바이트 서빙 파일은 실제로 404 다(전제)",
              client.get("/api/v1/item/1/documents/STATUS").status_code, 404)
        check_true("★ 0바이트면 file_size 는 0 이 아니라 None 이다(404 와 같은 판정)",
                   st0["file_size"] is None,
                   "file_size=%r - 받을 수 없는 문서에 크기를 광고하고 있다"
                   % (st0["file_size"],))
        with open(os.path.join(doc_dir, "status.html"), "wb") as f:
            f.write(html_bytes)

        # 서빙 파일이 사라지면 크기는 None 이 된다 - doc_raw 값으로 되돌아가지 않는다
        os.remove(os.path.join(doc_dir, "status.html"))
        body2 = client.get("/api/v1/item/1").json()
        st2 = {d["doc_type"]: d for d in body2["documents"]}["STATUS"]
        check_true("★ 서빙 파일이 없으면 file_size 는 None(옛 값으로 되돌아가지 않는다)",
                   st2["file_size"] is None,
                   "file_size=%r - doc_raw 로 폴백하면 다시 거짓말이 된다" % (st2["file_size"],))
    finally:
        env.close()



def test_stored_resolution_is_never_lower_than_the_source():
    """저장된 사진의 해상도가 **원본 후보보다 낮아지지 않는다** (2026-08-21 Sprint 243).

    ## 왜 이 검사가 필요했나

    "검색목록/상세의 사진이 왜 작은가"라는 질문에 답하려면 먼저 **우리가 줄이고
    있지 않다**는 것을 코드로 못 박아야 한다. 그래야 남은 원인(법원이 그 크기만 준다)
    을 근거 있게 말할 수 있다.

    2026-08-21 실측으로 확인한 사실들:

        운영 사진 45장  긴 변이 **전부 정확히 700px**
        우리 코드       `700` 리터럴 없음 / resize·thumbnail 호출 없음
        수집 경로       법원이 base64 data URI 로 바이트를 그대로 준다 -> 우리는 그대로 쓴다
        EXIF            45장 전부 없음 -> 법원 서버가 재인코딩한 산출물이다
        양자화테이블 합   64(거의 무손실) 와 1858(보통) 두 종류가 섞여 있다
                        -> 썸네일 파이프라인이라면 하나로 통일됐을 것이다

    즉 700px 는 **법원이 정한 크기**이지 우리가 만든 것이 아니다. 이 검사는 그 사실이
    앞으로도 유지되게 한다 — 누군가 파이프라인에 리사이즈를 넣으면 여기서 운다.

    ## 무엇을 잠그나

        1. 저장 파일의 해상도 == 원본 바이트의 해상도  (한 픽셀도 줄이지 않는다)
        2. 저장 파일의 바이트 == 원본 바이트           (재인코딩하지 않는다)
        3. DB(auction_image) 의 width/height == 실제 파일의 해상도
        4. 후보가 여럿이면 **가장 큰 것**이 저장된다
    """
    print(NL + "--- 42. 저장 해상도가 원본보다 낮아지지 않는다 (Sprint 243) ---")
    import hashlib
    from crawler.image_crawler import collect_images
    from crawler.image_assets import read_image_dimensions

    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        # 서로 다른 해상도의 원본들 - 세로/가로/정사각을 섞는다
        sources = {1: make_jpeg(1600, 1200), 2: make_jpeg(900, 1600),
                   3: make_jpeg(1024, 1024), 4: make_jpeg(640, 480)}
        driver = FakeDriver([img_el("전경도", s, b) for s, b in sorted(sources.items())])
        res = collect_images(driver, court, case_no, item_no)
        check("네 장 모두 저장", res["image_count"], 4)

        for im in res["images"]:
            seq = im["seq"]
            src = sources[seq]
            sw, sh = read_image_dimensions(src)
            # (1) 파이프라인이 보고한 해상도 == 원본 해상도
            check("★ seq%d 보고 해상도가 원본과 같다" % seq, (im["width"], im["height"]), (sw, sh))
            # (2) 디스크 파일을 실제로 읽어 다시 잰다 (보고를 믿지 않는다).
            #     제품이 쓰는 판독기를 그대로 쓴다 - 이 검사의 표본은 합성 JPEG 헤더라
            #     범용 디코더(PIL)로는 열리지 않는다. 재는 대상은 **해상도**이므로
            #     SOF 마커를 읽는 제품 판독기가 정확히 맞는 도구다.
            dw, dh = read_image_dimensions(open(im["path"], "rb").read())
            check("★ seq%d 디스크 파일 해상도가 원본과 같다" % seq, (dw, dh), (sw, sh))
            # (3) 바이트까지 동일 - 재인코딩하지 않는다
            disk = open(im["path"], "rb").read()
            check("★ seq%d 저장 바이트가 원본과 동일(재인코딩 없음)" % seq,
                  hashlib.sha256(disk).hexdigest(), hashlib.sha256(src).hexdigest())

        # (4) DB 기록도 실제 파일과 같아야 한다
        from storage.database import save_auction_images
        save_auction_images(court, case_no, item_no, res["images"])
        c = env.conn()
        try:
            rows = list(c.execute("SELECT seq,width,height,storage_path FROM auction_image"
                                  " ORDER BY seq"))
        finally:
            c.close()
        check("DB 에 네 행", len(rows), 4)
        for r in rows:
            dw, dh = read_image_dimensions(open(r["storage_path"], "rb").read())
            check("★ DB seq%d 해상도가 실제 파일과 같다" % r["seq"],
                  (r["width"], r["height"]), (dw, dh))
    finally:
        env.close()

    # (5) 후보가 여럿일 때 가장 큰 것이 저장된다 - 축소 저장을 만들지 않는다
    env = Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        thumb, full = make_jpeg(200, 150), make_jpeg(2000, 1500)
        # 썸네일이 **먼저** 오는 배치 - 옛 규칙이었다면 썸네일이 저장됐다
        driver = FakeDriver([img_el("전경도", 1, thumb), img_el("전경도", 1, full)])
        res = collect_images(driver, court, case_no, item_no)
        check("한 장만 저장", res["image_count"], 1)
        fw, fh = read_image_dimensions(full)
        check("★ 썸네일이 먼저 와도 큰 원본이 저장된다",
              (res["images"][0]["width"], res["images"][0]["height"]), (fw, fh))
        check_true("★ 저장 해상도가 썸네일보다 크다(축소 저장이 아니다)",
                   res["images"][0]["width"] > 200 and res["images"][0]["height"] > 150,
                   (res["images"][0]["width"], res["images"][0]["height"]))
    finally:
        env.close()

    # (6) 수집기 코드에 리사이즈 도구가 들어오지 않았는가 (주석이 아니라 코드)
    src_files = ["crawler/image_crawler.py", "crawler/image_assets.py"]
    for f in src_files:
        raw = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f),
                      encoding="utf-8-sig").read()
        code = NL.join(l for l in raw.splitlines() if not l.lstrip().startswith("#"))
        for banned in (".resize(", ".thumbnail(", "LANCZOS", "BICUBIC"):
            check_true("★ %s 에 %s 가 없다(파이프라인이 축소하지 않는다)" % (f, banned),
                       banned not in code, banned)

if __name__ == "__main__":
    test_alt_parsing()
    test_image_format_edge_cases()
    test_magic_sniffing_beats_declared_mime()
    test_dimension_reading()
    test_path_rules()
    test_collect_images_happy_path()
    test_image_write_failure_leaves_no_partial_file()
    test_overwrite_enables_recollection()
    test_image_change_detection()
    test_format_change_leaves_no_ghost_file()
    test_duplicate_seq_on_disk_refuses_to_fingerprint()
    test_refresh_does_not_rewrite_identical_photos()
    test_reduced_photo_count_removes_files_too()
    test_court_removed_all_photos_needs_two_sightings()
    test_three_sources_never_diverge()
    test_no_photos_is_not_a_failure()
    test_dom_change_is_a_failure_not_silent_success()
    test_bad_payloads_are_rejected()
    test_duplicate_seq_defense()
    test_rerun_is_idempotent_and_recovers_db()
    test_case_level_status_reuse()
    test_relative_storage_path_rule()
    test_save_auction_images_defenses()
    test_partial_collection_does_not_delete_old_photos()
    test_mark_queue_done_records_doc_raw()
    test_doc_raw_version_does_not_bump_on_unchanged_content()
    test_doc_raw_refuses_to_record_false_success()
    test_mark_queue_done_missing_file_is_not_recorded()
    test_image_queue_type_does_not_crash_legacy_update()
    test_enqueue_includes_image()
    test_reconcile_queue_auction_date()
    test_worker_consults_authoritative_date_before_expiring()
    test_api_contract()
    test_search_thumbnail_contract()
    test_favorites_and_recent_thumbnail_contract()
    test_item_detail_is_not_n_plus_one()
    test_api_images_status_variants()
    test_oversized_ids_are_404_not_500()
    test_image_path_traversal_blocked()
    test_deletion_never_escapes_document_root()
    test_worker_skips_navigation_when_sibling_reuse_possible()
    test_reconcile_uses_court_in_identity_key()
    test_path_segment_rule_is_single_sourced()
    test_image_success_is_not_recorded_before_the_photos_are()
    test_image_done_requires_actual_asset_record()
    test_document_done_requires_the_file_to_exist()
    test_queue_write_failure_after_the_photos_are_recorded()
    test_document_revision_survives_a_queue_write_failure()
    test_document_partial_collection_contract()
    test_court_removed_photos_end_to_end_through_the_worker()
    test_list_and_detail_show_the_same_photo()
    test_list_thumbnail_reflects_a_changed_photo()
    test_recorded_photo_is_always_servable()
    test_existence_rule_is_single_sourced()
    test_skip_path_records_the_document_it_already_has()
    test_download_of_another_case_is_refused()
    test_photos_are_not_taken_from_the_wrong_item()
    test_url_rules_match_between_modules()
    test_frontend_contract()
    test_missing_auction_image_table_degrades_not_crashes()
    test_file_size_describes_what_download_url_serves()
    test_stored_resolution_is_never_lower_than_the_source()
    test_ready_document_without_served_file_is_not_advertised()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL ASSET PIPELINE TESTS PASSED")
