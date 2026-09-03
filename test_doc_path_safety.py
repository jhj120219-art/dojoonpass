"""문서/사진 저장 경로 조각 정규화 회귀 (2026-08-17 Sprint 145 신설).

## 왜 이 파일이 생겼나

`crawler/doc_paths.py:_doc_dir_path()`의 주석은 예전부터 이렇게 적고 있었다:

> 경로 규칙은 여기 한 곳에만 두고 ... **규칙이 두 벌이 되면 "쓰는 곳과 읽는 곳이
> 다른 경로를 보는" 이 저장소의 단골 결함이 된다.**

2026-08-17 실측에서 그 규칙이 **세 곳**에 각자 적혀 있었다:

    crawler/doc_paths.py   _doc_dir_path()                (원본)
    crawler/doc_paths.py   find_sibling_case_document()   (Sprint 145에 추가된 두 번째 소비자)
    crawler/image_assets.py image_path()                  (Sprint 144)

세 곳이 어긋나면 증상이 조용하다 — 파일은 디스크에 있는데 조회 쪽이 다른 디렉터리를
보므로 `doc_exists()`가 False가 되어 **이미 받은 문서를 다시 받거나**, 형제 재사용이
항상 실패하거나, DB는 READY인데 서빙이 404가 된다.

## 이 검사가 지키는 사실

1. 사건번호에 `/`가 들어오는 것은 예외가 아니라 **일상**이다 — 실 DB 1,876건 중
   **425건(22.7%)**이 복수 사건번호(`"2024타경1451 / 2024타경32745"`)이고,
   그 물건들의 `doc_raw` 행이 101건이다.
2. Windows에서는 **역슬래시도 경로 구분자**다. `/`만 치환하던 시절
   역슬래시 두 단계 상위이동이 든 case_no는 `documents/`를 벗어난 경로를
   만들었다(실측 확인 — 구체적 입력은 아래 §4·§5의 hostile 목록에 있다).
   서빙은 `realpath`+`commonpath`로 막혀 있었지만(`api/v1/documents.py`,
   `api/v1/images.py`), **쓰기 경로**는 `get_doc_dir()`가 `os.makedirs()`를 부르므로
   저장소 바깥에 디렉터리를 만들 수 있었다. 이 저장소는 이미 `doc_paths` 때문에
   빈 디렉터리 1,674개가 생긴 사고를 겪었다.
   (실데이터에 역슬래시·`..`는 0건이다 — 터지던 버그가 아니라 자리를 막은 것이다.)

    python test_doc_path_safety.py
"""
import os
import re
import sys

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


ROOT = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# 1. 정상 입력
# ---------------------------------------------------------------------------
def test_normal_values_pass_through():
    print("\n--- 1. 정상 입력은 그대로 ---")
    from crawler.doc_paths import sanitize_path_segment as s
    check("단일 사건번호", s("2024타경3528"), "2024타경3528")
    check("물건번호", s("2"), "2")
    check("앞뒤 공백은 제거", s("  2024타경1  "), "2024타경1")


# ---------------------------------------------------------------------------
# 2. 실데이터 형태 — 복수 사건번호(전체의 22.7%)
# ---------------------------------------------------------------------------
def test_multi_case_numbers():
    print("\n--- 2. 복수 사건번호 (실데이터 425건 형태) ---")
    from crawler.doc_paths import sanitize_path_segment as s
    check("슬래시는 밑줄로",
          s("2024타경1451 / 2024타경32745"), "2024타경1451 _ 2024타경32745")
    check("3개 이상도 동일",
          s("2023타경848 / 2025타경20349 / 2024타경418"),
          "2023타경848 _ 2025타경20349 _ 2024타경418")


# ---------------------------------------------------------------------------
# 3. 경계값 — 비거나 상위를 가리키는 조각
# ---------------------------------------------------------------------------
def test_boundary_values():
    print("\n--- 3. 경계값 ---")
    from crawler.doc_paths import sanitize_path_segment as s
    # os.path.join에 ""를 주면 그 조각이 사라져 **상위 디렉터리**를 가리킨다.
    check("빈 문자열", s(""), "_")
    check("공백뿐", s("   "), "_")
    check("None", s(None), "_")
    check("점 하나", s("."), "_")
    check("점 둘", s(".."), "_")


# ---------------------------------------------------------------------------
# 4. 잘못된 입력 — 경로 구분자
# ---------------------------------------------------------------------------
def test_separators_are_neutralised():
    print("\n--- 4. 경로 구분자 무력화 ---")
    from crawler.doc_paths import sanitize_path_segment as s
    check("역슬래시도 밑줄로", s("a\\b"), "a_b")
    check("슬래시+역슬래시 혼합", s("a/b\\c"), "a_b_c")
    check_true("역슬래시 상위이동이 남지 않는다",
               os.sep not in s("..\\..\\evil") and "/" not in s("..\\..\\evil"),
               s("..\\..\\evil"))


# ---------------------------------------------------------------------------
# 5. ★ 어떤 입력으로도 documents/ 를 벗어나지 않는다
# ---------------------------------------------------------------------------
def _cleanup_probe_dir(path):
    """이 검사가 만든 탐침 디렉터리만 지운다. **파일은 절대 지우지 않는다.**

    `rmdir` 만 쓴다 — 비어 있지 않으면 그대로 둔다. 잎 이름이 QA 표식
    (`2099타경QA`)일 때만 시작하고, 위로 올라가며 비는 껍데기만 걷어낸다.
    저장소 밖을 지울 수도 있는 코드이므로 `rmtree` 를 쓰지 않는다.
    """
    cur = os.path.abspath(path)
    for _ in range(4):          # 잎 + 껍데기 3단계면 충분하다
        if not os.path.isdir(cur):
            break
        try:
            os.rmdir(cur)       # 비어 있을 때만 성공한다
        except OSError:
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent

