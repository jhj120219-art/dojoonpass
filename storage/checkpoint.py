"""`logs/` 아래 **파일로 관리하는 실행 상태** 두 가지.

    CheckpointManager   어디까지 했는가 (진행 상황)
    RunLock             지금 누가 하고 있는가 (배타성)

둘 다 "배치가 죽어도 다음 실행이 이어받을 수 있어야 한다"는 같은 요구에서 나왔고,
같은 규율을 쓴다 — **원자적 쓰기**(임시 파일 + `os.replace()`)와 **시간 기반 죽은
소유자 판정**이다. 새 의존성 없이 표준 라이브러리만 쓴다.

`RunLock` 은 2026-08-18 Sprint 194 에 여기로 왔다. 원래 `doc_worker.py` 안에 있었는데
(2026-08-16 Sprint 142), 같은 방어가 필요한 배치가 하나 더 생기면서
(`mvp_scraper.py`) **규칙을 베끼지 않으려고** 공용 자리로 올렸다 — 이 저장소는
"규칙이 두 벌"에서 반복해 사고를 겪었다(BUGS #107/#112/#136/#161).
"""
import json
import logging
import os
import time
from datetime import datetime
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class CheckpointManager:
    def __init__(self, path: str = "logs/checkpoint.json"):
        self.path = path

    def _write_atomic(self, data: Dict) -> None:
        """임시 파일에 다 쓴 뒤 os.replace()로 한 번에 바꾼다.

        목적지에 직접 쓰면 쓰기 도중 프로세스가 죽었을 때 체크포인트 파일이 반쯤 잘린
        JSON으로 남고, 다음 실행의 `_load_all()`이 그것을 파싱하지 못해 **크롤러가 진행
        상황을 통째로 잃는다**(모든 법원을 처음부터 다시 긁는다). `os.replace()`는
        같은 볼륨에서 원자적이라 목적지는 "이전 내용" 아니면 "새 내용" 둘 중 하나만 된다.
        (docs/BUGS.md #23 — 이 규칙이 코드에서 사라져 있던 것을 2026-08-10 Sprint 47에
        test_checkpoint_atomicity.py가 다시 잡아냈다.)
        """
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self.path)

    def save(self, court_code: str, case_no: str, completed: int, total: int) -> None:
        data = self._load_all()
        data[court_code] = {
            "last_case_no": case_no,
            "completed": completed,
            "total": total,
        }
        try:
            self._write_atomic(data)
        except Exception as e:
            logger.error("checkpoint save failed: %s", str(e))

    def get(self, court_code: str) -> Optional[Dict]:
        data = self._load_all()
        return data.get(court_code)

    def clear(self, court_code: str) -> None:
        data = self._load_all()
        if court_code in data:
            del data[court_code]
            try:
                # clear()도 같은 이유로 원자적이어야 한다 — 삭제 도중 죽으면 남은 법원들의
                # 진행 상황까지 함께 날아간다.
                self._write_atomic(data)
            except Exception as e:
                logger.error("checkpoint clear failed: %s", str(e))

    def _load_all(self) -> Dict:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


