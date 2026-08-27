"""한 번의 수집 실행이 실제로 무엇을 이뤘는지 담는 값 객체.

2026-08-11 Sprint 55 신설 (BUGS #47).

왜 `mvp_scraper.py`가 아니라 여기인가 — `mvp_scraper.py`는 import 한 줄만으로
`crawler.court_crawler` -> `selenium`을 끌어온다. 성패 판정 로직을 거기 두면
**selenium이 설치된 환경에서만 테스트할 수 있고**, 지금 이 저장소가 바로 그렇지 않다.
판정은 순수 산술이므로 의존성 없는 곳으로 분리해 테스트 가능하게 만든다.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CrawlOutcome:
    courts: int = 0                          # 시도한 법원 수
    skipped: List[str] = field(default_factory=list)  # 기일이 없어 건너뛴 법원 (정상)
    failed: List[str] = field(default_factory=list)   # 예외로 실패한 법원
    collected: int = 0                       # 크롤로 얻은 사건 수
    # ★ 크롤에는 성공했지만 **정규화에서 떨어져 나간** 건수 (2026-08-27, docs/BUGS.md #261)
    #
    #   `normalize_batch()` 는 행 하나가 기형이어도 나머지를 살리려고 그 행만 버린다
    #   (Sprint 78, 옳은 격리다). 그런데 **버렸다는 사실이 아무 데도 남지 않았다** —
    #   경고 한 줄이 로그로 나갈 뿐, 배치 요약도 `CrawlOutcome` 도 그 수를 몰랐다.
    #
    #   그래서 이런 날이 조용히 지나간다:
    #       수집 2,608건 -> 정규화 2,600건 -> 저장 2,600건 -> 종료코드 0
    #       법원에서 받아 온 8건이 DB 에 닿지 못했는데 아무도 모른다.
    #
    #   **전부** 떨어지면 `persisted == 0` 으로 잡히지만(그건 이미 있다), 부분 손실은
    #   지금까지 잡히는 곳이 한 곳도 없었다. 이 저장소가 #47 에서 고친
    #   "배치 로그가 사실이 아닌 것을 말한다"와 같은 계열이다.
    normalize_dropped: int = 0
    inserted: int = 0                        # DB 신규
    updated: int = 0                         # DB 갱신 (값이 실제로 바뀌어 쓴 것)
    unchanged: int = 0                       # DB에 이미 올바르게 있던 것 (쓸 필요가 없었다)
    upsert_failed: int = 0                   # DB 저장 실패

    @property
    def persisted(self) -> int:
        """실제로 DB에 남은 건수. 0이면 그 실행은 아무것도 이루지 못한 것이다.

        ## `unchanged`를 반드시 더한다 (2026-08-27, docs/BUGS.md #249)

        `upsert_batch()`는 값이 이미 같은 행에 UPDATE를 보내지 않는다(무의미한 쓰기 제거).
        그 행들은 `updated`가 아니라 `unchanged`로 돌아온다.

        **셋을 다 더하지 않으면 정상적인 날에 크롤이 실패로 판정된다.** 법원 자료가
        하루 종일 그대로면 `inserted=0, updated=0, unchanged=1876`이 되는데,
        `persisted`가 0이 되어 아래 `failure_reason()`이 "DB 저장 0건"을 돌려주고
        `run_daily.bat`이 exit 1로 멈춘다 — `migrate_execute.py`가 아예 실행되지 않는다.

        "찾았고 이미 올바르다"는 **저장에 성공한 것**이다. 실패는 `upsert_failed`다.
        """
        return self.inserted + self.updated + self.unchanged

    def failure_reason(self) -> Optional[str]:
        """치명적 실패면 사유 문자열, 아니면 None.

        '치명적'의 기준은 새 정책을 만든 것이 아니라 **명백한 것만** 잡는다.
        수집이 0건이거나 DB에 한 건도 남지 않았다면 그 실행은 목적을 달성하지 못했다.

        법원 몇 곳이 실패한 정도(부분 실패)는 사이트 사정으로 흔히 일어나므로
        경고만 남기고 성공으로 둔다 — 임계값을 임의로 정하면 그 자체가 새 정책이 되고,
        멀쩡한 실행이 매일 실패로 보고되면 경보가 무시당해 결국 같은 곳으로 돌아간다.

        2026-08-02 실측 사례가 정확히 여기 걸린다:
            법원 60곳 / 오류 59곳 / 스킵 1곳 / 저장 0건  ->  "수집 건수 0건"
        그때는 이 판정이 없어서 배치가 성공으로 끝났다.
        """
        if self.courts and len(self.failed) == self.courts:
            return "전 법원(%d곳) 수집 실패" % self.courts
        if self.collected == 0:
            return "수집 건수 0건 (오류 %d곳 / 스킵 %d곳)" % (len(self.failed), len(self.skipped))
        if self.persisted == 0:
            return "DB 저장 0건 (수집 %d건, 저장 실패 %d건)" % (self.collected, self.upsert_failed)
        return None

    def warnings(self) -> List[str]:
        """치명적이지는 않지만 **반드시 눈에 띄어야 하는** 것들 (2026-08-27, BUGS #261).

        치명적 실패로 만들지 않는 이유는 위 `failure_reason()` 의 판단과 같다 —
        임계값을 임의로 정하면 그 자체가 새 정책이 되고, 멀쩡한 실행이 매일 실패로
        보고되면 경보가 무시당한다. 대신 **숫자를 사실대로 내놓는다.**
        """
        out = []
        if self.normalize_dropped:
            out.append(
                "정규화에서 %d건이 떨어졌다 (수집 %d건 -> 저장 대상 %d건). "
                "크롤은 받아 왔는데 DB 에 닿지 못한 건수다 - logs/scraper.log 의 "
                "'normalize_item failed' 를 보라"
                % (self.normalize_dropped, self.collected,
                   self.collected - self.normalize_dropped))
        if self.failed:
            out.append("수집 실패 법원 %d곳: %s"
                       % (len(self.failed), ", ".join(self.failed[:10])))
        return out

    def exit_code(self) -> int:
        """배치가 읽을 종료 코드. 0=성공, 1=치명적 실패."""
        return 1 if self.failure_reason() else 0


@dataclass
class DocWorkerOutcome:
    """PDF 수집 Worker 한 번의 실행 결과.

    `doc_worker.py`도 `crawler.doc_crawler` -> `selenium`을 import하므로 판정만 여기로
    분리한다(`CrawlOutcome`과 같은 이유).
    """

    processed: int = 0   # 실제로 수집을 시도한 큐 항목 수
    succeeded: int = 0   # 그중 성공한 수

    def failure_reason(self) -> Optional[str]:
        """큐가 비어 아무것도 시도하지 않은 것(processed==0)은 정상이다 — 매일 도는
        워커이므로 할 일이 없는 날이 있다.

        시도했는데 **한 건도 성공하지 못한 것**은 다르다. 드라이버/사이트/선택자 중 하나가
        통째로 깨졌다는 신호이고, 조용히 지나가면 큐만 계속 쌓인다
        (2026-08-11 실측: pending 2,703건 / doc_raw 0행).
        """
        if self.processed > 0 and self.succeeded == 0:
            return "PDF 수집 %d건 시도, 성공 0건" % self.processed
        return None

    def exit_code(self) -> int:
        return 1 if self.failure_reason() else 0
