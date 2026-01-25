# ops/dev

Local-only dev harness configuration.

## Files
- `common.env.example`: copy to `common.env` and fill in commands.
- `ports.env.example`: copy to `ports.env` and fill in ports.

These files are ignored by git:
- `common.env`
- `ports.env`

## Typical setup
1) Copy the examples:
   - `cp ops/dev/common.env.example ops/dev/common.env`
   - `cp ops/dev/ports.env.example ops/dev/ports.env`
2) Set `DEV_BACKEND_CMD` (and optional `DEV_BACKEND_PORT`).
3) Run `./dev.sh doctor` then `./dev.sh up`.
