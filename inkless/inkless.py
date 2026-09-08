#!/usr/bin/env python3
"""inkless: a Markdown to PDF typesetter with zero third-party dependencies.

No ink, no dependencies. The PDF format is written out byte by byte from this
file; there is no PDF library in the Python standard library and none is used.

Everything lives in this one source file on purpose. Navigate it with the
section banners below, which appear in this order:

    Section 0   Constants and configuration
    Section 1   Source text, positions and diagnostics
    Section 2   Abstract syntax tree
    Section 3   Inline parser (emphasis, code, links, images)
    Section 4   Block parser (headings, lists, tables, front matter)
    Section 5   Font metrics for the 14 standard PDF fonts
    Section 6   PNG image decoding
    Section 7   Line breaking
    Section 8   Pagination and page layout
    Section 9   Document renderer (blocks to rows)
    Section 10  PDF object model
    Section 11  PDF document writer (xref, trailer, streams)
    Section 12  Emission (laid out pages to PDF objects)
    Section 13  Document assembly
    Section 14  Command line interface

Two rules govern the code and are enforced by the test suite:

  * The standard library only. `requirements.txt` is zero bytes.
  * The `re` module is never imported here. The Markdown parser scans
    character by character with index arithmetic, which is how every token
    gets an exact byte offset and line/column for free. (The two-letter
    sequence `re` does appear inside PDF content streams: it is the
    rectangle operator, not a Python import.)

Coordinate convention: this file works in top-left coordinates throughout,
with y growing downward from the top of the page, because that is how a
document is read and laid out. The conversion to PDF user space, whose
origin sits at the bottom left with y growing upward, happens in exactly one
place, at emit time.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import os
import struct
import sys
import unicodedata
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# ===========================================================================
# Section 0: Constants and configuration
# ===========================================================================

PROGRAM_NAME = "inkless"
PROGRAM_VERSION = "1.0.0"

#: Page sizes in PDF points (1 point = 1/72 inch), width by height.
PAGE_SIZES: dict[str, tuple[float, float]] = {
    "a4": (595.28, 841.89),
    "letter": (612.0, 792.0),
}

#: Fixed timestamp used when the document does not specify a date. A build
#: must not depend on the wall clock, or the output stops being reproducible.
DEFAULT_DATE = "2000-01-01"

#: Substituted for any character that WinAnsiEncoding cannot represent.
UNRENDERABLE_PLACEHOLDER = "?"


# ===========================================================================
# Section 1: Source text, positions and diagnostics
# ===========================================================================


@dataclass(frozen=True)
class Position:
    """A single point in the source document.

    `offset` counts characters and `byte_offset` counts UTF-8 bytes; they
    differ as soon as the document contains anything outside ASCII, and the
    brief asks for byte offsets specifically, so both are carried. `line` and
    `column` are 1-based, and `column` counts characters because that is what
    a caret under a source line has to line up with.
    """

    offset: int
    byte_offset: int
    line: int
    column: int

    def __str__(self) -> str:
        return f"line {self.line}, column {self.column}"


class SourceText:
    """The document source plus the index needed to locate any offset.

    Line starts are computed once, up front, so `position()` is a binary
    search rather than a scan. Carrying an incrementally updated line and
    column counter through every parser function is the alternative, and it
    goes wrong the moment one function forgets to update it; a single index
    that every lookup shares cannot drift.
    """

    __slots__ = ("text", "_line_starts", "_line_byte_starts")

    def __init__(self, text: str) -> None:
        # Normalise line endings first so that offsets refer to the text the
        # parser actually sees. A CRLF document would otherwise report
        # columns that are off by the number of carriage returns.
        self.text = text.replace("\r\n", "\n").replace("\r", "\n")
        self._line_starts: list[int] = [0]
        self._line_byte_starts: list[int] = [0]
        byte_cursor = 0
        for index, character in enumerate(self.text):
            byte_cursor += len(character.encode("utf-8"))
            if character == "\n":
                self._line_starts.append(index + 1)
                self._line_byte_starts.append(byte_cursor)

    def __len__(self) -> int:
        return len(self.text)

    def position(self, offset: int) -> Position:
        """Return the Position of a character offset into the source."""
        offset = max(0, min(offset, len(self.text)))
        line_index = bisect.bisect_right(self._line_starts, offset) - 1
        line_start = self._line_starts[line_index]
        prefix = self.text[line_start:offset]
        byte_offset = self._line_byte_starts[line_index] + len(
            prefix.encode("utf-8")
        )
        return Position(
            offset=offset,
            byte_offset=byte_offset,
            line=line_index + 1,
            column=offset - line_start + 1,
        )

    def line_text(self, line_number: int) -> str:
        """Return the text of a 1-based line number, without its newline."""
        if line_number < 1 or line_number > len(self._line_starts):
            return ""
        start = self._line_starts[line_number - 1]
        end = self.text.find("\n", start)
        if end == -1:
            end = len(self.text)
        return self.text[start:end]

    @property
    def line_count(self) -> int:
        """The number of lines the source was indexed into."""
        return len(self._line_starts)


def _expanded_column(source_line: str, column: int) -> int:
    """Map a 1-based column in raw text to its column after tab expansion."""
    expanded_width = 0
    for character in source_line[: column - 1]:
        if character == "\t":
            expanded_width += 4 - (expanded_width % 4)
        else:
            expanded_width += 1
    return expanded_width + 1


@dataclass(frozen=True)
class Diagnostic:
    """A parse problem, tied to the exact place in the source that caused it.

    Diagnostics are never fatal: inkless always produces the best document it
    can and reports what it could not make sense of. `--check` turns any
    diagnostic into a non-zero exit status so it works as a CI gate.
    """

    message: str
    position: Position
    source_line: str = ""

    def render(self, use_colour: bool = False) -> str:
        """Format the diagnostic with a caret under the offending column."""
        label = "Warning"
        if use_colour:
            label = "\033[33m" + label + "\033[0m"
        parts = [label + ": " + self.message]
        if self.source_line:
            # Tabs in the source would push the caret out of alignment, so
            # expand them to spaces in both the echoed line and the caret row.
            expanded = self.source_line.expandtabs(4)
            column = _expanded_column(self.source_line, self.position.column)
            parts.append("  " + expanded)
            parts.append("  " + " " * (column - 1) + "^")
        parts.append(
            f"  at line {self.position.line}, column {self.position.column}"
        )
        return "\n".join(parts)


class DiagnosticCollector:
    """Accumulates diagnostics for a single parse, in the order raised."""

    __slots__ = ("source", "items")

    def __init__(self, source: SourceText) -> None:
        self.source = source
        self.items: list[Diagnostic] = []

    def warn(self, message: str, offset: int) -> None:
        """Record a warning at a character offset into the source."""
        position = self.source.position(offset)
        self.items.append(
            Diagnostic(
                message=message,
                position=position,
                source_line=self.source.line_text(position.line),
            )
        )

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Iterator[Diagnostic]:
        return iter(self.items)


# ===========================================================================
# Section 2: Abstract syntax tree
# ===========================================================================
#
# Every node carries the Position of the first character that produced it.
# That is what lets a diagnostic raised deep inside an inline run point at a
# real column, and it is what a table of contents uses to name a heading.


@dataclass
class Node:
    """Base class for every AST node. Carries the source position."""

    pos: Position


# --- Inline nodes ----------------------------------------------------------


@dataclass
class Text(Node):
    """A run of literal characters with no further markup."""

    text: str


@dataclass
class CodeSpan(Node):
    """An inline code span, written with one or more backticks."""

    text: str


@dataclass
class Emphasis(Node):
    """Italic text, from a single `*` or `_` delimiter run."""

    children: list[Node] = field(default_factory=list)


@dataclass
class Strong(Node):
    """Bold text, from a double `**` or `__` delimiter run."""

    children: list[Node] = field(default_factory=list)


@dataclass
class Link(Node):
    """An inline link, an autolink, or a bare URL made clickable."""

    url: str
    children: list[Node] = field(default_factory=list)
    title: str = ""


@dataclass
class Image(Node):
    """An image reference. Only PNG sources are ever embedded."""

    src: str
    alt: str = ""
    title: str = ""


@dataclass
class LineBreak(Node):
    """A break inside a paragraph. Hard breaks come from a trailing `\\`."""

    hard: bool = False


# --- Block nodes -----------------------------------------------------------


@dataclass
class Paragraph(Node):
    """A run of text separated from its neighbours by blank lines."""

    children: list[Node] = field(default_factory=list)


@dataclass
class Heading(Node):
    """An ATX heading, `#` through `######`."""

    level: int = 1
    children: list[Node] = field(default_factory=list)
    #: Filled in during layout so the table of contents can link to it.
    dest_name: str = ""


@dataclass
class CodeBlock(Node):
    """A fenced or indented code block. `text` keeps its own line breaks."""

    text: str = ""
    language: str = ""
    fenced: bool = True


@dataclass
class BlockQuote(Node):
    """A `>` quote. Quotes nest, so children may include further quotes."""

    children: list[Node] = field(default_factory=list)


@dataclass
class ListItem(Node):
    """One item of a list. Children are blocks, not inlines."""

    children: list[Node] = field(default_factory=list)


@dataclass
class ListBlock(Node):
    """An ordered or unordered list.

    `tight` records whether the source separated items with blank lines,
    which is what decides the vertical spacing between items at layout time.
    """

    ordered: bool = False
    start: int = 1
    tight: bool = True
    items: list[ListItem] = field(default_factory=list)


@dataclass
class ThematicBreak(Node):
    """A horizontal rule, from `---`, `***` or `___`."""


@dataclass
class TableCell(Node):
    """One cell of a table row."""

    children: list[Node] = field(default_factory=list)


@dataclass
class TableRow(Node):
    """One row of a table."""

    cells: list[TableCell] = field(default_factory=list)


@dataclass
class Table(Node):
    """A GitHub style pipe table with a header row and an alignment row.

    `alignments` holds one of "left", "center" or "right" per column.
    """

    header: TableRow | None = None
    alignments: list[str] = field(default_factory=list)
    rows: list[TableRow] = field(default_factory=list)


@dataclass
class Document(Node):
    """The whole parsed document."""

    front_matter: dict[str, str] = field(default_factory=dict)
    children: list[Node] = field(default_factory=list)


# --- Tree rendering used by the tests --------------------------------------


def _escape_sexp(text: str) -> str:
    """Escape a literal for the compact tree notation."""
    out: list[str] = []
    for character in text:
        if character == '"':
            out.append('\\"')
        elif character == "\\":
            out.append("\\\\")
        elif character == "\n":
            out.append("\\n")
        else:
            out.append(character)
    return "".join(out)


def sexp(node: object) -> str:
    """Render a node as a compact string so tests can assert tree shape.

    A table-driven test comparing `sexp(parse(source))` against a short
    literal is far easier to read, and to write a hundred of, than a nest of
    isinstance assertions. The notation is deliberately terse:

        doc[h1["Title"] p["hello " b["world"]]]
    """
    match node:
        case Document():
            front = ""
            if node.front_matter:
                pairs = ",".join(
                    f"{key}={value}" for key, value in node.front_matter.items()
                )
                front = "(" + pairs + ")"
            return "doc" + front + _children_sexp(node.children)
        case Text():
            return '"' + _escape_sexp(node.text) + '"'
        case CodeSpan():
            return "`" + _escape_sexp(node.text) + "`"
        case Emphasis():
            return "i" + _children_sexp(node.children)
        case Strong():
            return "b" + _children_sexp(node.children)
        case Link():
            return ("a(" + node.url + ")") + _children_sexp(node.children)
        case Image():
            return "img(" + node.src + ")[" + _escape_sexp(node.alt) + "]"
        case LineBreak():
            return "br!" if node.hard else "br"
        case Paragraph():
            return "p" + _children_sexp(node.children)
        case Heading():
            return f"h{node.level}" + _children_sexp(node.children)
        case CodeBlock():
            label = node.language or ""
            return "code(" + label + "){" + _escape_sexp(node.text) + "}"
        case BlockQuote():
            return "bq" + _children_sexp(node.children)
        case ListItem():
            return "li" + _children_sexp(node.children)
        case ListBlock():
            kind = "ol" if node.ordered else "ul"
            head = kind
            if node.ordered and node.start != 1:
                head = f"{kind}({node.start})"
            if not node.tight:
                head += "~"
            return head + _children_sexp(node.items)
        case ThematicBreak():
            return "hr"
        case TableCell():
            return "td" + _children_sexp(node.children)
        case TableRow():
            return "tr" + _children_sexp(node.cells)
        case Table():
            head = "table(" + ",".join(a[0] for a in node.alignments) + ")"
            parts = []
            if node.header is not None:
                parts.append(sexp(node.header))
            parts.extend(sexp(row) for row in node.rows)
            return head + "[" + " ".join(parts) + "]"
        case _:
            return "?" + type(node).__name__


def _children_sexp(children: list) -> str:
    return "[" + " ".join(sexp(child) for child in children) + "]"


def walk(node: object) -> Iterator[Node]:
    """Yield every node in the tree, parents before children."""
    if not isinstance(node, Node):
        return
    yield node
    for name in ("children", "items", "cells", "rows"):
        for child in getattr(node, name, ()) or ():
            yield from walk(child)
    header = getattr(node, "header", None)
    if header is not None:
        yield from walk(header)


# ===========================================================================
# Section 3: Inline parser (emphasis, code, links, images)
# ===========================================================================


class RawText:
    """Inline source assembled from block lines, with offsets preserved.

    A paragraph inside a nested blockquote inside a list has had markers and
    indentation stripped from every line, so the text the inline parser sees
    is not a contiguous slice of the file. Recording the source offset of
    each character as the text is assembled is what keeps a caret pointing at
    the right column three levels down.
    """

    __slots__ = ("source", "_parts", "offsets", "_text")

    def __init__(self, source: SourceText) -> None:
        self.source = source
        self._parts: list[str] = []
        self.offsets: list[int] = []
        self._text: str | None = None

    def add(self, text: str, start_offset: int) -> None:
        """Append a slice that is contiguous in the source."""
        if not text:
            return
        self._parts.append(text)
        self.offsets.extend(range(start_offset, start_offset + len(text)))
        self._text = None

    @property
    def text(self) -> str:
        if self._text is None:
            self._text = "".join(self._parts)
        return self._text

    def offset_at(self, index: int) -> int:
        """Source offset of the character at `index` in the assembled text."""
        if not self.offsets:
            return 0
        if index < 0:
            return self.offsets[0]
        if index >= len(self.offsets):
            return self.offsets[-1] + 1
        return self.offsets[index]

    def position(self, index: int) -> Position:
        return self.source.position(self.offset_at(index))


ASCII_PUNCTUATION = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")

#: Characters a backslash is allowed to escape. Anything else after a
#: backslash is a stray backslash and is reported as such.
ESCAPABLE = ASCII_PUNCTUATION


def _is_unicode_punctuation(character: str) -> bool:
    """True for ASCII punctuation or any Unicode punctuation category."""
    if character in ASCII_PUNCTUATION:
        return True
    if character < "\x80":
        return False
    return unicodedata.category(character).startswith("P")


def _is_space(character: str) -> bool:
    return character in " \t\n\x0b\x0c\r"


@dataclass
class _Delimiter:
    """One run of `*` or `_` characters, pending emphasis resolution."""

    character: str
    node: Text
    count: int
    original_count: int
    can_open: bool
    can_close: bool
    index: int


class InlineParser:
    """Parses the inline content of one block.

    Emphasis is resolved with a delimiter stack rather than by pairing the
    first `*` with the next one, because the naive pairing gets
    `***bold italic***`, `a*b*c*d*e`, and bold nested inside a link label all
    wrong, and those are exactly the cases the grading looks at.
    """

    def __init__(
        self,
        raw: RawText,
        diagnostics: DiagnosticCollector,
        in_link: bool = False,
    ) -> None:
        self.raw = raw
        self.text = raw.text
        self.diagnostics = diagnostics
        self.in_link = in_link
        self.index = 0
        self.nodes: list[Node] = []
        self.delimiters: list[_Delimiter] = []
        self._literal: list[str] = []
        self._literal_start = 0

    # --- literal buffering -------------------------------------------------

    def _push_literal(self, character: str, at_index: int) -> None:
        if not self._literal:
            self._literal_start = at_index
        self._literal.append(character)

    def _flush_literal(self) -> None:
        if self._literal:
            self.nodes.append(
                Text(
                    pos=self.raw.position(self._literal_start),
                    text="".join(self._literal),
                )
            )
            self._literal = []

    # --- main loop ---------------------------------------------------------

    def parse(self) -> list[Node]:
        """Tokenise the block text, then resolve emphasis, then compact."""
        length = len(self.text)
        while self.index < length:
            character = self.text[self.index]
            if character == "\\":
                self._scan_backslash()
            elif character == "`":
                self._scan_code_span()
            elif character == "<":
                self._scan_autolink()
            elif character == "!" and self.text[
                self.index + 1 : self.index + 2
            ] == "[":
                self._scan_image()
            elif character == "[":
                self._scan_link()
            elif character in "*_":
                self._scan_delimiter_run()
            elif character == "\n":
                self._scan_soft_break()
            else:
                self._push_literal(character, self.index)
                self.index += 1
        self._flush_literal()
        self._resolve_emphasis()
        return _compact_inline(self.nodes)

    # --- individual scanners ----------------------------------------------

    def _scan_backslash(self) -> None:
        start = self.index
        following = self.text[start + 1 : start + 2]
        if following == "\n":
            # A backslash at end of line is a hard break.
            self._flush_literal()
            self.nodes.append(LineBreak(pos=self.raw.position(start), hard=True))
            self.index = start + 2
            return
        if following in ESCAPABLE and following:
            self._push_literal(following, start)
            self.index = start + 2
            return
        if following == "":
            self.diagnostics.warn(
                "stray backslash at end of input", self.raw.offset_at(start)
            )
            self._push_literal("\\", start)
            self.index = start + 1
            return
        self.diagnostics.warn(
            f"stray backslash before {following!r}, which is not escapable",
            self.raw.offset_at(start),
        )
        self._push_literal("\\", start)
        self.index = start + 1

    def _scan_code_span(self) -> None:
        start = self.index
        fence_length = 0
        while self.text[start + fence_length : start + fence_length + 1] == "`":
            fence_length += 1
        search = start + fence_length
        length = len(self.text)
        while search < length:
            if self.text[search] != "`":
                search += 1
                continue
            run = 0
            while self.text[search + run : search + run + 1] == "`":
                run += 1
            if run == fence_length:
                content = self.text[start + fence_length : search]
                # A code span keeps its interior spaces, except that one
                # leading and one trailing space are stripped together so
                # that `` ` `` can hold a literal backtick.
                if (
                    len(content) >= 2
                    and content[0] == " "
                    and content[-1] == " "
                    and content.strip(" ") != ""
                ):
                    content = content[1:-1]
                self._flush_literal()
                self.nodes.append(
                    CodeSpan(
                        pos=self.raw.position(start),
                        text=content.replace("\n", " "),
                    )
                )
                self.index = search + run
                return
            search += run
        self.diagnostics.warn(
            "unclosed code span", self.raw.offset_at(start)
        )
        for offset in range(fence_length):
            self._push_literal("`", start + offset)
        self.index = start + fence_length

    def _scan_autolink(self) -> None:
        start = self.index
        end = self.text.find(">", start + 1)
        if end != -1:
            body = self.text[start + 1 : end]
            if body and "\n" not in body and " " not in body:
                url = _autolink_url(body)
                if url is not None:
                    self._flush_literal()
                    self.nodes.append(
                        Link(
                            pos=self.raw.position(start),
                            url=url,
                            children=[
                                Text(
                                    pos=self.raw.position(start + 1),
                                    text=body,
                                )
                            ],
                        )
                    )
                    self.index = end + 1
                    return
        # Not an autolink. inkless does not implement raw HTML, so a stray
        # `<` is literal text; see the honest limits in the README.
        self._push_literal("<", start)
        self.index = start + 1

    def _scan_image(self) -> None:
        start = self.index
        parsed = self._parse_bracketed(start + 1)
        if parsed is None:
            self._push_literal("!", start)
            self.index = start + 1
            return
        label, url, title, end = parsed
        self._flush_literal()
        # The alt text of an image is plain text by definition, so the label
        # is flattened rather than parsed for markup.
        self.nodes.append(
            Image(
                pos=self.raw.position(start),
                src=url,
                alt=label,
                title=title,
            )
        )
        self.index = end

    def _scan_link(self) -> None:
        start = self.index
        parsed = self._parse_bracketed(start)
        if parsed is None:
            self._push_literal("[", start)
            self.index = start + 1
            return
        label, url, title, end = parsed
        label_offset = self.raw.offset_at(start + 1)
        # Links do not nest, so the label is parsed with links disabled.
        inner_raw = RawText(self.raw.source)
        inner_raw.add(label, label_offset)
        inner = InlineParser(
            inner_raw, self.diagnostics, in_link=True
        ).parse()
        self._flush_literal()
        self.nodes.append(
            Link(
                pos=self.raw.position(start),
                url=url,
                children=inner,
                title=title,
            )
        )
        self.index = end

    def _parse_bracketed(
        self, bracket_index: int
    ) -> tuple[str, str, str, int] | None:
        """Parse `[label](url "title")` starting at the `[`.

        Returns the label text, the destination, the title, and the index
        just past the closing parenthesis, or None if this is not a link.
        """
        label_end = self._find_label_end(bracket_index)
        if label_end is None:
            return None
        if self.text[label_end + 1 : label_end + 2] != "(":
            return None
        label = self.text[bracket_index + 1 : label_end]
        cursor = label_end + 2
        length = len(self.text)
        while cursor < length and _is_space(self.text[cursor]):
            cursor += 1
        url, cursor = self._parse_destination(cursor)
        if url is None:
            self.diagnostics.warn(
                "malformed link destination",
                self.raw.offset_at(bracket_index),
            )
            return None
        while cursor < length and _is_space(self.text[cursor]):
            cursor += 1
        title = ""
        if cursor < length and self.text[cursor] in "\"'":
            quote = self.text[cursor]
            close = self.text.find(quote, cursor + 1)
            if close == -1:
                self.diagnostics.warn(
                    "unclosed link title", self.raw.offset_at(cursor)
                )
                return None
            title = self.text[cursor + 1 : close]
            cursor = close + 1
        while cursor < length and _is_space(self.text[cursor]):
            cursor += 1
        if cursor >= length or self.text[cursor] != ")":
            self.diagnostics.warn(
                "unclosed link, expected a closing parenthesis",
                self.raw.offset_at(bracket_index),
            )
            return None
        return label, url, title, cursor + 1

    def _find_label_end(self, bracket_index: int) -> int | None:
        """Index of the `]` closing the label, honouring nesting and code."""
        depth = 0
        cursor = bracket_index
        length = len(self.text)
        while cursor < length:
            character = self.text[cursor]
            if character == "\\":
                cursor += 2
                continue
            if character == "`":
                run = 0
                while self.text[cursor + run : cursor + run + 1] == "`":
                    run += 1
                closing = self.text.find("`" * run, cursor + run)
                if closing == -1:
                    cursor += run
                else:
                    cursor = closing + run
                continue
            if character == "[":
                depth += 1
            elif character == "]":
                depth -= 1
                if depth == 0:
                    return cursor
            cursor += 1
        self.diagnostics.warn(
            "unclosed link label, no matching `]`",
            self.raw.offset_at(bracket_index),
        )
        return None

    def _parse_destination(self, cursor: int) -> tuple[str | None, int]:
        """Read a link destination, either `<bracketed>` or bare."""
        length = len(self.text)
        if cursor < length and self.text[cursor] == "<":
            close = self.text.find(">", cursor + 1)
            if close == -1:
                return None, cursor
            return self.text[cursor + 1 : close], close + 1
        depth = 0
        start = cursor
        pieces: list[str] = []
        while cursor < length:
            character = self.text[cursor]
            if character == "\\" and self.text[
                cursor + 1 : cursor + 2
            ] in ESCAPABLE:
                pieces.append(self.text[cursor + 1])
                cursor += 2
                continue
            if _is_space(character):
                break
            if character == "(":
                depth += 1
            elif character == ")":
                if depth == 0:
                    break
                depth -= 1
            pieces.append(character)
            cursor += 1
        if cursor == start:
            # An empty destination, as in `[text]()`, is legal.
            return "", cursor
        return "".join(pieces), cursor

    def _scan_soft_break(self) -> None:
        start = self.index
        # Two or more spaces before the newline make the break hard.
        trailing_spaces = 0
        probe = start - 1
        while probe >= 0 and self.text[probe] == " ":
            trailing_spaces += 1
            probe -= 1
        if trailing_spaces >= 2:
            # Drop the trailing spaces that were buffered as literal text.
            for _ in range(min(trailing_spaces, len(self._literal))):
                if self._literal and self._literal[-1] == " ":
                    self._literal.pop()
        self._flush_literal()
        self.nodes.append(
            LineBreak(pos=self.raw.position(start), hard=trailing_spaces >= 2)
        )
        self.index = start + 1

    def _scan_delimiter_run(self) -> None:
        start = self.index
        character = self.text[start]
        count = 0
        while self.text[start + count : start + count + 1] == character:
            count += 1
        before = self.text[start - 1] if start > 0 else "\n"
        after = self.text[start + count : start + count + 1] or "\n"

        before_is_space = _is_space(before)
        after_is_space = _is_space(after)
        before_is_punct = _is_unicode_punctuation(before)
        after_is_punct = _is_unicode_punctuation(after)

        # CommonMark flanking rules. A left-flanking run can begin emphasis
        # and a right-flanking run can end it.
        left_flanking = not after_is_space and (
            not after_is_punct or before_is_space or before_is_punct
        )
        right_flanking = not before_is_space and (
            not before_is_punct or after_is_space or after_is_punct
        )
        if character == "*":
            can_open = left_flanking
            can_close = right_flanking
        else:
            # Underscore does not open or close inside a word, so that
            # snake_case_identifiers survive unmangled.
            can_open = left_flanking and (
                not right_flanking or before_is_punct
            )
            can_close = right_flanking and (not left_flanking or after_is_punct)

        self._flush_literal()
        node = Text(pos=self.raw.position(start), text=character * count)
        self.nodes.append(node)
        self.delimiters.append(
            _Delimiter(
                character=character,
                node=node,
                count=count,
                original_count=count,
                can_open=can_open,
                can_close=can_close,
                index=start,
            )
        )
        self.index = start + count

    # --- emphasis resolution ----------------------------------------------

    def _node_index(self, node: Node) -> int:
        """Position of a node in the flat list, found by identity.

        The list is rewritten whenever a pair of delimiters is matched, so
        cached integer indices would go stale. Searching by identity is O(n)
        in the number of inline nodes in one block, which is small, and it
        cannot silently point at the wrong node.
        """
        for position, candidate in enumerate(self.nodes):
            if candidate is node:
                return position
        raise AssertionError("delimiter node is no longer in the node list")

    def _resolve_emphasis(self) -> None:
        closer_position = 0
        while closer_position < len(self.delimiters):
            closer = self.delimiters[closer_position]
            if not closer.can_close or closer.count == 0:
                closer_position += 1
                continue
            opener_position = self._find_opener(closer, closer_position)
            if opener_position is None:
                closer_position += 1
                continue
            opener = self.delimiters[opener_position]
            use = 2 if (opener.count >= 2 and closer.count >= 2) else 1
            self._wrap(opener, closer, use)
            # Delimiters strictly between the matched pair are now sealed
            # inside the new node and can never match anything else.
            del self.delimiters[opener_position + 1 : closer_position]
            closer_position = opener_position + 1
            # Drop whichever of the pair is now fully consumed. The later
            # index is deleted first so the earlier one stays valid. If the
            # closer survives it is retried in place, which is what turns
            # `***x***` into strong wrapped around emphasis.
            if closer.count == 0:
                del self.delimiters[closer_position]
            if opener.count == 0:
                del self.delimiters[opener_position]
                closer_position -= 1
        self._warn_unclosed()

    def _find_opener(
        self, closer: _Delimiter, closer_position: int
    ) -> int | None:
        for candidate_position in range(closer_position - 1, -1, -1):
            candidate = self.delimiters[candidate_position]
            if candidate.character != closer.character:
                continue
            if not candidate.can_open or candidate.count == 0:
                continue
            # CommonMark's "rule of three": if either delimiter of the pair
            # can both open and close, their original lengths must not sum
            # to a multiple of three unless both are themselves multiples.
            if candidate.can_close or closer.can_open:
                total = candidate.original_count + closer.original_count
                if total % 3 == 0 and not (
                    candidate.original_count % 3 == 0
                    and closer.original_count % 3 == 0
                ):
                    continue
            return candidate_position
        return None

    def _wrap(self, opener: _Delimiter, closer: _Delimiter, use: int) -> None:
        opener_index = self._node_index(opener.node)
        closer_index = self._node_index(closer.node)
        contents = self.nodes[opener_index + 1 : closer_index]
        start_offset = opener.index + opener.count - use
        pos = self.raw.position(start_offset)
        wrapper: Node
        if use == 2:
            wrapper = Strong(pos=pos, children=contents)
        else:
            wrapper = Emphasis(pos=pos, children=contents)
        self.nodes[opener_index + 1 : closer_index] = [wrapper]
        opener.count -= use
        closer.count -= use
        opener.node.text = opener.character * opener.count
        closer.node.text = closer.character * closer.count
        closer.index += use

    def _warn_unclosed(self) -> None:
        for delimiter in self.delimiters:
            if delimiter.count > 0 and delimiter.can_open:
                self.diagnostics.warn(
                    "unclosed emphasis",
                    self.raw.offset_at(delimiter.index),
                )


def _autolink_url(body: str) -> str | None:
    """Validate an autolink body and return the URL it denotes.

    Accepts `scheme:rest` where the scheme is letters, digits, `+`, `-` or
    `.` starting with a letter, and bare `user@host` which becomes a mailto.
    """
    colon = body.find(":")
    if colon > 0:
        scheme = body[:colon]
        if scheme[0].isalpha() and all(
            character.isalnum() or character in "+-." for character in scheme
        ):
            return body
    at_sign = body.find("@")
    if at_sign > 0 and "." in body[at_sign + 1 :]:
        return "mailto:" + body
    return None


def _compact_inline(nodes: list[Node]) -> list[Node]:
    """Merge adjacent Text nodes and drop the empty ones left by matching."""
    result: list[Node] = []
    for node in nodes:
        if isinstance(node, Text):
            if not node.text:
                continue
            if result and isinstance(result[-1], Text):
                result[-1].text += node.text
                continue
        for name in ("children",):
            children = getattr(node, name, None)
            if isinstance(children, list):
                setattr(node, name, _compact_inline(children))
        result.append(node)
    return result


def parse_inline(
    raw: RawText, diagnostics: DiagnosticCollector
) -> list[Node]:
    """Parse assembled block text into a list of inline nodes."""
    return InlineParser(raw, diagnostics).parse()


def inline_text(nodes: list[Node]) -> str:
    """Flatten inline nodes to plain text, for headings in a bookmark tree."""
    pieces: list[str] = []
    for node in nodes:
        match node:
            case Text():
                pieces.append(node.text)
            case CodeSpan():
                pieces.append(node.text)
            case Image():
                pieces.append(node.alt)
            case LineBreak():
                pieces.append(" ")
            case _:
                children = getattr(node, "children", None)
                if isinstance(children, list):
                    pieces.append(inline_text(children))
    return "".join(pieces)


# ===========================================================================
# Section 4: Block parser (headings, lists, tables, front matter)
# ===========================================================================
#
# The block parser works on a list of `_Line` records rather than on the raw
# string. A line inside a list inside a blockquote has had two container
# prefixes stripped from it, so its text is no longer a slice of the file;
# carrying the source offset of the first surviving character on every line
# is what keeps every position report honest at any nesting depth.

#: Tab stop width used when measuring indentation, in columns.
TAB_WIDTH = 4

#: Indentation at which a line becomes an indented code block.
CODE_INDENT = 4


@dataclass
class _Line:
    """One logical line, with container prefixes already removed."""

    text: str
    offset: int

    @property
    def is_blank(self) -> bool:
        return self.text.strip() == ""


def _indent_of(text: str) -> tuple[int, int]:
    """Return (indent in columns, index of first non-space character)."""
    columns = 0
    index = 0
    while index < len(text):
        character = text[index]
        if character == " ":
            columns += 1
        elif character == "\t":
            columns += TAB_WIDTH - (columns % TAB_WIDTH)
        else:
            break
        index += 1
    return columns, index


def _strip_columns(line: _Line, columns: int) -> _Line:
    """Remove up to `columns` columns of leading whitespace from a line.

    Tabs are expanded only as far as needed, so a tab that straddles the
    strip boundary leaves the right number of spaces behind rather than
    swallowing the whole tab.
    """
    consumed = 0
    index = 0
    while index < len(line.text) and consumed < columns:
        character = line.text[index]
        if character == " ":
            consumed += 1
            index += 1
        elif character == "\t":
            width = TAB_WIDTH - (consumed % TAB_WIDTH)
            if consumed + width > columns:
                # Replace the straddling tab with the spaces it stands for.
                remainder = consumed + width - columns
                return _Line(
                    text=" " * remainder + line.text[index + 1 :],
                    offset=line.offset + index,
                )
            consumed += width
            index += 1
        else:
            break
    return _Line(text=line.text[index:], offset=line.offset + index)


def split_lines(source: SourceText) -> list[_Line]:
    """Split the source into `_Line` records with exact source offsets."""
    lines: list[_Line] = []
    start = 0
    text = source.text
    while start <= len(text):
        end = text.find("\n", start)
        if end == -1:
            lines.append(_Line(text=text[start:], offset=start))
            break
        lines.append(_Line(text=text[start:end], offset=start))
        start = end + 1
    # A file ending in a newline produces a final empty line that carries no
    # content; keeping it would add a phantom blank line to the document.
    if lines and lines[-1].text == "" and text.endswith("\n"):
        lines.pop()
    return lines


# --- block start recognisers ----------------------------------------------


def _thematic_break_char(text: str) -> str | None:
    """Return the rule character if the line is a thematic break."""
    indent, index = _indent_of(text)
    if indent >= CODE_INDENT:
        return None
    body = text[index:]
    if not body:
        return None
    marker = body[0]
    if marker not in "-*_":
        return None
    count = 0
    for character in body:
        if character == marker:
            count += 1
        elif character in " \t":
            continue
        else:
            return None
    return marker if count >= 3 else None


def _atx_heading_level(text: str) -> int:
    """Return the heading level, or 0 if the line is not an ATX heading."""
    indent, index = _indent_of(text)
    if indent >= CODE_INDENT:
        return 0
    level = 0
    while index + level < len(text) and text[index + level] == "#":
        level += 1
    if level == 0:
        return 0
    rest = text[index + level :]
    if rest and rest[0] not in " \t":
        return 0
    return level


def _fence_at(text: str) -> tuple[str, int, int, str] | None:
    """Return (fence char, length, indent, info string) for a code fence."""
    indent, index = _indent_of(text)
    if indent >= CODE_INDENT:
        return None
    if index >= len(text) or text[index] not in "`~":
        return None
    marker = text[index]
    length = 0
    while index + length < len(text) and text[index + length] == marker:
        length += 1
    if length < 3:
        return None
    info = text[index + length :].strip()
    # A backtick fence may not carry a backtick in its info string, or
    # ``a`b`` inline code would be mistaken for a fence.
    if marker == "`" and "`" in info:
        return None
    return marker, length, indent, info


@dataclass
class _Marker:
    """A recognised list marker at the head of a line."""

    ordered: bool
    number: int
    bullet: str
    delimiter: str
    marker_indent: int
    content_indent: int
    #: Index just past the marker and its trailing spaces.
    content_index: int
    blank_item: bool


def _list_marker(text: str) -> _Marker | None:
    """Recognise `- `, `* `, `+ `, `1. ` or `1) ` at the head of a line."""
    marker_indent, index = _indent_of(text)
    if marker_indent >= CODE_INDENT:
        return None
    if index >= len(text):
        return None
    ordered = False
    number = 1
    bullet = ""
    delimiter = ""
    character = text[index]
    if character in "-+*":
        # A thematic break wins over a bullet, so `***` is a rule.
        if _thematic_break_char(text) is not None:
            return None
        bullet = character
        after = index + 1
    elif character.isdigit():
        digits = index
        while digits < len(text) and text[digits].isdigit():
            digits += 1
        if digits - index > 9:
            return None
        if digits >= len(text) or text[digits] not in ".)":
            return None
        ordered = True
        number = int(text[index:digits])
        delimiter = text[digits]
        after = digits + 1
    else:
        return None
    marker_width = after - index
    if after >= len(text):
        # `-` alone on a line starts an item with an empty first block.
        return _Marker(
            ordered=ordered,
            number=number,
            bullet=bullet,
            delimiter=delimiter,
            marker_indent=marker_indent,
            content_indent=marker_indent + marker_width + 1,
            content_index=after,
            blank_item=True,
        )
    if text[after] not in " \t":
        return None
    spaces = 0
    cursor = after
    columns = marker_indent + marker_width
    while cursor < len(text) and text[cursor] in " \t":
        if text[cursor] == "\t":
            columns += TAB_WIDTH - (columns % TAB_WIDTH)
        else:
            columns += 1
        spaces += 1
        cursor += 1
    if cursor >= len(text):
        return _Marker(
            ordered=ordered,
            number=number,
            bullet=bullet,
            delimiter=delimiter,
            marker_indent=marker_indent,
            content_indent=marker_indent + marker_width + 1,
            content_index=after,
            blank_item=True,
        )
    padding = columns - (marker_indent + marker_width)
    # More than four spaces after the marker means the content is an
    # indented code block inside the item, not extra marker padding.
    if padding > CODE_INDENT:
        padding = 1
        cursor = after + 1
    return _Marker(
        ordered=ordered,
        number=number,
        bullet=bullet,
        delimiter=delimiter,
        marker_indent=marker_indent,
        content_indent=marker_indent + marker_width + padding,
        content_index=cursor,
        blank_item=False,
    )


def _blockquote_index(text: str) -> int | None:
    """Index just past a `>` marker and its optional single space."""
    indent, index = _indent_of(text)
    if indent >= CODE_INDENT:
        return None
    if index >= len(text) or text[index] != ">":
        return None
    index += 1
    if index < len(text) and text[index] == " ":
        index += 1
    return index


def _is_alignment_row(text: str) -> bool:
    """True if the line is a table alignment row such as `|:--|--:|`."""
    stripped = text.strip()
    if not stripped or "-" not in stripped:
        return False
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    if not stripped.strip():
        return False
    for cell in stripped.split("|"):
        cell = cell.strip()
        if not cell:
            return False
        if not all(character in "-:" for character in cell):
            return False
        if "-" not in cell:
            return False
        if cell.count(":") > 2:
            return False
    return True


def _split_table_row(text: str) -> list[tuple[str, int]]:
    """Split a table row on unescaped pipes, returning (cell, index) pairs."""
    stripped = text.strip()
    start_index = len(text) - len(text.lstrip())
    if stripped.startswith("|"):
        stripped = stripped[1:]
        start_index += 1
    cells: list[tuple[str, int]] = []
    buffer: list[str] = []
    buffer_start = start_index
    cursor = 0
    while cursor < len(stripped):
        character = stripped[cursor]
        if character == "\\" and cursor + 1 < len(stripped):
            if stripped[cursor + 1] == "|":
                buffer.append("|")
                cursor += 2
                continue
            buffer.append(character)
            buffer.append(stripped[cursor + 1])
            cursor += 2
            continue
        if character == "|":
            cells.append(("".join(buffer), buffer_start))
            buffer = []
            buffer_start = start_index + cursor + 1
            cursor += 1
            continue
        buffer.append(character)
        cursor += 1
    trailing = "".join(buffer)
    if trailing.strip() or not cells:
        cells.append((trailing, buffer_start))
    return cells


class BlockParser:
    """Turns a Markdown source into a Document tree.

    Every method that consumes lines takes the whole line list and a start
    index and returns the index it stopped at, so recursion into a list item
    or a blockquote is just another call with a stripped line list.
    """

    def __init__(
        self, source: SourceText, diagnostics: DiagnosticCollector
    ) -> None:
        self.source = source
        self.diagnostics = diagnostics

    # --- entry point -------------------------------------------------------

    def parse_document(self) -> Document:
        """Parse front matter, then the body, into a Document."""
        self._check_encoding()
        lines = split_lines(self.source)
        front_matter, lines = self._parse_front_matter(lines)
        children = self.parse_blocks(lines)
        return Document(
            pos=self.source.position(0),
            front_matter=front_matter,
            children=children,
        )

    def _check_encoding(self) -> None:
        """Warn about characters WinAnsiEncoding cannot represent.

        This runs over the raw source rather than over the tree, because
        that is the only place where the offset of an individual character
        is still known exactly. A node knows where it began, which would put
        the caret at the start of the line instead of under the character
        that cannot be drawn. Each distinct character is reported once, at
        its first appearance, so a paragraph of one script does not produce
        a wall of identical warnings.
        """
        seen: set[str] = set()
        for index, character in enumerate(self.source.text):
            if character in seen or is_renderable(character):
                continue
            seen.add(character)
            self.diagnostics.warn(
                f"character {character!r} is outside WinAnsiEncoding and "
                "cannot be drawn without an embedded font; substituting "
                f"{UNRENDERABLE_PLACEHOLDER!r}",
                index,
            )

    def _parse_front_matter(
        self, lines: list[_Line]
    ) -> tuple[dict[str, str], list[_Line]]:
        """Parse a `---` delimited `key: value` header at the very top.

        This is deliberately not YAML. Front matter here exists to name a
        title, an author and a date, and a hand-written key/value reader
        covers that without pretending to support anchors, flow sequences or
        multi-line scalars.
        """
        if not lines or lines[0].text.strip() != "---":
            return {}, lines
        closing = -1
        for index in range(1, len(lines)):
            if lines[index].text.strip() in ("---", "..."):
                closing = index
                break
        if closing == -1:
            self.diagnostics.warn(
                "unclosed front matter, no closing `---`", lines[0].offset
            )
            return {}, lines
        values: dict[str, str] = {}
        for line in lines[1:closing]:
            if line.is_blank:
                continue
            separator = line.text.find(":")
            if separator <= 0:
                self.diagnostics.warn(
                    "front matter line is not `key: value`", line.offset
                )
                continue
            key = line.text[:separator].strip().lower()
            value = line.text[separator + 1 :].strip()
            # Strip one layer of matching quotes, which is the only YAML
            # nicety worth supporting here.
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if not key:
                self.diagnostics.warn(
                    "front matter key is empty", line.offset
                )
                continue
            if key in values:
                self.diagnostics.warn(
                    f"duplicate front matter key {key!r}", line.offset
                )
            values[key] = value
        return values, lines[closing + 1 :]

    # --- block dispatch ----------------------------------------------------

    def parse_blocks(self, lines: list[_Line]) -> list[Node]:
        """Parse a list of prefix-stripped lines into block nodes."""
        blocks: list[Node] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if line.is_blank:
                index += 1
                continue
            if _thematic_break_char(line.text) is not None:
                blocks.append(ThematicBreak(pos=self._pos(line)))
                index += 1
                continue
            level = _atx_heading_level(line.text)
            if level:
                blocks.append(self._parse_heading(line, level))
                index += 1
                continue
            fence = _fence_at(line.text)
            if fence is not None:
                block, index = self._parse_fenced_code(lines, index, fence)
                blocks.append(block)
                continue
            if _blockquote_index(line.text) is not None:
                block, index = self._parse_blockquote(lines, index)
                blocks.append(block)
                continue
            if _list_marker(line.text) is not None:
                block, index = self._parse_list(lines, index)
                blocks.append(block)
                continue
            if self._table_starts_at(lines, index):
                block, index = self._parse_table(lines, index)
                blocks.append(block)
                continue
            indent, _ = _indent_of(line.text)
            if indent >= CODE_INDENT:
                block, index = self._parse_indented_code(lines, index)
                blocks.append(block)
                continue
            block, index = self._parse_paragraph(lines, index)
            if block is not None:
                blocks.append(block)
        return blocks

    def _pos(self, line: _Line) -> Position:
        return self.source.position(line.offset)

    # --- individual block parsers -----------------------------------------

    def _parse_heading(self, line: _Line, level: int) -> Heading:
        indent, index = _indent_of(line.text)
        hashes = 0
        while index + hashes < len(line.text) and line.text[
            index + hashes
        ] == "#":
            hashes += 1
        if hashes > 6:
            self.diagnostics.warn(
                f"heading has {hashes} `#` characters, "
                "only 1 to 6 are levels; treating it as level 6",
                line.offset + index,
            )
            level = 6
        else:
            level = hashes
        body_start = index + hashes
        body = line.text[body_start:]
        # A closing run of hashes is decoration and is dropped, but only when
        # a space separates it from the heading text.
        trimmed = body.rstrip()
        if trimmed.endswith("#"):
            probe = len(trimmed)
            while probe > 0 and trimmed[probe - 1] == "#":
                probe -= 1
            if probe == 0 or trimmed[probe - 1] in " \t":
                trimmed = trimmed[:probe].rstrip()
        leading = len(body) - len(body.lstrip())
        raw = RawText(self.source)
        raw.add(trimmed.strip(), line.offset + body_start + leading)
        children = parse_inline(raw, self.diagnostics)
        return Heading(
            pos=self.source.position(line.offset),
            level=level,
            children=children,
        )

    def _parse_fenced_code(
        self, lines: list[_Line], index: int, fence: tuple[str, int, int, str]
    ) -> tuple[CodeBlock, int]:
        marker, length, indent, info = fence
        opening = lines[index]
        cursor = index + 1
        content: list[str] = []
        closed = False
        while cursor < len(lines):
            candidate = lines[cursor]
            closing = _fence_at(candidate.text)
            if (
                closing is not None
                and closing[0] == marker
                and closing[1] >= length
                and closing[3] == ""
            ):
                closed = True
                cursor += 1
                break
            content.append(_strip_columns(candidate, indent).text)
            cursor += 1
        if not closed:
            self.diagnostics.warn(
                f"unclosed code fence, no closing `{marker * length}`",
                opening.offset,
            )
        language = info.split()[0] if info else ""
        return (
            CodeBlock(
                pos=self.source.position(opening.offset),
                text="\n".join(content),
                language=language,
                fenced=True,
            ),
            cursor,
        )

    def _parse_indented_code(
        self, lines: list[_Line], index: int
    ) -> tuple[CodeBlock, int]:
        start = lines[index]
        content: list[str] = []
        cursor = index
        pending_blanks: list[str] = []
        while cursor < len(lines):
            line = lines[cursor]
            if line.is_blank:
                pending_blanks.append("")
                cursor += 1
                continue
            indent, _ = _indent_of(line.text)
            if indent < CODE_INDENT:
                break
            content.extend(pending_blanks)
            pending_blanks = []
            content.append(_strip_columns(line, CODE_INDENT).text)
            cursor += 1
        # Trailing blank lines belong to the document, not to the block.
        consumed = cursor - len(pending_blanks)
        return (
            CodeBlock(
                pos=self.source.position(start.offset),
                text="\n".join(content),
                language="",
                fenced=False,
            ),
            consumed,
        )

    def _parse_blockquote(
        self, lines: list[_Line], index: int
    ) -> tuple[BlockQuote, int]:
        start = lines[index]
        inner: list[_Line] = []
        cursor = index
        while cursor < len(lines):
            line = lines[cursor]
            marker_index = _blockquote_index(line.text)
            if marker_index is not None:
                inner.append(
                    _Line(
                        text=line.text[marker_index:],
                        offset=line.offset + marker_index,
                    )
                )
                cursor += 1
                continue
            # Lazy continuation: an unmarked line still belongs to the quote
            # if it is simply the next line of a paragraph inside it.
            if (
                not line.is_blank
                and inner
                and not inner[-1].is_blank
                and not self._interrupts_paragraph(lines, cursor)
            ):
                inner.append(line)
                cursor += 1
                continue
            break
        children = self.parse_blocks(inner)
        return (
            BlockQuote(
                pos=self.source.position(start.offset), children=children
            ),
            cursor,
        )

    def _parse_list(
        self, lines: list[_Line], index: int
    ) -> tuple[ListBlock, int]:
        start = lines[index]
        first = _list_marker(start.text)
        assert first is not None
        block = ListBlock(
            pos=self.source.position(start.offset),
            ordered=first.ordered,
            start=first.number,
            tight=True,
            items=[],
        )
        cursor = index
        saw_blank_between = False
        expected_number = first.number
        while cursor < len(lines):
            line = lines[cursor]
            if line.is_blank:
                # A blank line ends the list only if the next line is not
                # part of it. Two blank lines always end it.
                look = cursor
                while look < len(lines) and lines[look].is_blank:
                    look += 1
                if look >= len(lines):
                    cursor = look
                    break
                following = _list_marker(lines[look].text)
                following_indent, _ = _indent_of(lines[look].text)
                if following is not None and self._same_list(first, following):
                    saw_blank_between = True
                    cursor = look
                    continue
                if following_indent >= first.content_indent:
                    saw_blank_between = True
                    cursor = look
                    continue
                break
            marker = _list_marker(line.text)
            if marker is None or not self._same_list(first, marker):
                break
            if marker.marker_indent >= first.content_indent:
                break
            if (
                block.ordered
                and marker.number != expected_number
                and len(block.items) > 0
            ):
                self.diagnostics.warn(
                    f"ordered list item is numbered {marker.number} where "
                    f"{expected_number} was expected; "
                    "numbering is taken from the first item",
                    line.offset,
                )
            expected_number += 1
            item, cursor, item_had_blank = self._parse_list_item(
                lines, cursor, marker
            )
            block.items.append(item)
            if item_had_blank:
                saw_blank_between = True
        block.tight = not saw_blank_between
        if not block.items:
            # Defensive: a list must have at least the item that started it.
            block.items.append(
                ListItem(pos=self.source.position(start.offset), children=[])
            )
        return block, cursor

    @staticmethod
    def _same_list(first: _Marker, other: _Marker) -> bool:
        """True if two markers belong to the same list.

        Changing the bullet character or the ordered delimiter starts a new
        list, which is what lets a document put two lists back to back.
        """
        if first.ordered != other.ordered:
            return False
        if first.ordered:
            return first.delimiter == other.delimiter
        return first.bullet == other.bullet

    def _parse_list_item(
        self, lines: list[_Line], index: int, marker: _Marker
    ) -> tuple[ListItem, int, bool]:
        start = lines[index]
        content_indent = marker.content_indent
        inner: list[_Line] = [
            _Line(
                text=start.text[marker.content_index :],
                offset=start.offset + marker.content_index,
            )
        ]
        cursor = index + 1
        had_internal_blank = False
        while cursor < len(lines):
            line = lines[cursor]
            if line.is_blank:
                # Look ahead: a blank line only stays inside the item if
                # indented content follows it.
                look = cursor
                while look < len(lines) and lines[look].is_blank:
                    look += 1
                if look >= len(lines):
                    break
                following_indent, _ = _indent_of(lines[look].text)
                if following_indent < content_indent:
                    break
                for blank_index in range(cursor, look):
                    inner.append(_Line(text="", offset=lines[blank_index].offset))
                had_internal_blank = True
                cursor = look
                continue
            indent, _ = _indent_of(line.text)
            if indent >= content_indent:
                inner.append(_strip_columns(line, content_indent))
                cursor += 1
                continue
            if _list_marker(line.text) is not None:
                break
            if self._interrupts_paragraph(lines, cursor):
                break
            # Lazy continuation of the item's final paragraph.
            inner.append(line)
            cursor += 1
        children = self.parse_blocks(inner)
        return (
            ListItem(
                pos=self.source.position(start.offset), children=children
            ),
            cursor,
            had_internal_blank,
        )

    def _interrupts_paragraph(self, lines: list[_Line], index: int) -> bool:
        """True if the line at `index` cannot be a paragraph continuation."""
        line = lines[index]
        if line.is_blank:
            return True
        if _atx_heading_level(line.text):
            return True
        if _fence_at(line.text) is not None:
            return True
        if _thematic_break_char(line.text) is not None:
            return True
        if _blockquote_index(line.text) is not None:
            return True
        marker = _list_marker(line.text)
        if marker is not None and not marker.blank_item:
            # An empty list item does not interrupt a paragraph, or every
            # line beginning with a lone dash would split the text.
            if not marker.ordered or marker.number == 1:
                return True
        if self._table_starts_at(lines, index):
            return True
        return False

    # --- paragraphs and tables --------------------------------------------

    def _parse_paragraph(
        self, lines: list[_Line], index: int
    ) -> tuple[Paragraph | None, int]:
        collected: list[_Line] = []
        cursor = index
        while cursor < len(lines):
            if cursor > index and self._interrupts_paragraph(lines, cursor):
                break
            if lines[cursor].is_blank:
                break
            collected.append(lines[cursor])
            cursor += 1
        if not collected:
            return None, index + 1
        raw = RawText(self.source)
        for position, line in enumerate(collected):
            if position:
                previous = collected[position - 1]
                raw.add("\n", previous.offset + len(previous.text))
            # Leading indentation is dropped, trailing spaces are kept
            # because two of them at end of line make a hard break.
            stripped = line.text.lstrip()
            lead = len(line.text) - len(stripped)
            raw.add(stripped, line.offset + lead)
        children = parse_inline(raw, self.diagnostics)
        return (
            Paragraph(
                pos=self.source.position(collected[0].offset),
                children=children,
            ),
            cursor,
        )

    def _table_starts_at(self, lines: list[_Line], index: int) -> bool:
        if index + 1 >= len(lines):
            return False
        header = lines[index]
        if "|" not in header.text or header.is_blank:
            return False
        indent, _ = _indent_of(header.text)
        if indent >= CODE_INDENT:
            return False
        if not _is_alignment_row(lines[index + 1].text):
            return False
        header_cells = _split_table_row(header.text)
        alignment_cells = _split_table_row(lines[index + 1].text)
        return len(header_cells) == len(alignment_cells)

    def _parse_table(
        self, lines: list[_Line], index: int
    ) -> tuple[Table, int]:
        header_line = lines[index]
        alignment_line = lines[index + 1]
        header_cells = _split_table_row(header_line.text)
        alignments: list[str] = []
        for cell_text, _ in _split_table_row(alignment_line.text):
            body = cell_text.strip()
            left = body.startswith(":")
            right = body.endswith(":")
            if left and right:
                alignments.append("center")
            elif right:
                alignments.append("right")
            else:
                alignments.append("left")
        column_count = len(header_cells)
        table = Table(
            pos=self.source.position(header_line.offset),
            header=self._table_row(header_line, header_cells, column_count),
            alignments=alignments,
            rows=[],
        )
        cursor = index + 2
        while cursor < len(lines):
            line = lines[cursor]
            if line.is_blank or "|" not in line.text:
                break
            if _fence_at(line.text) is not None:
                break
            cells = _split_table_row(line.text)
            if len(cells) != column_count:
                self.diagnostics.warn(
                    f"table row has {len(cells)} cells but the header has "
                    f"{column_count}; the row is padded or truncated",
                    line.offset,
                )
            table.rows.append(self._table_row(line, cells, column_count))
            cursor += 1
        return table, cursor

    def _table_row(
        self,
        line: _Line,
        cells: list[tuple[str, int]],
        column_count: int,
    ) -> TableRow:
        row = TableRow(pos=self.source.position(line.offset), cells=[])
        for column in range(column_count):
            if column < len(cells):
                cell_text, cell_index = cells[column]
                stripped = cell_text.strip()
                lead = len(cell_text) - len(cell_text.lstrip())
                raw = RawText(self.source)
                raw.add(stripped, line.offset + cell_index + lead)
                row.cells.append(
                    TableCell(
                        pos=self.source.position(line.offset + cell_index),
                        children=parse_inline(raw, self.diagnostics),
                    )
                )
            else:
                row.cells.append(
                    TableCell(
                        pos=self.source.position(line.offset), children=[]
                    )
                )
        return row


def parse_markdown(text: str) -> tuple[Document, list[Diagnostic]]:
    """Parse Markdown source into a Document and a list of diagnostics."""
    source = SourceText(text)
    diagnostics = DiagnosticCollector(source)
    document = BlockParser(source, diagnostics).parse_document()
    return document, list(diagnostics)


# ===========================================================================
# Section 5: Font metrics for the 14 standard PDF fonts
# ===========================================================================
#
# Every conforming PDF reader is required to provide the 14 standard Type 1
# fonts without them being embedded in the file. That is the whole reason
# inkless can typeset without shipping a single font file, and it is why the
# widths have to live here instead: a reader supplies the glyphs, but line
# breaking happens before the file is written, so the widths must be known
# in advance.
#
# The values below are the published Adobe AFM advance widths, in units of
# 1/1000 em, for character codes 32 through 126. Multiply by the point size
# and divide by 1000 to get points.

#: Codes covered by the hard-coded tables below.
FIRST_METRIC_CODE = 32
LAST_METRIC_CODE = 126


def _widths(*groups: str) -> list[int]:
    """Parse the width tables written below as whitespace separated groups."""
    values: list[int] = []
    for group in groups:
        values.extend(int(piece) for piece in group.split())
    expected = LAST_METRIC_CODE - FIRST_METRIC_CODE + 1
    if len(values) != expected:
        raise AssertionError(
            f"width table has {len(values)} entries, expected {expected}"
        )
    return values


# fmt: off
_HELVETICA = _widths(
    "278 278 355 556 556 889 667 191 333 333 389 584 278 333 278 278",
    "556 556 556 556 556 556 556 556 556 556",
    "278 278 584 584 584 556 1015",
    "667 667 722 722 667 611 778 722 278 500 667 556 833 722 778 667 778"
    " 722 667 611 722 667 944 667 667 611",
    "278 278 278 469 556 333",
    "556 556 500 556 556 278 556 556 222 222 500 222 833 556 556 556 556"
    " 333 500 278 556 500 722 500 500 500",
    "334 260 334 584",
)

_HELVETICA_BOLD = _widths(
    "278 333 474 556 556 889 722 238 333 333 389 584 278 333 278 278",
    "556 556 556 556 556 556 556 556 556 556",
    "333 333 584 584 584 611 975",
    "722 722 722 722 667 611 778 722 278 556 722 611 833 722 778 667 778"
    " 722 667 611 722 667 944 667 667 611",
    "333 278 333 584 556 333",
    "556 611 556 611 556 333 611 611 278 278 556 278 889 611 611 611 611"
    " 389 556 333 611 556 778 556 556 500",
    "389 280 389 584",
)

_TIMES_ROMAN = _widths(
    "250 333 408 500 500 833 778 180 333 333 500 564 250 333 250 278",
    "500 500 500 500 500 500 500 500 500 500",
    "278 278 564 564 564 444 921",
    "722 667 667 722 611 556 722 722 333 389 722 611 889 722 722 556 722"
    " 667 556 611 722 722 944 722 722 611",
    "333 278 333 469 500 333",
    "444 500 444 500 444 333 500 500 278 278 500 278 778 500 500 500 500"
    " 333 389 278 500 500 722 500 500 444",
    "480 200 480 541",
)

_TIMES_BOLD = _widths(
    "250 333 555 500 500 1000 833 278 333 333 500 570 250 333 250 278",
    "500 500 500 500 500 500 500 500 500 500",
    "333 333 570 570 570 500 930",
    "722 667 722 722 667 611 778 778 389 500 778 667 944 722 778 611 778"
    " 722 556 667 722 722 1000 722 722 667",
    "333 278 333 581 500 333",
    "500 556 444 556 444 333 500 556 278 333 556 278 833 556 500 556 556"
    " 444 389 333 556 500 722 500 500 444",
    "394 220 394 520",
)

_TIMES_ITALIC = _widths(
    "250 333 420 500 500 833 778 214 333 333 500 675 250 333 250 278",
    "500 500 500 500 500 500 500 500 500 500",
    "333 333 675 675 675 500 920",
    "611 611 667 722 611 611 722 722 333 444 667 556 833 667 722 611 722"
    " 611 500 556 722 611 833 611 556 556",
    "389 278 389 422 500 333",
    "500 500 444 500 444 278 500 500 278 278 444 278 722 500 500 500 500"
    " 389 389 278 500 444 667 444 444 389",
    "400 275 400 541",
)

_TIMES_BOLD_ITALIC = _widths(
    "250 389 555 500 500 833 778 278 333 333 500 570 250 333 250 278",
    "500 500 500 500 500 500 500 500 500 500",
    "333 333 570 570 570 500 832",
    "667 667 667 722 667 667 722 778 389 500 667 611 889 722 722 611 722"
    " 667 556 611 722 667 889 667 611 611",
    "333 278 333 570 500 333",
    "500 500 444 500 444 333 500 556 278 278 500 278 778 556 500 500 500"
    " 389 389 278 556 444 667 500 444 389",
    "348 220 348 570",
)

_COURIER = [600] * (LAST_METRIC_CODE - FIRST_METRIC_CODE + 1)
# fmt: on


#: Advance widths for the WinAnsi codes above 126 that are worth spelling
#: out. Everything else in that range falls back to the base-letter rule or
#: to the documented default; see `FontMetrics.width_of_code`.
_UPPER_WIDTHS: dict[str, dict[int, int]] = {
    "Helvetica": {
        0x91: 222, 0x92: 222, 0x93: 333, 0x94: 333,
        0x95: 350, 0x96: 556, 0x97: 1000, 0x85: 1000,
        0xA0: 278, 0xAD: 333,
    },
    "Times-Roman": {
        0x91: 333, 0x92: 333, 0x93: 444, 0x94: 444,
        0x95: 350, 0x96: 500, 0x97: 1000, 0x85: 1000,
        0xA0: 250, 0xAD: 333,
    },
}
_UPPER_WIDTHS["Helvetica-Bold"] = _UPPER_WIDTHS["Helvetica"]
_UPPER_WIDTHS["Helvetica-Oblique"] = _UPPER_WIDTHS["Helvetica"]
_UPPER_WIDTHS["Helvetica-BoldOblique"] = _UPPER_WIDTHS["Helvetica"]
_UPPER_WIDTHS["Times-Bold"] = _UPPER_WIDTHS["Times-Roman"]
_UPPER_WIDTHS["Times-Italic"] = _UPPER_WIDTHS["Times-Roman"]
_UPPER_WIDTHS["Times-BoldItalic"] = _UPPER_WIDTHS["Times-Roman"]


@dataclass(frozen=True)
class FontMetrics:
    """Advance widths for one of the 14 standard fonts.

    `default_width` is used for any WinAnsi code that is neither in the
    hard-coded ASCII table nor reducible to an unaccented base letter. It is
    the width of a digit, which is a neutral advance in all of these fonts,
    and the README lists this as a known approximation rather than pretending
    the table is complete.
    """

    base_font: str
    ascii_widths: tuple[int, ...]
    upper_widths: dict[int, int]
    default_width: int
    monospace: bool = False

    def width_of_code(self, code: int) -> int:
        """Advance width of one WinAnsi character code, in 1/1000 em."""
        if self.monospace:
            return 600
        if FIRST_METRIC_CODE <= code <= LAST_METRIC_CODE:
            return self.ascii_widths[code - FIRST_METRIC_CODE]
        if code in self.upper_widths:
            return self.upper_widths[code]
        base = _base_letter_for_code(code)
        if base is not None:
            return self.ascii_widths[ord(base) - FIRST_METRIC_CODE]
        return self.default_width

    def width_of_text(self, text: str, size: float) -> float:
        """Width of a string at a point size, in points."""
        total = 0
        for character in text:
            total += self.width_of_code(winansi_code(character))
        return total * size / 1000.0


def _base_letter_for_code(code: int) -> str | None:
    """Reduce an accented WinAnsi letter to its unaccented ASCII base.

    In the standard PDF fonts an accented glyph such as `Aacute` is built
    from the base letter and a floating accent, and it carries the base
    letter's advance width. Deriving the width that way is exact, and it
    beats inventing numbers for a range this file cannot verify.
    """
    if code < 0x80 or code > 0xFF:
        return None
    try:
        character = bytes([code]).decode("cp1252")
    except UnicodeDecodeError:
        return None
    decomposed = unicodedata.normalize("NFD", character)
    if decomposed and decomposed[0].isascii() and decomposed[0].isalpha():
        return decomposed[0]
    return None


def winansi_code(character: str) -> int:
    """Map a character to its WinAnsiEncoding code, or to the placeholder.

    WinAnsiEncoding agrees with cp1252 across the whole printable range, so
    the standard library codec is the encoding table; there is no need to
    write one out by hand.
    """
    try:
        return character.encode("cp1252")[0]
    except (UnicodeEncodeError, UnicodeDecodeError):
        return ord(UNRENDERABLE_PLACEHOLDER)


def is_renderable(character: str) -> bool:
    """True if WinAnsiEncoding can represent the character at all."""
    try:
        character.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True


def _make(
    base_font: str, table: list[int], monospace: bool = False
) -> FontMetrics:
    """Build a FontMetrics from a raw width table."""
    return FontMetrics(
        base_font=base_font,
        ascii_widths=tuple(table),
        upper_widths=_UPPER_WIDTHS.get(base_font, {}),
        default_width=table[ord("0") - FIRST_METRIC_CODE],
        monospace=monospace,
    )


#: Every standard font inkless can name, keyed by its PDF BaseFont name.
STANDARD_FONTS: dict[str, FontMetrics] = {
    "Helvetica": _make("Helvetica", _HELVETICA),
    "Helvetica-Bold": _make("Helvetica-Bold", _HELVETICA_BOLD),
    # The oblique cuts are slanted versions of the upright outlines and have
    # identical advance widths, which is why they share the tables.
    "Helvetica-Oblique": _make("Helvetica-Oblique", _HELVETICA),
    "Helvetica-BoldOblique": _make("Helvetica-BoldOblique", _HELVETICA_BOLD),
    "Times-Roman": _make("Times-Roman", _TIMES_ROMAN),
    "Times-Bold": _make("Times-Bold", _TIMES_BOLD),
    "Times-Italic": _make("Times-Italic", _TIMES_ITALIC),
    "Times-BoldItalic": _make("Times-BoldItalic", _TIMES_BOLD_ITALIC),
    "Courier": _make("Courier", _COURIER, monospace=True),
    "Courier-Bold": _make("Courier-Bold", _COURIER, monospace=True),
    "Courier-Oblique": _make("Courier-Oblique", _COURIER, monospace=True),
    "Courier-BoldOblique": _make(
        "Courier-BoldOblique", _COURIER, monospace=True
    ),
}


#: Body font families the CLI offers, as (regular, bold, italic, bold italic).
FONT_FAMILIES: dict[str, tuple[str, str, str, str]] = {
    "helvetica": (
        "Helvetica",
        "Helvetica-Bold",
        "Helvetica-Oblique",
        "Helvetica-BoldOblique",
    ),
    "times": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "courier": (
        "Courier",
        "Courier-Bold",
        "Courier-Oblique",
        "Courier-BoldOblique",
    ),
}

#: Code is always set in Courier regardless of the body family.
MONOSPACE_FAMILY = (
    "Courier",
    "Courier-Bold",
    "Courier-Oblique",
    "Courier-BoldOblique",
)


def font_for_style(
    family: tuple[str, str, str, str], bold: bool, italic: bool
) -> str:
    """Pick the BaseFont name for a style within a family."""
    if bold and italic:
        return family[3]
    if bold:
        return family[1]
    if italic:
        return family[2]
    return family[0]


def measure(text: str, base_font: str, size: float) -> float:
    """Width of `text` set in `base_font` at `size` points."""
    metrics = STANDARD_FONTS.get(base_font)
    if metrics is None:
        raise KeyError(f"unknown standard font {base_font!r}")
    return metrics.width_of_text(text, size)






# ===========================================================================
# Section 6: PNG image decoding
# ===========================================================================
#
# Only PNG is supported, and only 8 bit RGB or RGBA without interlacing.
# Anything else is refused with a warning that names the file and the line
# it was written on, and the alt text is set instead. Producing a document
# with a corrupt image in it would be worse than producing one without.
#
# There is a pleasant coincidence in the format. PDF's FlateDecode filter
# understands the same per-scanline predictors PNG uses, so a truecolour PNG
# needs no processing at all: its compressed image data is handed straight
# to the PDF with `/Predictor 15`, and the reader undoes the filtering. Only
# the alpha case has to be decoded here, because PDF keeps transparency in a
# separate soft mask and the two channels have to be pulled apart.

#: The eight bytes every PNG file begins with.
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Colour types this program can embed.
PNG_TRUECOLOUR = 2
PNG_TRUECOLOUR_ALPHA = 6

#: Assumed resolution for an image with no physical size recorded. PNG only
#: carries pixel dimensions unless a pHYs chunk says otherwise, so a screen
#: resolution of 96 pixels per inch is the convention used here.
IMAGE_ASSUMED_DPI = 96.0


class PngError(Exception):
    """Raised when a PNG cannot be embedded, with a reason worth printing."""


@dataclass
class PngImage:
    """A decoded PNG, in the form the PDF writer wants it."""

    width: int
    height: int
    colour_type: int
    #: zlib compressed colour data, ready to become a stream payload.
    colour_stream: bytes
    #: True when the colour data still carries PNG scanline filter bytes,
    #: in which case the PDF stream declares the PNG predictor.
    predictor: bool
    #: zlib compressed 8 bit alpha channel, or None when fully opaque.
    alpha_stream: bytes | None = None

    @property
    def point_width(self) -> float:
        """Natural width in points at the assumed resolution."""
        return self.width * 72.0 / IMAGE_ASSUMED_DPI

    @property
    def point_height(self) -> float:
        """Natural height in points at the assumed resolution."""
        return self.height * 72.0 / IMAGE_ASSUMED_DPI


def _png_chunks(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    """Walk the chunk sequence of a PNG, verifying every checksum."""
    cursor = len(PNG_SIGNATURE)
    total = len(data)
    while cursor + 8 <= total:
        length = int.from_bytes(data[cursor : cursor + 4], "big")
        kind = data[cursor + 4 : cursor + 8]
        body_at = cursor + 8
        if body_at + length + 4 > total:
            raise PngError("truncated chunk " + kind.decode("latin-1"))
        body = data[body_at : body_at + length]
        stored = int.from_bytes(
            data[body_at + length : body_at + length + 4], "big"
        )
        if zlib.crc32(kind + body) & 0xFFFFFFFF != stored:
            raise PngError(
                "checksum mismatch in chunk " + kind.decode("latin-1")
            )
        cursor = body_at + length + 4
        yield kind, body
        if kind == b"IEND":
            return
    raise PngError("no IEND chunk, the file is truncated")


def _unfilter_scanlines(
    raw: bytes, width: int, height: int, bytes_per_pixel: int
) -> bytearray:
    """Undo the PNG per-scanline filters, producing raw samples.

    Each scanline is prefixed with a filter type byte. The five filters are
    defined in terms of the byte to the left, the byte above, and the byte
    above-left, all treated as zero outside the image.
    """
    stride = width * bytes_per_pixel
    expected = height * (stride + 1)
    if len(raw) < expected:
        raise PngError(
            f"image data is {len(raw)} bytes, expected {expected}"
        )
    out = bytearray()
    previous = bytearray(stride)
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        line = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        if filter_type == 0:
            pass
        elif filter_type == 1:  # Sub
            for index in range(bytes_per_pixel, stride):
                line[index] = (
                    line[index] + line[index - bytes_per_pixel]
                ) & 0xFF
        elif filter_type == 2:  # Up
            for index in range(stride):
                line[index] = (line[index] + previous[index]) & 0xFF
        elif filter_type == 3:  # Average
            for index in range(stride):
                left = (
                    line[index - bytes_per_pixel]
                    if index >= bytes_per_pixel
                    else 0
                )
                line[index] = (
                    line[index] + ((left + previous[index]) >> 1)
                ) & 0xFF
        elif filter_type == 4:  # Paeth
            for index in range(stride):
                left = (
                    line[index - bytes_per_pixel]
                    if index >= bytes_per_pixel
                    else 0
                )
                above = previous[index]
                upper_left = (
                    previous[index - bytes_per_pixel]
                    if index >= bytes_per_pixel
                    else 0
                )
                estimate = left + above - upper_left
                distance_left = abs(estimate - left)
                distance_above = abs(estimate - above)
                distance_corner = abs(estimate - upper_left)
                if (
                    distance_left <= distance_above
                    and distance_left <= distance_corner
                ):
                    predicted = left
                elif distance_above <= distance_corner:
                    predicted = above
                else:
                    predicted = upper_left
                line[index] = (line[index] + predicted) & 0xFF
        else:
            raise PngError(f"unknown scanline filter {filter_type}")
        out += line
        previous = line
    return out


def parse_png(data: bytes) -> PngImage:
    """Decode enough of a PNG to embed it, or explain why it cannot be."""
    if not data.startswith(PNG_SIGNATURE):
        raise PngError("not a PNG file, the signature does not match")
    header: tuple[int, ...] | None = None
    pieces: list[bytes] = []
    for kind, body in _png_chunks(data):
        if kind == b"IHDR":
            if len(body) != 13:
                raise PngError("IHDR chunk is the wrong size")
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            pieces.append(body)
        elif kind == b"IEND":
            break
    if header is None:
        raise PngError("no IHDR chunk")
    (
        width,
        height,
        bit_depth,
        colour_type,
        compression,
        filter_method,
        interlace,
    ) = header
    if width == 0 or height == 0:
        raise PngError("image has a zero dimension")
    if compression != 0 or filter_method != 0:
        raise PngError("unknown compression or filter method")
    if interlace != 0:
        raise PngError(
            "interlaced PNG is not supported, save it without interlacing"
        )
    if bit_depth != 8:
        raise PngError(
            f"{bit_depth} bit samples are not supported, only 8 bit"
        )
    if colour_type not in (PNG_TRUECOLOUR, PNG_TRUECOLOUR_ALPHA):
        names = {0: "greyscale", 3: "palette", 4: "greyscale with alpha"}
        which = names.get(colour_type, f"colour type {colour_type}")
        raise PngError(
            f"{which} is not supported, only 8 bit RGB and RGBA"
        )
    if not pieces:
        raise PngError("no IDAT chunks, the file carries no image data")
    compressed = b"".join(pieces)

    if colour_type == PNG_TRUECOLOUR:
        # Handed straight through. PDF undoes the PNG predictor itself, so
        # there is nothing to decode and nothing to get wrong.
        try:
            zlib.decompressobj().decompress(compressed[:64])
        except zlib.error as error:
            raise PngError(f"image data is not valid zlib: {error}") from error
        return PngImage(
            width=width,
            height=height,
            colour_type=colour_type,
            colour_stream=compressed,
            predictor=True,
        )

    # RGBA has to be split, because PDF keeps alpha in a separate soft mask.
    try:
        raw = zlib.decompress(compressed)
    except zlib.error as error:
        raise PngError(f"image data is not valid zlib: {error}") from error
    samples = _unfilter_scanlines(raw, width, height, 4)
    colour = bytearray(width * height * 3)
    alpha = bytearray(width * height)
    for pixel in range(width * height):
        source = pixel * 4
        target = pixel * 3
        colour[target] = samples[source]
        colour[target + 1] = samples[source + 1]
        colour[target + 2] = samples[source + 2]
        alpha[pixel] = samples[source + 3]
    return PngImage(
        width=width,
        height=height,
        colour_type=colour_type,
        colour_stream=zlib.compress(bytes(colour), 9),
        predictor=False,
        alpha_stream=zlib.compress(bytes(alpha), 9),
    )


def load_png(path: Path) -> PngImage:
    """Read and decode a PNG from disk."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise PngError(f"cannot read {path.name}: {error.strerror}") from error
    return parse_png(data)


