---
title: Blocks and Inlines
subtitle: A checkpoint document for inkless
author: Sankalp
date: 2026-01-01
---

# Typesetting checkpoint

This page exists to prove that every block construct renders. The paragraph
you are reading is ordinary body text, long enough to wrap across several
lines so that greedy line breaking has something to do. It should never
touch either margin, and the spacing between lines should be even.

A second paragraph follows the first with a clear gap, not a blank line of
the same height as the text. Inline styles all appear here: **bold text**,
*italic text*, ***bold italic together***, `inline code`, a
[link to example.org](https://example.org), and an autolink
<https://www.python.org>. Nesting works too: **bold with *italic inside* and
`code inside` as well**.

## Headings at every level

### Level three

#### Level four

##### Level five

###### Level six

## Code blocks

Fenced code keeps its own spacing and is set in Courier on a panel:

```python
def measure(text: str, base_font: str, size: float) -> float:
    """Width of text set in a standard font, in points."""
    metrics = STANDARD_FONTS[base_font]
    total = 0
    for character in text:
        total += metrics.width_of_code(winansi_code(character))
    return total * size / 1000.0
```

An indented code block works the same way:

    xref
    0 7
    0000000000 65535 f
    0000000015 00000 n

A very long code line must wrap inside the panel rather than run off the
edge of the page:

```
this_is_a_single_extremely_long_line_of_code_with_no_spaces_in_it_at_all_which_must_be_broken_by_width_rather_than_allowed_to_overflow_the_right_margin
```

## Lists

Unordered, with nesting:

- First item at the top level
- Second item, which is long enough that it will wrap onto a second line and
  let you check that the continuation lines align with the text and not with
  the bullet
  - Nested item one
  - Nested item two
    - Third level, with a different marker
- Back to the top level

Ordered, respecting the start number:

3. This list starts at three
4. Because the first item said so
   1. A nested ordered list restarts
   2. As you would expect
5. And the outer numbering continues

A loose list, with blank lines between items:

- Loose item one

- Loose item two

## Blockquotes

> A blockquote is set with a rule down its left side and slightly muted
> text. This one is long enough to wrap, so you can confirm the rule runs
> the full height of the quote rather than marking only the first line.
>
> > A nested quote indents again and draws a second rule.
>
> Back to the outer level, after the nested one.

Quotes can hold other blocks:

> ### A heading inside a quote
>
> - and a list
> - with two items
>
> ```
> and a code block
> ```

## Thematic breaks

Above the rule.

---

Below the rule.

## Tables

| Construct | Supported | Notes |
|:----------|:---------:|------:|
| Headings | yes | levels 1 to 6 |
| Tables | yes | with alignment |
| Images | no | alt text only |
| Footnotes | no | out of scope |

A table with longer content, to check wrapping inside cells:

| Feature | Description |
|---|---|
| Line breaking | Greedy first fit, breaking on spaces, with a hard break for any single word wider than the column |
| Widow control | The last line of a paragraph is never left alone at the top of a page |
| Orphan control | The first line of a paragraph is never left alone at the bottom of a page |

## Escaping

Parentheses ( ) and backslashes \\ must survive into the PDF unchanged, as
must a lone ) and a lone ( on their own. Accented text such as naïve,
résumé, Zürich and Ångström uses WinAnsiEncoding, and £5.00 works too.

Escaped markup: \*not emphasis\*, \_not emphasis\_, \`not code\`, and
\[not a link\](x).

## Widows and orphans

The paragraphs below are deliberately placed near a page boundary. Whatever
happens, no page should end with a single opening line of a paragraph, and
no page should begin with a single closing line of one. A heading should
never be the last thing on a page either.

This paragraph is a filler paragraph whose only job is to push the following
content down the page so that the page boundary lands somewhere interesting.
It is long enough to wrap several times, which is exactly what is wanted for
testing where the break falls.

This is another filler paragraph with the same purpose. Read it or not, it
makes no difference to the test. What matters is where the page break lands
and what inkless does about it when the break would otherwise strand a line.

### A heading near the boundary

If this heading were the last thing on its page, the pagination would be
wrong. It should have pulled itself onto the next page along with at least
the first lines of this paragraph.
