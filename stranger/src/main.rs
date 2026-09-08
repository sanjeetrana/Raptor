// ===========================================================================
//
//   stranger — an offline supply-chain auditor for dependency lockfiles
//
//   "Every dependency is a stranger. This time, invite none."
//
//   Zero Dependency Hackathon 2026 · Track A (Developer Tools & CLI)
//
//   ---------------------------------------------------------------------
//
//   This is the entire program. One file. No modules on disk, no crates,
//   no build script. `rustc -O src/main.rs` produces the shipped binary.
//
//   What it does: reads a lockfile you already have on disk, reconstructs
//   the full transitive dependency graph, and reports what is actually in
//   it — how much of it nobody chose, which names look like typosquats of
//   packages you meant to install, which entries run code at install time,
//   and which arrived without an integrity hash. It never touches the
//   network. There is no registry to be down, no API key, no rate limit,
//   and nothing to leak: the lockfile is the whole input.
//
//   The irony is deliberate. A tool that audits your dependencies has no
//   business having any.
//
//   Layout (top to bottom, each section self-contained):
//
//     1. json      RFC 8259 parser + serializer          (kills serde_json)
//     2. toml      Cargo.lock array-of-tables reader     (kills toml)
//     3. pep508    requirements.txt reader               (kills packaging)
//     4. dist      bounded Damerau-Levenshtein           (kills strsim)
//     5. corpus    embedded popular/trivial name lists   (kills a network call)
//     6. graph     package graph, closure, blame paths
//     7. rules     the seven offline risk rules
//     8. render    ANSI, TTY detection, tables           (kills colored)
//     9. cli       argument parsing, subcommands         (kills clap)
//    10. tests     table-driven, including a JSONTestSuite-style corpus
//
// ===========================================================================

#![forbid(unsafe_code)]
#![deny(clippy::all)]

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet, VecDeque};
use std::io::{IsTerminal, Read};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const VERSION: &str = "1.0.0";

// ===========================================================================
// 1. json — a complete RFC 8259 parser, written by hand
// ===========================================================================
//
// Would normally be: serde + serde_json (serde_json alone is one of the most
// installed crates on crates.io and pulls serde, serde_derive, syn, quote and
// proc-macro2 behind it — five crates and a procedural macro to read a text
// file).
//
// What we need is a fraction of that: parse a document, walk it, and emit one
// back. Written directly it is about 400 lines, has no macro expansion, no
// derive, and reports errors with a line and column — which serde_json's
// default output does too, but which we get here for free because we are the
// ones holding the cursor.
//
// Strictness notes, because a parser that is lenient in the wrong places is
// how malformed input becomes a security bug:
//   - no trailing commas, no comments, no single quotes, no NaN/Infinity
//   - unescaped control characters (U+0000..U+001F) inside strings rejected
//   - \u escapes validated, surrogate pairs joined, lone surrogates rejected
//   - number grammar is exactly the RFC railroad diagram: no leading +, no
//     leading zeros, no bare `.5`, no trailing `.`
//   - nesting depth capped, so a hostile lockfile cannot blow the stack
// ===========================================================================

mod json {
    use std::collections::BTreeMap;
    use std::fmt;

    /// Maximum nesting depth. A real package-lock.json nests maybe 8 levels.
    /// A file that nests 512 is not a lockfile, it is an attempt to crash us.
    pub const MAX_DEPTH: usize = 512;

    #[derive(Debug, Clone, PartialEq)]
    pub enum Value {
        Null,
        Bool(bool),
        /// The raw lexeme is kept alongside the parsed double so that
        /// round-tripping a lockfile does not silently rewrite `1.0` as `1`
        /// or lose precision on a u64 that does not fit an f64.
        Num(f64, String),
        Str(String),
        Arr(Vec<Value>),
        /// BTreeMap, not HashMap: key order must be deterministic, because
        /// `--json` output feeds the reproducible-build check and diffing two
        /// reports should not produce spurious churn.
        Obj(BTreeMap<String, Value>),
    }

    impl Value {
        pub fn get(&self, key: &str) -> Option<&Value> {
            match self {
                Value::Obj(m) => m.get(key),
                _ => None,
            }
        }

        pub fn as_str(&self) -> Option<&str> {
            match self {
                Value::Str(s) => Some(s),
                _ => None,
            }
        }

        pub fn as_bool(&self) -> Option<bool> {
            match self {
                Value::Bool(b) => Some(*b),
                _ => None,
            }
        }

        pub fn as_obj(&self) -> Option<&BTreeMap<String, Value>> {
            match self {
                Value::Obj(m) => Some(m),
                _ => None,
            }
        }

        pub fn as_u64(&self) -> Option<u64> {
            match self {
                Value::Num(n, _) if *n >= 0.0 && n.fract() == 0.0 => Some(*n as u64),
                _ => None,
            }
        }

    }

    #[derive(Debug, Clone, PartialEq)]
    pub struct Error {
        pub msg: String,
        pub line: usize,
        pub col: usize,
        pub offset: usize,
    }

    impl fmt::Display for Error {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            write!(f, "{} at line {} column {}", self.msg, self.line, self.col)
        }
    }

    pub struct Parser<'a> {
        src: &'a [u8],
        pos: usize,
        line: usize,
        line_start: usize,
        depth: usize,
    }

    pub fn parse(src: &str) -> Result<Value, Error> {
        let mut p = Parser {
            src: src.as_bytes(),
            pos: 0,
            line: 1,
            line_start: 0,
            depth: 0,
        };
        p.skip_ws();
        let v = p.value()?;
        p.skip_ws();
        if p.pos < p.src.len() {
            return Err(p.err("trailing data after top-level value"));
        }
        Ok(v)
    }

    impl<'a> Parser<'a> {
        fn err(&self, msg: &str) -> Error {
            Error {
                msg: msg.to_string(),
                line: self.line,
                col: self.pos - self.line_start + 1,
                offset: self.pos,
            }
        }

        fn peek(&self) -> Option<u8> {
            self.src.get(self.pos).copied()
        }

        fn bump(&mut self) -> Option<u8> {
            let b = self.src.get(self.pos).copied()?;
            self.pos += 1;
            if b == b'\n' {
                self.line += 1;
                self.line_start = self.pos;
            }
            Some(b)
        }

        /// RFC 8259 whitespace is exactly these four bytes. Not \x0b, not
        /// \x0c, not U+00A0. Being generous here is how you accept files
        /// other tools reject, which is its own kind of bug.
        fn skip_ws(&mut self) {
            while let Some(b) = self.peek() {
                match b {
                    b' ' | b'\t' | b'\n' | b'\r' => {
                        self.bump();
                    }
                    _ => break,
                }
            }
        }

        fn expect(&mut self, want: u8) -> Result<(), Error> {
            match self.peek() {
                Some(b) if b == want => {
                    self.bump();
                    Ok(())
                }
                Some(b) => Err(self.err(&format!(
                    "expected `{}` but found `{}`",
                    want as char, b as char
                ))),
                None => Err(self.err(&format!("expected `{}` but reached end of input", want as char))),
            }
        }

        fn value(&mut self) -> Result<Value, Error> {
            if self.depth >= MAX_DEPTH {
                return Err(self.err("maximum nesting depth exceeded"));
            }
            match self.peek() {
                Some(b'{') => self.object(),
                Some(b'[') => self.array(),
                Some(b'"') => Ok(Value::Str(self.string()?)),
                Some(b't') => self.literal("true", Value::Bool(true)),
                Some(b'f') => self.literal("false", Value::Bool(false)),
                Some(b'n') => self.literal("null", Value::Null),
                Some(b'-') | Some(b'0'..=b'9') => self.number(),
                Some(b) => Err(self.err(&format!("unexpected character `{}`", b as char))),
                None => Err(self.err("unexpected end of input")),
            }
        }

        fn literal(&mut self, word: &str, v: Value) -> Result<Value, Error> {
            let start = self.pos;
            if self.src.len() >= start + word.len()
                && &self.src[start..start + word.len()] == word.as_bytes()
            {
                for _ in 0..word.len() {
                    self.bump();
                }
                Ok(v)
            } else {
                Err(self.err(&format!("invalid literal, expected `{word}`")))
            }
        }

        fn object(&mut self) -> Result<Value, Error> {
            self.expect(b'{')?;
            self.depth += 1;
            let mut map = BTreeMap::new();
            self.skip_ws();
            if self.peek() == Some(b'}') {
                self.bump();
                self.depth -= 1;
                return Ok(Value::Obj(map));
            }
            loop {
                self.skip_ws();
                if self.peek() != Some(b'"') {
                    return Err(self.err("object key must be a string"));
                }
                let k = self.string()?;
                self.skip_ws();
                self.expect(b':')?;
                self.skip_ws();
                let v = self.value()?;
                // Duplicate keys are legal-but-undefined in the RFC. We take
                // last-wins (matching every mainstream parser) rather than
                // erroring, because real lockfiles in the wild do contain
                // them and refusing to audit a file is worse than auditing
                // it the way node would read it.
                map.insert(k, v);
                self.skip_ws();
                match self.peek() {
                    Some(b',') => {
                        self.bump();
                        self.skip_ws();
                        // Explicitly reject `{"a":1,}`.
                        if self.peek() == Some(b'}') {
                            return Err(self.err("trailing comma in object"));
                        }
                    }
                    Some(b'}') => {
                        self.bump();
                        break;
                    }
                    Some(_) => return Err(self.err("expected `,` or `}` in object")),
                    None => return Err(self.err("unterminated object")),
                }
            }
            self.depth -= 1;
            Ok(Value::Obj(map))
        }

        fn array(&mut self) -> Result<Value, Error> {
            self.expect(b'[')?;
            self.depth += 1;
            let mut out = Vec::new();
            self.skip_ws();
            if self.peek() == Some(b']') {
                self.bump();
                self.depth -= 1;
                return Ok(Value::Arr(out));
            }
            loop {
                self.skip_ws();
                out.push(self.value()?);
                self.skip_ws();
                match self.peek() {
                    Some(b',') => {
                        self.bump();
                        self.skip_ws();
                        if self.peek() == Some(b']') {
                            return Err(self.err("trailing comma in array"));
                        }
                    }
                    Some(b']') => {
                        self.bump();
                        break;
                    }
                    Some(_) => return Err(self.err("expected `,` or `]` in array")),
                    None => return Err(self.err("unterminated array")),
                }
            }
            self.depth -= 1;
            Ok(Value::Arr(out))
        }

        fn string(&mut self) -> Result<String, Error> {
            self.expect(b'"')?;
            let mut out = String::new();
            loop {
                let b = match self.bump() {
                    Some(b) => b,
                    None => return Err(self.err("unterminated string")),
                };
                match b {
                    b'"' => return Ok(out),
                    b'\\' => {
                        let e = match self.bump() {
                            Some(e) => e,
                            None => return Err(self.err("unterminated escape sequence")),
                        };
                        match e {
                            b'"' => out.push('"'),
                            b'\\' => out.push('\\'),
                            b'/' => out.push('/'),
                            b'b' => out.push('\u{0008}'),
                            b'f' => out.push('\u{000C}'),
                            b'n' => out.push('\n'),
                            b'r' => out.push('\r'),
                            b't' => out.push('\t'),
                            b'u' => {
                                let hi = self.hex4()?;
                                // Surrogate pair handling. This is the single
                                // most commonly botched part of a hand-rolled
                                // JSON parser, so it gets explicit cases:
                                // a high surrogate MUST be followed by \uDC00
                                // ..\uDFFF, and a lone low surrogate is an
                                // error rather than a replacement character.
                                if (0xD800..0xDC00).contains(&hi) {
                                    if self.peek() != Some(b'\\') {
                                        return Err(self.err(
                                            "high surrogate not followed by an escape sequence",
                                        ));
                                    }
                                    self.bump();
                                    if self.peek() != Some(b'u') {
                                        return Err(self
                                            .err("high surrogate not followed by \\u escape"));
                                    }
                                    self.bump();
                                    let lo = self.hex4()?;
                                    if !(0xDC00..0xE000).contains(&lo) {
                                        return Err(
                                            self.err("high surrogate followed by non-low surrogate")
                                        );
                                    }
                                    let c = 0x1_0000
                                        + ((hi as u32 - 0xD800) << 10)
                                        + (lo as u32 - 0xDC00);
                                    match char::from_u32(c) {
                                        Some(ch) => out.push(ch),
                                        None => return Err(self.err("invalid surrogate pair")),
                                    }
                                } else if (0xDC00..0xE000).contains(&hi) {
                                    return Err(self.err("unpaired low surrogate"));
                                } else {
                                    match char::from_u32(hi as u32) {
                                        Some(ch) => out.push(ch),
                                        None => return Err(self.err("invalid \\u escape")),
                                    }
                                }
                            }
                            other => {
                                return Err(
                                    self.err(&format!("invalid escape `\\{}`", other as char))
                                )
                            }
                        }
                    }
                    // Raw control characters are forbidden inside strings.
                    0x00..=0x1F => {
                        return Err(self.err(&format!(
                            "unescaped control character U+{b:04X} in string"
                        )))
                    }
                    // Everything else is UTF-8 we can copy through. We are
                    // iterating bytes, so multi-byte sequences arrive one
                    // byte at a time; collect the continuation bytes and
                    // validate, rather than assuming well-formed input.
                    _ if b < 0x80 => out.push(b as char),
                    _ => {
                        let len = utf8_len(b);
                        if len == 0 {
                            return Err(self.err("invalid UTF-8 start byte in string"));
                        }
                        let start = self.pos - 1;
                        for _ in 1..len {
                            match self.peek() {
                                Some(c) if (0x80..0xC0).contains(&c) => {
                                    self.bump();
                                }
                                _ => return Err(self.err("truncated UTF-8 sequence in string")),
                            }
                        }
                        match std::str::from_utf8(&self.src[start..self.pos]) {
                            Ok(s) => out.push_str(s),
                            Err(_) => return Err(self.err("invalid UTF-8 sequence in string")),
                        }
                    }
                }
            }
        }

        fn hex4(&mut self) -> Result<u16, Error> {
            let mut v: u16 = 0;
            for _ in 0..4 {
                let b = match self.bump() {
                    Some(b) => b,
                    None => return Err(self.err("truncated \\u escape")),
                };
                let d = match b {
                    b'0'..=b'9' => b - b'0',
                    b'a'..=b'f' => b - b'a' + 10,
                    b'A'..=b'F' => b - b'A' + 10,
                    _ => return Err(self.err("invalid hex digit in \\u escape")),
                };
                v = v * 16 + d as u16;
            }
            Ok(v)
        }

        /// The RFC number grammar, transcribed directly:
        ///   number = [ minus ] int [ frac ] [ exp ]
        ///   int    = zero / ( digit1-9 *DIGIT )
        fn number(&mut self) -> Result<Value, Error> {
            let start = self.pos;
            if self.peek() == Some(b'-') {
                self.bump();
            }
            match self.peek() {
                Some(b'0') => {
                    self.bump();
                    // `01` is not a number. Leading zeros are how you smuggle
                    // an octal interpretation past a lenient reader.
                    if matches!(self.peek(), Some(b'0'..=b'9')) {
                        return Err(self.err("leading zeros are not allowed in numbers"));
                    }
                }
                Some(b'1'..=b'9') => {
                    while matches!(self.peek(), Some(b'0'..=b'9')) {
                        self.bump();
                    }
                }
                _ => return Err(self.err("expected a digit")),
            }
            if self.peek() == Some(b'.') {
                self.bump();
                if !matches!(self.peek(), Some(b'0'..=b'9')) {
                    return Err(self.err("expected a digit after the decimal point"));
                }
                while matches!(self.peek(), Some(b'0'..=b'9')) {
                    self.bump();
                }
            }
            if matches!(self.peek(), Some(b'e') | Some(b'E')) {
                self.bump();
                if matches!(self.peek(), Some(b'+') | Some(b'-')) {
                    self.bump();
                }
                if !matches!(self.peek(), Some(b'0'..=b'9')) {
                    return Err(self.err("expected a digit in the exponent"));
                }
                while matches!(self.peek(), Some(b'0'..=b'9')) {
                    self.bump();
                }
            }
            let raw = std::str::from_utf8(&self.src[start..self.pos])
                .map_err(|_| self.err("invalid UTF-8 in number"))?;
            match raw.parse::<f64>() {
                Ok(n) => Ok(Value::Num(n, raw.to_string())),
                Err(_) => Err(self.err("number out of range")),
            }
        }
    }

    fn utf8_len(b: u8) -> usize {
        match b {
            0xC2..=0xDF => 2,
            0xE0..=0xEF => 3,
            0xF0..=0xF4 => 4,
            _ => 0,
        }
    }

    // -----------------------------------------------------------------------
    // Serializer. `--json` output has to be machine-readable and stable, so
    // this emits sorted keys (BTreeMap gives us that for free) and escapes
    // conservatively.
    // -----------------------------------------------------------------------

    pub fn escape(s: &str, out: &mut String) {
        out.push('"');
        for c in s.chars() {
            match c {
                '"' => out.push_str("\\\""),
                '\\' => out.push_str("\\\\"),
                '\n' => out.push_str("\\n"),
                '\r' => out.push_str("\\r"),
                '\t' => out.push_str("\\t"),
                '\u{0008}' => out.push_str("\\b"),
                '\u{000C}' => out.push_str("\\f"),
                c if (c as u32) < 0x20 => {
                    out.push_str(&format!("\\u{:04x}", c as u32));
                }
                c => out.push(c),
            }
        }
        out.push('"');
    }

    pub fn write(v: &Value, indent: usize, out: &mut String) {
        let pad = "  ".repeat(indent);
        let pad_in = "  ".repeat(indent + 1);
        match v {
            Value::Null => out.push_str("null"),
            Value::Bool(true) => out.push_str("true"),
            Value::Bool(false) => out.push_str("false"),
            Value::Num(_, raw) => out.push_str(raw),
            Value::Str(s) => escape(s, out),
            Value::Arr(a) if a.is_empty() => out.push_str("[]"),
            Value::Arr(a) => {
                out.push_str("[\n");
                for (i, item) in a.iter().enumerate() {
                    out.push_str(&pad_in);
                    write(item, indent + 1, out);
                    if i + 1 < a.len() {
                        out.push(',');
                    }
                    out.push('\n');
                }
                out.push_str(&pad);
                out.push(']');
            }
            Value::Obj(m) if m.is_empty() => out.push_str("{}"),
            Value::Obj(m) => {
                out.push_str("{\n");
                let n = m.len();
                for (i, (k, val)) in m.iter().enumerate() {
                    out.push_str(&pad_in);
                    escape(k, out);
                    out.push_str(": ");
                    write(val, indent + 1, out);
                    if i + 1 < n {
                        out.push(',');
                    }
                    out.push('\n');
                }
                out.push_str(&pad);
                out.push('}');
            }
        }
    }

    pub fn to_string(v: &Value) -> String {
        let mut s = String::new();
        write(v, 0, &mut s);
        s
    }

    /// Builder helpers, so the report code reads like data rather than like
    /// string concatenation.
    pub fn obj(pairs: Vec<(&str, Value)>) -> Value {
        let mut m = BTreeMap::new();
        for (k, v) in pairs {
            m.insert(k.to_string(), v);
        }
        Value::Obj(m)
    }

    pub fn s(v: &str) -> Value {
        Value::Str(v.to_string())
    }

    pub fn n(v: usize) -> Value {
        Value::Num(v as f64, v.to_string())
    }
}

// ===========================================================================
// 2. toml — the slice of TOML that Cargo.lock actually uses
// ===========================================================================
//
// Would normally be: the `toml` crate (which pulls serde, and in recent
// versions toml_edit and winnow behind it).
//
// The honest framing, because this is exactly the kind of thing STDLIB.md
// exists to keep me truthful about: this is NOT a TOML implementation. It is
// a reader for the subset Cargo emits into Cargo.lock — top-level key/value
// pairs, arrays of tables, basic and literal strings, integers, and arrays of
// strings. It does not do inline tables, dotted keys, datetimes, floats, or
// multi-line strings, and it will tell you so rather than guessing.
//
// That is a defensible trade. A general TOML parser is a week; the Cargo.lock
// dialect is an afternoon, and Cargo.lock is a machine-generated file with a
// fixed shape. Where the subset ends, `Error::Unsupported` begins — the tool
// says "this construct is outside the subset I implement" instead of silently
// mis-parsing, which is the failure mode that actually hurts.
// ===========================================================================