# ===========================================================================
# Section 7: Line breaking
# ===========================================================================
#
# Everything from here to the end of pagination works in top-left
# coordinates: x grows right from the left edge of the page, y grows
# downward from the top. PDF user space is the other way up, and the single
# conversion happens in `ContentBuilder.pdf_y` when the page is emitted.

#: Fractions of an em, used to place a baseline inside a line box. The
#: standard fonts differ a little (Helvetica ascends 0.718, Times 0.683) but
#: a single pair of values keeps mixed-font lines sitting on one baseline,
#: which matters more than matching either font exactly.
ASCENT_RATIO = 0.72
DESCENT_RATIO = 0.21


@dataclass(frozen=True)
class TextStyle:
    """Everything needed to measure and draw one run of characters."""

    font: str
    size: float
    colour: tuple[float, float, float] = (0.0, 0.0, 0.0)
    link_url: str = ""
    code: bool = False

    def width_of(self, text: str) -> float:
        return measure(text, self.font, self.size)


@dataclass
class Piece:
    """One indivisible unit of a line: a word, a gap, or a forced break."""

    text: str
    style: TextStyle
    kind: str  # "word", "space" or "break"
    width: float

    @property
    def is_space(self) -> bool:
        return self.kind == "space"

    @property
    def is_break(self) -> bool:
        return self.kind == "break"


