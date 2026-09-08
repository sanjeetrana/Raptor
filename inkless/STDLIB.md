# What the standard library replaced

Every row is a package this project would ordinarily have installed, and what
was used instead. `requirements.txt` is zero bytes.

| Would install | Used instead | Rationale |
|:--|:--|:--|
| `reportlab`, `fpdf2` | A hand written PDF object model and writer (`inkless.py` sections 10 and 11) | This is the project. A PDF is eight value types, numbered indirect objects, a table of byte offsets and a trailer. `zlib` supplies the one thing that genuinely needs a C library, and it is in the standard library already. |
| `weasyprint`, `wkhtmltopdf`, `playwright` | Markdown straight to PDF, with no HTML step | A browser engine to lay out text is an enormous dependency for a job that is measuring strings and stacking boxes. Skipping HTML also removes a whole class of CSS surprises. |
| `markdown`, `mistune`, `commonmark` | A hand written character scanning parser (sections 3 and 4) | A parser that hands back spans does not hand back positions. Scanning by index yields the byte offset, line and column of every token for free, which is what makes a caret under the exact offending character possible. |
| `re` (standard library, but banned here) | Index arithmetic | Not a dependency, but worth listing: `re` is never imported in `inkless.py`, enforced by a test that walks the syntax tree. Regular expressions are how a Markdown parser ends up handling only the happy path. |
| `Pillow` | Hand written PNG chunk parsing and scanline unfiltering (section 6) | Only the header fields and the pixel data are needed. `zlib` already does the decompression, and PDF's FlateDecode understands PNG predictors natively, so a truecolour image needs no processing at all. |
| `fonttools`, `matplotlib.font_manager` | Hard-coded metrics for the standard 14 PDF fonts (section 5) | Conforming readers are required to supply these fonts, so no file is ever parsed or embedded. Only the advance widths are needed, and those are published constants. |
| `numpy` | `bytearray` and integer arithmetic | The heaviest numeric work is undoing PNG scanline filters over a few million bytes. A list of integers is entirely adequate and avoids a 20 MB wheel. |
| `click`, `typer` | `argparse`, with the colour support added in Python 3.14 | The standard parser gained the one feature that used to justify reaching for a third-party one. Colour is passed only when the interpreter supports it, so the same file still runs on 3.10. |
| `colorama`, `rich`, `termcolor` | Raw ANSI escapes, `NO_COLOR` honoured, TTY checked | Two escape sequences and three conditions. `colorama` existed for a Windows console problem that modern Windows terminals no longer have. |
| `pyyaml` | A hand written `key: value` front matter reader (section 4) | Front matter here names a title, an author and a date. Supporting anchors, flow sequences and multi-line scalars would be implementing YAML for no gain, so the reader does exactly the documented subset and warns on anything else. |
| `pydantic`, `attrs` | `dataclasses` | AST nodes, style records and paint operations are plain data with defaults. `dataclasses` has done this since 3.7. |
| `jinja2`, `mako` | f-strings | Nothing here is templated by a user. The only generated text is diagnostics and PDF syntax, both of which are assembled from bytes. |
| `pytest`, `nose` | `unittest` with `subTest` | `subTest` gives table-driven cases that report the failing tuple by name, which is the feature the table-driven requirement actually needs. |
| `hypothesis` | Explicit adversarial case tables | The malformed-input group is 36 hand-picked documents where the expected warning **and its exact line and column** are asserted. Generated inputs would not know the right position to expect. |
| `pypdf`, `pdfminer` | A ~150 line PDF reader written inside `test_inkless.py` | The tests must not trust the writer's own bookkeeping. A reader written independently re-derives the xref from the finished bytes, and two tests corrupt a file on purpose to prove the checker would notice. |
| `python-dateutil` | `str.split` and a shape check | The date is a label printed into the document, not an instant. It is validated for shape and never compared, formatted or arithmetic'd. |
| `filetype`, `imghdr` | `bytes.startswith` on the PNG signature | One eight byte constant. |
| `zopfli`, `brotli` | `zlib` at level 9 | Content streams are highly repetitive text and compress well already. PDF readers are required to support FlateDecode and nothing better. |

## Standard library modules actually imported

`argparse`, `bisect`, `dataclasses`, `hashlib`, `os`, `pathlib`, `struct`,
`sys`, `typing`, `unicodedata`, `zlib`, and `__future__`.

Eleven modules, all of them shipped with Python. The test suite adds `ast`,
`shutil`, `tempfile` and `unittest`.

## What each one is for

| Module | Why |
|:--|:--|
| `zlib` | FlateDecode content streams, PNG decompression, and CRC32 for PNG chunk checksums |
| `hashlib` | The content-derived `/ID` in the trailer, which is what keeps builds reproducible without a clock |
| `struct` | Unpacking the 13 byte PNG IHDR chunk |
| `bisect` | Binary search over line starts, so any offset resolves to a line and column without a scan |
| `unicodedata` | Punctuation classification for the CommonMark flanking rules, and NFD decomposition to find an accented letter's base |
| `dataclasses` | AST nodes, text styles, paint operations, page geometry |
| `pathlib` | Every filesystem path |
| `argparse` | The command line, with 3.14 colour |
| `os`, `sys` | `NO_COLOR`, TTY detection, exit status, standard input |
| `typing` | `Iterator` in two signatures; everything else is builtin generics |