mod toml {
    use std::collections::BTreeMap;
    use std::fmt;

    #[derive(Debug, Clone, PartialEq)]
    pub enum Value {
        Str(String),
        Int(i64),
        Bool(bool),
        Arr(Vec<Value>),
    }

    impl Value {
        pub fn as_str(&self) -> Option<&str> {
            match self {
                Value::Str(s) => Some(s),
                _ => None,
            }
        }
        pub fn as_arr(&self) -> Option<&Vec<Value>> {
            match self {
                Value::Arr(a) => Some(a),
                _ => None,
            }
        }
    }

    pub type Table = BTreeMap<String, Value>;

    #[derive(Debug, Default)]
    pub struct Document {
        /// Top-level `key = value` pairs, e.g. `version = 4`.
        pub root: Table,
        /// `[[name]]` array-of-table sections, keyed by section name.
        pub arrays: BTreeMap<String, Vec<Table>>,
    }

    #[derive(Debug, Clone, PartialEq)]
    pub struct Error {
        pub msg: String,
        pub line: usize,
    }

    impl fmt::Display for Error {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            write!(f, "{} at line {}", self.msg, self.line)
        }
    }

    pub fn parse(src: &str) -> Result<Document, Error> {
        let mut doc = Document::default();
        // `None` means we are writing into the root table; `Some(name)` means
        // we are writing into the last table pushed onto arrays[name].
        let mut current: Option<String> = None;

        let mut lines = src.lines().enumerate().peekable();
        while let Some((idx, raw)) = lines.next() {
            let mut lineno = idx + 1;
            let line = strip_comment(raw).trim();
            if line.is_empty() {
                continue;
            }

            if let Some(rest) = line.strip_prefix("[[") {
                let name = rest.strip_suffix("]]").ok_or(Error {
                    msg: "unterminated [[array of tables]] header".into(),
                    line: lineno,
                })?;
                let name = name.trim().to_string();
                doc.arrays.entry(name.clone()).or_default().push(Table::new());
                current = Some(name);
                continue;
            }

            if line.starts_with('[') {
                // A plain [table] header. Cargo.lock does not emit these, so
                // rather than half-supporting them we reset to root and skip.
                // Anything inside would land in the root table, which is the
                // least surprising behaviour for a file we do not expect.
                current = None;
                continue;
            }

            let eq = line.find('=').ok_or(Error {
                msg: "expected `key = value`".into(),
                line: lineno,
            })?;
            let key = unquote_key(line[..eq].trim());
            let rhs = line[eq + 1..].trim();

            // Arrays may open on this line and close several lines later,
            // which is exactly how Cargo formats `dependencies = [...]`.
            let value = if rhs.starts_with('[') && !balanced(rhs) {
                let mut buf = rhs.to_string();
                loop {
                    let (i2, more) = lines.next().ok_or(Error {
                        msg: "unterminated array".into(),
                        line: lineno,
                    })?;
                    lineno = i2 + 1;
                    buf.push(' ');
                    buf.push_str(strip_comment(more).trim());
                    if balanced(&buf) {
                        break;
                    }
                }
                parse_value(&buf, lineno)?
            } else {
                parse_value(rhs, lineno)?
            };

            match &current {
                None => {
                    doc.root.insert(key, value);
                }
                Some(name) => {
                    if let Some(tbl) = doc.arrays.get_mut(name).and_then(|v| v.last_mut()) {
                        tbl.insert(key, value);
                    }
                }
            }
        }
        Ok(doc)
    }

    /// Strip a `#` comment, but only when the `#` is outside a string. The
    /// naive `split('#').next()` breaks on `checksum = "ab#cd"`, which is
    /// rare but not impossible, and on source URLs containing a fragment.
    fn strip_comment(line: &str) -> &str {
        let b = line.as_bytes();
        let mut in_basic = false;
        let mut in_literal = false;
        let mut i = 0;
        while i < b.len() {
            match b[i] {
                b'\\' if in_basic => i += 1,
                b'"' if !in_literal => in_basic = !in_basic,
                b'\'' if !in_basic => in_literal = !in_literal,
                b'#' if !in_basic && !in_literal => return &line[..i],
                _ => {}
            }
            i += 1;
        }
        line
    }

    fn balanced(s: &str) -> bool {
        let b = s.as_bytes();
        let mut depth = 0i32;
        let mut in_basic = false;
        let mut in_literal = false;
        let mut i = 0;
        while i < b.len() {
            match b[i] {
                b'\\' if in_basic => i += 1,
                b'"' if !in_literal => in_basic = !in_basic,
                b'\'' if !in_basic => in_literal = !in_literal,
                b'[' if !in_basic && !in_literal => depth += 1,
                b']' if !in_basic && !in_literal => depth -= 1,
                _ => {}
            }
            i += 1;
        }
        depth == 0
    }

    fn unquote_key(k: &str) -> String {
        let k = k.trim();
        if (k.starts_with('"') && k.ends_with('"') && k.len() >= 2)
            || (k.starts_with('\'') && k.ends_with('\'') && k.len() >= 2)
        {
            k[1..k.len() - 1].to_string()
        } else {
            k.to_string()
        }
    }

    fn parse_value(s: &str, line: usize) -> Result<Value, Error> {
        let s = s.trim();
        if s.is_empty() {
            return Err(Error {
                msg: "missing value".into(),
                line,
            });
        }
        if s == "true" {
            return Ok(Value::Bool(true));
        }
        if s == "false" {
            return Ok(Value::Bool(false));
        }
        if let Some(body) = s.strip_prefix('[') {
            let body = body.strip_suffix(']').ok_or(Error {
                msg: "unterminated array".into(),
                line,
            })?;
            let mut out = Vec::new();
            for item in split_top_level(body) {
                let item = item.trim();
                if item.is_empty() {
                    continue;
                }
                out.push(parse_value(item, line)?);
            }
            return Ok(Value::Arr(out));
        }
        if s.starts_with('\'') {
            // Literal string: no escapes at all, by definition.
            let body = s.strip_prefix('\'').and_then(|r| r.strip_suffix('\'')).ok_or(
                Error {
                    msg: "unterminated literal string".into(),
                    line,
                },
            )?;
            return Ok(Value::Str(body.to_string()));
        }
        if s.starts_with('"') {
            return Ok(Value::Str(unescape_basic(s, line)?));
        }
        if s.starts_with("{") {
            return Err(Error {
                msg: "inline tables are outside the Cargo.lock subset this reader implements"
                    .into(),
                line,
            });
        }
        // Integers, with TOML's underscore separators.
        let cleaned: String = s.chars().filter(|c| *c != '_').collect();
        if let Ok(i) = cleaned.parse::<i64>() {
            return Ok(Value::Int(i));
        }
        Err(Error {
            msg: format!("unsupported value `{s}` (this reader covers the Cargo.lock subset only)"),
            line,
        })
    }

    fn unescape_basic(s: &str, line: usize) -> Result<String, Error> {
        let inner = s.strip_prefix('"').and_then(|r| r.strip_suffix('"')).ok_or(Error {
            msg: "unterminated basic string".into(),
            line,
        })?;
        let mut out = String::new();
        let mut it = inner.chars();
        while let Some(c) = it.next() {
            if c != '\\' {
                out.push(c);
                continue;
            }
            match it.next() {
                Some('n') => out.push('\n'),
                Some('t') => out.push('\t'),
                Some('r') => out.push('\r'),
                Some('"') => out.push('"'),
                Some('\\') => out.push('\\'),
                Some('b') => out.push('\u{0008}'),
                Some('f') => out.push('\u{000C}'),
                Some('u') => {
                    let hex: String = it.by_ref().take(4).collect();
                    let cp = u32::from_str_radix(&hex, 16).map_err(|_| Error {
                        msg: "invalid \\u escape".into(),
                        line,
                    })?;
                    out.push(char::from_u32(cp).ok_or(Error {
                        msg: "invalid unicode scalar in \\u escape".into(),
                        line,
                    })?);
                }
                Some(other) => {
                    return Err(Error {
                        msg: format!("invalid escape `\\{other}`"),
                        line,
                    })
                }
                None => {
                    return Err(Error {
                        msg: "unterminated escape".into(),
                        line,
                    })
                }
            }
        }
        Ok(out)
    }

    /// Split on commas that are not inside a string or a nested array.
    fn split_top_level(s: &str) -> Vec<&str> {
        let b = s.as_bytes();
        let mut out = Vec::new();
        let mut start = 0;
        let mut depth = 0i32;
        let mut in_basic = false;
        let mut in_literal = false;
        let mut i = 0;
        while i < b.len() {
            match b[i] {
                b'\\' if in_basic => i += 1,
                b'"' if !in_literal => in_basic = !in_basic,
                b'\'' if !in_basic => in_literal = !in_literal,
                b'[' if !in_basic && !in_literal => depth += 1,
                b']' if !in_basic && !in_literal => depth -= 1,
                b',' if depth == 0 && !in_basic && !in_literal => {
                    out.push(&s[start..i]);
                    start = i + 1;
                }
                _ => {}
            }
            i += 1;
        }
        if start <= s.len() {
            out.push(&s[start..]);
        }
        out
    }
}

// ===========================================================================
// 3. pep508 — requirements.txt, read the way pip reads it
// ===========================================================================
//
// Would normally be: `packaging` (for Requirement / SpecifierSet) or
// `pip-requirements-parser`.
//
// requirements.txt is deceptively hostile. It is line-oriented, but lines
// continue with a backslash; it carries pip flags mixed in with package
// names; it has environment markers after a semicolon, extras in brackets,
// direct URL references with `@`, and per-requirement hashes. Getting the
// pin/range distinction right matters here because "unpinned dependency" is
// one of the findings we report, and reporting it wrongly is worse than not
// reporting it.
// ===========================================================================

mod pep508 {
    #[derive(Debug, Clone, PartialEq)]
    pub struct Requirement {
        pub name: String,
        pub extras: Vec<String>,
        /// The raw specifier text, e.g. `==1.2.3` or `>=1.0,<2`.
        pub spec: String,
        pub marker: Option<String>,
        /// A direct reference: `pkg @ https://…`. These bypass the index
        /// entirely, which is worth flagging.
        pub url: Option<String>,
        pub hashes: Vec<String>,
        pub line: usize,
    }

    impl Requirement {
        /// Exactly pinned to one version: `==1.2.3` or `===1.2.3`.
        pub fn is_pinned(&self) -> bool {
            let s = self.spec.trim();
            if s.is_empty() {
                return false;
            }
            // A single `==` clause with no wildcard is a pin. `==1.2.*` is not.
            let clauses: Vec<&str> = s.split(',').map(str::trim).collect();
            clauses.len() == 1
                && (clauses[0].starts_with("===")
                    || (clauses[0].starts_with("==") && !clauses[0].contains('*')))
        }

    }

    #[derive(Debug, Default)]
    pub struct File {
        pub requirements: Vec<Requirement>,
        /// `-r other.txt` includes we saw but did not follow.
        pub includes: Vec<String>,
        /// `-e .` / `--editable` entries.
        pub editables: Vec<String>,
        /// Index overrides: `--index-url`, `--extra-index-url`. A requirements
        /// file that points at a non-PyPI index is a supply-chain fact.
        pub index_urls: Vec<String>,
    }

    pub fn parse(src: &str) -> File {
        let mut out = File::default();

        // First fold backslash continuations, keeping track of the line
        // number the logical line started on so errors stay useful.
        let mut logical: Vec<(usize, String)> = Vec::new();
        let mut buf = String::new();
        let mut start_line = 1usize;
        for (i, raw) in src.lines().enumerate() {
            if buf.is_empty() {
                start_line = i + 1;
            }
            if let Some(stripped) = raw.strip_suffix('\\') {
                buf.push_str(stripped);
                buf.push(' ');
                continue;
            }
            buf.push_str(raw);
            logical.push((start_line, std::mem::take(&mut buf)));
        }
        if !buf.is_empty() {
            logical.push((start_line, buf));
        }

        for (lineno, raw) in logical {
            let line = strip_comment(&raw).trim().to_string();
            if line.is_empty() {
                continue;
            }

            if line.starts_with('-') {
                let (flag, rest) = split_flag(&line);
                match flag.as_str() {
                    "-r" | "--requirement" | "-c" | "--constraint" => {
                        out.includes.push(rest.to_string())
                    }
                    "-e" | "--editable" => out.editables.push(rest.to_string()),
                    "-i" | "--index-url" | "--extra-index-url" => {
                        out.index_urls.push(rest.to_string())
                    }
                    _ => {} // --no-binary, --hash on its own line, etc.
                }
                continue;
            }

            if let Some(req) = parse_requirement(&line, lineno) {
                out.requirements.push(req);
            }
        }
        out
    }

    fn split_flag(line: &str) -> (String, &str) {
        let line = line.trim();
        if let Some(eq) = line.find('=') {
            if line[..eq].starts_with("--") {
                return (line[..eq].to_string(), line[eq + 1..].trim());
            }
        }
        match line.find(char::is_whitespace) {
            Some(i) => (line[..i].to_string(), line[i..].trim()),
            None => (line.to_string(), ""),
        }
    }

    fn strip_comment(line: &str) -> &str {
        // pip only treats ` #` (whitespace then hash) or a leading `#` as a
        // comment, so that URL fragments like `#egg=foo` survive.
        if line.trim_start().starts_with('#') {
            return "";
        }
        let b = line.as_bytes();
        for i in 1..b.len() {
            if b[i] == b'#' && (b[i - 1] == b' ' || b[i - 1] == b'\t') {
                return &line[..i];
            }
        }
        line
    }

    fn parse_requirement(line: &str, lineno: usize) -> Option<Requirement> {
        // Pull every `--hash=sha256:…` token out of the line first. They can
        // appear repeatedly and anywhere after the requirement, usually on
        // continuation lines that we have already folded into this one.
        let mut hashes = Vec::new();
        let mut kept = String::with_capacity(line.len());
        for token in line.split_whitespace() {
            if let Some(v) = token.strip_prefix("--hash=") {
                if !v.is_empty() {
                    hashes.push(v.to_string());
                }
                continue;
            }
            if !kept.is_empty() {
                kept.push(' ');
            }
            kept.push_str(token);
        }
        finish(&kept, hashes, lineno)
    }

    fn finish(line: &str, hashes: Vec<String>, lineno: usize) -> Option<Requirement> {
        let line = line.trim();
        if line.is_empty() {
            return None;
        }

        // Environment marker.
        let (head, marker) = match line.split_once(';') {
            Some((h, m)) => (h.trim(), Some(m.trim().to_string())),
            None => (line, None),
        };

        // Direct URL reference: `name @ url`.
        let (head, url) = match head.split_once(" @ ") {
            Some((n, u)) => (n.trim(), Some(u.trim().to_string())),
            None => (head, None),
        };

        // Extras.
        let (name_part, extras) = match head.find('[') {
            Some(i) => {
                let close = head[i..].find(']').map(|j| i + j)?;
                let ex: Vec<String> = head[i + 1..close]
                    .split(',')
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
                    .collect();
                let mut merged = String::from(&head[..i]);
                merged.push_str(&head[close + 1..]);
                (merged, ex)
            }
            None => (head.to_string(), Vec::new()),
        };

        // The name runs until the first specifier operator.
        let ops = ['=', '<', '>', '!', '~'];
        let cut = name_part.find(ops).unwrap_or(name_part.len());
        let name = name_part[..cut].trim().to_string();
        let spec = name_part[cut..].trim().to_string();

        if name.is_empty() || !name.chars().next()?.is_ascii_alphanumeric() {
            return None;
        }

        Some(Requirement {
            name,
            extras,
            spec,
            marker,
            url,
            hashes,
            line: lineno,
        })
    }

    /// PEP 503 normalisation. `Flask`, `flask`, and `FLASK_` all name the same
    /// project, and a typosquat check that does not normalise first will
    /// report noise.
    pub fn normalize(name: &str) -> String {
        let mut out = String::with_capacity(name.len());
        let mut last_dash = false;
        for c in name.chars() {
            let c = c.to_ascii_lowercase();
            if c == '-' || c == '_' || c == '.' {
                if !last_dash {
                    out.push('-');
                    last_dash = true;
                }
            } else {
                out.push(c);
                last_dash = false;
            }
        }
        out.trim_matches('-').to_string()
    }
}

// ===========================================================================
// 4. dist — bounded Damerau-Levenshtein (optimal string alignment)
// ===========================================================================
//
// Would normally be: `strsim`.
//
// Plain Levenshtein is the wrong metric for typosquatting. The single most
// common human typo is a transposition — `recieve`, `lodahs`, `axois` — and
// Levenshtein charges 2 for a swap, the same as two unrelated edits. Damerau
// charges 1, which puts real squats inside a distance-1 ball and keeps
// unrelated packages out of it.
//
// Two implementation notes that matter more than the algorithm:
//
//   1. Bounded. We compare every package name against ~500 corpus names.
//      A full O(mn) matrix for each pair is wasteful when we only care
//      whether the distance is <= 2. `bounded()` bails out as soon as an
//      entire row exceeds the limit, which turns most comparisons into a
//      few dozen operations.
//
//   2. Two rolling rows, not a full matrix. Distance is computed from the
//      previous two rows only, so memory is O(min(m,n)) instead of O(mn).
// ===========================================================================

mod dist {
    /// Damerau-Levenshtein (OSA variant) with early exit.
    /// Returns `None` when the true distance exceeds `max`.
    pub fn bounded(a: &str, b: &str, max: usize) -> Option<usize> {
        let a: Vec<char> = a.chars().collect();
        let b: Vec<char> = b.chars().collect();
        let (n, m) = (a.len(), b.len());

        // A length difference greater than max cannot be closed by edits.
        if n.abs_diff(m) > max {
            return None;
        }
        if n == 0 {
            return if m <= max { Some(m) } else { None };
        }
        if m == 0 {
            return if n <= max { Some(n) } else { None };
        }

        // prev2 is needed for the transposition case; that is the whole
        // difference between this and plain Levenshtein.
        let mut prev2: Vec<usize> = vec![0; m + 1];
        let mut prev: Vec<usize> = (0..=m).collect();
        let mut cur: Vec<usize> = vec![0; m + 1];

        for i in 1..=n {
            cur[0] = i;
            let mut row_min = cur[0];
            for j in 1..=m {
                let cost = usize::from(a[i - 1] != b[j - 1]);
                let mut v = (cur[j - 1] + 1)      // insertion
                    .min(prev[j] + 1)             // deletion
                    .min(prev[j - 1] + cost);     // substitution
                if i > 1 && j > 1 && a[i - 1] == b[j - 2] && a[i - 2] == b[j - 1] {
                    v = v.min(prev2[j - 2] + 1); // transposition
                }
                cur[j] = v;
                row_min = row_min.min(v);
            }
            // Every future row is >= this row's minimum, so if the whole row
            // is already past the budget we can stop.
            if row_min > max {
                return None;
            }
            std::mem::swap(&mut prev2, &mut prev);
            std::mem::swap(&mut prev, &mut cur);
        }
        let d = prev[m];
        if d <= max {
            Some(d)
        } else {
            None
        }
    }

    /// Confusable-character folding. Registry squatters do not only rely on
    /// typos — they rely on glyphs that read the same in a terminal font.
    /// Folding `1`->`l`, `0`->`o`, `rn`->`m`, and stripping separators turns
    /// `l0dash`, `1odash` and `lo-dash` into the same skeleton as `lodash`,
    /// which catches a class of squat that edit distance alone misses because
    /// the substitution is deliberate and minimal.
    pub fn skeleton(name: &str) -> String {
        let lowered = name.to_ascii_lowercase().replace("rn", "m").replace("vv", "w");
        let mut out = String::with_capacity(lowered.len());
        for c in lowered.chars() {
            match c {
                '-' | '_' | '.' => {}
                '0' => out.push('o'),
                '1' | '|' => out.push('l'),
                '5' => out.push('s'),
                '3' => out.push('e'),
                c => out.push(c),
            }
        }
        out
    }