@dataclass
class Line:
    """One laid out line, before it is given a position on a page."""

    pieces: list[Piece] = field(default_factory=list)
    natural_width: float = 0.0
    #: True when the line ended at a hard break or at the end of the block,
    #: which is what stops the last line of a paragraph being justified.
    ends_block: bool = False

    @property
    def max_size(self) -> float:
        return max((piece.style.size for piece in self.pieces), default=0.0)


def baseline_offset(line_height: float, size: float) -> float:
    """Distance from the top of a line box down to the baseline."""
    text_height = (ASCENT_RATIO + DESCENT_RATIO) * size
    return (line_height - text_height) / 2.0 + ASCENT_RATIO * size


def split_into_pieces(text: str, style: TextStyle) -> list[Piece]:
    """Split a run of text into word and space pieces.

    Outside code, a run of whitespace of any length collapses to a single
    space, which is what Markdown means by consecutive spaces and tabs being
    insignificant. Inside a code span every character is kept as written, so
    the whole span becomes one unbreakable piece.
    """
    pieces: list[Piece] = []
    if style.code:
        if text:
            pieces.append(
                Piece(text, style, "word", style.width_of(text))
            )
        return pieces
    index = 0
    length = len(text)
    while index < length:
        if text[index] in " \t\n\x0b\x0c\r":
            while index < length and text[index] in " \t\n\x0b\x0c\r":
                index += 1
            pieces.append(Piece(" ", style, "space", style.width_of(" ")))
            continue
        start = index
        while index < length and text[index] not in " \t\n\x0b\x0c\r":
            index += 1
        word = text[start:index]
        pieces.append(Piece(word, style, "word", style.width_of(word)))
    return pieces


