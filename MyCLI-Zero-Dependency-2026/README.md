# MyCLI — Windows Control Center (Zero Dependency Edition)

A local, browser-based Windows control center: real file management, an
interactive terminal, and system tooling (processes, services, storage,
network, health, installed apps, winget, installers) — served entirely by a
plain Node.js HTTP server with **zero third-party runtime dependencies**.

## Problem

Everyday Windows administration is scattered across a dozen built-in tools
(Task Manager, Services, Device Manager, File Explorer, PowerShell, winget)
with no single, scriptable, inspectable home. MyCLI puts the common ones
behind one lightweight local web UI.

## Solution

A single Node.js process (`server.js`) does two things: it serves a small
static front end, and it exposes a JSON API that composes the operating
system's own tools — `node:fs` for the filesystem, `node:child_process` to
spawn shells and PowerShell, `node:http` for everything else. No framework,
no bundler, no package manager download required to run it.

## Key Features

- **File manager** — browse, create, rename, copy, move, and delete files
  and folders; view properties; open a folder in a new terminal.
- **Terminal** — multiple concurrent PowerShell/cmd (or `sh` on non-Windows)
  sessions, streamed live to the browser.
- **System tools** — live process list with kill, service start/stop/restart,
  startup items, storage volumes, network configuration, and a health
  dashboard, all sourced from PowerShell/CIM on Windows.
- **Applications** — installed-application inventory (from the registry) and
  a winget front end (search/install/upgrade) with a trusted installer runner
  for `.exe`/`.msi` files.
- **History & activity log** — every command and every filesystem/system
  action is recorded, searchable, and exportable.
- **Workspace state stack** — push/pop the current view, folder, and terminal
  directory to jump around and back.

## Hackathon Track

**Track A — Developer Tools & CLI.** MyCLI is a control-center/automation
tool for developers and admins working on Windows: it wraps file utilities,
a terminal, and Git-adjacent day-to-day OS operations behind one interface
with clear, composable JSON endpoints underneath.

## Why This Is Useful

It replaces switching between Explorer, Task Manager, Services, Device
Manager, and a terminal window with one page, while keeping every action
auditable in the history and activity log — genuinely useful for anyone who
spends their day driving a Windows machine.

## Architecture

```
server.js          Node http server: routing, static files, JSON API
lib/
  store.js         History/activity/settings persistence (JSON on disk)
  events.js        Server-Sent Events broadcaster (replaces Electron IPC push)
  fsOps.js         Filesystem operations + cross-platform "open" helpers
  terminalOps.js   Shell session management and child-process execution
  systemOps.js     Windows system info (PowerShell/CIM), winget, installers
public/
  index.html       UI shell (unchanged from the original app)
  styles.css       Styling (unchanged)
  renderer.js       UI logic (unchanged — talks to window.mycli, same as before)
  api-client.js    NEW: implements window.mycli over fetch()/EventSource
                   instead of Electron's contextBridge/ipcRenderer
  modules/gestures.js  Touch gesture support (unchanged)
tests/             node:test suites
scripts/           build.js, check-size.js
```

The UI code (`index.html`, `styles.css`, `renderer.js`) is the same code the
original Electron app shipped. Only the transport underneath changed: what
used to be `ipcRenderer.invoke(...)` is now `fetch('/api/...')`, and what
used to be Electron's native OS dialogs is now a small in-page picker backed
by a `/api/browse` endpoint. See `STDLIB.md` for the full substitution list.

## Technology Used

Node.js standard library only: `http`, `fs`, `path`, `url`, `os`, `crypto`,
`child_process`, `assert`, `test`. Front end: plain HTML/CSS/JavaScript using
only browser-native `fetch`, `EventSource`, and DOM APIs — no React, no
jQuery, no CSS framework, no CDN scripts.

## Zero-Dependency Explanation

`package.json` ships `"dependencies": {}` and `"devDependencies": {}`. The
original app depended on `electron` and `electron-builder`; both are
removed and replaced with standard-library equivalents. Full audit and
substitution table: **[STDLIB.md](./STDLIB.md)**.

## Installation

Requires only Node.js ≥ 18 (for built-in `fetch`/`node:test`). No `npm
install` step — there is nothing to install.

## One-Command Build

```
npm run build
```

Runs `scripts/build.js`, which syntax-checks every source file with
`node --check`, assembles a self-contained `dist/` copy, and prints a
deterministic SHA-256 hash of that copy (see Reproducible Build below).

## One-Command Run

```
npm start
```

(equivalently `node server.js`). Then open **http://127.0.0.1:4173** in a
browser. Override the port/host with `PORT=8080 HOST=0.0.0.0 node server.js`.

## Usage

- **Files** tab: choose a folder, create/rename/copy/move/delete entries,
  open a folder in a terminal.
- **Terminal** tab: start a new PowerShell or cmd session, run commands,
  inspect live output.
- **OS Manager / Processes / Services / Startup / Storage / Network /
  Health**: read-only or lightly destructive system views (Windows-only —
  these call PowerShell/CIM and return a clear error on other platforms).
- **Applications**: browse installed software and drive winget.
- **Activity / Command Center**: full history and audit log with export.

## Testing

```
npm test
```

Runs `node --test tests/`: 25 tests across filesystem operations, the data
store, and a full HTTP integration suite that starts the real server on an
ephemeral port and exercises the JSON API end to end (including actually
spawning a shell command and reading the resulting history entry).

## Security Considerations

See **STDLIB.md §5** for the full write-up. In short: the server binds to
`127.0.0.1` only, all paths are resolved and names validated before touching
the filesystem, secrets are redacted from stored history/activity, and no
custom cryptography is implemented (`crypto.randomUUID()` only). This is a
local, single-user tool — it is not hardened against a malicious co-tenant
of the same machine while it's running.

## Project Structure

See **Architecture** above.

## Performance Considerations

Everything runs on `localhost`, so the HTTP round trip per API call adds
negligible latency compared to the original in-process IPC call. Live
terminal/activity output streams over a single long-lived SSE connection
rather than polling.

## Limitations

- Windows-only features (system info, processes, services, startup,
  storage, network, health, installed apps, most Windows-tool launchers)
  return a clear error on macOS/Linux, exactly as the original app was
  Windows-only for those same features.
- Deleted files go to an app-managed trash folder, not the real OS Recycle
  Bin (documented trade-off in STDLIB.md #7).
- The folder/file picker is a custom in-page modal, not the OS-native
  dialog.

## Future Improvements

- A native Recycle Bin bridge (e.g. a small native helper binary invoked by
  `child_process`, still without adding any *runtime* npm dependency).
- Optional token-based auth for exposing the server beyond `127.0.0.1`.
- WebSocket-based terminal I/O instead of the current run-to-completion
  command model, for long-running interactive processes.

## Bonus Challenges Claimed

- **Reproducible Build:** `npm run build` twice in a row produces an
  identical `SHA-256(dist)` hash (verified during development — see
  `BUILD_HASH.txt` after running the build).
- **Package Killer:** Electron itself is the "package" replaced — see
  STDLIB.md substitutions #1–#3 for what a full IPC-driven desktop shell
  becomes on `node:http` + Server-Sent Events alone.
- **STDLIB Log:** 11 documented substitutions in STDLIB.md §3.

## AI Usage Disclosure

An AI coding assistant (Claude) was used to inspect the original Electron
source, design the zero-dependency architecture (HTTP + SSE replacing
Electron IPC, an in-page picker replacing native dialogs), implement the
server and client-side shim, and write the accompanying tests and
documentation in this repository.

## License

MIT — see [LICENSE](./LICENSE).
