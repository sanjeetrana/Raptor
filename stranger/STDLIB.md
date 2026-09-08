# STDLIB.md

Every third-party crate `stranger` would normally have installed, what replaced
it, and what that trade actually cost.

The rule for this file, self-imposed: no entry unless I can say what the crate
does better. A list of substitutions where the standard library wins every time
is a list I wrote wrong.

**Runtime dependencies: 0. Dev dependencies: 0. Build dependencies: 0.**

```
$ cargo tree
stranger v1.0.0 (/stranger)
```

That is the whole tree. `Cargo.lock` contains one `[[package]]` block, and it is
this program.

---

## The headline: `serde` + `serde_json`

**Package Killer submission.** `serde_json` is one of the most-installed crates
on crates.io; virtually every Rust program that touches a config file, an API,
or a lockfile pulls it in.

**What it costs you.** `serde_json` with the `derive` feature does not arrive
alone. It brings `serde`, `serde_derive`, `syn`, `quote`, `proc-macro2` and
`itoa`/`ryu` — six crates, two of which (`syn`, `proc-macro2`) are procedural
macros that execute arbitrary code in your build. To read a text file.

**Replaced by:** `mod json` — 420 lines implementing RFC 8259 in full, plus a
serializer.

**Where it lives:** `src/main.rs`, section 1.

**What I had to get right that the crate gets right for free:**

| RFC requirement | Why a naive parser gets it wrong |
| --- | --- |
| Surrogate pairs | `"😀"` is one emoji, not two chars. A lone `\ud800` must be an error, not U+FFFD. |
| Control characters | A raw `\n` inside a string is invalid JSON. Accepting it means accepting input other parsers reject. |
| Number grammar | `01` is not a number, `.5` is not a number, `1.` is not a number, `+1` is not a number. Leading zeros in particular are how an octal reading gets smuggled past a lenient reader. |
| Trailing commas | `{"a":1,}` is invalid. Every hand-rolled parser I have read accepts it by accident. |
| Depth limiting | A file of 100,000 `[` is not a lockfile. Without a cap, a recursive-descent parser meets it with a stack overflow. |
| UTF-8 validation | Iterating bytes means multi-byte sequences arrive one byte at a time; a truncated sequence has to be rejected, not concatenated. |

Verified against a 30-case must-reject corpus modelled on JSONTestSuite
(`json_rejects_invalid_documents`) and a 15-case must-accept corpus. It parses a
330 KB, 666-package real `package-lock.json` correctly.

**Honest cost:** `serde_json` is faster. It has a SIMD-adjacent scanner and years
of profiling behind it; this is a straightforward byte loop with two rolling
buffers. On the 330 KB lockfile the difference is not measurable at human scale
(the whole audit runs in ~20 ms), but on a 50 MB document it would be. It also
has no `Deserialize` derive — every field access here is an explicit
`get("version").and_then(as_str)`, which is more code at every call site. I would
still use `serde_json` in production. That is not the same as needing it here.

---

## The rest

### 1. `toml` → `mod toml`

**Would have installed:** `toml` (which pulls `serde`, `toml_edit`, `winnow`,
`indexmap`, `hashbrown`).

**Replaced with:** a reader for the Cargo.lock dialect — top-level key/value
pairs, `[[array of tables]]`, basic and literal strings, integers, string arrays
including the multi-line form Cargo emits.

**The honest part, and the reason this entry exists:** this is *not* a TOML
implementation. No inline tables, no dotted keys, no datetimes, no floats, no
multi-line strings. Cargo.lock is machine-generated with a fixed shape, so the
subset is safe — and where it ends, the parser returns
`"inline tables are outside the Cargo.lock subset this reader implements"`
rather than guessing. A parser that silently mis-reads input it does not
understand is worse than one that refuses it, and that refusal is tested
(`toml_rejects_constructs_outside_the_subset_instead_of_guessing`).

Two details that are easy to get wrong and are tested: `#` inside a string is
not a comment (`checksum = "ab#cd"`), and a literal `'...'` string processes no
escapes at all (Windows paths).

---

### 2. `packaging` / `pip-requirements-parser` → `mod pep508`

**Would have installed:** in Rust there is no direct equivalent, which is
itself informative — the Python-side answer is `packaging`, and the usual Rust
move is to shell out to `pip`, which the hackathon rules correctly call a hidden
dependency.

**Replaced with:** a `requirements.txt` reader handling backslash continuations,
`--hash=` tokens scattered across folded lines, environment markers after `;`,
extras in `[...]`, direct URL references via ` @ `, pip flags (`-r`, `-c`, `-e`,
`--index-url`), and PEP 503 name normalisation.

**Why it needed care:** the pin/range distinction drives a finding. Reporting
`django==4.2.*` as "pinned" would be wrong (it is a range), and reporting
`requests==2.31.0` as unpinned would be noise. `is_pinned()` is four lines and
two of them are about the wildcard case.

Also: pip treats `#` as a comment only at line start or after whitespace, so
`https://x/y.whl#egg=pkg` keeps its fragment. Tested.

---

### 3. `strsim` → `mod dist`

**Would have installed:** `strsim`.

**Replaced with:** Damerau-Levenshtein (OSA), bounded, with early exit.

**Why not plain Levenshtein:** the most common human typo is a transposition —
`axois`, `lodahs`, `python-dotnev`. Levenshtein charges 2 for a swap, the same
as two unrelated edits, which puts real squats outside a distance-1 ball and
lets noise in. Damerau charges 1. That single difference is what makes the rule
usable.

**Two things the crate would not have given me:**

- **Bounded early exit.** Every package name is compared against ~450 corpus
  names. The full O(mn) matrix is waste when the answer is only ever
  "is this ≤ 2?". Bailing out as soon as a whole row exceeds the budget turns
  most comparisons into a few dozen operations. 665 packages × 454 names
  completes in single-digit milliseconds.
- **Confusable-glyph folding** (`skeleton()`), which no distance crate does:
  `0`→`o`, `1`→`l`, `rn`→`m`, separators stripped. `cha1k` and `chalk` are
  distance 1 — indistinguishable from an innocent typo — but their skeletons are
  *equal*, which is a categorically stronger signal and gets its own rule and
  its own severity.

**Honest cost:** OSA is not true Damerau-Levenshtein; it does not allow edits
between transposed characters. For package names, which are short, the
difference does not arise.

---

### 4. `clap` → `parse_args`

**Would have installed:** `clap` + `clap_derive`, and behind them `syn`,
`quote`, `proc-macro2`, `strsim`, `anstyle`, `anstream`, `colorchoice`,
`is_terminal_polyfill`, `utf8parse`, `terminal_size`. A double-digit subtree to
turn `Vec<String>` into a struct.

**Replaced with:** ~80 lines over `std::env::args()`.

**What I kept, because these are the conventions clap actually sells:**
`--flag=value` and `--flag value` both work; `--` ends option parsing so a file
named `--weird.json` is reachable; short flags cluster (`-qj`); unknown flags
are an error, not a silent ignore; a missing flag value is an error, not a panic.
All five are tested.

**Honest cost:** no generated shell completions, no `--help` that stays in sync
automatically (`HELP` is a `const &str` I have to remember to edit), no
suggestion on a misspelled flag. For a five-flag tool that is the right trade;
at twenty flags it would not be.

---

### 5. `colored` / `owo-colors` → `mod render::Style`

**Would have installed:** `colored` or `owo-colors`.

**Replaced with:** `\x1b[{code}m…\x1b[0m`.

**The actual content of this dependency:** not the escape codes — those have
been stable since 1979 and are four characters. What `chalk` earns 319 million
weekly downloads for, and what `colored` provides here, is answering *when* to
emit them. Writing colour into a pipe corrupts every downstream `grep`.

The policy, implemented in `color_enabled()`: an explicit `--color always|never`
wins; then `NO_COLOR` (any value, per no-color.org); then
`std::io::stdout().is_terminal()`. Three branches, and it is the whole product.

---

### 6. `is-terminal` / `atty` → `std::io::IsTerminal`

**Would have installed:** `atty` (unmaintained, and had an unsoundness
advisory) or `is-terminal`.

**Replaced with:** `std::io::IsTerminal`, stable since Rust 1.70.

This one is pure win and worth flagging as such: the crate exists only because
the std trait did not, and thousands of dependency trees still carry it out of
habit. Nothing was lost.

---

### 7. `comfy-table` / `tabled` → fixed-width layout

**Would have installed:** `comfy-table` (pulls `unicode-width`,
`strum`, `crossterm`).

**Replaced with:** `format!("{:>9}")` and a 78-column budget.

**Honest cost, and it is real:** the report does not adapt to terminal width. I
did not implement `TIOCGWINSZ`, because doing it portably means either an
`unsafe` `ioctl` (the file is `#![forbid(unsafe_code)]`) or spawning `stty`
(a hidden dependency on an external binary, explicitly out of scope). 78 columns
fits every terminal ≥ 80 wide, which is all of them; on a very wide terminal the
report simply does not use the extra space. That is a visible limitation, not a
solved problem.

---

### 8. `textwrap` → `render::wrap_text`

