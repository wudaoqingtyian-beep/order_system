"""数据库连接与事务管理（PyMySQL，不使用 ORM）。"""
import os
import contextlib

import pymysql
from pymysql.cursors import DictCursor

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "123456")
DB_NAME = os.getenv("DB_NAME", "order_system")


def connect(db_name=None, autocommit=True, with_db=True):
    """建立一个新连接。db_name=None 时使用当前配置的 DB_NAME（运行时读取）。

    with_db=False 表示不指定数据库（建库场景）。
    """
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=(db_name or DB_NAME) if with_db else None,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=autocommit,
    )


@contextlib.contextmanager
def get_conn():
    """只读/单条写入用的短连接（自动提交）。"""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def transaction():
    """写事务：正常提交，任何异常回滚，绝不留下半成品数据。"""
    conn = connect(autocommit=False)
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query_all(sql, args=None, conn=None):
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(sql, args or ())
            return cur.fetchall()
    with get_conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, args or ())
            return cur.fetchall()


def query_one(sql, args=None, conn=None):
    rows = query_all(sql, args, conn)
    return rows[0] if rows else None
