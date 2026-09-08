# RepoLens


**Track A — Developer Tools & CLI**

RepoLens is a zero-dependency developer tool designed to reduce the
time required to understand an unfamiliar JavaScript or Node.js
repository.

**Zero-Dependency Repository Intelligence & Architecture Analysis**

> Understand an unfamiliar JavaScript codebase before reading thousands of lines of code.

RepoLens statically inspects JavaScript and Node.js codebases to produce transparent architectural insights, dependency graphs, Express route maps, and prioritized starting recommendations—all compiled into a self-contained, offline HTML intelligence report without executing target code.

* **Zero external runtime dependencies** — Built exclusively with standard Node.js built-ins.
* **Static analysis only** — Never evaluates or executes analyzed repository code.
* **Offline HTML report** — Clean, self-contained report with zero external CDN dependencies.
* **Architecture & cycles** — Identifies entry points, leaf modules, dependent rankings, and circular imports.
* **Route discovery** — Statically extracts Express HTTP methods, paths, and handlers.
* **"Where Should I Start?"** — Transparent, deterministic scoring engine to guide developer onboarding.

---

## The Problem

When developers join a new team or explore an unfamiliar open-source repository, they face common onboarding challenges:

* **Where should I start reading?** Which files contain core entry points versus leaf utilities?
* **What is the system architecture?** How do modules connect, and what is the dependency flow?
* **Are there hidden circular dependencies?** Which modules might cause unexpected import cycles?
* **Which modules are critical?** Which files have the highest number of incoming dependents?
* **What API endpoints exist?** What routes and handlers are exposed across the codebase?
* **Where are code signals concentrated?** Where are `TODO` and `FIXME` technical debts located?

Traditionally, developers answer these questions by manually reading thousands of lines of code, clicking through folder hierarchies, and searching string patterns across disparate files.

---

## The Solution

RepoLens provides an automated, zero-dependency static analysis pipeline that extracts structure directly from source files without running untrusted code:

```text
Target Repository
       ↓
Recursive Scanner (src/scanner.js)
       ↓
Source Analyzer (src/analyzer.js)
       ↓
Statistics Engine (src/statistics.js)
       ↓
Dependency Graph (src/dependencies.js)
       ↓
Architecture Analysis (src/architecture.js)
       ↓
"Where Should I Start?" (src/start.js)
       ↓
Route Map (src/routes.js)
       ↓
Unified Pipeline (src/project.js)
       ↓
Static HTML Report (src/report.js)
```

---

## Key Features