**Would have installed:** `textwrap` (pulls `unicode-width`,
`unicode-linebreak`, `smawk`).

**Replaced with:** a greedy word-wrap with hanging indent — a while loop over
`split_whitespace()` with a running column count.

**Honest cost:** greedy, not Knuth-Plass, so line breaks are less even than
`textwrap`'s optimal-fit. It also counts `chars()`, not display width, so
double-width CJK characters in a package name would overflow the column. Package
names are ASCII in practice; if that stopped being true this would need
`unicode-width`'s tables, which are data, not logic — and I would write them out
rather than import them. Tested to never exceed the requested width for ASCII.

---

### 9. `petgraph` → `mod graph`

**Would have installed:** `petgraph` (pulls `indexmap`, `fixedbitset`,
`hashbrown`).

**Replaced with:** adjacency lists as `Vec<usize>`, BFS for depths and blame
paths, and an **iterative** three-colour DFS for cycle detection.

**Why iterative matters:** a recursive DFS over a hostile lockfile is a stack
overflow with extra steps. The same reasoning as the JSON depth cap: this program
reads files that an attacker may have written.

The npm-specific part is not something `petgraph` would have helped with anyway:
turning a lockfile's `dependencies: {name: range}` into edges means reproducing
Node's own resolution — from the depending package's install directory, try
`<dir>/node_modules/<name>`, then strip a path segment and try again, up to the
root. Get it wrong and two different versions of one package fuse into a single
node, which makes every "why is this here" chain a lie. Tested against a fixture
with a hoisted and a nested copy of the same package
(`npm_resolution_walks_up_from_the_nested_directory_first`).

---

### 10. `anyhow` / `thiserror` → `Result<T, String>` + `impl Display`

**Would have installed:** `anyhow`, or `thiserror` (which is a proc macro:
`syn`, `quote`, `proc-macro2`).

**Replaced with:** `Result<T, String>` at the command layer, and typed error
structs (`json::Error`, `toml::Error`) with hand-written `Display` where position
information matters.

**Honest cost:** no backtraces, no error chaining, no `?`-across-error-types
without a `map_err`. There are ~20 `map_err(|e| format!(...))` calls that
`anyhow` would have erased. For a CLI whose errors all terminate in the same
`eprintln!`, allocating a `String` at the boundary is not a real cost — in a
library it would be.

---

### 11. `once_cell` / `lazy_static` → `const` arrays

**Would have installed:** `once_cell` or `lazy_static` for the corpus tables.

**Replaced with:** `&'static [&'static str]` consts. No lazy initialisation
needed — they are compile-time data that lives in `.rodata`.

Worth noting because this is the substitution people forget exists:
`LazyLock`/`LazyCell` have been in std since 1.80 and `once_cell` is still
installed out of habit. Here even that was unnecessary.

---

### 12. `indexmap` → `BTreeMap`

**Would have installed:** `indexmap`, for insertion-ordered maps.

**Replaced with:** `BTreeMap`, which gives *sorted* order rather than insertion
order.

**Why the swap is an improvement, not a compromise:** `--json` output gets
diffed in CI. Sorted keys mean identical input produces byte-identical output —
which is the same discipline as the reproducible build, applied to the report.
Insertion order would have been stable too, but sorted order is stable *and*
canonical across lockfiles that list packages in different orders. Tested
(`json_report_is_stable_across_runs`, `json_object_keys_are_sorted…`).

---

### 13. `rustc-hash` / `ahash` → `std::collections::HashMap`

**Would have installed:** a faster hasher.

**Replaced with:** std's SipHash-1-3 `HashMap`.

**Honest note:** SipHash is measurably slower than FxHash for short string keys,
and this program hashes a lot of short string keys. It is also DoS-resistant,
and this program's input is a file that may be hostile. For a 666-package
lockfile the whole audit is ~20 ms; the hasher is not the bottleneck, and the
resistance is worth more than the microseconds.

---

### 14. A registry API call → an embedded corpus

**Would have needed:** the npm/PyPI download-counts API, or a crate vendoring a
popular-names list.

**Replaced with:** `mod corpus` — ~450 npm, ~180 PyPI and ~150 crates.io names,
plus 52 known-trivial packages and their standard-library one-liners, compiled
into the binary as `&[&str]`.

This is the substitution I am least comfortable with and most glad I was forced
into. Uncomfortable because a hand-maintained list goes stale, and the tool is
only as good as it; glad because the alternative — an auditor that phones a
registry to tell you your registry is dangerous — has a credibility problem, and
because the hackathon rules put network-dependent projects out of scope for
good reason. `--corpus <file>` lets you supply your own list, and the report
states how many names it compared against so the number is never implicit.

