from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import psycopg2


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    database: str
    user: str
    password: str


def load_db_config() -> DbConfig:
    return DbConfig(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ.get("DB_NAME", "anomaly_detection"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", "12@firstlove"),
    )


def get_conn():
    cfg = load_db_config()
    return psycopg2.connect(
        host=cfg.host,
        port=cfg.port,
        dbname=cfg.database,
        user=cfg.user,
        password=cfg.password,
    )


def fetch_user_by_email(email: str) -> Optional[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, password_hash, username FROM users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "email": row[1],
                "password_hash": row[2],
                "username": row[3],
            }
    finally:
        conn.close()
