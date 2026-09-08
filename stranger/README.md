# stranger

[![ci](https://github.com/AnishPrakash/stranger/actions/workflows/ci.yml/badge.svg)](https://github.com/AnishPrakash/stranger/actions/workflows/ci.yml)
[![dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](deps-proof.txt)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**An offline supply-chain auditor for dependency lockfiles. It has no
dependencies.**

> *"Every dependency is a stranger. This time, invite none."*

**[▶ Watch the 5-minute demo](https://youtu.be/T9Px18FKZ68)** — the tool working
on real lockfiles, and the manifest being empty.

Zero Dependency Hackathon 2026 · **Track A — Developer Tools & CLI** · Rust,
standard library only, one source file.

---

## What it does

Point it at a lockfile you already have. It reconstructs the full transitive
dependency graph and tells you what is actually in there:

```
$ stranger audit package-lock.json

  stranger 1.0.0 · package-lock.json · npm · lockfileVersion 3

        665  packages in the tree
         22  you chose
        643  arrived with them

  #######################################. 97% of your tree is code nobody chose

  max depth 9  ·  1 run install scripts  ·  32 duplicated  ·  8 cycles
```

Then it reports the things worth looking at — names that sit one keystroke from
something popular, entries that execute code during `npm install`, packages that
resolve to a git branch instead of the registry, dependencies carried with no
integrity hash — each with the chain that explains **why it is in your tree**:

```
   CRITICAL  `expres` runs code during install
             Lifecycle hooks present: postinstall. These execute on `install`,
             before anyone reads the code, with the permissions of whoever ran
             the command — including CI. This package ALSO has a name
             resembling a popular one. That combination is the shape of a live
             attack, not a coincidence.
             [install-script]

     HIGH    `cha1k` is visually confusable with `chalk`
             After folding lookalike glyphs (0/o, 1/l, rn/m) and separators,
             both names reduce to `chalk`. That is not a typo pattern — it is
             a deliberate one. If you meant `chalk`, this is not it.
             why: report-builder@1.0.0 -> cha1k@5.3.0
             [confusable-name]
```

**It never touches the network.** There is no registry to be down, no API key,
no rate limit, and nothing to leak. The lockfile is the entire input.

---

## Quick start

```bash
make            # one command, produces ./stranger
./stranger audit package-lock.json
```

Requires `rustc` (1.85+). Nothing else — no `cargo build` needed, no crates
fetched, no network. `make` runs a single `rustc` invocation on a single file.

**Windows without `make`:**

```powershell
rustc -O -o stranger.exe src/main.rs
```

That builds and runs fine. For the *reproducible* build specifically, MSVC
needs two extra linker flags — and under Git Bash you need `MSYS_NO_PATHCONV=1`
in front, or MSYS rewrites `/Brepro` into a filesystem path and `link.exe`
fails with `LNK1181`:

```bash
MSYS_NO_PATHCONV=1 rustc -O -C codegen-units=1 -C debuginfo=0 \
  -C strip=symbols -C metadata=stranger-1.0.0 \
  -C link-arg=/Brepro -C link-arg=/DEBUG:NONE -o stranger.exe src/main.rs
```

The Makefile handles all of this for you — it exports the MSYS guard and picks
the flags from `rustc -vV`. `make info` shows what it will do on your machine.

```bash
make test       # 58 tests, std harness, no test crate
make repro      # build twice, prove the bytes are identical
make demo       # the guided tour
```

---

## The three commands

### `audit` — what is in this lockfile

```bash
stranger audit package-lock.json
stranger audit Cargo.lock --fail-on medium
stranger audit requirements.txt --json | jq '.summary'
cat package-lock.json | stranger audit - --as npm
```

### `diff` — what did that install actually add

This is the one I wanted to exist. `npm install one-thing` says it added 47
packages and does not say which; the lockfile diff in your pull request is four
thousand lines of reordered JSON. This answers the question the diff is hiding:

```bash
$ stranger diff before/package-lock.json after/package-lock.json

  6 packages -> 20 packages   +14

  NEW (13 packages never seen before)
    + cha1k@5.3.0
    + expres@4.18.2
    + node-ipc@9.2.1
    ...

  CHANGED (1 version changes)
    ~ qs 6.11.0 -> 6.5.2

  NEW FINDINGS (13)
   CRITICAL  `cha1k` runs code during install
   CRITICAL  `expres` runs code during install
```

Rules run against the new tree, and only findings about **packages this change
introduced** are shown. The review question is not "is my tree clean" — it is
"did this pull request make it worse".

### `why` — who pulled this in

```bash
$ stranger why package-lock.json fsevents

  fsevents · 1 instance(s)

  fsevents@2.3.3  depth 3 · dev
    nodemon@3.1.14
      -> chokidar@3.6.0
      -> fsevents@2.3.3
    install scripts: hasInstallScript
    from: https://registry.npmjs.org/fsevents/-/fsevents-2.3.3.tgz
```

If the package is not there, it offers the near-misses — which for this tool is
the interesting answer anyway.

---

## Supported inputs

| File | Ecosystem | Transitive graph? |
| --- | --- | --- |
| `package-lock.json` (v1, v2, v3) | npm | Yes — full, via Node's own resolution |
| `npm-shrinkwrap.json` | npm | Yes |
| `Cargo.lock` (v3, v4) | crates.io | Yes |
| `requirements.txt` | PyPI | **No** — declared requirements only |
| `-` (stdin) | any, with `--as` | as above |

Format is detected from the filename, then from content, then from `--as`.

---

## The rules

Nine, all answerable from the lockfile alone.

| Rule | Severity | What it means |
| --- | --- | --- |
| `install-script` | Medium → **Critical** | Runs `preinstall`/`install`/`postinstall`. Escalates to Critical if the name also resembles a popular package — that combination is the attack, not two observations. |
| `confusable-name` | High | Folds to the same skeleton as a popular name after `0`→`o`, `1`→`l`, `rn`→`m`. Deliberate, not a typo. |
| `typosquat-candidate` | High / Medium / Info | Within 1–2 Damerau edits of a widely-installed name. Demoted to Info when many packages depend on it (see below). |
| `off-registry-source` | High | Resolves to a git ref, a local path, or a non-default host. Registry provenance does not apply. |
| `direct-url-requirement` | High | A pip requirement installed straight from a URL. |
| `no-integrity` | Medium | Version pinned, but nothing to verify the bytes against. |
| `unpinned` / `unpinned-range` | Medium / Low | A pip requirement with no constraint, or a range. |
| `trivial-package` | Low | A one-liner carried as a dependency, with the stdlib equivalent named. |
| `duplicate-versions` | Low | Installed at more than one version — one finding, not thirty. |
| `deep-transitive` | Info | Six or more levels down. Nobody chose it, nobody reviews it. |
| `unreachable-entry` | Low | In the lockfile but not reachable from any root. |

### How the typosquat rule avoids being useless

The first version of this rule ran against a real 665-package tree and reported
`etag` as a near-miss for `tar`, `depd` for `del`, and `exit` for `next`. All
true at edit distance 2. All worthless. A rule that cries wolf on express's own
dependencies is a rule people turn off, and a disabled rule catches nothing.

Three gates fixed it:

1. **Distance relative to length.** Two edits on a four-character name is half
   the string. `d=1` requires ≥ 5 characters, `d=2` requires ≥ 8.
2. **In-degree as a popularity proxy.** A name many packages independently
   depend on is established, not squatted. It is the only popularity signal
   available without a network, and it is a good one: a real squat is pulled in
   by one mistaken import, while `safer-buffer` is pulled in by half the
   registry. High in-degree demotes a finding to Info rather than deleting it —
   the evidence is weaker, not absent.
3. **Compare like with like.** `@jest/core` is not a near-miss for
   `@types/node` just because `core` and `node` are two edits apart.

On that same 665-package tree the tool now reports **zero** high-severity
findings, which is the correct answer for an ordinary, uncompromised project.

---

## Limits

An auditor that overstates what it knows is worse than no auditor, so:

- **It cannot tell you a package was compromised.** There is no CVE feed and no
  advisory database, because both need a network. `stranger` reports *shape*:
  attack surface, provenance gaps, and names worth a second look. Every incident
  in the last decade — `left-pad`, `xz`, `chalk`/`debug`, Shai-Hulud, ChainDrop
  — was legitimate right up until it was not. Run `npm audit` too. They answer
  different questions.
- **The corpus is hand-maintained and will go stale.** ~450 npm, ~180 PyPI and
  ~150 crates.io names compiled into the binary. Use `--corpus <file>` to
  supply your own; the report always states how many names it compared against.
- **`requirements.txt` has no transitive information.** It reports what you
  declared, not what pip installs. The tool says so in its own output rather
  than letting you assume otherwise.
- **`lockfileVersion 1` merges duplicate nested versions by name.** v1 records
  `requires` without install paths, so the resolution that v2/v3 supports is not
  reconstructable. Disclosed in the output when it happens.
- **The TOML reader is a Cargo.lock subset, not a TOML implementation.** It
  refuses constructs it does not implement rather than guessing at them.
- **The report is a fixed 78 columns.** Terminal width detection needs an
  `unsafe` ioctl or an external `stty`; the file is `#![forbid(unsafe_code)]`
  and shelling out is a hidden dependency. So it does not adapt.
- **Typosquat findings are prompts, not verdicts.** The output says so in every
  one of them.

---

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | No findings at or above the `--fail-on` threshold |
| `1` | Findings at or above the threshold (default: `high`) |
| `2` | Input could not be read or parsed |

Which makes it a CI gate:

```yaml
- run: stranger audit package-lock.json --fail-on high
```

---

## Zero-dependency proof

```
$ cargo tree
stranger v1.0.0 (/stranger)
```

That is the entire tree. `Cargo.toml` has an empty `[dependencies]` **and** an
empty `[dev-dependencies]`; `Cargo.lock` contains one `[[package]]` block and it
is this program. Full evidence in [`deps-proof.txt`](deps-proof.txt), regenerable
with `make deps-proof`.

The tool audits itself as part of that proof — `stranger audit Cargo.lock`
reports one package and nothing else.

Every substitution is documented in **[STDLIB.md](STDLIB.md)**, including the
places the crate would have been better.

### Reproducibility

```
$ make repro
target:  x86_64-unknown-linux-gnu
build 1: 2a6d1023d86dafeda89ed204c4b20d88471dee7148f5e51364ef464e12d5484e
build 2: 2a6d1023d86dafeda89ed204c4b20d88471dee7148f5e51364ef464e12d5484e
REPRODUCIBLE: byte-identical
```

Reproducibility is per-target — "byte-identical" always means the same
toolchain building for the same target — so `make info` prints what your
machine will do, and `make repro` prints the target alongside the hashes.
Verified on two:

| Target | Extra linker flags needed | Proof |
| --- | --- | --- |
| `x86_64-unknown-linux-gnu` | none — ELF carries no link timestamp | [`deps-proof.txt`](deps-proof.txt) + CI |
| `x86_64-pc-windows-msvc` | `/Brepro` and `/DEBUG:NONE` | [`deps-proof-windows-msvc.txt`](deps-proof-windows-msvc.txt) |

Two files rather than one, because `make deps-proof` regenerates its output on
whichever host runs it — a Windows section appended to it would be silently
overwritten by the next Linux run. `bash tools/repro-windows.sh` regenerates
the Windows one.

The Windows case is worth spelling out, because it took two attempts. MSVC
embeds two per-link nondeterministic values in the PE image. `/Brepro`
replaces the COFF `TimeDateStamp` with a hash of the file contents — but the
CodeView debug directory carries a PDB GUID that is regenerated on every link,
and `/Brepro` folds that random GUID into its hash. So the "deterministic"
timestamp varied anyway, and two builds differed by 69 bytes across three
sites. `/DEBUG:NONE` drops the debug directory, and both settle. The Makefile
detects the host and applies the right flag; you do not have to know any of
this to run `make repro`.

CI runs `make repro` on `ubuntu-latest` every push, so the published proof is
a clean-runner build rather than a hash I pasted from my own machine.

### Bonus challenges

| Challenge | Status |
| --- | --- |
| **Single File** (+5) | `src/main.rs`, 4,357 lines, inline `mod` blocks. `rustc -O src/main.rs` builds it. No `src/` tree, no modules on disk. |
| **Reproducible Build** (+5) | `make repro` builds twice and compares. Verified byte-identical on **`x86_64-unknown-linux-gnu`** and **`x86_64-pc-windows-msvc`** — see [Reproducibility](#reproducibility) and [`deps-proof.txt`](deps-proof.txt). |
| **Package Killer** (+3) | `serde_json` (and the `serde`/`syn`/`quote`/`proc-macro2` subtree behind it), replaced by a full RFC 8259 parser tested against a JSONTestSuite-style must-reject corpus. |
| **STDLIB Log** (+3) | 15 substitutions in [STDLIB.md](STDLIB.md), each with what it cost. |

---

## Layout

One file, ten sections, top to bottom:

| § | Module | Replaces |
| --- | --- | --- |
| 1 | `json` — RFC 8259 parser + serializer | `serde_json`, `serde` |
| 2 | `toml` — Cargo.lock array-of-tables reader | `toml` |
| 3 | `pep508` — requirements.txt reader | `packaging` |
| 4 | `dist` — bounded Damerau-Levenshtein | `strsim` |
| 5 | `corpus` — embedded name lists | a registry API call |
| 6 | `graph` — closure, depths, blame, cycles | `petgraph` |
| 7 | `rules` — the nine offline checks | — |
| 8 | `render` — ANSI, TTY detection, wrapping | `colored`, `textwrap`, `comfy-table` |
| 9 | `cli` — argument parsing | `clap` |
| 10 | `tests` — 58 tests | a test framework |

```
stranger/
├── README.md              this file
├── STDLIB.md              every substitution, and what it cost
├── Makefile               `make` -> ./stranger, one rustc call
├── Cargo.toml             [dependencies] is empty
├── Cargo.lock             one [[package]] block: this program
├── deps-proof.txt         cargo tree output + reproducible-build hashes
├── .zero-dep.toml         track letter and pitch
├── src/main.rs            the whole program
└── examples/
    ├── clean-lock.json         an ordinary tree
    └── compromised-lock.json   the same tree, one bad install later
```

---

## Why Track A

It is a developer tool with a CLI: flags, exit codes, stdin, `NO_COLOR`, and a
`--json` mode for CI. But the reason it belongs at *this* event is narrower.

The hackathon's premise is that the dependency tree is the attack surface and
that AI-generated code makes it worse — 19.7% of packages suggested by models do
not exist, and attackers register the names the models reliably invent. The
honest response to that is not only "add no packages", it is "be able to see
what you already added". `stranger` is the second half, and it would be absurd
for it to have dependencies of its own.

It is also the rare case where the constraint improved the product rather than
taxing it. Being unable to call a registry forced in-degree as a popularity
proxy, which turned out to be a better signal than download counts for this
purpose — a squat has a download count too, but it does not have thirty
independent packages depending on it.

---

## License

MIT. See [LICENSE](LICENSE).
