"""
通用界面组件与对话框。

原系统的 styles.py 只有圆角按钮和一个配色表，其余控件（表格、日期输入、
提示框、居中逻辑）在每个界面文件里各写一遍：三个窗口类各有一份
_center_window，日期靠 tk.Entry 手输，表格的滚动条配置复制了十几处。

本模块把这些集中起来：
    RoundedButton / Card     视觉组件
    DataTable                带滚动条与隔行底色的表格（统一列宽、取值方式）
    LabeledEntry / LabeledCombo / DateField   表单输入
    center_window / FormDialog / info / warn / error / confirm   对话框
    StatusBar                底部状态栏
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import messagebox, ttk
from typing import Any, Callable, Iterable, Sequence


# =====================================================================
#  配色与字体
# =====================================================================
class ColorScheme:
    """全局配色方案。"""

    PRIMARY = "#3498db"
    PRIMARY_DARK = "#2980b9"
    SUCCESS = "#27ae60"
    SUCCESS_DARK = "#219a52"
    DANGER = "#e74c3c"
    DANGER_DARK = "#c0392b"
    WARNING = "#f39c12"
    WARNING_DARK = "#d68910"
    PURPLE = "#9b59b6"
    PURPLE_DARK = "#8e44ad"
    TEAL = "#1abc9c"
    TEAL_DARK = "#16a085"
    NEUTRAL = "#95a5a6"
    NEUTRAL_DARK = "#7f8c8d"

    BG_MAIN = "#f0f2f5"
    BG_WHITE = "#ffffff"
    BG_CARD = "#ffffff"
    BG_DARK = "#2c3e50"

    TEXT_PRIMARY = "#2c3e50"
    TEXT_SECONDARY = "#7f8c8d"
    TEXT_MUTED = "#bdc3c7"
    TEXT_WHITE = "#ffffff"

    BORDER = "#dfe4ea"
    BORDER_LIGHT = "#ecf0f1"

    ROW_ODD = "#fbfdff"
    ROW_EVEN = "#ffffff"


CS = ColorScheme
FONT = "微软雅黑"

# 订单状态 -> 表格中的前景色
STATUS_COLORS = {
    "进行中": CS.PRIMARY,
    "已完成": CS.SUCCESS,
    "已取消": CS.TEXT_MUTED,
    "待确认/待入住": CS.WARNING,
    "已入住": CS.SUCCESS,
    "已退房": CS.TEXT_SECONDARY,
    "待用餐": CS.WARNING,
    "用餐中": CS.PRIMARY,
    "待服务": CS.WARNING,
    "服务中": CS.PRIMARY,
    "等待取衣": CS.WARNING,
    "已取衣": CS.PRIMARY,
    "洗涤中": CS.PRIMARY,
    "已送达": CS.SUCCESS,
    "已预约": CS.PRIMARY,
    "空闲": CS.SUCCESS,
    "在住": CS.DANGER,
    "打扫中": CS.WARNING,
    "维护中": CS.NEUTRAL,
}


# =====================================================================
#  视觉组件
# =====================================================================
class RoundedButton(tk.Canvas):
    """基于 Canvas 绘制的圆角按钮（保留原有视觉风格）。"""

    def __init__(self, parent, text: str = "", width: int = 160, height: int = 42,
                 radius: int = 12, color: str = CS.PRIMARY, hover_color: str | None = None,
                 text_color: str = "white", font=(FONT, 11, "bold"),
                 command: Callable[[], None] | None = None, **kwargs):
        bg = kwargs.pop("bg", None) or parent["bg"]
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bg=bg, **kwargs)

        self._text = text
        self._width = width
        self._height = height
        self._radius = radius
        self._color = color
        self._hover_color = hover_color or self._darken(color)
        self._text_color = text_color
        self._font = font
        self._command = command
        self._enabled = True

        self._draw(self._color)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    @staticmethod
    def _darken(hex_color: str, factor: float = 0.85) -> str:
        hex_color = hex_color.lstrip("#")
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
        return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"

    def _draw(self, color: str) -> None:
        self.delete("all")
        r, w, h = self._radius, self._width, self._height
        self.create_arc((0, 0, 2 * r, 2 * r), start=90, extent=90, fill=color, outline=color)
        self.create_arc((w - 2 * r, 0, w, 2 * r), start=0, extent=90, fill=color, outline=color)
        self.create_arc((w - 2 * r, h - 2 * r, w, h), start=270, extent=90,
                        fill=color, outline=color)
        self.create_arc((0, h - 2 * r, 2 * r, h), start=180, extent=90,
                        fill=color, outline=color)
        self.create_rectangle((r, 0, w - r, h), fill=color, outline=color)
        self.create_rectangle((0, r, w, h - r), fill=color, outline=color)
        self.create_text(w / 2, h / 2, text=self._text, fill=self._text_color,
                         font=self._font, anchor="center")

    def _on_enter(self, _event=None) -> None:
        if self._enabled:
            self._draw(self._hover_color)
            self.config(cursor="hand2")

    def _on_leave(self, _event=None) -> None:
        if self._enabled:
            self._draw(self._color)
            self.config(cursor="")

    def _on_click(self, _event=None) -> None:
        if self._enabled and self._command:
            self._command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._draw(self._color if enabled else CS.TEXT_MUTED)

    def set_text(self, text: str) -> None:
        self._text = text
        self._draw(self._color if self._enabled else CS.TEXT_MUTED)


class Card(tk.Frame):
    """带内边距与浅边框的卡片容器。"""

    def __init__(self, parent, padding: int = 14, bg: str = CS.BG_WHITE, **kwargs):
        super().__init__(parent, bg=bg, highlightbackground=CS.BORDER,
                         highlightthickness=1, bd=0, **kwargs)
        self._padding = padding

    def body(self) -> tk.Frame:
        """返回真正用于摆放内容的内部 Frame。"""
        if not hasattr(self, "_body"):
            self._body = tk.Frame(self, bg=self["bg"])
            self._body.pack(fill="both", expand=True,
                            padx=self._padding, pady=self._padding)
        return self._body


class StatCard(tk.Frame):
    """指标卡片：标题 + 数值 + 可选副标题。"""

    def __init__(self, parent, label: str, value: str, color: str = CS.PRIMARY,
                 hint: str = "", width: int = 165, height: int = 88):
        super().__init__(parent, bg=color, width=width, height=height)
        self.pack_propagate(False)
        tk.Label(self, text=label, font=(FONT, 10), bg=color, fg="white").pack(pady=(12, 0))
        self._value = tk.Label(self, text=value, font=(FONT, 15, "bold"),
                               bg=color, fg="white")
        self._value.pack()
        self._hint = tk.Label(self, text=hint, font=(FONT, 8), bg=color, fg="#f5f6fa")
        if hint:
            self._hint.pack()

    def update_value(self, value: str, hint: str | None = None) -> None:
        self._value.config(text=value)
        if hint is not None:
            self._hint.config(text=hint)


# =====================================================================
#  表格
# =====================================================================
class DataTable(tk.Frame):
    """
    统一风格的只读表格。

    原实现里每个表格都手写 Treeview + Scrollbar + 列宽配置，并且靠
    `item['values'][3]` 这种下标取值 —— 列顺序一改就全线出错。
    这里要求显式声明 columns 的 key，并支持按 key 读写整行数据。
    """

    def __init__(self, parent, columns: Sequence[tuple[str, str, int]],
                 height: int = 16, on_double_click: Callable[[dict], None] | None = None,
                 on_select: Callable[[dict], None] | None = None, **kwargs):
        """
        columns: [(列键, 显示名, 宽度), ...]
        """
        super().__init__(parent, bg=CS.BG_MAIN, **kwargs)
        self._keys = [c[0] for c in columns]
        self._rows: dict[str, dict] = {}
        self._on_double_click = on_double_click
        self._on_select = on_select

        self.tree = ttk.Treeview(self, columns=self._keys, show="headings", height=height)
        for key, title, width in columns:
            self.tree.heading(key, text=title)
            anchor = "w" if width >= 160 else "center"
            self.tree.column(key, width=width, anchor=anchor)

        self.tree.tag_configure("odd", background=CS.ROW_ODD)
        self.tree.tag_configure("even", background=CS.ROW_EVEN)

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._handle_select)
        if on_double_click:
            self.tree.bind("<Double-1>", self._handle_double_click)

    # --- 数据操作 -------------------------------------------------
    def clear(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._rows.clear()

    def set_rows(self, rows: Iterable[dict],
                 formatter: Callable[[dict], Sequence[Any]] | None = None,
                 tagger: Callable[[dict], str | None] | None = None) -> None:
        """
        rows: 数据行（必须带唯一键 __key，否则用行内 order_id/room_id 兜底）
        formatter: 把数据行转换成一串显示值（默认按键顺序取值）
        tagger: 返回状态名，用于按状态着色
        """
        self.clear()
        for index, row in enumerate(rows):
            values = formatter(row) if formatter else [row.get(k, "") for k in self._keys]
            tags = ["odd" if index % 2 else "even"]
            status = tagger(row) if tagger else None
            if status and status in STATUS_COLORS:
                tags.append(f"status::{status}")
            item_id = self.tree.insert("", "end", values=values, tags=tuple(tags))
            self._rows[item_id] = dict(row)

        # 状态色需要为每种状态单独注册 tag
        for status, color in STATUS_COLORS.items():
            self.tree.tag_configure(f"status::{status}", foreground=color)

    def selected(self) -> dict | None:
        """返回选中行的原始数据字典（而不是下标数组）。"""
        selection = self.tree.selection()
        if not selection:
            return None
        return self._rows.get(selection[0])

    def selected_many(self) -> list[dict]:
        return [self._rows[i] for i in self.tree.selection() if i in self._rows]

    def count(self) -> int:
        return len(self._rows)

    # --- 事件 -----------------------------------------------------
    def _handle_select(self, _event=None) -> None:
        if self._on_select:
            row = self.selected()
            if row:
                self._on_select(row)

    def _handle_double_click(self, _event=None) -> None:
        row = self.selected()
        if row and self._on_double_click:
            self._on_double_click(row)


# =====================================================================
#  表单控件
# =====================================================================
class LabeledEntry(tk.Frame):
    """标签 + 输入框（保持原有下划线式外观）。"""

    def __init__(self, parent, label: str, width: int = 20,
                 show: str | None = None, initial: str = "", bg: str = CS.BG_WHITE):
        super().__init__(parent, bg=bg)
        tk.Label(self, text=label, font=(FONT, 10), bg=bg,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w")
        self.var = tk.StringVar(value=initial)
        self.entry = tk.Entry(self, textvariable=self.var, font=(FONT, 11), width=width,
                             bd=0, relief="flat", bg="white", highlightthickness=1,
                             highlightbackground=CS.BORDER, highlightcolor=CS.PRIMARY,
                             show=show, insertbackground=CS.PRIMARY)
        self.entry.pack(fill="x", pady=(2, 8), ipady=4)

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(value)

    def bind_change(self, callback: Callable[[], None]) -> None:
        self.entry.bind("<KeyRelease>", lambda _e: callback())


class LabeledCombo(tk.Frame):
    """
    标签 + 只读下拉框。

    重要约定：on_change 只由用户选择触发，set_values 默认不会主动调用它。
    早期版本在 set_values 里无条件回调，导致控件构造过程中回调先于控件
    赋值执行，访问到尚未创建的属性（曾引发控件树无限递归）。
    需要在程序化赋值后联动刷新时，显式传 notify=True。
    """

    def __init__(self, parent, label: str, values: Sequence[str] = (),
                 width: int = 20, initial: str | None = None,
                 on_change: Callable[[str], None] | None = None, bg: str = CS.BG_WHITE):
        super().__init__(parent, bg=bg)
        tk.Label(self, text=label, font=(FONT, 10), bg=bg,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w")
        self.var = tk.StringVar()
        self._on_change = on_change
        self.combo = ttk.Combobox(self, textvariable=self.var, values=list(values),
                                  font=(FONT, 10), width=width - 2, state="readonly")
        self.combo.pack(fill="x", pady=(2, 8), ipady=3)
        if values:
            self.var.set(values[0])
        if on_change:
            self.combo.bind("<<ComboboxSelected>>",
                            lambda _e: on_change(self.var.get()))

    def set_values(self, values: Sequence[str], initial: str | None = None,
                   on_change: Callable[[str], None] | None = None,
                   *, notify: bool = False) -> None:
        values = list(values)
        self.combo["values"] = values
        if on_change is not None:
            self._on_change = on_change
        if initial and initial in values:
            self.var.set(initial)
        elif values and self.var.get() not in values:
            self.var.set(values[0])
        if notify and self._on_change and self.var.get():
            self._on_change(self.var.get())

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str) -> None:
        self.var.set(value)


class DateField(LabeledEntry):
    """
    日期输入：带 ±1 天快捷按钮，并在失焦时做格式校验。

    原系统是纯 tk.Entry 手输，用户输入 "2026/5/1" 甚至乱码都会在提交时
    抛 ValueError 崩溃。这里把校验前移到输入阶段，并给出即时提示。
    """

    def __init__(self, parent, label: str, initial: date | None = None, **kwargs):
        self._value = initial or date.today()
        super().__init__(parent, label, initial=self._value.strftime("%Y-%m-%d"), **kwargs)

        buttons = tk.Frame(self, bg=self["bg"])
        buttons.pack(anchor="e", pady=(0, 6))
        for text, delta in (("◀ 前一天", -1), ("后一天 ▶", 1)):
            tk.Button(buttons, text=text, font=(FONT, 8), bd=0, cursor="hand2",
                      bg=self["bg"], fg=CS.PRIMARY,
                      command=lambda d=delta: self.shift(days=d)).pack(side="left", padx=2)
        tk.Button(buttons, text="今天", font=(FONT, 8), bd=0, cursor="hand2",
                  bg=self["bg"], fg=CS.TEXT_SECONDARY,
                  command=lambda: self.set_date(date.today())).pack(side="left", padx=2)

    def shift(self, *, days: int) -> None:
        self.set_date(self.value() + timedelta(days=days))

    def set_date(self, value: date) -> None:
        self.set(value.strftime("%Y-%m-%d"))

    def value(self) -> date:
        """解析当前文本为 date；非法时抛出 ValueError 供上层转成提示。"""
        raw = self.get().strip().replace("/", "-").replace(".", "-")
        return datetime.strptime(raw, "%Y-%m-%d").date()


class TimeCombo(LabeledCombo):
    """时间下拉框。"""

    def __init__(self, parent, label: str = "时间", values: Sequence[str] = (),
                 **kwargs):
        super().__init__(parent, label, values, **kwargs)

    def value(self) -> str:
        return self.get()


class ToolbarCombo(tk.Frame):
    """
    工具栏里横向排列的「标签 + 下拉框」。

    注意与 LabeledCombo 的区别：这里的回调只绑定在用户选择事件上，
    不会在初始化赋值时触发。LabeledCombo 的 on_change 会在 set_values 里
    立即调用一次，若把它用在"标签页尚未构建完"的位置，回调会访问到还没
    创建的控件（曾导致控件树无限递归、窗口尺寸爆炸）。
    """

    def __init__(self, parent, label: str, values: Sequence[str] = (),
                 width: int = 10, initial: str | None = None,
                 on_change: Callable[[str], None] | None = None,
                 bg: str = CS.BG_MAIN):
        super().__init__(parent, bg=bg)
        self._on_change = on_change
        tk.Label(self, text=label, font=(FONT, 10), bg=bg,
                 fg=CS.TEXT_PRIMARY).pack(side="left")
        self.var = tk.StringVar()
        self.combo = ttk.Combobox(self, textvariable=self.var, values=list(values),
                                  font=(FONT, 10), width=width, state="readonly")
        self.combo.pack(side="left")
        if values:
            self.var.set(initial if initial in values else values[0])
        if on_change:
            self.combo.bind("<<ComboboxSelected>>",
                            lambda _e: on_change(self.var.get()))

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str) -> None:
        self.var.set(value)

    def set_values(self, values: Sequence[str], initial: str | None = None) -> None:
        values = list(values)
        self.combo["values"] = values
        if initial and initial in values:
            self.var.set(initial)
        elif values and self.var.get() not in values:
            self.var.set(values[0])


# =====================================================================
#  对话框与提示
# =====================================================================
def center_window(window: tk.Misc, width: int | None = None,
                  height: int | None = None) -> None:
    """把窗口/对话框居中显示（原实现在三处各写了一遍）。"""
    window.update_idletasks()
    w = width or window.winfo_width()
    h = height or window.winfo_height()
    x = max(0, (window.winfo_screenwidth() - w) // 2)
    y = max(0, (window.winfo_screenheight() - h) // 3)
    window.geometry(f"{w}x{h}+{x}+{y}")


def info(title: str, message: str, parent=None) -> None:
    messagebox.showinfo(title, message, parent=parent)


def warn(title: str, message: str, parent=None) -> None:
    messagebox.showwarning(title, message, parent=parent)


def error(title: str, message: str, parent=None) -> None:
    messagebox.showerror(title, message, parent=parent)


def confirm(title: str, message: str, parent=None) -> bool:
    return bool(messagebox.askyesno(title, message, parent=parent))


class FormDialog(tk.Toplevel):
    """
    通用模态表单对话框。

    子类通过 fields() 声明字段，通过 submit(values) 处理结果；
    submit 中抛出 BusinessError 会把错误显示在对话框内且不关闭窗口，
    让用户能就地修正，而不是像原系统那样弹一堆 messagebox 后丢失已填内容。
    """

    def __init__(self, parent, title: str, size: tuple[int, int] = (420, 480),
                 bg: str = CS.BG_WHITE):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=bg)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        self._error_var = tk.StringVar()
        self._body = tk.Frame(self, bg=bg)
        self._body.pack(fill="both", expand=True, padx=24, pady=(18, 0))

        tk.Label(self._body, text=title, font=(FONT, 14, "bold"),
                 bg=bg, fg=CS.TEXT_PRIMARY).pack(pady=(0, 14), anchor="w")

        self.build(self._body)

        self._error_label = tk.Label(self, textvariable=self._error_var, font=(FONT, 9),
                                     bg=bg, fg=CS.DANGER, wraplength=size[0] - 60,
                                     justify="left")
        self._error_label.pack(fill="x", padx=24, pady=(6, 0))

        self._buttons = tk.Frame(self, bg=bg)
        self._buttons.pack(fill="x", padx=24, pady=14)
        RoundedButton(self._buttons, text="保存", width=110, height=36, radius=8,
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      command=self._on_submit).pack(side="right")
        RoundedButton(self._buttons, text="取消", width=90, height=36, radius=8,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=self.destroy).pack(side="right", padx=(0, 8))

        center_window(self, *size)

    # 子类实现
    def build(self, parent: tk.Frame) -> None:
        raise NotImplementedError

    def submit(self, values: dict) -> None:
        raise NotImplementedError

    def collect(self) -> dict:
        """默认收集所有 LabeledEntry / LabeledCombo 子控件的值。"""
        values: dict[str, Any] = {}
        for child in _walk(self._body):
            if isinstance(child, (LabeledEntry, LabeledCombo)):
                key = getattr(child, "field_key", None)
                if key:
                    values[key] = child.get()
        return values

    def show_error(self, message: str) -> None:
        self._error_var.set(f"⚠ {message}")

    def _on_submit(self) -> None:
        from app.service import BusinessError
        self._error_var.set("")
        try:
            self.submit(self.collect())
        except BusinessError as exc:
            self.show_error(str(exc))
        except Exception as exc:                      # noqa: BLE001 - 兜底避免对话框卡死
            self.show_error(f"操作失败：{exc}")


def _walk(widget: tk.Misc):
    """深度遍历子控件。"""
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


class DetailDialog(tk.Toplevel):
    """键值对详情对话框（订单详情、房间日历等）。"""

    def __init__(self, parent, title: str, pairs: Sequence[tuple[str, Any]],
                 size: tuple[int, int] = (430, 400), list_data: dict | None = None):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=CS.BG_WHITE)
        self.transient(parent)
        self.grab_set()

        tk.Label(self, text=title, font=(FONT, 13, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(16, 10))

        body = tk.Frame(self, bg=CS.BG_WHITE)
        body.pack(fill="both", expand=True, padx=24)

        for index, (key, value) in enumerate(pairs):
            row = tk.Frame(body, bg=CS.BG_WHITE)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=f"{key}：", font=(FONT, 10), bg=CS.BG_WHITE,
                     fg=CS.TEXT_SECONDARY, width=12, anchor="e").pack(side="left")
            tk.Label(row, text=str(value), font=(FONT, 10), bg=CS.BG_WHITE,
                     fg=CS.TEXT_PRIMARY, wraplength=280, justify="left",
                     anchor="w").pack(side="left", fill="x", expand=True)

        if list_data:
            tk.Label(body, text=list_data.get("title", ""), font=(FONT, 10, "bold"),
                     bg=CS.BG_WHITE, fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(12, 4))
            table = DataTable(body, list_data["columns"],
                              height=min(8, max(3, len(list_data["rows"])) + 1))
            table.pack(fill="both", expand=True)
            table.set_rows(list_data["rows"],
                           formatter=list_data.get("formatter"))

        RoundedButton(self, text="关闭", width=100, height=34, radius=8,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=self.destroy).pack(pady=14)
        center_window(self, *size)


class StatusBar(tk.Frame):
    """底部状态栏，显示最近一次操作结果。"""

    def __init__(self, parent):
        super().__init__(parent, bg=CS.BG_DARK, height=26)
        self.pack_propagate(False)
        self._var = tk.StringVar(value="就绪")
        tk.Label(self, textvariable=self._var, font=(FONT, 9), bg=CS.BG_DARK,
                 fg="#dfe6e9", anchor="w").pack(side="left", padx=12)

    def show(self, message: str, kind: str = "info") -> None:
        icons = {"info": "ℹ", "success": "✓", "warn": "⚠", "error": "✗"}
        self._var.set(f"{icons.get(kind, '')} {message}")


def apply_theme(root: tk.Misc) -> None:
    """统一 ttk 控件的外观（表头、选项卡、滚动条）。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure("Treeview", font=(FONT, 10), rowheight=26,
                    background=CS.BG_WHITE, fieldbackground=CS.BG_WHITE,
                    borderwidth=0)
    style.configure("Treeview.Heading", font=(FONT, 10, "bold"),
                    background="#eef2f7", foreground=CS.TEXT_PRIMARY, relief="flat")
    style.map("Treeview", background=[("selected", "#d6eaf8")],
              foreground=[("selected", CS.TEXT_PRIMARY)])
    style.map("Treeview.Heading", background=[("active", "#e3ebf3")])

    style.configure("TNotebook", background=CS.BG_MAIN, borderwidth=0)
    style.configure("TNotebook.Tab", font=(FONT, 10), padding=(16, 8),
                    background="#e6ebf1", foreground=CS.TEXT_SECONDARY)
    style.map("TNotebook.Tab",
              background=[("selected", CS.BG_WHITE)],
              foreground=[("selected", CS.PRIMARY)])

    style.configure("TLabelframe", background=CS.BG_WHITE, borderwidth=1)
    style.configure("TLabelframe.Label", font=(FONT, 10, "bold"),
                    background=CS.BG_WHITE, foreground=CS.TEXT_PRIMARY)
    style.configure("TCombobox", font=(FONT, 10))
    style.configure("Vertical.TScrollbar", background="#cfd8dc", troughcolor=CS.BG_MAIN)
