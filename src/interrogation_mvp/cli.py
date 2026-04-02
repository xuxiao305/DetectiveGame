"""CLI entry point for InterrogationRoom MVP."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import time

from .controller import GameController
from .models import SessionStatus


def _typewriter_delay_seconds() -> float:
    raw = os.getenv("INTERROGATION_TYPEWRITER_DELAY_MS", "40").strip()
    try:
        delay_ms = float(raw)
    except ValueError:
        delay_ms = 40.0
    if delay_ms <= 0:
        return 0.0
    return delay_ms / 1000.0


def _print_with_typewriter(text: str, delay_seconds: float) -> None:
    if delay_seconds <= 0:
        print(text)
        return
    for ch in text:
        print(ch, end="", flush=True)
        time.sleep(delay_seconds)
    print()


def _print_case_intro(state) -> None:
    case_data = state.case_data
    print("\n=== 《审讯室》MVP ===")
    print(f"案件：{case_data.case_name}")
    print(f"背景：{case_data.background}")
    print(f"侦探：{case_data.detective_name} | 嫌疑人：{case_data.suspect_name}")
    print("\n可用证据：")
    for item in case_data.evidence_items:
        print(f"- {item.evidence_id}: {item.title} ({item.content})")


def _print_turn(result) -> None:
    turn = result.turn
    delay_seconds = _typewriter_delay_seconds()
    print(f"\n--- 第 {turn.round_index} 回合 ---")
    print(f"侦探内心：{turn.detective_thought}")
    source_d = f" ({turn.detective_source})" if turn.detective_source else ""
    print(f"侦探发问{source_d}：", end="")
    _print_with_typewriter(turn.detective_question, delay_seconds)
    print(f"嫌疑人内心：{turn.suspect_thought}")
    source_s = f" ({turn.suspect_source})" if turn.suspect_source else ""
    print(f"嫌疑人回答{source_s}：", end="")
    _print_with_typewriter(turn.suspect_answer, delay_seconds)
    if result.new_contradiction_descriptions:
        for desc in result.new_contradiction_descriptions:
            print(f"⚠️ 矛盾点：{desc}")


def _configure_logging() -> None:
    level_name = os.getenv("INTERROGATION_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    log_file = os.getenv("INTERROGATION_LOG_FILE", "").strip()
    if log_file:
        log_path = Path(log_file)
        if not log_path.is_absolute():
            log_path = Path.cwd() / log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        handlers=handlers,
    )


def run_cli() -> None:
    _configure_logging()
    controller = GameController()
    state = controller.start_session()
    _print_case_intro(state)

    print("\n操作：")
    print("n = 下一回合")
    print("i = 注入证据")
    print("e = 结束审讯")

    while True:
        state = controller.get_state(state.session_id)
        if state.status == SessionStatus.SOFT_LIMIT:
            print("\n[提示] 已到第12回合及以上，建议收束。")

        if state.status == SessionStatus.HARD_LIMIT:
            end_result = controller.end_session(state.session_id, "触发硬上限自动结束")
            print("\n[系统] 已达到15回合硬上限，自动结束。")
            print("\n" + end_result.transcript)
            return

        action = input("\n请输入操作(n/i/e): ").strip().lower()

        if action == "n":
            try:
                result = controller.next_turn(state.session_id)
                _print_turn(result)
            except RuntimeError as err:
                print(f"[错误] {err}")
            continue

        if action == "i":
            current = controller.get_state(state.session_id)
            used = set(current.used_evidence_ids)
            pending = set(current.pending_evidence_ids)
            print("\n可注入证据：")
            for item in current.case_data.evidence_items:
                status = "可用"
                if item.evidence_id in used:
                    status = "已使用"
                elif item.evidence_id in pending:
                    status = "待生效"
                print(f"- {item.evidence_id}: {item.title} [{status}]")
            evidence_id = input("输入证据ID: ").strip()
            try:
                controller.inject_evidence(state.session_id, evidence_id)
                print("[剧情节点] 侦探收到了新情报，下一回合将引用该证据。")
            except ValueError as err:
                print(f"[错误] {err}")
            continue

        if action == "e":
            end_result = controller.end_session(state.session_id, "玩家手动结束")
            print("\n" + end_result.transcript)
            return

        print("无效操作，请输入 n / i / e。")


if __name__ == "__main__":
    run_cli()
