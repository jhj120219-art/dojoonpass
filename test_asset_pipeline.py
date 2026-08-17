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
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
        self.dbmod, self.dp, self.ia, self.apiimg = dbmod, dp, ia, apiimg
        self._orig = (dbmod.DB_PATH, dp.DOCUMENT_ROOT, ia.DOCUMENT_ROOT,
                      apiimg.DOCUMENT_ROOT, apiimg.PROJECT_ROOT)
        dbmod.DB_PATH = os.path.join(self.dir, "t.db")
        dp.DOCUMENT_ROOT = self.docs
        ia.DOCUMENT_ROOT = self.docs
        apiimg.DOCUMENT_ROOT = self.docs
        apiimg.PROJECT_ROOT = self.dir

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
         self.apiimg.DOCUMENT_ROOT, self.apiimg.PROJECT_ROOT) = self._orig
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


def test_duplicate_seq_defense():
    print("\n--- 9. 같은 순번 중복 방어 ---")
    from crawler.image_crawler import collect_images
    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        a, b = make_jpeg(100, 100), make_jpeg(200, 200)
        driver = FakeDriver([img_el("전경도", 1, a), img_el("위치도", 1, b)])
        res = collect_images(driver, court, case_no, item_no)
        check("순번 중복은 하나만 채택", res["image_count"], 1)
        check("먼저 나온 것을 쓴다", res["images"][0]["kind"], "전경도")
        check("먼저 나온 것의 크기", (res["images"][0]["width"], res["images"][0]["height"]),
              (100, 100))
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
        res2 = dc.collect_status(None, court, case_no, "2", "qa-btn-unused")
        check("이미 있으면 스킵한다(성공)", res2["success"], True)
        # 스킵 경로는 `_empty_result()`를 그대로 돌려주므로 `reused_from` 키 자체가 없다.
        # 즉 "재사용도 하지 않았다"가 키 부재로 드러난다 — 그것을 고정한다.
        check_true("스킵 경로는 재사용을 타지 않는다(reused_from 키 없음)",
                   "reused_from" not in res2, sorted(res2))
        check("스킵 경로는 파일을 다시 쓰지 않는다", res2["files_saved"], [])

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
        for seq in (2, 3):
            p = os.path.join(d, "0%d.jpg" % seq)
            with open(p, "wb") as f:
                f.write(make_jpeg())
            save_auction_images(court, case_no, item_no,
                                [{"seq": 1, "kind": "전경도", "path": real, "file_hash": "h",
                                  "width": 1, "height": 1},
                                 {"seq": seq, "kind": "전경도", "path": p, "file_hash": "h",
                                  "width": 1, "height": 1}])
        check("누적 3장 기록(1,2,3)", [r["seq"] for r in env.images_of(1)], [1, 2, 3])
        save_auction_images(court, case_no, item_no,
                            [{"seq": 1, "kind": "전경도", "path": real, "file_hash": "h",
                              "width": 1, "height": 1}])
        check("사진이 줄면 뒤쪽 옛 행이 정리된다", [r["seq"] for r in env.images_of(1)], [1])
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

        # 두 번째 수집이면 버전이 올라간다.
        # 큐 행은 새로 만들지 않는다 — 018 마이그레이션의 UNIQUE(법원,사건,물건,종류)
        # 때문에 애초에 만들 수 없고, 운영에서도 재수집은 `reset_stale_queue()`가
        # **같은 행**을 pending으로 되살리는 방식이다.
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
                            "doc_worker.py"), encoding="utf-8").read()
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
    src = open(page, encoding="utf-8").read()

    for field in ("images_status", "representative_image", "thumbnail_url",
                  "page_count", "download_url", "viewer_url"):
        check_true("프런트가 %s를 쓴다" % field, field in src)

    item_src = open(os.path.join(root, "api", "v1", "item.py"), encoding="utf-8").read()
    for field in ("images_status", "representative_image", "thumbnail_url",
                  "image_count", "page_count", "viewer_url", "download_url", "available"):
        check_true("서버가 %s를 준다" % field, '"%s"' % field in item_src)

    # 프런트가 아는 상태 라벨이 서버가 실제로 쓰는 값을 덮는가
    for status in ("READY", "COLLECTING", "FAILED", "NO_IMAGE"):
        check_true("프런트에 %s 라벨이 있다" % status, status in src)


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
    test_doc_raw_refuses_to_record_false_success()
    test_mark_queue_done_missing_file_is_not_recorded()
    test_image_queue_type_does_not_crash_legacy_update()
    test_enqueue_includes_image()
    test_reconcile_queue_auction_date()
    test_worker_consults_authoritative_date_before_expiring()
    test_api_contract()
    test_search_thumbnail_contract()
    test_item_detail_is_not_n_plus_one()
    test_api_images_status_variants()
    test_oversized_ids_are_404_not_500()
    test_image_path_traversal_blocked()
    test_worker_skips_navigation_when_sibling_reuse_possible()
    test_reconcile_uses_court_in_identity_key()
    test_path_segment_rule_is_single_sourced()
    test_url_rules_match_between_modules()
    test_frontend_contract()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL ASSET PIPELINE TESTS PASSED")