    /// npm scoped names (`@scope/pkg`) compare badly as whole strings: every
    /// `@types/*` package is distance-2 from every other. Split them so the
    /// scope and the bare name are judged separately.
    pub fn split_scope(name: &str) -> (Option<&str>, &str) {
        if let Some(rest) = name.strip_prefix('@') {
            if let Some((scope, pkg)) = rest.split_once('/') {
                return (Some(scope), pkg);
            }
        }
        (None, name)
    }
}

// ===========================================================================
// 5. corpus — the reference lists, embedded in the binary
// ===========================================================================
//
// Would normally be: a network call to the registry's download-counts API,
// or a crate that vendors a name list.
//
// Neither is available to us, and that turns out to be a feature rather than
// a concession. The rules explicitly put "projects that need a running
// third-party service" out of scope, and an auditor that phones a registry to
// tell you your registry is dangerous has a credibility problem. So the
// reference data ships inside the binary as `&[&str]` constants: names of
// widely-installed packages (the squat targets), and names of packages whose
// entire implementation is a few lines (the ones that should never have been
// packages).
//
// This is data I typed, not code I imported — the distinction the rules draw
// under "No Vendoring to Fake It". It is also, honestly, the part most likely
// to go stale, which is why `--corpus <file>` lets you supply your own list
// and why the report says how many names it compared against.
// ===========================================================================

mod corpus {
    /// Widely-installed npm packages: the names attackers register lookalikes
    /// of. Ordering is irrelevant; membership is what matters.
    pub const NPM_POPULAR: &[&str] = &[
        "lodash", "react", "react-dom", "express", "axios", "chalk", "debug", "commander",
        "moment", "dayjs", "uuid", "async", "request", "webpack", "babel-core", "typescript",
        "jest", "mocha", "chai", "eslint", "prettier", "rimraf", "glob", "minimist", "yargs",
        "semver", "colors", "cross-env", "dotenv", "body-parser", "cors", "helmet", "morgan",
        "mongoose", "mysql", "mysql2", "pg", "redis", "socket.io", "ws", "node-fetch",
        "cheerio", "puppeteer", "playwright", "nodemon", "concurrently", "husky", "vue",
        "angular", "svelte", "next", "nuxt", "vite", "rollup", "esbuild", "parcel", "gulp",
        "grunt", "browserify", "postcss", "autoprefixer", "tailwindcss", "sass", "less",
        "styled-components", "emotion", "redux", "mobx", "rxjs", "immer", "zustand",
        "graphql", "apollo-client", "prisma", "sequelize", "typeorm", "knex", "bcrypt",
        "bcryptjs", "jsonwebtoken", "passport", "multer", "sharp", "jimp", "canvas",
        "pdfkit", "archiver", "tar", "zip", "unzipper", "node-sass", "core-js",
        "regenerator-runtime", "tslib", "rxjs-compat", "zone.js", "classnames", "clsx",
        "prop-types", "react-router", "react-router-dom", "react-redux", "formik",
        "react-hook-form", "yup", "joi", "zod", "ajv", "validator", "qs", "query-string",
        "url-parse", "path-to-regexp", "cookie", "cookie-parser", "express-session",
        "connect-redis", "winston", "pino", "bunyan", "log4js", "signale", "ora", "inquirer",
        "prompts", "enquirer", "figlet", "boxen", "cli-table3", "columnify", "strip-ansi",
        "ansi-styles", "ansi-regex", "supports-color", "color-convert", "color-name",
        "has-flag", "escape-string-regexp", "string-width", "wrap-ansi", "slice-ansi",
        "cliui", "camelcase", "decamelize", "kebab-case", "snake-case", "dedent",
        "readable-stream", "through2", "split2", "pump", "pumpify", "duplexify", "end-of-stream",
        "once", "inherits", "util-deprecate", "safe-buffer", "buffer", "process", "events",
        "stream-browserify", "crypto-browserify", "path-browserify", "os-browserify",
        "browserify-zlib", "assert", "timers-browserify", "tty-browserify", "vm-browserify",
        "node-gyp", "node-pre-gyp", "prebuild-install", "nan", "bindings", "napi-build-utils",
        "fs-extra", "graceful-fs", "mkdirp", "del", "cpy", "globby", "fast-glob", "chokidar",
        "watchpack", "micromatch", "picomatch", "minimatch", "braces", "fill-range",
        "to-regex-range", "is-number", "is-glob", "is-extglob", "normalize-path",
        "anymatch", "binary-extensions", "is-binary-path", "readdirp", "fsevents",
        "@types/node", "@types/react", "@types/express", "@babel/core", "@babel/preset-env",
        "@babel/runtime", "@babel/parser", "@babel/traverse", "@babel/types",
        "@typescript-eslint/parser", "@typescript-eslint/eslint-plugin", "eslint-config-prettier",
        "eslint-plugin-import", "eslint-plugin-react", "eslint-plugin-jsx-a11y",
        "webpack-cli", "webpack-dev-server", "html-webpack-plugin", "mini-css-extract-plugin",
        "css-loader", "style-loader", "babel-loader", "ts-loader", "file-loader", "url-loader",
        "terser", "terser-webpack-plugin", "uglify-js", "acorn", "espree", "esprima",
        "estraverse", "escodegen", "esutils", "source-map", "source-map-support",
        "convert-source-map", "magic-string", "sucrase", "swc", "@swc/core", "nanoid",
        "shortid", "cuid", "bson", "mongodb", "ioredis", "amqplib", "kafkajs", "bull",
        "agenda", "node-cron", "cron", "luxon", "date-fns", "ms", "pretty-ms", "humanize-duration",
        // The transitive substrate. These are not packages people typically
        // target with squats, but they appear in almost every tree, and a
        // near-miss check that does not know them reports them as suspicious
        // of each other. Their absence was a gap in the data, not a threshold
        // that needed loosening.
        "safer-buffer", "color", "color-string", "colorspace", "depd", "etag", "exit",
        "bser", "fb-watchman", "destroy", "encodeurl", "escape-html", "finalhandler",
        "fresh", "merge-descriptors", "methods", "on-finished", "parseurl", "range-parser",
        "send", "serve-static", "setprototypeof", "statuses", "toidentifier", "type-is",
        "unpipe", "utils-merge", "vary", "content-disposition", "content-type",
        "raw-body", "http-errors", "iconv-lite", "media-typer", "mime-db", "mime-types",
        "negotiator", "accepts", "array-flatten", "bytes", "call-bind", "get-intrinsic",
        "has-symbols", "has-property-descriptors", "define-data-property", "gopd",
        "object-inspect", "side-channel", "function-bind", "hasown", "es-errors",
        "es-define-property", "set-function-length", "math-intrinsics", "dunder-proto",
        "js-tokens", "loose-envify", "scheduler", "react-is", "csstype", "nanoid",
        "picocolors", "postcss-value-parser", "resolve-from", "path-parse", "resolve",
        "supports-preserve-symlinks-flag", "is-core-module", "yallist", "lru-cache",
        "brace-expansion", "balanced-match", "concat-map", "wrappy", "signal-exit",
        "shebang-command", "shebang-regex", "path-key", "npm-run-path", "onetime",
        "mimic-fn", "human-signals", "is-stream", "get-stream", "merge-stream",
        "strip-final-newline", "execa", "cross-spawn", "which", "isexe", "node-int64",
        "walker", "makeerror", "tmpl", "leven", "sisteransi", "ci-info", "detect-newline",
        "emittery", "jest-util", "jest-worker", "pretty-format", "diff-sequences",
        "natural-compare", "stack-utils", "type-detect", "type-fest", "callsites",
        "parent-module", "import-fresh", "argparse", "js-yaml", "json5", "jsesc",
        "gensync", "globals", "chownr", "minipass", "fs-minipass", "encoding",
        "whatwg-url", "webidl-conversions", "tr46", "punycode", "psl", "tough-cookie",
        "form-data", "asynckit", "combined-stream", "delayed-stream", "follow-redirects",
        "proxy-from-env", "mkdirp-classic", "napi-build-utils", "simple-get",
        "simple-concat", "decompress-response", "mimic-response", "expand-template",
        "github-from-package", "tunnel-agent", "aproba", "are-we-there-yet", "gauge",
        "npmlog", "console-control-strings", "delegates", "wide-align", "set-blocking",
        "sprintf-js", "esprima", "esquery", "esrecurse", "eslint-scope", "eslint-visitor-keys",
        "levn", "prelude-ls", "type-check", "optionator", "fast-levenshtein",
        "deep-is", "word-wrap", "flat-cache", "flatted", "keyv", "json-buffer",
        "imurmurhash", "text-table", "doctrine", "ignore", "is-path-inside",
        "locate-path", "p-locate", "p-limit", "p-try", "path-exists", "find-up",
        "pkg-dir", "yocto-queue", "clean-stack", "indent-string", "aggregate-error",
        "triple-beam", "logform", "winston-transport", "one-time", "stack-trace",
        "call-bound", "side-channel-map", "side-channel-list", "side-channel-weakmap",
        "fecha", "safe-stable-stringify", "enabled", "kuler", "async-limiter",
    ];

    /// Widely-installed PyPI projects, in PEP 503 normalised form.
    pub const PYPI_POPULAR: &[&str] = &[
        "requests", "urllib3", "certifi", "charset-normalizer", "idna", "numpy", "pandas",
        "scipy", "matplotlib", "seaborn", "scikit-learn", "tensorflow", "torch", "torchvision",
        "keras", "transformers", "datasets", "tokenizers", "huggingface-hub", "flask",
        "django", "fastapi", "uvicorn", "gunicorn", "starlette", "pydantic", "sqlalchemy",
        "alembic", "psycopg2", "psycopg2-binary", "pymysql", "redis", "celery", "kombu",
        "boto3", "botocore", "s3transfer", "awscli", "google-cloud-storage", "azure-storage-blob",
        "click", "typer", "rich", "colorama", "tqdm", "pyyaml", "toml", "tomli", "jinja2",
        "markupsafe", "werkzeug", "itsdangerous", "blinker", "six", "python-dateutil",
        "pytz", "tzdata", "setuptools", "wheel", "pip", "packaging", "attrs", "cattrs",
        "pytest", "pytest-cov", "pytest-asyncio", "tox", "nox", "coverage", "mock",
        "hypothesis", "faker", "factory-boy", "black", "isort", "flake8", "pylint", "mypy",
        "ruff", "bandit", "pre-commit", "cryptography", "pyopenssl", "pyjwt", "passlib",
        "bcrypt", "argon2-cffi", "cffi", "pycparser", "pillow", "opencv-python",
        "beautifulsoup4", "lxml", "html5lib", "soupsieve", "scrapy", "selenium", "httpx",
        "aiohttp", "anyio", "sniffio", "h11", "httpcore", "websockets", "protobuf",
        "grpcio", "google-api-python-client", "openai", "anthropic", "langchain",
        "llama-index", "chromadb", "faiss-cpu", "sentence-transformers", "nltk", "spacy",
        "gensim", "statsmodels", "xgboost", "lightgbm", "catboost", "shap", "plotly",
        "dash", "streamlit", "gradio", "jupyter", "notebook", "ipython", "ipykernel",
        "jupyterlab", "nbconvert", "nbformat", "traitlets", "pygments", "docutils",
        "sphinx", "mkdocs", "python-dotenv", "environs", "marshmallow", "cerberus",
        "jsonschema", "orjson", "ujson", "msgpack", "pyarrow", "polars", "duckdb",
        "openpyxl", "xlrd", "xlsxwriter", "python-docx", "pypdf", "reportlab", "paramiko",
        "fabric", "ansible", "docker", "kubernetes", "psutil", "watchdog", "schedule",
        "apscheduler", "structlog", "loguru", "sentry-sdk", "prometheus-client",
    ];

    /// Widely-installed crates.
    pub const CRATES_POPULAR: &[&str] = &[
        "serde", "serde_json", "serde_derive", "syn", "quote", "proc-macro2", "libc",
        "rand", "regex", "lazy_static", "once_cell", "itertools", "chrono", "time",
        "clap", "structopt", "anyhow", "thiserror", "log", "env_logger", "tracing",
        "tracing-subscriber", "tokio", "async-trait", "futures", "futures-util", "hyper",
        "reqwest", "axum", "actix-web", "warp", "rocket", "tower", "tower-http", "tonic",
        "prost", "sqlx", "diesel", "sea-orm", "rusqlite", "redis", "mongodb", "uuid",
        "bytes", "bitflags", "cfg-if", "num-traits", "num_cpus", "parking_lot", "crossbeam",
        "crossbeam-channel", "rayon", "dashmap", "indexmap", "smallvec", "arrayvec",
        "hashbrown", "ahash", "fxhash", "toml", "toml_edit", "ron", "yaml-rust", "csv",
        "base64", "hex", "sha2", "sha1", "md5", "digest", "hmac", "ring", "rustls",
        "native-tls", "openssl", "flate2", "zstd", "lz4", "tar", "zip", "walkdir",
        "glob", "tempfile", "dirs", "which", "shellexpand", "colored", "termcolor",
        "console", "indicatif", "dialoguer", "crossterm", "ratatui", "tui", "strsim",
        "unicode-width", "unicode-segmentation", "url", "percent-encoding", "idna",
        "mime", "http", "http-body", "httparse", "socket2", "mio", "polling", "nix",
        "winapi", "windows-sys", "cc", "pkg-config", "bindgen", "cbindgen", "criterion",
        "proptest", "quickcheck", "insta", "mockall", "wiremock", "itoa", "ryu", "memchr",
        "aho-corasick", "regex-syntax", "either", "pin-project", "pin-project-lite",
        "slab", "scopeguard", "static_assertions", "paste", "derive_more", "strum",
        "num-derive", "enum-iterator", "bincode", "postcard", "rmp-serde", "ciborium",
    ];

    /// Packages whose whole job is now a standard-library call, and the call
    /// that replaces them. Roughly 16.8% of npm is this shape; these are the
    /// ones you are most likely to actually find in a lockfile.
    ///
    /// Membership rule, applied strictly: the replacement has to be something
    /// a competent developer would write inline without thinking about it.
    /// `core-js` and `es6-promise` were in an earlier version of this list and
    /// have been removed — modern runtimes do make them unnecessary, but they
    /// are large, careful libraries, and calling a 150,000-line polyfill suite
    /// a one-liner is the kind of overclaim that makes a whole report easy to
    /// dismiss. A rule is only worth as much as its least defensible entry.
    pub const TRIVIAL: &[(&str, &str)] = &[
        ("left-pad", "String::repeat + concat, or `format!(\"{:>width$}\")`"),
        ("is-even", "n % 2 == 0"),
        ("is-odd", "n % 2 != 0"),
        ("is-number", "matches!(v, Value::Num(..)) / typeof x === 'number'"),
        ("is-array", "Array.isArray, which is already a builtin"),
        ("is-string", "typeof x === 'string'"),
        ("is-object", "typeof x === 'object' && x !== null"),
        ("is-nan", "Number.isNaN, a builtin since ES2015"),
        ("is-negative", "n < 0"),
        ("is-positive", "n > 0"),
        ("is-plain-object", "Object.getPrototypeOf(x) === Object.prototype"),
        ("is-promise", "x instanceof Promise"),
        ("is-function", "typeof x === 'function'"),
        ("is-buffer", "Buffer.isBuffer, a builtin"),
        ("is-windows", "process.platform === 'win32' / cfg!(windows)"),
        ("is-wsl", "read /proc/version once"),
        ("is-docker", "existsSync('/.dockerenv')"),
        ("has-flag", "argv.includes('--flag')"),
        ("array-flatten", "Array.prototype.flat, a builtin since ES2019"),
        ("array-uniq", "[...new Set(a)] / BTreeSet"),
        ("array-union", "[...new Set([...a, ...b])]"),
        ("object-assign", "Object.assign, a builtin since ES2015"),
        ("object-keys", "Object.keys, a builtin"),
        ("string-trim", "String.prototype.trim, a builtin"),
        ("pad-left", "String.prototype.padStart, a builtin since ES2017"),
        ("pad-right", "String.prototype.padEnd, a builtin since ES2017"),
        ("repeat-string", "String.prototype.repeat, a builtin"),
        ("escape-string-regexp", "one replace() with a character class"),
        ("kind-of", "typeof plus a couple of instanceof checks"),
        ("to-array", "Array.from, a builtin"),
        ("defined", "x !== undefined"),
        ("isarray", "Array.isArray, a builtin"),
        ("number-is-nan", "Number.isNaN, a builtin"),
        ("index-of", "Array.prototype.indexOf, a builtin"),
        ("inherits", "class X extends Y"),
        ("util-deprecate", "a console.warn behind a flag"),
        ("path-is-absolute", "path.isAbsolute, a builtin"),
        ("fs-exists", "fs.existsSync / Path::exists"),
        ("mkdirp", "fs.mkdirSync(p, {recursive:true}) / create_dir_all"),
        ("rimraf", "fs.rmSync(p, {recursive:true}) / remove_dir_all"),
        ("os-tmpdir", "os.tmpdir, a builtin / std::env::temp_dir"),
        ("user-home", "os.homedir, a builtin"),
        ("widest-line", "one max() over split('\\n')"),
        ("word-wrap", "a loop over split(' ') with a running width counter"),
        ("clone-deep", "structuredClone, a builtin"),
        ("deep-equal", "a recursive comparison, or assert.deepStrictEqual"),
        ("lodash.isequal", "the same, from the standard assert module"),
        ("lodash.get", "optional chaining: a?.b?.c"),
        ("lodash.merge", "structuredClone plus a recursive assign"),
        ("lodash.debounce", "a setTimeout and a cleared handle"),
    ];

    /// npm lifecycle scripts that execute during `npm install`, before any
    /// human has looked at the code. This is the mechanism nearly every
    /// registry worm in the incident log used to gain execution.
    pub const INSTALL_SCRIPT_KEYS: &[&str] =
        &["preinstall", "install", "postinstall", "preprepare", "prepare", "prepublish"];

    pub fn popular_for(eco: crate::Ecosystem) -> &'static [&'static str] {
        match eco {
            crate::Ecosystem::Npm => NPM_POPULAR,
            crate::Ecosystem::PyPI => PYPI_POPULAR,
            crate::Ecosystem::Crates => CRATES_POPULAR,
        }
    }
}

// ===========================================================================
// 6. graph — the package graph
// ===========================================================================
//
// Everything above this point turns bytes into structure. This is where the
// structure becomes a graph you can ask questions of: how deep is this, who
// pulled it in, how much of the tree did anyone actually choose.
//
// The interesting part is npm resolution. A package-lock.json v2/v3 is a flat
// map keyed by install path — `node_modules/a`, `node_modules/a/node_modules/b`
// — and an entry's `dependencies` field gives names, not paths. Turning a name
// into an edge means reproducing Node's own lookup: from the depending
// package's directory, check `<dir>/node_modules/<name>`, then walk up one
// directory at a time to the root. Get this wrong and you either lose edges
// (undercounting the tree) or fuse two different versions of the same package
// into one node (which would make the blame paths lie).
// ===========================================================================

#[derive(Clone, Copy, PartialEq, Eq, Debug, Hash)]
pub enum Ecosystem {
    Npm,
    PyPI,
    Crates,
}