def test_never_escapes_document_root():
    print("\n--- 5. DOCUMENT_ROOT 밖으로 나가지 않는다 ---")
    import crawler.doc_paths as dp
    import crawler.image_assets as ia
    root = os.path.abspath(dp.DOCUMENT_ROOT)

    hostile = [
        "..\\..\\evil", "../../evil", "..", ".", "",
        "   ", "a\\..\\..\\b", "\\\\server\\share", "/etc/passwd",
    ]
    for value in hostile:
        d = os.path.abspath(dp._doc_dir_path("법원", value, "1"))
        i = os.path.abspath(ia.image_path("법원", value, "1", 1, "jpg"))
        check_true("문서 경로가 root 안 (case_no=%r)" % value[:18],
                   os.path.commonpath([d, root]) == root, d)
        check_true("사진 경로가 root 안 (case_no=%r)" % value[:18],
                   os.path.commonpath([i, root]) == root, i)
        # item_no 쪽도 같은 방어가 필요하다(사건번호만 막으면 절반이다).
        d2 = os.path.abspath(dp._doc_dir_path("법원", "2024타경1", value))
        check_true("문서 경로가 root 안 (item_no=%r)" % value[:18],
                   os.path.commonpath([d2, root]) == root, d2)

    # ★ 셋째 조각 — **법원**도 흔든다 (2026-09-04).
    #
    #   위 두 루프는 `case_no` 와 `item_no` 만 흔들고 법원 자리는 "법원" 으로
    #   고정한다. 그런데 `sanitize_path_segment()` 를 지나는 것도 그 둘뿐이고,
    #   **법원 조각은 원문 그대로** `os.path.join()` 에 들어간다. 즉 위 주석이
    #   *"사건번호만 막으면 절반이다"* 라고 적어 둔 그 자리에서 셋째가 빠져 있었다.
    #
    #   실측(2026-09-04, 가드 도입 전):
    #       _doc_dir_path('..',            '2024타경1','1') -> <저장소>/2024타경1/1
    #       _doc_dir_path('../../Windows', '2024타경1','1') -> <바탕화면>/Windows/...
    #       _doc_dir_path('D:',            '2024타경1','1') -> D: 드라이브로 튄다
    #
    #   경로 **계산**은 지금도 밖을 가리킬 수 있다(정상 입력의 경로를 바꾸지 않기
    #   위해 법원 조각을 치환하지 않기로 했다 — `get_doc_dir()` docstring 참고).
    #   대신 **디스크를 바꾸는** `get_doc_dir()` 이 담김을 확인하고 거절한다.
    #   그래서 여기서는 "계산이 밖을 가리키면 쓰기가 거절되는가" 를 본다.
    hostile_courts = ["..", "../..", "..\\..\\Windows", "/etc", "D:",
                      "\\\\server\\share"]
    rejected = []
    for court in hostile_courts:
        calculated = os.path.abspath(dp._doc_dir_path(court, "2099타경QA", "1"))
        try:
            inside = os.path.commonpath([calculated, root]) == root
        except ValueError:
            inside = False          # 드라이브가 다르면 비교 자체가 안 된다 = 밖
        if inside:
            continue                # 이 값은 애초에 밖으로 못 나간다 - 볼 것 없다
        try:
            made = dp.get_doc_dir(court, "2099타경QA", "1")
            check_true("★ 저장소 밖 쓰기가 거절된다 (court=%r)" % court[:18],
                       False, "만들어 버렸다 -> %s" % made)
        except ValueError:
            rejected.append(court)
        # 거절했으면 디스크에 흔적이 없어야 한다.
        left = os.path.exists(calculated)
        check_true("거절된 경로가 디스크에 생기지 않았다 (court=%r)" % court[:18],
                   not left, calculated)
        # ★ 붉어진 경우에도 **저장소 밖을 어지르지 않는다** (2026-09-04).
        #   가드가 깨진 변이에서 이 루프는 실제로 `C:\\etc\\...` 같은 자리에
        #   디렉터리를 만들었다. 실패한 검사가 파일시스템을 남기면 안 된다.
        #   이름이 QA 표식인 잎과, 그 뒤 비는 부모만 지운다(rmdir 은 비어야 지운다).
        if left:
            _cleanup_probe_dir(calculated)
    check_true("검사가 공허하지 않다 - 실제로 거절된 입력이 있다 (%d개)" % len(rejected),
               len(rejected) >= 4, rejected)

    # 대조군 — 정상 법원은 여전히 만들어진다(가드가 과하면 수집이 통째로 멈춘다).
    ok_dir = dp.get_doc_dir("QA경로법원", "2099타경QA", "1")
    check_true("대조군: 정상 법원은 그대로 만들어진다", os.path.isdir(ok_dir), ok_dir)
    check_true("대조군: 그 경로는 root 안이다",
               os.path.commonpath([os.path.abspath(ok_dir), root]) == root, ok_dir)
    # 뒷정리 - 이 검사가 만든 것만 지운다(역순으로 빈 디렉터리만).
    for d in (ok_dir, os.path.dirname(ok_dir), os.path.dirname(os.path.dirname(ok_dir))):
        try:
            os.rmdir(d)
        except OSError:
            break


