from __future__ import annotations

from pathlib import Path

from autocapture_nx.kernel.hashing import sha256_directory, sha256_file


def test_sha256_file_normalizes_crlf_for_text_suffix(tmp_path: Path) -> None:
    lf = tmp_path / "a.py"
    crlf = tmp_path / "b.py"
    lf.write_bytes(b"print('x')\nprint('y')\n")
    crlf.write_bytes(b"print('x')\r\nprint('y')\r\n")
    assert sha256_file(lf) == sha256_file(crlf)


def test_sha256_file_does_not_normalize_unknown_suffix(tmp_path: Path) -> None:
    lf = tmp_path / "a.bin"
    crlf = tmp_path / "b.bin"
    lf.write_bytes(b"x\ny\n")
    crlf.write_bytes(b"x\r\ny\r\n")
    assert sha256_file(lf) != sha256_file(crlf)


def test_sha256_directory_normalizes_text_files(tmp_path: Path) -> None:
    dir_lf = tmp_path / "lf"
    dir_crlf = tmp_path / "crlf"
    dir_lf.mkdir()
    dir_crlf.mkdir()
    (dir_lf / "plugin.json").write_bytes(b'{\n  "x": 1\n}\n')
    (dir_crlf / "plugin.json").write_bytes(b'{\r\n  "x": 1\r\n}\r\n')
    assert sha256_directory(dir_lf) == sha256_directory(dir_crlf)