class RunLock:
    """`path` 에 락 파일을 두고 배치의 동시 실행을 막는다.

    사용법은 doc_worker 가 하던 그대로다 — 얻지 못하면 **아무것도 하지 않고 조용히
    끝낸다**(실패가 아니다. 다른 실행이 이미 그 일을 하고 있다).

        lock = RunLock("logs/x.lock", stale_hours=5)
        if not lock.acquire():
            return 0
        try:
            ...
        finally:
            lock.release()
    """

    def __init__(self, path: str, stale_hours: float, label: str = ""):
        self.path = path
        self.stale_hours = stale_hours
        self.label = label or os.path.basename(path)

    def acquire(self) -> bool:
        """다른 실행이 없으면 락을 잡고 True. 이미 있으면 False.

        ## 만드는 것 자체가 판정이다 (2026-08-19 Sprint 217, BUGS #145)

        예전 구현은 `os.path.exists()` 로 **보고 나서** `open(..., "w")` 로 **썼다.**
        그 둘 사이가 열려 있어서 동시에 들어온 실행이 **전부** 통과했다.
        실측(스레드 8 x 200라운드): **200라운드 전부에서 8개가 동시에 성공.**
        즉 이 락은 "몇 초 차이로 시작한 실행"만 막았고 **같은 순간에 시작한 실행은
        하나도 막지 못했다** — 그런데 이 락이 막으려는 상황(운영자가 수동 실행하는
        동안 예약 실행이 겹친다)이 정확히 그 모양이다.

        `O_CREAT | O_EXCL` 은 "없으면 만들고, 있으면 실패한다"를 **한 번의 시스템
        호출**로 한다. 커널이 판정하므로 창 자체가 없다(Windows/POSIX 둘 다).

        ## 오래된 락 회수는 **한 번에 하나만** 들어간다

        회수(`지우고 -> 새로 만들기`)는 그 자체가 두 단계라, 여러 실행이 동시에 회수하면
        늦은 쪽이 **먼저 회수한 쪽의 새 락을 지운다.** 측정으로 확인한 것들:

            os.remove 로 회수                      1,000라운드 중 4라운드에서 둘이 성공
            지우기 직전 mtime 재확인 추가            그대로 4/1,000 (창의 종류가 같다)
            os.rename 로 회수 권한 중재              8스레드에서 2/40 (셋 이상이면 남는다)

        그래서 **회수 구역 자체를 배타 토큰으로 감싼다** — 토큰을 `O_EXCL` 로 만든
        실행만 회수하고, 나머지는 조용히 물러난다(다음 실행에서 잡으면 된다).
        토큰을 쥔 채 죽어도 멈추지 않게, 오래된 토큰은 같은 기준으로 회수한다.
        """
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        if self._create_exclusive(self.path):
            return True

        # 여기 왔다 = 락 파일이 이미 있다. 오래된 것인가?
        try:
            age_hours = (time.time() - os.path.getmtime(self.path)) / 3600
        except OSError:
            # 확인하는 사이에 사라졌다 = 소유자가 방금 끝냈다. 한 번 더 잡으러 간다.
            return self._create_exclusive(self.path)
        if age_hours < self.stale_hours:
            return False

        token = self.path + ".reclaim"
        if not self._create_exclusive(token):
            # 누군가 이미 회수 중이거나, 회수하다 죽었다.
            try:
                token_age = (time.time() - os.path.getmtime(token)) / 3600
            except OSError:
                token_age = None
            if token_age is None or token_age < self.stale_hours:
                return False        # 진행 중이다. 물러난다.
            logger.warning("[%s] 회수 토큰이 %.1f시간째 남아 있다 - 죽은 회수로 간주",
                           self.label, token_age)
            try:
                os.remove(token)
            except OSError:
                return False
            if not self._create_exclusive(token):
                return False        # 그 사이 다른 실행이 가져갔다

        # --- 여기부터는 **한 번에 하나만** 들어온다 -----------------------------
        try:
            try:
                still_stale = ((time.time() - os.path.getmtime(self.path)) / 3600
                               >= self.stale_hours)
            except OSError:
                still_stale = True          # 그 사이 사라졌다 = 잡아도 된다
            if not still_stale:
                return False                # 그 사이 누가 정상적으로 잡았다
            logger.warning("[%s] 오래된 락 파일 발견(%.1f시간 경과) - "
                           "죽은 실행으로 간주하고 회수", self.label, age_hours)
            try:
                os.remove(self.path)
            except FileNotFoundError:
                pass
            except OSError:
                return False
            return self._create_exclusive(self.path)
        finally:
            try:
                os.remove(token)
            except OSError:
                logger.warning("[%s] 회수 토큰을 지우지 못했다: %s", self.label, token)

    def _create_exclusive(self, path: str) -> bool:
        """`path` 를 **배타적으로** 만들고 소유자 흔적을 남긴다. 이미 있으면 False.

        `O_CREAT | O_EXCL` 은 존재 확인과 생성을 한 번의 시스템 호출로 한다 —
        "보고 나서 쓴다" 사이의 창이 존재하지 않는다.
        """
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()) + " " + datetime.now().isoformat())
        return True

    def release(self) -> None:
        """락을 놓는다. 이미 없어도 조용히 넘어간다(정리는 실패해도 되는 일이다)."""
        try:
            os.remove(self.path)
        except OSError:
            pass