# ---------------------------------------------------------------------------
# 6. ★ 세 소비자가 같은 디렉터리를 가리킨다
# ---------------------------------------------------------------------------
def test_all_consumers_agree():
    print("\n--- 6. 문서 / 사진 / 형제탐색이 같은 경로를 본다 ---")
    import crawler.doc_paths as dp
    import crawler.image_assets as ia

    for case_no in ("2024타경3528", "2024타경1451 / 2024타경32745", "a\\b"):
        doc_dir = os.path.normpath(dp._doc_dir_path("법원", case_no, "2"))
        # image_path -> <물건dir>/images/NN.ext 이므로 두 단계 위가 물건 디렉터리다.
        img_item_dir = os.path.normpath(
            os.path.dirname(os.path.dirname(ia.image_path("법원", case_no, "2", 1, "jpg"))))
        check("문서dir == 사진의 물건dir (%r)" % case_no[:20], img_item_dir, doc_dir)

        # find_sibling_case_document가 만드는 case_dir은 물건 디렉터리의 부모여야 한다.
        # (규칙이 어긋나면 case_dir을 못 찾아 형제 재사용이 **항상 실패**한다.)
        sib_case_dir = os.path.normpath(os.path.join(
            dp.DOCUMENT_ROOT, "법원", dp.sanitize_path_segment(case_no)))
        check("형제탐색 case_dir == 문서dir의 부모 (%r)" % case_no[:20],
              sib_case_dir, os.path.dirname(doc_dir))

    # ★ 2026-08-17 Sprint 164: **쓰는 쪽과 읽는 쪽의 뿌리**가 같은 곳인지 확인한다.
    #
    # 위 검사들은 크롤러 두 모듈(`doc_paths` / `image_assets`)끼리만 비교한다. 그런데
    # 실제로 그 파일을 **서빙하는 것은 API 쪽**(`api/v1/documents.py`,
    # `api/v1/images.py`)이고, 상태를 판정하는 것은 `repair_document_status.py`다.
    # 이들은 각자 `DOCUMENT_ROOT`를 따로 계산한다 — 파일 깊이가 달라 표현식도 다르다:
    #
    #     crawler/doc_paths.py         dirname(dirname(__file__))        (2단계)
    #     api/v1/documents.py          dirname(dirname(dirname(__file__))) (3단계)
    #     repair_document_status.py    dirname(__file__)                 (1단계)
    #
    # 지금은 셋 다 같은 곳으로 해석된다. 그러나 **파일이 옮겨지거나 단계 수가 어긋나면
    # 조용히 갈라진다.** 그때 나타나는 증상이 이 저장소의 단골이다 — 크롤러는 저장했고
    # `document_status`는 READY인데 서빙만 404다(화면은 "수집완료"라고 말한다).
    # 표현식이 아니라 **해석된 실제 경로**를 비교해야 잡힌다.
    import api.v1.documents as _apidocs
    import repair_document_status as _repair

    roots = {
        "crawler/doc_paths.py": dp.DOCUMENT_ROOT,
        "crawler/image_assets.py": ia.DOCUMENT_ROOT,
        "api/v1/documents.py": _apidocs.DOCUMENT_ROOT,
        "repair_document_status.py": _repair.DOCUMENT_ROOT,
    }
    resolved = {k: os.path.realpath(v) for k, v in roots.items()}
    distinct = sorted(set(resolved.values()))
    check("모든 소비자의 DOCUMENT_ROOT가 같은 곳을 가리킨다", len(distinct), 1)
    if len(distinct) != 1:
        for k, v in sorted(resolved.items()):
            print("      %-32s %s" % (k, v))

    # 대조군 — 뿌리가 실제로 저장소 안의 documents/ 인지도 본다(전부 같지만 엉뚱한 곳일 수 있다).
    expected = os.path.realpath(os.path.join(ROOT, "documents"))
    check("그 경로가 저장소의 documents/ 이다", distinct[0], expected)

    # ★ 뿌리만 같은 것으로는 부족하다 — **경로 생성기 자체**를 대조한다 (2026-09-04).
    #
    #   위 검사는 `DOCUMENT_ROOT` 네 개가 같은 곳인지만 본다. 그런데 그 뿌리 위에
    #   경로를 **조립하는 식**도 세 벌이었다:
    #
    #       crawler/doc_paths._doc_dir_path()
    #       api/v1/documents.get_doc_dir()
    #       repair_document_status.get_doc_dir()
    #
    #   셋 다 `join(root, court, sanitize(case), sanitize(item or '1'))` 를 손으로
    #   적고 있었고, **이미 갈라져 있었다** — `repair_document_status` 만 법원 조각에
    #   `or ""` 를 붙여, `court_name=None` 에서 예외 대신 **한 단계 위 경로**를 돌려줬다:
    #
    #       canon / api  ->  TypeError
    #       repair       ->  <ROOT>/<사건>/<물건>      (조용히 틀렸고 root 안이라 담김 검사도 통과)
    #
    #   그 경로에 파일이 있으면 `repair_document_status` 가 엉뚱한 근거로
    #   `document_status` 를 READY 로 바꾼다 — 그 스크립트가 없애려던 상태 그대로다.
    #
    #   2026-09-04 에 셋을 하나로 모았다. 여기서 그것을 고정한다.
    probes = [
        ("강릉지원", "2024타경3528", "1"),
        ("서울중앙지방법원", "2024타경1451 / 2024타경32745", "2"),
        ("법원", "a\\b", "1"),
        ("법원", "..", "1"),
        ("법원", "2024타경1", ""),
        ("법원", "2024타경1", None),
        ("", "2024타경1", "1"),
        (None, "2024타경1", "1"),          # <- 갈라져 있던 바로 그 입력
        ("   ", "2024타경1", "1"),
    ]

    def _call(fn, args):
        """경로 문자열 또는 예외 이름. 둘 다 계약이므로 함께 비교한다."""
        try:
            return os.path.normpath(fn(*args))
        except Exception as exc:            # noqa: BLE001 - 예외 종류도 계약이다
            return "!" + type(exc).__name__

    builders = [
        ("crawler/doc_paths._doc_dir_path", dp._doc_dir_path),
        ("api/v1/documents.get_doc_dir", _apidocs.get_doc_dir),
        ("repair_document_status.get_doc_dir", _repair.get_doc_dir),
    ]
    disagreements = []
    for args in probes:
        answers = {name: _call(fn, args) for name, fn in builders}
        if len(set(answers.values())) != 1:
            disagreements.append((args, answers))
    check("★ 세 경로 생성기가 모든 입력에서 같은 답을 낸다", disagreements, [])

    # 검사가 공허하지 않다 — 정상 입력에서 실제 경로가 나오는지(전부 예외면 무의미).
    normal = _call(dp._doc_dir_path, probes[0])
    check_true("검사가 공허하지 않다 - 정상 입력이 실제 경로를 낸다",
               not normal.startswith("!") and "강릉지원" in normal, normal)
    # 그리고 셋이 실제로 **서로 다른 함수 객체**인지도 본다(같은 것을 세 번 부르면 공허하다).
    check_true("검사가 공허하지 않다 - 서로 다른 세 진입점을 불렀다",
               len({id(fn) for _, fn in builders}) == 3,
               [n for n, _ in builders])


