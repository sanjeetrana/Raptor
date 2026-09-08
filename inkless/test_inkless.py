#!/usr/bin/env python3
"""Test suite for inkless.

Run with:

    python -m unittest test_inkless -v

The tests are table driven, as the brief requires: one method walks a list of
tuples with `subTest` so a single failure names the exact case rather than
stopping the run. Groups, in order:

    TestSourcePositions      offsets, byte offsets, lines and columns
    TestBlockParsing         every block construct, flat and nested
    TestInlineParsing        emphasis, code, links, images, escapes
    TestMalformedInput       broken documents, with exact caret positions
    TestFontMetrics          known strings at known sizes
    TestPdfPrimitives        number, name and string serialisation
    TestPdfEscaping          round trip through the emitted PDF
    TestPdfStructure         a small PDF reader checks our own output
    TestDeterminism          byte identical output across builds
    TestZeroDependency       the build fails if a dependency creeps in

`re` is deliberately not imported here either. It is permitted in this file
by the brief, but every assertion below is either an equality check or a
substring check, so a regular expression would add a dependency on regex
semantics without buying anything.
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inkless as k

REPO_ROOT = Path(__file__).resolve().parent
ENGINE_PATH = REPO_ROOT / "inkless.py"


def tree(source: str) -> str:
    """Parse Markdown and return the compact tree notation."""
    document, _ = k.parse_markdown(source)
    return k.sexp(document)


def warnings_for(source: str) -> list[k.Diagnostic]:
    """Parse Markdown and return only the diagnostics."""
    _, diagnostics = k.parse_markdown(source)
    return diagnostics


# ===========================================================================
# A minimal PDF reader, written here so the tests never trust the writer's
# own bookkeeping. It re-derives everything from the finished bytes.
# ===========================================================================


class MiniPdf:
    """A deliberately small PDF reader used only to check our own output.

    It reads the trailer, walks the cross-reference table, and can hand back
    the raw bytes of any indirect object and the decoded content of any
    literal string. That is enough to prove the structure is sound without
    pretending to be a general PDF parser.
    """

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.problems: list[str] = []
        self.xref: list[tuple[int, bytes]] = []
        self.trailer = b""
        self.startxref = -1
        self._read()

    # --- structure ---------------------------------------------------------

    def _read(self) -> None:
        data = self.data
        if not data.startswith(b"%PDF-"):
            self.problems.append("file does not start with %PDF-")
            return
        if not data.rstrip(b"\r\n \t").endswith(b"%%EOF"):
            self.problems.append("file does not end with %%EOF")
        marker = data.rfind(b"startxref")
        if marker == -1:
            self.problems.append("no startxref keyword")
            return
        tail = data[marker + len("startxref") :]
        digits = []
        for character in tail:
            glyph = chr(character)
            if glyph.isdigit():
                digits.append(glyph)
            elif digits:
                break
        if not digits:
            self.problems.append("startxref is not followed by a number")
            return
        self.startxref = int("".join(digits))
        if data[self.startxref : self.startxref + 4] != b"xref":
            self.problems.append(
                f"startxref points at byte {self.startxref}, "
                "which is not the xref keyword"
            )
            return
        cursor = self.startxref + len(b"xref")
        while cursor < len(data) and data[cursor] in b"\r\n":
            cursor += 1
        line_end = data.index(b"\n", cursor)
        header = data[cursor:line_end].split()
        if len(header) != 2:
            self.problems.append("xref subsection header is malformed")
            return
        first_number, count = int(header[0]), int(header[1])
        if first_number != 0:
            self.problems.append("xref subsection does not start at object 0")
        entry_start = line_end + 1
        for index in range(count):
            record = data[
                entry_start + index * 20 : entry_start + index * 20 + 20
            ]
            if len(record) != 20:
                self.problems.append(f"xref entry {index} is short")
                return
            if record[10:11] != b" " or record[16:17] != b" ":
                self.problems.append(
                    f"xref entry {index} is not the fixed 20 byte layout"
                )
            if record[17:18] not in (b"n", b"f"):
                self.problems.append(f"xref entry {index} has no type flag")
            self.xref.append((int(record[0:10]), record[17:18]))
        trailer_at = data.find(b"trailer", entry_start + count * 20)
        if trailer_at == -1:
            self.problems.append("no trailer keyword")
        else:
            self.trailer = data[trailer_at:marker]

    def check_offsets(self) -> list[str]:
        """Confirm every xref offset lands on its own object header."""
        problems: list[str] = []
        for number, (offset, kind) in enumerate(self.xref):
            if number == 0:
                if kind != b"f":
                    problems.append("object 0 is not marked free")
                if offset != 0:
                    problems.append("object 0 does not have offset 0")
                continue
            if kind != b"n":
                problems.append(f"object {number} is not marked in use")
                continue
            expected = b"%d 0 obj" % number
            found = self.data[offset : offset + len(expected)]
            if found != expected:
                problems.append(
                    f"object {number}: xref offset {offset} holds {found!r}, "
                    f"expected {expected!r}"
                )
        return problems

    @property
    def size(self) -> int:
        return len(self.xref)

    def raw_object(self, number: int) -> bytes:
        """Bytes of one indirect object, from its header to `endobj`."""
        offset = self.xref[number][0]
        end = self.data.index(b"endobj", offset)
        return self.data[offset:end]

    def referenced_numbers(self) -> set[int]:
        """Every object number that appears as an `N 0 R` reference."""
        found: set[int] = set()
        data = self.data
        cursor = 0
        while True:
            cursor = data.find(b" 0 R", cursor)
            if cursor == -1:
                return found
            probe = cursor - 1
            digits = []
            while probe >= 0 and chr(data[probe]).isdigit():
                digits.append(chr(data[probe]))
                probe -= 1
            if digits:
                found.add(int("".join(reversed(digits))))
            cursor += 4

    # --- content -----------------------------------------------------------

    def stream_data(self, number: int) -> bytes:
        """Decompressed payload of a stream object, with /Length checked."""
        body = self.raw_object(number)
        start = body.index(b"stream") + len(b"stream")
        if body[start : start + 2] == b"\r\n":
            start += 2
        elif body[start : start + 1] == b"\n":
            start += 1
        end = body.rindex(b"endstream")
        # Exactly one end of line separates the data from the `endstream`
        # keyword and is not part of the data. Stripping every trailing
        # newline instead would eat a byte whenever the payload itself ends
        # in one, which is how this reader first disagreed with /Length.
        if body[end - 2 : end] == b"\r\n":
            end -= 2
        elif body[end - 1 : end] in (b"\n", b"\r"):
            end -= 1
        payload = body[start:end]
        declared = self._declared_length(body)
        if declared is not None and declared != len(payload):
            raise AssertionError(
                f"object {number}: /Length says {declared} but the stream "
                f"holds {len(payload)} bytes"
            )
        if b"/FlateDecode" in body[: body.index(b"stream")]:
            return zlib.decompress(payload)
        return payload

    @staticmethod
    def _declared_length(body: bytes) -> int | None:
        at = body.find(b"/Length")
        if at == -1:
            return None
        digits = []
        for character in body[at + len(b"/Length") :]:
            glyph = chr(character)
            if glyph.isdigit():
                digits.append(glyph)
            elif digits:
                break
        return int("".join(digits)) if digits else None

    def all_stream_numbers(self) -> list[int]:
        numbers = []
        for number in range(1, self.size):
            if b"stream" in self.raw_object(number):
                numbers.append(number)
        return numbers


def decode_literal_strings(data: bytes) -> list[bytes]:
    """Pull every `( ... )` literal out of a byte run and unescape it.

    This is the inverse of `inkless.encode_literal_string`, written
    separately so that a bug shared between an encoder and its own decoder
    cannot hide. Escapes handled: `\\(`, `\\)`, `\\\\`, the single letter
    escapes, a backslash before a newline, and three digit octal.
    """
    results: list[bytes] = []
    cursor = 0
    length = len(data)
    simple = {
        ord("n"): 0x0A,
        ord("r"): 0x0D,
        ord("t"): 0x09,
        ord("b"): 0x08,
        ord("f"): 0x0C,
    }
    while cursor < length:
        if data[cursor] != ord("("):
            cursor += 1
            continue
        cursor += 1
        depth = 1
        out = bytearray()
        while cursor < length and depth:
            byte = data[cursor]
            if byte == ord("\\"):
                cursor += 1
                if cursor >= length:
                    break
                escaped = data[cursor]
                if escaped in simple:
                    out.append(simple[escaped])
                    cursor += 1
                elif ord("0") <= escaped <= ord("7"):
                    octal = ""
                    while (
                        cursor < length
                        and len(octal) < 3
                        and ord("0") <= data[cursor] <= ord("7")
                    ):
                        octal += chr(data[cursor])
                        cursor += 1
                    out.append(int(octal, 8))
                elif escaped == 0x0A:
                    cursor += 1
                else:
                    out.append(escaped)
                    cursor += 1
                continue
            if byte == ord("("):
                depth += 1
            elif byte == ord(")"):
                depth -= 1
                if depth == 0:
                    cursor += 1
                    break
            out.append(byte)
            cursor += 1
        results.append(bytes(out))
    return results


def build_pdf_with_text(
    lines: list[str], title: str = "test", compress: bool = True
) -> bytes:
    """Build a one page PDF containing the given lines, via PdfWriter.

    Sections 8 and later will render whole documents; until then this is how
    the writer is exercised end to end.
    """
    page_width, page_height = k.PAGE_SIZES["a4"]
    writer = k.PdfWriter()
    catalog_ref = writer.reserve()
    pages_ref = writer.reserve()
    page_ref = writer.reserve()
    font_ref = writer.add(
        {
            "Type": k.PdfName("Font"),
            "Subtype": k.PdfName("Type1"),
            "BaseFont": k.PdfName("Helvetica"),
            "Encoding": k.PdfName("WinAnsiEncoding"),
        }
    )
    content = bytearray()
    top = 72.0
    for line in lines:
        encoded, _ = k.encode_winansi(line)
        content += b"BT\n/F1 11 Tf\n1 0 0 1 72 "
        content += k.format_number(page_height - top) + b" Tm\n"
        content += k.encode_literal_string(encoded) + b" Tj\nET\n"
        top += 14
    contents_ref = writer.add(
        k.PdfStream(data=bytes(content), compress=compress)
    )
    writer.assign(
        page_ref,
        {
            "Type": k.PdfName("Page"),
            "Parent": pages_ref,
            "MediaBox": [0, 0, page_width, page_height],
            "Resources": {"Font": {"F1": font_ref}},
            "Contents": contents_ref,
        },
    )
    writer.assign(
        pages_ref,
        {"Type": k.PdfName("Pages"), "Kids": [page_ref], "Count": 1},
    )
    writer.assign(
        catalog_ref, {"Type": k.PdfName("Catalog"), "Pages": pages_ref}
    )
    info_ref = writer.add(
        {
            "Title": k.PdfString(title),
            "Producer": k.PdfString("inkless " + k.PROGRAM_VERSION),
            "CreationDate": k.PdfString(k.pdf_date(k.DEFAULT_DATE)),
        }
    )
    return writer.render(root=catalog_ref, info=info_ref)


# ===========================================================================
# Group 1: source positions
# ===========================================================================


class TestSourcePositions(unittest.TestCase):
    """Offsets, byte offsets, lines and columns must be exact everywhere."""

    DOCUMENTS = [
        "",
        "a",
        "hello\nworld\n",
        "no trailing newline",
        "\n\n\nblank leading lines\n",
        "unicode: café naïve ångström\nsecond line\n",
        "emoji \U0001f600 then text\nand more\n",
        "tabs\there\n\tindented\n",
        "windows\r\nline\r\nendings\r\n",
        "mixed é\r\nlines\n中文\n",
    ]

    def test_positions_match_independent_computation(self) -> None:
        """Every offset agrees with a separately computed line and column."""
        for raw in self.DOCUMENTS:
            source = k.SourceText(raw)
            text = source.text
            # Independent reference: walk the text once, counting by hand.
            expected: list[tuple[int, int, int]] = []
            line = 1
            column = 1
            byte_offset = 0
            for character in text:
                expected.append((byte_offset, line, column))
                byte_offset += len(character.encode("utf-8"))
                if character == "\n":
                    line += 1
                    column = 1
                else:
                    column += 1
            expected.append((byte_offset, line, column))
            for offset, (want_bytes, want_line, want_col) in enumerate(
                expected
            ):
                with self.subTest(document=raw[:20], offset=offset):
                    position = source.position(offset)
                    self.assertEqual(position.offset, offset)
                    self.assertEqual(position.byte_offset, want_bytes)
                    self.assertEqual(position.line, want_line)
                    self.assertEqual(position.column, want_col)

    def test_byte_offset_differs_from_character_offset(self) -> None:
        """A multi byte character pushes the byte offset ahead of the index."""
        source = k.SourceText("ééx")
        self.assertEqual(source.position(2).offset, 2)
        self.assertEqual(source.position(2).byte_offset, 4)

    def test_crlf_is_normalised_before_indexing(self) -> None:
        source = k.SourceText("a\r\nb")
        self.assertEqual(source.text, "a\nb")
        self.assertEqual(source.position(2).line, 2)
        self.assertEqual(source.position(2).column, 1)

    def test_line_text_round_trip(self) -> None:
        source = k.SourceText("one\ntwo\nthree")
        self.assertEqual(source.line_text(1), "one")
        self.assertEqual(source.line_text(2), "two")
        self.assertEqual(source.line_text(3), "three")
        self.assertEqual(source.line_text(9), "")

    def test_offset_is_clamped_to_the_document(self) -> None:
        source = k.SourceText("abc")
        self.assertEqual(source.position(999).offset, 3)
        self.assertEqual(source.position(-5).offset, 0)

    def test_every_node_carries_a_position(self) -> None:
        """No AST node may be built without a source position."""
        source = (
            "---\ntitle: T\n---\n\n# Head\n\ntext *em* `c` [l](u)\n\n"
            "- item\n  - nested\n\n> quote\n\n```py\nx\n```\n\n"
            "| a | b |\n|---|---|\n| 1 | 2 |\n\n---\n"
        )
        document, _ = k.parse_markdown(source)
        count = 0
        for node in k.walk(document):
            count += 1
            with self.subTest(node=type(node).__name__):
                self.assertIsInstance(node.pos, k.Position)
                self.assertGreaterEqual(node.pos.offset, 0)
                self.assertLessEqual(node.pos.offset, len(source))
                self.assertGreaterEqual(node.pos.line, 1)
                self.assertGreaterEqual(node.pos.column, 1)
        self.assertGreater(count, 20)

    def test_node_positions_point_at_the_right_text(self) -> None:
        """A node's offset must index the characters that produced it."""
        source = "# Title\n\nsome **bold** text\n"
        document, _ = k.parse_markdown(source)
        heading = document.children[0]
        self.assertEqual(source[heading.pos.offset], "#")
        paragraph = document.children[1]
        self.assertTrue(source[paragraph.pos.offset :].startswith("some"))
        strong = paragraph.children[1]
        self.assertIsInstance(strong, k.Strong)
        self.assertTrue(source[strong.pos.offset :].startswith("**bold**"))
        self.assertEqual(strong.pos.line, 3)
        self.assertEqual(strong.pos.column, 6)


# ===========================================================================
# Group 2: block parsing
# ===========================================================================


class TestBlockParsing(unittest.TestCase):
    """Every block construct, flat and nested, asserted by tree shape."""

    CASES: list[tuple[str, str]] = [
        # --- headings ---
        ("# One", 'doc[h1["One"]]'),
        ("## Two", 'doc[h2["Two"]]'),
        ("### Three", 'doc[h3["Three"]]'),
        ("#### Four", 'doc[h4["Four"]]'),
        ("##### Five", 'doc[h5["Five"]]'),
        ("###### Six", 'doc[h6["Six"]]'),
        ("#NoSpace", 'doc[p["#NoSpace"]]'),
        ("#", "doc[h1[]]"),
        ("#  padded  ", 'doc[h1["padded"]]'),
        ("## closed ##", 'doc[h2["closed"]]'),
        ("## hash#inside", 'doc[h2["hash#inside"]]'),
        ("## trailing###nospace", 'doc[h2["trailing###nospace"]]'),
        ("   # indented three", 'doc[h1["indented three"]]'),
        ("# a\n# b", 'doc[h1["a"] h1["b"]]'),
        # --- paragraphs ---
        ("hello", 'doc[p["hello"]]'),
        ("hello\nworld", 'doc[p["hello" br "world"]]'),
        ("one\n\ntwo", 'doc[p["one"] p["two"]]'),
        ("one\n\n\n\ntwo", 'doc[p["one"] p["two"]]'),
        ("  leading spaces", 'doc[p["leading spaces"]]'),
        ("hello  \nworld", 'doc[p["hello" br! "world"]]'),
        ("", "doc[]"),
        ("\n\n\n", "doc[]"),
        # --- thematic breaks ---
        ("---", "doc[hr]"),
        ("***", "doc[hr]"),
        ("___", "doc[hr]"),
        ("- - -", "doc[hr]"),
        ("*****", "doc[hr]"),
        ("   ---", "doc[hr]"),
        ("--", 'doc[p["--"]]'),
        ("a\n\n---\n\nb", 'doc[p["a"] hr p["b"]]'),
        # --- fenced code ---
        ("```\nx\n```", "doc[code(){x}]"),
        ("```py\nx\n```", "doc[code(py){x}]"),
        ("```python title\nx\n```", "doc[code(python){x}]"),
        ("~~~\nx\n~~~", "doc[code(){x}]"),
        ("````\n```\n````", "doc[code(){```}]"),
        ("```\na\nb\n```", "doc[code(){a\\nb}]"),
        ("```\n\n```", "doc[code(){}]"),
        ("  ```\n  x\n  ```", "doc[code(){x}]"),
        ("```\n  indented\n```", "doc[code(){  indented}]"),
        # --- indented code ---
        ("    x", "doc[code(){x}]"),
        ("    a\n    b", "doc[code(){a\\nb}]"),
        ("    a\n\n    b", "doc[code(){a\\n\\nb}]"),
        ("\tx", "doc[code(){x}]"),
        ("text\n\n    code", 'doc[p["text"] code(){code}]'),
        # --- blockquotes ---
        ("> quote", 'doc[bq[p["quote"]]]'),
        (">quote", 'doc[bq[p["quote"]]]'),
        ("> a\n> b", 'doc[bq[p["a" br "b"]]]'),
        ("> a\nb", 'doc[bq[p["a" br "b"]]]'),
        ("> > deep", "doc[bq[bq[p[\"deep\"]]]]"),
        ("> # heading", 'doc[bq[h1["heading"]]]'),
        ("> - item", 'doc[bq[ul[li[p["item"]]]]]'),
        ("> a\n\n> b", 'doc[bq[p["a"]] bq[p["b"]]]'),
        ("> ```\n> x\n> ```", "doc[bq[code(){x}]]"),
        # --- unordered lists ---
        ("- a", 'doc[ul[li[p["a"]]]]'),
        ("* a", 'doc[ul[li[p["a"]]]]'),
        ("+ a", 'doc[ul[li[p["a"]]]]'),
        ("- a\n- b", 'doc[ul[li[p["a"]] li[p["b"]]]]'),
        ("- a\n\n- b", 'doc[ul~[li[p["a"]] li[p["b"]]]]'),
        ("- a\n- b\n\n* c", 'doc[ul[li[p["a"]] li[p["b"]]] ul[li[p["c"]]]]'),
        ("- a\n  - b", 'doc[ul[li[p["a"] ul[li[p["b"]]]]]]'),
        (
            "- a\n  - b\n    - c",
            'doc[ul[li[p["a"] ul[li[p["b"] ul[li[p["c"]]]]]]]]',
        ),
        ("- a\n\n  second", 'doc[ul~[li[p["a"] p["second"]]]]'),
        ("- ", "doc[ul[li[]]]"),
        ("-", "doc[ul[li[]]]"),
        ("- > quote", 'doc[ul[li[bq[p["quote"]]]]]'),
        ("- ```\n  x\n  ```", "doc[ul[li[code(){x}]]]"),
        # --- ordered lists ---
        ("1. a", 'doc[ol[li[p["a"]]]]'),
        ("1) a", 'doc[ol[li[p["a"]]]]'),
        ("3. a\n4. b", 'doc[ol(3)[li[p["a"]] li[p["b"]]]]'),
        ("1. a\n2. b", 'doc[ol[li[p["a"]] li[p["b"]]]]'),
        ("1. a\n   1. b", 'doc[ol[li[p["a"] ol[li[p["b"]]]]]]'),
        ("1. a\n\n2. b", 'doc[ol~[li[p["a"]] li[p["b"]]]]'),
        ("1. a\n1) b", 'doc[ol[li[p["a"]]] ol[li[p["b"]]]]'),
        ("- a\n1. b", 'doc[ul[li[p["a"]]] ol[li[p["b"]]]]'),
        ("10. ten", 'doc[ol(10)[li[p["ten"]]]]'),
        # --- tables ---
        ("| a |\n|---|", "doc[table(l)[tr[td[\"a\"]]]]"),
        (
            "| a | b |\n|---|---|\n| 1 | 2 |",
            'doc[table(l,l)[tr[td["a"] td["b"]] tr[td["1"] td["2"]]]]',
        ),
        (
            "| a | b |\n|:--|--:|\n| 1 | 2 |",
            'doc[table(l,r)[tr[td["a"] td["b"]] tr[td["1"] td["2"]]]]',
        ),
        (
            "| a |\n|:-:|\n| 1 |",
            'doc[table(c)[tr[td["a"]] tr[td["1"]]]]',
        ),
        (
            "a | b\n--- | ---\n1 | 2",
            'doc[table(l,l)[tr[td["a"] td["b"]] tr[td["1"] td["2"]]]]',
        ),
        (
            "| a |\n|---|\n| **b** |",
            'doc[table(l)[tr[td["a"]] tr[td[b["b"]]]]]',
        ),
        ("| a | b |\n| c | d |", 'doc[p["| a | b |" br "| c | d |"]]'),
        # --- front matter ---
        ("---\ntitle: T\n---\n\nbody", 'doc(title=T)[p["body"]]'),
        (
            "---\ntitle: T\nauthor: A\ndate: 2026-01-01\n---\n",
            "doc(title=T,author=A,date=2026-01-01)[]",
        ),
        ('---\ntitle: "Quoted"\n---\n', "doc(title=Quoted)[]"),
        ("---\ntitle: has: colons\n---\n", "doc(title=has: colons)[]"),
        ("\n---\ntitle: T\n---\n", "doc[hr p[\"title: T\"] hr]"),
        ("---\n---\n\nbody", 'doc[p["body"]]'),
        # --- mixtures ---
        (
            "# H\n\ntext\n\n- a\n\n> q\n\n```\nc\n```\n\n---",
            'doc[h1["H"] p["text"] ul[li[p["a"]]] bq[p["q"]] '
            "code(){c} hr]",
        ),
        (
            "> - a\n>   - b",
            'doc[bq[ul[li[p["a"] ul[li[p["b"]]]]]]]',
        ),
        (
            "1. > quote\n2. plain",
            'doc[ol[li[bq[p["quote"]]] li[p["plain"]]]]',
        ),
    ]

    def test_block_trees(self) -> None:
        for source, expected in self.CASES:
            with self.subTest(source=source):
                self.assertEqual(tree(source), expected)

    def test_case_count_meets_the_brief(self) -> None:
        self.assertGreaterEqual(len(self.CASES), 60)


# ===========================================================================
# Group 3: inline parsing
# ===========================================================================


class TestInlineParsing(unittest.TestCase):
    """Emphasis, code, links, images and escapes, including nesting."""

    CASES: list[tuple[str, str]] = [
        # --- emphasis ---
        ("*a*", 'doc[p[i["a"]]]'),
        ("_a_", 'doc[p[i["a"]]]'),
        ("**a**", 'doc[p[b["a"]]]'),
        ("__a__", 'doc[p[b["a"]]]'),
        ("***a***", 'doc[p[i[b["a"]]]]'),
        ("___a___", 'doc[p[i[b["a"]]]]'),
        ("a *b* c", 'doc[p["a " i["b"] " c"]]'),
        ("**a** and **b**", 'doc[p[b["a"] " and " b["b"]]]'),
        ("*a* *b*", 'doc[p[i["a"] " " i["b"]]]'),
        ("**bold *italic* bold**", 'doc[p[b["bold " i["italic"] " bold"]]]'),
        ("*italic **bold** italic*", 'doc[p[i["italic " b["bold"] " italic"]]]'),
        ("snake_case_name", 'doc[p["snake_case_name"]]'),
        ("a_b_c", 'doc[p["a_b_c"]]'),
        ("a*b*c", 'doc[p["a" i["b"] "c"]]'),
        ("* not a list *", 'doc[ul[li[p["not a list *"]]]]'),
        ("5 * 3 * 2", 'doc[p["5 * 3 * 2"]]'),
        ("**a", 'doc[p["**a"]]'),
        ("a**", 'doc[p["a**"]]'),
        ("****", "doc[hr]"),  # three or more rule characters win
        ("x ****", 'doc[p["x ****"]]'),
        ("*a**b*", 'doc[p[i["a**b"]]]'),
        ("**a*b**", 'doc[p[b["a*b"]]]'),
        # --- code spans ---
        ("`a`", "doc[p[`a`]]"),
        ("``a``", "doc[p[`a`]]"),
        ("`` ` ``", "doc[p[```]]"),
        ("`a b`", "doc[p[`a b`]]"),
        ("`a  b`", "doc[p[`a  b`]]"),
        ("` a `", "doc[p[`a`]]"),
        ("`*not em*`", "doc[p[`*not em*`]]"),
        ("a `b` c", 'doc[p["a " `b` " c"]]'),
        ("`a\nb`", "doc[p[`a b`]]"),
        ("``a`b``", "doc[p[`a`b`]]"),
        # --- links ---
        ("[a](b)", 'doc[p[a(b)["a"]]]'),
        ("[a](http://x.y)", 'doc[p[a(http://x.y)["a"]]]'),
        ('[a](b "t")', 'doc[p[a(b)["a"]]]'),
        ("[a](<b c>)", 'doc[p[a(b c)["a"]]]'),
        ("[a]()", 'doc[p[a()["a"]]]'),
        ("[**a**](b)", 'doc[p[a(b)[b["a"]]]]'),
        ("[*a* and `b`](c)", 'doc[p[a(c)[i["a"] " and " `b`]]]'),
        ("text [a](b) more", 'doc[p["text " a(b)["a"] " more"]]'),
        ("[a](b(c))", 'doc[p[a(b(c))["a"]]]'),
        ("[a[b]c](d)", 'doc[p[a(d)["a[b]c"]]]'),
        ("[not a link]", 'doc[p["[not a link]"]]'),
        ("**[a](b)**", 'doc[p[b[a(b)["a"]]]]'),
        # --- autolinks ---
        ("<http://x.y>", 'doc[p[a(http://x.y)["http://x.y"]]]'),
        ("<https://x.y/z?a=1>", 'doc[p[a(https://x.y/z?a=1)["https://x.y/z?a=1"]]]'),
        ("<a@b.com>", 'doc[p[a(mailto:a@b.com)["a@b.com"]]]'),
        ("<mailto:a@b.com>", 'doc[p[a(mailto:a@b.com)["mailto:a@b.com"]]]'),
        ("<notalink>", 'doc[p["<notalink>"]]'),
        ("a < b", 'doc[p["a < b"]]'),
        # --- images ---
        ("![alt](x.png)", "doc[p[img(x.png)[alt]]]"),
        ("![](x.png)", "doc[p[img(x.png)[]]]"),
        ('![a](x.png "t")', "doc[p[img(x.png)[a]]]"),
        ("text ![a](x.png)", 'doc[p["text " img(x.png)[a]]]'),
        ("[![a](x.png)](y)", 'doc[p[a(y)[img(x.png)[a]]]]'),
        # --- escapes ---
        ("\\*not em\\*", 'doc[p["*not em*"]]'),
        ("\\_a\\_", 'doc[p["_a_"]]'),
        ("\\#not a heading", 'doc[p["#not a heading"]]'),
        ("\\\\", 'doc[p["\\\\"]]'),
        ("\\[a\\](b)", 'doc[p["[a](b)"]]'),
        ("a\\`b", 'doc[p["a`b"]]'),
        ("\\!not an image", 'doc[p["!not an image"]]'),
        ("line\\\nbreak", 'doc[p["line" br! "break"]]'),
        # --- deep nesting ---
        (
            "[**bold *and italic* here**](u)",
            'doc[p[a(u)[b["bold " i["and italic"] " here"]]]]',
        ),
        (
            "***a `b` c***",
            'doc[p[i[b["a " `b` " c"]]]]',
        ),
        (
            "**a [b *c*](d) e**",
            'doc[p[b["a " a(d)["b " i["c"]] " e"]]]',
        ),
        # --- headings and table cells run the same inline parser ---
        ("# *a* **b**", 'doc[h1[i["a"] " " b["b"]]]'),
        ("> *a*", 'doc[bq[p[i["a"]]]]'),
        ("- `a`", "doc[ul[li[p[`a`]]]]"),
    ]

    def test_inline_trees(self) -> None:
        for source, expected in self.CASES:
            with self.subTest(source=source):
                self.assertEqual(tree(source), expected)

    def test_case_count_meets_the_brief(self) -> None:
        self.assertGreaterEqual(len(self.CASES), 55)

    def test_total_parsing_cases_exceed_one_hundred(self) -> None:
        total = len(TestBlockParsing.CASES) + len(self.CASES)
        self.assertGreaterEqual(total, 100)

    def test_inline_text_flattens(self) -> None:
        document, _ = k.parse_markdown("# a **b** `c` [d](e)")
        heading = document.children[0]
        self.assertEqual(k.inline_text(heading.children), "a b c d")


