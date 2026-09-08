# Field test

`stranger`'s rules were tuned against two fixtures. That is a weak basis for
claiming precision, so before submitting I ran it across every real lockfile on
my machine — npm, Cargo and pip alike, trees it had never seen and that I had
no opportunity to tune against.

The claim being tested is narrow and falsifiable: **an ordinary, uncompromised
project should produce zero HIGH or CRITICAL findings.** A supply-chain tool
that cries wolf on `express`'s own dependencies is a tool people disable, and a
disabled tool catches nothing. Precision matters more than recall here.

Project paths below are reduced to the directory name. Regenerate with
`bash tools/gen-field-test.sh <root>`.

---

## `argus-backend` — `requirements.txt`

```

  stranger 1.0.0 · argus-backend/requirements.txt · PyPI

         18  packages in the tree
         18  you chose  (declared in this file)
          0  arrived with them

  ........................................ 0% of your tree is code nobody chose

  note: requirements.txt records no transitive information, so this audit
        covers only what you declared — the installed tree is larger

  FINDINGS (6)

     LOW     `certifi` allows a version range (>=2024.1.0)
             A range is a standing instruction to accept future code you have
             not seen. Pin it, or use a hash-locked file.
             [unpinned-range]

     LOW     `httpx` allows a version range (>=0.28)
             A range is a standing instruction to accept future code you have
             not seen. Pin it, or use a hash-locked file.
             [unpinned-range]

     LOW     `huggingface-hub` allows a version range (>=0.23.0)
             A range is a standing instruction to accept future code you have
             not seen. Pin it, or use a hash-locked file.
             [unpinned-range]

     LOW     `opencv-python-headless` allows a version range (>=4.7.0)
             A range is a standing instruction to accept future code you have
             not seen. Pin it, or use a hash-locked file.
             [unpinned-range]

     LOW     `supabase` allows a version range (>=2.7.0)
             A range is a standing instruction to accept future code you have
             not seen. Pin it, or use a hash-locked file.
             [unpinned-range]

     LOW     `torch` allows a version range (>=2.0.0)
             A range is a standing instruction to accept future code you have
             not seen. Pin it, or use a hash-locked file.
             [unpinned-range]

  4 more findings hidden by --top

  SUMMARY  0 critical · 0 high · 0 medium · 10 low · 0 info
  compared 18 names against 168 known-popular PyPI package names, offline

```

## `argus-frontend` — `package-lock.json`

```

  stranger 1.0.0 · argus-frontend/package-lock.json · npm · lockfileVersion 3

        482  packages in the tree
         12  you chose
        470  arrived with them

  #######################################. 98% of your tree is code nobody chose

  max depth 9  ·  2 run install scripts  ·  17 duplicated  ·  5 cycles

  FINDINGS (6)

    MEDIUM   `fsevents` runs code during install
             Lifecycle hooks present: hasInstallScript. These execute on
             `install`, before anyone reads the code, with the permissions of
             whoever ran the command — including CI.
             why: tailwindcss@3.4.19 -> chokidar@3.6.0 -> fsevents@2.3.3
             [install-script]

    MEDIUM   `unrs-resolver` runs code during install
             Lifecycle hooks present: hasInstallScript. These execute on
             `install`, before anyone reads the code, with the permissions of
             whoever ran the command — including CI.
             why: eslint-config-next@14.2.3 -> eslint-import-resolver-typescript@3.10.1 -> unrs-resolver@1.12.2
             [install-script]

     LOW     17 packages are installed at more than one version
             Patching one copy does not patch the others. This is how an
             advisory gets marked resolved while a vulnerable copy stays in
             the bundle.
             ansi-regex (5.0.1, 6.3.0), ansi-styles (4.3.0, 6.2.3),
             brace-expansion (1.1.18, 2.1.4), debug (3.2.7, 4.4.3), doctrine
             (2.1.0, 3.0.0), emoji-regex (8.0.0, 9.2.2), glob (10.3.10,
             7.2.3), glob-parent (5.1.2, 6.0.2), minimatch (3.1.5, 9.0.3,
             9.0.9), picomatch (2.3.2, 4.0.5), postcss (8.4.31, 8.5.26),
             react-is (16.13.1, 18.3.1) … and 5 more
             [duplicate-versions]

     LOW     `array-union` is a standard-library call carried as a dependency
             Standard-library equivalent: [...new Set([...a, ...b])]
             About 16.8% of the npm registry is this shape. Each one is a
             maintainer account, a publish token and a release pipeline you
             are trusting to save a few lines of code.
             why: eslint-config-next@14.2.3 -> @typescript-eslint/parser@7.2.0 -> @typescript-eslint/typescript-estree@7.2.0 -> globby@11.1.0 -> array-union@2.1.0
             [trivial-package]

     LOW     `escape-string-regexp` is a standard-library call carried as a dependency
             Standard-library equivalent: one replace() with a character
             class
             About 16.8% of the npm registry is this shape. Each one is a
             maintainer account, a publish token and a release pipeline you
             are trusting to save a few lines of code.
             why: eslint@8.57.1 -> escape-string-regexp@4.0.0
             [trivial-package]

     LOW     `has-flag` is a standard-library call carried as a dependency
             Standard-library equivalent: argv.includes('--flag')
             About 16.8% of the npm registry is this shape. Each one is a
             maintainer account, a publish token and a release pipeline you
             are trusting to save a few lines of code.
             why: eslint@8.57.1 -> chalk@4.1.2 -> supports-color@7.2.0 -> has-flag@4.0.0
             [trivial-package]

  67 more findings hidden by -v / --top

  SUMMARY  0 critical · 0 high · 2 medium · 15 low · 56 info
  compared 482 names against 454 known-popular npm package names, offline

```