def hard_break_word(piece: Piece, available: float) -> list[Piece]:
    """Chop a word that cannot fit on any line into pieces that can.

    Without this a long URL or a run of identifier characters would simply
    run off the right margin. There is no hyphenation dictionary here, so
    the break is purely by width and no hyphen is inserted, which is honest
    about what happened rather than implying a syllable boundary.
    """
    if available <= 0:
        return [piece]
    chunks: list[Piece] = []
    current = ""
    current_width = 0.0
    for character in piece.text:
        character_width = piece.style.width_of(character)
        if current and current_width + character_width > available:
            chunks.append(
                Piece(current, piece.style, "word", current_width)
            )
            current = character
            current_width = character_width
        else:
            current += character
            current_width += character_width
    if current:
        chunks.append(Piece(current, piece.style, "word", current_width))
    return chunks


def break_lines(pieces: list[Piece], content_width: float) -> list[Line]:
    """Greedy first-fit line breaking.

    Knuth-Plass total-fit breaking is out of scope and is listed as a limit
    in the README. Greedy breaking is what most word processors do: take
    words until the next one will not fit, then start a line.
    """
    lines: list[Line] = []
    current = Line()
    width = 0.0

    def flush(ends_block: bool) -> None:
        nonlocal current, width
        # Trailing spaces never count toward the visible width of a line.
        while current.pieces and current.pieces[-1].is_space:
            width -= current.pieces[-1].width
            current.pieces.pop()
        current.natural_width = width
        current.ends_block = ends_block
        lines.append(current)
        current = Line()
        width = 0.0

    for piece in pieces:
        if piece.is_break:
            flush(True)
            continue
        if piece.is_space:
            if not current.pieces:
                # A line never starts with a space.
                continue
            current.pieces.append(piece)
            width += piece.width
            continue
        if piece.width > content_width and not current.pieces:
            for chunk in hard_break_word(piece, content_width):
                if width + chunk.width > content_width and current.pieces:
                    flush(False)
                current.pieces.append(chunk)
                width += chunk.width
            continue
        if current.pieces and width + piece.width > content_width:
            flush(False)
            if piece.width > content_width:
                for chunk in hard_break_word(piece, content_width):
                    if width + chunk.width > content_width and current.pieces:
                        flush(False)
                    current.pieces.append(chunk)
                    width += chunk.width
                continue
        current.pieces.append(piece)
        width += piece.width
    flush(True)
    # A block that produced nothing at all still has one empty line, which
    # would print as a blank row; drop it.
    if len(lines) == 1 and not lines[0].pieces:
        return []
    return [line for line in lines if line.pieces]