# ===========================================================================
# Group 4: malformed input
# ===========================================================================


class TestMalformedInput(unittest.TestCase):
    """Broken documents must warn, at the exact position of the problem.

    Each case is (source, message substring, line, column). Asserting the
    position is the point: a warning that fires at the wrong place is barely
    better than no warning at all.
    """

    CASES: list[tuple[str, str, int, int]] = [
        # --- unclosed emphasis ---
        ("some **bold text here", "unclosed emphasis", 1, 6),
        ("*italic never closed", "unclosed emphasis", 1, 1),
        ("line one\nline **two", "unclosed emphasis", 2, 6),
        ("a *b **c* d", "unclosed emphasis", 1, 3),
        ("__bold", "unclosed emphasis", 1, 1),
        ("# heading **bold", "unclosed emphasis", 1, 11),
        ("- item *em", "unclosed emphasis", 1, 8),
        ("> quote *em", "unclosed emphasis", 1, 9),
        ("| a |\n|---|\n| *x |", "unclosed emphasis", 3, 3),
        # --- unclosed code spans ---
        ("`code never closed", "unclosed code span", 1, 1),
        ("text ``double", "unclosed code span", 1, 6),
        ("a `b`` c", "unclosed code span", 1, 3),
        # --- unclosed fences ---
        ("```\nnever closed", "unclosed code fence", 1, 1),
        ("```python\nx", "unclosed code fence", 1, 1),
        ("~~~\nx", "unclosed code fence", 1, 1),
        ("text\n\n```\nx", "unclosed code fence", 3, 1),
        ("> ```\n> x", "unclosed code fence", 1, 3),
        # --- broken links ---
        ("[text](unclosed", "unclosed link", 1, 1),
        ("[text](url 'unclosed", "unclosed link title", 1, 12),
        ("a [b](c d) e", "unclosed link", 1, 3),
        ("[unclosed label", "unclosed link label", 1, 1),
        ("![alt](unclosed", "unclosed link", 1, 2),
        # --- stray backslashes ---
        ("a \\z b", "stray backslash", 1, 3),
        ("trailing \\", "stray backslash", 1, 10),
        ("\\q at the start", "stray backslash", 1, 1),
        # --- malformed tables ---
        ("| a | b |\n|---|---|\n| 1 |", "table row has 1 cells", 3, 1),
        (
            "| a | b |\n|---|---|\n| 1 | 2 | 3 |",
            "table row has 3 cells",
            3,
            1,
        ),
        # --- bad headings ---
        ("####### too deep", "only 1 to 6 are levels", 1, 1),
        ("######## also too deep", "only 1 to 6 are levels", 1, 1),
        # --- front matter ---
        ("---\ntitle: T\n", "unclosed front matter", 1, 1),
        ("---\nnot a pair\n---\n", "not `key: value`", 2, 1),
        ("---\n: novalue\n---\n", "not `key: value`", 2, 1),
        ("---\n   : novalue\n---\n", "front matter key is empty", 2, 1),
        ("---\ntitle: A\ntitle: B\n---\n", "duplicate front matter key", 3, 1),
        # --- bad list numbering ---
        ("1. a\n5. b", "numbered 5 where 2 was expected", 2, 1),
        ("1. a\n2. b\n9. c", "numbered 9 where 3 was expected", 3, 1),
    ]

    def test_warning_and_position(self) -> None:
        for source, fragment, line, column in self.CASES:
            with self.subTest(source=source):
                diagnostics = warnings_for(source)
                self.assertTrue(
                    diagnostics,
                    f"expected a warning for {source!r} but got none",
                )
                matching = [
                    diagnostic
                    for diagnostic in diagnostics
                    if fragment in diagnostic.message
                ]
                self.assertTrue(
                    matching,
                    f"no warning contained {fragment!r}; got "
                    + repr([d.message for d in diagnostics]),
                )
                first = matching[0]
                self.assertEqual(
                    (first.position.line, first.position.column),
                    (line, column),
                    f"warning {first.message!r} reported at "
                    f"line {first.position.line} column "
                    f"{first.position.column}",
                )

    def test_case_count_meets_the_brief(self) -> None:
        self.assertGreaterEqual(len(self.CASES), 30)

    def test_caret_lines_up_under_the_column(self) -> None:
        """The rendered caret must sit under the reported column."""
        diagnostics = warnings_for("some **bold text here")
        rendered = diagnostics[0].render()
        lines = rendered.split("\n")
        self.assertEqual(lines[1], "  some **bold text here")
        self.assertEqual(lines[2], "       ^")
        self.assertIn("line 1, column 6", lines[3])

    def test_caret_accounts_for_tabs(self) -> None:
        """A tab before the problem must not push the caret out of line."""
        diagnostics = warnings_for("a\tb **c")
        self.assertTrue(diagnostics)
        rendered = diagnostics[0].render().split("\n")
        caret_column = rendered[2].index("^")
        self.assertEqual(rendered[1][caret_column], "*")

    def test_colour_is_opt_in(self) -> None:
        diagnostic = warnings_for("**x")[0]
        self.assertNotIn("\033", diagnostic.render(use_colour=False))
        self.assertIn("\033[33m", diagnostic.render(use_colour=True))

    def test_clean_documents_produce_no_warnings(self) -> None:
        clean = [
            "# Title\n\nA paragraph.\n",
            "- a\n- b\n",
            "```py\nx = 1\n```\n",
            "| a | b |\n|---|---|\n| 1 | 2 |\n",
            "---\ntitle: T\n---\n\nbody\n",
            "A [link](http://x.y) and `code` and **bold**.\n",
            "> quote\n> more\n",
            "1. one\n2. two\n3. three\n",
            "snake_case and 5 * 3 and a\\*b\n",
        ]
        for source in clean:
            with self.subTest(source=source):
                self.assertEqual(
                    [d.message for d in warnings_for(source)], []
                )

    def test_parsing_never_raises(self) -> None:
        """Malformed input degrades, it does not crash."""
        nasty = [
            "*" * 200,
            "`" * 50,
            "[" * 50,
            "]" * 50,
            "\\" * 50,
            "|" * 50 + "\n" + "-" * 50,
            "#" * 50 + " x",
            "> " * 40 + "deep",
            "- " * 40 + "deep",
            "```" + "\n```" * 30,
            "---\n" * 20,
            "\x00\x01\x02 control characters",
            "\U0001f600" * 20,
        ]
        for source in nasty:
            with self.subTest(source=source[:20]):
                document, _ = k.parse_markdown(source)
                self.assertIsInstance(document, k.Document)
                self.assertIsInstance(k.sexp(document), str)


# ===========================================================================
# Group 5: font metrics
# ===========================================================================


class TestFontMetrics(unittest.TestCase):
    """Known strings at known sizes against widths computed by hand."""

    #: (text, font, size, expected width in points). Expected values are the
    #: sum of the published AFM advance widths times size over 1000.
    CASES: list[tuple[str, str, float, float]] = [
        ("", "Helvetica", 12, 0.0),
        (" ", "Helvetica", 1000, 278.0),
        ("H", "Helvetica", 1000, 722.0),
        ("Hello", "Helvetica", 1000, 2278.0),  # 722+556+222+222+556
        ("Hello", "Helvetica", 12, 27.336),
        ("i", "Helvetica", 1000, 222.0),
        ("W", "Helvetica", 1000, 944.0),
        ("@", "Helvetica", 1000, 1015.0),
        ("0123456789", "Helvetica", 1000, 5560.0),
        ("Hello", "Helvetica-Bold", 1000, 2445.0),  # 722+556+278+278+611
        ("H", "Times-Roman", 1000, 722.0),
        ("Hello", "Times-Roman", 1000, 2222.0),  # 722+444+278+278+500
        ("i", "Times-Roman", 1000, 278.0),
        ("W", "Times-Roman", 1000, 944.0),
        ("Hello", "Times-Bold", 1000, 2278.0),  # 778+444+278+278+500
        ("Hello", "Times-Italic", 1000, 2222.0),  # 722+444+278+278+500
        ("Hello", "Times-BoldItalic", 1000, 2278.0),  # 778+444+278+278+500
        ("Hello", "Courier", 1000, 3000.0),
        ("iiiii", "Courier", 1000, 3000.0),
        ("WWWWW", "Courier", 1000, 3000.0),
        ("x", "Courier-Bold", 10, 6.0),
        ("(", "Helvetica", 1000, 333.0),
        ("\\", "Helvetica", 1000, 278.0),
        ("|", "Times-Roman", 1000, 200.0),
    ]

    def test_known_widths(self) -> None:
        for text, font, size, expected in self.CASES:
            with self.subTest(text=text, font=font, size=size):
                self.assertAlmostEqual(
                    k.measure(text, font, size), expected, places=6
                )

    def test_every_table_covers_the_printable_ascii_range(self) -> None:
        span = k.LAST_METRIC_CODE - k.FIRST_METRIC_CODE + 1
        for name, metrics in k.STANDARD_FONTS.items():
            with self.subTest(font=name):
                self.assertEqual(len(metrics.ascii_widths), span)
                self.assertTrue(all(w > 0 for w in metrics.ascii_widths))

    def test_oblique_matches_upright(self) -> None:
        """The slanted cuts are the same outlines and the same widths."""
        pairs = [
            ("Helvetica", "Helvetica-Oblique"),
            ("Helvetica-Bold", "Helvetica-BoldOblique"),
        ]
        for upright, oblique in pairs:
            with self.subTest(font=oblique):
                self.assertEqual(
                    k.STANDARD_FONTS[upright].ascii_widths,
                    k.STANDARD_FONTS[oblique].ascii_widths,
                )

    def test_courier_is_monospace(self) -> None:
        for code in range(32, 127):
            with self.subTest(code=code):
                self.assertEqual(
                    k.STANDARD_FONTS["Courier"].width_of_code(code), 600
                )

    def test_accented_letters_take_the_base_letter_width(self) -> None:
        """Composed glyphs carry their base letter's advance width."""
        pairs = [
            ("Á", "A"),
            ("é", "e"),
            ("ü", "u"),
            ("ñ", "n"),
            ("Å", "A"),
        ]
        for font in ("Helvetica", "Times-Roman", "Times-Bold"):
            metrics = k.STANDARD_FONTS[font]
            for accented, base in pairs:
                with self.subTest(font=font, character=accented):
                    self.assertEqual(
                        metrics.width_of_code(k.winansi_code(accented)),
                        metrics.width_of_code(ord(base)),
                    )

    def test_unknown_font_is_rejected_loudly(self) -> None:
        with self.assertRaises(KeyError):
            k.measure("x", "Comic-Sans", 12)

    def test_width_grows_with_size(self) -> None:
        small = k.measure("typography", "Helvetica", 10)
        large = k.measure("typography", "Helvetica", 20)
        self.assertAlmostEqual(large, small * 2, places=9)

    def test_width_is_additive(self) -> None:
        joined = k.measure("abcdef", "Times-Roman", 11)
        split = k.measure("abc", "Times-Roman", 11) + k.measure(
            "def", "Times-Roman", 11
        )
        self.assertAlmostEqual(joined, split, places=9)

    def test_unrenderable_characters_are_detected(self) -> None:
        self.assertTrue(k.is_renderable("a"))
        self.assertTrue(k.is_renderable("é"))
        self.assertFalse(k.is_renderable("中"))
        self.assertFalse(k.is_renderable("\U0001f600"))

    def test_font_style_selection(self) -> None:
        family = k.FONT_FAMILIES["times"]
        self.assertEqual(k.font_for_style(family, False, False), "Times-Roman")
        self.assertEqual(k.font_for_style(family, True, False), "Times-Bold")
        self.assertEqual(k.font_for_style(family, False, True), "Times-Italic")
        self.assertEqual(
            k.font_for_style(family, True, True), "Times-BoldItalic"
        )


