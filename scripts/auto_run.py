"""Auto-run the full interrogation game without manual input.

Drives all rounds to HARD_LIMIT, injects evidence periodically,
writes a full log to logs/session_<timestamp>.log, and prints win/loss.
On per-round errors, logs the error and continues to the next round.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Allow running from repo root: python scripts/auto_run.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.interrogation_mvp.controller import GameController
from src.interrogation_mvp.models import SessionStatus


# --------------------------------------------------------------------------- #
# Logging setup – stream to both console and a timestamped log file
# --------------------------------------------------------------------------- #

LOGS_DIR = Path(__file__).resolve().parents[1] / "logs"
LOGS_DIR.mkdir(exist_ok=True)

_RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = LOGS_DIR / f"session_{_RUN_TS}.log"


_FILE_LOG_EXCLUDE_KEYWORDS: tuple[str, ...] = (
    "【证据注入】",
    "llm_provider_route",
    "llm_request",
    "llm_generate_success",
    "turn_timing",
)


class _ExcludeMessageFilter(logging.Filter):
    """Drop noisy operational lines from persisted log files."""

    def __init__(self, excluded_keywords: tuple[str, ...]) -> None:
        super().__init__()
        self._excluded_keywords = excluded_keywords

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(keyword in message for keyword in self._excluded_keywords)


def _setup_logging() -> None:
    fmt = "%(asctime)s %(levelname)s %(name)s - %(message)s"
    stream_handler = logging.StreamHandler(sys.stdout)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.addFilter(_ExcludeMessageFilter(_FILE_LOG_EXCLUDE_KEYWORDS))
    handlers: list[logging.Handler] = [stream_handler, file_handler]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


LOGGER = logging.getLogger("auto_run")

# --------------------------------------------------------------------------- #
# Evidence injection schedule (round -> evidence_id to inject before that round)
# --------------------------------------------------------------------------- #
# Spread the 4 evidence pieces across rounds 3, 5, 8, 11 so they have impact.
_EVIDENCE_SCHEDULE: dict[int, str] = {
    3: "e2",   # 邻居证词 – early corroboration
    5: "e3",   # 受害者手机 – phone records
    8: "e1",   # 便利店监控 – alibi destroyer
    11: "e4",  # 银行记录 – motive evidence
}


# --------------------------------------------------------------------------- #
# Win / loss determination
# --------------------------------------------------------------------------- #

def _determine_outcome(state) -> str:
    n_contradictions = len(state.contradictions)
    if n_contradictions >= 2:
        return f"【侦探胜利】累计发现 {n_contradictions} 处矛盾，嫌疑人谎言被识破。"
    elif n_contradictions == 1:
        return f"【平局/未定】仅发现 {n_contradictions} 处矛盾，证据不足以定罪。"
    else:
        return "【嫌疑人胜利】全程未抓到明显矛盾，嫌疑人成功掩护。"


# --------------------------------------------------------------------------- #
# Turn display helper (mirrors cli._print_turn but writes to logger)
# --------------------------------------------------------------------------- #

def _log_turn(result) -> None:
    turn = result.turn
    sep = "=" * 60
    LOGGER.info(sep)
    LOGGER.info("第 %d 回合", turn.round_index)
    LOGGER.info("[侦探内心] %s", turn.detective_thought)
    LOGGER.info("[侦探发问] %s", turn.detective_question)
    LOGGER.info("[嫌疑人内心] %s", turn.suspect_thought)
    LOGGER.info("[嫌疑人回答] %s", turn.suspect_answer)
    if result.new_contradiction_descriptions:
        for desc in result.new_contradiction_descriptions:
            LOGGER.warning("⚠️ 矛盾点：%s", desc)


# --------------------------------------------------------------------------- #
# Main auto-run loop
# --------------------------------------------------------------------------- #

def run_auto() -> None:
    _setup_logging()
    LOGGER.info("=== 自动运行模式启动 | 日志文件: %s ===", LOG_FILE)

    controller = GameController()
    state = controller.start_session()

    LOGGER.info(
        "案件：%s | 侦探：%s | 嫌疑人：%s | 硬上限：%d 回合",
        state.case_data.case_name,
        state.case_data.detective_name,
        state.case_data.suspect_name,
        state.round_limit_hard,
    )

    injected: set[str] = set()

    while True:
        state = controller.get_state(state.session_id)

        # --- Check terminal states ---
        if state.status == SessionStatus.ENDED:
            LOGGER.info("会话已标记为 ENDED，退出循环。")
            break

        if state.status == SessionStatus.HARD_LIMIT:
            LOGGER.info("已达到硬上限 (%d 回合)，自动结束。", state.round_limit_hard)
            end_result = controller.end_session(state.session_id, "自动运行触发硬上限结束")
            LOGGER.info("\n%s", end_result.transcript)
            break

        # --- Inject scheduled evidence before the upcoming round ---
        upcoming_round = state.round_index + 1
        scheduled_evidence = _EVIDENCE_SCHEDULE.get(upcoming_round)
        if scheduled_evidence and scheduled_evidence not in injected:
            try:
                controller.inject_evidence(state.session_id, scheduled_evidence)
                injected.add(scheduled_evidence)
                LOGGER.info("【证据注入】第 %d 回合前注入：%s", upcoming_round, scheduled_evidence)
            except ValueError as exc:
                LOGGER.warning("证据注入失败 (忽略): %s", exc)

        # --- Advance one round ---
        try:
            result = controller.next_turn(state.session_id)
            _log_turn(result)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error(
                "第 %d 回合执行出错，跳过本回合继续: %s",
                upcoming_round,
                exc,
                exc_info=True,
            )
            # Bump round manually in state so loop doesn't get stuck
            state = controller.get_state(state.session_id)
            if state.round_index == upcoming_round - 1:
                # Turn didn't advance – force the state past this round
                # by attempting end only if hard limit reached
                if state.round_index + 1 >= state.round_limit_hard:
                    LOGGER.warning("错误发生在最后一回合，强制结束会话。")
                    end_result = controller.end_session(state.session_id, "最终回合出错，强制结束")
                    LOGGER.info("\n%s", end_result.transcript)
                    break
                # Otherwise just continue; the get_state at top of loop will re-check
            continue

    # --- Final verdict ---
    final_state = controller.get_state(state.session_id)
    outcome = _determine_outcome(final_state)
    LOGGER.info("\n%s\n矛盾汇总共 %d 条。", outcome, len(final_state.contradictions))
    LOGGER.info("日志已写入: %s", LOG_FILE)

    print(f"\n{'='*60}")
    print(outcome)
    print(f"完整日志：{LOG_FILE}")


if __name__ == "__main__":
    run_auto()
