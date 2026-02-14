ROOT_SPOOL/
  session_<session_id>/
    manifest.json
    meta/
      frames.pb.zst
      input.pb.zst
      detections.pb.zst
    frames/
      frame_000000.png
      frame_000001.png
      ...
    COMPLETE.json

Atomicity rules
- Hypervisor writes artifacts to `*.tmp` then renames atomically.
- `COMPLETE.json` is the final marker written last. Autocapture must ignore any
  session directory without `COMPLETE.json`.

Compression
- `*.pb.zst` are Zstandard-compressed protobuf payloads.

manifest.json
- JSON serialization of `SessionManifest` plus any extra fields (append-only).