# ===========================================================================
# Group 6: PDF primitives and escaping
# ===========================================================================


class TestPdfPrimitives(unittest.TestCase):
    """Serialisation of the eight PDF object types."""

    NUMBER_CASES: list[tuple[float, bytes]] = [
        (0, b"0"),
        (1, b"1"),
        (-1, b"-1"),
        (42, b"42"),
        (1.5, b"1.5"),
        (0.1, b"0.1"),
        (595.28, b"595.28"),
        (841.89, b"841.89"),
        (1.0, b"1"),
        (-0.0, b"0"),
        (2.00001, b"2"),
        (1e-9, b"0"),
        (123456.789, b"123456.789"),
    ]

    def test_numbers_never_use_exponent_notation(self) -> None:
        for value, expected in self.NUMBER_CASES:
            with self.subTest(value=value):
                self.assertEqual(k.format_number(value), expected)
        self.assertNotIn(b"e", k.format_number(1e20))
        self.assertNotIn(b"e", k.format_number(1e-20))

    NAME_CASES: list[tuple[str, bytes]] = [
        ("Type", b"/Type"),
        ("F1", b"/F1"),
        ("Helvetica-Bold", b"/Helvetica-Bold"),
        ("A_B", b"/A_B"),
        ("with space", b"/with#20space"),
        ("hash#tag", b"/hash#23tag"),
        ("paren(", b"/paren#28"),
    ]

    def test_names_escape_unsafe_characters(self) -> None:
        for value, expected in self.NAME_CASES:
            with self.subTest(value=value):
                self.assertEqual(k.encode_name(value), expected)

    def test_object_serialisation(self) -> None:
        cases: list[tuple[object, bytes]] = [
            (None, b"null"),
            (True, b"true"),
            (False, b"false"),
            (k.PdfName("X"), b"/X"),
            (k.PdfRef(7), b"7 0 R"),
            ([1, 2, 3], b"[1 2 3]"),
            ([], b"[]"),
            ({}, b"<< >>"),
            ({"A": 1}, b"<< /A 1 >>"),
            (
                {"A": [k.PdfName("B"), k.PdfRef(2)]},
                b"<< /A [/B 2 0 R] >>",
            ),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(k.serialize(value), expected)

    def test_booleans_are_not_written_as_numbers(self) -> None:
        """bool subclasses int in Python, so this ordering bug is easy."""
        self.assertEqual(k.serialize(True), b"true")
        self.assertEqual(k.serialize(1), b"1")

    def test_unserialisable_object_raises(self) -> None:
        with self.assertRaises(TypeError):
            k.serialize(object())

    def test_dictionary_order_is_insertion_order(self) -> None:
        """Determinism depends on dictionaries never being reordered."""
        first = k.serialize({"B": 1, "A": 2, "C": 3})
        self.assertEqual(first, b"<< /B 1 /A 2 /C 3 >>")


class TestPdfEscaping(unittest.TestCase):
    """Strings must survive the round trip into and out of the PDF."""

    STRINGS: list[str] = [
        "plain text",
        "with (parentheses)",
        "unbalanced ( open",
        "unbalanced ) close",
        "a backslash \\ here",
        "double backslash \\\\ here",
        "all three ( ) \\ together",
        "nested ((deep)) parens",
        "\\(already escaped looking\\)",
        "percent % and hash #",
        "slash / and angle < >",
        "square [ brackets ]",
        "curly { braces }",
        "accented café naïve",
        "Ångström über",
        "currency £ ¥ ¢",
        "tab\tseparated",
        "newline\nembedded",
        "the quick brown fox jumps over the lazy dog",
        "()()()()",
        "\\\\\\\\",
        "((((",
        "))))",
    ]

    def test_literal_string_round_trip(self) -> None:
        """Encode then decode with an independent decoder."""
        for text in self.STRINGS:
            with self.subTest(text=text):
                encoded, substituted = k.encode_winansi(text)
                self.assertEqual(substituted, [])
                literal = k.encode_literal_string(encoded)
                self.assertTrue(literal.startswith(b"("))
                self.assertTrue(literal.endswith(b")"))
                decoded = decode_literal_strings(literal)
                self.assertEqual(len(decoded), 1)
                self.assertEqual(
                    decoded[0].decode("cp1252"), text
                )

    def test_output_is_pure_ascii_inside_strings(self) -> None:
        """High bytes are written as octal escapes, not raw."""
        encoded, _ = k.encode_winansi("café")
        literal = k.encode_literal_string(encoded)
        self.assertEqual(literal, b"(caf\\351)")
        for byte in literal:
            self.assertLess(byte, 128)

    def test_delimiters_are_escaped(self) -> None:
        cases = [
            ("(", b"(\\()"),
            (")", b"(\\))"),
            ("\\", b"(\\\\)"),
            ("()", b"(\\(\\))"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                encoded, _ = k.encode_winansi(text)
                self.assertEqual(k.encode_literal_string(encoded), expected)

    def test_unrenderable_characters_are_substituted_and_reported(
        self,
    ) -> None:
        """Nothing is dropped silently; the caller is told what changed."""
        encoded, substituted = k.encode_winansi("a中b\U0001f600c")
        self.assertEqual(encoded, b"a?b?c")
        self.assertEqual(substituted, ["中", "\U0001f600"])

    def test_escaping_survives_into_a_real_pdf(self) -> None:
        """Parse the emitted file back and compare the strings."""
        data = build_pdf_with_text(self.STRINGS, compress=False)
        reader = MiniPdf(data)
        self.assertEqual(reader.problems, [])
        payload = b""
        for number in reader.all_stream_numbers():
            payload += reader.stream_data(number)
        recovered = [
            piece.decode("cp1252") for piece in decode_literal_strings(payload)
        ]
        self.assertEqual(recovered, self.STRINGS)

    def test_escaping_survives_compression(self) -> None:
        data = build_pdf_with_text(self.STRINGS, compress=True)
        reader = MiniPdf(data)
        self.assertEqual(reader.problems, [])
        payload = b""
        for number in reader.all_stream_numbers():
            payload += reader.stream_data(number)
        recovered = [
            piece.decode("cp1252") for piece in decode_literal_strings(payload)
        ]
        self.assertEqual(recovered, self.STRINGS)

    def test_info_dictionary_string_is_escaped(self) -> None:
        data = build_pdf_with_text(["x"], title="A (tricky) \\ title")
        reader = MiniPdf(data)
        info = reader.raw_object(reader.size - 1)
        self.assertIn(b"\\(tricky\\)", info)
        self.assertIn(b"\\\\", info)


# ===========================================================================
# Group 7: PDF structure
# ===========================================================================


class TestPdfStructure(unittest.TestCase):
    """The emitted file is re-read by MiniPdf and checked from scratch."""

    def setUp(self) -> None:
        self.data = build_pdf_with_text(
            ["first line", "second (line)", "third \\ line"]
        )
        self.reader = MiniPdf(self.data)

    def test_no_structural_problems(self) -> None:
        self.assertEqual(self.reader.problems, [])

    def test_header_and_binary_comment(self) -> None:
        self.assertTrue(self.data.startswith(b"%PDF-1.7\n"))
        second_line = self.data.split(b"\n")[1]
        self.assertTrue(second_line.startswith(b"%"))
        self.assertTrue(
            any(byte > 127 for byte in second_line),
            "the second line must carry high bytes to mark the file binary",
        )

    def test_file_ends_with_eof(self) -> None:
        self.assertTrue(self.data.rstrip().endswith(b"%%EOF"))

    def test_xref_offsets_are_real_byte_positions(self) -> None:
        self.assertEqual(self.reader.check_offsets(), [])

    def test_xref_entries_are_twenty_bytes(self) -> None:
        start = self.reader.startxref
        header_end = self.data.index(b"\n", start + 5) + 1
        for index in range(self.reader.size):
            record = self.data[
                header_end + index * 20 : header_end + index * 20 + 20
            ]
            with self.subTest(entry=index):
                self.assertEqual(len(record), 20)
                self.assertEqual(record[10:11], b" ")
                self.assertEqual(record[16:17], b" ")
                self.assertEqual(record[18:20], b" \n")

    def test_free_entry_has_generation_65535(self) -> None:
        start = self.reader.startxref
        header_end = self.data.index(b"\n", start + 5) + 1
        self.assertEqual(
            self.data[header_end : header_end + 20],
            b"0000000000 65535 f \n",
        )

    def test_trailer_is_well_formed(self) -> None:
        trailer = self.reader.trailer
        for key in (b"/Size", b"/Root", b"/Info", b"/ID"):
            with self.subTest(key=key):
                self.assertIn(key, trailer)

    def test_trailer_size_matches_the_object_count(self) -> None:
        trailer = self.reader.trailer
        at = trailer.index(b"/Size")
        digits = ""
        for character in trailer[at + 5 :].decode("latin-1"):
            if character.isdigit():
                digits += character
            elif digits:
                break
        self.assertEqual(int(digits), self.reader.size)

    def test_every_reference_points_at_an_existing_object(self) -> None:
        for number in self.reader.referenced_numbers():
            with self.subTest(reference=number):
                self.assertGreaterEqual(number, 1)
                self.assertLess(number, self.reader.size)

    def test_document_tree_is_reachable(self) -> None:
        root_at = self.reader.trailer.index(b"/Root")
        digits = ""
        for character in self.reader.trailer[root_at + 5 :].decode("latin-1"):
            if character.isdigit():
                digits += character
            elif digits:
                break
        catalog = self.reader.raw_object(int(digits))
        self.assertIn(b"/Type /Catalog", catalog)
        self.assertIn(b"/Pages", catalog)

    def test_stream_length_is_exact(self) -> None:
        """stream_data raises if /Length disagrees with the payload."""
        for number in self.reader.all_stream_numbers():
            with self.subTest(object=number):
                self.reader.stream_data(number)

    def test_content_stream_is_compressed(self) -> None:
        numbers = self.reader.all_stream_numbers()
        self.assertTrue(numbers)
        for number in numbers:
            with self.subTest(object=number):
                self.assertIn(
                    b"/Filter /FlateDecode", self.reader.raw_object(number)
                )

    def test_content_stream_decompresses_to_operators(self) -> None:
        payload = self.reader.stream_data(
            self.reader.all_stream_numbers()[0]
        )
        for operator in (b"BT", b"ET", b"Tf", b"Tm", b"Tj"):
            with self.subTest(operator=operator):
                self.assertIn(operator, payload)

    def test_page_has_the_expected_dictionary(self) -> None:
        found = False
        for number in range(1, self.reader.size):
            body = self.reader.raw_object(number)
            if b"/Type /Page\n" in body or b"/Type /Page " in body:
                found = True
                self.assertIn(b"/MediaBox", body)
                self.assertIn(b"/Resources", body)
                self.assertIn(b"/Contents", body)
                self.assertIn(b"/Parent", body)
        self.assertTrue(found, "no page object in the file")

    def test_font_is_a_standard_14_without_embedding(self) -> None:
        found = False
        for number in range(1, self.reader.size):
            body = self.reader.raw_object(number)
            if b"/Type /Font" in body:
                found = True
                self.assertIn(b"/Subtype /Type1", body)
                self.assertIn(b"/BaseFont /Helvetica", body)
                self.assertIn(b"/Encoding /WinAnsiEncoding", body)
                self.assertNotIn(b"/FontFile", body)
        self.assertTrue(found, "no font object in the file")

    def test_reserved_but_unassigned_object_is_caught(self) -> None:
        writer = k.PdfWriter()
        root = writer.reserve()
        writer.reserve()
        writer.assign(root, {"Type": k.PdfName("Catalog")})
        with self.assertRaises(AssertionError):
            writer.render(root=root)

    def test_a_truncated_file_is_detected_by_the_reader(self) -> None:
        """Confirms MiniPdf would actually notice a broken file."""
        broken = MiniPdf(self.data[: len(self.data) // 2])
        self.assertTrue(broken.problems)

    def test_a_corrupted_offset_is_detected_by_the_reader(self) -> None:
        """Shift one xref offset by a byte and confirm the check fails."""
        start = self.reader.startxref
        header_end = self.data.index(b"\n", start + 5) + 1
        entry_at = header_end + 20
        corrupted = bytearray(self.data)
        original = int(self.data[entry_at : entry_at + 10])
        corrupted[entry_at : entry_at + 10] = b"%010d" % (original + 1)
        problems = MiniPdf(bytes(corrupted)).check_offsets()
        self.assertTrue(
            problems, "a one byte offset error must not go unnoticed"
        )

    def test_pdf_date_never_reads_the_clock(self) -> None:
        self.assertEqual(
            k.pdf_date("2026-01-01"), "D:20260101000000+00'00'"
        )
        self.assertEqual(
            k.pdf_date("2000-01-01"), "D:20000101000000+00'00'"
        )


# ===========================================================================
# Group 8: determinism
# ===========================================================================


class TestDeterminism(unittest.TestCase):
    """The same input must produce byte identical output, every time."""

    def test_same_input_gives_identical_bytes(self) -> None:
        lines = ["alpha", "beta (gamma)", "delta \\ epsilon"]
        first = build_pdf_with_text(lines)
        second = build_pdf_with_text(lines)
        self.assertEqual(first, second)

    def test_repeated_builds_are_stable(self) -> None:
        lines = ["repeat me"]
        builds = {build_pdf_with_text(lines) for _ in range(10)}
        self.assertEqual(len(builds), 1)

    def test_different_input_gives_different_bytes(self) -> None:
        """A stable hash must still be sensitive to the content."""
        first = build_pdf_with_text(["alpha"])
        second = build_pdf_with_text(["beta"])
        self.assertNotEqual(first, second)

    def test_document_id_is_derived_from_content(self) -> None:
        data = build_pdf_with_text(["alpha"])
        reader = MiniPdf(data)
        self.assertIn(b"/ID", reader.trailer)
        opening = reader.trailer.index(b"/ID")
        identifier = reader.trailer[opening : opening + 80]
        self.assertIn(b"<", identifier)
        again = MiniPdf(build_pdf_with_text(["alpha"])).trailer
        self.assertEqual(reader.trailer, again)

    def test_no_wall_clock_in_the_engine(self) -> None:
        """A build that stamps the current time cannot be reproducible.

        Checked against the syntax tree rather than the raw text, so that a
        comment or docstring explaining why the clock is avoided does not
        trip the test that enforces it.
        """
        forbidden = {
            "now",
            "today",
            "utcnow",
            "time",
            "localtime",
            "gmtime",
            "monotonic",
            "perf_counter",
        }
        engine = ast.parse(
            ENGINE_PATH.read_text(encoding="utf-8"), filename=str(ENGINE_PATH)
        )
        offenders: list[str] = []
        for node in ast.walk(engine):
            if isinstance(node, ast.Call) and isinstance(
                node.func, ast.Attribute
            ):
                if node.func.attr in forbidden:
                    offenders.append(f"{node.func.attr} on line {node.lineno}")
        self.assertEqual(offenders, [])
        # The clock modules must not even be imported.
        for module in ("time", "datetime", "calendar", "random", "uuid"):
            with self.subTest(module=module):
                self.assertNotIn(module, self._engine_imports())

    @staticmethod
    def _engine_imports() -> set[str]:
        engine = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(engine):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    modules.add(node.module.split(".")[0])
        return modules

    def test_parse_is_deterministic(self) -> None:
        source = (
            "# H\n\ntext **bold**\n\n- a\n  - b\n\n| x | y |\n|---|---|\n"
            "| 1 | 2 |\n"
        )
        shapes = {tree(source) for _ in range(5)}
        self.assertEqual(len(shapes), 1)


# ===========================================================================
# Group 9: layout
# ===========================================================================


def render_rows(source: str, **option_overrides: object) -> tuple[
    list[k.Row], k.PageGeometry
]:
    """Parse and render a document, returning its rows and page geometry."""
    options = k.BuildOptions(**option_overrides)
    geometry = options.geometry()
    text = k.SourceText(source)
    diagnostics = k.DiagnosticCollector(text)
    document = k.BlockParser(text, diagnostics).parse_document()
    renderer = k.DocumentRenderer(
        geometry, options.render_options(), diagnostics
    )
    return renderer.render(document), geometry


def text_fragments(rows: list[k.Row]) -> list[tuple[float, str]]:
    """Every drawn fragment as (x position, text), in drawing order."""
    found: list[tuple[float, str]] = []
    for row in rows:
        for item in row.items:
            if isinstance(item, k.PaintText):
                for fragment in item.fragments:
                    found.append((fragment.x, fragment.text))
    return found


class TestCodeBlockIndentation(unittest.TestCase):
    """Leading whitespace in code must reach the page at its real depth."""

    def test_leading_spaces_stay_in_the_drawn_string(self) -> None:
        """Indentation must survive being copied out of the finished PDF."""
        rows, _ = render_rows(
            "```\nzero\n    four\n        eight\n```\n"
        )
        drawn = [body for _, body in text_fragments(rows) if body.strip()]
        self.assertEqual(drawn, ["zero", "    four", "        eight"])

    def test_three_indent_depths_give_three_left_edges(self) -> None:
        """The three depths must reach the page at three distinct offsets.

        The indent lives in the string rather than in the x coordinate, so
        the position that matters is where the first non-space glyph lands:
        the fragment x plus the width of its leading spaces.
        """
        rows, _ = render_rows(
            "```\nzero\n    four\n        eight\n```\n"
        )
        edges = []
        for x, body in text_fragments(rows):
            if not body.strip():
                continue
            indent = len(body) - len(body.lstrip(" "))
            style = k.TextStyle(
                font="Courier",
                size=11.0 * k.RenderOptions().code_size_ratio,
                code=True,
            )
            edges.append(x + style.width_of(" " * indent))
        self.assertEqual(
            len(set(round(edge, 6) for edge in edges)),
            3,
            f"expected three distinct left edges, got {edges}",
        )
        self.assertLess(edges[0], edges[1])
        self.assertLess(edges[1], edges[2])

    def test_indent_steps_are_exactly_the_space_advance(self) -> None:
        """Four spaces of Courier is 4 * 600/1000 em, and nothing else."""
        size = 11.0 * k.RenderOptions().code_size_ratio
        space = k.measure(" ", "Courier", size)
        rows, _ = render_rows(
            "```\nzero\n    four\n        eight\n```\n"
        )
        widths = [
            k.measure(body[: len(body) - len(body.lstrip(" "))], "Courier", size)
            for _, body in text_fragments(rows)
            if body.strip()
        ]
        self.assertAlmostEqual(widths[1] - widths[0], 4 * space, places=6)
        self.assertAlmostEqual(widths[2] - widths[1], 4 * space, places=6)

    def test_tabs_are_expanded_not_emitted_raw(self) -> None:
        """A tab has no glyph, so it must never reach the content stream."""
        rows, _ = render_rows("```\nzero\n\ttabbed\n```\n")
        for _, body in text_fragments(rows):
            self.assertNotIn("\t", body)
        drawn = [body for _, body in text_fragments(rows) if body.strip()]
        self.assertEqual(drawn, ["zero", "    tabbed"])

    def test_tab_indent_matches_the_equivalent_spaces(self) -> None:
        tabbed, _ = render_rows("```\n\tx\n```\n")
        spaced, _ = render_rows("```\n    x\n```\n")
        self.assertEqual(text_fragments(tabbed), text_fragments(spaced))

    def test_wrapped_code_hangs_at_its_own_indent(self) -> None:
        """A wrapped continuation must not fall back to the panel edge."""
        long_word = "x" * 400
        rows, _ = render_rows("```\n        " + long_word + "\n```\n")
        drawn = [(x, body) for x, body in text_fragments(rows) if body.strip()]
        self.assertGreater(len(drawn), 1, "the line should have wrapped")
        style = k.TextStyle(
            font="Courier",
            size=11.0 * k.RenderOptions().code_size_ratio,
            code=True,
        )
        first_edge = drawn[0][0] + style.width_of(" " * 8)
        for x, _ in drawn[1:]:
            self.assertAlmostEqual(x, first_edge, places=6)

    def test_interior_spacing_is_preserved(self) -> None:
        """Alignment inside a line stays in the string, where it belongs."""
        rows, _ = render_rows("```\na    b\n```\n")
        self.assertEqual(text_fragments(rows)[0][1], "a    b")

    def test_blank_lines_inside_code_are_kept(self) -> None:
        rows, _ = render_rows("```\na\n\nb\n```\n")
        drawn = [body for _, body in text_fragments(rows) if body.strip()]
        self.assertEqual(drawn, ["a", "b"])


class TestLineBreaking(unittest.TestCase):
    """No line may exceed the content width, whatever the input."""

    SOURCES = [
        "A short paragraph.",
        "word " * 200,
        "supercalifragilisticexpialidocious " * 20,
        "a" * 400,
        "https://example.org/" + "path/" * 60,
        "**bold** and *italic* and `code` " * 30,
        "- a list item that is long enough to wrap several times " * 8,
        "> a quote that is long enough to wrap several times over " * 8,
        "| a | b |\n|---|---|\n| " + "long " * 40 + " | short |",
        "```\n" + "x" * 300 + "\n```",
    ]

    def test_no_drawn_text_crosses_the_right_margin(self) -> None:
        for source in self.SOURCES:
            for justify in (False, True):
                with self.subTest(source=source[:30], justify=justify):
                    rows, geometry = render_rows(source, justify=justify)
                    limit = (
                        geometry.content_left + geometry.content_width + 0.01
                    )
                    for row in rows:
                        for item in row.items:
                            if not isinstance(item, k.PaintText):
                                continue
                            for fragment in item.fragments:
                                end = fragment.x + fragment.style.width_of(
                                    fragment.text
                                )
                                self.assertLessEqual(
                                    end,
                                    limit,
                                    f"{fragment.text[:30]!r} ends at {end}",
                                )

    def test_long_word_is_hard_broken_not_overflowed(self) -> None:
        style = k.TextStyle(font="Helvetica", size=11)
        pieces = k.split_into_pieces("a" * 500, style)
        lines = k.break_lines(pieces, 200.0)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(line.natural_width, 200.0 + 0.01)
        rebuilt = "".join(
            piece.text for line in lines for piece in line.pieces
        )
        self.assertEqual(rebuilt, "a" * 500)

    def test_consecutive_spaces_collapse_outside_code(self) -> None:
        style = k.TextStyle(font="Helvetica", size=11)
        pieces = k.split_into_pieces("a    b\t\tc", style)
        self.assertEqual(
            [piece.text for piece in pieces], ["a", " ", "b", " ", "c"]
        )

    def test_code_spans_keep_their_spacing(self) -> None:
        style = k.TextStyle(font="Courier", size=11, code=True)
        pieces = k.split_into_pieces("a    b", style)
        self.assertEqual([piece.text for piece in pieces], ["a    b"])

    def test_a_line_never_starts_with_a_space(self) -> None:
        style = k.TextStyle(font="Helvetica", size=11)
        pieces = k.split_into_pieces("word " * 60, style)
        lines = k.break_lines(pieces, 120.0)
        for line in lines:
            self.assertFalse(line.pieces[0].is_space)
            self.assertFalse(line.pieces[-1].is_space)

    def test_hard_break_starts_a_new_line(self) -> None:
        rows, _ = render_rows("first  \nsecond\n")
        drawn = [body for _, body in text_fragments(rows)]
        self.assertEqual(drawn, ["first", "second"])


class TestTableBounds(unittest.TestCase):
    """A malformed table must never draw outside the columns it declared."""

    MISMATCHED = (
        "| x | y | z |\n"
        "|---|---|---|\n"
        "| short row |\n"
        "| kept | kept | kept | DROPPED |\n"
    )

    def test_surplus_cells_are_dropped_not_drawn(self) -> None:
        rows, _ = render_rows(self.MISMATCHED)
        drawn = [body for _, body in text_fragments(rows)]
        self.assertNotIn("DROPPED", drawn)
        self.assertEqual(drawn.count("kept"), 3)

    def test_short_rows_are_padded_without_drawing_anything(self) -> None:
        rows, _ = render_rows(self.MISMATCHED)
        drawn = [body for _, body in text_fragments(rows) if body.strip()]
        self.assertEqual(drawn.count("short row"), 1)

    def test_both_mismatches_warn_with_a_position(self) -> None:
        diagnostics = warnings_for(self.MISMATCHED)
        table_warnings = [
            d for d in diagnostics if "cells but the header has" in d.message
        ]
        self.assertEqual(len(table_warnings), 2)
        self.assertEqual(table_warnings[0].position.line, 3)
        self.assertEqual(table_warnings[1].position.line, 4)

    def test_nothing_in_a_table_crosses_the_page_margin(self) -> None:
        sources = [
            self.MISMATCHED,
            "| a | b | c | d | e | f |\n" + "|---" * 6 + "|\n"
            + "| " + " | ".join(["a much longer cell than fits"] * 6)
            + " |\n",
            "| a |\n|---|\n| " + "x" * 300 + " |\n",
        ]
        for source in sources:
            with self.subTest(source=source[:30]):
                rows, geometry = render_rows(source)
                limit = geometry.content_left + geometry.content_width + 0.01
                for row in rows:
                    for item in row.items:
                        if isinstance(item, k.PaintText):
                            for fragment in item.fragments:
                                end = fragment.x + fragment.style.width_of(
                                    fragment.text
                                )
                                self.assertLessEqual(end, limit, fragment.text)
                        elif isinstance(item, k.PaintRect):
                            self.assertLessEqual(
                                item.x + item.width, limit
                            )

    def test_cells_stay_within_their_own_column(self) -> None:
        """Each cell's text must sit inside the column it belongs to."""
        source = (
            "| one | two | three |\n|---|---|---|\n"
            "| " + "w" * 60 + " | short | " + "z" * 60 + " |\n"
        )
        rows, geometry = render_rows(source)
        columns: list[float] = []
        for row in rows:
            for item in row.items:
                if isinstance(item, k.PaintText):
                    for fragment in item.fragments:
                        columns.append(fragment.x)
        # Three distinct column origins, and no fourth.
        self.assertEqual(len(set(round(x, 3) for x in columns)), 3)


class TestPagination(unittest.TestCase):
    """Widow, orphan and keep-with-next rules, checked on real documents."""

    DOCUMENTS = [
        "para\n\n" * 120,
        ("# Heading\n\nSome text that wraps a little.\n\n" * 40),
        ("Body text. " * 40 + "\n\n") * 30,
        "- item\n" * 300,
        ("## H2\n\n" + "word " * 120 + "\n\n") * 12,
        "```\n" + "code line\n" * 200 + "```\n",
        ("> quote\n> more quote\n\n" * 60),
    ]

    def _pages(self, source: str) -> list[k.LaidOutPage]:
        rows, geometry = render_rows(source)
        return k.paginate(rows, geometry)

    def test_no_page_ends_on_a_kept_row(self) -> None:
        """This single invariant is what widow and orphan control means."""
        for source in self.DOCUMENTS:
            with self.subTest(source=source[:25]):
                pages = self._pages(source)
                for page in pages[:-1]:
                    if len(page.rows) <= 1:
                        continue
                    self.assertFalse(
                        page.rows[-1].row.keep_with_next,
                        f"page {page.number} ends on a kept row",
                    )

    def test_no_page_ends_on_a_heading(self) -> None:
        for source in self.DOCUMENTS:
            with self.subTest(source=source[:25]):
                for page in self._pages(source):
                    if page.rows:
                        self.assertIsNone(page.rows[-1].row.heading)

    def test_no_page_starts_with_blank_space(self) -> None:
        for source in self.DOCUMENTS:
            with self.subTest(source=source[:25]):
                for page in self._pages(source):
                    if page.rows:
                        self.assertFalse(page.rows[0].row.is_space)

    def test_rows_stay_inside_the_text_area(self) -> None:
        for source in self.DOCUMENTS:
            with self.subTest(source=source[:25]):
                rows, geometry = render_rows(source)
                for page in k.paginate(rows, geometry):
                    for placed in page.rows:
                        if len(page.rows) == 1:
                            continue
                        self.assertLessEqual(
                            placed.y + placed.row.height,
                            geometry.content_bottom + 0.01,
                        )

    def test_every_row_is_placed_exactly_once(self) -> None:
        """Pagination must not drop or duplicate content."""
        for source in self.DOCUMENTS:
            with self.subTest(source=source[:25]):
                rows, geometry = render_rows(source)
                pages = k.paginate(rows, geometry)
                placed = [
                    id(item.row) for page in pages for item in page.rows
                ]
                self.assertEqual(len(placed), len(set(placed)))
                kept = {id(row) for row in rows if not row.is_space}
                self.assertTrue(kept.issubset(set(placed)))

    def test_pagination_terminates_on_an_oversized_row(self) -> None:
        """A row taller than the page is placed rather than looping."""
        geometry = k.BuildOptions().geometry()
        huge = k.Row(height=geometry.height * 3)
        pages = k.paginate([huge, k.Row(height=10.0)], geometry)
        self.assertGreaterEqual(len(pages), 1)

    def test_empty_document_still_produces_a_page(self) -> None:
        pages = k.paginate([], k.BuildOptions().geometry())
        self.assertEqual(len(pages), 1)


# ===========================================================================
# Group 10: table of contents, destinations and outline
# ===========================================================================


def parse_dests(reader: MiniPdf) -> dict[str, tuple[int, float]]:
    """Read the catalog's `/Dests` into {name: (page object, pdf y)}."""
    catalog_number = next(
        number
        for number in range(1, reader.size)
        if b"/Type /Catalog" in reader.raw_object(number)
    )
    body = reader.raw_object(catalog_number)
    if b"/Dests <<" not in body:
        return {}
    blob = body.split(b"/Dests <<")[1]
    depth, cursor = 1, 0
    while depth and cursor < len(blob):
        if blob[cursor : cursor + 2] == b"<<":
            depth += 1
            cursor += 2
        elif blob[cursor : cursor + 2] == b">>":
            depth -= 1
            cursor += 2
        else:
            cursor += 1
    blob = blob[: cursor - 2]
    found: dict[str, tuple[int, float]] = {}
    for chunk in blob.split(b"/H")[1:]:
        name = "H" + chunk.split(b" ")[0].decode("ascii")
        array = chunk.split(b"[")[1].split(b"]")[0].split()
        # [page ref] 0 R /XYZ left top null
        found[name] = (int(array[0]), float(array[5]))
    return found


def page_object_numbers(reader: MiniPdf) -> list[int]:
    """The page object numbers, in document order, from the pages tree."""
    tree = next(
        number
        for number in range(1, reader.size)
        if b"/Type /Pages" in reader.raw_object(number)
    )
    kids = reader.raw_object(tree).split(b"/Kids [")[1].split(b"]")[0]
    return [int(token) for token in kids.replace(b" 0 R", b"").split()]


def numbers_printed_on(reader: MiniPdf, page_index: int) -> list[str]:
    """Digit-only strings drawn on one page, minus the footer page number."""
    payload = reader.stream_data(reader.all_stream_numbers()[page_index])
    strings = [
        piece.decode("cp1252") for piece in decode_literal_strings(payload)
    ]
    digits = [piece for piece in strings if piece.isdigit()]
    return digits[:-1] if digits else []


#: A document with enough headings to push the contents onto two pages, so
#: the convergence loop is exercised rather than merely present.
def toc_document(section_count: int = 26) -> str:
    parts = ["---", "title: Contents Test", "---", ""]
    for index in range(section_count):
        parts.append(f"# Chapter {index + 1}")
        parts.append("")
        parts.append("Body text for the chapter. " * 12)
        parts.append("")
        parts.append(f"## Section {index + 1}.1")
        parts.append("")
        parts.append("More body text that runs on for a while. " * 10)
        parts.append("")
        parts.append(f"### Subsection {index + 1}.1.1")
        parts.append("")
        parts.append("Yet more text to push the pages along. " * 10)
        parts.append("")
    return "\n".join(parts)


class TestTableOfContents(unittest.TestCase):
    """The contents must agree with where the headings actually landed."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.options = k.BuildOptions(toc=True, date="2026-01-01")
        cls.result = k.build_pdf(toc_document(), cls.options)
        cls.reader = MiniPdf(cls.result.data)
        cls.geometry = cls.options.geometry()

    def test_the_document_is_big_enough_to_be_a_real_test(self) -> None:
        self.assertGreaterEqual(self.result.page_count, 8)
        self.assertGreaterEqual(len(self.result.headings), 30)
        levels = {entry.heading.level for entry in self.result.headings}
        self.assertEqual(levels, {1, 2, 3})

    def test_the_contents_needed_more_than_one_pass(self) -> None:
        """A one page guess that grew is the case worth proving."""
        self.assertGreaterEqual(self.result.toc_passes, 2)

    def test_printed_numbers_match_the_real_heading_pages(self) -> None:
        """The whole point: an entry must name the page it jumps to."""
        expected = [
            str(entry.page_index + 1) for entry in self.result.headings
        ]
        printed: list[str] = []
        for index in range(1, 1 + self.result.toc_page_count):
            printed.extend(numbers_printed_on(self.reader, index))
        self.assertEqual(printed, expected)

    def test_every_heading_has_a_destination(self) -> None:
        dests = parse_dests(self.reader)
        self.assertEqual(len(dests), len(self.result.headings))
        for entry in self.result.headings:
            with self.subTest(name=entry.heading.dest_name):
                self.assertIn(entry.heading.dest_name, dests)

    def test_destinations_point_at_the_right_page(self) -> None:
        dests = parse_dests(self.reader)
        pages = page_object_numbers(self.reader)
        for entry in self.result.headings:
            with self.subTest(name=entry.heading.dest_name):
                self.assertEqual(
                    dests[entry.heading.dest_name][0],
                    pages[entry.page_index],
                )

    def test_destinations_point_at_the_heading_not_the_page_top(self) -> None:
        """A heading two thirds down must not dump the reader at the top."""
        dests = parse_dests(self.reader)
        page_top = self.geometry.height - self.geometry.content_top
        below_the_top = 0
        for entry in self.result.headings:
            with self.subTest(name=entry.heading.dest_name):
                expected = self.geometry.height - max(entry.y - 8.0, 0.0)
                self.assertAlmostEqual(
                    dests[entry.heading.dest_name][1], expected, places=4
                )
            if dests[entry.heading.dest_name][1] < page_top - 1:
                below_the_top += 1
        self.assertGreater(
            below_the_top,
            0,
            "no heading sat below its page top, so this proves nothing",
        )

    def test_one_link_annotation_per_contents_line(self) -> None:
        self.assertEqual(
            self.result.data.count(b"/Subtype /Link"),
            len(self.result.headings),
        )

    def test_outline_tree_is_well_formed(self) -> None:
        """Every sibling chain and parent pointer must agree."""
        data = self.result.data
        self.assertIn(b"/Type /Outlines", data)
        items: dict[int, bytes] = {}
        for number in range(1, self.reader.size):
            body = self.reader.raw_object(number)
            if b"/Dest [" in body and b"/Parent" in body and b"/Title" in body:
                items[number] = body
        self.assertEqual(len(items), len(self.result.headings))

        def ref(body: bytes, key: bytes) -> int | None:
            at = body.find(key)
            if at == -1:
                return None
            tail = body[at + len(key) :].strip()
            digits = ""
            for character in tail.decode("latin-1"):
                if character.isdigit():
                    digits += character
                else:
                    break
            return int(digits) if digits else None

        for number, body in items.items():
            with self.subTest(item=number):
                following = ref(body, b"/Next")
                if following is not None:
                    self.assertEqual(
                        ref(items[following], b"/Prev"),
                        number,
                        "Next and Prev disagree",
                    )
                first = ref(body, b"/First")
                if first is not None:
                    self.assertEqual(ref(items[first], b"/Parent"), number)
                    self.assertIsNone(ref(items[first], b"/Prev"))

    def test_contents_is_absent_without_the_flag(self) -> None:
        plain = k.build_pdf(
            toc_document(4), k.BuildOptions(toc=False, date="2026-01-01")
        )
        with_toc = k.build_pdf(
            toc_document(4), k.BuildOptions(toc=True, date="2026-01-01")
        )
        self.assertLess(plain.page_count, with_toc.page_count)
        self.assertEqual(plain.toc_passes, 0)

    def test_contents_build_is_deterministic(self) -> None:
        again = k.build_pdf(toc_document(), self.options)
        self.assertEqual(again.data, self.result.data)

    def test_convergence_holds_across_many_sizes(self) -> None:
        """The loop must settle for documents of every awkward length."""
        for count in (1, 2, 5, 12, 18, 24, 30, 40):
            with self.subTest(sections=count):
                options = k.BuildOptions(toc=True, date="2026-01-01")
                result = k.build_pdf(toc_document(count), options)
                self.assertLess(
                    result.toc_passes,
                    k.TOC_MAX_PASSES,
                    "contents layout did not settle",
                )
                self.assertEqual(
                    [
                        diagnostic.message
                        for diagnostic in result.diagnostics
                        if "did not settle" in diagnostic.message
                    ],
                    [],
                )
                reader = MiniPdf(result.data)
                self.assertEqual(reader.problems, [])
                expected = [
                    str(entry.page_index + 1) for entry in result.headings
                ]
                printed: list[str] = []
                for index in range(1, 1 + result.toc_page_count):
                    printed.extend(numbers_printed_on(reader, index))
                self.assertEqual(
                    printed,
                    expected,
                    f"contents numbers wrong for {count} sections",
                )


# ===========================================================================
# Group 11: PNG decoding and image embedding
# ===========================================================================


def png_chunk(kind: bytes, body: bytes) -> bytes:
    return (
        struct.pack(">I", len(body))
        + kind
        + body
        + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    )


def make_png(
    width: int,
    height: int,
    alpha: bool = False,
    filter_type: int = 0,
    bit_depth: int = 8,
    colour_type: int | None = None,
    interlace: int = 0,
) -> tuple[bytes, list[tuple[int, ...]]]:
    """Encode a PNG by hand, and return it with the pixels that went in.

    Written here rather than imported so that the decoder under test is
    checked against an independent encoder. Only the filters the decoder
    claims to support are produced, one per call.
    """
    channels = 4 if alpha else 3
    if colour_type is None:
        colour_type = 6 if alpha else 2
    pixels: list[tuple[int, ...]] = []
    rows: list[bytes] = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            value = [
                (x * 7 + y * 3) % 256,
                (x * 11 + y * 5) % 256,
                (x * 13 + y * 17) % 256,
            ]
            if alpha:
                value.append((x * 19 + y * 23) % 256)
            pixels.append(tuple(value))
            row += bytes(value)
        rows.append(bytes(row))
    raw = bytearray()
    previous = bytes(width * channels)
    for row in rows:
        raw.append(filter_type)
        if filter_type == 0:
            raw += row
        elif filter_type == 1:  # Sub
            out = bytearray(len(row))
            for index in range(len(row)):
                left = row[index - channels] if index >= channels else 0
                out[index] = (row[index] - left) & 0xFF
            raw += out
        elif filter_type == 2:  # Up
            out = bytearray(len(row))
            for index in range(len(row)):
                out[index] = (row[index] - previous[index]) & 0xFF
            raw += out
        elif filter_type == 3:  # Average
            out = bytearray(len(row))
            for index in range(len(row)):
                left = row[index - channels] if index >= channels else 0
                out[index] = (
                    row[index] - ((left + previous[index]) >> 1)
                ) & 0xFF
            raw += out
        elif filter_type == 4:  # Paeth
            out = bytearray(len(row))
            for index in range(len(row)):
                left = row[index - channels] if index >= channels else 0
                above = previous[index]
                corner = (
                    previous[index - channels] if index >= channels else 0
                )
                estimate = left + above - corner
                da, db, dc = (
                    abs(estimate - left),
                    abs(estimate - above),
                    abs(estimate - corner),
                )
                predicted = left if (da <= db and da <= dc) else (
                    above if db <= dc else corner
                )
                out[index] = (row[index] - predicted) & 0xFF
            raw += out
        previous = row
    header = struct.pack(
        ">IIBBBBB", width, height, bit_depth, colour_type, 0, 0, interlace
    )
    data = (
        k.PNG_SIGNATURE
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + png_chunk(b"IEND", b"")
    )
    return data, pixels


def unfilter_for_test(
    raw: bytes, width: int, height: int, channels: int
) -> bytes:
    """A second, independent implementation of PNG unfiltering."""
    stride = width * channels
    out = bytearray()
    previous = bytearray(stride)
    cursor = 0
    for _ in range(height):
        kind = raw[cursor]
        cursor += 1
        line = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        for index in range(stride):
            left = line[index - channels] if index >= channels else 0
            above = previous[index]
            corner = previous[index - channels] if index >= channels else 0
            if kind == 0:
                addend = 0
            elif kind == 1:
                addend = left
            elif kind == 2:
                addend = above
            elif kind == 3:
                addend = (left + above) >> 1
            else:
                estimate = left + above - corner
                da, db, dc = (
                    abs(estimate - left),
                    abs(estimate - above),
                    abs(estimate - corner),
                )
                addend = left if (da <= db and da <= dc) else (
                    above if db <= dc else corner
                )
            line[index] = (line[index] + addend) & 0xFF
        out += line
        previous = line
    return bytes(out)


class TestPngDecoding(unittest.TestCase):
    """The PNG decoder must be exact, or refuse the file outright."""

    def test_all_supported_filters_round_trip_rgb(self) -> None:
        for filter_type in range(5):
            with self.subTest(filter=filter_type):
                data, pixels = make_png(9, 7, filter_type=filter_type)
                image = k.parse_png(data)
                self.assertEqual((image.width, image.height), (9, 7))
                self.assertTrue(image.predictor)
                self.assertIsNone(image.alpha_stream)
                # The colour stream is the original filtered data, which is
                # what the PDF predictor will undo.
                recovered = unfilter_for_test(
                    zlib.decompress(image.colour_stream), 9, 7, 3
                )
                expected = b"".join(bytes(pixel) for pixel in pixels)
                self.assertEqual(recovered, expected)

    def test_all_supported_filters_round_trip_rgba(self) -> None:
        for filter_type in range(5):
            with self.subTest(filter=filter_type):
                data, pixels = make_png(
                    9, 7, alpha=True, filter_type=filter_type
                )
                image = k.parse_png(data)
                self.assertFalse(image.predictor)
                self.assertIsNotNone(image.alpha_stream)
                colour = zlib.decompress(image.colour_stream)
                alpha = zlib.decompress(image.alpha_stream)
                self.assertEqual(len(colour), 9 * 7 * 3)
                self.assertEqual(len(alpha), 9 * 7)
                for index, pixel in enumerate(pixels):
                    self.assertEqual(
                        tuple(colour[index * 3 : index * 3 + 3]), pixel[:3]
                    )
                    self.assertEqual(alpha[index], pixel[3])

    def test_natural_size_in_points(self) -> None:
        data, _ = make_png(96, 48)
        image = k.parse_png(data)
        # 96 pixels at the assumed 96 dpi is one inch, which is 72 points.
        self.assertAlmostEqual(image.point_width, 72.0)
        self.assertAlmostEqual(image.point_height, 36.0)

    REJECTED: list[tuple[str, bytes, str]] = []

    def test_unsupported_and_broken_files_are_refused(self) -> None:
        """Every refusal must name a reason a human can act on."""
        good, _ = make_png(4, 4)
        cases: list[tuple[str, bytes, str]] = [
            ("not a png", b"GIF89a" + b"\x00" * 40, "signature"),
            ("empty", b"", "signature"),
            ("truncated after signature", k.PNG_SIGNATURE, "truncated"),
            ("truncated body", good[: len(good) - 12], "truncated"),
            (
                "corrupt checksum",
                good[:30] + bytes([good[30] ^ 0xFF]) + good[31:],
                "checksum",
            ),
            (
                "interlaced",
                make_png(4, 4, interlace=1)[0],
                "interlaced",
            ),
            (
                "sixteen bit",
                make_png(4, 4, bit_depth=16)[0],
                "8 bit",
            ),
            (
                "palette",
                make_png(4, 4, colour_type=3)[0],
                "palette",
            ),
            (
                "greyscale",
                make_png(4, 4, colour_type=0)[0],
                "greyscale",
            ),
            (
                "greyscale with alpha",
                make_png(4, 4, alpha=True, colour_type=4)[0],
                "greyscale with alpha",
            ),
            (
                "no image data",
                k.PNG_SIGNATURE
                + png_chunk(
                    b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
                )
                + png_chunk(b"IEND", b""),
                "no IDAT",
            ),
            (
                "zero width",
                k.PNG_SIGNATURE
                + png_chunk(
                    b"IHDR", struct.pack(">IIBBBBB", 0, 4, 8, 2, 0, 0, 0)
                )
                + png_chunk(b"IDAT", zlib.compress(b"\x00"))
                + png_chunk(b"IEND", b""),
                "zero dimension",
            ),
        ]
        for label, data, fragment in cases:
            with self.subTest(case=label):
                with self.assertRaises(k.PngError) as caught:
                    k.parse_png(data)
                self.assertIn(fragment, str(caught.exception))

    def test_a_good_file_is_not_refused(self) -> None:
        """Guards the negative tests above against being vacuous."""
        for alpha in (False, True):
            with self.subTest(alpha=alpha):
                data, _ = make_png(5, 5, alpha=alpha)
                self.assertIsInstance(k.parse_png(data), k.PngImage)


class TestImageEmbedding(unittest.TestCase):
    """Images must reach the PDF intact, or not at all."""

    def setUp(self) -> None:
        self.directory = Path(
            tempfile.mkdtemp(prefix="inkless-image-test-")
        )
        self.addCleanup(shutil.rmtree, self.directory, True)

    def _write(self, name: str, **kwargs: object) -> list[tuple[int, ...]]:
        data, pixels = make_png(12, 8, **kwargs)  # type: ignore[arg-type]
        (self.directory / name).write_bytes(data)
        return pixels

    def _build(self, source: str) -> k.BuildResult:
        return k.build_pdf(
            source,
            k.BuildOptions(date="2026-01-01", base_path=self.directory),
        )

    def test_rgb_image_becomes_an_xobject_with_the_png_predictor(
        self,
    ) -> None:
        self._write("a.png")
        result = self._build("![alt](a.png)\n")
        self.assertEqual(result.diagnostics, [])
        data = result.data
        self.assertIn(b"/Subtype /Image", data)
        self.assertIn(b"/Width 12", data)
        self.assertIn(b"/Height 8", data)
        self.assertIn(b"/ColorSpace /DeviceRGB", data)
        self.assertIn(b"/BitsPerComponent 8", data)
        self.assertIn(b"/Predictor 15", data)
        self.assertIn(b"/Colors 3", data)
        self.assertIn(b"/Columns 12", data)
        self.assertIn(b"/XObject", data)
        self.assertNotIn(b"/SMask", data)
        # The Do operator lives inside the compressed content stream.
        reader = MiniPdf(data)
        page = reader.stream_data(reader.all_stream_numbers()[0])
        self.assertIn(b" Do", page)

    def test_rgba_image_gets_a_soft_mask(self) -> None:
        self._write("a.png", alpha=True)
        result = self._build("![alt](a.png)\n")
        self.assertEqual(result.diagnostics, [])
        self.assertIn(b"/SMask", result.data)
        self.assertIn(b"/ColorSpace /DeviceGray", result.data)
        # A split image carries no predictor, because it was unfiltered here.
        self.assertNotIn(b"/Predictor", result.data)

    def test_embedded_pixels_survive_the_round_trip(self) -> None:
        pixels = self._write("a.png", alpha=True)
        result = self._build("![alt](a.png)\n")
        reader = MiniPdf(result.data)
        self.assertEqual(reader.problems, [])
        colour = None
        alpha = None
        for number in reader.all_stream_numbers():
            body = reader.raw_object(number)
            if b"/ColorSpace /DeviceRGB" in body:
                colour = reader.stream_data(number)
            elif b"/ColorSpace /DeviceGray" in body:
                alpha = reader.stream_data(number)
        self.assertIsNotNone(colour)
        self.assertIsNotNone(alpha)
        for index, pixel in enumerate(pixels):
            self.assertEqual(
                tuple(colour[index * 3 : index * 3 + 3]), pixel[:3]
            )
            self.assertEqual(alpha[index], pixel[3])

    def test_image_is_placed_with_a_cm_matrix(self) -> None:
        self._write("a.png")
        result = self._build("![alt](a.png)\n")
        reader = MiniPdf(result.data)
        page = reader.stream_data(reader.all_stream_numbers()[0])
        self.assertIn(b" cm\n", page)
        self.assertIn(b"q\n", page)
        self.assertIn(b"Q\n", page)

    def test_a_wide_image_is_scaled_into_the_column(self) -> None:
        data, _ = make_png(4000, 100)
        (self.directory / "wide.png").write_bytes(data)
        options = k.BuildOptions(date="2026-01-01", base_path=self.directory)
        geometry = options.geometry()
        source = k.SourceText("![alt](wide.png)\n")
        diagnostics = k.DiagnosticCollector(source)
        document = k.BlockParser(source, diagnostics).parse_document()
        renderer = k.DocumentRenderer(
            geometry, options.render_options(), diagnostics
        )
        placed = [
            item
            for row in renderer.render(document)
            for item in row.items
            if isinstance(item, k.PaintImage)
        ]
        self.assertEqual(len(placed), 1)
        self.assertLessEqual(placed[0].width, geometry.content_width + 0.01)
        self.assertGreater(placed[0].width, 0)

    MISSING_CASES = [
        ("![alt](nope.png)\n", "cannot read"),
        ("![alt](notes.txt)\n", "only PNG images"),
        ("![alt](broken.png)\n", "signature"),
    ]

    def test_unusable_images_warn_and_fall_back_to_alt_text(self) -> None:
        (self.directory / "notes.txt").write_text("hello", encoding="utf-8")
        (self.directory / "broken.png").write_bytes(b"not a png at all")
        for source, fragment in self.MISSING_CASES:
            with self.subTest(source=source):
                result = self._build(source)
                messages = [d.message for d in result.diagnostics]
                self.assertTrue(
                    any(fragment in message for message in messages),
                    f"expected {fragment!r} in {messages}",
                )
                self.assertNotIn(b"/Subtype /Image", result.data)
                reader = MiniPdf(result.data)
                self.assertEqual(reader.problems, [])
                page = reader.stream_data(reader.all_stream_numbers()[0])
                strings = b"".join(decode_literal_strings(page))
                self.assertIn(b"[image:", strings)

    def test_a_broken_image_still_produces_a_valid_pdf(self) -> None:
        (self.directory / "broken.png").write_bytes(
            k.PNG_SIGNATURE + b"\x00" * 20
        )
        result = self._build("# Title\n\n![alt](broken.png)\n\nAfter.\n")
        reader = MiniPdf(result.data)
        self.assertEqual(reader.problems, [])
        self.assertEqual(reader.check_offsets(), [])

    def test_image_warnings_carry_a_source_position(self) -> None:
        result = self._build("intro\n\n![alt](nope.png)\n")
        warning = next(
            d for d in result.diagnostics if "cannot read" in d.message
        )
        self.assertEqual(warning.position.line, 3)
        self.assertEqual(warning.position.column, 1)

    def test_inline_image_is_reported_and_falls_back(self) -> None:
        self._write("a.png")
        result = self._build("text ![alt](a.png) more text\n")
        messages = [d.message for d in result.diagnostics]
        self.assertTrue(
            any("inside a line of text" in message for message in messages),
            messages,
        )
        self.assertNotIn(b"/Subtype /Image", result.data)

    def test_the_same_image_is_embedded_once(self) -> None:
        self._write("a.png")
        result = self._build("![one](a.png)\n\n![two](a.png)\n")
        self.assertEqual(result.data.count(b"/Subtype /Image"), 1)

    def test_images_are_skipped_without_a_base_path(self) -> None:
        result = k.build_pdf(
            "![alt](a.png)\n", k.BuildOptions(date="2026-01-01")
        )
        self.assertTrue(
            any(
                "not a file" in d.message for d in result.diagnostics
            ),
            [d.message for d in result.diagnostics],
        )

    def test_image_builds_are_deterministic(self) -> None:
        self._write("a.png", alpha=True)
        first = self._build("![alt](a.png)\n")
        second = self._build("![alt](a.png)\n")
        self.assertEqual(first.data, second.data)


# ===========================================================================
# Group 12: command line interface
# ===========================================================================


class TestCommandLine(unittest.TestCase):
    """Every flag the README documents is exercised here."""

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="inkless-cli-test-"))
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.source = self.directory / "doc.md"
        self.source.write_text(
            "---\ntitle: CLI Test\nauthor: Nobody\n---\n\n"
            "# One\n\nSome body text that is long enough to wrap a little.\n\n"
            "## Two\n\n- a\n- b\n\n```\ncode\n```\n\n"
            "| a | b |\n|---|---|\n| 1 | 2 |\n",
            encoding="utf-8",
        )
        self.output = self.directory / "out.pdf"

    def run_cli(
        self, argv: list[str], stdin_text: str | None = None
    ) -> tuple[int, str, str]:
        """Call main() with captured streams, returning (code, out, err)."""
        out, err = io.StringIO(), io.StringIO()
        old = (sys.stdout, sys.stderr, sys.stdin)
        sys.stdout, sys.stderr = out, err
        if stdin_text is not None:
            sys.stdin = io.StringIO(stdin_text)
        try:
            code = k.main(argv)
        except SystemExit as exit_error:  # argparse errors and --version
            code = int(exit_error.code or 0)
        finally:
            sys.stdout, sys.stderr, sys.stdin = old
        return code, out.getvalue(), err.getvalue()

    FLAG_CASES: list[tuple[str, list[str]]] = [
        ("defaults", []),
        ("page size a4", ["--page-size", "a4"]),
        ("page size letter", ["--page-size", "letter"]),
        ("font helvetica", ["--font", "helvetica"]),
        ("font times", ["--font", "times"]),
        ("font courier", ["--font", "courier"]),
        ("font size", ["--font-size", "9"]),
        ("large font size", ["--font-size", "18"]),
        ("margin", ["--margin", "40"]),
        ("large margin", ["--margin", "120"]),
        ("toc", ["--toc"]),
        ("justify", ["--justify"]),
        ("no page numbers", ["--no-page-numbers"]),
        ("date", ["--date", "2026-03-04"]),
        ("everything at once", [
            "--page-size", "letter", "--font", "times", "--font-size", "12",
            "--margin", "70", "--toc", "--justify", "--no-page-numbers",
            "--date", "2026-01-01",
        ]),
    ]

    def test_every_flag_produces_a_valid_pdf(self) -> None:
        for label, flags in self.FLAG_CASES:
            with self.subTest(case=label):
                target = self.directory / f"{label.replace(' ', '-')}.pdf"
                code, _, err = self.run_cli(
                    [str(self.source), "-o", str(target), *flags]
                )
                self.assertEqual(code, 0, err)
                self.assertTrue(target.exists())
                reader = MiniPdf(target.read_bytes())
                self.assertEqual(reader.problems, [], label)
                self.assertEqual(reader.check_offsets(), [], label)

    def test_page_size_reaches_the_media_box(self) -> None:
        for size, width in (("a4", b"595.28"), ("letter", b"612")):
            with self.subTest(size=size):
                target = self.directory / f"{size}.pdf"
                self.run_cli(
                    [str(self.source), "-o", str(target), "--page-size", size]
                )
                self.assertIn(b"/MediaBox [0 0 " + width, target.read_bytes())

    def test_font_choice_reaches_the_font_object(self) -> None:
        for family, base in (
            ("helvetica", b"/BaseFont /Helvetica"),
            ("times", b"/BaseFont /Times-Roman"),
            ("courier", b"/BaseFont /Courier"),
        ):
            with self.subTest(font=family):
                target = self.directory / f"{family}.pdf"
                self.run_cli(
                    [str(self.source), "-o", str(target), "--font", family]
                )
                self.assertIn(base, target.read_bytes())

    def test_toc_adds_pages_and_bookmarks(self) -> None:
        plain = self.directory / "plain.pdf"
        with_toc = self.directory / "toc.pdf"
        self.run_cli([str(self.source), "-o", str(plain)])
        self.run_cli([str(self.source), "-o", str(with_toc), "--toc"])
        self.assertGreater(
            len(MiniPdf(with_toc.read_bytes()).xref),
            len(MiniPdf(plain.read_bytes()).xref),
        )
        self.assertIn(b"/Outlines", with_toc.read_bytes())

    def test_no_page_numbers_removes_the_footer(self) -> None:
        numbered = self.directory / "numbered.pdf"
        plain = self.directory / "plain.pdf"
        self.run_cli([str(self.source), "-o", str(numbered)])
        self.run_cli(
            [str(self.source), "-o", str(plain), "--no-page-numbers"]
        )
        self.assertLess(plain.stat().st_size, numbered.stat().st_size)

    def test_date_reaches_the_info_dictionary(self) -> None:
        target = self.directory / "dated.pdf"
        self.run_cli(
            [str(self.source), "-o", str(target), "--date", "2026-03-04"]
        )
        self.assertIn(b"(D:20260304000000+00'00')", target.read_bytes())

    def test_front_matter_reaches_the_info_dictionary(self) -> None:
        target = self.directory / "info.pdf"
        self.run_cli([str(self.source), "-o", str(target)])
        data = target.read_bytes()
        self.assertIn(b"/Title (CLI Test)", data)
        self.assertIn(b"/Author (Nobody)", data)

    def test_output_defaults_to_the_input_name(self) -> None:
        code, _, _ = self.run_cli([str(self.source)])
        self.assertEqual(code, 0)
        self.assertTrue((self.directory / "doc.pdf").exists())

    def test_check_writes_no_file_and_exits_zero_when_clean(self) -> None:
        code, _, err = self.run_cli([str(self.source), "--check"])
        self.assertEqual(code, 0)
        self.assertIn("no problems found", err)
        self.assertFalse((self.directory / "doc.pdf").exists())

    def test_check_exits_non_zero_on_a_problem(self) -> None:
        broken = self.directory / "broken.md"
        broken.write_text("text **unclosed\n", encoding="utf-8")
        code, _, err = self.run_cli([str(broken), "--check"])
        self.assertEqual(code, 1)
        self.assertIn("unclosed emphasis", err)
        self.assertIn("line 1, column 6", err)
        self.assertFalse((self.directory / "broken.pdf").exists())

    def test_stdin_is_accepted(self) -> None:
        target = self.directory / "stdin.pdf"
        code, _, err = self.run_cli(
            ["-", "-o", str(target)], stdin_text="# From stdin\n\nBody.\n"
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(MiniPdf(target.read_bytes()).problems, [])

    def test_stdin_without_output_is_an_error(self) -> None:
        code, _, err = self.run_cli(["-"], stdin_text="# x\n")
        self.assertEqual(code, 2)
        self.assertIn("needs -o", err)

    def test_missing_input_file_is_reported(self) -> None:
        code, _, err = self.run_cli(
            [str(self.directory / "nope.md"), "-o", str(self.output)]
        )
        self.assertEqual(code, 3)
        self.assertIn("cannot read", err)

    BAD_ARGUMENTS: list[tuple[str, list[str]]] = [
        ("bad date shape", ["--date", "01-01-2026"]),
        ("bad date text", ["--date", "yesterday"]),
        ("bad month", ["--date", "2026-13-01"]),
        ("bad day", ["--date", "2026-01-99"]),
        ("negative font size", ["--font-size", "-3"]),
        ("zero margin", ["--margin", "0"]),
        ("non numeric margin", ["--margin", "wide"]),
        ("unknown page size", ["--page-size", "a3"]),
        ("unknown font", ["--font", "comic"]),
    ]

    def test_bad_arguments_are_rejected(self) -> None:
        for label, flags in self.BAD_ARGUMENTS:
            with self.subTest(case=label):
                code, _, _ = self.run_cli(
                    [str(self.source), "-o", str(self.output), *flags]
                )
                self.assertEqual(code, 2, label)

    def test_version_flag(self) -> None:
        code, out, _ = self.run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(k.PROGRAM_VERSION, out)

    def test_colour_is_disabled_when_not_a_terminal(self) -> None:
        self.assertFalse(k.colour_enabled(io.StringIO()))

    def test_no_color_environment_variable_is_honoured(self) -> None:
        class FakeTerminal(io.StringIO):
            def isatty(self) -> bool:
                return True

        terminal = FakeTerminal()
        previous = os.environ.get("NO_COLOR")
        try:
            os.environ.pop("NO_COLOR", None)
            os.environ.pop("TERM", None)
            self.assertTrue(k.colour_enabled(terminal))
            os.environ["NO_COLOR"] = "1"
            self.assertFalse(k.colour_enabled(terminal))
        finally:
            os.environ.pop("NO_COLOR", None)
            if previous is not None:
                os.environ["NO_COLOR"] = previous

    def test_cli_output_is_deterministic(self) -> None:
        first = self.directory / "one.pdf"
        second = self.directory / "two.pdf"
        for target in (first, second):
            self.run_cli(
                [
                    str(self.source),
                    "-o",
                    str(target),
                    "--toc",
                    "--justify",
                    "--date",
                    "2026-01-01",
                ]
            )
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_date_shape_validator(self) -> None:
        self.assertEqual(k.valid_date("2026-01-01"), "2026-01-01")
        for bad in ("2026-1-1", "26-01-01", "2026/01/01", "", "x"):
            with self.subTest(value=bad):
                with self.assertRaises(argparse.ArgumentTypeError):
                    k.valid_date(bad)


# ===========================================================================
# Group 13: zero dependency self audit
# ===========================================================================


class TestZeroDependency(unittest.TestCase):
    """The build fails if a dependency, or `re`, creeps into the engine.

    The audit walks the parsed syntax tree rather than grepping the text.
    A textual search for `re.` matches `figure.` and `store.`, and a search
    for `import re` misses `__import__("re")`; walking the AST for Import
    nodes and for attribute access on a name bound to `re` does not have
    either problem. It also means the `re` rectangle operator, which appears
    inside PDF content streams as a byte string, is correctly ignored.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = ENGINE_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(ENGINE_PATH))

    def _imported_modules(self) -> set[str]:
        modules: set[str] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    modules.add(node.module.split(".")[0])
        return modules

    def test_requirements_file_is_empty(self) -> None:
        path = REPO_ROOT / "requirements.txt"
        self.assertTrue(path.exists(), "requirements.txt must exist")
        self.assertEqual(
            path.stat().st_size, 0, "requirements.txt must be zero bytes"
        )

    def test_every_import_is_standard_library(self) -> None:
        allowed = set(sys.stdlib_module_names) | {"__future__"}
        for module in sorted(self._imported_modules()):
            with self.subTest(module=module):
                self.assertIn(
                    module,
                    allowed,
                    f"{module} is not in the standard library",
                )

    def test_re_is_never_imported(self) -> None:
        self.assertNotIn("re", self._imported_modules())

    def test_re_is_never_used_as_a_name(self) -> None:
        offenders: list[int] = []
        for node in ast.walk(self.tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "re"
            ):
                offenders.append(node.lineno)
            if isinstance(node, ast.Name) and node.id == "re":
                offenders.append(node.lineno)
        self.assertEqual(offenders, [], f"`re` used on lines {offenders}")

    def test_dynamic_imports_are_not_used_to_smuggle_anything(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotEqual(
                    node.func.id,
                    "__import__",
                    f"dynamic import on line {node.lineno}",
                )

    def test_no_subprocess_or_shelling_out(self) -> None:
        """The brief forbids driving an external converter."""
        for module in ("subprocess", "os.system", "popen", "ctypes"):
            with self.subTest(module=module):
                self.assertNotIn(module, self._imported_modules())
        self.assertNotIn("os.system", self.source)
        self.assertNotIn("subprocess", self.source)

    def test_engine_is_a_single_file(self) -> None:
        python_files = sorted(
            path.name
            for path in REPO_ROOT.glob("*.py")
            if not path.name.startswith(".")
        )
        self.assertEqual(python_files, ["inkless.py", "test_inkless.py"])
        self.assertFalse(
            (REPO_ROOT / "inkless").is_dir(),
            "the implementation must not be split into a package",
        )

    def test_no_em_dashes_anywhere(self) -> None:
        """A style rule from the brief, enforced rather than remembered."""
        for path in sorted(REPO_ROOT.glob("*.py")) + sorted(
            REPO_ROOT.glob("*.md")
        ):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                # Written as an escape so this file does not itself
                # contain the character it forbids.
                self.assertNotIn("\u2014", text)

    def test_engine_has_section_banners(self) -> None:
        """The single file has to stay navigable."""
        for banner in (
            "Section 1: Source text",
            "Section 2: Abstract syntax tree",
            "Section 3: Inline parser",
            "Section 4: Block parser",
            "Section 5: Font metrics",
            "Section 6: PNG image decoding",
            "Section 7: Line breaking",
            "Section 8: Pagination and page layout",
            "Section 9: Document renderer",
            "Section 10: PDF object model",
            "Section 11: PDF document writer",
            "Section 12: Emission",
            "Section 13: Document assembly",
            "Section 14: Command line interface",
        ):
            with self.subTest(banner=banner):
                self.assertIn(banner, self.source)

    def test_public_classes_have_docstrings(self) -> None:
        for node in self.tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                if node.name.startswith("_"):
                    continue
                with self.subTest(name=node.name):
                    self.assertIsNotNone(
                        ast.get_docstring(node),
                        f"{node.name} has no docstring",
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