# ---------------------------------------------------------------------------
# 7. ★ 규칙 사본이 다시 생기지 않았는가 (소스 대조)
# ---------------------------------------------------------------------------
def test_no_new_copies_of_the_rule():
    """저장소 **전체**를 훑는다 — 목록으로 지정하지 않는다.

    ## 왜 목록을 버렸나 (2026-08-17 Sprint 161)

    이 검사는 원래 파일 목록을 들고 있었고, **그 목록에서 빠진 파일 때문에 두 번
    연속으로 규칙 사본을 놓쳤다.**

        Sprint 145   sanitize_path_segment() 로 규칙을 한 곳에 모았다
        Sprint 153   repair_document_status.py 가 목록에 없어 옛 사본이 살아남았다 -> 목록에 추가
        Sprint 160   backfill_doc_raw.py 가 목록에 없어 또 살아남았다 (4곳)

    목록을 한 줄 더 늘리는 것은 **세 번째를 예약하는 일**이다. `docs/BUGS.md` 의 교훈도
    같은 말을 한다 — *"목록으로 대상을 지정하는 검사는 목록에서 빠진 파일을 영원히 못
    본다. 새 파일이 생길 때 목록을 갱신하는 규율이 없다면, 목록이 아니라 전수 스캔으로
    짜야 한다."* 그래서 전수 스캔으로 바꿨다.

    스캔에서 제외하는 것은 두 가지뿐이고, 둘 다 이유가 분명하다.

      - `sanitize_path_segment()` 자신의 구현 한 줄  = 정당한 유일한 사본
      - 주석                                        = 코드가 아니다(사고 이력 인용을
        위반으로 잡으면 "왜 고쳤는지 남기는 일"과 검사가 싸운다)
    """
    print("\n--- 7. 정규화 규칙 사본이 다시 생기지 않았다 (전수 스캔) ---")

    # 전수 스캔 — 저장소의 모든 .py 를 본다. 테스트 파일은 규칙을 **검증**하느라
    # 옛 패턴을 문자열로 들고 있을 수 있어 제외한다(이 파일 자신이 그렇다).
    skip_dirs = {".git", "node_modules", ".next", "__pycache__", "htmlcov",
                 ".claude", "logs", "venv", ".venv"}
    scanned = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in filenames:
            if name.endswith(".py") and not name.startswith("test_"):
                scanned.append(os.path.join(dirpath, name))

    pattern = re.compile(r'\.replace\(\s*["\']/["\']\s*,\s*["\']_["\']\s*\)')
    offenders = []
    for path in sorted(scanned):
        try:
            src = open(path, encoding="utf-8-sig").read()
        except OSError:
            continue
        # 주석은 코드가 아니다. 줄 번호는 유지한 채 주석 줄만 비운다
        # (그래야 실제 위반의 위치가 정확히 나온다).
        body = "\n".join(
            "" if l.lstrip().startswith("#") else l for l in src.splitlines()
        )
        # sanitize_path_segment() 자신의 구현 한 줄은 정당한 단 하나의 사본이다.
        if "def sanitize_path_segment" in body:
            body = body.replace(
                '.replace("/", "_").replace("\\\\", "_")', "<<CANONICAL>>", 1)
        for m in pattern.finditer(body):
            line = body[:m.start()].count("\n") + 1
            offenders.append("%s:%d" % (os.path.relpath(path, ROOT), line))

    print("      스캔한 .py 파일: %d개" % len(scanned))
    check_true("스캔 대상이 실제로 모였다(0개면 검사가 비어 있다)", len(scanned) > 20, len(scanned))
    check_true(
        "★ 인라인 '/'->'_' 치환 사본이 없다 (sanitize_path_segment()를 쓸 것)",
        not offenders,
        offenders,
    )



