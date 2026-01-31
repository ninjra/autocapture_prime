# Safe Mode

Safe mode boots with defaults only and ignores user overrides.

## Behavior
- Only plugins in `plugins.default_pack` are loaded.
- Any user config is ignored.
- Network remains denied unless explicitly enabled in defaults.

## Usage
- `autocapture --safe-mode doctor`
