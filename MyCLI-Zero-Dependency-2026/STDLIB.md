# STDLIB.md — MyCLI (Zero Dependency Edition)

## 1. Dependency Philosophy

MyCLI was originally an **Electron** desktop app: a Windows control center with
real file management, a terminal, and system tooling (processes, services,
storage, network, installed apps, winget). Electron itself is a third-party
runtime dependency — it bundles Chromium and a matching Node.js build and
ships as an npm package (`electron`), packaged for distribution by a second
npm package (`electron-builder`). Neither can be part of a Zero Dependency
submission, no matter how the rest of the code is written.

Rather than throw the project away, this edition keeps the entire feature
set and rebuilds only the *delivery mechanism*: a plain `node:http` server
(Node's standard library) now serves the same UI to whatever browser the
user already has installed, and talks to the OS through the same
`node:child_process` / `node:fs` calls Electron's main process used
internally. The browser replaces Chromium-the-dependency with
browser-the-thing-you-already-own. Nothing here is a mock — every
filesystem operation, every spawned shell, every PowerShell query against
Windows actually runs.

## 2. Dependency Audit

| Original dependency | Type | Purpose | Disposition |
|---|---|---|---|
| `electron` (^31.7.7) | devDependency, used as the runtime via `electron .` | Bundled Chromium GUI shell + IPC bridge (`BrowserWindow`, `ipcMain`, `dialog`, `shell`, `session`) | **Removed.** Replaced with `node:http` + the user's own browser (§3). |
| `electron-builder` (^24.13.3) | devDependency | Packaged the app into an NSIS installer / portable `.exe` | **Removed.** Not needed — `node server.js` is the only run step; `scripts/build.js` is the only build step. |

Final `dependencies` and `devDependencies` in `package.json`: `{}` and `{}`.

## 3. Standard Library Mapping

| # | Normally used | Why | Standard-library replacement | How it works | Trade-off |
|---|---|---|---|---|---|
| 1 | `electron` (`BrowserWindow`) | Render a desktop GUI shell | `node:http` static file server (`server.js` → `serveStatic`) | Serves `public/index.html`/`styles.css`/`renderer.js` to any browser on `localhost` | User opens a browser tab instead of a native window; no window chrome/tray icon |
| 2 | `electron` (`ipcMain`/`ipcRenderer`/`contextBridge`) | Renderer ↔ main process messaging | Plain JSON HTTP endpoints under `/api/*` (`server.js` routing table) | `fetch()` in `public/api-client.js` calls the same method names (`window.mycli.files.list(...)`, etc.) the original preload script exposed | One HTTP round trip per call instead of an in-process IPC message; negligible on localhost |
| 3 | `electron` (`mainWindow.webContents.send`) | Push live events (terminal output, history updates) into the UI | Server-Sent Events over `node:http` (`lib/events.js`) | `/api/events` stays open; `EventSource` in the browser receives `terminal:data`, `history:added`, etc. | SSE is one-way (server→client), which is all the original push channel needed anyway |
| 4 | `electron` (`dialog.showOpenDialog`) | Native "choose a folder/file" dialog | `node:fs.readdir` exposed via `GET /api/browse`, rendered as an in-page picker modal (`public/api-client.js`) | Browses the real filesystem the server can see; same method signature (`window.mycli.dialog.openFolder()`) | Styled HTML modal instead of the OS-native dialog chrome |
| 5 | `electron` (`dialog.showSaveDialog`) | Native "save as" dialog for exporting history/activity | `Content-Disposition: attachment` header set by `node:http` (`server.js` → `downloadResponse`) | Browser's own download manager saves the file; no dialog needed at all | User doesn't pick a destination folder — file lands in the browser's default downloads location |
| 6 | `electron` (`shell.openPath`) | Open a file/folder with its default application | `node:child_process.spawn` of the OS's own opener (`cmd /c start`, `open`, `xdg-open`) — `lib/fsOps.js` → `openWithDefaultApp` | Spawns the platform's existing "open" command | None — same underlying OS mechanism Electron itself used |
| 7 | `electron` (`shell.trashItem`) | Move a deleted file to the Recycle Bin | `node:fs.rename` into an app-managed trash folder — `lib/fsOps.js` → `deleteEntry` | Deleted items move to `~/.mycli-data/trash/` instead of vanishing | **Real trade-off:** this is not the Windows Recycle Bin (that requires native shell32 COM bindings, unavailable from the standard library). Deleted files are still recoverable, just from a different folder — documented here rather than hidden. |
| 8 | `electron` (`app.getPath('userData')`) | Per-user writable data directory | `node:os.homedir()` + `node:path.join(...,'.mycli-data')` — `lib/store.js` | Same purpose, same guarantee (always writable, per-user) | None |
| 9 | `electron-builder` (NSIS/portable packaging) | Produce a distributable Windows installer | No packaging step — `node server.js` *is* the distributable | `scripts/build.js` does `node --check` on every source file and assembles a self-contained `dist/` copy | No signed `.exe`; the trade-off is explicit in README's Installation section |
| 10 | Would-be `express` (common alternative for the API layer) | Routing, JSON body parsing, static file serving | Hand-rolled router + `readBody`/`serveStatic` in `server.js`, built on `node:http`/`node:url` | A small array of `{method, pattern, handler}` matched against `req.method`/`url.pathname` | No middleware ecosystem, but the API surface here is small and fixed |
| 11 | Would-be `jest`/`mocha` | Test runner | `node:test` + `node:assert/strict` (`tests/*.test.js`) | Node's built-in test runner, invoked via `node --test tests/` | Slightly less tooling (no snapshot testing, fewer matchers) than Jest, but fully sufficient here |

That's 11 documented substitutions — see the STDLIB Log bonus in README.md.

## 4. Trade-offs

**Gained:** zero install step for the runtime (any machine with Node.js can
run it — no Electron download, no `npm install` of a 200+MB dependency
tree), a much smaller repository, and a server that's trivially inspectable
in a few hundred lines of plain JS.

**Lost:** a native window (no taskbar icon, no OS-level "always on top",
etc.), native OS dialogs (replaced with an in-page picker that looks the
same across platforms but isn't the OS's own widget), and true Recycle Bin
integration (see substitution #7). All of these are UI/desktop-integration
conveniences, not core functionality — every file operation, terminal
session, and Windows system query still works exactly as before.

## 5. Security

- **Command execution.** The terminal and installer/winget features spawn
  real shells and executables by design — that is the feature. `server.js`
  binds to `127.0.0.1` only, so the API is not reachable from the network by
  default; it is a *local* control center, not a multi-user service.
- **Path handling.** Every filesystem operation resolves through
  `fsOps.safePath`, and every created name is validated by `fsOps.assertName`
  to reject path separators, null bytes, and Windows-reserved characters —
  ported unchanged from the original Electron handlers.
- **Secret redaction.** `lib/store.js` redacts `password=`, `token=`,
  `secret=`, and similar patterns out of anything written to history or the
  activity log, same as the original.
- **No custom cryptography.** The only cryptographic primitive used is
  `node:crypto.randomUUID()` for generating IDs — a standard-library
  primitive, not a hand-rolled algorithm.
- **Threat model.** MyCLI assumes the person running it is the same person
  sitting at the keyboard, on their own machine, and trusts the commands
  they type into its terminal. It does not attempt to sandbox commands,
  authenticate requests, or protect against a malicious actor who already
  has local network access to `127.0.0.1` while the server is running.
- **Limitations.** There is no encryption at rest for `~/.mycli-data/`
  (history/activity/settings are plain JSON, matching the original app's
  plain-JSON `userData` files). There is no authentication on the local API —
  anyone who can reach `127.0.0.1:4173` while it's running can use it, same
  trust boundary the original desktop app had (anyone at the keyboard).

## 6. Build Environment

- **Runtime dependencies:** none (`dependencies: {}` in `package.json`).
- **Development-only tools:** none (`devDependencies: {}`); `node --test` and
  `node --check` are both built into the Node.js binary itself.
- **Build tools:** `scripts/build.js`, which itself only uses `node:fs`,
  `node:path`, `node:crypto`, and `node:child_process` (to shell out to
  `node --check`).
- **Standard-library components used across the project:** `http`, `fs`,
  `path`, `url`, `os`, `crypto`, `child_process`, `assert`, `test`.

The final runtime — everything under `server.js`, `lib/`, and `public/` — has
**zero third-party packages**, confirmed by `npm ls` returning nothing and by
`package.json` shipping empty `dependencies`/`devDependencies` objects.
