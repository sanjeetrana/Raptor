# RepoLens — Standard Library Usage & Zero-Dependency Substitutions

RepoLens is intentionally implemented without third-party runtime
dependencies.

The project uses only Node.js built-in modules and JavaScript language
features. This document explains which standard-library capabilities are
used, what common third-party packages they replace, and why those
substitutions were chosen.

---

## 1. Zero-Dependency Policy

RepoLens follows a strict zero-dependency design:

- No third-party runtime packages.
- No external JavaScript parsers.
- No framework dependency for the analysis engine.
- No visualization libraries.
- No CSS frameworks.
- No external fonts or CDN resources.
- No network access is required to analyze a repository or view the report.
- The analyzed repository is never executed.

The `package.json` intentionally contains no runtime dependencies.

RepoLens can therefore be used immediately with a compatible Node.js
installation without running:

```bash
npm install
```

---

# 2. Standard Library Modules Used

## `node:fs`

### Used for

Filesystem inspection and file operations.

### RepoLens usage

`fs` is used throughout the project for:

- Reading JavaScript source files.
- Recursively scanning directories.
- Checking whether files and directories exist.
- Reading file metadata.
- Creating temporary test fixtures.
- Writing generated HTML reports.
- Cleaning up temporary test files.

Examples of operations used include:

```javascript
fs.readdirSync()
fs.readFileSync()
fs.writeFileSync()
fs.existsSync()
fs.statSync()
fs.mkdirSync()
fs.rmSync()
```

### Replaces

Typical third-party alternatives would include:

- `glob`
- `fast-glob`
- filesystem abstraction packages

### Why standard library?

RepoLens only needs straightforward filesystem traversal and file
operations. Node's built-in `fs` module provides everything required
without adding another dependency.

---

# 3. `node:path`

### Used for

Cross-platform filesystem path manipulation.

### RepoLens usage

`path` is used for:

- Joining paths.
- Resolving absolute paths.
- Finding parent directories.
- Calculating paths relative to the project root.
- Normalizing Windows and POSIX path separators.

Examples:

```javascript
path.resolve()
path.dirname()
path.join()
path.relative()
```

RepoLens additionally normalizes reported paths to use `/` so that
generated reports are consistent across Windows and POSIX environments.

### Replaces

Typical alternatives include:

- `slash`
- `upath`
- path utility libraries

### Why standard library?

Node's `path` module already provides reliable platform-aware path
handling, so an additional path package would provide little value.

---

# 4. `node:assert`

### Used for

Zero-dependency automated testing.

### RepoLens usage

The test suites use Node's built-in assertion functionality to verify:

- Scanner behavior.
- Source-analysis results.
- Project statistics.
- Dependency resolution.
- Architecture analysis.
- Starting-file recommendations.
- Route extraction.
- Project-level integration.
- HTML report generation.

Examples include:

```javascript
assert.strictEqual()
assert.ok()
assert.deepStrictEqual()
```

### Replaces

Common third-party testing frameworks include:

- Jest
- Mocha
- Chai
- Vitest

### Why standard library?

RepoLens does not require a large testing framework for its deterministic
unit and integration tests. Node's built-in assertion API is sufficient
for the project's test requirements.

---

# 5. `node:child_process`

### Used for

Executing the individual test files from the master test runner.

### RepoLens usage

The project contains a master test runner that launches the individual
zero-dependency test suites sequentially.

This allows:

```bash
npm test
```

to execute the complete test collection.

### Replaces

A third-party task runner or test orchestration package could otherwise
be used to coordinate multiple test commands.

### Why standard library?

`child_process` provides the required process execution capability
without introducing an additional task-runner dependency.

---

# 6. JavaScript Regular Expressions

RepoLens does not use an external JavaScript parser or AST package.

Instead, selected static-analysis tasks use JavaScript's built-in
regular-expression engine.

### Used for

Regular expressions are used to identify patterns such as:

- `TODO`
- `FIXME`
- Function declarations.
- Arrow functions.
- Class declarations.
- ES module imports.
- ES module re-exports.
- CommonJS `require()` calls.
- Express-style HTTP routes.

Examples include patterns for:

```javascript
function example() {}

const example = () => {}

class User {}

import user from "./user.js";

const user = require("./user");

app.get("/users", handler);
```

### Replaces

A conventional implementation might use parser packages such as:

- Acorn
- Babel parser
- Esprima
- Espree

### Why standard library?

