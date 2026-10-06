"""
Tkinter 界面层。

分层约定：
    ui/widgets.py    通用控件与对话框（圆角按钮、表格、日期输入、表单框）
    ui/base.py       窗口基类：角色会话、统一异常处理、退出登录
    ui/login.py      登录 / 注册 / 修改密码
    ui/guest*.py     客人端（六个标签页分模块）
    ui/reception*.py 前台端
    ui/admin*.py     管理端

界面只做两件事：收集用户输入、渲染 service 层返回的数据。
任何业务规则都不允许写在此层，否则又会退回到"三端各写一份"的老问题。
"""

__all__ = ["widgets", "base", "login", "guest", "reception", "admin"]