# ---------------------------------------------------------------------------
# 8. ★ 읽기 전용 스캔이 디스크에 디렉터리를 만들지 않는가 (2026-08-17 Sprint 153, BUGS #111)
#
# `get_doc_dir()`은 `os.makedirs()`를 부르고 `_doc_dir_path()`는 경로만 계산한다.
# 이 저장소는 그 둘을 섞어 쓴 탓에 **"이 문서 있어요?"라고 묻기만 해도 디렉터리가 생기는**
# 사고를 겪었다(빈 물건 디렉터리 1,674개 = 파일 있는 202개를 더하면 정확히 auction_item
# 1,876행). 2026-08-14에 `doc_exists()`는 고쳤는데 `repair_empty_status_capture.py`에는
# 적용이 빠져 있었다 — 그 스크립트는 물건 전수를 훑는 읽기 전용 도구다.
#
# 여기서는 두 가지를 고정한다.
#   (a) `_doc_dir_path()`는 절대 디스크를 건드리지 않는다.
#   (b) 읽기 전용 스캐너가 생성 함수를 import하지 않는다(소스 대조).
# ---------------------------------------------------------------------------
def test_readonly_lookup_never_creates_directories():
    print("\n--- 8. 읽기 전용 조회가 디렉터리를 만들지 않는다 ---")
    import crawler.doc_paths as dp

    probe = ("QA경로검사법원", "9999타경00001", "3")
    path = dp._doc_dir_path(*probe)
    # 사전 정리 — 이전 실행 잔재가 있으면 검사가 무의미해진다.
    for d in (path, os.path.dirname(path), os.path.dirname(os.path.dirname(path))):
        try:
            os.rmdir(d)
        except OSError:
            pass

    check("_doc_dir_path()는 경로만 계산한다(호출 전 없음)", os.path.exists(path), False)
    again = dp._doc_dir_path(*probe)
    check("_doc_dir_path()를 불러도 생기지 않는다", os.path.exists(again), False)

    # 대조군 — 생성 함수는 실제로 만든다(둘이 정말 다른 함수임을 확인).
    created = dp.get_doc_dir(*probe)
    check("get_doc_dir()는 만든다(대조군)", os.path.exists(created), True)
    for d in (created, os.path.dirname(created), os.path.dirname(os.path.dirname(created))):
        try:
            os.rmdir(d)
        except OSError:
            pass
    check("검사 흔적을 지웠다", os.path.exists(created), False)

    # (b) 읽기 전용 스캐너는 생성 함수를 import하면 안 된다.
    readonly_scanners = ["repair_empty_status_capture.py", "empty_doc_dirs_dryrun.py",
                         "cleanup_orphans_dryrun.py"]
    offenders = []
    for name in readonly_scanners:
        fp = os.path.join(ROOT, name)
        if not os.path.exists(fp):
            continue
        src = open(fp, encoding="utf-8-sig").read()
        # 주석은 걷어내고 실제 import 문만 본다.
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        if re.search(r"^\s*from\s+crawler\.doc_paths\s+import[^\n]*get_doc_dir",
                     code, re.M):
            offenders.append(name)
    check("읽기 전용 스캐너가 get_doc_dir()를 import하지 않는다", offenders, [])

    # ── (c) 조회 API 를 **실제로 불러 본다** (2026-09-02 추가) ────────────────
    #
    #   위 (a) 는 `_doc_dir_path()` 만 본다. 그런데 사고를 낸 것은 그 함수가 아니라
    #   **`doc_exists()`** 였다 - 그 함수가 `get_doc_dir()` 을 부르는 바람에
    #   "이 문서 있어요?" 라고 묻기만 해도 빈 디렉터리가 쌓였다(실측 잔재 1,832개가
    #   지금도 `documents/` 에 남아 있다). 2026-08-14 에 `_doc_dir_path()` 로 바꿔
    #   고쳤지만, **그 상태를 지키는 검사는 없었다** - 되돌려도 아무도 모른다.
    probe_dirs = [dp._doc_dir_path(*probe),
                  os.path.dirname(dp._doc_dir_path(*probe)),
                  os.path.dirname(os.path.dirname(dp._doc_dir_path(*probe)))]

    def _cleanup_probe():
        for d in probe_dirs:
            try:
                os.rmdir(d)
            except OSError:
                pass

    # 전체 디렉터리 수를 세지 않는다 - doc_worker 가 동시에 돌면 그 수가 흔들려
    # 이 검사가 간헐 실패한다(이 저장소가 이미 겪은 flaky 부류). **프로브 경로가
    # 생겼는가**만 본다: 결정적이고, 남이 무엇을 만들든 영향을 받지 않는다.
    _cleanup_probe()
    before = [d for d in probe_dirs if os.path.exists(d)]
    check("검사 시작 시 프로브 경로가 없다", before, [])
    #   `canonical_doc_path()` 는 **여기서 부르지 않는다** - 이름과 달리 조회가 아니라
    #   **저장 경로 헬퍼**다(유일한 호출부 `collect_documents.py:finalize_download()` 가
    #   바로 다음 줄에서 `os.replace()` 로 쓴다. 목적지 디렉터리가 없으면 그 이동이
    #   실패하므로 거기서는 만드는 것이 맞다). 아래 (d) 의 허용 목록에 그래서 들어 있다.
    dp.doc_exists(probe[0], probe[1], probe[2], "spec")
    dp.existing_doc_files(probe[0], probe[1], probe[2], "spec")
    after = [d for d in probe_dirs if os.path.exists(d)]
    check("★ 조회 API 를 불러도 디렉터리가 생기지 않는다", after, [])
    _cleanup_probe()

    # ── (d) 앞으로 생길 조회 함수까지 본다 (구조) ────────────────────────────
    #
    #   (c) 는 **지금 아는 함수 셋**만 부른다. 내일 조회 함수가 하나 더 생기면
    #   그 목록에 안 들어가고, 같은 사고가 세 번째로 난다 - 이미 두 번 났다
    #   (`doc_paths.doc_exists`, 그리고 사진 쪽에서 같은 교훈을 다시 배웠다:
    #   `crawler/image_assets.py` 주석 참고).
    #
    #   그래서 두 모듈을 통째로 훑는다. **디렉터리를 만들어도 되는 함수는 정해져 있고**
    #   (쓰기 직전에 부르는 것), 나머지는 만들면 안 된다. 이름 목록을 여기 베끼지
    #   않고 모듈에서 함수를 뽑으므로 새 함수가 자동으로 대상이 된다.
    import ast

    #   ★ 허용 목록에 이름을 넣는 기준은 "만들어도 되는가" 가 아니라
    #     **"쓰기 직전인가"** 다. `canonical_doc_path()` 는 이름이 조회처럼 보이지만
    #     저장 경로를 만들어 돌려주는 함수이고, 호출부가 곧바로 `os.replace()` 한다.
    #     조회 목적으로 이 함수를 쓰면 그 순간 다시 사고가 된다 - 조회는
    #     `_doc_dir_path()` / `doc_exists()` 를 쓰라.
    DIR_CREATORS = {
        os.path.join("crawler", "doc_paths.py"): {"get_doc_dir", "canonical_doc_path"},
        os.path.join("crawler", "image_assets.py"): {"ensure_image_dir"},
    }
    CREATOR_CALLS = {"makedirs", "mkdir", "get_doc_dir", "ensure_image_dir"}

    creators_seen, scanned, makers = [], 0, []
    for rel, allowed in DIR_CREATORS.items():
        try:
            src = open(os.path.join(ROOT, rel), encoding="utf-8-sig").read()
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            scanned += 1
            calls = set()
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    calls.add(getattr(n.func, "id", None)
                              or getattr(n.func, "attr", None))
            hit = sorted(calls & CREATOR_CALLS)
            if fn.name in allowed:
                if hit:
                    creators_seen.append(fn.name)
                continue
            if hit:
                makers.append("%s:%s() -> %s"
                              % (rel.replace(os.sep, "/"), fn.name, ", ".join(hit)))

    check_true("검사가 공허하지 않다(두 모듈의 함수를 훑었다) - %d개" % scanned,
               scanned >= 15, scanned)
    # 대조군 - 만들어도 되는 함수는 **실제로 만들고 있어야** 한다. 그렇지 않으면
    # CREATOR_CALLS 가 안 맞는다는 뜻이고, 그러면 아래 판정이 통째로 공허해진다.
    check("대조군: 생성 담당 함수가 실제로 생성 호출을 갖고 있다",
          sorted(creators_seen), ["canonical_doc_path", "ensure_image_dir", "get_doc_dir"])
    check("★ 생성 담당 함수 외에는 디렉터리를 만들지 않는다", makers, [])



# ---------------------------------------------------------------------------
# 9. 서빙 쪽 가드가 **막아야 할 입력에서 스스로 죽지 않는가**
#    (2026-08-26, `docs/BUGS.md` #229)
# ---------------------------------------------------------------------------
#
# 위 5번은 **경로를 만드는 쪽**(크롤러)이 root 를 벗어나지 않는지 본다.
# 이 검사는 반대쪽 — **DB 에 이미 이상한 값이 들어 있을 때 서빙 라우트가 어떻게 되는가**다.
#
# 실측으로 드러난 것: `os.path.commonpath()` 는 두 경로의 **드라이브가 다르면
# ValueError 를 던진다**(Windows). 그리고 `os.path.join(root, "D:/evil")` 은
# 베이스를 통째로 갈아치워 정확히 그 상황을 만든다.
#
#     os.path.join('C:/proj/documents', 'D:/evil')  ->  'D:/evil'
#     os.path.commonpath(['C:/proj/documents', 'D:/evil.txt'])  ->  ValueError
#
# 그래서 **막아야 할 입력에서 가드 자신이 죽어** 404 가 아니라 500 이 나갔다.
# 파일이 새지는 않았지만, 방어가 거절 대신 붕괴하는 것은 그 자체로 결함이다.
#
# ★ 저장소는 이 함정을 **이미 알고 있었다.** `api/v1/admin.py` /
#   `crawler/image_assets.py` / `repair_document_status.py` 세 곳은 ValueError 를
#   잡아 "밖"으로 처리한다. 그런데 **서빙 라우트 세 곳이 그 정리에서 빠져 있었다** —
#   심지어 `api/v1/registry.py` 는 주석으로 *"documents.py 와 동일한 방식"* 이라며
#   고쳐지지 않은 판을 베껴 왔다. 복제된 판정은 결함까지 함께 복제된다.


