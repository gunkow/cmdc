# cmdc

Menu-bar app: triple Cmd+C corrects the copied text with an LLM and pastes it back.

## Build

`./scripts/build_app.sh` rebuilds the launcher and installs it to `/Applications/cmdc.app`.
Always land a rebuild in `/Applications` - a bundle left in `dist/` is not what runs.
The launcher imports the package from this repo, so source edits only need an app restart.

## Test

`./.venv/bin/python -m unittest discover -s tests` - run it outside an agent sandbox;
AppKit menu calls abort without a WindowServer connection.

## Git

Commit and push after each meaningful change; never leave finished work uncommitted.
The keychain offers the wrong account here, so push with
`git -c credential.helper= -c credential.helper='!gh auth git-credential' push`.

## Debug

Log: `/tmp/cmdc.log`. Set `CMDC_DEBUG=1` for per-key tracing. Config: `~/.config/cmdc/config.json`.
If the shortcut is dead, check Secure Input first: it blocks every event tap system-wide,
and the `Secure Input: …` menu item names the holder.
