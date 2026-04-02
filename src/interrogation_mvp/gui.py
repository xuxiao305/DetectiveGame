"""
GUI 入口 —— 基于 tkinter 的可视化审讯室界面。

文件职责：替代 cli.py 提供图形交互。所有 LLM 调用（next_turn / inject_evidence /
end_session）通过 threading.Thread + queue.Queue 移入后台线程，主线程仅负责 UI 渲染。

在整体架构中的位置：表现层，直接依赖 GameController，不绕过任何现有内部模块。

与其他模块的协作：
- controller.py：GameController 是唯一交互入口
- models.py：消费 GameState / TurnResult / SessionStatus / EvidenceItem
- 不直接调用 orchestrator / llm_gateway 等内部层
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText
from typing import List, Optional

from .controller import GameController
from .models import SessionStatus


class InterrogationGUI:
    """主窗口，持有 GameController 并通过队列与后台线程通信。"""

    def __init__(self, root: tk.Tk, controller: GameController) -> None:
        self._root = root
        self._controller = controller
        self._session_id: Optional[str] = None
        self._q: queue.Queue = queue.Queue()
        self._turn_count = 0
        self._evidence_ids: List[str] = []
        self._evidence_map: dict = {}  # evidence_id -> title

        self._build_ui()
        # 开启队列轮询，再启动后台会话初始化线程
        self._root.after(50, self._poll_queue)
        self._start_session()

    # ─────────────────────────────── UI 构建 ────────────────────────────────

    def _build_ui(self) -> None:
        self._root.title("审讯室")
        self._root.minsize(720, 620)

        # ── 标题栏 ────────────────────────────────────────────────────────
        self._title_var = tk.StringVar(value="审讯室")
        tk.Label(
            self._root,
            textvariable=self._title_var,
            font=("Helvetica", 16, "bold"),
            pady=6,
        ).pack(fill=tk.X, padx=10)

        # ── 案件信息区（只读 Label） ──────────────────────────────────────
        info_frame = tk.LabelFrame(self._root, text="案件信息", padx=6, pady=4)
        info_frame.pack(fill=tk.X, padx=10, pady=(0, 4))

        self._info_var = tk.StringVar(value="初始化中，请稍候…")
        tk.Label(
            info_frame,
            textvariable=self._info_var,
            justify=tk.LEFT,
            wraplength=700,
            anchor="w",
        ).pack(fill=tk.X)

        # ── 对话滚动区 ──────────────────────────────────────────────────
        self._chat = ScrolledText(
            self._root,
            state=tk.DISABLED,
            wrap=tk.WORD,
            font=("Helvetica", 11),
            height=18,
        )
        self._chat.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        # 颜色标签定义
        self._chat.tag_config("thought",    foreground="#888888", font=("Helvetica", 9))
        self._chat.tag_config("detective",  foreground="#1a5fa8", font=("Helvetica", 11, "bold"))
        self._chat.tag_config("suspect",    foreground="#222222", font=("Helvetica", 11))
        self._chat.tag_config("contradict", foreground="#cc0000", font=("Helvetica", 11, "bold"))
        self._chat.tag_config("soft_limit", foreground="#b8860b", font=("Helvetica", 10))
        self._chat.tag_config("inject_ok",  foreground="#2e7d32", font=("Helvetica", 10))
        self._chat.tag_config("error_msg",  foreground="#cc0000", font=("Helvetica", 10))
        self._chat.tag_config("system",     foreground="#555555", font=("Helvetica", 9, "italic"))
        self._chat.tag_config("pending",    foreground="#555555", font=("Helvetica", 9, "italic"))

        # ── 证据注入行 ──────────────────────────────────────────────────
        ev_frame = tk.Frame(self._root)
        ev_frame.pack(fill=tk.X, padx=10, pady=2)

        tk.Label(ev_frame, text="注入证据：").pack(side=tk.LEFT)
        self._evidence_var = tk.StringVar(value="（无可用证据）")
        self._evidence_menu = tk.OptionMenu(ev_frame, self._evidence_var, "（无可用证据）")
        self._evidence_menu.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._inject_btn = tk.Button(
            ev_frame,
            text="注入证据",
            command=self._on_inject,
            state=tk.DISABLED,
        )
        self._inject_btn.pack(side=tk.RIGHT, padx=(6, 0))

        # ── 操作按钮行 ──────────────────────────────────────────────────
        btn_frame = tk.Frame(self._root)
        btn_frame.pack(fill=tk.X, padx=10, pady=(2, 8))

        self._next_btn = tk.Button(
            btn_frame,
            text="下一回合",
            command=self._on_next_turn,
            state=tk.DISABLED,
            width=12,
        )
        self._next_btn.pack(side=tk.LEFT)

        self._end_btn = tk.Button(
            btn_frame,
            text="结束审讯",
            command=self._on_end_session,
            state=tk.DISABLED,
            width=12,
        )
        self._end_btn.pack(side=tk.RIGHT)

    # ─────────────────────────────── 会话启动 ───────────────────────────────

    def _start_session(self) -> None:
        def _run() -> None:
            try:
                state = self._controller.start_session()
                self._q.put(("session_started", state))
            except Exception as exc:
                self._q.put(("error", str(exc)))

        threading.Thread(target=_run, daemon=True).start()

    # ─────────────────────────────── 事件处理 ───────────────────────────────

    def _on_next_turn(self) -> None:
        self._set_buttons_disabled()
        self._turn_count += 1
        self._append_pending(f"⏳ 正在生成第 {self._turn_count} 回合…\n")

        session_id = self._session_id

        def _run() -> None:
            try:
                result = self._controller.next_turn(session_id)
                self._q.put(("turn_result", result))
            except Exception as exc:
                self._q.put(("error", str(exc)))

        threading.Thread(target=_run, daemon=True).start()

    def _on_inject(self) -> None:
        selected = self._evidence_var.get()
        if not selected or selected == "（无可用证据）":
            return
        # 格式 "evidence_id - title"，取第一段作为 id
        evidence_id = selected.split(" - ")[0].strip()
        title = self._evidence_map.get(evidence_id, evidence_id)

        self._inject_btn.config(state=tk.DISABLED)
        session_id = self._session_id

        def _run() -> None:
            try:
                self._controller.inject_evidence(session_id, evidence_id)
                self._q.put(("inject_ok", evidence_id, title))
            except Exception as exc:
                self._q.put(("error", str(exc)))

        threading.Thread(target=_run, daemon=True).start()

    def _on_end_session(self) -> None:
        if not messagebox.askokcancel("结束审讯", "确定要结束本次审讯吗？"):
            return
        self._set_buttons_disabled()
        self._auto_end("用户手动结束")

    # ─────────────────────────────── 队列轮询 ───────────────────────────────

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self._q.get_nowait()
                self._handle_message(msg)
        except queue.Empty:
            pass
        self._root.after(50, self._poll_queue)

    def _handle_message(self, msg: tuple) -> None:
        tag = msg[0]

        if tag == "session_started":
            state = msg[1]
            self._session_id = state.session_id
            cd = state.case_data
            if cd:
                self._title_var.set(f"审讯室 — {cd.case_name}")
                self._info_var.set(
                    f"【案件背景】{cd.background}\n"
                    f"侦探：{cd.detective_name}　　嫌疑人：{cd.suspect_name}"
                )
                self._build_evidence_menu(cd.evidence_items)
            self._next_btn.config(state=tk.NORMAL)
            self._end_btn.config(state=tk.NORMAL)

        elif tag == "turn_result":
            result = msg[1]
            self._remove_pending()
            self._append_turn(result.turn, result.new_contradiction_descriptions)
            self._refresh_buttons_after_turn()

        elif tag == "inject_ok":
            evidence_id, title = msg[1], msg[2]
            self._append_text(f"[已注入证据：{evidence_id} {title}]\n", "inject_ok")
            self._inject_btn.config(
                state=tk.NORMAL if self._evidence_ids else tk.DISABLED
            )

        elif tag == "ended":
            result = msg[1]
            self._append_text("\n══════ 审讯记录 ══════\n", "system")
            self._append_text(result.transcript + "\n", "system")
            self._set_buttons_disabled()

        elif tag == "error":
            self._remove_pending()
            self._append_text(f"❌ 错误：{msg[1]}\n", "error_msg")
            # 恢复按钮，让用户能重试或结束
            if self._session_id:
                self._next_btn.config(state=tk.NORMAL)
                self._end_btn.config(state=tk.NORMAL)

    def _refresh_buttons_after_turn(self) -> None:
        """根据当前 session 状态决定是否恢复按钮，或触发自动结束。"""
        try:
            state = self._controller.get_state(self._session_id)
        except Exception:
            self._next_btn.config(state=tk.NORMAL)
            self._end_btn.config(state=tk.NORMAL)
            return

        if state.status == SessionStatus.HARD_LIMIT:
            self._append_text("⛔ 已达到最大回合上限，审讯自动结束。\n", "soft_limit")
            self._auto_end("已达到最大回合上限")
        else:
            if state.status == SessionStatus.SOFT_LIMIT:
                self._append_text("⚠️ 已接近回合上限，建议尽快结束审讯。\n", "soft_limit")
            self._next_btn.config(state=tk.NORMAL)
            self._end_btn.config(state=tk.NORMAL)
            self._inject_btn.config(
                state=tk.NORMAL if self._evidence_ids else tk.DISABLED
            )

    # ─────────────────────────────── 辅助方法 ───────────────────────────────

    def _build_evidence_menu(self, evidence_items) -> None:
        self._evidence_ids = [e.evidence_id for e in evidence_items]
        self._evidence_map = {e.evidence_id: e.title for e in evidence_items}
        options = [f"{e.evidence_id} - {e.title}" for e in evidence_items]
        if not options:
            return
        menu = self._evidence_menu["menu"]
        menu.delete(0, tk.END)
        for opt in options:
            menu.add_command(
                label=opt, command=lambda v=opt: self._evidence_var.set(v)
            )
        self._evidence_var.set(options[0])
        self._inject_btn.config(state=tk.NORMAL)

    def _append_text(self, text: str, tag: str = "") -> None:
        self._chat.config(state=tk.NORMAL)
        if tag:
            self._chat.insert(tk.END, text, tag)
        else:
            self._chat.insert(tk.END, text)
        self._chat.config(state=tk.DISABLED)
        self._chat.see(tk.END)

    def _append_pending(self, text: str) -> None:
        """追加带 'pending' 标签的提示文本，供后续精准删除。"""
        self._chat.config(state=tk.NORMAL)
        self._chat.insert(tk.END, text, "pending")
        self._chat.config(state=tk.DISABLED)
        self._chat.see(tk.END)

    def _remove_pending(self) -> None:
        """删除对话区中所有带 'pending' 标签的内容（即 ⏳ 提示行）。"""
        self._chat.config(state=tk.NORMAL)
        ranges = self._chat.tag_ranges("pending")
        # tag_ranges 返回 (start1, end1, start2, end2, ...) 扁平元组，倒序删除
        for i in range(len(ranges) - 1, -1, -2):
            self._chat.delete(ranges[i - 1], ranges[i])
        self._chat.config(state=tk.DISABLED)

    def _append_turn(self, turn, contradictions: list) -> None:
        self._append_text(f"\n── 第 {turn.round_index} 回合 ──\n", "system")
        if turn.detective_thought:
            self._append_text(f"[侦探内心] {turn.detective_thought}\n", "thought")
        self._append_text(f"侦探：{turn.detective_question}\n", "detective")
        if turn.suspect_thought:
            self._append_text(f"[嫌疑人内心] {turn.suspect_thought}\n", "thought")
        self._append_text(f"嫌疑人：{turn.suspect_answer}\n", "suspect")
        for desc in contradictions:
            self._append_text(f"⚠️ 矛盾：{desc}\n", "contradict")

    def _set_buttons_disabled(self) -> None:
        self._next_btn.config(state=tk.DISABLED)
        self._end_btn.config(state=tk.DISABLED)
        self._inject_btn.config(state=tk.DISABLED)

    def _auto_end(self, reason: str) -> None:
        session_id = self._session_id

        def _run() -> None:
            try:
                result = self._controller.end_session(session_id, reason)
                self._q.put(("ended", result))
            except Exception as exc:
                self._q.put(("error", str(exc)))

        threading.Thread(target=_run, daemon=True).start()


# ─────────────────────────────────── 入口 ────────────────────────────────────

def main() -> None:
    root = tk.Tk()
    controller = GameController()
    InterrogationGUI(root, controller)
    root.mainloop()


if __name__ == "__main__":
    main()