def test_serving_guard_survives_uncomparable_paths():
    """DB 에 드라이브가 다른 경로가 들어 있어도 404 로 거절한다(500 이 아니다)."""
    print("\n--- 9. 서빙 가드가 비교 불가 경로에서 죽지 않는다 (BUGS #229) ---")
    import contextlib
    import io as _io
    import shutil
    import tempfile

    import storage.database as dbmod
    import storage.migrate_v4_1 as mig
    import storage.migrations.run_migrations as runmig

    work = tempfile.mkdtemp(prefix="qa_serve_")
    orig_db = dbmod.DB_PATH
    secret = os.path.join(work, "SECRET.txt")
    _io.open(secret, "w", encoding="utf-8").write("TOP-SECRET-CONTENT")
    try:
        dbmod.DB_PATH = os.path.join(work, "t.db")
        with contextlib.redirect_stdout(_io.StringIO()):
            dbmod.init_db()
            mig.migrate()
            runmig.run()

        conn = dbmod.get_connection()
        cid = conn.execute("INSERT INTO auction_case (court_code,case_no) VALUES (?,?)",
                           ("서울중앙지방법원", "2024타경1")).lastrowid
        conn.execute("INSERT INTO auction_item (id,case_id,case_no,item_no,court_name,auction_date)"
                     " VALUES (1,?,'2024타경1','1','서울중앙지방법원','2099-01-01')", (cid,))
        # ★ 핵심 입력: 드라이브가 다른 절대경로. join 이 베이스를 갈아치운다.
        hostile = ["D:/evil.txt", "D:evil.txt", "Z:/x/y.jpg",
                   "../../../../Windows/win32.ini", os.path.abspath(secret)]
        for seq, p in enumerate(hostile, 1):
            conn.execute("INSERT INTO auction_image (item_id,seq,kind,storage_path,file_size,width,height)"
                         " VALUES (1,?,'PHOTO',?,10,4,4)", (seq, p))
        # 문서 경로는 court_name 으로 만들어진다 — 드라이브 문자를 넣어 escape 시킨다.
        conn.execute("INSERT INTO auction_case (court_code,case_no) VALUES ('D:','2024타경9')")
        conn.execute("INSERT INTO auction_item (id,case_id,case_no,item_no,court_name,auction_date)"
                     " VALUES (2,(SELECT id FROM auction_case WHERE court_code='D:'),"
                     "'2024타경9','1','D:','2099-01-01')")
        conn.commit()
        conn.close()

        from fastapi.testclient import TestClient
        from api_server import app
        client = TestClient(app)

        checked = 0
        for seq, p in enumerate(hostile, 1):
            try:
                r = client.get("/api/v1/item/1/images/%d" % seq)
                code, body = r.status_code, r.content[:64]
            except Exception as exc:  # noqa: BLE001
                code, body = "EXC:%s" % type(exc).__name__, b""
            checked += 1
            check("사진 %r 는 404" % p[:26], code, 404)
            check_true("사진 %r 가 root 밖 내용을 주지 않는다" % p[:26],
                       b"SECRET" not in body, body[:40])
        for doc_type in ("SPEC", "STATUS"):
            try:
                code = client.get("/api/v1/item/2/documents/%s" % doc_type).status_code
            except Exception as exc:  # noqa: BLE001
                code = "EXC:%s" % type(exc).__name__
            checked += 1
            check("문서(court_name='D:') %s 는 404" % doc_type, code, 404)

        check_true("검사가 공허하지 않다(실제로 요청을 보냈다)", checked >= 7, checked)
    finally:
        dbmod.DB_PATH = orig_db
        shutil.rmtree(work, ignore_errors=True)


def test_every_containment_check_handles_uncomparable_paths():
    """제품 코드의 **모든** `commonpath` 담기 검사가 ValueError 를 다루는가.

    위 검사는 라우트 세 개를 직접 태운다. 이 검사는 **다음에 생길 네 번째**를 막는다 —
    결함이 "여섯 곳 중 세 곳만 고쳐져 있었다" 였으므로, 라우트별로 세는 것만으로는
    같은 일이 또 일어난다.
    """
    print("\n--- 9-b. commonpath 담기 검사가 전부 ValueError 를 다루는가 ---")
    import glob
    import io as _io

    targets = []
    for pattern in ("api/**/*.py", "crawler/**/*.py", "storage/**/*.py", "*.py"):
        for path in glob.glob(os.path.join(ROOT, pattern), recursive=True):
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            if rel.startswith("test_") or "/worktrees/" in rel:
                continue
            targets.append((rel, path))

    sites, unsafe = 0, []
    for rel, path in sorted(set(targets)):
        try:
            src = _io.open(path, encoding="utf-8-sig").read()
        except OSError:
            continue
        lines = src.split("\n")
        for i, line in enumerate(lines):
            if "os.path.commonpath" not in line or line.strip().startswith("#"):
                continue
            sites += 1
            # 이 호출을 감싸는 try 가 위쪽 12줄 안에 있고, 아래쪽에 ValueError 를 잡는가.
            window_up = "\n".join(lines[max(0, i - 12):i + 1])
            window_dn = "\n".join(lines[i:i + 12])
            # ★ `except (OSError, ValueError)` 같은 튜플 형태도 안전하다.
            #   처음에는 `"except ValueError"` 문자열만 봤다가 `crawler/image_assets.py`
            #   를 **거짓 양성으로 잡았다** — 그 자리는 이미 튜플로 막고 있었다.
            #   가드가 멀쩡한 코드를 결함이라고 부르면 사람이 가드를 끄게 된다.
            guarded = ("try:" in window_up) and any(
                ln.lstrip().startswith("except") and "ValueError" in ln
                for ln in window_dn.split("\n"))
            if not guarded:
                unsafe.append("%s:%d  %s" % (rel, i + 1, line.strip()[:60]))

    # 검사가 공허하지 않다 — 대상을 실제로 찾았는가.
    check_true("commonpath 사용처를 실제로 찾았다(검사가 공허하지 않다)", sites >= 5, sites)
    check("★ ValueError 를 다루지 않는 commonpath 검사", unsafe, [])
    if unsafe:
        print("      드라이브가 다른 경로가 오면 이 자리에서 500 이 난다:")
        for u in unsafe:
            print("        " + u)
    print("    훑은 commonpath 사용처 %d곳" % sites)

    # ★ 검출기 자체 검증 — 규칙이 실제로 두 모양을 가려내는가.
    def _judge(snippet):
        ls = snippet.split("\n")
        for i, ln in enumerate(ls):
            if "os.path.commonpath" in ln and not ln.strip().startswith("#"):
                up = "\n".join(ls[max(0, i - 12):i + 1])
                dn = "\n".join(ls[i:i + 12])
                return ("try:" in up) and any(
                    x.lstrip().startswith("except") and "ValueError" in x
                    for x in dn.split("\n"))
        return None
    good = "    try:\n        x = os.path.commonpath([a, b])\n    except ValueError:\n        x = None"
    tup = "    try:\n        x = os.path.commonpath([a, b])\n    except (OSError, ValueError):\n        x = None"
    bad = "    x = os.path.commonpath([a, b]) != a"
    other = "    try:\n        x = os.path.commonpath([a, b])\n    except OSError:\n        x = None"
    check("검출기 자체 검증: 감싼 형태를 안전하다고 본다", _judge(good), True)
    check("검출기 자체 검증: 튜플 except 도 안전하다고 본다", _judge(tup), True)
    check("검출기 자체 검증: 맨 호출을 위험하다고 본다", _judge(bad), False)
    check("검출기 자체 검증: ValueError 를 안 잡으면 위험하다고 본다", _judge(other), False)


