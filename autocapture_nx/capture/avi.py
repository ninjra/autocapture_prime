"""Minimal MJPEG AVI writer/reader for capture segments."""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from typing import BinaryIO


@dataclass
class AviIndexEntry:
    offset: int
    size: int


class AviMjpegWriter:
    def __init__(self, path: str, width: int, height: int, fps: int) -> None:
        self._path = path
        self._width = int(width)
        self._height = int(height)
        self._fps = max(1, int(fps))
        self._frame_count = 0
        self._index: list[AviIndexEntry] = []
        self._fp: BinaryIO = open(path, "wb")
        self._write_header()

    @property
    def path(self) -> str:
        return self._path

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def _write_header(self) -> None:
        f = self._fp
        # RIFF header
        f.write(b"RIFF")
        self._riff_size_pos = f.tell()
        f.write(struct.pack("<I", 0))
        f.write(b"AVI ")

        # LIST hdrl
        f.write(b"LIST")
        self._hdrl_size_pos = f.tell()
        f.write(struct.pack("<I", 0))
        f.write(b"hdrl")

        # avih chunk
        f.write(b"avih")
        f.write(struct.pack("<I", 56))
        self._avih_pos = f.tell()
        microsec = int(1_000_000 // self._fps)
        flags = 0x10  # AVIF_HASINDEX
        f.write(
            struct.pack(
                "<IIIIIIIIII",
                microsec,
                0,
                0,
                flags,
                0,  # total frames placeholder
                0,
                1,
                0,
                self._width,
                self._height,
            )
        )
        f.write(struct.pack("<IIII", 0, 0, 0, 0))
        self._avih_microsec_pos = self._avih_pos
        self._avih_frames_pos = self._avih_pos + 16

        # LIST strl
        f.write(b"LIST")
        self._strl_size_pos = f.tell()
        f.write(struct.pack("<I", 0))
        f.write(b"strl")

        # strh chunk
        f.write(b"strh")
        f.write(struct.pack("<I", 56))
        self._strh_pos = f.tell()
        f.write(b"vids")
        f.write(b"MJPG")
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", 1))  # scale
        f.write(struct.pack("<I", self._fps))  # rate
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", 0))  # length placeholder
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", 0xFFFFFFFF))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<hhhh", 0, 0, self._width, self._height))
        self._strh_rate_pos = self._strh_pos + 24
        self._strh_length_pos = self._strh_pos + 32

        # strf chunk (BITMAPINFOHEADER)
        f.write(b"strf")
        f.write(struct.pack("<I", 40))
        compression = _fourcc("MJPG")
        f.write(
            struct.pack(
                "<IIIHHIIIIII",
                40,
                self._width,
                self._height,
                1,
                24,
                compression,
                0,
                0,
                0,
                0,
                0,
            )
        )

        # Patch LIST sizes now that hdrl and strl are complete.
        hdrl_end = f.tell()
        self._patch_size(self._strl_size_pos, hdrl_end)
        self._patch_size(self._hdrl_size_pos, hdrl_end)

        # LIST movi
        f.write(b"LIST")
        self._movi_size_pos = f.tell()
        f.write(struct.pack("<I", 0))
        f.write(b"movi")
        self._movi_start = f.tell()

    def _patch_size(self, size_pos: int, end_pos: int) -> None:
        # LIST size is length of type+data (end_pos - (size_pos + 4)).
        current = self._fp.tell()
        self._fp.seek(size_pos)
        self._fp.write(struct.pack("<I", max(0, end_pos - (size_pos + 4))))
        self._fp.seek(current)

    def add_frame(self, jpeg_bytes: bytes) -> None:
        if not jpeg_bytes:
            return
        f = self._fp
        chunk_id = b"00dc"
        pos = f.tell()
        f.write(chunk_id)
        f.write(struct.pack("<I", len(jpeg_bytes)))
        f.write(jpeg_bytes)
        if len(jpeg_bytes) % 2:
            f.write(b"\x00")
        offset = pos - self._movi_start
        self._index.append(AviIndexEntry(offset=offset, size=len(jpeg_bytes)))
        self._frame_count += 1

    def close(self, duration_ms: int | None = None) -> None:
        if self._fp.closed:
            return
        f = self._fp
        # Write idx1 chunk
        idx_start = f.tell()
        f.write(b"idx1")
        f.write(struct.pack("<I", len(self._index) * 16))
        for entry in self._index:
            f.write(b"00dc")
            f.write(struct.pack("<I", 0x10))
            f.write(struct.pack("<I", entry.offset))
            f.write(struct.pack("<I", entry.size))

        end_pos = f.tell()
        # Patch movi size
        self._patch_size(self._movi_size_pos, idx_start)
        # Patch RIFF size
        f.seek(self._riff_size_pos)
        f.write(struct.pack("<I", max(0, end_pos - 8)))
        # Patch frame counts
        f.seek(self._avih_frames_pos)
        f.write(struct.pack("<I", self._frame_count))
        f.seek(self._strh_length_pos)
        f.write(struct.pack("<I", self._frame_count))

        # Patch fps based on duration if provided
        if duration_ms and duration_ms > 0 and self._frame_count > 0:
            us_per_frame = max(1, (duration_ms * 1000) // self._frame_count)
            fps = max(1, 1_000_000 // us_per_frame)
            f.seek(self._avih_microsec_pos)
            f.write(struct.pack("<I", us_per_frame))
            f.seek(self._strh_rate_pos)
            f.write(struct.pack("<I", fps))

        f.close()


class AviMjpegReader:
    def __init__(self, source: bytes | BinaryIO) -> None:
        if isinstance(source, (bytes, bytearray)):
            self._fp = io.BytesIO(source)
            self._close_fp = True
        else:
            self._fp = source
            self._close_fp = False

    def close(self) -> None:
        if self._close_fp:
            self._fp.close()

    def first_frame(self) -> bytes | None:
        fp = self._fp
        fp.seek(0)
        movi_start = _find_movi(fp)
        if movi_start is None:
            return None
        fp.seek(movi_start)
        chunk_id = fp.read(4)
        if len(chunk_id) < 4:
            return None
        size_bytes = fp.read(4)
        if len(size_bytes) < 4:
            return None
        size = struct.unpack("<I", size_bytes)[0]
        data = fp.read(size)
        return data


def _find_movi(fp: BinaryIO) -> int | None:
    fp.seek(0)
    while True:
        tag = fp.read(4)
        if len(tag) < 4:
            return None
        if tag == b"RIFF":
            _ = fp.read(4)
            _ = fp.read(4)
            continue
        size_bytes = fp.read(4)
        if len(size_bytes) < 4:
            return None
        size = struct.unpack("<I", size_bytes)[0]
        if tag == b"LIST":
            list_type = fp.read(4)
            if list_type == b"movi":
                return fp.tell()
            fp.seek(max(0, size - 4), 1)
        else:
            fp.seek(size + (size % 2), 1)


def _fourcc(text: str) -> int:
    data = text.encode("ascii")
    return int.from_bytes(data, "little")
