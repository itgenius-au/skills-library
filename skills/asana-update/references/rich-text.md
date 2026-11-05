# Asana rich text

Comments (`html_text`) and descriptions (`html_notes`) take the same small set
of tags. The body must be wrapped in `<body>...</body>`; the scripts do that
for you (`wrap_body()` in `scripts/_asana.py`).

| Works | Notes |
|---|---|
| `<strong>`, `<em>`, `<u>`, `<s>`, `<code>` | inline |
| `<a href="...">text</a>` | a link |
| `<a data-asana-gid="USER_GID"/>` | an @-mention; notifies that person |
| `<h1>`, `<h2>`, `<h3>` | headings |
| `<hr>` | a rule; the comment shape puts it between the summary and the details |
| `<ul>`, `<ol>`, `<li>` | lists, nested, with inline tags inside |
| `<blockquote>`, `<pre>` | blocks |
| `<table>`, `<tr>`, `<td>` | tables; use `<td><strong>` for a header row |

**Not supported:** `<p>`, `<br>`, `<th>`, `<img>`, `<div>`. On a comment, one
of them makes Asana store the WHOLE comment as escaped plain text (you see
`&lt;p&gt;`). On a description, Asana answers `400 XML is invalid`. The
scripts refuse these tags before they write.

- **Line breaks:** use real newlines, not `<br>`.
- **Escape plain text** with `html.escape(text, quote=False)`. Escape only
  `&`, `<` and `>`. Python's default `html.escape(text)` also turns `'` into
  `&#x27;`, and Asana shows that literally.
- **List whitespace:** newlines or indentation between `<li>` tags render as
  blank lines and large indents. `wrap_body()` removes that whitespace, or keep
  each list on one line: `<ul><li>a</li><li>b</li></ul>`.

## Example

```html
<strong>Status:</strong> the import is fixed and running again.
<hr>
<h3>What changed</h3>
<ul><li>Retry on HTTP 429 with the server's <code>Retry-After</code></li><li>Batch size 500 to 200</li></ul>
<table><tr><td><strong>Run</strong></td><td><strong>Rows</strong></td></tr><tr><td>Before</td><td>12,000 (failed at 4,100)</td></tr><tr><td>After</td><td>12,000</td></tr></table>
```
