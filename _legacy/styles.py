"""酒店服务预约系统的UI样式模块，提供圆角按钮、卡片式容器和配色方案。"""

import tkinter as tk


class RoundedButton(tk.Canvas):
    """基于 Canvas 绘制的圆角按钮组件。"""

    def __init__(self, parent, text="", width=160, height=42, radius=12,
                 color="#3498db", hover_color=None, text_color="white",
                 font=("微软雅黑", 11, "bold"), command=None, **kwargs):
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bg=parent['bg'], **kwargs)

        self._text = text
        self._width = width
        self._height = height
        self._radius = radius
        self._color = color
        self._hover_color = hover_color or self._darken(color)
        self._text_color = text_color
        self._font = font
        self._command = command
        self._is_hovered = False

        self._draw_button(self._color)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _darken(self, hex_color):
        """将颜色稍微加深（用于悬停效果）"""
        hex_color = hex_color.lstrip('#')
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        factor = 0.85
        r, g, b = int(r * factor), int(g * factor), int(b * factor)
        return f'#{r:02x}{g:02x}{b:02x}'

    def _draw_button(self, color):
        """绘制圆角矩形按钮"""
        self.delete("all")
        r = self._radius
        w, h = self._width, self._height

        self.create_arc((0, 0, 2*r, 2*r), start=90, extent=90, fill=color, outline=color)
        self.create_arc((w-2*r, 0, w, 2*r), start=0, extent=90, fill=color, outline=color)
        self.create_arc((w-2*r, h-2*r, w, h), start=270, extent=90, fill=color, outline=color)
        self.create_arc((0, h-2*r, 2*r, h), start=180, extent=90, fill=color, outline=color)
        self.create_rectangle((r, 0, w-r, h), fill=color, outline=color)
        self.create_rectangle((0, r, w, h-r), fill=color, outline=color)

        self.create_text(w/2, h/2, text=self._text, fill=self._text_color,
                         font=self._font, anchor="center")

    def _on_enter(self, event):
        self._is_hovered = True
        self._draw_button(self._hover_color)
        self.config(cursor="hand2")

    def _on_leave(self, event):
        self._is_hovered = False
        self._draw_button(self._color)
        self.config(cursor="")

    def _on_click(self, event):
        if self._command:
            self._command()

    def config_text(self, text):
        """更新按钮文字"""
        self._text = text
        self._draw_button(self._color)


class StyledFrame(tk.Frame):
    """带有圆角边框效果的卡片式容器。"""

    def __init__(self, parent, padding=15, bg="white", **kwargs):
        super().__init__(parent, bg=bg, **kwargs)

        # 模拟卡片效果：用白色背景 + 内边距
        self.config(
            highlightbackground="#e0e0e0",
            highlightthickness=1,
            padx=padding,
            pady=padding,
            relief="flat",
            bd=0
        )


class ColorScheme:
    """全局配色方案"""

    # 主色调
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

    # 背景色
    BG_MAIN = "#f0f2f5"
    BG_WHITE = "#ffffff"
    BG_CARD = "#ffffff"
    BG_DARK = "#2c3e50"

    # 文字色
    TEXT_PRIMARY = "#2c3e50"
    TEXT_SECONDARY = "#7f8c8d"
    TEXT_MUTED = "#bdc3c7"
    TEXT_WHITE = "#ffffff"

    # 边框色
    BORDER = "#e0e0e0"
    BORDER_LIGHT = "#ecf0f1"