The project deliberately targets a lightweight static-analysis model.
Regular expressions allow RepoLens to inspect common JavaScript patterns
without downloading or installing a parser.

### Trade-off

This is intentionally not a complete JavaScript parser.

Regex-based analysis can miss or misinterpret unusual syntax, dynamically
constructed imports, or JavaScript structures outside the supported
patterns.

This limitation is accepted as part of RepoLens's zero-dependency design.

---

# 7. `String` and Template Literal APIs

### Used for

Generating the standalone HTML report.

RepoLens builds its HTML using JavaScript strings and template literals.

For example:

```javascript
const html = `
<!DOCTYPE html>
<html>
  ...
</html>
`;
```

### Replaces

A typical web application might use:

- EJS
- Handlebars
- Pug
- React
- other template engines

### Why standard library?

The report is generated from deterministic data and does not require a
full template engine.

JavaScript template literals are sufficient to construct the complete
HTML document.

---

# 8. Built-in HTML and CSS

RepoLens does not use a frontend framework or CSS framework for its
generated report.

### Used for

The report contains:

- Metric cards.
- Recommendation cards.
- Dependency information.
- Route tables.
- Status indicators.
- Progress meters.
- Collapsible raw JSON data.
- Responsive layout styling.

### Replaces

No external frontend packages are required.

Typical alternatives that were intentionally avoided include:

- React
- Vue
- Tailwind CSS
- Bootstrap
- Chart.js
- D3.js

### Why standard HTML/CSS?

The generated report is intended to be:

- Self-contained.
- Offline.
- Portable.
- Easy to inspect.
- Easy to open in any browser.

All styling is embedded directly inside the generated HTML file.

---

# 9. JSON Serialization

RepoLens uses JavaScript's built-in JSON functionality to represent and
serialize analysis results.

Examples:

```javascript
JSON.stringify()
JSON.parse()
```

### Used for

The JSON representation is used for:

- Project analysis results.
- Dependency graphs.
- Architecture metrics.
- Raw report data.
- Debugging and inspection.

The generated HTML report also exposes the complete report data through
a collapsible raw JSON section.

### Replaces

No external serialization library is required.

---

# 10. Custom Dependency Graph Instead of Graph Libraries

RepoLens implements its own dependency graph representation.

The graph is represented using ordinary JavaScript objects and arrays:

```javascript
{
  "src/project.js": [
    "src/analyzer.js",
    "src/statistics.js"
  ]
}
```

### Used for

The custom graph implementation supports:

- Dependency counts.
- Dependent counts.
- Entry-point detection.
- Leaf-module detection.
- Most-depended-on rankings.
- Circular dependency detection.

### Replaces

Third-party graph libraries such as:

- graphlib
- dependency graph packages
- graph visualization libraries

### Why custom implementation?

RepoLens only needs a relatively small directed graph representation.
A JavaScript object plus arrays is sufficient.

This keeps the implementation:

- Small.
- Transparent.
- Dependency-free.
- Easy to test.

---

# 11. Custom DFS Instead of a Graph Algorithm Package

Circular dependencies are detected using a custom
Depth-First Search (DFS) implementation.

The algorithm tracks:

- Visited nodes.
- The current recursion path.
- Back edges indicating cycles.

Detected cycles are then canonicalized so that the same cycle is not
reported multiple times merely because traversal started from a different
node.

For example:

```text
A -> B -> C -> A
```

and:

```text
B -> C -> A -> B
```

represent the same logical cycle and are reported once.

### Replaces

No external graph-algorithm package is required.

### Why custom DFS?

DFS is a well-understood algorithm and is straightforward to implement
using JavaScript arrays, objects, and sets.

---

# 12. `Set` and `Map`

RepoLens uses JavaScript's built-in collection types.

### `Set`

Used for:

- Deduplicating imports.
- Deduplicating dependencies.
- Deduplicating detected functions/classes.
- Avoiding duplicate cycles.

Example:

```javascript
const dependencies = new Set();
```

### `Map` / object-based maps

Used for:

- Dependency relationships.
- Count tracking.
- Architecture metrics.

### Replaces

No utility or collection library is required.

JavaScript's native `Set` and `Map` types provide the required
functionality directly.

---

# 13. No External Parser

One of the most important zero-dependency decisions in RepoLens is that
the analyzed JavaScript is never passed to an external parser.

Instead:

```text
JavaScript Source
       |
       v
Comment Stripping
       |
       v
Pattern Detection
       |
       v
Structured Analysis Result
```

