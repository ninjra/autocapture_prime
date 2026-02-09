from __future__ import annotations

import sqlite3

from autocapture.indexing.lexical import LexicalIndex
from autocapture.indexing.vector import VectorIndex, HashEmbedder
from autocapture_nx.state_layer.store_sqlite import StateTapeStore


def _versions(conn: sqlite3.Connection) -> list[int]:
    cur = conn.execute("SELECT version FROM schema_migrations ORDER BY version")
    return [int(row[0]) for row in cur.fetchall() if row]


def test_migrations_table_created_for_indexes(tmp_path) -> None:
    lex_path = tmp_path / "lexical.db"
    vec_path = tmp_path / "vector.db"

    lex = LexicalIndex(lex_path)
    vec = VectorIndex(vec_path, HashEmbedder(64))

    assert _versions(lex._conn) == [1]
    assert _versions(vec._conn) == [1]


def test_migrations_table_created_for_state_tape(tmp_path) -> None:
    path = tmp_path / "state_tape.db"
    store = StateTapeStore(path)
    store.insert_batch([], [])
    conn = store._conn
    assert conn is not None
    assert _versions(conn) == [1]

