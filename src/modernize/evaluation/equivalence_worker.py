"""Processo isolado que executa o codigo gerado contra o database legacy.

Le um JSON da entrada padrao e escreve o resultado na ultima linha da saida
padrao. O processo pai aplica o timeout. Isola memoria e tempo do servidor;
nao e sandbox de privilegio (ver limitacoes no README).
"""

import contextlib
import io
import json
import logging
import sys

from modernize.evaluation.equivalence import run_scenarios
from modernize.ir.models import RoutineIR


def main() -> None:
    payload = json.loads(sys.stdin.read())
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(io.StringIO()):
        result = run_scenarios(
            payload["dsn"],
            RoutineIR.model_validate(payload["ir"]),
            payload["legacy_sources"],
            payload["modules"],
            payload["scenarios"],
        )
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