# ---------------------------------------------------------------------------
# 10. "있다"의 크기 하한을 **실제 파일로** 못박는다 (2026-08-26, `docs/BUGS.md` #238)
#
# 경계 변이(`getsize >= MIN_IMAGE_BYTES` -> `>`)가 살아남아 추가했다.
# 정확히 하한값인 파일이 어느 쪽으로 판정되는지를 아무도 검사하지 않고 있었다.
#
# 문서와 사진은 **하한도 방향도 다르다.** 그 차이가 의도라는 것을 값으로 고정한다 —
# 나중에 누가 "둘을 통일하자"며 한쪽을 옮기면 여기서 먼저 걸린다.
#
#     문서  getsize > 0                 -> 1바이트도 '있다'
#     사진  getsize >= MIN_IMAGE_BYTES  -> 1024바이트부터 '있다'
# ---------------------------------------------------------------------------
def test_existence_size_floor_is_exact():
    print("\n--- 10. '있다'의 크기 하한 경계 (BUGS #238) ---")
    import shutil
    import tempfile
    import crawler.image_assets as ia
    import crawler.doc_paths as dp

    work = tempfile.mkdtemp(prefix="qa_floor_")
    old_ia, old_dp = ia.DOCUMENT_ROOT, dp.DOCUMENT_ROOT
    ia.DOCUMENT_ROOT = dp.DOCUMENT_ROOT = work
    try:
        check_true("전제: 사진 하한이 양수다(검사가 공허하지 않다)",
                   ia.MIN_IMAGE_BYTES > 0, ia.MIN_IMAGE_BYTES)
        floor = ia.MIN_IMAGE_BYTES

        p = ia.image_path("법원", "2024타경1", "1", 1, "jpg")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        for size, expected in ((floor - 1, False), (floor, True), (floor + 1, True), (0, False)):
            with open(p, "wb") as fh:
                fh.write(b"\0" * size)
            check("★ 사진 %d바이트 -> image_exists" % size,
                  ia.image_exists("법원", "2024타경1", "1", 1, "jpg"), expected)
        os.remove(p)

        # 문서 쪽은 하한이 **0** 이고 방향도 다르다 — 같이 고정해 둔다.
        d = dp.get_doc_dir("법원", "2024타경1", "1")
        os.makedirs(d, exist_ok=True)
        fp = os.path.join(d, dp.CANONICAL_DOC_FILENAME["SPEC"])
        for size, expected in ((0, False), (1, True), (floor - 1, True)):
            with open(fp, "wb") as fh:
                fh.write(b"\0" * size)
            check("★ 문서 %d바이트 -> doc_exists" % size,
                  dp.doc_exists("법원", "2024타경1", "1", "SPEC"), expected)
        os.remove(fp)

        # ★ 서빙 쪽이 이 함수의 **여집합**인지도 소스로 고정한다.
        #   한쪽만 옮기면 "화면은 READY인데 뷰어는 404" 가 된다 — 이 파일의 docstring 이
        #   경고하는 바로 그 상태다.
        img_src = open(os.path.join(ROOT, "api", "v1", "images.py"),
                       encoding="utf-8-sig").read()
        check_true("★ 서빙도 같은 상수를 쓴다(하드코딩하지 않는다)",
                   "MIN_IMAGE_BYTES" in img_src,
                   "-> 서빙이 자기 숫자를 들면 두 쪽이 조용히 갈라진다")
        check_true("★ 서빙의 거절 조건이 여집합(`< MIN_IMAGE_BYTES`)이다",
                   "< MIN_IMAGE_BYTES" in img_src,
                   "-> `<=` 로 바뀌면 정확히 하한인 사진이 404 가 된다")

        # ★★ 세 번째 다리 — **DB 행을 만드는 단계**도 같은 경계여야 한다.
        #
        #   처음 이 검사를 쓸 때는 쓰기(image_exists)와 서빙만 못박았다. 그런데
        #   변이 `size < MIN` -> `size <= MIN` (`storage/database.py:save_auction_images`)이
        #   **살아남았다.** 그 상태에서 벌어지는 일은 #148 의 정반대다:
        #
        #       정확히 1024바이트 사진 -> 파일은 디스크에 있고 서빙도 200 인데
        #       auction_image 행이 **안 생긴다** -> image_count=0, 썸네일 없음
        #       => 받아 놓고도 사용자에게 영원히 안 보인다
        #
        #   `api/v1/thumbnails.py` 는 크기를 보지 않고 `auction_image` 행만 읽으므로,
        #   이 단계가 어긋나면 목록·상세·서빙 셋이 서로 다른 말을 한다.
        #   **세 다리가 같은 경계를 써야 한다.**
        db_src = open(os.path.join(ROOT, "storage", "database.py"), encoding="utf-8-sig").read()
        # ★ 이름이 **등장하는지**가 아니라 **정본에서 import 하는지**를 본다.
        #   `"MIN_IMAGE_BYTES" in db_src` 로 썼다가 변이
        #   `_MIN_IMAGE_BYTES = 2048  # 자기 숫자` 를 **놓쳤다** — 그 줄에도 이름이 들어 있다.
        #   BUGS #232 에서 겪은 부분 문자열 함정과 같은 모양이다.
        _imports_const = re.search(r"from\s+crawler\.image_assets\s+import[^\n]*\bMIN_IMAGE_BYTES\b", db_src)
        check_true("★ DB 기록 단계가 정본 상수를 **import** 한다(자기 숫자를 들지 않는다)",
                   _imports_const is not None,
                   "-> 하드코딩하면 목록/서빙과 조용히 갈라진다")
        check_true("★ DB 기록 단계에 하드코딩된 하한이 없다",
                   re.search(r"_MIN_IMAGE_BYTES\s*=\s*\d+", db_src) is None,
                   "-> 숫자를 직접 대입한 자리가 있다")
        check_true("★ DB 기록의 거절 조건이 `< MIN` 이다(하한 자체는 받아들인다)",
                   "size < _MIN_IMAGE_BYTES" in db_src,
                   "-> `<=` 면 정확히 하한인 사진이 **행 없이** 디스크에만 남는다")
        # 썸네일이 크기를 보지 않는다는 전제도 함께 고정한다 — 이 전제가 깨지면
        # 위 세 다리 말고 네 번째 판정자가 생긴 것이다.
        th_src = open(os.path.join(ROOT, "api", "v1", "thumbnails.py"), encoding="utf-8-sig").read()
        check_true("전제: 썸네일은 크기를 판정하지 않는다(auction_image 행만 읽는다)",
                   "MIN_IMAGE_BYTES" not in th_src and "getsize" not in th_src,
                   "-> 썸네일이 자기 기준을 가지면 판정자가 넷이 된다")
    finally:
        ia.DOCUMENT_ROOT, dp.DOCUMENT_ROOT = old_ia, old_dp
        shutil.rmtree(work, ignore_errors=True)