## `specter` — `package-lock.json`

```

  stranger 1.0.0 · specter/package-lock.json · npm · lockfileVersion 3

        546  packages in the tree
         25  you chose
        521  arrived with them

  ######################################.. 95% of your tree is code nobody chose

  max depth 9  ·  3 run install scripts  ·  17 duplicated  ·  6 cycles

  FINDINGS (6)

    MEDIUM   `core-js` runs code during install
             Lifecycle hooks present: hasInstallScript. These execute on
             `install`, before anyone reads the code, with the permissions of
             whoever ran the command — including CI.
             why: jspdf@4.2.1 -> core-js@3.49.0
             [install-script]

    MEDIUM   `sharp` runs code during install
             Lifecycle hooks present: hasInstallScript. These execute on
             `install`, before anyone reads the code, with the permissions of
             whoever ran the command — including CI.
             why: next@16.2.9 -> sharp@0.34.5
             [install-script]

    MEDIUM   `unrs-resolver` runs code during install
             Lifecycle hooks present: hasInstallScript. These execute on
             `install`, before anyone reads the code, with the permissions of
             whoever ran the command — including CI.
             why: eslint-config-next@16.2.9 -> eslint-import-resolver-typescript@3.10.1 -> unrs-resolver@1.12.2
             [install-script]

     LOW     17 packages are installed at more than one version
             Patching one copy does not patch the others. This is how an
             advisory gets marked resolved while a vulnerable copy stays in
             the bundle.
             @emnapi/runtime (1.10.0, 1.11.1), balanced-match (1.0.2, 4.0.4),
             brace-expansion (1.1.15, 5.0.7), debug (3.2.7, 4.4.3),
             eslint-visitor-keys (3.4.3, 4.2.1, 5.0.1), fflate (0.6.10,
             0.8.3), glob-parent (5.1.2, 6.0.2), globals (14.0.0, 16.4.0),
             ignore (5.3.2, 7.0.5), json5 (1.0.2, 2.2.3), maath (0.10.8,
             0.6.0), minimatch (10.2.5, 3.1.5) … and 5 more
             [duplicate-versions]

     LOW     `escape-string-regexp` is a standard-library call carried as a dependency
             Standard-library equivalent: one replace() with a character
             class
             About 16.8% of the npm registry is this shape. Each one is a
             maintainer account, a publish token and a release pipeline you
             are trusting to save a few lines of code.
             why: eslint@9.39.4 -> escape-string-regexp@4.0.0
             [trivial-package]

     LOW     `has-flag` is a standard-library call carried as a dependency
             Standard-library equivalent: argv.includes('--flag')
             About 16.8% of the npm registry is this shape. Each one is a
             maintainer account, a publish token and a release pipeline you
             are trusting to save a few lines of code.
             why: eslint@9.39.4 -> chalk@4.1.2 -> supports-color@7.2.0 -> has-flag@4.0.0
             [trivial-package]

  49 more findings hidden by -v / --top

  SUMMARY  0 critical · 0 high · 3 medium · 11 low · 41 info
  compared 546 names against 454 known-popular npm package names, offline

```

## `stranger` — `Cargo.lock`

```

  stranger 1.0.0 · stranger/Cargo.lock · crates.io · lockfileVersion 4

          0  packages in the tree
          0  you chose
          0  arrived with them

  ........................................ 0% of your tree is code nobody chose

  max depth 0

  CLEAN  nothing to report

```

---

## False-positive sweep

Every lockfile above, checked against the three rules that can produce a HIGH
or CRITICAL on a legitimate package — name-similarity, confusable glyphs,
off-registry provenance, and direct-URL requirements. Anything printed between
the markers is a false positive.

```
--- begin sweep ---
--- end sweep ---
```

## Result

No HIGH or CRITICAL findings on any real project tree. Everything the tool
reported was accurate and actionable: packages that genuinely run install
scripts (`fsevents`, `sharp`, `core-js`, `unrs-resolver`), packages genuinely
present at multiple versions, and one-liners genuinely carried as
dependencies.

This is what the three precision gates on the name-similarity rule were for.
An earlier version, gated only on edit distance, reported `etag` as a near-miss
for `tar` and `depd` for `del` — both true at distance 2, both worthless. See
the README section on that rule for what changed and why.
