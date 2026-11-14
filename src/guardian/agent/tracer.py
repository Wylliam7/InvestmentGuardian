"""Journal d'exécution réel des outils. Écrit par notre code, jamais par le modèle."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

_SECRET_PATTERNS = [
    re.compile(r"(AKIA|ASIA|AIDA|AROA)[A-Z0-9]{12,}"),
    re.compile(r"(?i)(aws_secret_access_key|aws_session_token|secret[_-]?key|authorization|x-amz-security-token)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"\b[A-Za-z0-9/+=]{40,}\b"),
]


def sanitize(text: str) -> str:
    """Masque les motifs ressemblant à des identifiants ou jetons."""
    out = str(text)
    for p in _SECRET_PATTERNS:
        out = p.sub("[masqué]", out)
    return out


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:16]


@dataclass
class ToolRecord:
    id: int
    turn: int
    tool: str
    arguments: dict
    status: str                    # "ok" | "error"
    duration_ms: float
    started_at: str
    result: dict | None = None
    result_digest: str | None = None
    error: str | None = None
    data_refs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class Tracer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.records: list[ToolRecord] = []
        self.turn = 0

    def start_turn(self) -> int:
        """Ouvre une nouvelle REQUÊTE utilisateur. Les cycles internes de Strands ne créent pas de nouveau tour.

        Tous les outils exécutés avant le prochain appel sont rattachés à cette requête.
        """
        with self._lock:
            self.turn += 1
            return self.turn

    def add(self, **kw) -> ToolRecord:
        with self._lock:
            rec = ToolRecord(id=len(self.records) + 1, turn=self.turn,
                             started_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **kw)
            self.records.append(rec)
            return rec

    def for_turn(self, turn: int) -> list[ToolRecord]:
        return [r for r in self.records if r.turn == turn]

    def export(self) -> list[dict]:
        return [r.to_dict() for r in self.records]