impl Ecosystem {
    pub fn label(&self) -> &'static str {
        match self {
            Ecosystem::Npm => "npm",
            Ecosystem::PyPI => "PyPI",
            Ecosystem::Crates => "crates.io",
        }
    }
    pub fn manifest_hint(&self) -> &'static str {
        match self {
            Ecosystem::Npm => "package-lock.json",
            Ecosystem::PyPI => "requirements.txt",
            Ecosystem::Crates => "Cargo.lock",
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct Pkg {
    pub name: String,
    pub version: String,
    /// npm install path, or the package name elsewhere. Identity, not label:
    /// two entries can share a name and differ here.
    pub location: String,
    pub resolved: Option<String>,
    pub integrity: Option<String>,
    pub install_scripts: Vec<String>,
    pub dev: bool,
    pub optional: bool,
    /// Names this package depends on, before resolution.
    pub wants: Vec<String>,
    /// Indices this package depends on, after resolution.
    pub edges: Vec<usize>,
    /// Distance from the project root. 1 = you chose it.
    pub depth: usize,
    /// A `link: true` entry: a workspace symlink, not a downloaded artifact.
    pub link: bool,
    /// Requirements-file specifics.
    pub spec: String,
    pub direct_url: Option<String>,
}

pub struct Graph {
    pub eco: Ecosystem,
    pub pkgs: Vec<Pkg>,
    /// Indices of packages the project asked for by name.
    pub roots: Vec<usize>,
    pub lock_version: Option<u64>,
    pub source: PathBuf,
    /// Non-fatal complaints raised while reading the file.
    pub warnings: Vec<String>,
    /// True when the format carries no transitive information at all
    /// (requirements.txt), so depth-based rules must stay quiet.
    pub flat: bool,
}

impl Graph {
    pub fn total(&self) -> usize {
        self.pkgs.len()
    }

    /// Packages nobody chose: reachable, but not a direct dependency.
    pub fn transitive_count(&self) -> usize {
        self.pkgs.iter().filter(|p| !p.link).count().saturating_sub(self.roots.len())
    }

    pub fn max_depth(&self) -> usize {
        self.pkgs.iter().map(|p| p.depth).max().unwrap_or(0)
    }

    /// Assign each package its shortest distance from a root, and record the
    /// predecessor so we can reconstruct a blame path later.
    pub fn compute_depths(&mut self) -> Vec<Option<usize>> {
        let n = self.pkgs.len();
        let mut parent: Vec<Option<usize>> = vec![None; n];
        let mut seen = vec![false; n];
        let mut q = VecDeque::new();

        for &r in &self.roots {
            if !seen[r] {
                seen[r] = true;
                self.pkgs[r].depth = 1;
                q.push_back(r);
            }
        }
        while let Some(i) = q.pop_front() {
            let d = self.pkgs[i].depth;
            let edges = self.pkgs[i].edges.clone();
            for e in edges {
                if !seen[e] {
                    seen[e] = true;
                    self.pkgs[e].depth = d + 1;
                    parent[e] = Some(i);
                    q.push_back(e);
                }
            }
        }
        // Anything unreachable from a root is still in the lockfile and still
        // gets installed; mark it rather than leaving depth 0, which would
        // read as "this is a root".
        for i in 0..n {
            if !seen[i] && !self.roots.contains(&i) {
                self.pkgs[i].depth = 0;
            }
        }
        parent
    }

    /// "Why is this here?" — the chain from a direct dependency down to `idx`.
    pub fn blame(&self, parent: &[Option<usize>], idx: usize) -> Vec<String> {
        let mut chain = Vec::new();
        let mut cur = Some(idx);
        let mut guard = 0;
        while let Some(i) = cur {
            chain.push(format!("{}@{}", self.pkgs[i].name, self.pkgs[i].version));
            cur = parent[i];
            guard += 1;
            if guard > 64 {
                chain.push("…".into());
                break;
            }
        }
        chain.reverse();
        chain
    }

    /// Packages appearing at more than one version. Duplicate versions are
    /// where "we patched that CVE" quietly stops being true.
    pub fn duplicates(&self) -> BTreeMap<String, BTreeSet<String>> {
        let mut m: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        for p in &self.pkgs {
            if p.link {
                continue;
            }
            m.entry(p.name.clone()).or_default().insert(p.version.clone());
        }
        m.retain(|_, v| v.len() > 1);
        m
    }

    /// Cycle detection over the resolved edges, iterative so that a pathological
    /// lockfile cannot exhaust the stack.
    pub fn cycles(&self) -> Vec<Vec<usize>> {
        let n = self.pkgs.len();
        let mut color = vec![0u8; n]; // 0 unvisited, 1 on stack, 2 done
        let mut out = Vec::new();
        let mut stack: Vec<(usize, usize)> = Vec::new();
        let mut path: Vec<usize> = Vec::new();

        for start in 0..n {
            if color[start] != 0 {
                continue;
            }
            stack.push((start, 0));
            color[start] = 1;
            path.push(start);
            while let Some(&mut (node, ref mut ei)) = stack.last_mut() {
                if *ei < self.pkgs[node].edges.len() {
                    let next = self.pkgs[node].edges[*ei];
                    *ei += 1;
                    match color[next] {
                        0 => {
                            color[next] = 1;
                            path.push(next);
                            stack.push((next, 0));
                        }
                        1 => {
                            if let Some(pos) = path.iter().position(|&x| x == next) {
                                let mut c: Vec<usize> = path[pos..].to_vec();
                                c.push(next);
                                if out.len() < 32 {
                                    out.push(c);
                                }
                            }
                        }
                        _ => {}
                    }
                } else {
                    color[node] = 2;
                    path.pop();
                    stack.pop();
                }
            }
        }
        out
    }
}

// ---------------------------------------------------------------------------
// npm: package-lock.json, v1 through v3
// ---------------------------------------------------------------------------

fn load_npm(v: &json::Value, path: &Path) -> Result<Graph, String> {
    let lock_version = v.get("lockfileVersion").and_then(|x| x.as_u64());
    let mut g = Graph {
        eco: Ecosystem::Npm,
        pkgs: Vec::new(),
        roots: Vec::new(),
        lock_version,
        source: path.to_path_buf(),
        warnings: Vec::new(),
        flat: false,
    };

    if let Some(packages) = v.get("packages").and_then(|p| p.as_obj()) {
        // ---- v2 / v3: flat map keyed by install path -----------------------
        let mut index: HashMap<String, usize> = HashMap::new();
        let mut root_wants: Vec<String> = Vec::new();

        for (loc, entry) in packages {
            if loc.is_empty() {
                // The "" entry describes the project itself. Its dependency
                // names are the only things the human actually chose.
                for field in ["dependencies", "devDependencies", "optionalDependencies"] {
                    if let Some(deps) = entry.get(field).and_then(|d| d.as_obj()) {
                        root_wants.extend(deps.keys().cloned());
                    }
                }
                continue;
            }
            let name = entry
                .get("name")
                .and_then(|n| n.as_str())
                .map(str::to_string)
                .unwrap_or_else(|| name_from_location(loc));
            let version = entry
                .get("version")
                .and_then(|x| x.as_str())
                .unwrap_or("")
                .to_string();

            let mut wants = Vec::new();
            for field in ["dependencies", "optionalDependencies", "peerDependencies"] {
                if let Some(d) = entry.get(field).and_then(|d| d.as_obj()) {
                    wants.extend(d.keys().cloned());
                }
            }

            // npm records install scripts two ways depending on the version:
            // a boolean summary, or the actual scripts block.
            let mut install_scripts = Vec::new();
            if entry.get("hasInstallScript").and_then(|b| b.as_bool()) == Some(true) {
                install_scripts.push("hasInstallScript".to_string());
            }
            if let Some(scripts) = entry.get("scripts").and_then(|s| s.as_obj()) {
                for k in scripts.keys() {
                    if corpus::INSTALL_SCRIPT_KEYS.contains(&k.as_str()) {
                        install_scripts.push(k.clone());
                    }
                }
            }

            let idx = g.pkgs.len();
            index.insert(loc.clone(), idx);
            g.pkgs.push(Pkg {
                name,
                version,
                location: loc.clone(),
                resolved: entry.get("resolved").and_then(|x| x.as_str()).map(str::to_string),
                integrity: entry.get("integrity").and_then(|x| x.as_str()).map(str::to_string),
                install_scripts,
                dev: entry.get("dev").and_then(|b| b.as_bool()).unwrap_or(false),
                optional: entry.get("optional").and_then(|b| b.as_bool()).unwrap_or(false),
                link: entry.get("link").and_then(|b| b.as_bool()).unwrap_or(false),
                wants,
                ..Default::default()
            });
        }

        // Resolve every edge using Node's directory walk.
        for i in 0..g.pkgs.len() {
            let from = g.pkgs[i].location.clone();
            let wants = g.pkgs[i].wants.clone();
            let mut edges = Vec::new();
            for w in &wants {
                if let Some(&t) = resolve_npm(&index, &from, w) {
                    if t != i {
                        edges.push(t);
                    }
                }
            }
            edges.sort_unstable();
            edges.dedup();
            g.pkgs[i].edges = edges;
        }

        // Direct dependencies resolve from the project root.
        for w in &root_wants {
            if let Some(&t) = resolve_npm(&index, "", w) {
                g.roots.push(t);
            }
        }
        g.roots.sort_unstable();
        g.roots.dedup();

        if g.roots.is_empty() && !g.pkgs.is_empty() {
            g.warnings.push(
                "the root entry lists no dependencies, so every package is reported as \
                 transitive; depth-based findings may be misleading"
                    .into(),
            );
        }
    } else if let Some(deps) = v.get("dependencies").and_then(|d| d.as_obj()) {
        // ---- v1: recursively nested "dependencies" -------------------------
        g.warnings.push(
            "lockfileVersion 1 detected: v1 records requires-by-name without install \
             paths, so duplicate nested versions are merged by name"
                .into(),
        );
        let mut index: HashMap<String, usize> = HashMap::new();
        collect_v1(deps, &mut g, &mut index);
        for i in 0..g.pkgs.len() {
            let wants = g.pkgs[i].wants.clone();
            let mut edges: Vec<usize> = wants
                .iter()
                .filter_map(|w| index.get(w).copied())
                .filter(|&t| t != i)
                .collect();
            edges.sort_unstable();
            edges.dedup();
            g.pkgs[i].edges = edges;
        }
        // Without a root manifest we cannot know which were chosen. Treat
        // top-level (non-nested) entries as direct and say so.
        g.roots = (0..g.pkgs.len()).filter(|&i| g.pkgs[i].depth == 1).collect();
        for p in g.pkgs.iter_mut() {
            p.depth = 0;
        }
    } else {
        return Err("not a package-lock.json: no `packages` or `dependencies` object".into());
    }

    Ok(g)
}

fn collect_v1(
    deps: &BTreeMap<String, json::Value>,
    g: &mut Graph,
    index: &mut HashMap<String, usize>,
) {
    for (name, entry) in deps {
        let idx = g.pkgs.len();
        let wants = entry
            .get("requires")
            .and_then(|r| r.as_obj())
            .map(|m| m.keys().cloned().collect())
            .unwrap_or_default();
        g.pkgs.push(Pkg {
            name: name.clone(),
            version: entry.get("version").and_then(|x| x.as_str()).unwrap_or("").to_string(),
            location: name.clone(),
            resolved: entry.get("resolved").and_then(|x| x.as_str()).map(str::to_string),
            integrity: entry.get("integrity").and_then(|x| x.as_str()).map(str::to_string),
            dev: entry.get("dev").and_then(|b| b.as_bool()).unwrap_or(false),
            optional: entry.get("optional").and_then(|b| b.as_bool()).unwrap_or(false),
            wants,
            depth: 1,
            ..Default::default()
        });
        index.entry(name.clone()).or_insert(idx);
        if let Some(nested) = entry.get("dependencies").and_then(|d| d.as_obj()) {
            collect_v1(nested, g, index);
        }
    }
}

fn name_from_location(loc: &str) -> String {
    // "node_modules/@scope/pkg/node_modules/other" -> "other"
    match loc.rfind("node_modules/") {
        Some(i) => loc[i + "node_modules/".len()..].to_string(),
        None => loc.to_string(),
    }
}

/// Node's resolution algorithm, which is the reason edges in a v2 lockfile are
/// not simply "look up the name". From `from_dir`, try
/// `<from_dir>/node_modules/<name>`, then strip one path segment and try again,
/// all the way up to `node_modules/<name>` at the root.
fn resolve_npm<'a>(
    index: &'a HashMap<String, usize>,
    from_dir: &str,
    name: &str,
) -> Option<&'a usize> {
    let mut base = from_dir.to_string();
    loop {
        let candidate = if base.is_empty() {
            format!("node_modules/{name}")
        } else {
            format!("{base}/node_modules/{name}")
        };
        if let Some(i) = index.get(&candidate) {
            return Some(i);
        }
        if base.is_empty() {
            return None;
        }
        match base.rfind('/') {
            Some(p) => base.truncate(p),
            None => base.clear(),
        }
        // Strip a trailing "node_modules" segment so the next iteration steps
        // out of the module directory rather than looping on it.
        if base.ends_with("node_modules") {
            match base.rfind('/') {
                Some(p) => base.truncate(p),
                None => base.clear(),
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Cargo.lock
// ---------------------------------------------------------------------------

fn load_cargo(doc: &toml::Document, path: &Path) -> Result<Graph, String> {
    let packages = doc
        .arrays
        .get("package")
        .ok_or("not a Cargo.lock: no [[package]] sections")?;

    let mut g = Graph {
        eco: Ecosystem::Crates,
        pkgs: Vec::new(),
        roots: Vec::new(),
        lock_version: doc.root.get("version").and_then(|v| match v {
            toml::Value::Int(i) => Some(*i as u64),
            _ => None,
        }),
        source: path.to_path_buf(),
        warnings: Vec::new(),
        flat: false,
    };

    // Two indexes, because Cargo writes dependency entries either as a bare
    // name (unambiguous) or as "name version" (when the graph holds more than
    // one version of that crate).
    let mut by_name_ver: HashMap<String, usize> = HashMap::new();
    let mut by_name: HashMap<String, Vec<usize>> = HashMap::new();
    let mut locals: Vec<usize> = Vec::new();

    for t in packages {
        let name = match t.get("name").and_then(|v| v.as_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };
        let version = t.get("version").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let source = t.get("source").and_then(|v| v.as_str()).map(str::to_string);
        let checksum = t.get("checksum").and_then(|v| v.as_str()).map(str::to_string);
        let wants: Vec<String> = t
            .get("dependencies")
            .and_then(|v| v.as_arr())
            .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
            .unwrap_or_default();

        let idx = g.pkgs.len();
        // No `source` key means a path/workspace member: your own code, not a
        // dependency. `link` already carries that meaning for npm workspace
        // symlinks, so reuse it and get the same exclusion from counts and
        // rules for free.
        let is_local = source.is_none();
        if is_local {
            locals.push(idx);
        }
        by_name_ver.insert(format!("{name} {version}"), idx);
        by_name.entry(name.clone()).or_default().push(idx);
        g.pkgs.push(Pkg {
            name,
            version,
            location: String::new(),
            resolved: source,
            integrity: checksum,
            wants,
            link: is_local,
            ..Default::default()
        });
    }

    for i in 0..g.pkgs.len() {
        let wants = g.pkgs[i].wants.clone();
        let mut edges = Vec::new();
        for w in &wants {
            let target = by_name_ver.get(w.as_str()).copied().or_else(|| {
                by_name.get(w.split(' ').next().unwrap_or(w)).and_then(|v| {
                    if v.len() == 1 {
                        Some(v[0])
                    } else {
                        None
                    }
                })
            });
            if let Some(t) = target {
                if t != i {
                    edges.push(t);
                }
            }
        }
        edges.sort_unstable();
        edges.dedup();
        g.pkgs[i].edges = edges;
    }

    // Direct dependencies are whatever the workspace members depend on. The
    // workspace members themselves are your code and are not "dependencies",
    // so they are excluded from every count.
    let local_set: HashSet<usize> = locals.iter().copied().collect();
    let mut roots: Vec<usize> = Vec::new();
    for &l in &locals {
        for &e in &g.pkgs[l].edges {
            if !local_set.contains(&e) {
                roots.push(e);
            }
        }
    }
    roots.sort_unstable();
    roots.dedup();
    g.roots = roots;

    if locals.is_empty() {
        g.warnings.push(
            "no workspace members found (every [[package]] has a `source`), so direct \
             dependencies could not be distinguished from transitive ones"
                .into(),
        );
    }
    Ok(g)
}

// ---------------------------------------------------------------------------
// requirements.txt
// ---------------------------------------------------------------------------

fn load_requirements(file: &pep508::File, path: &Path) -> Graph {
    let mut g = Graph {
        eco: Ecosystem::PyPI,
        pkgs: Vec::new(),
        roots: Vec::new(),
        lock_version: None,
        source: path.to_path_buf(),
        warnings: Vec::new(),
        flat: true,
    };
    for r in &file.requirements {
        let idx = g.pkgs.len();
        g.pkgs.push(Pkg {
            name: r.name.clone(),
            version: if r.is_pinned() {
                r.spec.trim_start_matches('=').trim().to_string()
            } else {
                String::new()
            },
            location: r.name.clone(),
            resolved: r.url.clone(),
            integrity: r.hashes.first().cloned(),
            spec: r.spec.clone(),
            direct_url: r.url.clone(),
            depth: 1,
            ..Default::default()
        });
        g.roots.push(idx);
    }
    if !file.includes.is_empty() {
        g.warnings.push(format!(
            "{} `-r`/`-c` include(s) were not followed: {}",
            file.includes.len(),
            file.includes.join(", ")
        ));
    }
    g.warnings.push(
        "requirements.txt records no transitive information, so this audit covers only \
         what you declared — the installed tree is larger"
            .into(),
    );
    for u in &file.index_urls {
        g.warnings.push(format!("custom package index configured: {u}"));
    }
    g
}

// ===========================================================================
// 7. rules — what we can honestly say without a network
// ===========================================================================
//
// Every rule here answers a question the lockfile alone can answer. That is a
// real constraint and it is worth stating plainly rather than pretending
// otherwise: this tool cannot tell you a package was compromised yesterday.
// It has no CVE feed and no download counts. What it can tell you is the
// shape of your exposure — how much of the tree nobody chose, which names sit
// one keystroke away from something popular, which entries will execute code
// during `install`, and which arrived with no integrity hash to check.
//
// Those are the properties every incident in the last decade shared before it
// became an incident. `chalk` and `debug` were legitimate right up until they
// were not; what made the blast radius enormous was that 2.6 billion weekly
// downloads sat behind a maintainer's password. No scanner catches that on
// day zero. But "you have 1,247 packages, 1,198 of which nobody chose, and 31
// of them run scripts at install time" is a sentence you can act on today,
// and it is true whether or not anything has gone wrong yet.
// ===========================================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Severity {
    Info,
    Low,
    Medium,
    High,
    Critical,
}

impl Severity {
    pub fn label(&self) -> &'static str {
        match self {
            Severity::Critical => "CRITICAL",
            Severity::High => "HIGH",
            Severity::Medium => "MEDIUM",
            Severity::Low => "LOW",
            Severity::Info => "INFO",
        }
    }
    pub fn from_str(s: &str) -> Option<Severity> {
        match s.to_ascii_lowercase().as_str() {
            "critical" => Some(Severity::Critical),
            "high" => Some(Severity::High),
            "medium" | "med" => Some(Severity::Medium),
            "low" => Some(Severity::Low),
            "info" => Some(Severity::Info),
            _ => None,
        }
    }
}

#[derive(Debug, Clone)]
pub struct Finding {
    pub rule: &'static str,
    pub severity: Severity,
    pub package: String,
    pub version: String,
    pub title: String,
    pub detail: String,
    pub blame: Vec<String>,
}

pub struct Audit {
    pub findings: Vec<Finding>,
    pub total: usize,
    pub direct: usize,
    pub transitive: usize,
    pub max_depth: usize,
    pub install_scripts: usize,
    pub missing_integrity: usize,
    pub duplicates: BTreeMap<String, BTreeSet<String>>,
    pub cycles: usize,
    pub corpus_size: usize,
    pub warnings: Vec<String>,
    pub eco: Ecosystem,
    pub source: PathBuf,
    pub lock_version: Option<u64>,
}

impl Audit {
    pub fn worst(&self) -> Option<Severity> {
        self.findings.iter().map(|f| f.severity).max()
    }
    pub fn count(&self, s: Severity) -> usize {
        self.findings.iter().filter(|f| f.severity == s).count()
    }
}

pub struct RuleOptions {
    pub extra_corpus: Vec<String>,
    pub deep_threshold: usize,
    pub min_name_len: usize,
}

impl Default for RuleOptions {
    fn default() -> Self {
        RuleOptions {
            extra_corpus: Vec::new(),
            // Six levels down is where "I could review this" stops being true
            // for most people. Tunable, because monorepos differ.
            deep_threshold: 6,
            // Names shorter than this produce nothing but false positives:
            // `ms` is distance 2 from `ws`, `fs`, and half the registry.
            min_name_len: 4,
        }
    }
}

pub fn audit(g: &mut Graph, opts: &RuleOptions) -> Audit {
    let parent = g.compute_depths();

    // In-degree: how many packages depend on each one. The only popularity
    // signal obtainable without a network, and the thing that separates a
    // squat from a substrate package. See Rule 1.
    let mut indegree = vec![0usize; g.pkgs.len()];
    for p in &g.pkgs {
        for &e in &p.edges {
            indegree[e] += 1;
        }
    }

    let duplicates = g.duplicates();
    let cycles = g.cycles();

    let mut popular: Vec<String> = corpus::popular_for(g.eco).iter().map(|s| s.to_string()).collect();
    popular.extend(opts.extra_corpus.iter().cloned());
    let popular_set: HashSet<&str> = popular.iter().map(|s| s.as_str()).collect();
    // Precomputed skeletons, so the confusable check is a hash lookup rather
    // than another O(n*m) sweep.
    let mut skeletons: HashMap<String, &str> = HashMap::new();
    for p in &popular {
        skeletons.entry(dist::skeleton(p)).or_insert(p.as_str());
    }

    let mut findings: Vec<Finding> = Vec::new();
    let mut install_scripts = 0usize;
    let mut missing_integrity = 0usize;

    for i in 0..g.pkgs.len() {
        let p = &g.pkgs[i];
        if p.link {
            continue; // a workspace symlink is your own code
        }
        let blame = g.blame(&parent, i);
        let norm = match g.eco {
            Ecosystem::PyPI => pep508::normalize(&p.name),
            _ => p.name.clone(),
        };

        // -- Rule 1: name resembles a widely-installed package ---------------
        //
        // The 19.7% figure is what makes this rule matter now rather than in
        // 2016. When a model invents `python-dotnev` often enough, somebody
        // registers it, and the victim never made a typo at all.
        //
        // Precision matters more than recall here, and the first version of
        // this rule taught me why. Run against a real 665-package tree it
        // reported `etag` as a near-miss for `tar`, `depd` for `del`, and
        // `exit` for `next` — all true at edit distance 2, all worthless. A
        // rule that cries wolf on express's own dependencies is a rule people
        // turn off, and a disabled rule catches nothing.
        //
        // Three gates fixed it, in increasing order of interest:
        //
        //   (a) Distance has to be small RELATIVE to length. Two edits on a
        //       four-character name is half the string; two edits on
        //       `python-dotenv` is a typo. So d=1 needs >= 5 characters and
        //       d=2 needs >= 8.
        //
        //   (b) A name that many packages independently depend on is
        //       established, not squatted. In-degree is the one popularity
        //       signal available without a network, and it is a good one: a
        //       real squat is pulled in by one mistaken import, while
        //       `safer-buffer` is pulled in by half the registry. High
        //       in-degree demotes a finding to INFO rather than deleting it —
        //       the evidence is weaker, not absent.
        //
        //   (c) Compare like with like. `@jest/core` is not a near-miss for
        //       `@types/node` just because `core` and `node` are two edits
        //       apart.
        if !popular_set.contains(norm.as_str()) && norm.len() >= opts.min_name_len {
            let (scope, bare) = dist::split_scope(&norm);
            let mut best: Option<(usize, &str)> = None;

            for cand in &popular {
                let (cscope, cbare) = dist::split_scope(cand);
                // Only compare like with like: an unscoped name is not a near
                // miss for a scoped one, whatever the raw edit distance says.
                if scope.is_some() != cscope.is_some() {
                    continue;
                }
                if let (Some(a), Some(b)) = (scope, cscope) {
                    // Same scope, different package: that is just a sibling.
                    if a == b {
                        continue;
                    }
                }
                let len = bare.chars().count().min(cbare.chars().count());
                if let Some(d) = dist::bounded(bare, cbare, 2) {
                    let credible = match d {
                        1 => len >= 5,
                        2 => len >= 8,
                        _ => false,
                    };
                    if credible && best.map(|(bd, _)| d < bd).unwrap_or(true) {
                        best = Some((d, cand.as_str()));
                    }
                }
            }

            // Confusable-glyph check, which catches deliberate substitutions
            // that edit distance scores identically to an innocent one.
            let skel = dist::skeleton(&norm);
            let confusable = skeletons
                .get(&skel)
                .copied()
                .filter(|t| *t != norm.as_str());

            if let Some(target) = confusable {
                findings.push(Finding {
                    rule: "confusable-name",
                    severity: Severity::High,
                    package: p.name.clone(),
                    version: p.version.clone(),
                    title: format!("`{}` is visually confusable with `{}`", p.name, target),
                    detail: format!(
                        "After folding lookalike glyphs (0/o, 1/l, rn/m) and separators, both \
                         names reduce to `{skel}`. That is not a typo pattern — it is a \
                         deliberate one. If you meant `{target}`, this is not it.",
                    ),
                    blame: blame.clone(),
                });
            } else if let Some((d, target)) = best {
                let established = indegree[i] >= 3;
                let sev = if established {
                    Severity::Info
                } else if d == 1 {
                    Severity::High
                } else {
                    Severity::Medium
                };
                findings.push(Finding {
                    rule: "typosquat-candidate",
                    severity: sev,
                    package: p.name.clone(),
                    version: p.version.clone(),
                    title: format!(
                        "`{}` is {} edit{} from the widely-installed `{}`",
                        p.name,
                        d,
                        if d == 1 { "" } else { "s" },
                        target
                    ),
                    detail: format!(
                        "This is not proof of anything — plenty of legitimate packages sit \
                         near a popular name. It is a prompt to check that you, or the model \
                         that wrote the import, meant `{target}`. Attackers pre-register the \
                         names that get invented reliably.{}",
                        if established {
                            format!(
                                " Downgraded to INFO: {} other packages in this tree depend \
                                 on it independently, which is what an established package \
                                 looks like and not what a squat looks like.",
                                indegree[i]
                            )
                        } else {
                            String::new()
                        }
                    ),
                    blame: blame.clone(),
                });
            }
        }

        // -- Rule 2: executes code at install time ---------------------------
        if !p.install_scripts.is_empty() {
            install_scripts += 1;
            // A near-miss name that also runs a script is the actual attack
            // shape, not two independent observations. Escalate it.
            let squatty = findings.iter().any(|f| {
                f.package == p.name
                    && (f.rule == "typosquat-candidate" || f.rule == "confusable-name")
            });
            findings.push(Finding {
                rule: "install-script",
                severity: if squatty { Severity::Critical } else { Severity::Medium },
                package: p.name.clone(),
                version: p.version.clone(),
                title: format!("`{}` runs code during install", p.name),
                detail: format!(
                    "Lifecycle hooks present: {}. These execute on `install`, before anyone \
                     reads the code, with the permissions of whoever ran the command — \
                     including CI.{}",
                    p.install_scripts.join(", "),
                    if squatty {
                        " This package ALSO has a name resembling a popular one. That \
                         combination is the shape of a live attack, not a coincidence."
                    } else {
                        ""
                    }
                ),
                blame: blame.clone(),
            });
        }

        // -- Rule 3: no integrity hash --------------------------------------
        let wants_integrity = match g.eco {
            Ecosystem::Npm => p.resolved.is_some(),
            Ecosystem::Crates => p
                .resolved
                .as_deref()
                .map(|s| s.starts_with("registry+"))
                .unwrap_or(false),
            Ecosystem::PyPI => false,
        };
        if wants_integrity && p.integrity.is_none() {
            missing_integrity += 1;
            findings.push(Finding {
                rule: "no-integrity",
                severity: Severity::Medium,
                package: p.name.clone(),
                version: p.version.clone(),
                title: format!("`{}` has no integrity hash", p.name),
                detail: "The lockfile pins a version but records nothing to verify the \
                         downloaded bytes against. A republished artifact at the same \
                         version would install silently."
                    .into(),
                blame: blame.clone(),
            });
        }

        // -- Rule 4: came from somewhere other than the registry -------------
        if let Some(res) = &p.resolved {
            if let Some(kind) = off_registry(g.eco, res) {
                findings.push(Finding {
                    rule: "off-registry-source",
                    severity: Severity::High,
                    package: p.name.clone(),
                    version: p.version.clone(),
                    title: format!("`{}` resolves to {kind}, not the registry", p.name),
                    detail: format!(
                        "Source: {res}\nRegistry provenance, signing and yank/unpublish \
                         protections do not apply here. A mutable ref (a branch, a tag that \
                         can move) means the content can change without the lockfile changing."
                    ),
                    blame: blame.clone(),
                });
            }
        }

        // -- Rule 5: this did not need to be a package -----------------------
        if let Some((_, replacement)) =
            corpus::TRIVIAL.iter().find(|(n, _)| *n == norm.as_str())
        {
            findings.push(Finding {
                rule: "trivial-package",
                severity: Severity::Low,
                package: p.name.clone(),
                version: p.version.clone(),
                title: format!(
                    "`{}` is a standard-library call carried as a dependency",
                    p.name
                ),
                detail: format!(
                    "Standard-library equivalent: {replacement}\nAbout 16.8% of the npm \
                     registry is this shape. Each one is a maintainer account, a publish \
                     token and a release pipeline you are trusting to save a few lines of \
                     code."
                ),
                blame: blame.clone(),
            });
        }

        // -- Rule 6: declared without a version constraint -------------------
        if g.eco == Ecosystem::PyPI {
            if p.direct_url.is_some() {
                findings.push(Finding {
                    rule: "direct-url-requirement",
                    severity: Severity::High,
                    package: p.name.clone(),
                    version: p.version.clone(),
                    title: format!("`{}` installs from a direct URL", p.name),
                    detail: format!(
                        "Source: {}\nThis bypasses the index entirely. Whatever is at that \
                         URL at install time is what you get.",
                        p.direct_url.as_deref().unwrap_or("?")
                    ),
                    blame: blame.clone(),
                });
            } else if p.spec.trim().is_empty() {
                findings.push(Finding {
                    rule: "unpinned",
                    severity: Severity::Medium,
                    package: p.name.clone(),
                    version: p.version.clone(),
                    title: format!("`{}` is declared with no version constraint", p.name),
                    detail: "Two installs a week apart can produce different code. Whatever \
                             the maintainer publishes next is what lands in your build."
                        .into(),
                    blame: blame.clone(),
                });
            } else if !p.spec.contains("==") {
                findings.push(Finding {
                    rule: "unpinned-range",
                    severity: Severity::Low,
                    package: p.name.clone(),
                    version: p.version.clone(),
                    title: format!("`{}` allows a version range ({})", p.name, p.spec.trim()),
                    detail: "A range is a standing instruction to accept future code you \
                             have not seen. Pin it, or use a hash-locked file."
                        .into(),
                    blame: blame.clone(),
                });
            }
        }

        // -- Rule 7: buried deep in the tree ---------------------------------
        if !g.flat && p.depth >= opts.deep_threshold {
            findings.push(Finding {
                rule: "deep-transitive",
                severity: Severity::Info,
                package: p.name.clone(),
                version: p.version.clone(),
                title: format!("`{}` sits {} levels deep", p.name, p.depth),
                detail: "Nobody in your organisation chose this, reviewed it, or is \
                         watching its releases. It ships in your artifact all the same."
                    .into(),
                blame: blame.clone(),
            });
        }

        // -- Rule 8: present but unreachable ---------------------------------
        if !g.flat && p.depth == 0 && !g.roots.contains(&i) {
            findings.push(Finding {
                rule: "unreachable-entry",
                severity: Severity::Low,
                package: p.name.clone(),
                version: p.version.clone(),
                title: format!("`{}` is in the lockfile but unreachable from any root", p.name),
                detail: "Either a stale entry from a removed dependency, or an edge this \
                         reader failed to resolve. Both are worth a look: the first is \
                         installed for no reason, the second means a count below is low."
                    .into(),
                blame: vec![format!("{}@{}", p.name, p.version)],
            });
        }
    }

    // -- Whole-graph observations -------------------------------------------
    // One finding, not thirty-two. A large tree routinely carries dozens of
    // duplicated packages, and emitting one finding each buries everything
    // else on the screen — which is how a report stops being read at all.
    if !duplicates.is_empty() {
        let worst: Vec<String> = duplicates
            .iter()
            .map(|(n, v)| format!("{n} ({})", v.iter().cloned().collect::<Vec<_>>().join(", ")))
            .take(12)
            .collect();
        let extra = duplicates.len().saturating_sub(worst.len());
        findings.push(Finding {
            rule: "duplicate-versions",
            severity: Severity::Low,
            package: format!("{} packages", duplicates.len()),
            version: String::new(),
            title: format!(
                "{} packages are installed at more than one version",
                duplicates.len()
            ),
            detail: format!(
                "Patching one copy does not patch the others. This is how an advisory gets \
                 marked resolved while a vulnerable copy stays in the bundle.\n{}{}",
                worst.join(", "),
                if extra > 0 {
                    format!(" … and {extra} more")
                } else {
                    String::new()
                }
            ),
            blame: Vec::new(),
        });
    }

    for c in cycles.iter().take(5) {
        let names: Vec<String> = c
            .iter()
            .map(|&i| format!("{}@{}", g.pkgs[i].name, g.pkgs[i].version))
            .collect();
        findings.push(Finding {
            rule: "dependency-cycle",
            severity: Severity::Info,
            package: g.pkgs[c[0]].name.clone(),
            version: g.pkgs[c[0]].version.clone(),
            title: format!("dependency cycle across {} packages", c.len().saturating_sub(1)),
            detail: format!("Cycle: {}", names.join(" -> ")),
            blame: Vec::new(),
        });
    }

    // Sort by severity descending, then rule, then package, so output is
    // stable across runs — which matters because `--json` gets diffed in CI.
    findings.sort_by(|a, b| {
        b.severity
            .cmp(&a.severity)
            .then_with(|| a.rule.cmp(b.rule))
            .then_with(|| a.package.cmp(&b.package))
            .then_with(|| a.version.cmp(&b.version))
    });

    Audit {
        total: g.pkgs.iter().filter(|p| !p.link).count(),
        direct: g.roots.len(),
        transitive: g.transitive_count(),
        max_depth: g.max_depth(),
        install_scripts,
        missing_integrity,
        duplicates,
        cycles: cycles.len(),
        corpus_size: popular.len(),
        warnings: g.warnings.clone(),
        eco: g.eco,
        source: g.source.clone(),
        lock_version: g.lock_version,
        findings,
    }
}

/// Recognise a source that is not the ecosystem's default registry.
fn off_registry(eco: Ecosystem, resolved: &str) -> Option<&'static str> {
    let r = resolved.to_ascii_lowercase();
    match eco {
        Ecosystem::Npm => {
            if r.starts_with("git+") || r.starts_with("git:") || r.contains("github.com/") && r.ends_with(".git") {
                Some("a git repository")
            } else if r.starts_with("file:") {
                Some("a local path")
            } else if r.starts_with("http") && !r.contains("registry.npmjs.org") {
                Some("a non-default registry or tarball URL")
            } else {
                None
            }
        }
        Ecosystem::Crates => {
            if r.starts_with("git+") {
                Some("a git repository")
            } else if r.starts_with("registry+")
                && !r.contains("github.com/rust-lang/crates.io-index")
            {
                Some("an alternate registry")
            } else {
                None
            }
        }
        Ecosystem::PyPI => None,
    }
}

