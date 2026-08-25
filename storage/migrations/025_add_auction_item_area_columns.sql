-- 025_add_auction_item_area_columns.sql
--
-- [2026-08-26] `auction_item` 에 건물면적 / 토지면적 컬럼을 추가한다.
--
-- 왜 — **검색 폼에 이미 있는 입력이 아무 일도 하지 않고 있었다**
-- ---------------------------------------------------------------------------
-- `src/app/search/SearchForm.tsx` 는 건물면적·토지면적 입력을 그려 주고
-- `min_building_area` / `max_building_area` / `min_land_area` / `max_land_area` 를
-- 실제로 **보낸다.** 그런데 `auction_item` 에 대응 컬럼이 없어 `api/v1/search.py` 가
-- 그 파라미터를 읽지 않았다 — 사용자가 면적을 좁혀도 **결과가 그대로**다.
--
-- 오류도 없고 안내도 없다. 사용자는 "이 조건에 맞는 물건이 이렇게 많구나"라고 읽는다.
-- 이 저장소가 반복해서 경계해 온 **조용히 틀린** 부류다(소스에는 `TODO(API 미지원)` 이,
-- `test_search.py` 에는 그 사실을 고정하는 검사가 있었다).
--
-- 데이터는 이미 있다 (2026-08-26 실측, auction_item 2,444행)
-- ---------------------------------------------------------------------------
-- 면적은 `full_address` 원문의 대괄호 안에 규칙적으로 적혀 있다.
--
--     [집합건물 철근콘크리트구조 17.08㎡]                    -> 건물 17.08
--     [건물 ... 1층 75.60㎡ 2층 70.20㎡]                     -> 건물 145.80 (연면적 = 층 합)
--     [토지 대 420㎡]                                        -> 토지 420
--     [카니발 2016년식 승용차]                               -> 해당 없음
--
--     추출 결과   건물만 1,454(59.5%) / 토지만 974(39.9%) / 둘 다 0 / 없음 16(0.7%)
--     커버리지    **99.3%**   (없는 16행은 전부 차량·선박·건설기계다)
--
-- 추출 규칙의 정본은 `normalizer/normalizer.py:extract_areas()` 다 — 여기에 규칙을
-- 다시 적지 않는다(같은 어휘가 두 곳에 있으면 갈라진다, BUGS #204).
--
-- 왜 REAL 이고 왜 NULL 을 허용하는가
-- ---------------------------------------------------------------------------
-- 면적은 소수를 갖는다(17.08㎡). 그리고 **모르는 것은 NULL 로 둔다** — 0 으로 채우면
-- "면적 0㎡ 인 물건"이 되어 `min_building_area=0` 같은 검색에 걸린다. 값이 없는 것과
-- 0 인 것은 다르다. 검색 조건도 NULL 을 자연히 걸러 낸다(`col >= ?` 는 NULL 에 대해 거짓).
--
-- 안전성
-- ---------------------------------------------------------------------------
-- `ALTER TABLE ... ADD COLUMN` 은 기존 행을 건드리지 않는다(전부 NULL 로 시작).
-- 기존 컬럼·행·인덱스에 영향이 없고 되돌리기는 컬럼 두 개를 무시하면 된다.
-- 값 채우기는 이 파일이 하지 않는다 — `backfill_area.py` 가 따로 한다
-- (마이그레이션이 애플리케이션 로직을 import 하면 순환이 생기고, 백필은 dry-run 으로
--  먼저 확인할 수 있어야 한다. 이 저장소의 `backfill_doc_raw.py` 관례와 같다).
--
-- ★ SQLite 는 `ADD COLUMN` 에 IF NOT EXISTS 가 없다. 이미 있으면 러너가 예외로 죽는데,
--   러너는 파일명으로 적용 여부를 판단하므로 정상 경로에서는 두 번 실행되지 않는다.

ALTER TABLE auction_item ADD COLUMN building_area REAL;
ALTER TABLE auction_item ADD COLUMN land_area REAL;

-- 범위 검색(`min/max_building_area`)이 이 컬럼을 단독으로 훑는다.
-- migration 021 이 확인했듯 **좁은 인덱스가 범위/커버링 스캔에서 유리하다** —
-- 다른 열과 묶지 않고 각각 단독으로 둔다.
CREATE INDEX IF NOT EXISTS idx_auction_item_building_area
    ON auction_item(building_area);
CREATE INDEX IF NOT EXISTS idx_auction_item_land_area
    ON auction_item(land_area);