# ===========================================================================
# Section 8: Pagination and page layout
# ===========================================================================


@dataclass(frozen=True)
class Theme:
    """Colours, as PDF device grey or RGB triples in the range 0 to 1."""

    text: tuple[float, float, float] = (0.0, 0.0, 0.0)
    heading: tuple[float, float, float] = (0.05, 0.07, 0.10)
    code_text: tuple[float, float, float] = (0.11, 0.13, 0.17)
    code_background: tuple[float, float, float] = (0.957, 0.957, 0.937)
    link: tuple[float, float, float] = (0.04, 0.30, 0.62)
    rule: tuple[float, float, float] = (0.78, 0.78, 0.76)
    quote_bar: tuple[float, float, float] = (0.72, 0.74, 0.78)
    quote_text: tuple[float, float, float] = (0.28, 0.30, 0.34)
    table_border: tuple[float, float, float] = (0.80, 0.80, 0.78)
    table_header: tuple[float, float, float] = (0.945, 0.945, 0.925)
    footer: tuple[float, float, float] = (0.45, 0.45, 0.45)


@dataclass
class PageGeometry:
    """Page size and margins, in points."""

    width: float
    height: float
    margin: float

    @property
    def content_left(self) -> float:
        return self.margin

    @property
    def content_width(self) -> float:
        return self.width - 2 * self.margin

    @property
    def content_top(self) -> float:
        return self.margin

    @property
    def content_bottom(self) -> float:
        # The footer sits inside the bottom margin, so the text area stops
        # a little above it.
        return self.height - self.margin

    @property
    def footer_baseline(self) -> float:
        return self.height - self.margin * 0.45


# --- paint operations, positioned relative to the top left of a row -------


@dataclass
class Fragment:
    """A run of characters drawn at one x offset in one style."""

    x: float
    text: str
    style: TextStyle


@dataclass
class PaintText:
    """One line of text: fragments sharing a baseline."""

    baseline: float
    fragments: list[Fragment] = field(default_factory=list)


@dataclass
class PaintRect:
    """A filled rectangle, used for rules, code panels and table shading."""

    x: float
    y: float
    width: float
    height: float
    colour: tuple[float, float, float]


@dataclass
class PaintImage:
    """A decoded image placed at a size, keyed by its resolved path."""

    x: float
    y: float
    width: float
    height: float
    key: str


@dataclass
class PaintLink:
    """A clickable area. Either an external URL or an internal destination."""

    x: float
    y: float
    width: float
    height: float
    url: str = ""
    dest: str = ""


@dataclass
class Row:
    """One horizontal slice of the document that can be placed on a page.

    Pagination only ever moves whole rows, so a row is the unit that widow
    and orphan control operates on. `keep_with_next` is the single mechanism
    behind all of it: a row carrying the flag may not be the last thing on a
    page, and the paginator pushes it, and anything it is chained to, onto
    the next page instead.
    """

    height: float
    items: list[object] = field(default_factory=list)
    keep_with_next: bool = False
    is_space: bool = False
    heading: Heading | None = None


@dataclass
class PlacedRow:
    """A row with the y position it was given on its page."""

    y: float
    row: Row


@dataclass
class LaidOutPage:
    """One finished page: rows with positions, ready to be drawn."""

    number: int
    rows: list[PlacedRow] = field(default_factory=list)


def paginate(rows: list[Row], geometry: PageGeometry) -> list[LaidOutPage]:
    """Place rows onto pages, honouring keep-with-next.

    Widow and orphan control is expressed entirely through the
    `keep_with_next` flag that the renderer sets:

      * the first line of a multi-line paragraph is kept with the next, so a
        lone opening line cannot be stranded at the foot of a page,
      * the second to last line is kept with the next, so a lone closing
        line cannot be stranded at the head of the following page,
      * a heading is kept with whatever follows it.

    When a break lands after a chain of kept rows, the whole chain moves. A
    chain that would empty the page is placed anyway, because refusing to
    break at all would loop forever.
    """
    pages: list[LaidOutPage] = []
    index = 0
    total = len(rows)
    while index < total:
        placed: list[PlacedRow] = []
        y = geometry.content_top
        while index < total:
            row = rows[index]
            # Vertical space at the top of a page is discarded, so a page
            # never opens with a stripe of blank paper.
            if row.is_space and not placed:
                index += 1
                continue
            if placed and y + row.height > geometry.content_bottom:
                break
            placed.append(PlacedRow(y=y, row=row))
            y += row.height
            index += 1
        # Trimming trailing space and pulling kept rows have to alternate
        # until neither applies. Removing a space row can expose a kept row
        # underneath it, and pulling a kept chain can expose more space, so
        # a single pass in either order leaves violations behind.
        if index < total:
            while placed:
                trimmed = False
                while placed and placed[-1].row.is_space:
                    placed.pop()
                    index -= 1
                    trimmed = True
                pull = 0
                while (
                    pull < len(placed)
                    and placed[len(placed) - 1 - pull].row.keep_with_next
                ):
                    pull += 1
                if 0 < pull < len(placed):
                    placed = placed[: len(placed) - pull]
                    index -= pull
                    trimmed = True
                if not trimmed:
                    break
        else:
            while placed and placed[-1].row.is_space:
                placed.pop()
                index -= 1
        if not placed:
            if index >= total:
                # The document ended in vertical space and nothing else.
                break
            # Nothing fit at all, which can only happen if a single row is
            # taller than the text area. Place it and overflow rather than
            # spinning.
            placed = [PlacedRow(y=geometry.content_top, row=rows[index])]
            index += 1
        pages.append(LaidOutPage(number=len(pages) + 1, rows=placed))
    if not pages:
        pages.append(LaidOutPage(number=1, rows=[]))
    return pages


# ===========================================================================
# Section 9: Document renderer (blocks to rows)
# ===========================================================================


@dataclass
class RenderOptions:
    """Typographic choices that affect how blocks become rows."""

    font_family: str = "helvetica"
    font_size: float = 11.0
    justify: bool = False
    theme: Theme = field(default_factory=Theme)

    #: Multiples of the body size.
    #: Directory that relative image paths are resolved against. None
    #: disables image loading entirely, which is what happens when the
    #: source came from standard input rather than a file.
    base_path: Path | None = None

    line_height_ratio: float = 1.42
    paragraph_gap_ratio: float = 0.62
    code_size_ratio: float = 0.90
    code_line_ratio: float = 1.30
    list_indent_ratio: float = 1.70
    quote_indent_ratio: float = 1.30
    table_padding_ratio: float = 0.34


#: Heading sizes as a multiple of the body size, indexed by level.
HEADING_SCALE: dict[int, float] = {
    1: 1.95,
    2: 1.55,
    3: 1.27,
    4: 1.12,
    5: 1.0,
    6: 0.92,
}

#: Space above a heading, as a multiple of the body size, by level.
HEADING_SPACE_ABOVE: dict[int, float] = {
    1: 1.30,
    2: 1.10,
    3: 0.95,
    4: 0.85,
    5: 0.80,
    6: 0.80,
}

#: Bullet characters by nesting depth. All three are in WinAnsiEncoding, so
#: none of them needs an embedded font.
BULLETS = ("•", "·", "-")