// ===========================================================================
// 8. render — terminal output
// ===========================================================================
//
// Would normally be: `colored` or `owo-colors` for styling, `comfy-table` or
// `tabled` for layout, `terminal_size` for width.
//
// ANSI SGR is a handful of escape sequences that have been stable since
// 1979. The part worth actually thinking about is not the codes, it is *when*
// to emit them: writing colour into a pipe corrupts every downstream grep,
// and `chalk` earning 319 million weekly downloads is mostly people paying a
// dependency to answer that question for them.
//
// The policy here, in order: an explicit --color/--no-color flag wins;
// otherwise NO_COLOR (any value, per the no-color.org convention) disables;
// otherwise colour only when stdout is a terminal, via std::io::IsTerminal.
// ===========================================================================

mod render {
    pub struct Style {
        pub on: bool,
    }

    impl Style {
        pub fn wrap(&self, code: &str, s: &str) -> String {
            if self.on {
                format!("\x1b[{code}m{s}\x1b[0m")
            } else {
                s.to_string()
            }
        }
        pub fn bold(&self, s: &str) -> String {
            self.wrap("1", s)
        }
        pub fn dim(&self, s: &str) -> String {
            self.wrap("2", s)
        }
        pub fn red(&self, s: &str) -> String {
            self.wrap("31;1", s)
        }
        pub fn yellow(&self, s: &str) -> String {
            self.wrap("33;1", s)
        }
        pub fn blue(&self, s: &str) -> String {
            self.wrap("34;1", s)
        }
        pub fn cyan(&self, s: &str) -> String {
            self.wrap("36", s)
        }
        pub fn green(&self, s: &str) -> String {
            self.wrap("32;1", s)
        }
        pub fn magenta(&self, s: &str) -> String {
            self.wrap("35;1", s)
        }
        pub fn sev(&self, s: crate::Severity) -> String {
            match s {
                crate::Severity::Critical => self.magenta(" CRITICAL "),
                crate::Severity::High => self.red("   HIGH   "),
                crate::Severity::Medium => self.yellow("  MEDIUM  "),
                crate::Severity::Low => self.blue("   LOW    "),
                crate::Severity::Info => self.dim("   INFO   "),
            }
        }
    }

    /// Wrap text to a width, indenting continuation lines. Written directly
    /// because `textwrap` is another crate and this is a while loop.
    pub fn wrap_text(s: &str, width: usize, indent: &str) -> String {
        let mut out = String::new();
        for (i, para) in s.split('\n').enumerate() {
            if i > 0 {
                out.push('\n');
                out.push_str(indent);
            }
            let mut col = 0usize;
            for (j, word) in para.split_whitespace().enumerate() {
                let w = word.chars().count();
                if j > 0 && col + 1 + w > width {
                    out.push('\n');
                    out.push_str(indent);
                    col = 0;
                } else if j > 0 {
                    out.push(' ');
                    col += 1;
                }
                out.push_str(word);
                col += w;
            }
        }
        out
    }

    /// A horizontal bar, for the "how much of this did you choose" figure.
    /// One glyph is worth more than the number next to it.
    pub fn bar(fraction: f64, width: usize) -> String {
        let filled = ((fraction.clamp(0.0, 1.0)) * width as f64).round() as usize;
        let mut s = String::with_capacity(width);
        for i in 0..width {
            s.push(if i < filled { '#' } else { '.' });
        }
        s
    }
}

// ===========================================================================
// 9. cli — argument parsing
// ===========================================================================
//
// Would normally be: `clap` (which, with derive, pulls clap_derive, syn,
// quote, proc-macro2, strsim, anstyle, anstream, colorchoice and more — a
// double-digit subtree to read a Vec<String>).
//
// std::env::args() gives us that Vec. What clap actually sells is the
// conventions: `--flag=value` and `--flag value` both working, `--` ending
// option parsing, clustered short flags, and a help text that stays in sync.
// Those are worth having, so they are implemented rather than skipped — about
// eighty lines, below.
// ===========================================================================

#[derive(Debug, Default)]
pub struct Args {
    pub command: String,
    pub positionals: Vec<String>,
    pub flags: HashSet<String>,
    pub values: HashMap<String, String>,
}

impl Args {
    pub fn has(&self, name: &str) -> bool {
        self.flags.contains(name)
    }
    pub fn value(&self, name: &str) -> Option<&str> {
        self.values.get(name).map(|s| s.as_str())
    }
}

const KNOWN_VALUE_FLAGS: &[&str] = &["fail-on", "corpus", "deep", "only", "top", "color"];