To be clear about the rules: this is data I typed, not code I imported. Nothing
in `src/` was copied from a library.

---

### 15. `num-format` / `thousands` → `commas()`

**Would have installed:** `num-format` (pulls `arrayvec`, `itoa`,
`lazy_static`).

**Replaced with:** nine lines — walk the digits, insert a comma where
`(len - i) % 3 == 0`.

**Honest cost:** locale-blind. It emits `1,247` for everyone, including locales
that write `1.247` or `1 247`. `num-format` carries CLDR tables for that. For a
developer CLI whose entire UI is English, hard-coding the Anglo grouping is a
defensible call — and pretending otherwise by importing a locale crate I would
then only ever use in one locale would be worse.

---

## Substitutions I considered and rejected

Listing these because "what I chose not to replace" is part of an honest
accounting.

- **`regex`.** Never needed one. Every piece of parsing here is a character
  scanner, which is faster and gives position information for free. If I had
  reached for a regex it would have been a sign the parser was wrong.
- **`semver`.** `stranger` compares version *strings* for equality (duplicate
  detection) and never orders them. Implementing semver precedence — with
  pre-release and build-metadata rules — to support a feature I do not have
  would have been the stunt the rules warn about.
- **`walkdir`.** The tool takes a file path, not a directory. Recursive
  discovery would be feature creep.
- **`criterion`.** Benchmarks would have been nice. `criterion` is a
  dev-dependency and the rules permit test tooling — but Rust ships `#[test]`,
  so the grey-area exemption does not apply to me and I did not take it.

---

## An aside: what determinism cost

Not a substitution, but it belongs in an honest accounting, because the
Reproducible Build claim is the one thing here a judge can falsify in one
command — and on the first attempt, they could have.

`make repro` passed on Linux immediately. ELF carries no link timestamp, and
with `codegen-units=1` and stripped symbols the two builds matched on the first
try. That made it tempting to write "verified byte-identical" and move on.

Running the same check on Windows produced `DIFFER` at byte 249 — the COFF
`TimeDateStamp`. The obvious fix is `/Brepro`, which tells the MSVC linker to
derive that field from a hash of the file contents instead of the clock. It
did not help: the two builds still differed, by 69 bytes across three sites,
and the differing values were not clock-shaped.

The reason is a second source of entropy stacked behind the first. MSVC also
emits a CodeView debug directory containing a PDB GUID, regenerated on every
link — and `/Brepro` hashes the whole file, GUID included. The deterministic
timestamp was faithfully reflecting a random input. `/DEBUG:NONE` removes the
debug directory, and with both flags the builds are identical.

Two things worth taking from that:

- **Reproducibility is per-target, and a claim that does not name its target is
  not a claim.** `make info` now prints the host and the flags it will apply;
  `make repro` prints the target next to the hashes.
- **A deterministic-looking mechanism can launder a nondeterministic input.**
  `/Brepro` was working exactly as documented the entire time. That is a
  general shape worth recognising, and it is the same shape as a lockfile with
  an integrity hash over a tarball that was republished — the hash is honest
  about content that was never pinned.

There was a third layer underneath, found only by running the fixed command on
a real Windows shell: under Git Bash, MSYS rewrites any argument that looks
like a Unix path, so `-C link-arg=/Brepro` reached `link.exe` as
`C:/Program Files/Git/Brepro` and it died with `LNK1181` hunting for
`Brepro.obj`. The flag was correct; the shell edited it in transit. The
Makefile now exports `MSYS_NO_PATHCONV` so nobody else has to discover that.

Cost: about forty minutes and two extra linker flags. No dependency involved
either way, which is the point — this is the kind of thing a build tool would
normally have handled invisibly, and doing it by hand is how you find out that
"invisibly" was doing real work.

---

## What "zero dependency" cost, totalled

Roughly 1,400 of the 3,600 lines in `src/main.rs` are things a crate would have
provided. That is the price, and it bought three things I would not otherwise
have:

1. **Error positions everywhere**, because I am holding the cursor. `serde_json`
   gives line/column too; the TOML and requirements readers give it because I
   wrote them, and an off-the-shelf `toml` crate would not have given me the
   subset-boundary message at all.
2. **A bounded distance function**, which is a ~50× reduction in comparison work
   over calling `strsim::damerau_levenshtein` in a loop, and which no crate
   exposes because it is a weird thing to want.
3. **A binary with nothing in it but this program.** For a supply-chain auditor
   that is not a gimmick — it is the only version of this tool whose own
   provenance you do not have to take on faith.

The last one is the argument. Everything else here is a trade I would reverse in
a different context.
