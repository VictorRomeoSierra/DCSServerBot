# Extension "TacviewLink"

Posts a clickable [Lardoon](https://github.com/b1naryth1ef/lardoon) viewer link to a
Discord channel each time a mission ends and its ACMI file is indexed.

This is the modern replacement for the Tacview extension's `target` Discord upload
field — that path is hard-capped at 10 MB by Discord and effectively unusable for
real ACMI files (which routinely run 40 - 160 MB).

## How it works

1. The Tacview extension records the mission and writes an ACMI file.
2. The Lardoon extension's scheduled `import` run (default every 5 minutes) indexes
   the new file.
3. **TacviewLink** tails `dcs.log` for the `Successfully saved [...acmi]` line, then
   polls `{base_url}/api/replay` until lardoon reports the file is indexed, and
   posts a clickable embed with the viewer URL `{base_url}/replay/{id}` to the
   configured Discord channel.

## Dependencies

* **Tacview** extension — produces the ACMI files this extension links to.
* **Lardoon** extension — indexes the files and serves the viewer. TacviewLink
  reads the public URL from the sibling Lardoon extension's `url` config by
  default (no need to configure it twice).

If neither dependency is present, TacviewLink logs a warning at startup and stays
idle.

## Configuration

Configured per-instance in `nodes.yaml`:

```yaml
MyNode:
  # [...]
  instances:
    DCS.dcs_serverrelease:
      # [...]
      extensions:
        Tacview:
          # [...]
        Lardoon:
          # [...]
          url: 'https://tacview.example.com'   # public URL for the lardoon UI
        TacviewLink:
          enabled: true
          target: '<id:112233445566778899>'    # Discord channel to post links to
```

### Fields

* **target** *(required)* — Discord channel reference in `<id:...>` syntax. This
  matches the existing convention used by the Tacview extension's `target` field.
* **base_url** *(optional)* — Public base URL for the lardoon viewer
  (`https://tacview.example.com`). Defaults to reading the sibling Lardoon
  extension's `url` field, so usually you don't need to set this here.
* **poll_timeout** *(optional, default `600`)* — Maximum seconds to wait for the
  ACMI file to appear in lardoon's index after mission end. Lardoon's import job
  runs every 5 minutes by default, so 10 minutes is a comfortable upper bound.
* **poll_interval** *(optional, default `30`)* — Seconds between poll attempts
  against `{base_url}/api/replay`.
* **log** *(optional)* — Path to the DCS log file to tail. Defaults to
  `{instance.home}/Logs/dcs.log`.

## Failure modes

All failures log a warning to the bot log and skip the post — they never raise:

* ACMI file does not appear within 60 seconds — usually means the mission was
  too short or Tacview crashed.
* Lardoon does not index the file within `poll_timeout` — lardoon may be down,
  or the import job is stuck. Check `tacview.example.com` directly.
* Discord channel ID is invalid or the bot lacks permission to post — fix the
  channel reference or the bot's role on the server.

## Notes

* The mission name is captured at the moment the ACMI is detected, not at post
  time. This avoids a race where the polling window outlasts the current
  mission and the link gets attributed to the next one.
* Multiple posts can be in flight at once if missions rotate quickly — each
  ACMI gets its own polling task.
