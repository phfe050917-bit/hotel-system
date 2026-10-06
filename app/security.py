"""
密码安全模块 —— 加盐哈希与校验。

原系统把密码明文存在 user.password 里（连自己的 SQL 注释都写着"建议加密"
却没做）。安全性要求：
  · 数据库被看到也不能直接得到明文密码；
  · 同一密码在不同账号下哈希值不同（加盐），防止彩虹表与批量比对；
  · 校验使用常量时间比较，避免计时侧信道。

存储格式（单列 VARCHAR(128) 自描述）：
    pbkdf2_sha256$<迭代次数>$<盐十六进制>$<哈希十六进制>
"""

from __future__ import annotations

import hashlib
import hmac
import os

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 200_000
SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    """把明文密码转换成可入库的加盐哈希字符串。"""
    if not password:
        raise ValueError("密码不能为空")

    salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验明文密码与库中哈希是否匹配。格式非法一律返回 False。"""
    if not password or not stored:
        return False

    try:
        algorithm, iterations_str, salt_hex, digest_hex = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str) -> bool:
    """判断已有哈希是否需要按当前参数重算（迭代次数升级时使用）。"""
    try:
        algorithm, iterations_str, _, _ = stored.split("$")
    except (ValueError, AttributeError):
        return True
    return algorithm != ALGORITHM or int(iterations_str) < ITERATIONS