def test_size_floor_holds_end_to_end_at_runtime():
    """하한 경계를 **소스가 아니라 실제 실행**으로 확인한다 (2026-08-26, BUGS #238).

    위 10번은 세 다리가 같은 상수·같은 방향을 쓰는지를 **소스로** 본다. 그것만으로는
    "정말 그렇게 동작하는가"를 말할 수 없다 — 경로 해석·호출 순서·조기 반환 같은 것이
    끼면 소스가 옳아도 결과가 다를 수 있다.

    그래서 임시 DB + 임시 documents 루트를 만들고 `save_auction_images()` 를 **실제로
    불러** 세 값(하한-1 / 하한 / 하한+1)이 다음 넷에서 어떻게 되는지 한 번에 본다.

        saved 개수 -> auction_image 행 -> 썸네일 seq -> 서빙 응답

    ★ 이 검사를 쓰다가 **내가 먼저 틀렸다.** 처음에는 `path` 에 프로젝트 상대경로를
      넘겼는데, `save_auction_images()` 는 `os.path.getsize(path)` 를 **준 그대로** 쓴다.
      그래서 1024바이트도 `saved=0` 이 나왔고 하마터면 "하한 가드가 과하다"고 오판할
      뻔했다. 실 호출부(`crawler/image_crawler.py`)가 넘기는 것은 `image_path()` 가
      돌려주는 **절대경로**다. 이 검사도 같은 형태로 넘긴다.
    """
    print("\n--- 11. 하한 경계 end-to-end 실행 검증 (BUGS #238) ---")
    import contextlib
    import io as _io
    import shutil
    import tempfile

    import storage.database as dbmod
    import storage.migrate_v4_1 as mig
    import storage.migrations.run_migrations as runmig
    import crawler.image_assets as ia
    import api.v1.images as apiimg
    import api.v1.thumbnails as th

    work = tempfile.mkdtemp(prefix="qa_floor_e2e_")
    orig_db = dbmod.DB_PATH
    old = (ia.DOCUMENT_ROOT, apiimg.DOCUMENT_ROOT, apiimg.PROJECT_ROOT)
    try:
        dbmod.DB_PATH = os.path.join(work, "t.db")
        docs = os.path.join(work, "documents")
        os.makedirs(docs)
        ia.DOCUMENT_ROOT = apiimg.DOCUMENT_ROOT = docs
        apiimg.PROJECT_ROOT = work
        with contextlib.redirect_stdout(_io.StringIO()):
            dbmod.init_db()
            mig.migrate()
            runmig.run()
        conn = dbmod.get_connection()
        try:
            cid = conn.execute("INSERT INTO auction_case (court_code,case_no) VALUES (?,?)",
                               ("서울중앙지방법원", "2024타경1")).lastrowid
            conn.execute("INSERT INTO auction_item (id,case_id,case_no,item_no,court_name,auction_date)"
                         " VALUES (1,?,'2024타경1','1','서울중앙지방법원','2099-01-01')", (cid,))
            conn.commit()
        finally:
            conn.close()

        from fastapi.testclient import TestClient
        from api_server import app
        client = TestClient(app)
        floor = ia.MIN_IMAGE_BYTES

        for seq, (size, want_row) in enumerate(
                ((floor - 1, False), (floor, True), (floor + 1, True)), start=1):
            path = ia.image_path("서울중앙지방법원", "2024타경1", "1", seq, "jpg")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(b"" + bytes([255, 216]) + bytes(size - 2))
            res = dbmod.save_auction_images(
                "서울중앙지방법원", "2024타경1", "1",
                [{"seq": seq, "kind": "PHOTO", "path": path, "file_size": size,
                  "file_hash": "h%d" % seq, "width": 4, "height": 4}], complete=False)
            conn = dbmod.get_connection()
            try:
                rows = conn.execute("SELECT COUNT(*) FROM auction_image WHERE seq=?",
                                    (seq,)).fetchone()[0]
                thumb = th.fetch_thumbnail_seqs(conn, [1]).get(1)
            finally:
                conn.close()
            served = client.get("/api/v1/item/1/images/%d" % seq).status_code

            check("★ %d바이트: save_auction_images saved" % size,
                  res.get("saved"), 1 if want_row else 0)
            check("★ %d바이트: auction_image 행" % size, rows, 1 if want_row else 0)
            check("★ %d바이트: 서빙 응답" % size, served, 200 if want_row else 404)
            if not want_row:
                # 행이 없으면 썸네일도 없어야 한다 -> "목록엔 보이는데 404" 가 성립 불가
                check("★ %d바이트: 썸네일이 가리키지 않는다(#148 이 성립 불가)" % size,
                      thumb, None)
            else:
                check_true("★ %d바이트: 썸네일이 이 사진을 가리킨다" % size,
                           thumb is not None, thumb)
    finally:
        dbmod.DB_PATH = orig_db
        ia.DOCUMENT_ROOT, apiimg.DOCUMENT_ROOT, apiimg.PROJECT_ROOT = old
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    test_normal_values_pass_through()
    test_multi_case_numbers()
    test_boundary_values()
    test_separators_are_neutralised()
    test_never_escapes_document_root()
    test_all_consumers_agree()
    test_no_new_copies_of_the_rule()
    test_readonly_lookup_never_creates_directories()
    test_serving_guard_survives_uncomparable_paths()
    test_every_containment_check_handles_uncomparable_paths()
    test_existence_size_floor_is_exact()
    test_size_floor_holds_end_to_end_at_runtime()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL DOC PATH SAFETY TESTS PASSED")