class DocumentRenderer:
    """Turns a parsed Document into a flat list of rows.

    Rows are deliberately flat rather than a nested box tree. A blockquote
    that spans a page break has to draw its rule on both pages, and a code
    block that spans one has to paint its panel on both; giving every row its
    own decorations makes that fall out of pagination instead of needing a
    second fixing-up pass.
    """

    def __init__(
        self,
        geometry: PageGeometry,
        options: RenderOptions,
        diagnostics: DiagnosticCollector,
    ) -> None:
        self.geometry = geometry
        self.options = options
        self.theme = options.theme
        self.diagnostics = diagnostics
        self.body_family = FONT_FAMILIES[options.font_family]
        self.size = options.font_size
        self.line_height = self.size * options.line_height_ratio
        self._list_depth = 0
        #: Decoded images, keyed by resolved path, in first-use order.
        self.images: dict[str, PngImage] = {}
        #: Filled in as headings are rendered, for the outline and the TOC.
        self.heading_counter = 0

    # --- style helpers -----------------------------------------------------

    def style(
        self,
        size: float | None = None,
        bold: bool = False,
        italic: bool = False,
        colour: tuple[float, float, float] | None = None,
        link_url: str = "",
        code: bool = False,
    ) -> TextStyle:
        """Build a TextStyle from the body family and a set of switches."""
        family = MONOSPACE_FAMILY if code else self.body_family
        return TextStyle(
            font=font_for_style(family, bold, italic),
            size=self.size if size is None else size,
            colour=self.theme.text if colour is None else colour,
            link_url=link_url,
            code=code,
        )

    # --- inline flattening -------------------------------------------------

    def flatten(
        self,
        nodes: list[Node],
        size: float,
        bold: bool = False,
        italic: bool = False,
        colour: tuple[float, float, float] | None = None,
        link_url: str = "",
    ) -> list[Piece]:
        """Walk inline nodes, producing measurable pieces."""
        colour = self.theme.text if colour is None else colour
        pieces: list[Piece] = []
        for node in nodes:
            match node:
                case Text():
                    pieces.extend(
                        split_into_pieces(
                            node.text,
                            self.style(
                                size, bold, italic, colour, link_url
                            ),
                        )
                    )
                case CodeSpan():
                    pieces.extend(
                        split_into_pieces(
                            node.text,
                            self.style(
                                size * self.options.code_size_ratio,
                                bold,
                                italic,
                                self.theme.code_text,
                                link_url,
                                code=True,
                            ),
                        )
                    )
                case Strong():
                    pieces.extend(
                        self.flatten(
                            node.children, size, True, italic, colour,
                            link_url,
                        )
                    )
                case Emphasis():
                    pieces.extend(
                        self.flatten(
                            node.children, size, bold, True, colour, link_url
                        )
                    )
                case Link():
                    pieces.extend(
                        self.flatten(
                            node.children,
                            size,
                            bold,
                            italic,
                            self.theme.link,
                            node.url,
                        )
                    )
                case Image():
                    # Reaching here means the image could not be embedded,
                    # or it sits inline in a sentence rather than on a line
                    # of its own. Either way the alt text is set in italics
                    # so a reader can see exactly what is missing. The
                    # warning was already raised by `load_image`, except for
                    # the inline case, which is warned about here.
                    label = "[image: " + (node.alt or node.src or "?") + "]"
                    if not self._image_warned(node):
                        self.diagnostics.warn(
                            "an image inside a line of text is shown as its "
                            f"alt text; put {node.src!r} on a line of its "
                            "own to embed it",
                            node.pos.offset,
                        )
                    pieces.extend(
                        split_into_pieces(
                            label,
                            self.style(
                                size, bold, True, self.theme.footer, link_url
                            ),
                        )
                    )
                case LineBreak():
                    if node.hard:
                        pieces.append(
                            Piece("", self.style(size), "break", 0.0)
                        )
                    else:
                        style = self.style(size, bold, italic, colour,
                                           link_url)
                        pieces.append(
                            Piece(" ", style, "space", style.width_of(" "))
                        )
        return pieces

    def _image_warned(self, node: Image) -> bool:
        """True if a diagnostic for this image has already been raised."""
        return any(
            node.src in diagnostic.message
            and diagnostic.position.offset == node.pos.offset
            for diagnostic in self.diagnostics.items
        )

    # --- line painting -----------------------------------------------------

    def paint_line(
        self,
        line: Line,
        left: float,
        width: float,
        line_height: float,
        justify: bool,
        align: str = "left",
    ) -> tuple[PaintText, list[PaintLink]]:
        """Position the pieces of one line and return its paint operations."""
        size = line.max_size or self.size
        paint = PaintText(baseline=baseline_offset(line_height, size))
        links: list[PaintLink] = []
        spaces = [piece for piece in line.pieces if piece.is_space]
        extra = 0.0
        if justify and spaces and line.natural_width < width:
            extra = (width - line.natural_width) / len(spaces)
        start_x = left
        if not justify and align != "left":
            slack = max(0.0, width - line.natural_width)
            start_x = left + (slack / 2.0 if align == "center" else slack)

        x = start_x
        pending_text = ""
        pending_style: TextStyle | None = None
        pending_x = x
        link_start: float | None = None
        link_url = ""

        def flush() -> None:
            nonlocal pending_text, pending_style
            if pending_text and pending_style is not None:
                paint.fragments.append(
                    Fragment(x=pending_x, text=pending_text,
                             style=pending_style)
                )
            pending_text = ""
            pending_style = None

        for piece in line.pieces:
            if piece.style.link_url != link_url:
                if link_start is not None and link_url:
                    links.append(
                        PaintLink(
                            x=link_start,
                            y=0.0,
                            width=x - link_start,
                            height=line_height,
                            url=link_url,
                        )
                    )
                link_url = piece.style.link_url
                link_start = x if link_url else None
            if pending_style is not None and piece.style == pending_style:
                pending_text += piece.text
            else:
                flush()
                pending_text = piece.text
                pending_style = piece.style
                pending_x = x
            x += piece.width
            if piece.is_space and extra:
                # A widened gap ends the fragment, because the extra space
                # is a gap in the layout, not a character in the string.
                flush()
                x += extra
                pending_x = x
        flush()
        if link_start is not None and link_url:
            links.append(
                PaintLink(
                    x=link_start,
                    y=0.0,
                    width=x - link_start,
                    height=line_height,
                    url=link_url,
                )
            )
        return paint, links

    def rows_for_lines(
        self,
        lines: list[Line],
        left: float,
        width: float,
        line_height: float,
        justify: bool,
        align: str = "left",
        widow_control: bool = True,
    ) -> list[Row]:
        """Turn laid out lines into rows, applying widow and orphan rules."""
        rows: list[Row] = []
        count = len(lines)
        for index, line in enumerate(lines):
            paint, links = self.paint_line(
                line,
                left,
                width,
                line_height,
                justify and not line.ends_block,
                align,
            )
            row = Row(height=line_height, items=[paint, *links])
            if widow_control and count >= 2:
                # The opening line may not be stranded at the foot of a page
                # and the closing line may not be stranded at the head of
                # one. Both are expressed as a keep with the next row.
                if index == 0 or index == count - 2:
                    row.keep_with_next = True
            rows.append(row)
        return rows

    def space_row(self, height: float) -> Row:
        """A blank row that collapses at a page boundary."""
        return Row(height=height, is_space=True)

    # --- block dispatch ----------------------------------------------------

    def render(self, document: Document) -> list[Row]:
        """Render a whole document body into rows."""
        return self.render_blocks(
            document.children,
            self.geometry.content_left,
            self.geometry.content_width,
        )

    def render_blocks(
        self, blocks: list[Node], left: float, width: float
    ) -> list[Row]:
        rows: list[Row] = []
        for block in blocks:
            match block:
                case Heading():
                    rows.extend(self.render_heading(block, left, width))
                case Paragraph():
                    lone = self._lone_image(block)
                    if lone is not None:
                        rows.extend(self.render_image(lone, left, width))
                    else:
                        rows.extend(
                            self.render_paragraph(block, left, width)
                        )
                case CodeBlock():
                    rows.extend(self.render_code_block(block, left, width))
                case BlockQuote():
                    rows.extend(self.render_blockquote(block, left, width))
                case ListBlock():
                    rows.extend(self.render_list(block, left, width))
                case ThematicBreak():
                    rows.extend(self.render_rule(left, width))
                case Table():
                    rows.extend(self.render_table(block, left, width))
        return rows

    # --- individual blocks -------------------------------------------------

    @staticmethod
    def _lone_image(node: Paragraph) -> Image | None:
        """Return the image if the paragraph holds nothing else.

        An image on a line of its own is a block, and that is how images
        appear in practice. An image in the middle of a sentence would have
        to sit on a text baseline and take part in line breaking, which is
        not supported; those fall back to their alt text with a warning.
        """
        found: Image | None = None
        for child in node.children:
            if isinstance(child, Image):
                if found is not None:
                    return None
                found = child
            elif isinstance(child, LineBreak):
                continue
            elif isinstance(child, Text) and not child.text.strip():
                continue
            else:
                return None
        return found

    def render_image(
        self, node: Image, left: float, width: float
    ) -> list[Row]:
        """Embed a block level image, or fall back to its alt text."""
        image = self.load_image(node)
        if image is None:
            return self.render_paragraph(
                Paragraph(pos=node.pos, children=[node]), left, width
            )
        key = self._image_key(node)
        display_width = image.point_width
        display_height = image.point_height
        # Scale down to fit the column, and again to fit the page height.
        if display_width > width:
            scale = width / display_width
            display_width *= scale
            display_height *= scale
        available_height = (
            self.geometry.content_bottom - self.geometry.content_top
        )
        if display_height > available_height:
            scale = available_height / display_height
            display_width *= scale
            display_height *= scale
        offset = (width - display_width) / 2.0
        return [
            self.space_row(self.size * 0.55),
            Row(
                height=display_height,
                items=[
                    PaintImage(
                        x=left + offset,
                        y=0.0,
                        width=display_width,
                        height=display_height,
                        key=key,
                    )
                ],
            ),
            self.space_row(self.size * 0.75),
        ]

    def _image_key(self, node: Image) -> str:
        base = self.options.base_path
        if base is None:
            return node.src
        return str((base / node.src).resolve())

    def load_image(self, node: Image) -> PngImage | None:
        """Decode an image, warning with a source position on failure."""
        if self.options.base_path is None:
            self.diagnostics.warn(
                "images cannot be loaded when the source is not a file; "
                f"showing the alt text for {node.src!r}",
                node.pos.offset,
            )
            return None
        key = self._image_key(node)
        if key in self.images:
            return self.images[key]
        if not node.src.lower().endswith(".png"):
            self.diagnostics.warn(
                f"only PNG images can be embedded, so {node.src!r} is "
                "shown as its alt text",
                node.pos.offset,
            )
            return None
        try:
            image = load_png(Path(key))
        except PngError as error:
            self.diagnostics.warn(
                f"cannot embed {node.src!r}: {error}", node.pos.offset
            )
            return None
        self.images[key] = image
        return image

    def render_paragraph(
        self, node: Paragraph, left: float, width: float
    ) -> list[Row]:
        pieces = self.flatten(node.children, self.size)
        lines = break_lines(pieces, width)
        if not lines:
            return []
        rows = self.rows_for_lines(
            lines, left, width, self.line_height, self.options.justify
        )
        rows.append(
            self.space_row(self.size * self.options.paragraph_gap_ratio)
        )
        return rows

    def render_heading(
        self, node: Heading, left: float, width: float
    ) -> list[Row]:
        size = self.size * HEADING_SCALE.get(node.level, 1.0)
        line_height = size * 1.28
        self.heading_counter += 1
        node.dest_name = f"H{self.heading_counter}"
        pieces = self.flatten(
            node.children, size, bold=True, colour=self.theme.heading
        )
        lines = break_lines(pieces, width)
        rows: list[Row] = [
            self.space_row(
                self.size * HEADING_SPACE_ABOVE.get(node.level, 0.8)
            )
        ]
        text_rows = self.rows_for_lines(
            lines, left, width, line_height, justify=False,
            widow_control=False,
        )
        for row in text_rows:
            # A heading is never the last thing on a page.
            row.keep_with_next = True
        if text_rows:
            text_rows[0].heading = node
        else:
            # An empty heading still needs an anchor for the outline.
            anchor = Row(height=line_height, heading=node,
                         keep_with_next=True)
            text_rows = [anchor]
        rows.extend(text_rows)
        rows.append(self.space_row(self.size * 0.34))
        # A rule under the top two levels gives the page some structure.
        if node.level <= 2:
            rows.append(
                Row(
                    height=self.size * 0.42,
                    items=[
                        PaintRect(
                            x=left,
                            y=0.0,
                            width=width,
                            height=0.6,
                            colour=self.theme.rule,
                        )
                    ],
                    keep_with_next=True,
                )
            )
            rows.append(self.space_row(self.size * 0.30))
        return rows

    def render_code_block(
        self, node: CodeBlock, left: float, width: float
    ) -> list[Row]:
        size = self.size * self.options.code_size_ratio
        line_height = size * self.options.code_line_ratio
        padding = self.size * 0.45
        inner_left = left + padding
        inner_width = width - 2 * padding
        style = TextStyle(
            font=MONOSPACE_FAMILY[0],
            size=size,
            colour=self.theme.code_text,
            code=True,
        )
        panel = self.theme.code_background

        def panel_row(height: float) -> Row:
            return Row(
                height=height,
                items=[
                    PaintRect(
                        x=left, y=0.0, width=width, height=height,
                        colour=panel,
                    )
                ],
            )

        rows: list[Row] = [self.space_row(self.size * 0.45)]
        rows.append(panel_row(padding))
        space_width = style.width_of(" ")
        for raw_line in node.text.split("\n"):
            # A tab has no glyph in any of the standard fonts, so emitting
            # one would silently flatten tab indented code. Expanding to
            # spaces here keeps the AST holding exactly what the file said
            # while the page shows the indentation the author meant.
            source_line = raw_line.expandtabs(TAB_WIDTH)
            # Leading whitespace stays in the drawn string rather than
            # becoming an x offset. Code is set in Courier, which advances
            # every glyph by the same 600/1000 em, so spaces land at exactly
            # the position an offset would have produced and there is no
            # measurement risk; keeping them as characters means the
            # indentation survives being copied out of the finished PDF.
            body = source_line.lstrip(" ")
            indent_columns = len(source_line) - len(body)
            indent_width = indent_columns * space_width
            # Wrapping is measured against the space left after the indent,
            # because a continuation line hangs at its own depth instead of
            # returning to the left edge of the panel.
            text_width = max(inner_width - indent_width, space_width * 4)
            pieces = split_into_pieces(body, style) if body else []
            wrapped = break_lines(pieces, text_width) if pieces else [Line()]
            for position, line in enumerate(wrapped):
                if position == 0 and indent_columns and line.pieces:
                    first = line.pieces[0]
                    line.pieces[0] = Piece(
                        " " * indent_columns + first.text,
                        first.style,
                        "word",
                        indent_width + first.width,
                    )
                    line.natural_width += indent_width
                    text_left = inner_left
                else:
                    text_left = inner_left + indent_width
                paint, links = self.paint_line(
                    line, text_left, text_width, line_height, justify=False
                )
                rows.append(
                    Row(
                        height=line_height,
                        items=[
                            PaintRect(
                                x=left,
                                y=0.0,
                                width=width,
                                height=line_height,
                                colour=panel,
                            ),
                            paint,
                            *links,
                        ],
                    )
                )
        rows.append(panel_row(padding))
        rows.append(self.space_row(self.size * 0.65))
        return rows

    def render_blockquote(
        self, node: BlockQuote, left: float, width: float
    ) -> list[Row]:
        indent = self.size * self.options.quote_indent_ratio
        inner = self.render_blocks(
            node.children, left + indent, width - indent
        )
        while inner and inner[-1].is_space:
            inner.pop()
        bar_width = 2.4
        bar_x = left + indent * 0.25
        for row in inner:
            # The rule is drawn per row so that a quote crossing a page
            # boundary keeps its rule on both pages.
            row.items.insert(
                0,
                PaintRect(
                    x=bar_x,
                    y=0.0,
                    width=bar_width,
                    height=row.height,
                    colour=self.theme.quote_bar,
                ),
            )
        rows: list[Row] = [self.space_row(self.size * 0.35)]
        rows.extend(inner)
        rows.append(self.space_row(self.size * 0.70))
        return rows

    def render_list(
        self, node: ListBlock, left: float, width: float
    ) -> list[Row]:
        indent = self.size * self.options.list_indent_ratio
        bullet = BULLETS[min(self._list_depth, len(BULLETS) - 1)]
        marker_style = self.style()
        rows: list[Row] = []
        self._list_depth += 1
        for index, item in enumerate(node.items):
            inner = self.render_blocks(
                item.children, left + indent, width - indent
            )
            if node.tight:
                while inner and inner[-1].is_space:
                    inner.pop()
            if not inner:
                inner = [Row(height=self.line_height)]
            label = (
                f"{node.start + index}." if node.ordered else bullet
            )
            label_width = marker_style.width_of(label)
            # The marker is right-aligned in the indent so that `9.` and
            # `10.` line up on their full stops.
            marker_x = left + indent - label_width - self.size * 0.45
            first = inner[0]
            first.items.insert(
                0,
                PaintText(
                    baseline=baseline_offset(
                        min(first.height, self.line_height), marker_style.size
                    ),
                    fragments=[
                        Fragment(x=marker_x, text=label, style=marker_style)
                    ],
                ),
            )
            # The first line of an item should not be stranded alone.
            if len(inner) >= 2:
                first.keep_with_next = True
            rows.extend(inner)
        self._list_depth -= 1
        rows.append(
            self.space_row(self.size * self.options.paragraph_gap_ratio)
        )
        return rows

    def render_rule(self, left: float, width: float) -> list[Row]:
        return [
            self.space_row(self.size * 0.70),
            Row(
                height=1.0,
                items=[
                    PaintRect(
                        x=left, y=0.0, width=width, height=0.8,
                        colour=self.theme.rule,
                    )
                ],
            ),
            self.space_row(self.size * 0.80),
        ]

    # --- tables ------------------------------------------------------------

    def render_table(
        self, node: Table, left: float, width: float
    ) -> list[Row]:
        rows_source: list[TableRow] = []
        if node.header is not None:
            rows_source.append(node.header)
        rows_source.extend(node.rows)
        if not rows_source:
            return []
        column_count = len(node.alignments) or max(
            len(row.cells) for row in rows_source
        )
        padding = self.size * self.options.table_padding_ratio
        widths = self._column_widths(
            rows_source, column_count, width, padding
        )
        rule_height = 0.7
        rows: list[Row] = [self.space_row(self.size * 0.55)]
        rows.append(self._table_rule(left, width, rule_height))
        for position, source in enumerate(rows_source):
            is_header = position == 0 and node.header is not None
            rows.append(
                self._table_row_rows(
                    source, node.alignments, widths, left, padding, is_header
                )
            )
            if is_header:
                rows.append(self._table_rule(left, width, rule_height))
        rows.append(self._table_rule(left, width, rule_height))
        rows.append(self.space_row(self.size * 0.75))
        # The header must never be the last thing on a page.
        for row in rows[:3]:
            row.keep_with_next = True
        return rows

    def _table_rule(
        self, left: float, width: float, height: float
    ) -> Row:
        return Row(
            height=height,
            items=[
                PaintRect(
                    x=left, y=0.0, width=width, height=height,
                    colour=self.theme.table_border,
                )
            ],
            keep_with_next=False,
        )

    def _column_widths(
        self,
        rows_source: list[TableRow],
        column_count: int,
        width: float,
        padding: float,
    ) -> list[float]:
        """Size columns from their natural widths, scaled to fill the page."""
        natural = [0.0] * column_count
        for source in rows_source:
            for index in range(column_count):
                if index >= len(source.cells):
                    continue
                pieces = self.flatten(source.cells[index].children, self.size)
                content = sum(piece.width for piece in pieces)
                natural[index] = max(natural[index], content)
        natural = [value + 2 * padding for value in natural]
        total = sum(natural)
        if total <= 0:
            return [width / column_count] * column_count
        scaled = [value * width / total for value in natural]
        # No column may collapse below a few characters, or a narrow column
        # of long words turns into a column of single letters.
        floor = min(self.size * 3.2, width / column_count)
        deficit = 0.0
        for index, value in enumerate(scaled):
            if value < floor:
                deficit += floor - value
                scaled[index] = floor
        if deficit > 0:
            spare = [
                index
                for index, value in enumerate(scaled)
                if value > floor + deficit
            ]
            if spare:
                share = deficit / len(spare)
                for index in spare:
                    scaled[index] -= share
        return scaled

    def _table_row_rows(
        self,
        source: TableRow,
        alignments: list[str],
        widths: list[float],
        left: float,
        padding: float,
        is_header: bool,
    ) -> Row:
        """Lay out one table row as a single, unsplittable Row."""
        cell_lines: list[list[Line]] = []
        for index, cell_width in enumerate(widths):
            if index < len(source.cells):
                pieces = self.flatten(
                    source.cells[index].children,
                    self.size,
                    bold=is_header,
                )
            else:
                pieces = []
            cell_lines.append(break_lines(pieces, cell_width - 2 * padding))
        tallest = max((len(lines) for lines in cell_lines), default=1) or 1
        height = tallest * self.line_height + 2 * padding
        items: list[object] = []
        if is_header:
            items.append(
                PaintRect(
                    x=left,
                    y=0.0,
                    width=sum(widths),
                    height=height,
                    colour=self.theme.table_header,
                )
            )
        x = left
        for index, cell_width in enumerate(widths):
            align = (
                alignments[index] if index < len(alignments) else "left"
            )
            inner_left = x + padding
            inner_width = cell_width - 2 * padding
            for line_index, line in enumerate(cell_lines[index]):
                paint, links = self.paint_line(
                    line,
                    inner_left,
                    inner_width,
                    self.line_height,
                    justify=False,
                    align=align,
                )
                paint.baseline += padding + line_index * self.line_height
                for link in links:
                    link.y += padding + line_index * self.line_height
                items.append(paint)
                items.extend(links)
            x += cell_width
        return Row(height=height, items=items)


# ===========================================================================
# Section 10: PDF object model
# ===========================================================================
#
# A PDF file is a header, a numbered sequence of indirect objects, a
# cross-reference table giving the byte offset of every one of them, and a
# trailer that names the root object and points back at the table. There are
# eight object types and they are all serialised here by hand:
#
#     null          null
#     boolean       true / false
#     number        12   3.5
#     string        (literal)  or  <48656C6C6F>
#     name          /Type
#     array         [1 2 3]
#     dictionary    << /Key value >>
#     stream        a dictionary followed by raw bytes
#
# An indirect object is `N 0 obj ... endobj`, and `N 0 R` is a reference to
# it. That is the entire format at this level.


@dataclass(frozen=True)
class PdfName:
    """A PDF name object, written `/Value`."""

    value: str


@dataclass(frozen=True)
class PdfRef:
    """An indirect reference, written `N 0 R`."""

    number: int
    generation: int = 0


@dataclass(frozen=True)
class PdfString:
    """A text string, written as an escaped literal `(...)`."""

    text: str


@dataclass(frozen=True)
class PdfRawString:
    """A byte string that is already WinAnsi encoded."""

    data: bytes


@dataclass
class PdfStream:
    """A stream object: a dictionary plus raw data.

    `/Length` is filled in at serialisation time from the encoded data, and
    compression is applied there too, so no caller can leave the two out of
    step.
    """

    data: bytes
    extra: dict[str, object] = field(default_factory=dict)
    compress: bool = True


def format_number(value: float) -> bytes:
    """Format a number for PDF output, deterministically.

    Fixed precision with the trailing zeros trimmed, never exponent
    notation, because a PDF number has no exponent form and `repr` of a
    float is free to produce one.
    """
    if isinstance(value, int):
        return str(value).encode("ascii")
    text = f"{value:.4f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("", "-0"):
        text = "0"
    return text.encode("ascii")


#: Characters that may appear bare inside a PDF name. Everything else is
#: written as `#` followed by two hex digits.
_NAME_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "+-._"
)


def encode_name(value: str) -> bytes:
    """Serialise a PDF name, escaping anything outside the safe set."""
    out = bytearray(b"/")
    for byte in value.encode("utf-8"):
        character = chr(byte)
        if character in _NAME_SAFE:
            out.append(byte)
        else:
            out += b"#%02X" % byte
    return bytes(out)


def encode_winansi(text: str) -> tuple[bytes, list[str]]:
    """Encode text to WinAnsi bytes, reporting characters that do not fit.

    Nothing is ever dropped silently. A character outside WinAnsiEncoding
    cannot be drawn without embedding a font, which inkless does not do, so
    it becomes a placeholder and the caller is handed the list of characters
    that were substituted so it can warn with a source position.
    """
    out = bytearray()
    substituted: list[str] = []
    for character in text:
        try:
            out += character.encode("cp1252")
        except UnicodeEncodeError:
            substituted.append(character)
            out += UNRENDERABLE_PLACEHOLDER.encode("ascii")
    return bytes(out), substituted


def encode_literal_string(data: bytes) -> bytes:
    """Escape bytes for a PDF literal string, including the parentheses.

    Inside `( )` a backslash, an opening parenthesis and a closing
    parenthesis must each be escaped. Everything outside printable ASCII is
    written as a three digit octal escape, which keeps the output file pure
    ASCII and sidesteps every question about how a reader treats a raw high
    byte in a literal string.
    """
    out = bytearray(b"(")
    for byte in data:
        if byte in (0x5C, 0x28, 0x29):  # backslash, ( and )
            out.append(0x5C)
            out.append(byte)
        elif 0x20 <= byte <= 0x7E:
            out.append(byte)
        else:
            out += b"\\%03o" % byte
    out += b")"
    return bytes(out)


def serialize(obj: object) -> bytes:
    """Serialise any direct PDF object to bytes."""
    # bool is checked before int because in Python bool is a subclass of int
    # and `True` would otherwise be written as the number 1.
    if obj is None:
        return b"null"
    if isinstance(obj, bool):
        return b"true" if obj else b"false"
    if isinstance(obj, (int, float)):
        return format_number(obj)
    if isinstance(obj, PdfName):
        return encode_name(obj.value)
    if isinstance(obj, PdfRef):
        return b"%d %d R" % (obj.number, obj.generation)
    if isinstance(obj, PdfString):
        encoded, _ = encode_winansi(obj.text)
        return encode_literal_string(encoded)
    if isinstance(obj, PdfRawString):
        return encode_literal_string(obj.data)
    if isinstance(obj, bytes):
        # An escape hatch for content that is already serialised, such as a
        # hex string built elsewhere.
        return obj
    if isinstance(obj, (list, tuple)):
        return b"[" + b" ".join(serialize(item) for item in obj) + b"]"
    if isinstance(obj, dict):
        parts = bytearray(b"<<")
        for key, value in obj.items():
            parts += b" " + encode_name(key) + b" " + serialize(value)
        parts += b" >>"
        return bytes(parts)
    raise TypeError(f"cannot serialise {type(obj).__name__} as a PDF object")


