#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash "$repo_root/tools/run_fixture_pipeline_full.sh"
bash "$repo_root/tools/run_fixture_pipeline_full_mp4.sh"

