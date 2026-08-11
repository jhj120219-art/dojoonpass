import json
import logging
import os
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
