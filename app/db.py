"""
数据访问层。

相对原 database.py 的关键改进：

  1. 事务与回滚 —— 原实现每个 execute 直接 commit，且全项目没有一处
     rollback，异常后连接会残留未完成事务。现在提供 transaction()
     上下文管理器，多步业务操作（下单、汇总、支付）要么全成功要么全回滚。

  2. 断线重连 —— 原 _ensure_connection 的 except 分支里又调用同一个
     ping，等于没有兜底。现在真正尝试重连并重建游标。

  3. 不吞异常 —— 原 query 出错时直接把异常抛给 Tkinter 回调，
     控制台一堆栈、界面卡死。现在统一封装为 DatabaseError，
     由界面层捕获后弹提示。

  4. 游标在事务中复用同一连接，DictCursor 让结果可直接按键取值。
"""

from __future__ import annotations

import contextlib
import threading
from typing import Any, Iterable, Iterator, Sequence

import pymysql
import pymysql.cursors

from app.config import DB_CONFIG


class DatabaseError(RuntimeError):
    """包装底层数据库异常，便于界面层统一提示。"""

    def __init__(self, message: str, *, original: Exception | None = None):
        super().__init__(message)
        self.original = original


class Database:
    """MySQL 连接的薄封装：查询、执行、事务、重连。"""

    def __init__(self, **overrides: Any):
        config = dict(DB_CONFIG)
        config.update(overrides)
        self._config = config
        self._lock = threading.RLock()
        self.connection: pymysql.connections.Connection | None = None
        self.cursor: pymysql.cursors.DictCursor | None = None
        self._connect()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
    def _connect(self) -> None:
        try:
            self.connection = pymysql.connect(
                host=self._config["host"],
                port=int(self._config["port"]),
                user=self._config["user"],
                password=self._config["password"],
                database=self._config["database"],
                charset=self._config.get("charset", "utf8mb4"),
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False,          # 显式控制事务边界
            )
            self.cursor = self.connection.cursor()
        except pymysql.Error as exc:
            raise DatabaseError(
                f"数据库连接失败：{exc}\n请检查 MySQL 是否启动，以及 "
                f"config.local.py / 环境变量中的账号密码是否正确。",
                original=exc,
            ) from exc

    def _ensure_connection(self) -> None:
        """连接失效时真正重建连接，而不是重复调用同一个 ping。"""
        if self.connection is None:
            self._connect()
            return
        try:
            self.connection.ping(reconnect=True)
            if self.cursor is None:
                self.cursor = self.connection.cursor()
        except pymysql.Error:
            # 重连失败则彻底重建
            with contextlib.suppress(Exception):
                self.connection.close()
            self.connection = None
            self.cursor = None
            self._connect()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict]:
        """执行 SELECT，返回全部结果行（列表套字典）。"""
        with self._lock:
            try:
                self._ensure_connection()
                self.cursor.execute(sql, tuple(params or ()))
                return list(self.cursor.fetchall())
            except pymysql.Error as exc:
                raise DatabaseError(f"查询失败：{exc}", original=exc) from exc

    def query_one(self, sql: str, params: Sequence[Any] | None = None) -> dict | None:
        """执行 SELECT，返回第一行或 None。"""
        with self._lock:
            try:
                self._ensure_connection()
                self.cursor.execute(sql, tuple(params or ()))
                return self.cursor.fetchone()
            except pymysql.Error as exc:
                raise DatabaseError(f"查询失败：{exc}", original=exc) from exc

    def query_value(self, sql: str, params: Sequence[Any] | None = None,
                    default: Any = None) -> Any:
        """取单行单列，常用于 COUNT/SUM 这类聚合。无结果时返回 default。"""
        row = self.query_one(sql, params)
        if not row:
            return default
        value = next(iter(row.values()), default)
        return default if value is None else value

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        """
        执行单条写语句并提交，返回受影响行数。

        单条语句自身即构成一个事务；多步操作请使用 transaction()。
        """
        with self._lock:
            self._ensure_connection()
            try:
                affected = self.cursor.execute(sql, tuple(params or ()))
                self.connection.commit()
                return affected
            except pymysql.Error as exc:
                self._rollback_quietly()
                raise DatabaseError(f"写入失败：{exc}", original=exc) from exc

    def execute_many(self, sql: str, rows: Iterable[Sequence[Any]]) -> int:
        """批量写入，整体提交。"""
        payload = [tuple(row) for row in rows]
        if not payload:
            return 0
        with self._lock:
            self._ensure_connection()
            try:
                affected = self.cursor.executemany(sql, payload)
                self.connection.commit()
                return affected
            except pymysql.Error as exc:
                self._rollback_quietly()
                raise DatabaseError(f"批量写入失败：{exc}", original=exc) from exc

    def _rollback_quietly(self) -> None:
        if self.connection is None:
            return
        with contextlib.suppress(Exception):
            self.connection.rollback()

    # ------------------------------------------------------------------
    # 事务
    # ------------------------------------------------------------------
    @contextlib.contextmanager
    def transaction(self, cursor_class=None) -> Iterator["Transaction"]:
        """
        多步写操作的事务边界。

        用法：
            with db.transaction() as tx:
                tx.execute("INSERT INTO ...", (...))
                tx.execute("UPDATE ...", (...))
            # 正常退出即提交；抛异常则整体回滚

        原系统"查容量 -> 插预约"是两次独立提交，中间存在并发窗口，
        现在都放在同一个事务里。
        """
        self._ensure_connection()
        cursor = self.connection.cursor(cursor_class) if cursor_class else self.connection.cursor()
        tx = Transaction(self.connection, cursor)
        try:
            with self._lock:
                yield tx
                self.connection.commit()
        except Exception:
            with contextlib.suppress(Exception):
                self.connection.rollback()
            raise
        finally:
            with contextlib.suppress(Exception):
                cursor.close()

    # ------------------------------------------------------------------
    def close(self) -> None:
        with contextlib.suppress(Exception):
            if self.cursor is not None:
                self.cursor.close()
        with contextlib.suppress(Exception):
            if self.connection is not None:
                self.connection.close()
        self.cursor = None
        self.connection = None

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


class Transaction:
    """事务内使用的游标包装，提供与 Database 一致的调用方式。"""

    def __init__(self, connection: pymysql.connections.Connection, cursor):
        self._connection = connection
        self._cursor = cursor

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        try:
            return self._cursor.execute(sql, tuple(params or ()))
        except pymysql.Error as exc:
            raise DatabaseError(f"事务内写入失败：{exc}", original=exc) from exc

    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict]:
        try:
            self._cursor.execute(sql, tuple(params or ()))
            return list(self._cursor.fetchall())
        except pymysql.Error as exc:
            raise DatabaseError(f"事务内查询失败：{exc}", original=exc) from exc

    def query_one(self, sql: str, params: Sequence[Any] | None = None) -> dict | None:
        try:
            self._cursor.execute(sql, tuple(params or ()))
            return self._cursor.fetchone()
        except pymysql.Error as exc:
            raise DatabaseError(f"事务内查询失败：{exc}", original=exc) from exc

    def query_value(self, sql: str, params: Sequence[Any] | None = None,
                    default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if not row:
            return default
        value = next(iter(row.values()), default)
        return default if value is None else value

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount
