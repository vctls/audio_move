# audio-move

A self-hosted web app that tags and files music the way foobar2000 does. You
pick a folder, fix its tags by hand or from MusicBrainz, then move the files
into your library with a foobar2000 title-formatting pattern.

- **Folder browser** over the mounted music folders. Clicking a folder loads
  its tracks, and subfolders too (CD1/CD2) unless you untick *Subfolders*.
- **Track list** with foobar2000-style selection (click, Ctrl+click,
  Shift+click, Ctrl+A), column sorting, Alt+↑/↓ to reorder and Del to drop
  tracks from the list. Double-click a cell to edit it in place: Enter moves
  down, Tab moves right. Right-click the header to choose columns.
- **Properties panel** for the selection. It shows `<multiple values>` where
  tracks differ. Editing a value writes it to every selected track, and an
  empty value removes the field. You can also add a field, remove one (✕), or
  rename one (double-click its name). In multi-value fields (ARTIST, GENRE…),
  `;` separates values.
- **Auto track number** numbers the selection in list order. It can restart
  at each disc and set TOTALTRACKS.
- **Tools**: *Guess values from file name*
  (`%tracknumber% - %artist% - %title%`, and `/` matches parent folders) and
  *Format field from other fields* (any title-formatting script).
- **MusicBrainz**: searches by artist and album (prefilled from the tags or
  the folder name), or by MBID or URL. Pasting a release-group URL lists its
  releases. Selecting a result shows the exact old → new change for every
  file. Fields that are the same for the whole album are grouped once. You
  can reassign which release track goes to which file, untick fields you want
  left alone, and optionally save the front cover as the folder image.
- **Cover art as a folder image.** The *Art* column and the info panel show
  embedded pictures (type, format, size in pixels and bytes) and the folder's
  `folder.jpg`/`folder.png`. *Tools → Remove embedded pictures* strips them
  from the selection on the next save, and the files shrink accordingly.
  Before that, it can write the best embedded front cover as `folder.jpg` or
  `folder.png` in folders that have none, so no artwork is lost. A folder
  only ever keeps one folder image. The name `folder` can be changed in
  Settings.
- **Move / copy / rename** with a live preview. It can also move the other
  files in the source folders (cover, logs, scans) and remove the emptied
  source folders. Every move is journaled and can be undone from the same
  dialog.

Edits are staged, not written: changed cells turn orange until you **Save**
(Ctrl+S). Undo and Redo (Ctrl+Z, Ctrl+Y) work on staged edits.

## Running it

```yaml
services:
  audio-move:
    build: .
    ports:
      - "8080:8080"
    environment:
      PUID: "1000"
      PGID: "1000"
      MUSIC_ROOTS: /music
      MB_CONTACT: you@example.com
    volumes:
      - /path/to/music:/music
      - ./config:/config
```

```sh
docker compose up -d --build
```

Then open <http://localhost:8080>.

| Variable      | Default   | Purpose |
|---------------|-----------|---------|
| `MUSIC_ROOTS` | `/music`  | Comma-separated folders shown in the browser. Nothing outside them can be read, written or used as a destination. |
| `PUID`/`PGID` | `1000`    | Owner of the files the app writes. Match the owner of your library. |
| `UMASK`       | `022`     | Umask for created files and folders. |
| `MB_CONTACT`  | —         | An email or URL sent in the MusicBrainz User-Agent, as their API terms ask. |
| `MAX_TRACKS`  | `5000`    | Upper limit on the tracks loaded from one folder. |

Settings, saved patterns and the move journal live in `/config`.

**Use one mount for both source and destination when you can.** For example,
mount `/srv/media` as `/music` and use `incoming/` and `library/` inside it.
Two separate bind mounts count as two filesystems, so every move turns into a
copy followed by a delete.

There is no authentication. Keep the app on your LAN or put it behind a
reverse proxy that handles auth.

## foobar2000 compatibility

The pattern language follows the
[foobar2000 title formatting reference](https://wiki.hydrogenaud.io/index.php?title=Foobar2000:Title_Formatting_Reference):
fields, remappings (`%album artist%`, `%artist%`, `%title%`, `%tracknumber%`,
`%discnumber%`…), `[...]` sections, `'quoting'`, and about 80 functions
(`$if`, `$if2`, `$caps`, `$num`, `$replace`, `$meta`, `$ascii`, `$year`…).

A few behaviours are worth knowing:

- `[...]` is a conditional section, not literal brackets. To get
  `Album [Flac]`, write `'['$caps(%codec%)']'`. The default pattern is
  `%album artist% - %year% - %album% '['$caps(%codec%)']'/%track number% - %artist% - %title%`.
- `$caps(%codec%)` gives `Flac` and `Mp3`. Use `$upper(%codec%)` for `FLAC`
  and `MP3`.
- `%tracknumber%` is padded to two digits, but `%track number%` is not. Auto
  track number and MusicBrainz write `01` by default, so both give `01`.
  The digit count is set in Settings.
- `%year%` is an addition. It reads a YEAR tag, or else the year of DATE.
- The extension is appended for you, as in foobar2000's File Operations.
- `/` and `\` inside tag values never create folders. They are replaced, as
  are `: * ? " < > |`, by `_` (configurable in Settings). Trailing dots and
  spaces are trimmed so the library stays readable over SMB.

Tags are shown under foobar2000 names (ALBUM ARTIST, TRACKNUMBER/TOTALTRACKS,
DISCNUMBER/TOTALDISCS…). They are mapped to each format's native fields:

- **FLAC, Ogg Vorbis and Opus** use Vorbis comments. Album artist is written
  as `ALBUMARTIST` or `ALBUM ARTIST`, chosen in Settings.
- **MP3, WAV, AIFF and DSF** use ID3v2.4 or 2.3, with the TXXX and UFID names
  Picard uses for MusicBrainz IDs.
- **M4A (AAC and ALAC)** uses MP4 atoms and iTunes freeform atoms.
- **Monkey's Audio, WavPack and Musepack** use APEv2.

Only the fields you change are rewritten. Unknown frames are left untouched,
and embedded pictures stay until you remove them.

## Development

```sh
cd backend && uv sync && uv run pytest
MUSIC_ROOTS=/some/music CONFIG_DIR=/tmp/am-config uv run uvicorn app.main:app --port 8080

cd frontend && npm install && npm run dev   # http://localhost:5173, proxies /api to :8080
```

The tests generate audio files with `ffmpeg`, so it must be on `PATH`.