pub fn parse_args(argv: Vec<String>) -> Result<Args, String> {
    let mut a = Args::default();
    let mut it = argv.into_iter().peekable();
    let mut no_more_flags = false;

    while let Some(tok) = it.next() {
        if no_more_flags {
            a.positionals.push(tok);
            continue;
        }
        if tok == "--" {
            no_more_flags = true;
            continue;
        }
        if let Some(long) = tok.strip_prefix("--") {
            if let Some((k, v)) = long.split_once('=') {
                a.values.insert(k.to_string(), v.to_string());
                continue;
            }
            if KNOWN_VALUE_FLAGS.contains(&long) {
                let v = it
                    .next()
                    .ok_or_else(|| format!("--{long} expects a value"))?;
                a.values.insert(long.to_string(), v);
            } else {
                a.flags.insert(long.to_string());
            }
            continue;
        }
        if tok.len() > 1 && tok.starts_with('-') {
            // Clustered short flags: -qh is -q -h.
            for c in tok[1..].chars() {
                let name = match c {
                    'h' => "help",
                    'V' => "version",
                    'q' => "quiet",
                    'v' => "verbose",
                    'j' => "json",
                    other => return Err(format!("unknown flag -{other}")),
                };
                a.flags.insert(name.to_string());
            }
            continue;
        }
        if a.command.is_empty() && matches!(tok.as_str(), "audit" | "diff" | "why" | "help" | "version") {
            a.command = tok;
        } else {
            a.positionals.push(tok);
        }
    }
    if a.command.is_empty() {
        a.command = "audit".to_string();
    }
    Ok(a)
}

const HELP: &str = r#"stranger — offline supply-chain auditor for dependency lockfiles

USAGE
    stranger [audit] <lockfile>          audit a lockfile (default command)
    stranger diff <old> <new>            show what an install actually added
    stranger why <lockfile> <package>    show why a package is in the tree
    stranger help | version

SUPPORTED INPUTS
    package-lock.json    npm, lockfileVersion 1, 2 and 3
    Cargo.lock           cargo
    requirements.txt     pip (declared requirements only; see LIMITS in README)
    -                    read from stdin, with --as npm|cargo|pip

OPTIONS
    --json, -j           machine-readable report on stdout
    --fail-on <sev>      exit 1 at or above this severity
                         (critical|high|medium|low|info; default: high)
    --only <rule>        show findings from one rule only
    --top <n>            show at most n findings (default: all)
    --corpus <file>      add newline-separated package names to compare against
    --deep <n>           depth at which a package counts as deep (default: 6)
    --as <eco>           force the input format: npm, cargo or pip
    --no-blame           omit the "why is this here" chains
    --color <when>       always | never | auto (default: auto)
    --quiet, -q          findings only, no summary
    --verbose, -v        include INFO findings in the default view
    --help, -h           this text
    --version, -V        version

EXIT CODES
    0    no findings at or above the --fail-on threshold
    1    findings at or above the threshold
    2    the input could not be read or parsed

    Nothing here talks to the network. The lockfile is the entire input.
"#;

// ===========================================================================
// main
// ===========================================================================

fn main() -> ExitCode {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let args = match parse_args(argv) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("stranger: {e}");
            return ExitCode::from(2);
        }
    };

    if args.has("help") || args.command == "help" {
        print!("{HELP}");
        return ExitCode::SUCCESS;
    }
    if args.has("version") || args.command == "version" {
        println!("stranger {VERSION}");
        println!("dependencies: 0");
        return ExitCode::SUCCESS;
    }

    let style = render::Style {
        on: color_enabled(&args),
    };

    let result = match args.command.as_str() {
        "diff" => cmd_diff(&args, &style),
        "why" => cmd_why(&args, &style),
        _ => cmd_audit(&args, &style),
    };

    match result {
        Ok(code) => code,
        Err(e) => {
            eprintln!("{} {e}", style.red("error:"));
            ExitCode::from(2)
        }
    }
}

fn color_enabled(args: &Args) -> bool {
    match args.value("color") {
        Some("always") => return true,
        Some("never") => return false,
        _ => {}
    }
    if args.has("no-color") {
        return false;
    }
    if std::env::var_os("NO_COLOR").is_some() {
        return false;
    }
    std::io::stdout().is_terminal()
}

fn read_input(path: &str) -> Result<String, String> {
    if path == "-" {
        let mut s = String::new();
        std::io::stdin()
            .read_to_string(&mut s)
            .map_err(|e| format!("reading stdin: {e}"))?;
        return Ok(s);
    }
    std::fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))
}

/// Decide what kind of file this is. The filename is a hint, not the answer:
/// people rename lockfiles, and stdin has no name at all. So sniff content
/// when the name is not decisive.
fn detect(path: &str, src: &str, forced: Option<&str>) -> Result<Ecosystem, String> {
    if let Some(f) = forced {
        return match f {
            "npm" | "node" | "package-lock" => Ok(Ecosystem::Npm),
            "cargo" | "rust" | "crates" => Ok(Ecosystem::Crates),
            "pip" | "python" | "pypi" | "requirements" => Ok(Ecosystem::PyPI),
            other => Err(format!("unknown --as value `{other}`")),
        };
    }
    let base = Path::new(path)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    if base == "package-lock.json" || base == "npm-shrinkwrap.json" {
        return Ok(Ecosystem::Npm);
    }
    if base == "cargo.lock" {
        return Ok(Ecosystem::Crates);
    }
    if base.starts_with("requirements") && base.ends_with(".txt") {
        return Ok(Ecosystem::PyPI);
    }
    let head = src.trim_start();
    if head.starts_with('{') {
        return Ok(Ecosystem::Npm);
    }
    if head.contains("[[package]]") {
        return Ok(Ecosystem::Crates);
    }
    if !head.is_empty() {
        return Ok(Ecosystem::PyPI);
    }
    Err("could not determine the lockfile format; pass --as npm|cargo|pip".into())
}

fn build_graph(path: &str, forced: Option<&str>) -> Result<Graph, String> {
    let src = read_input(path)?;
    let eco = detect(path, &src, forced)?;
    let p = Path::new(path).to_path_buf();
    match eco {
        Ecosystem::Npm => {
            let v = json::parse(&src).map_err(|e| format!("{path}: {e}"))?;
            load_npm(&v, &p).map_err(|e| format!("{path}: {e}"))
        }
        Ecosystem::Crates => {
            let d = toml::parse(&src).map_err(|e| format!("{path}: {e}"))?;
            load_cargo(&d, &p).map_err(|e| format!("{path}: {e}"))
        }
        Ecosystem::PyPI => {
            let f = pep508::parse(&src);
            Ok(load_requirements(&f, &p))
        }
    }
}

fn rule_options(args: &Args) -> Result<RuleOptions, String> {
    let mut o = RuleOptions::default();
    if let Some(d) = args.value("deep") {
        o.deep_threshold = d.parse().map_err(|_| format!("--deep expects a number, got `{d}`"))?;
    }
    if let Some(f) = args.value("corpus") {
        let text = std::fs::read_to_string(f).map_err(|e| format!("--corpus {f}: {e}"))?;
        o.extra_corpus = text
            .lines()
            .map(|l| l.trim().to_string())
            .filter(|l| !l.is_empty() && !l.starts_with('#'))
            .collect();
    }
    Ok(o)
}

fn cmd_audit(args: &Args, st: &render::Style) -> Result<ExitCode, String> {
    let path = args
        .positionals
        .first()
        .cloned()
        .or_else(|| default_lockfile().map(|p| p.display().to_string()))
        .ok_or_else(|| {
            "no lockfile given, and none of package-lock.json, Cargo.lock or \
             requirements.txt was found here. Try `stranger help`."
                .to_string()
        })?;

    let mut g = build_graph(&path, args.value("as"))?;
    let opts = rule_options(args)?;
    let report = audit(&mut g, &opts);

    if args.has("json") {
        println!("{}", json::to_string(&report_json(&report)));
    } else {
        print_report(&report, args, st);
    }

    let threshold = args
        .value("fail-on")
        .map(|s| Severity::from_str(s).ok_or(format!("unknown severity `{s}`")))
        .transpose()?
        .unwrap_or(Severity::High);

    let over = report.findings.iter().any(|f| f.severity >= threshold);
    Ok(if over { ExitCode::from(1) } else { ExitCode::SUCCESS })
}

fn default_lockfile() -> Option<PathBuf> {
    for c in ["package-lock.json", "Cargo.lock", "requirements.txt"] {
        let p = PathBuf::from(c);
        if p.exists() {
            return Some(p);
        }
    }
    None
}

/// Thousands separators. Would normally be `num-format` or `thousands`; it is
/// a reverse chunk of three with a comma between chunks.
fn commas(n: usize) -> String {
    let s = n.to_string();
    let mut out = String::with_capacity(s.len() + s.len() / 3);
    let bytes = s.as_bytes();
    for (i, b) in bytes.iter().enumerate() {
        if i > 0 && (bytes.len() - i) % 3 == 0 {
            out.push(',');
        }
        out.push(*b as char);
    }
    out
}

/// Decide which findings are displayed, and account for every one that is not.
///
/// Returns `(shown, matched, below_verbosity, past_the_limit)`. Pulled out of
/// `print_report` so the accounting is testable on its own: the bug this
/// replaced was a display-layer contradiction (a "CLEAN" verdict printed under
/// a summary that counted install scripts), and a bug you cannot write a test
/// for is a bug that comes back.
fn select_findings<'a>(
    findings: &'a [Finding],
    only: Option<&str>,
    verbose: bool,
    top: usize,
) -> (Vec<&'a Finding>, usize, usize, usize) {
    let matching: Vec<&Finding> = findings
        .iter()
        .filter(|f| only.map(|o| f.rule == o).unwrap_or(true))
        .collect();
    let visible: Vec<&Finding> = matching
        .iter()
        .copied()
        .filter(|f| verbose || f.severity > Severity::Info)
        .collect();
    let shown: Vec<&Finding> = visible.iter().copied().take(top).collect();
    let below_verbosity = matching.len() - visible.len();
    let past_the_limit = visible.len() - shown.len();
    (shown, matching.len(), below_verbosity, past_the_limit)
}

fn print_report(r: &Audit, args: &Args, st: &render::Style) {
    let width = 78usize;
    let verbose = args.has("verbose");
    let quiet = args.has("quiet");
    let show_blame = !args.has("no-blame");
    let only = args.value("only");
    let top: usize = args.value("top").and_then(|s| s.parse().ok()).unwrap_or(usize::MAX);

    if !quiet {
        println!();
        println!(
            "  {} {}",
            st.bold("stranger"),
            st.dim(&format!(
                "{VERSION} · {} · {}{}",
                r.source.display(),
                r.eco.label(),
                match r.lock_version {
                    Some(v) => format!(" · lockfileVersion {v}"),
                    None => String::new(),
                }
            ))
        );
        println!();

        // The headline number. Everything else on this screen is detail.
        let frac = if r.total > 0 {
            r.transitive as f64 / r.total as f64
        } else {
            0.0
        };
        println!(
            "  {}  packages in the tree",
            st.bold(&format!("{:>9}", commas(r.total)))
        );
        println!(
            "  {}  you chose{}",
            st.green(&format!("{:>9}", commas(r.direct))),
            st.dim(if r.eco == Ecosystem::PyPI {
                "  (declared in this file)"
            } else {
                ""
            })
        );
        println!(
            "  {}  arrived with them",
            st.yellow(&format!("{:>9}", commas(r.transitive)))
        );
        println!();
        println!(
            "  {} {}",
            st.dim(&render::bar(frac, 40)),
            st.bold(&format!("{:.0}% of your tree is code nobody chose", frac * 100.0))
        );

        if !r.flat_note() {
            println!();
            let mut bits: Vec<String> = Vec::new();
            bits.push(format!("max depth {}", r.max_depth));
            if r.install_scripts > 0 {
                bits.push(format!("{} run install scripts", r.install_scripts));
            }
            if r.missing_integrity > 0 {
                bits.push(format!("{} without integrity", r.missing_integrity));
            }
            if !r.duplicates.is_empty() {
                bits.push(format!("{} duplicated", r.duplicates.len()));
            }
            if r.cycles > 0 {
                bits.push(format!("{} cycles", r.cycles));
            }
            println!("  {}", st.dim(&bits.join("  ·  ")));
        }

        for w in &r.warnings {
            println!();
            println!(
                "  {} {}",
                st.yellow("note:"),
                render::wrap_text(w, width - 8, "        ")
            );
        }
    }

    // -- findings ----------------------------------------------------------
    //
    // Three populations, kept distinct on purpose. Collapsing them is how the
    // first version of this function came to print "CLEAN — nothing to report"
    // directly under a header saying "2 run install scripts": `--top 0`
    // truncated every finding, and the empty-list branch could not tell
    // "found nothing" apart from "you filtered everything out". A verdict
    // that contradicts the summary three lines above it is worse than no
    // verdict, so the two reasons a finding is absent are now tracked and
    // named separately.
    let (shown, matched, below_verbosity, past_the_limit) =
        select_findings(&r.findings, only, verbose, top);

    // How to say "there are more, here is how to see them" — accurately, and
    // naming only the flag that is actually responsible.
    let more_hint = |n: usize| -> String {
        let mut ways: Vec<&str> = Vec::new();
        if below_verbosity > 0 {
            ways.push("-v");
        }
        if past_the_limit > 0 {
            ways.push("--top");
        }
        format!(
            "{n} more finding{} hidden by {}",
            if n == 1 { "" } else { "s" },
            ways.join(" / ")
        )
    };

    println!();
    if shown.is_empty() {
        if matched == 0 {
            // Genuinely nothing — the only case that earns the word CLEAN.
            println!(
                "  {}  nothing to report{}",
                st.green("CLEAN"),
                match only {
                    Some(rule) => format!(" for rule `{rule}`"),
                    None => String::new(),
                }
            );
        } else {
            // Findings exist; the flags suppressed them. Say so plainly, and
            // keep the severity breakdown visible so the verdict cannot
            // contradict the summary above it.
            println!(
                "  {}  {} finding{} matched, none displayed — {}",
                st.yellow("FILTERED"),
                matched,
                if matched == 1 { "" } else { "s" },
                more_hint(matched)
            );
            println!(
                "  {}",
                st.dim(&format!(
                    "{} critical · {} high · {} medium · {} low · {} info",
                    r.count(Severity::Critical),
                    r.count(Severity::High),
                    r.count(Severity::Medium),
                    r.count(Severity::Low),
                    r.count(Severity::Info),
                ))
            );
        }
        println!();
        return;
    }

    println!("  {}", st.bold(&format!("FINDINGS ({})", shown.len())));
    println!();

    for f in &shown {
        println!("  {} {}", st.sev(f.severity), st.bold(&f.title));
        println!(
            "             {}",
            render::wrap_text(&f.detail, width - 14, "             ")
        );
        if show_blame && f.blame.len() > 1 {
            println!(
                "             {} {}",
                st.dim("why:"),
                st.cyan(&f.blame.join(" -> "))
            );
        }
        println!("             {}", st.dim(&format!("[{}]", f.rule)));
        println!();
    }

    let hidden = below_verbosity + past_the_limit;
    if hidden > 0 {
        println!("  {}", st.dim(&more_hint(hidden)));
        println!();
    }

    if !quiet {
        let c = r.count(Severity::Critical);
        let h = r.count(Severity::High);
        let m = r.count(Severity::Medium);
        let l = r.count(Severity::Low);
        let i = r.count(Severity::Info);
        println!(
            "  {}  {}",
            st.bold("SUMMARY"),
            format_args!(
                "{} critical · {} high · {} medium · {} low · {} info",
                c, h, m, l, i
            )
        );
        println!(
            "  {}",
            st.dim(&format!(
                "compared {} names against {} known-popular {} package names, offline",
                commas(r.total),
                commas(r.corpus_size),
                r.eco.label()
            ))
        );
        println!();
    }
}

impl Audit {
    /// requirements.txt has no tree, so the tree-shaped stats are meaningless
    /// there and printing them would be a lie by formatting.
    fn flat_note(&self) -> bool {
        self.eco == Ecosystem::PyPI
    }
}

fn report_json(r: &Audit) -> json::Value {
    let findings: Vec<json::Value> = r
        .findings
        .iter()
        .map(|f| {
            json::obj(vec![
                ("rule", json::s(f.rule)),
                ("severity", json::s(&f.severity.label().to_ascii_lowercase())),
                ("package", json::s(&f.package)),
                ("version", json::s(&f.version)),
                ("title", json::s(&f.title)),
                ("detail", json::s(&f.detail)),
                (
                    "path",
                    json::Value::Arr(f.blame.iter().map(|b| json::s(b)).collect()),
                ),
            ])
        })
        .collect();

    let dups: Vec<json::Value> = r
        .duplicates
        .iter()
        .map(|(k, v)| {
            json::obj(vec![
                ("name", json::s(k)),
                (
                    "versions",
                    json::Value::Arr(v.iter().map(|s| json::s(s)).collect()),
                ),
            ])
        })
        .collect();

    json::obj(vec![
        ("tool", json::s("stranger")),
        ("version", json::s(VERSION)),
        ("ecosystem", json::s(r.eco.label())),
        ("source", json::s(&r.source.display().to_string())),
        (
            "summary",
            json::obj(vec![
                ("total", json::n(r.total)),
                ("direct", json::n(r.direct)),
                ("transitive", json::n(r.transitive)),
                ("maxDepth", json::n(r.max_depth)),
                ("installScripts", json::n(r.install_scripts)),
                ("missingIntegrity", json::n(r.missing_integrity)),
                ("cycles", json::n(r.cycles)),
                ("corpusSize", json::n(r.corpus_size)),
                ("critical", json::n(r.count(Severity::Critical))),
                ("high", json::n(r.count(Severity::High))),
                ("medium", json::n(r.count(Severity::Medium))),
                ("low", json::n(r.count(Severity::Low))),
                ("info", json::n(r.count(Severity::Info))),
            ]),
        ),
        ("duplicates", json::Value::Arr(dups)),
        (
            "warnings",
            json::Value::Arr(r.warnings.iter().map(|w| json::s(w)).collect()),
        ),
        ("findings", json::Value::Arr(findings)),
    ])
}

// ---------------------------------------------------------------------------
// diff — what did that install actually add?
// ---------------------------------------------------------------------------
//
// This is the subcommand I wanted to exist. `npm install one-thing` prints a
// line saying it added 47 packages and does not tell you which, and the
// lockfile diff in your PR is four thousand lines of reordered JSON. This
// answers the question the diff is hiding: what is new, what vanished, what
// changed version — and are any of the new arrivals worth a second look.