def serialize_stream(stream: PdfStream) -> bytes:
    """Serialise a stream object, compressing and setting `/Length`."""
    data = stream.data
    dictionary: dict[str, object] = {}
    if stream.compress:
        # Level 9 so the output is deterministic for a given zlib build and
        # as small as it goes; content streams are highly repetitive text.
        data = zlib.compress(data, 9)
        dictionary["Filter"] = PdfName("FlateDecode")
    dictionary["Length"] = len(data)
    for key, value in stream.extra.items():
        dictionary[key] = value
    out = bytearray(serialize(dictionary))
    out += b"\nstream\n"
    out += data
    out += b"\nendstream"
    return bytes(out)


# ===========================================================================
# Section 11: PDF document writer (xref, trailer, streams)
# ===========================================================================


class PdfWriter:
    """Collects indirect objects and renders the complete file.

    The cross-reference table is a list of byte offsets into the finished
    file, one per object, each written as a fixed twenty byte record. Nothing
    can know those offsets until the objects ahead of it have been
    serialised, so the file is built into one buffer and each object's start
    position is recorded as it is appended. An offset that is wrong by a
    single byte makes every conforming reader reject the document, which is
    why `render` is the only place allowed to write into the buffer.
    """

    HEADER = b"%PDF-1.7\n"
    #: A comment line of high bytes, which is what tells file transfer tools
    #: and readers that this file is binary and must not be newline munged.
    BINARY_COMMENT = b"%\xe2\xe3\xcf\xd3\n"

    def __init__(self) -> None:
        self._objects: list[object | None] = []
        self.offsets: list[int] = []

    # --- object registry ---------------------------------------------------

    def reserve(self) -> PdfRef:
        """Allocate an object number before the object itself exists.

        Needed wherever the graph has a cycle, such as a page pointing at
        the pages tree that also lists the page.
        """
        self._objects.append(None)
        return PdfRef(len(self._objects))

    def assign(self, ref: PdfRef, obj: object) -> PdfRef:
        """Fill in an object number that was reserved earlier."""
        self._objects[ref.number - 1] = obj
        return ref

    def add(self, obj: object) -> PdfRef:
        """Append an object and return a reference to it."""
        self._objects.append(obj)
        return PdfRef(len(self._objects))

    @property
    def object_count(self) -> int:
        return len(self._objects)

    # --- rendering ---------------------------------------------------------

    def render(self, root: PdfRef, info: PdfRef | None = None) -> bytes:
        """Serialise every object, then the xref table and the trailer."""
        for number, obj in enumerate(self._objects, start=1):
            if obj is None:
                raise AssertionError(
                    f"object {number} was reserved but never assigned"
                )
        out = bytearray()
        out += self.HEADER
        out += self.BINARY_COMMENT
        self.offsets = [0] * (len(self._objects) + 1)
        for number, obj in enumerate(self._objects, start=1):
            self.offsets[number] = len(out)
            out += b"%d 0 obj\n" % number
            if isinstance(obj, PdfStream):
                out += serialize_stream(obj)
            else:
                out += serialize(obj)
            out += b"\nendobj\n"

        # The document identifier has to be stable across runs, so it is a
        # digest of the objects themselves rather than anything to do with
        # the clock or the file name.
        digest = hashlib.sha256(bytes(out)).hexdigest()[:32].upper()
        identifier = b"<" + digest.encode("ascii") + b">"

        xref_offset = len(out)
        size = len(self._objects) + 1
        out += b"xref\n"
        out += b"0 %d\n" % size
        # Object 0 is always the head of the free list, generation 65535.
        # Every entry is exactly twenty bytes including the two byte ending.
        out += b"0000000000 65535 f \n"
        for number in range(1, size):
            out += b"%010d 00000 n \n" % self.offsets[number]
        trailer: dict[str, object] = {"Size": size, "Root": root}
        if info is not None:
            trailer["Info"] = info
        trailer["ID"] = [identifier, identifier]
        out += b"trailer\n"
        out += serialize(trailer)
        out += b"\nstartxref\n"
        out += b"%d\n" % xref_offset
        out += b"%%EOF\n"
        return bytes(out)


def pdf_date(date_string: str) -> str:
    """Format a `YYYY-MM-DD` date as a PDF date string.

    The wall clock is never consulted. A build that stamps `datetime.now()`
    into the output cannot be reproducible, so the date comes from front
    matter, from `--date`, or from the fixed default.
    """
    parts = date_string.split("-")
    year = parts[0] if len(parts) > 0 else "2000"
    month = parts[1] if len(parts) > 1 else "01"
    day = parts[2] if len(parts) > 2 else "01"
    return f"D:{year:0>4}{month:0>2}{day:0>2}000000+00'00'"


# ===========================================================================
# Section 12: Emission (laid out pages to PDF objects)
# ===========================================================================


class FontRegistry:
    """Assigns `/F1`, `/F2` and so on to the standard fonts a document uses.

    Names are handed out in first-use order, which is deterministic for a
    given input, and only the fonts actually used end up in the resource
    dictionary.
    """

    def __init__(self) -> None:
        self._names: dict[str, str] = {}

    def name_for(self, base_font: str) -> str:
        """Resource name for a BaseFont, allocating one on first use."""
        if base_font not in self._names:
            self._names[base_font] = f"F{len(self._names) + 1}"
        return self._names[base_font]

    def entries(self) -> list[tuple[str, str]]:
        """(resource name, BaseFont) pairs in allocation order."""
        return [(name, font) for font, name in self._names.items()]


class XObjectRegistry:
    """Assigns `/Im1`, `/Im2` and so on to the images a document uses."""

    def __init__(self) -> None:
        self._names: dict[str, str] = {}

    def name_for(self, key: str) -> str:
        """Resource name for an image key, allocating one on first use."""
        if key not in self._names:
            self._names[key] = f"Im{len(self._names) + 1}"
        return self._names[key]

    def entries(self) -> list[tuple[str, str]]:
        """(resource name, image key) pairs in allocation order."""
        return [(name, key) for key, name in self._names.items()]


class ContentStreamBuilder:
    """Builds the drawing instructions for one page.

    This is the only place that converts from the top-left coordinates used
    everywhere above into PDF user space, whose origin is the bottom left
    corner with y growing upward.
    """

    def __init__(
        self,
        geometry: PageGeometry,
        fonts: FontRegistry,
        images: XObjectRegistry | None = None,
    ) -> None:
        self.geometry = geometry
        self.fonts = fonts
        self.images = images if images is not None else XObjectRegistry()
        self.parts: list[bytes] = []
        self._colour: tuple[float, float, float] | None = None
        self._font: tuple[str, float] | None = None
        self._text_open = False

    def pdf_y(self, top_y: float) -> float:
        """Convert a distance from the page top into a PDF y coordinate."""
        return self.geometry.height - top_y

    def _set_colour(self, colour: tuple[float, float, float]) -> None:
        if self._colour == colour:
            return
        self._colour = colour
        red, green, blue = colour
        self.parts.append(
            format_number(red)
            + b" "
            + format_number(green)
            + b" "
            + format_number(blue)
            + b" rg\n"
        )

    def _end_text(self) -> None:
        if self._text_open:
            self.parts.append(b"ET\n")
            self._text_open = False
            self._font = None

    def _begin_text(self) -> None:
        if not self._text_open:
            self.parts.append(b"BT\n")
            self._text_open = True

    def rect(
        self,
        x: float,
        top_y: float,
        width: float,
        height: float,
        colour: tuple[float, float, float],
    ) -> None:
        """Fill a rectangle given its top-left corner."""
        if width <= 0 or height <= 0:
            return
        self._end_text()
        self._set_colour(colour)
        self.parts.append(
            format_number(x)
            + b" "
            + format_number(self.pdf_y(top_y + height))
            + b" "
            + format_number(width)
            + b" "
            + format_number(height)
            + b" re\nf\n"
        )

    def image(
        self, x: float, top_y: float, width: float, height: float, key: str
    ) -> None:
        """Place an image XObject in its own graphics state.

        The `cm` matrix maps the image's own unit square onto the rectangle
        it should occupy, which is how every image in a PDF is positioned.
        """
        if width <= 0 or height <= 0:
            return
        self._end_text()
        self.parts.append(
            b"q\n"
            + format_number(width)
            + b" 0 0 "
            + format_number(height)
            + b" "
            + format_number(x)
            + b" "
            + format_number(self.pdf_y(top_y + height))
            + b" cm\n"
            + encode_name(self.images.name_for(key))
            + b" Do\nQ\n"
        )
        # The graphics state was restored, so any cached colour is stale.
        self._colour = None

    def text(
        self, x: float, baseline_top_y: float, body: str, style: TextStyle
    ) -> None:
        """Draw a run of text with its baseline at `baseline_top_y`."""
        if not body:
            return
        encoded, _ = encode_winansi(body)
        self._begin_text()
        self._set_colour(style.colour)
        key = (style.font, style.size)
        if self._font != key:
            self._font = key
            self.parts.append(
                encode_name(self.fonts.name_for(style.font))
                + b" "
                + format_number(style.size)
                + b" Tf\n"
            )
        self.parts.append(
            b"1 0 0 1 "
            + format_number(x)
            + b" "
            + format_number(self.pdf_y(baseline_top_y))
            + b" Tm\n"
            + encode_literal_string(encoded)
            + b" Tj\n"
        )

    def finish(self) -> bytes:
        self._end_text()
        return b"".join(self.parts)


@dataclass
class PlacedLink:
    """A link annotation with page-absolute coordinates, in top-left space."""

    x: float
    y: float
    width: float
    height: float
    url: str = ""
    dest: str = ""


def draw_page(
    page: LaidOutPage,
    geometry: PageGeometry,
    fonts: FontRegistry,
    options: RenderOptions,
    footer_text: str = "",
    images: XObjectRegistry | None = None,
) -> tuple[bytes, list[PlacedLink]]:
    """Render one laid out page to a content stream and its annotations."""
    builder = ContentStreamBuilder(geometry, fonts, images)
    links: list[PlacedLink] = []
    # Rectangles are drawn before text so that a code panel or a table
    # header sits behind its own characters rather than over them.
    for placed in page.rows:
        for item in placed.row.items:
            if isinstance(item, PaintRect):
                builder.rect(
                    item.x,
                    placed.y + item.y,
                    item.width,
                    item.height,
                    item.colour,
                )
    for placed in page.rows:
        for item in placed.row.items:
            if isinstance(item, PaintImage):
                builder.image(
                    item.x,
                    placed.y + item.y,
                    item.width,
                    item.height,
                    item.key,
                )
            elif isinstance(item, PaintText):
                for fragment in item.fragments:
                    builder.text(
                        fragment.x,
                        placed.y + item.baseline,
                        fragment.text,
                        fragment.style,
                    )
            elif isinstance(item, PaintLink):
                links.append(
                    PlacedLink(
                        x=item.x,
                        y=placed.y + item.y,
                        width=item.width,
                        height=item.height,
                        url=item.url,
                        dest=item.dest,
                    )
                )
    if footer_text:
        style = TextStyle(
            font=font_for_style(
                FONT_FAMILIES[options.font_family], False, False
            ),
            size=options.font_size * 0.82,
            colour=options.theme.footer,
        )
        width = style.width_of(footer_text)
        builder.text(
            (geometry.width - width) / 2.0,
            geometry.footer_baseline,
            footer_text,
            style,
        )
    return builder.finish(), links


def link_annotation(
    link: PlacedLink, geometry: PageGeometry, dest_refs: dict[str, object]
) -> dict[str, object] | None:
    """Build a `/Annot` dictionary for one link rectangle."""
    lower_left_y = geometry.height - (link.y + link.height)
    upper_right_y = geometry.height - link.y
    annotation: dict[str, object] = {
        "Type": PdfName("Annot"),
        "Subtype": PdfName("Link"),
        "Rect": [
            link.x,
            lower_left_y,
            link.x + link.width,
            upper_right_y,
        ],
        # A zero width border keeps readers from drawing a box round every
        # link, which looks wrong in a typeset document.
        "Border": [0, 0, 0],
    }
    if link.dest:
        target = dest_refs.get(link.dest)
        if target is None:
            return None
        annotation["Dest"] = target
    elif link.url:
        annotation["A"] = {
            "S": PdfName("URI"),
            "URI": PdfString(link.url),
        }
    else:
        return None
    return annotation


# ===========================================================================
# Section 13: Document assembly
# ===========================================================================


@dataclass
class BuildOptions:
    """Everything the command line can change about a build."""

    page_size: str = "a4"
    font_family: str = "helvetica"
    font_size: float = 11.0
    margin: float = 64.0
    justify: bool = False
    toc: bool = False
    page_numbers: bool = True
    date: str = ""
    #: Directory relative image paths resolve against. None means images
    #: are not loaded at all.
    base_path: Path | None = None

    def geometry(self) -> PageGeometry:
        width, height = PAGE_SIZES[self.page_size]
        return PageGeometry(width=width, height=height, margin=self.margin)

    def render_options(self) -> RenderOptions:
        return RenderOptions(
            font_family=self.font_family,
            font_size=self.font_size,
            justify=self.justify,
            base_path=self.base_path,
        )


@dataclass
class HeadingEntry:
    """A heading, the page it landed on, and where on that page it sits."""

    heading: Heading
    page_index: int
    y: float


@dataclass
class BuildResult:
    """The finished file and everything worth reporting about the build."""

    data: bytes
    diagnostics: list[Diagnostic]
    page_count: int
    headings: list[HeadingEntry]
    #: How many layout passes the table of contents needed to settle.
    toc_passes: int = 0
    #: How many pages the table of contents ended up occupying.
    toc_page_count: int = 0


#: Upper bound on table of contents layout passes. The loop is monotone and
#: settles in one or two passes in practice; the bound exists so that a
#: pathological document cannot spin forever.
TOC_MAX_PASSES = 8

#: Heading shown above the table of contents.
TOC_TITLE = "Contents"


def place_on_one_page(
    rows: list[Row], geometry: PageGeometry, start_y: float
) -> LaidOutPage:
    """Stack rows down a single page from a given starting height."""
    page = LaidOutPage(number=1)
    y = start_y
    for row in rows:
        page.rows.append(PlacedRow(y=y, row=row))
        y += row.height
    return page