| Feature | What it does |
| :--- | :--- |
| **Recursive File Scanner** | Traverses project directories to discover `.js` files while ignoring noisy directories like `node_modules` and `.git`. |
| **JavaScript Source Analyzer** | Extracts total lines, blank lines, function declarations, class declarations, and case-insensitive `TODO`/`FIXME` counts. |
| **Project Statistics** | Aggregates project-level metrics and identifies the largest file in the codebase. |
| **Static Dependency Analysis** | Discovers relative ES module imports and CommonJS `require()` statements, resolving extensions (`.js`) and folder index files. |
| **Architecture Engine** | Maps in-degree/out-degree counts, identifies entry points, leaf modules, most-depended-on files, and detects circular import cycles. |
| **"Where Should I Start?"** | Ranks critical files using a deterministic scoring formula with human-readable rationale. |
| **Static Route Map** | Statically detects Express-style HTTP routes (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`) and extracts terminal handlers. |
| **Standalone HTML Report** | Generates a single self-contained, light-themed HTML report with zero external CDN dependencies. |

---

### Feature Details

#### 1. Recursive File Scanner (`src/scanner.js`)
* Recursively walks directory trees using standard `fs.readdirSync` with `{ withFileTypes: true }`.
* Filters for JavaScript source files (`.js`).
* Automatically ignores common non-application directories (`node_modules`, `.git`, `dist`, `build`, `coverage`, `.next`).
* Normalizes all file paths with forward slashes (`/`) for cross-platform consistency.

#### 2. JavaScript Source Analyzer (`src/analyzer.js`)
* Computes total line count and blank line count.
* Performs case-insensitive matching for `TODO` and `FIXME` comments.
* Strips block and line comments prior to identifier extraction to avoid false positives.
* Extracts standard function declarations (`function name()`, `async function name()`), arrow functions (`const name = () => {}`), and expressions (`const name = function() {}`).
* Extracts class declarations (`class User`, `class Admin extends User`).

#### 3. Project Statistics (`src/statistics.js`)
* Aggregates individual file reports into project-wide metrics: `totalFiles`, `totalLines`, `totalBlankLines`, `totalFunctions`, `totalClasses`, `totalTodos`, and `totalFixmes`.
* Identifies the `largestFile` by line count.

#### 4. Dependency Analysis (`src/dependencies.js`)
* Detects static relative imports (`./` and `../`) across both ES Modules (`import ... from '...'`) and CommonJS (`require('...')`).
* Resolves extension-less imports (e.g., `require('./user')` $\rightarrow$ `user.js`) and directory indexes (e.g., `require('./models')` $\rightarrow$ `models/index.js`).
* Ignores external packages (`express`, `lodash`, etc.) and dynamic runtime requires (`require(variable)`).
* Deduplicates multiple imports between the same files.

#### 5. Architecture Analysis (`src/architecture.js`)
* Calculates `dependencyCounts` (out-degree) and `dependentCounts` (in-degree) for each file.
* Identifies **Application Entry Points** (files with 0 dependents, excluding test suites).
* Identifies **Leaf Modules** (files that import 0 local modules).
* Ranks **Most Depended On** files to highlight critical foundation modules.
* Detects **Circular Dependencies** using Depth-First Search (DFS) with canonical cycle rotation to prevent duplicate cycle reports.

#### 6. "Where Should I Start?" Recommendation Engine (`src/start.js`)
* Calculates a transparent, deterministic score for every candidate file:
  $$\text{Score} = (\text{dependents} \times 5) + (\text{isEntryPoint} \mathrel{?} 20 : 0) + (\text{functions} \times 2) + (\text{classes} \times 3) + (\text{todos} \times 2) + (\text{fixmes} \times 3) + \left(\frac{\text{lines}}{100}\right)$$
* Generates contextual human-readable reasons (e.g., `"Entry point"`, `"Used by 5 files"`, `"Contains 6 functions"`).
* Sorts recommendations by score descending with deterministic alphabetical tie-breaking.

#### 7. Static Route Map (`src/routes.js`)
* Statically detects Express route invocations on common receiver variables (`app`, `router`, `api`, `userRouter`).
* Supports standard HTTP verbs: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`.
* Captures route parameter patterns (e.g., `/users/:id`, `/posts/:postId/comments/:commentId`).
* Resolves terminal controller handlers through middleware chains (e.g., `app.get('/users', auth, validate, userController.getUsers)` $\rightarrow$ `userController.getUsers`).
* Identifies inline arrow/function callbacks as `"anonymous"`.

#### 8. Standalone HTML Report (`src/report.js`)
* Generates a self-contained single-file HTML report.
* Light developer theme with card layouts, method badges, progress meters, and collapsible raw JSON inspection.
* Operates fully offline with zero external network requests or CDN dependencies.

---

## Why Zero Dependency?

RepoLens was built strictly for the **Zero Dependency Hackathon** following a deliberate engineering philosophy:

* **Zero Third-Party Packages**: `package.json` contains an empty `dependencies: {}` object. No Express, React, Babel, Acorn, D3, Chart.js, or Tailwind.
* **Standard Library Only**: Uses Node.js built-in modules (`fs`, `path`, `child_process` for test running).
* **Safe Static Inspection**: Never executes the analyzed target code, avoiding runtime execution hazards and untrusted code execution.
* **Instant Portability**: Works immediately with standard Node.js without requiring `npm install`.
* **Complete Offline Capability**: Generates self-contained HTML reports that can be viewed without internet connectivity.

---

## Technical Architecture

```text
                      ┌────────────────────────┐
                      │   Target Repository    │
                      └───────────┬────────────┘
                                  │
                                  v
                      ┌────────────────────────┐
                      │      File Scanner      │
                      │     src/scanner.js     │
                      └───────────┬────────────┘
                                  │ File Paths
                                  v
                      ┌────────────────────────┐
                      │    Source Analyzer     │
                      │    src/analyzer.js     │
                      └───────────┬────────────┘
                                  │ File Reports
                   ┌──────────────┴──────────────┐
                   │                             │
                   v                             v
       ┌────────────────────────┐   ┌────────────────────────┐
       │   Statistics Engine    │   │   Dependency Engine    │
       │   src/statistics.js    │   │  src/dependencies.js   │
       └───────────┬────────────┘   └────────────┬───────────┘
                   │                             │ Dependency Graph
                   │                             v
                   │                ┌────────────────────────┐
                   │                │  Architecture Engine   │
                   │                │  src/architecture.js   │
                   │                └────────────┬───────────┘
                   │                             │
                   │                 ┌───────────┴───────────┐
                   │                 │                       │
                   │                 v                       v
                   │    ┌────────────────────────┐ ┌───────────────────┐
                   │    │  Start Recommendations │ │     Route Map     │
                   │    │      src/start.js      │ │   src/routes.js   │
                   │    └────────────┬───────────┘ └─────────┬─────────┘
                   │                 │                       │
                   └─────────────────┼───────────────────────┘
                                     │
                                     v
                        ┌────────────────────────┐
                        │  Unified Project API   │
                        │     src/project.js     │
                        └────────────┬───────────┘
                                     │ JSON Report
                                     v
                        ┌────────────────────────┐
                        │   Static HTML Report   │
                        │     src/report.js      │
                        └────────────────────────┘
```

---

## Project Structure

```text
RepoLens/
├── src/
│   ├── scanner.js          # Recursive directory file scanner
│   ├── analyzer.js         # Source code metrics, function & class parser
│   ├── statistics.js       # Project-wide metrics aggregator
│   ├── dependencies.js     # Static import & require dependency parser
│   ├── architecture.js     # Graph metrics, entry points, leaves & cycle detection
│   ├── start.js            # "Where Should I Start?" scoring & recommendation engine
│   ├── routes.js           # Static Express HTTP route detector
│   ├── project.js          # Unified pipeline orchestration API
│   └── report.js           # Self-contained HTML report generator
├── test/
│   ├── run-all-tests.js    # Master test suite runner
│   ├── test-scanner.js     # Tests for file scanner
│   ├── test-analyzer.js    # Tests for source code analyzer
│   ├── test-statistics.js  # Tests for statistics engine
│   ├── test-dependencies.js# Tests for dependency parser & resolver
│   ├── test-architecture.js# Tests for graph metrics & cycle detection
│   ├── test-start.js       # Tests for starting file recommendations
│   ├── test-routes.js      # Tests for static route extraction
│   ├── test-project.js     # Tests for unified project pipeline
│   └── test-report.js      # Tests for HTML report generator
├── example.js              # Live end-to-end pipeline demonstration script
├── generate-report.js      # CLI script to generate repolens-report.html
├── repolens-report.html    # Standalone HTML report generated by RepoLens
├── package.json            # Project manifest with zero dependencies
└── README.md               # Project documentation
```

### Module Responsibilities

* **[`src/scanner.js`](src/scanner.js)**: Discovers project `.js` files and filters out ignored directories.
* **[`src/analyzer.js`](src/analyzer.js)**: Parses line counts, blank lines, TODOs/FIXMEs, functions, and classes.
* **[`src/statistics.js`](src/statistics.js)**: Computes project-level totals and tracks the largest file.
* **[`src/dependencies.js`](src/dependencies.js)**: Statically extracts relative imports and resolves local file paths.
* **[`src/architecture.js`](src/architecture.js)**: Analyzes module graph topology, entry points, and detects dependency cycles.
* **[`src/start.js`](src/start.js)**: Scores and ranks optimal files for codebase onboarding.
* **[`src/routes.js`](src/routes.js)**: Extracts Express HTTP routes and maps terminal controller handlers.
* **[`src/project.js`](src/project.js)**: Orchestrates all analysis components into a single JSON report object.
* **[`src/report.js`](src/report.js)**: Generates self-contained, light-themed HTML reports.

---

## How to Run

### Prerequisites

* **Node.js**: Node.js 24 LTS or Node.js 26
* **Zero installations needed**: No `npm install` is required because RepoLens has no dependencies.

---

### 1. Run the Full Test Suite

Executes all 9 unit and integration test suites sequentially:

```bash
npm test
```

You can also run individual test suites:

```bash
npm run test:scanner
npm run test:analyzer
npm run test:statistics
npm run test:dependencies
npm run test:architecture
npm run test:start
npm run test:routes
npm run test:project
npm run test:report
```

---

### 2. Generate the Static HTML Report

Analyzes the repository and generates a standalone `repolens-report.html` in the project root:

```bash
npm run report
```

Open `repolens-report.html` directly in any web browser to view the interactive intelligence report.

---

### 3. Run the Terminal Demo Pipeline

Executes the complete analysis pipeline on the current repository and prints overview metrics, architecture details, recommendations, and route maps to the console:

```bash
npm start
```

---

## Programmatic API Usage

RepoLens can be imported as a module in any Node.js application:

```javascript
const { analyzeProject } = require('./src/project');
const { writeHtmlReport } = require('./src/report');

// 1. Analyze target repository
const report = analyzeProject('/path/to/target/project');

console.log(`Files Scanned: ${report.project.fileCount}`);
console.log(`Total Lines: ${report.statistics.totalLines}`);
console.log(`Top Recommendation: ${report.recommendations[0].path}`);

// 2. Export standalone HTML report
writeHtmlReport(report, './output-report.html');
```

---

## License

MIT