fn cmd_diff(args: &Args, st: &render::Style) -> Result<ExitCode, String> {
    let old_path = args.positionals.first().ok_or("diff needs two files: <old> <new>")?;
    let new_path = args.positionals.get(1).ok_or("diff needs two files: <old> <new>")?;

    let mut old = build_graph(old_path, args.value("as"))?;
    let mut new = build_graph(new_path, args.value("as"))?;
    if old.eco != new.eco {
        return Err(format!(
            "cannot compare a {} lockfile with a {} one",
            old.eco.label(),
            new.eco.label()
        ));
    }

    let key = |p: &Pkg| format!("{}@{}", p.name, p.version);
    let old_set: HashMap<String, ()> = old.pkgs.iter().map(|p| (key(p), ())).collect();
    let new_set: HashMap<String, ()> = new.pkgs.iter().map(|p| (key(p), ())).collect();

    let old_names: HashMap<String, BTreeSet<String>> = version_map(&old);
    let new_names: HashMap<String, BTreeSet<String>> = version_map(&new);

    // Owned clones: the rule pass below needs `new` mutably, so nothing may
    // still be borrowing out of it.
    let mut added: Vec<Pkg> =
        new.pkgs.iter().filter(|p| !old_set.contains_key(&key(p))).cloned().collect();
    let mut removed: Vec<Pkg> =
        old.pkgs.iter().filter(|p| !new_set.contains_key(&key(p))).cloned().collect();
    added.sort_by(|a, b| a.name.cmp(&b.name).then(a.version.cmp(&b.version)));
    removed.sort_by(|a, b| a.name.cmp(&b.name).then(a.version.cmp(&b.version)));

    let brand_new: Vec<&Pkg> = added.iter().filter(|p| !old_names.contains_key(&p.name)).collect();
    let bumped: Vec<&Pkg> = added.iter().filter(|p| old_names.contains_key(&p.name)).collect();
    let gone: Vec<&Pkg> = removed.iter().filter(|p| !new_names.contains_key(&p.name)).collect();

    println!();
    println!(
        "  {} {}",
        st.bold("stranger diff"),
        st.dim(&format!("{old_path} -> {new_path}"))
    );
    println!();
    let delta = new.pkgs.len() as i64 - old.pkgs.len() as i64;
    println!(
        "  {} packages -> {} packages   {}",
        commas(old.pkgs.len()),
        commas(new.pkgs.len()),
        if delta > 0 {
            st.yellow(&format!("+{delta}"))
        } else if delta < 0 {
            st.green(&format!("{delta}"))
        } else {
            st.dim("no net change")
        }
    );
    println!();

    if !brand_new.is_empty() {
        println!("  {} {}", st.yellow("NEW"), st.bold(&format!("({} packages never seen before)", brand_new.len())));
        for p in brand_new.iter().take(200) {
            println!("    {} {}@{}", st.yellow("+"), p.name, p.version);
        }
        println!();
    }
    if !bumped.is_empty() {
        println!("  {} {}", st.cyan("CHANGED"), st.bold(&format!("({} version changes)", bumped.len())));
        for p in bumped.iter().take(200) {
            let was = old_names
                .get(&p.name)
                .map(|v| v.iter().cloned().collect::<Vec<_>>().join(", "))
                .unwrap_or_default();
            println!("    {} {} {} -> {}", st.cyan("~"), p.name, st.dim(&was), p.version);
        }
        println!();
    }
    if !gone.is_empty() {
        println!("  {} {}", st.green("REMOVED"), st.bold(&format!("({} packages)", gone.len())));
        for p in gone.iter().take(200) {
            println!("    {} {}@{}", st.green("-"), p.name, p.version);
        }
        println!();
    }

    // Re-run the rules against the new file, then report only findings that
    // concern packages this change introduced. This is the review question:
    // not "is my tree clean" but "did this PR make it worse".
    let opts = rule_options(args)?;
    let _ = audit(&mut old, &opts);
    let new_report = audit(&mut new, &opts);
    let added_keys: HashSet<String> = added.iter().map(|p| p.name.clone()).collect();
    let relevant: Vec<&Finding> = new_report
        .findings
        .iter()
        .filter(|f| added_keys.contains(&f.package))
        .filter(|f| f.severity > Severity::Info)
        .collect();

    if relevant.is_empty() {
        println!("  {} no new findings from the added packages", st.green("CLEAN"));
    } else {
        println!("  {}", st.bold(&format!("NEW FINDINGS ({})", relevant.len())));
        println!();
        for f in &relevant {
            println!("  {} {}", st.sev(f.severity), st.bold(&f.title));
            println!(
                "             {}",
                render::wrap_text(&f.detail, 64, "             ")
            );
            println!();
        }
    }
    println!();

    let threshold = args
        .value("fail-on")
        .map(|s| Severity::from_str(s).ok_or(format!("unknown severity `{s}`")))
        .transpose()?
        .unwrap_or(Severity::High);
    let over = relevant.iter().any(|f| f.severity >= threshold);
    Ok(if over { ExitCode::from(1) } else { ExitCode::SUCCESS })
}

fn version_map(g: &Graph) -> HashMap<String, BTreeSet<String>> {
    let mut m: HashMap<String, BTreeSet<String>> = HashMap::new();
    for p in &g.pkgs {
        m.entry(p.name.clone()).or_default().insert(p.version.clone());
    }
    m
}

// ---------------------------------------------------------------------------
// why — who pulled this in
// ---------------------------------------------------------------------------

fn cmd_why(args: &Args, st: &render::Style) -> Result<ExitCode, String> {
    let path = args.positionals.first().ok_or("why needs <lockfile> <package>")?;
    let target = args.positionals.get(1).ok_or("why needs <lockfile> <package>")?;

    let mut g = build_graph(path, args.value("as"))?;
    let parent = g.compute_depths();

    let matches: Vec<usize> = (0..g.pkgs.len())
        .filter(|&i| g.pkgs[i].name == *target)
        .collect();

    println!();
    if matches.is_empty() {
        // Be useful about it: near-miss names are exactly what this tool is
        // good at, so offer them rather than just failing.
        let mut near: Vec<(usize, &str)> = g
            .pkgs
            .iter()
            .filter_map(|p| dist::bounded(&p.name, target, 2).map(|d| (d, p.name.as_str())))
            .collect();
        near.sort_unstable();
        near.dedup_by(|a, b| a.1 == b.1);
        println!("  {} `{target}` is not in {}", st.yellow("not found:"), path);
        if !near.is_empty() {
            println!(
                "  {} {}",
                st.dim("did you mean:"),
                near.iter().take(5).map(|(_, n)| *n).collect::<Vec<_>>().join(", ")
            );
        }
        println!();
        return Ok(ExitCode::from(1));
    }

    println!("  {} {}", st.bold(target), st.dim(&format!("· {} instance(s)", matches.len())));
    println!();
    for i in matches {
        let p = &g.pkgs[i];
        println!(
            "  {}@{}  {}",
            st.bold(&p.name),
            p.version,
            st.dim(&format!(
                "depth {}{}{}",
                p.depth,
                if p.dev { " · dev" } else { "" },
                if p.optional { " · optional" } else { "" }
            ))
        );
        let chain = g.blame(&parent, i);
        if chain.len() > 1 {
            println!("    {}", st.cyan(&chain.join("\n      -> ")));
        } else if g.roots.contains(&i) {
            println!("    {}", st.green("you chose this directly"));
        } else {
            println!("    {}", st.dim("no path from a root dependency"));
        }
        if !p.install_scripts.is_empty() {
            println!("    {} {}", st.red("install scripts:"), p.install_scripts.join(", "));
        }
        if let Some(res) = &p.resolved {
            println!("    {} {}", st.dim("from:"), res);
        }
        println!();
    }
    Ok(ExitCode::SUCCESS)
}