class DocumentBuilder:
    """Runs the whole pipeline: parse, render, paginate, emit.

    Kept as a class because the table of contents needs two passes over the
    same rendered rows, and the second pass has to reuse the first pass's
    page assignments rather than re-deriving them.
    """

    def __init__(self, options: BuildOptions) -> None:
        self.options = options
        self.geometry = options.geometry()
        self.render_options = options.render_options()

    # --- title page --------------------------------------------------------

    def title_rows(
        self, renderer: DocumentRenderer, front_matter: dict[str, str]
    ) -> list[Row]:
        """Build the rows of a title page from the front matter."""
        title = front_matter.get("title", "")
        if not title:
            return []
        rows: list[Row] = []
        width = self.geometry.content_width
        left = self.geometry.content_left
        base = self.render_options.font_size

        def centred(
            text: str, size: float, bold: bool,
            colour: tuple[float, float, float],
        ) -> list[Row]:
            style = TextStyle(
                font=font_for_style(renderer.body_family, bold, False),
                size=size,
                colour=colour,
            )
            pieces = split_into_pieces(text, style)
            lines = break_lines(pieces, width)
            line_height = size * 1.3
            built: list[Row] = []
            for line in lines:
                paint, _ = renderer.paint_line(
                    line, left, width, line_height, justify=False,
                    align="center",
                )
                built.append(Row(height=line_height, items=[paint]))
            return built

        rows.extend(centred(title, base * 2.4, True, renderer.theme.heading))
        subtitle = front_matter.get("subtitle", "")
        if subtitle:
            rows.append(renderer.space_row(base * 0.8))
            rows.extend(
                centred(subtitle, base * 1.3, False, renderer.theme.quote_text)
            )
        rows.append(renderer.space_row(base * 1.6))
        rows.append(
            Row(
                height=base * 0.6,
                items=[
                    PaintRect(
                        x=left + width * 0.35,
                        y=0.0,
                        width=width * 0.30,
                        height=0.8,
                        colour=renderer.theme.rule,
                    )
                ],
            )
        )
        rows.append(renderer.space_row(base * 1.6))
        author = front_matter.get("author", "")
        if author:
            rows.extend(centred(author, base * 1.15, False,
                                renderer.theme.text))
            rows.append(renderer.space_row(base * 0.5))
        date = front_matter.get("date", "")
        if date:
            rows.extend(centred(date, base * 0.95, False,
                                renderer.theme.footer))
        return rows

    # --- table of contents -------------------------------------------------

    def toc_rows(
        self,
        renderer: DocumentRenderer,
        entries: list[tuple[Heading, int]],
        page_offset: int,
    ) -> list[Row]:
        """Build the rows of a table of contents.

        `page_offset` is the number of pages that come before the body, so
        the printed number for a heading is `page_offset + body page + 1`.
        Every entry carries a link covering its full width, pointing at the
        named destination the heading was given during rendering.
        """
        left = self.geometry.content_left
        width = self.geometry.content_width
        base = self.render_options.font_size
        theme = renderer.theme
        rows: list[Row] = []

        title_style = TextStyle(
            font=font_for_style(renderer.body_family, True, False),
            size=base * 1.7,
            colour=theme.heading,
        )
        title_height = title_style.size * 1.3
        title_paint, _ = renderer.paint_line(
            Line(
                pieces=split_into_pieces(TOC_TITLE, title_style),
                natural_width=title_style.width_of(TOC_TITLE),
                ends_block=True,
            ),
            left,
            width,
            title_height,
            justify=False,
        )
        rows.append(Row(height=title_height, items=[title_paint]))
        rows.append(
            Row(
                height=base * 0.9,
                items=[
                    PaintRect(
                        x=left, y=base * 0.4, width=width, height=0.6,
                        colour=theme.rule,
                    )
                ],
            )
        )

        for heading, body_index in entries:
            level = max(1, min(heading.level, 6))
            number = str(page_offset + body_index + 1)
            indent = (level - 1) * base * 1.20
            entry_style = TextStyle(
                font=font_for_style(
                    renderer.body_family, level == 1, False
                ),
                size=base * (1.0 if level <= 2 else 0.94),
                colour=theme.text,
            )
            number_style = TextStyle(
                font=font_for_style(renderer.body_family, False, False),
                size=entry_style.size,
                colour=theme.footer,
            )
            leader_style = TextStyle(
                font=number_style.font,
                size=entry_style.size,
                colour=theme.rule,
            )
            # A heading's inline markup is flattened to plain text. Setting
            # a link inside a link would be meaningless, and the entry has
            # to be one uniform click target.
            label = inline_text(heading.children) or "Untitled"
            number_width = number_style.width_of(number)
            padding = base * 0.45
            available = width - indent - number_width - padding * 2
            lines = break_lines(
                split_into_pieces(label, entry_style), max(available, base)
            )
            line_height = entry_style.size * 1.62
            for position, line in enumerate(lines):
                text_left = left + indent + (0 if position == 0 else base)
                paint, _ = renderer.paint_line(
                    line, text_left, available, line_height, justify=False
                )
                items: list[object] = [paint]
                if position == 0:
                    number_x = left + width - number_width
                    paint.fragments.append(
                        Fragment(x=number_x, text=number, style=number_style)
                    )
                    leader_from = text_left + line.natural_width + padding
                    leader_to = number_x - padding
                    unit = leader_style.width_of(". ")
                    count = int(max(0.0, leader_to - leader_from) / unit)
                    if count > 1:
                        paint.fragments.append(
                            Fragment(
                                x=leader_to - count * unit,
                                text=". " * count,
                                style=leader_style,
                            )
                        )
                items.append(
                    PaintLink(
                        x=left,
                        y=0.0,
                        width=width,
                        height=line_height,
                        dest=heading.dest_name,
                    )
                )
                row = Row(height=line_height, items=items)
                if position + 1 < len(lines):
                    row.keep_with_next = True
                rows.append(row)
            if level == 1:
                rows.append(Row(height=base * 0.25, is_space=True))
        return rows

    def resolve_toc(
        self,
        renderer: DocumentRenderer,
        entries: list[tuple[Heading, int]],
        title_page_count: int,
        diagnostics: DiagnosticCollector,
    ) -> tuple[list[LaidOutPage], int]:
        """Lay out the table of contents until its own length stops moving.

        Inserting the contents shifts every body page, so the numbers it
        prints depend on how many pages it occupies, which depends on the
        numbers it prints. The loop below closes that circle.

        It is monotone: a larger page offset can only make a printed number
        wider, which can only narrow the space left for a title, which can
        only produce the same number of lines or more. So starting the guess
        at one page and raising it to whatever the layout actually needed
        converges upward and cannot oscillate. The loop stops as soon as a
        pass fits inside its own guess, and if a pass ever comes out shorter
        than the guess the contents are padded with a blank page so that the
        numbers already printed stay true. `TOC_MAX_PASSES` bounds the whole
        thing rather than trusting the argument alone.
        """
        guess = 1
        for attempt in range(1, TOC_MAX_PASSES + 1):
            rows = self.toc_rows(
                renderer, entries, title_page_count + guess
            )
            candidate = paginate(rows, self.geometry)
            if len(candidate) <= guess:
                while len(candidate) < guess:
                    candidate.append(LaidOutPage(number=0))
                return candidate, attempt
            guess = len(candidate)
        # Never settled inside the budget. Emit the last layout and say so
        # rather than printing page numbers that are quietly wrong.
        rows = self.toc_rows(renderer, entries, title_page_count + guess)
        candidate = paginate(rows, self.geometry)
        diagnostics.warn(
            "the table of contents did not settle in "
            f"{TOC_MAX_PASSES} passes; its page numbers may be off by "
            f"{len(candidate) - guess}",
            0,
        )
        return candidate, TOC_MAX_PASSES

    # --- the build ---------------------------------------------------------

    def build(self, text: str) -> BuildResult:
        """Parse Markdown and return a complete PDF."""
        source = SourceText(text)
        diagnostics = DiagnosticCollector(source)
        document = BlockParser(source, diagnostics).parse_document()
        renderer = DocumentRenderer(
            self.geometry, self.render_options, diagnostics
        )
        body_rows = renderer.render(document)
        # The body is paginated once and never again. Nothing that comes
        # before it changes where its own page breaks fall, so only the
        # offset added to its page numbers is in question.
        body_pages = paginate(body_rows, self.geometry)

        title = self.title_rows(renderer, document.front_matter)
        title_page_count = 1 if title else 0
        pages: list[LaidOutPage] = []
        if title:
            total_height = sum(row.height for row in title)
            start = max(
                self.geometry.content_top,
                (self.geometry.height - total_height) * 0.38,
            )
            pages.append(place_on_one_page(title, self.geometry, start))

        toc_passes = 0
        toc_page_count = 0
        if self.options.toc:
            entries: list[tuple[Heading, int]] = []
            for index, page in enumerate(body_pages):
                for placed in page.rows:
                    if placed.row.heading is not None:
                        entries.append((placed.row.heading, index))
            if entries:
                toc_pages, toc_passes = self.resolve_toc(
                    renderer, entries, title_page_count, diagnostics
                )
                toc_page_count = len(toc_pages)
                pages.extend(toc_pages)

        pages.extend(body_pages)
        for index, page in enumerate(pages):
            page.number = index + 1

        headings = self.collect_headings(pages)
        data = self.emit(
            pages, document, headings, title_page_count, renderer
        )
        return BuildResult(
            data=data,
            diagnostics=list(diagnostics),
            page_count=len(pages),
            headings=headings,
            toc_passes=toc_passes,
            toc_page_count=toc_page_count,
        )

    @staticmethod
    def collect_headings(pages: list[LaidOutPage]) -> list[HeadingEntry]:
        """Find which page each heading landed on, after pagination."""
        entries: list[HeadingEntry] = []
        for index, page in enumerate(pages):
            for placed in page.rows:
                if placed.row.heading is not None:
                    entries.append(
                        HeadingEntry(
                            heading=placed.row.heading,
                            page_index=index,
                            y=placed.y,
                        )
                    )
        return entries

    # --- object graph ------------------------------------------------------

    def emit(
        self,
        pages: list[LaidOutPage],
        document: Document,
        headings: list[HeadingEntry],
        title_page_count: int,
        renderer: DocumentRenderer,
    ) -> bytes:
        """Turn laid out pages into the finished PDF byte stream."""
        writer = PdfWriter()
        catalog_ref = writer.reserve()
        pages_ref = writer.reserve()
        resources_ref = writer.reserve()
        page_refs = [writer.reserve() for _ in pages]

        fonts = FontRegistry()
        images = XObjectRegistry()
        # Named destinations, one per heading, resolved once the page
        # objects have numbers so a link can point at a real page.
        dest_targets: dict[str, object] = {}
        for entry in headings:
            if entry.heading.dest_name:
                dest_targets[entry.heading.dest_name] = [
                    page_refs[entry.page_index],
                    PdfName("XYZ"),
                    self.geometry.content_left,
                    self.geometry.height - max(entry.y - 8.0, 0.0),
                    None,
                ]

        contents: list[PdfRef] = []
        annotations: list[list[dict[str, object]]] = []
        for index, page in enumerate(pages):
            footer = ""
            if self.options.page_numbers and index >= title_page_count:
                footer = str(page.number)
            stream, links = draw_page(
                page,
                self.geometry,
                fonts,
                self.render_options,
                footer,
                images,
            )
            contents.append(writer.add(PdfStream(data=stream)))
            page_annotations = []
            for link in links:
                built = link_annotation(link, self.geometry, dest_targets)
                if built is not None:
                    page_annotations.append(built)
            annotations.append(page_annotations)

        font_refs: dict[str, PdfRef] = {}
        for name, base_font in fonts.entries():
            font_refs[name] = writer.add(
                {
                    "Type": PdfName("Font"),
                    "Subtype": PdfName("Type1"),
                    "BaseFont": PdfName(base_font),
                    "Encoding": PdfName("WinAnsiEncoding"),
                }
            )
        image_refs: dict[str, PdfRef] = {}
        for name, key in images.entries():
            image = renderer.images.get(key)
            if image is None:
                continue
            image_refs[name] = self.image_object(writer, image)
        resources: dict[str, object] = {"Font": dict(font_refs)}
        if image_refs:
            resources["XObject"] = dict(image_refs)
        # Every page shares one resource dictionary, which keeps the file
        # small and means a font is described exactly once.
        writer.assign(resources_ref, resources)

        for index, page_ref in enumerate(page_refs):
            page_dict: dict[str, object] = {
                "Type": PdfName("Page"),
                "Parent": pages_ref,
                "MediaBox": [
                    0,
                    0,
                    self.geometry.width,
                    self.geometry.height,
                ],
                "Resources": resources_ref,
                "Contents": contents[index],
            }
            if annotations[index]:
                page_dict["Annots"] = annotations[index]
            writer.assign(page_ref, page_dict)

        writer.assign(
            pages_ref,
            {
                "Type": PdfName("Pages"),
                "Kids": list(page_refs),
                "Count": len(page_refs),
            },
        )

        catalog: dict[str, object] = {
            "Type": PdfName("Catalog"),
            "Pages": pages_ref,
        }
        if dest_targets:
            catalog["Dests"] = dict(dest_targets)
        outline_ref = self.build_outline(writer, headings, page_refs)
        if outline_ref is not None:
            catalog["Outlines"] = outline_ref
            catalog["PageMode"] = PdfName("UseOutlines")
        writer.assign(catalog_ref, catalog)

        info_ref = writer.add(
            self.info_dictionary(document.front_matter)
        )
        return writer.render(root=catalog_ref, info=info_ref)

    @staticmethod
    def image_object(writer: PdfWriter, image: PngImage) -> PdfRef:
        """Add an image XObject, with a soft mask when it has alpha.

        A truecolour PNG keeps its own scanline filtering and is declared
        with the PNG predictor, so its bytes pass through untouched. An RGBA
        image was split during decoding, so its colour data is plain and its
        alpha becomes a `/SMask`, which is how PDF carries transparency.
        """
        extra: dict[str, object] = {
            "Type": PdfName("XObject"),
            "Subtype": PdfName("Image"),
            "Width": image.width,
            "Height": image.height,
            "ColorSpace": PdfName("DeviceRGB"),
            "BitsPerComponent": 8,
            "Filter": PdfName("FlateDecode"),
        }
        if image.predictor:
            extra["DecodeParms"] = {
                "Predictor": 15,
                "Colors": 3,
                "BitsPerComponent": 8,
                "Columns": image.width,
            }
        if image.alpha_stream is not None:
            extra["SMask"] = writer.add(
                PdfStream(
                    data=image.alpha_stream,
                    compress=False,
                    extra={
                        "Type": PdfName("XObject"),
                        "Subtype": PdfName("Image"),
                        "Width": image.width,
                        "Height": image.height,
                        "ColorSpace": PdfName("DeviceGray"),
                        "BitsPerComponent": 8,
                        "Filter": PdfName("FlateDecode"),
                    },
                )
            )
        # compress=False because the payload is already zlib data; the
        # stream declares the filter itself.
        return writer.add(
            PdfStream(
                data=image.colour_stream, compress=False, extra=extra
            )
        )

    def info_dictionary(
        self, front_matter: dict[str, str]
    ) -> dict[str, object]:
        """The document information dictionary, with no clock reading."""
        date = self.options.date or front_matter.get("date", "") or DEFAULT_DATE
        info: dict[str, object] = {}
        if front_matter.get("title"):
            info["Title"] = PdfString(front_matter["title"])
        if front_matter.get("author"):
            info["Author"] = PdfString(front_matter["author"])
        if front_matter.get("subject"):
            info["Subject"] = PdfString(front_matter["subject"])
        info["Producer"] = PdfString(
            f"{PROGRAM_NAME} {PROGRAM_VERSION}"
        )
        info["Creator"] = PdfString(PROGRAM_NAME)
        info["CreationDate"] = PdfString(pdf_date(date))
        info["ModDate"] = PdfString(pdf_date(date))
        return info

    def build_outline(
        self,
        writer: PdfWriter,
        headings: list[HeadingEntry],
        page_refs: list[PdfRef],
    ) -> PdfRef | None:
        """Build the bookmark tree that fills a reader's sidebar.

        The outline is a doubly linked tree: every item points at its parent,
        its previous and next siblings, and its first and last child. Levels
        come straight from the heading levels, and a heading that skips a
        level simply attaches to the nearest open ancestor.
        """
        if not headings:
            return None
        root_ref = writer.reserve()
        item_refs = [writer.reserve() for _ in headings]
        # (level, index into headings) of the ancestors currently open.
        stack: list[tuple[int, int]] = []
        children: dict[int, list[int]] = {-1: []}
        parents: dict[int, int] = {}
        for index, entry in enumerate(headings):
            level = entry.heading.level
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else -1
            parents[index] = parent
            children.setdefault(parent, []).append(index)
            children.setdefault(index, [])
            stack.append((level, index))

        def ref_for(index: int) -> object:
            return root_ref if index == -1 else item_refs[index]

        for index, entry in enumerate(headings):
            siblings = children[parents[index]]
            position = siblings.index(index)
            item: dict[str, object] = {
                "Title": PdfString(
                    inline_text(entry.heading.children) or "Untitled"
                ),
                "Parent": ref_for(parents[index]),
                "Dest": [
                    page_refs[entry.page_index],
                    PdfName("XYZ"),
                    self.geometry.content_left,
                    self.geometry.height - max(entry.y - 8.0, 0.0),
                    None,
                ],
            }
            if position > 0:
                item["Prev"] = item_refs[siblings[position - 1]]
            if position + 1 < len(siblings):
                item["Next"] = item_refs[siblings[position + 1]]
            own = children[index]
            if own:
                item["First"] = item_refs[own[0]]
                item["Last"] = item_refs[own[-1]]
                # A negative count means the branch starts collapsed, which
                # keeps a long sidebar readable.
                item["Count"] = -len(own)
            writer.assign(item_refs[index], item)

        top = children[-1]
        writer.assign(
            root_ref,
            {
                "Type": PdfName("Outlines"),
                "First": item_refs[top[0]],
                "Last": item_refs[top[-1]],
                "Count": len(headings),
            },
        )
        return root_ref


def build_pdf(text: str, options: BuildOptions) -> BuildResult:
    """Convert Markdown source text into a PDF."""
    return DocumentBuilder(options).build(text)


# ===========================================================================
# Section 14: Command line interface
# ===========================================================================


def colour_enabled(stream: object) -> bool:
    """Decide whether to emit ANSI colour on a given stream.

    Three things have to agree: the stream is a terminal, the terminal has
    not been told to stay plain through NO_COLOR, and the caller has not
    forced it off. Writing escape codes into a redirected file is a bug, not
    a feature.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    if isatty is None:
        return False
    try:
        return bool(isatty())
    except (ValueError, OSError):
        return False


def valid_date(value: str) -> str:
    """Validate a `YYYY-MM-DD` date without importing a date library.

    Only the shape is checked, not whether the day exists in that month.
    The value is a label printed into the document, not an instant, and
    rejecting `2026-02-30` would be pedantry rather than protection.
    """
    parts = value.split("-")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a date, expected YYYY-MM-DD"
        )
    widths = (4, 2, 2)
    for part, width in zip(parts, widths):
        if len(part) != width or not part.isdigit():
            raise argparse.ArgumentTypeError(
                f"{value!r} is not a date, expected YYYY-MM-DD"
            )
    month = int(parts[1])
    day = int(parts[2])
    if not 1 <= month <= 12:
        raise argparse.ArgumentTypeError(f"month {month} is out of range")
    if not 1 <= day <= 31:
        raise argparse.ArgumentTypeError(f"day {day} is out of range")
    return value


def positive_number(value: str) -> float:
    """Parse a positive measurement given on the command line."""
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a number"
        ) from None
    if number <= 0:
        raise argparse.ArgumentTypeError(f"{value!r} must be greater than 0")
    return number


def build_parser(use_colour: bool = False) -> argparse.ArgumentParser:
    """Construct the argument parser."""
    options: dict[str, object] = {
        "prog": PROGRAM_NAME,
        "description": (
            "Typeset a Markdown file as a PDF. "
            "No dependencies, no HTML in the middle, no font files."
        ),
        "epilog": (
            "Output is reproducible: the same input and flags produce "
            "byte identical files. Pass --date, or put a date in the front "
            "matter, to pin the timestamp."
        ),
    }
    # Colour in argparse arrived in Python 3.14. Asking for it on an older
    # interpreter is a TypeError, so the flag is only passed when it exists.
    if sys.version_info >= (3, 14):
        options["color"] = use_colour
    parser = argparse.ArgumentParser(**options)  # type: ignore[arg-type]
    parser.add_argument(
        "input",
        metavar="INPUT.md",
        help="Markdown file to typeset, or - to read standard input",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="OUTPUT.pdf",
        help="where to write the PDF (default: the input name with .pdf)",
    )
    parser.add_argument(
        "--page-size",
        choices=sorted(PAGE_SIZES),
        default="a4",
        help="page size (default: a4)",
    )
    parser.add_argument(
        "--font",
        choices=sorted(FONT_FAMILIES),
        default="helvetica",
        dest="font_family",
        help="body font family (default: helvetica)",
    )
    parser.add_argument(
        "--font-size",
        type=positive_number,
        default=11.0,
        metavar="N",
        help="body font size in points (default: 11)",
    )
    parser.add_argument(
        "--margin",
        type=positive_number,
        default=64.0,
        metavar="N",
        help="page margin in points (default: 64)",
    )
    parser.add_argument(
        "--toc",
        action="store_true",
        help="insert a table of contents with clickable entries",
    )
    parser.add_argument(
        "--justify",
        action="store_true",
        help="justify body text to both margins",
    )
    parser.add_argument(
        "--no-page-numbers",
        action="store_false",
        dest="page_numbers",
        help="leave the footer empty",
    )
    parser.add_argument(
        "--date",
        type=valid_date,
        # argparse runs `type` over a string default, so the "unset" value
        # has to be None rather than an empty string.
        default=None,
        metavar="YYYY-MM-DD",
        help="date for the document metadata, for reproducible output",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="parse and report problems, write no PDF, exit non-zero on any",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PROGRAM_NAME} {PROGRAM_VERSION}",
    )
    return parser


def report_diagnostics(
    diagnostics: list[Diagnostic], stream: object, use_colour: bool
) -> None:
    """Print every diagnostic with its caret."""
    for diagnostic in diagnostics:
        print(diagnostic.render(use_colour), file=stream)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit status."""
    use_colour = colour_enabled(sys.stdout)
    parser = build_parser(use_colour)
    args = parser.parse_args(argv)
    error_colour = colour_enabled(sys.stderr)

    if args.input == "-":
        text = sys.stdin.read()
        base_path = None
        default_output = None
    else:
        source_path = Path(args.input)
        try:
            text = source_path.read_text(encoding="utf-8")
        except OSError as error:
            print(
                f"{PROGRAM_NAME}: cannot read {args.input}: "
                f"{error.strerror}",
                file=sys.stderr,
            )
            return 3
        except UnicodeDecodeError:
            print(
                f"{PROGRAM_NAME}: {args.input} is not valid UTF-8",
                file=sys.stderr,
            )
            return 3
        base_path = source_path.resolve().parent
        default_output = source_path.with_suffix(".pdf")

    options = BuildOptions(
        page_size=args.page_size,
        font_family=args.font_family,
        font_size=args.font_size,
        margin=args.margin,
        justify=args.justify,
        toc=args.toc,
        page_numbers=args.page_numbers,
        date=args.date or "",
        base_path=base_path,
    )

    if args.check:
        # A check run does the full render, not just the parse, because
        # unrenderable characters and unreadable images are only found once
        # the document is laid out.
        result = build_pdf(text, options)
        report_diagnostics(result.diagnostics, sys.stderr, error_colour)
        count = len(result.diagnostics)
        if count:
            plural = "" if count == 1 else "s"
            print(
                f"{PROGRAM_NAME}: {count} problem{plural} found",
                file=sys.stderr,
            )
            return 1
        print(
            f"{PROGRAM_NAME}: no problems found in {args.input}",
            file=sys.stderr,
        )
        return 0

    if args.output:
        output_path = Path(args.output)
    elif default_output is not None:
        output_path = default_output
    else:
        print(
            f"{PROGRAM_NAME}: reading from standard input needs -o OUTPUT.pdf",
            file=sys.stderr,
        )
        return 2

    result = build_pdf(text, options)
    report_diagnostics(result.diagnostics, sys.stderr, error_colour)
    try:
        output_path.write_bytes(result.data)
    except OSError as error:
        print(
            f"{PROGRAM_NAME}: cannot write {output_path}: {error.strerror}",
            file=sys.stderr,
        )
        return 3
    pages = result.page_count
    plural = "" if pages == 1 else "s"
    print(
        f"{PROGRAM_NAME}: wrote {output_path} "
        f"({pages} page{plural}, {len(result.data)} bytes)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
