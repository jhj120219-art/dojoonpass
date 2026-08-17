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


if __name__ == "__main__":
    test_normal_values_pass_through()
    test_multi_case_numbers()
    test_boundary_values()
    test_separators_are_neutralised()
    test_never_escapes_document_root()
    test_all_consumers_agree()
    test_no_new_copies_of_the_rule()
    test_readonly_lookup_never_creates_directories()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL DOC PATH SAFETY TESTS PASSED")