This approach is used for:

- Functions.
- Classes.
- Imports.
- Requires.
- Routes.
- TODOs.
- FIXMEs.

The target source code is treated as data and is never executed.

---

# 14. No External Express Dependency

RepoLens can identify Express-style routes without installing Express.

For example:

```javascript
app.get("/users", userController.getUsers);
app.post("/users", userController.createUser);
app.delete("/users/:id", deleteUser);
```

RepoLens statically detects the method, path, and terminal handler.

### Replaces

A conventional approach could attempt to inspect a running Express
application or import the application's framework modules.

RepoLens intentionally does neither.

### Why?

The goal is static repository intelligence.

The analyzed project does not need to be installed, started, or executed.

---

# 15. No External Visualization Library

The dependency graph and architecture information are represented directly
in the generated HTML report using ordinary HTML and CSS.

### Replaces

Libraries such as:

- D3.js
- Chart.js
- Mermaid
- Cytoscape

### Why?

RepoLens primarily needs to communicate architectural relationships,
not provide a full interactive graph editor.

HTML/CSS cards provide a lightweight and completely offline representation.

---

# 16. No External Network Requests

The generated HTML report does not load:

- CDN scripts.
- CDN stylesheets.
- External fonts.
- Remote images.
- Analytics scripts.

Everything required to display the report is embedded in the generated
HTML file.

Therefore:

```text
Repository
    |
    v
RepoLens
    |
    v
repolens-report.html
    |
    v
Browser
```

works without an internet connection.

---

# 17. Dependency Substitution Summary

| Common third-party dependency | RepoLens standard-library solution |
|---|---|
| `glob` / `fast-glob` | `fs.readdirSync()` + recursive traversal |
| `slash` / `upath` | `node:path` + custom normalization |
| Acorn / Babel parser | JavaScript RegExp-based static analysis |
| Jest / Mocha / Chai | `node:assert` + custom test runner |
| Task runner | `node:child_process` |
| Express inspection | Static route pattern detection |
| Graph library | Objects, arrays, `Set`, and `Map` |
| Graph cycle library | Custom DFS |
| EJS / Pug / Handlebars | JavaScript template literals |
| React / Vue | Plain HTML |
| Tailwind / Bootstrap | Embedded CSS |
| D3 / Chart.js | Native HTML/CSS presentation |
| External JSON library | `JSON.stringify()` / `JSON.parse()` |

---

# 18. Why These Substitutions Were Chosen

The substitutions were not made only to reduce the number of entries in
`package.json`.

They support the core engineering goals of RepoLens:

### Portability

A compatible Node.js installation is enough to run the project.

### Transparency

The analysis algorithms are implemented directly in the repository
rather than hidden behind large dependencies.

### Offline operation

No package installation or network access is required to generate or
view the report.

### Security

RepoLens statically inspects source files rather than executing the
target repository.

### Maintainability

The individual analysis components are small and independently tested.

### Educational value

The implementation demonstrates how filesystem traversal, static pattern
matching, graph analysis, ranking, route detection, and HTML generation
can be built using the Node.js standard library.

---

# 19. Intentional Trade-offs

Zero dependency does not mean zero trade-offs.

RepoLens intentionally accepts some limitations:

- Regex-based JavaScript analysis is not equivalent to a full AST parser.
- Dynamic imports cannot always be resolved.
- Dynamically constructed `require()` calls are ignored.
- Custom path aliases are not resolved.
- Route detection targets common Express-style syntax.
- Complex JavaScript syntax outside supported patterns may not be detected.
- The generated dependency map represents statically resolvable local
  dependencies rather than the complete runtime dependency behavior.

These limitations are preferable to introducing third-party packages
because the primary goal of RepoLens is transparent, portable,
zero-dependency repository intelligence.

---

# 20. Final Dependency Statement

RepoLens is implemented using Node.js standard-library capabilities and
native JavaScript features.

The core project requires no third-party runtime packages.

The resulting tool can:

```text
Scan a repository
       ↓
Analyze source files
       ↓
Calculate statistics
       ↓
Build dependency graphs
       ↓
Analyze architecture
       ↓
Recommend starting files
       ↓
Discover Express-style routes
       ↓
Generate an offline HTML report
```

without installing a third-party runtime dependency.

This is the central engineering principle of RepoLens:

> **Use the platform first. Add a dependency only when the standard
> library cannot reasonably provide the required capability.**