// ===========================================================================
// 10. tests
// ===========================================================================
//
// Would normally be: pytest / jest / testify / a test crate. Rust ships a
// harness, so `cargo test` runs all of this with no dev-dependency.
//
// The parser tests are the ones that matter. A hand-written JSON parser is
// only worth trusting if it is tested against the inputs that break parsers,
// not the inputs that work — so the corpus below is modelled on the shape of
// JSONTestSuite: y_ cases must parse, n_ cases must be rejected. Getting the
// n_ cases right is what separates "reads my file" from "is a JSON parser".
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // -----------------------------------------------------------------
    // JSON: must-accept
    // -----------------------------------------------------------------
    #[test]
    fn json_accepts_valid_documents() {
        let cases: &[(&str, &str)] = &[
            ("empty object", "{}"),
            ("empty array", "[]"),
            ("nested empties", r#"{"a":[],"b":{}}"#),
            ("all scalars", r#"{"n":null,"t":true,"f":false,"i":0,"s":""}"#),
            ("negative zero", "[-0]"),
            ("exponents", "[1e10,1E+2,1e-2,0e0,-1.5E-10]"),
            ("deep-ish nesting", "[[[[[[[[[[1]]]]]]]]]]"),
            ("escapes", r#""\"\\\/\b\f\n\r\t""#),
            ("unicode escape", r#""\u00e9\u0041""#),
            ("surrogate pair", r#""\ud83d\ude00""#),
            ("raw utf8", "\"héllo — 世界 🎉\""),
            ("whitespace everywhere", " \t\r\n { \"a\" : \n 1 } \r\n "),
            ("big int lexeme", "[123456789012345678901234567890]"),
            ("string with solidus", r#""a/b""#),
            ("key with escapes", r#"{"a\nb":1}"#),
        ];
        for (name, src) in cases {
            assert!(
                json::parse(src).is_ok(),
                "expected `{name}` to parse: {src}\n  got: {:?}",
                json::parse(src).err()
            );
        }
    }

    // -----------------------------------------------------------------
    // JSON: must-reject. These are the cases a lenient parser waves through.
    // -----------------------------------------------------------------
    #[test]
    fn json_rejects_invalid_documents() {
        let cases: &[(&str, &str)] = &[
            ("trailing comma in object", r#"{"a":1,}"#),
            ("trailing comma in array", "[1,2,]"),
            ("leading zero", "[01]"),
            ("plus sign", "[+1]"),
            ("bare fraction", "[.5]"),
            ("trailing dot", "[1.]"),
            ("no exponent digits", "[1e]"),
            ("hex literal", "[0x10]"),
            ("single quotes", "{'a':1}"),
            ("unquoted key", "{a:1}"),
            ("comment", "{} // hi"),
            ("NaN", "[NaN]"),
            ("Infinity", "[Infinity]"),
            ("unterminated string", "\"abc"),
            ("unterminated object", "{\"a\":1"),
            ("unterminated array", "[1,2"),
            ("lone high surrogate", r#""\ud800""#),
            ("lone low surrogate", r#""\udc00""#),
            ("high surrogate then plain", r#""\ud800\u0041""#),
            ("bad escape", r#""\x41""#),
            ("short unicode escape", r#""\u12""#),
            ("raw newline in string", "\"a\nb\""),
            ("raw tab in string", "\"a\tb\""),
            ("raw null in string", "\"a\u{0}b\""),
            ("two top-level values", "{} {}"),
            ("empty input", ""),
            ("just a comma", ","),
            ("missing colon", r#"{"a" 1}"#),
            ("missing value", r#"{"a":}"#),
            ("double comma", "[1,,2]"),
        ];
        for (name, src) in cases {
            assert!(
                json::parse(src).is_err(),
                "expected `{name}` to be REJECTED but it parsed: {src}"
            );
        }
    }

    #[test]
    fn json_reports_useful_positions() {
        // Position information is the thing you actually want at 2am, so it
        // gets a test rather than being assumed.
        let src = "{\n  \"a\": 1,\n  \"b\": tru\n}";
        let e = json::parse(src).unwrap_err();
        assert_eq!(e.line, 3, "error should point at line 3, got {e:?}");
        assert!(e.col > 1);
    }

    #[test]
    fn json_depth_limit_is_enforced() {
        // A hostile file should produce an error, not a stack overflow.
        let deep = "[".repeat(json::MAX_DEPTH + 10) + &"]".repeat(json::MAX_DEPTH + 10);
        let e = json::parse(&deep).unwrap_err();
        assert!(e.msg.contains("depth"), "got: {}", e.msg);
    }

    #[test]
    fn json_surrogate_pair_decodes_to_one_char() {
        let v = json::parse(r#""\ud83d\ude00""#).unwrap();
        assert_eq!(v.as_str().unwrap(), "😀");
    }

    #[test]
    fn json_duplicate_keys_take_the_last_value() {
        let v = json::parse(r#"{"a":1,"a":2}"#).unwrap();
        assert_eq!(v.get("a").unwrap().as_u64(), Some(2));
    }

    #[test]
    fn json_number_lexeme_is_preserved() {
        // `1.0` must not come back as `1`, and a u64 beyond f64 precision must
        // not be silently rounded when we re-emit it.
        let v = json::parse(r#"{"a":1.0,"b":10000000000000000001}"#).unwrap();
        let out = json::to_string(&v);
        assert!(out.contains("1.0"), "got {out}");
        assert!(out.contains("10000000000000000001"), "got {out}");
    }

    #[test]
    fn json_roundtrips() {
        let src = r#"{"b":[1,2,{"c":null}],"a":"x\ny"}"#;
        let once = json::to_string(&json::parse(src).unwrap());
        let twice = json::to_string(&json::parse(&once).unwrap());
        assert_eq!(once, twice, "serialize -> parse -> serialize must be stable");
    }

    #[test]
    fn json_escapes_control_characters_on_output() {
        let v = json::Value::Str("a\u{1}b".to_string());
        assert_eq!(json::to_string(&v), r#""a\u0001b""#);
    }

    #[test]
    fn json_object_keys_are_sorted_for_stable_output() {
        let v = json::parse(r#"{"z":1,"a":2,"m":3}"#).unwrap();
        let out = json::to_string(&v);
        let a = out.find("\"a\"").unwrap();
        let m = out.find("\"m\"").unwrap();
        let z = out.find("\"z\"").unwrap();
        assert!(a < m && m < z, "keys must serialize sorted: {out}");
    }

    // -----------------------------------------------------------------
    // TOML subset
    // -----------------------------------------------------------------
    const CARGO_LOCK: &str = r#"
# This file is automatically @generated by Cargo.
version = 4

[[package]]
name = "aho-corasick"
version = "1.1.3"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "8e60d3430d3a69478ad0993f19238d2df97c507009a52b3c10addcd7f6bcb916"
dependencies = [
 "memchr",
]

[[package]]
name = "memchr"
version = "2.7.4"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "78ca9ab1a0babb1e7d5695e3530886289c18cf2f87ec19a575a0abdce112e3a3"

[[package]]
name = "regex"
version = "1.11.1"
source = "registry+https://github.com/rust-lang/crates.io-index"
dependencies = [
 "aho-corasick",
 "memchr",
 "regex-syntax 0.8.5",
]
"#;

    #[test]
    fn toml_reads_cargo_lock_shape() {
        let d = toml::parse(CARGO_LOCK).unwrap();
        assert_eq!(d.root.get("version"), Some(&toml::Value::Int(4)));
        let pkgs = d.arrays.get("package").unwrap();
        assert_eq!(pkgs.len(), 3);
        assert_eq!(pkgs[0].get("name").unwrap().as_str(), Some("aho-corasick"));
        // The multi-line array must survive the fold.
        let deps = pkgs[2].get("dependencies").unwrap().as_arr().unwrap();
        assert_eq!(deps.len(), 3);
        assert_eq!(deps[2].as_str(), Some("regex-syntax 0.8.5"));
        // A package with no checksum must read as absent, not as empty.
        assert!(pkgs[2].get("checksum").is_none());
    }

    #[test]
    fn toml_hash_inside_a_string_is_not_a_comment() {
        let d = toml::parse(r#"a = "value#not-a-comment" # real comment"#).unwrap();
        assert_eq!(d.root.get("a").unwrap().as_str(), Some("value#not-a-comment"));
    }

    #[test]
    fn toml_literal_strings_do_not_process_escapes() {
        let d = toml::parse(r#"p = 'C:\Users\n'"#).unwrap();
        assert_eq!(d.root.get("p").unwrap().as_str(), Some(r"C:\Users\n"));
    }

    #[test]
    fn toml_basic_strings_do_process_escapes() {
        let d = toml::parse(r#"a = "line\nbreak\u0041""#).unwrap();
        assert_eq!(d.root.get("a").unwrap().as_str(), Some("line\nbreakA"));
    }

    #[test]
    fn toml_rejects_constructs_outside_the_subset_instead_of_guessing() {
        // The honest failure. Silently mis-parsing an inline table would be
        // worse than refusing it.
        let e = toml::parse("a = { b = 1 }").unwrap_err();
        assert!(e.msg.contains("inline table"), "got: {}", e.msg);
    }

    #[test]
    fn toml_underscored_integers() {
        let d = toml::parse("n = 1_000_000").unwrap();
        assert_eq!(d.root.get("n"), Some(&toml::Value::Int(1_000_000)));
    }

    // -----------------------------------------------------------------
    // requirements.txt
    // -----------------------------------------------------------------
    #[test]
    fn pep508_parses_the_awkward_lines() {
        let src = r#"
# a comment
requests==2.31.0
Django >= 4.2, < 5.0
numpy
pandas[performance]==2.1.4
flask ; python_version >= "3.9"
mytool @ https://example.invalid/mytool-1.0.whl
urllib3==2.0.7 --hash=sha256:aaa --hash=sha256:bbb
-r dev.txt
--extra-index-url https://internal.example/simple
-e .
scikit-learn==1.3.2 \
    --hash=sha256:ccc
"#;
        let f = pep508::parse(src);
        let names: Vec<&str> = f.requirements.iter().map(|r| r.name.as_str()).collect();
        assert_eq!(
            names,
            vec![
                "requests", "Django", "numpy", "pandas", "flask", "mytool", "urllib3",
                "scikit-learn"
            ]
        );
        assert_eq!(f.includes, vec!["dev.txt"]);
        assert_eq!(f.editables, vec!["."]);
        assert_eq!(f.index_urls, vec!["https://internal.example/simple"]);

        let by = |n: &str| f.requirements.iter().find(|r| r.name == n).unwrap();
        assert!(by("requests").is_pinned());
        assert!(!by("Django").is_pinned());
        assert!(by("numpy").spec.trim().is_empty() && by("numpy").url.is_none());
        assert_eq!(by("pandas").extras, vec!["performance"]);
        assert!(by("pandas").is_pinned());
        assert_eq!(by("flask").marker.as_deref(), Some(r#"python_version >= "3.9""#));
        assert_eq!(
            by("mytool").url.as_deref(),
            Some("https://example.invalid/mytool-1.0.whl")
        );
        assert_eq!(by("urllib3").hashes.len(), 2);
        // The backslash continuation must fold into the previous requirement.
        assert_eq!(by("scikit-learn").hashes, vec!["sha256:ccc"]);
    }

    #[test]
    fn pep508_wildcard_pin_is_not_a_pin() {
        let f = pep508::parse("django==4.2.*");
        assert!(!f.requirements[0].is_pinned());
    }

    #[test]
    fn pep508_normalises_per_pep503() {
        for (raw, want) in [
            ("Flask", "flask"),
            ("python_dotenv", "python-dotenv"),
            ("zope.interface", "zope-interface"),
            ("Foo--Bar", "foo-bar"),
            ("A.B_C", "a-b-c"),
        ] {
            assert_eq!(pep508::normalize(raw), want, "normalising {raw}");
        }
    }

    #[test]
    fn pep508_url_fragment_is_not_a_comment() {
        let f = pep508::parse("pkg @ https://example.invalid/x.whl#egg=pkg");
        assert_eq!(f.requirements.len(), 1);
        assert!(f.requirements[0].url.as_deref().unwrap().contains("#egg=pkg"));
    }

    // -----------------------------------------------------------------
    // distance
    // -----------------------------------------------------------------
    #[test]
    fn distance_counts_a_transposition_as_one_edit() {
        // The whole reason for Damerau over Levenshtein.
        assert_eq!(dist::bounded("python-dotnev", "python-dotenv", 2), Some(1));
        assert_eq!(dist::bounded("axois", "axios", 2), Some(1));
        assert_eq!(dist::bounded("lodahs", "lodash", 2), Some(1));
    }

    #[test]
    fn distance_basic_edits() {
        assert_eq!(dist::bounded("express", "express", 2), Some(0));
        assert_eq!(dist::bounded("expres", "express", 2), Some(1)); // deletion
        assert_eq!(dist::bounded("expresss", "express", 2), Some(1)); // insertion
        assert_eq!(dist::bounded("exprese", "express", 2), Some(1)); // substitution
    }

    #[test]
    fn distance_respects_its_budget() {
        assert_eq!(dist::bounded("abcdef", "uvwxyz", 2), None);
        assert_eq!(dist::bounded("a", "abcdefgh", 2), None);
        // Length difference alone is enough to bail out.
        assert_eq!(dist::bounded("", "abc", 2), None);
        assert_eq!(dist::bounded("", "ab", 2), Some(2));
    }

    #[test]
    fn distance_handles_multibyte_characters_by_char_not_byte() {
        // Byte-wise distance would call these far apart; they differ by one
        // character.
        assert_eq!(dist::bounded("café", "cafe", 2), Some(1));
    }

    #[test]
    fn skeleton_folds_confusable_glyphs() {
        assert_eq!(dist::skeleton("cha1k"), dist::skeleton("chalk"));
        assert_eq!(dist::skeleton("l0dash"), dist::skeleton("lodash"));
        assert_eq!(dist::skeleton("lo-dash"), dist::skeleton("lodash"));
        assert_eq!(dist::skeleton("moment"), dist::skeleton("rnoment"));
        assert_ne!(dist::skeleton("react"), dist::skeleton("redux"));
    }

    #[test]
    fn scope_splitting() {
        assert_eq!(dist::split_scope("@types/node"), (Some("types"), "node"));
        assert_eq!(dist::split_scope("lodash"), (None, "lodash"));
        assert_eq!(dist::split_scope("@weird"), (None, "@weird"));
    }

    // -----------------------------------------------------------------
    // npm resolution + graph
    // -----------------------------------------------------------------
    fn npm_graph(src: &str) -> Graph {
        let v = json::parse(src).unwrap();
        load_npm(&v, Path::new("test-lock.json")).unwrap()
    }

    /// Two versions of `dep` at different install paths. Node resolves `a`'s
    /// dependency to the nested copy and `b`'s to the hoisted one. Merging
    /// them by name would make every blame path a lie.
    const NESTED: &str = r#"{
      "lockfileVersion": 3,
      "packages": {
        "": {"dependencies": {"a": "1.0.0", "b": "1.0.0"}},
        "node_modules/a": {"version": "1.0.0", "dependencies": {"dep": "2.0.0"}},
        "node_modules/a/node_modules/dep": {"version": "2.0.0"},
        "node_modules/b": {"version": "1.0.0", "dependencies": {"dep": "1.0.0"}},
        "node_modules/dep": {"version": "1.0.0"}
      }
    }"#;

    #[test]
    fn npm_resolution_walks_up_from_the_nested_directory_first() {
        let g = npm_graph(NESTED);
        let idx = |loc: &str| g.pkgs.iter().position(|p| p.location == loc).unwrap();
        let a = idx("node_modules/a");
        let b = idx("node_modules/b");
        let nested = idx("node_modules/a/node_modules/dep");
        let hoisted = idx("node_modules/dep");

        assert_eq!(g.pkgs[a].edges, vec![nested], "a must bind to its nested copy");
        assert_eq!(g.pkgs[b].edges, vec![hoisted], "b must bind to the hoisted copy");
        assert_eq!(g.pkgs[nested].version, "2.0.0");
        assert_eq!(g.pkgs[hoisted].version, "1.0.0");
    }

    #[test]
    fn npm_name_is_derived_from_the_install_path() {
        let g = npm_graph(NESTED);
        let nested = g
            .pkgs
            .iter()
            .find(|p| p.location == "node_modules/a/node_modules/dep")
            .unwrap();
        assert_eq!(nested.name, "dep");
    }

    #[test]
    fn npm_scoped_names_survive_the_path_split() {
        let g = npm_graph(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"@scope/pkg":"1.0.0"}},
                "node_modules/@scope/pkg":{"version":"1.0.0"}}}"#,
        );
        assert_eq!(g.pkgs[0].name, "@scope/pkg");
        assert_eq!(g.roots.len(), 1);
    }

    #[test]
    fn depths_are_shortest_paths_from_a_root() {
        let mut g = npm_graph(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"a":"1"}},
                "node_modules/a":{"version":"1","dependencies":{"b":"1"}},
                "node_modules/b":{"version":"1","dependencies":{"c":"1"}},
                "node_modules/c":{"version":"1"}}}"#,
        );
        g.compute_depths();
        let d = |n: &str| g.pkgs.iter().find(|p| p.name == n).unwrap().depth;
        assert_eq!((d("a"), d("b"), d("c")), (1, 2, 3));
        assert_eq!(g.max_depth(), 3);
    }

    #[test]
    fn blame_reconstructs_the_chain_to_a_root() {
        let mut g = npm_graph(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"a":"1"}},
                "node_modules/a":{"version":"1","dependencies":{"b":"1"}},
                "node_modules/b":{"version":"1"}}}"#,
        );
        let parent = g.compute_depths();
        let b = g.pkgs.iter().position(|p| p.name == "b").unwrap();
        assert_eq!(g.blame(&parent, b), vec!["a@1", "b@1"]);
    }

    #[test]
    fn cycles_are_detected_without_recursion_blowing_up() {
        let g = npm_graph(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"a":"1"}},
                "node_modules/a":{"version":"1","dependencies":{"b":"1"}},
                "node_modules/b":{"version":"1","dependencies":{"a":"1"}}}}"#,
        );
        assert!(!g.cycles().is_empty(), "a <-> b is a cycle");
    }

    #[test]
    fn duplicates_are_grouped_by_name() {
        let g = npm_graph(NESTED);
        let d = g.duplicates();
        assert_eq!(d.len(), 1);
        assert_eq!(d["dep"].len(), 2);
    }

    #[test]
    fn lockfile_v1_is_read_rather_than_refused() {
        let g = npm_graph(
            r#"{"lockfileVersion":1,"dependencies":{
                "a":{"version":"1.0.0","requires":{"b":"1.0.0"},
                     "dependencies":{"b":{"version":"1.0.0"}}}}}"#,
        );
        assert_eq!(g.pkgs.len(), 2);
        assert!(!g.warnings.is_empty(), "v1 limitations must be disclosed");
    }

    // -----------------------------------------------------------------
    // rules
    // -----------------------------------------------------------------
    fn audit_src(src: &str) -> Audit {
        let mut g = npm_graph(src);
        audit(&mut g, &RuleOptions::default())
    }

    fn has_rule(a: &Audit, rule: &str, pkg: &str) -> bool {
        a.findings.iter().any(|f| f.rule == rule && f.package == pkg)
    }

    #[test]
    fn typosquat_fires_on_a_credible_near_miss() {
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"expres":"4"}},
                "node_modules/expres":{"version":"4.18.2","resolved":"https://registry.npmjs.org/x","integrity":"sha512-x"}}}"#,
        );
        assert!(has_rule(&a, "typosquat-candidate", "expres"));
    }

    #[test]
    fn typosquat_stays_quiet_on_short_names() {
        // The regression that mattered: two edits on a four-character name is
        // half the string, and reporting it made the tool useless on any real
        // tree. `etag` must not be flagged as a near-miss for `tar`.
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"etag":"1"}},
                "node_modules/etag":{"version":"1.8.1"}}}"#,
        );
        assert!(
            !has_rule(&a, "typosquat-candidate", "etag"),
            "short names must not produce distance-2 findings"
        );
    }

    #[test]
    fn typosquat_is_demoted_when_many_packages_depend_on_it() {
        // High in-degree is the offline stand-in for "this package is
        // established". The finding survives, at INFO, rather than vanishing.
        let src = r#"{"lockfileVersion":3,"packages":{
            "":{"dependencies":{"a":"1","b":"1","c":"1","d":"1"}},
            "node_modules/a":{"version":"1","dependencies":{"webpack-clii":"1"}},
            "node_modules/b":{"version":"1","dependencies":{"webpack-clii":"1"}},
            "node_modules/c":{"version":"1","dependencies":{"webpack-clii":"1"}},
            "node_modules/d":{"version":"1","dependencies":{"webpack-clii":"1"}},
            "node_modules/webpack-clii":{"version":"1"}}}"#;
        let a = audit_src(src);
        let f = a
            .findings
            .iter()
            .find(|f| f.rule == "typosquat-candidate" && f.package == "webpack-clii")
            .expect("finding should still be reported");
        assert_eq!(f.severity, Severity::Info, "in-degree 4 must demote it");
    }

    #[test]
    fn confusable_glyphs_are_caught_separately_from_edit_distance() {
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"cha1k":"5"}},
                "node_modules/cha1k":{"version":"5.3.0"}}}"#,
        );
        assert!(has_rule(&a, "confusable-name", "cha1k"));
    }

    #[test]
    fn a_squatty_name_that_also_runs_scripts_is_escalated_to_critical() {
        // Either signal alone is a maybe. Together they are the attack.
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"expres":"4"}},
                "node_modules/expres":{"version":"4.18.2","hasInstallScript":true}}}"#,
        );
        let f = a
            .findings
            .iter()
            .find(|f| f.rule == "install-script")
            .unwrap();
        assert_eq!(f.severity, Severity::Critical);
    }

    #[test]
    fn install_scripts_are_found_in_both_recorded_shapes() {
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"alpha-widget":"1","beta-widget":"1"}},
                "node_modules/alpha-widget":{"version":"1","hasInstallScript":true},
                "node_modules/beta-widget":{"version":"1","scripts":{"postinstall":"node x.js","test":"jest"}}}}"#,
        );
        assert!(has_rule(&a, "install-script", "alpha-widget"));
        assert!(has_rule(&a, "install-script", "beta-widget"));
        // `test` is not a lifecycle install hook and must not be reported.
        let f = a.findings.iter().find(|f| f.package == "beta-widget").unwrap();
        assert!(!f.detail.contains("test"), "only install hooks count");
    }

    #[test]
    fn off_registry_sources_are_flagged() {
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"internal-thing":"1","normal-thing":"1"}},
                "node_modules/internal-thing":{"version":"1","resolved":"git+ssh://git@github.com/x/y.git#main"},
                "node_modules/normal-thing":{"version":"1","resolved":"https://registry.npmjs.org/n/-/n-1.tgz","integrity":"sha512-x"}}}"#,
        );
        assert!(has_rule(&a, "off-registry-source", "internal-thing"));
        assert!(!has_rule(&a, "off-registry-source", "normal-thing"));
    }

    #[test]
    fn missing_integrity_is_only_reported_when_a_hash_was_expected() {
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"downloaded":"1","linked":"1"}},
                "node_modules/downloaded":{"version":"1","resolved":"https://registry.npmjs.org/d/-/d-1.tgz"},
                "node_modules/linked":{"version":"1"}}}"#,
        );
        assert!(has_rule(&a, "no-integrity", "downloaded"));
        assert!(
            !has_rule(&a, "no-integrity", "linked"),
            "an entry with no `resolved` was never downloaded"
        );
    }

    #[test]
    fn the_trivial_list_holds_only_genuinely_small_packages() {
        // The guard on an overclaim: `core-js` and `es6-promise` were once on
        // this list. They are large, careful libraries that modern runtimes
        // make unnecessary — which is a different argument, and not one this
        // rule is making. Calling them one-liners was wrong.
        for banned in ["core-js", "es6-promise", "readable-stream", "lodash", "moment"] {
            assert!(
                !corpus::TRIVIAL.iter().any(|(n, _)| *n == banned),
                "`{banned}` is not a standard-library one-liner and must not be listed"
            );
        }
        // Every entry must carry a non-empty replacement, or the finding says
        // nothing actionable.
        for (name, replacement) in corpus::TRIVIAL {
            assert!(
                !replacement.trim().is_empty(),
                "`{name}` has no stated replacement"
            );
        }
    }

    #[test]
    fn trivial_packages_are_named_with_their_replacement() {
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"left-pad":"1"}},
                "node_modules/left-pad":{"version":"1.3.0"}}}"#,
        );
        let f = a
            .findings
            .iter()
            .find(|f| f.rule == "trivial-package")
            .expect("left-pad is the canonical case");
        assert!(f.detail.contains("padStart") || f.detail.contains("repeat"));
    }

    #[test]
    fn workspace_links_are_not_counted_as_dependencies() {
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"my-own-lib":"1"}},
                "node_modules/my-own-lib":{"resolved":"packages/lib","link":true},
                "packages/lib":{"version":"1.0.0"}}}"#,
        );
        assert!(
            !a.findings.iter().any(|f| f.package == "my-own-lib"),
            "your own workspace code is not a third-party dependency"
        );
    }

    #[test]
    fn findings_are_ordered_worst_first_and_deterministically() {
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"expres":"4","left-pad":"1"}},
                "node_modules/expres":{"version":"4","hasInstallScript":true},
                "node_modules/left-pad":{"version":"1.3.0"}}}"#,
        );
        let sevs: Vec<Severity> = a.findings.iter().map(|f| f.severity).collect();
        let mut sorted = sevs.clone();
        sorted.sort_by(|x, y| y.cmp(x));
        assert_eq!(sevs, sorted, "findings must be sorted worst-first");
    }

    #[test]
    fn the_summary_and_the_findings_can_never_disagree() {
        // The header counts install scripts; the findings list reports them.
        // If those two ever diverge, the report contradicts itself.
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"alpha-widget":"1","beta-widget":"1"}},
                "node_modules/alpha-widget":{"version":"1","hasInstallScript":true},
                "node_modules/beta-widget":{"version":"1","scripts":{"postinstall":"x"}}}}"#,
        );
        assert_eq!(a.install_scripts, 2);
        assert_eq!(
            a.install_scripts,
            a.findings.iter().filter(|f| f.rule == "install-script").count(),
            "the header counter and the findings list must be the same fact"
        );
    }

    #[test]
    fn top_zero_does_not_masquerade_as_a_clean_bill_of_health() {
        // The regression: `--top 0` truncated every finding, and the empty
        // list was reported as "CLEAN — nothing to report" directly beneath a
        // summary line counting install scripts. `matched` is what tells the
        // two cases apart.
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"alpha-widget":"1"}},
                "node_modules/alpha-widget":{"version":"1","hasInstallScript":true}}}"#,
        );
        let (shown, matched, _below, past) = select_findings(&a.findings, None, false, 0);
        assert!(shown.is_empty(), "--top 0 displays nothing");
        assert!(matched > 0, "but findings existed, so this is not CLEAN");
        assert_eq!(past, matched, "all of them were cut by the limit, not by -v");
    }

    #[test]
    fn every_suppressed_finding_is_accounted_for() {
        // shown + below_verbosity + past_the_limit == matched, for any flags.
        // Without this the footer's "N more" line drifts from reality.
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"expres":"4","left-pad":"1","deep-a":"1"}},
                "node_modules/expres":{"version":"4","hasInstallScript":true},
                "node_modules/left-pad":{"version":"1.3.0"},
                "node_modules/deep-a":{"version":"1","dependencies":{"deep-b":"1"}},
                "node_modules/deep-b":{"version":"1"}}}"#,
        );
        for verbose in [false, true] {
            for top in [0usize, 1, 3, usize::MAX] {
                let (shown, matched, below, past) =
                    select_findings(&a.findings, None, verbose, top);
                assert_eq!(
                    shown.len() + below + past,
                    matched,
                    "accounting broke at verbose={verbose} top={top}"
                );
            }
        }
    }

    #[test]
    fn only_filter_narrows_to_one_rule_and_reports_the_rest_as_matched_zero() {
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"left-pad":"1"}},
                "node_modules/left-pad":{"version":"1.3.0"}}}"#,
        );
        let (_, matched, _, _) =
            select_findings(&a.findings, Some("off-registry-source"), true, usize::MAX);
        assert_eq!(matched, 0, "a rule with no findings is genuinely clean");
        let (_, matched, _, _) =
            select_findings(&a.findings, Some("trivial-package"), true, usize::MAX);
        assert_eq!(matched, 1);
    }

    #[test]
    fn info_findings_are_hidden_without_v_and_shown_with_it() {
        let a = audit_src(
            r#"{"lockfileVersion":3,"packages":{
                "":{"dependencies":{"a":"1"}},
                "node_modules/a":{"version":"1","dependencies":{"b":"1"}},
                "node_modules/b":{"version":"1","dependencies":{"c":"1"}},
                "node_modules/c":{"version":"1","dependencies":{"d":"1"}},
                "node_modules/d":{"version":"1","dependencies":{"e":"1"}},
                "node_modules/e":{"version":"1","dependencies":{"f":"1"}},
                "node_modules/f":{"version":"1"}}}"#,
        );
        let (quiet, _, below, _) = select_findings(&a.findings, None, false, usize::MAX);
        let (loud, _, below_v, _) = select_findings(&a.findings, None, true, usize::MAX);
        assert!(below > 0, "the depth-6 finding is INFO and hidden by default");
        assert_eq!(below_v, 0, "-v hides nothing");
        assert!(loud.len() > quiet.len());
    }

    #[test]
    fn json_report_is_stable_across_runs() {
        // `--json` gets diffed in CI, so byte-identical output for identical
        // input is a requirement, not a nicety.
        let src = r#"{"lockfileVersion":3,"packages":{
            "":{"dependencies":{"expres":"4","left-pad":"1"}},
            "node_modules/expres":{"version":"4","hasInstallScript":true},
            "node_modules/left-pad":{"version":"1.3.0"}}}"#;
        let a = json::to_string(&report_json(&audit_src(src)));
        let b = json::to_string(&report_json(&audit_src(src)));
        assert_eq!(a, b);
    }

    // -----------------------------------------------------------------
    // CLI
    // -----------------------------------------------------------------
    fn args(v: &[&str]) -> Args {
        parse_args(v.iter().map(|s| s.to_string()).collect()).unwrap()
    }

    #[test]
    fn cli_supports_both_flag_value_forms() {
        let a = args(&["audit", "f.json", "--fail-on=medium"]);
        assert_eq!(a.value("fail-on"), Some("medium"));
        let b = args(&["audit", "f.json", "--fail-on", "medium"]);
        assert_eq!(b.value("fail-on"), Some("medium"));
    }

    #[test]
    fn cli_clusters_short_flags() {
        let a = args(&["-qj"]);
        assert!(a.has("quiet") && a.has("json"));
    }

    #[test]
    fn cli_double_dash_ends_option_parsing() {
        let a = args(&["audit", "--", "--weird-filename.json"]);
        assert_eq!(a.positionals, vec!["--weird-filename.json"]);
        assert!(!a.has("weird-filename.json"));
    }

    #[test]
    fn cli_defaults_to_audit() {
        assert_eq!(args(&["package-lock.json"]).command, "audit");
        assert_eq!(args(&["package-lock.json"]).positionals, vec!["package-lock.json"]);
        assert_eq!(args(&["diff", "a", "b"]).command, "diff");
    }

    #[test]
    fn cli_rejects_unknown_short_flags() {
        assert!(parse_args(vec!["-Z".to_string()]).is_err());
    }

    #[test]
    fn cli_missing_value_is_an_error_not_a_panic() {
        assert!(parse_args(vec!["--fail-on".to_string()]).is_err());
    }

    #[test]
    fn severity_parsing_round_trips() {
        for s in ["critical", "high", "medium", "low", "info"] {
            let sev = Severity::from_str(s).unwrap();
            assert_eq!(sev.label().to_ascii_lowercase(), s);
        }
        assert!(Severity::from_str("catastrophic").is_none());
    }

    // -----------------------------------------------------------------
    // format detection + rendering
    // -----------------------------------------------------------------
    #[test]
    fn format_detection_uses_the_name_then_the_content() {
        assert_eq!(detect("package-lock.json", "{}", None).unwrap(), Ecosystem::Npm);
        assert_eq!(detect("Cargo.lock", "", None).unwrap(), Ecosystem::Crates);
        assert_eq!(detect("requirements.txt", "", None).unwrap(), Ecosystem::PyPI);
        // A renamed file, or stdin, must still be identified.
        assert_eq!(detect("-", "  {\"a\":1}", None).unwrap(), Ecosystem::Npm);
        assert_eq!(detect("-", "[[package]]\nname=\"x\"", None).unwrap(), Ecosystem::Crates);
        // An explicit override wins over both.
        assert_eq!(detect("package-lock.json", "{}", Some("cargo")).unwrap(), Ecosystem::Crates);
        assert!(detect("-", "", None).is_err());
    }

    #[test]
    fn commas_group_thousands() {
        assert_eq!(commas(0), "0");
        assert_eq!(commas(999), "999");
        assert_eq!(commas(1000), "1,000");
        assert_eq!(commas(1247), "1,247");
        assert_eq!(commas(1234567), "1,234,567");
    }

    #[test]
    fn wrap_text_never_exceeds_the_width() {
        let s = "the quick brown fox jumps over the lazy dog and keeps on going for a while";
        for line in render::wrap_text(s, 20, "").lines() {
            assert!(line.chars().count() <= 20, "line too long: {line:?}");
        }
    }

    #[test]
    fn styling_is_inert_when_disabled() {
        let off = render::Style { on: false };
        assert_eq!(off.red("x"), "x", "no escape codes when colour is off");
        let on = render::Style { on: true };
        assert!(on.red("x").contains("\x1b["));
    }

    #[test]
    fn bar_is_proportional_and_bounded() {
        assert_eq!(render::bar(0.0, 10), "..........");
        assert_eq!(render::bar(1.0, 10), "##########");
        assert_eq!(render::bar(0.5, 10), "#####.....");
        assert_eq!(render::bar(9.9, 4), "####", "out-of-range input must clamp");
    }
}
