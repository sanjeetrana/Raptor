#!/usr/bin/env python3
import ast
import argparse
import json
import sys
import re
import tomllib
import importlib.util
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path


# ==========================================
# Data Models & Enums
# ==========================================

class DependencyKind(Enum):
    STDLIB = "stdlib"
    LOCAL = "local"
    THIRD_PARTY = "third-party"
    UNKNOWN = "unknown"

class Severity(Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

@dataclass
class ImportRecord:
    module: str
    source_file: Path
    line: int
    column: int
    imported_name: str | None
    kind: DependencyKind = DependencyKind.UNKNOWN

@dataclass
class Finding:
    severity: Severity
    title: str
    description: str
    file: Path | None = None
    line: int | None = None

@dataclass
class Project:
    root: Path
    python_files: list[Path] = field(default_factory=list)
    requirements_files: list[Path] = field(default_factory=list)
    pyproject_files: list[Path] = field(default_factory=list)
    declared_dependencies: set[str] = field(default_factory=set)
    used_dependencies: list[ImportRecord] = field(default_factory=list)
    local_module_names: set[str] = field(default_factory=set)

@dataclass
class AuditResult:
    project: Project
    findings: list[Finding] = field(default_factory=list)


# ==========================================
# The Project Scanner
# ==========================================

def scan_project(root_path: Path) -> Project:
    """Recursively walks a directory using pathlib to discover project files."""
    project = Project(root=root_path.resolve())
    ignored_dirs = {".git", "venv", ".venv", "__pycache__", "node_modules"}

    def _walk(current_dir: Path):
        try:
            for path in current_dir.iterdir():
                if path.is_dir():

                    if path.name not in ignored_dirs:  _walk(path)

                elif path.is_file():
                    if path.suffix == ".py":
                        project.python_files.append(path)

                        # Determine local module name (top-level directory or file)
                        if path.name == "__init__.py":
                            rel = current_dir.relative_to(project.root)

                            if rel.parts:
                                project.local_module_names.add(rel.parts[0])

                        else:
                            rel = path.relative_to(project.root)

                            if len(rel.parts) == 1:
                                project.local_module_names.add(path.stem)
                            else:
                                project.local_module_names.add(rel.parts[0])

                    elif path.name == "requirements.txt":
                        project.requirements_files.append(path)

                    elif path.name == "pyproject.toml":
                        project.pyproject_files.append(path)

        except PermissionError: pass

    if project.root.is_dir(): _walk(project.root)

    elif project.root.is_file() and project.root.suffix == ".py":
        project.python_files.append(project.root)
        project.local_module_names.add(project.root.stem)
        
    return project

# ==========================================
# The Parsers (The Fact Finders)
# ==========================================

def parse_requirements(path: Path) -> set[str]:
    """Parses requirements.txt, stripping versions and keeping base names."""

    deps = set()

    try:
        content = path.read_text(encoding="utf-8")

        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Extract base package name
            match = re.match(r'^([a-zA-Z0-9_\-]+)', line)

            if match:
                deps.add(match.group(1).lower().replace("-", "_"))

    except Exception: pass
    return deps

def parse_pyproject(path: Path) -> set[str]:
    """Parses pyproject.toml to extract project dependencies using tomllib."""

    deps = set()

    try:
        with open(path, "rb") as f:

            data = tomllib.load(f)
            project_data = data.get("project", {})
            dependencies = project_data.get("dependencies", [])

            for dep in dependencies:

                match = re.match(r'^([a-zA-Z0-9_\-]+)', dep)
                if match:
                    deps.add(match.group(1).lower().replace("-", "_"))

    except Exception: pass

    return deps

class SecurityNodeVisitor(ast.NodeVisitor):

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.imports: list[ImportRecord] = []
        self.security_findings: list[Finding] = []

    def visit_Import(self, node: ast.Import):

        """Collects AST Import nodes."""

        for alias in node.names:

            top_level = alias.name.split('.')[0]

            self.imports.append(ImportRecord(
                module=top_level,
                source_file=self.file_path,
                line=node.lineno,
                column=node.col_offset,
                imported_name=alias.name
            ))

        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Collects AST ImportFrom nodes."""

        if node.module:

            top_level = node.module.split('.')[0]

            for alias in node.names:
                self.imports.append(ImportRecord(
                    module=top_level,
                    source_file=self.file_path,
                    line=node.lineno,
                    column=node.col_offset,
                    imported_name=alias.name
                ))

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Flags security heuristics like eval(), exec(), pickle.loads(), and subprocess with shell=True."""

        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

            if isinstance(node.func.value, ast.Name):
                func_name = f"{node.func.value.id}.{func_name}"

        # 1. eval() and exec()
        if func_name in ("eval", "exec"):

            self.security_findings.append(Finding(
                severity=Severity.CRITICAL,
                title=f"Dangerous API use: {func_name}()",
                description=f"Avoid using {func_name}() as it can execute arbitrary code statically.",
                file=self.file_path,
                line=node.lineno
            ))
            
        # 2. pickle.loads()
        if "pickle" in func_name and "loads" in func_name or func_name == "loads":
            # Heuristic for pickle.loads
            if func_name in ("pickle.loads", "loads"):
                self.security_findings.append(Finding(
                    severity=Severity.HIGH,
                    title="Dangerous API use: pickle.loads()",
                    description="Unpickling untrusted data can lead to arbitrary code execution.",
                    file=self.file_path,
                    line=node.lineno
                ))
                
        # 3. subprocess calls with shell=True
        is_subprocess = "subprocess" in func_name or func_name in ("run", "Popen", "call", "check_call", "check_output")
        if is_subprocess:
            for keyword in node.keywords:
                if keyword.arg == "shell":
                    if isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                        self.security_findings.append(Finding(
                            severity=Severity.HIGH,
                            title="Dangerous API use: subprocess with shell=True",
                            description="Using shell=True can lead to shell injection vulnerabilities.",
                            file=self.file_path,
                            line=node.lineno
                        ))

        # 4. Dynamic Imports
        if func_name in ("__import__", "importlib.import_module"):
            self.security_findings.append(Finding(
                severity=Severity.MEDIUM,
                title=f"Dynamic Import: {func_name}()",
                description="Dynamic imports can hide dependencies from static analysis and are often used in malicious code.",
                file=self.file_path,
                line=node.lineno
            ))

        self.generic_visit(node)


def analyze_python_file(path: Path) -> tuple[list[ImportRecord], list[Finding]]:
    """Analyzes a Python file for imports and security heuristics using AST."""
    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(path))
        visitor = SecurityNodeVisitor(path)
        visitor.visit(tree)
        return visitor.imports, visitor.security_findings
    
    except SyntaxError:
        return [], []
    
    except Exception:
        return [], []


# ==========================================================
# The Intelligence Engine (Resolver & Drift)
# ==========================================================

def classify_import(module_name: str, local_modules: set[str]) -> DependencyKind:
    """Classifies an import into STDLIB, LOCAL, THIRD_PARTY, or UNKNOWN."""

    # 1. Standard Library
    if module_name in sys.stdlib_module_names:
        return DependencyKind.STDLIB
    
    # 2. Local Module
    if module_name in local_modules:
        return DependencyKind.LOCAL
    
    # 3. Installed Third-Party Module
    try:
        # Static check without executing target code
        spec = importlib.util.find_spec(module_name)
        if spec is not None:
            return DependencyKind.THIRD_PARTY
    except Exception:
        pass
    
    # 4. Unknown Module
    return DependencyKind.UNKNOWN

def analyze_project(project: Project) -> AuditResult:
    """The Drift Engine: Analyzes declared vs. used dependencies."""

    result = AuditResult(project=project)
    
    # Parse Manifests
    for req_file in project.requirements_files:
        project.declared_dependencies.update(parse_requirements(req_file))

    for toml_file in project.pyproject_files:
        project.declared_dependencies.update(parse_pyproject(toml_file))
        
    # Parse Python Files
    for py_file in project.python_files:
        imports, security_findings = analyze_python_file(py_file)
        project.used_dependencies.extend(imports)
        result.findings.extend(security_findings)
        
    # Classify Dependencies
    used_external = set()
    for imp in project.used_dependencies:
        imp.kind = classify_import(imp.module, project.local_module_names)
        
        if imp.kind == DependencyKind.UNKNOWN:
            result.findings.append(Finding(
                severity=Severity.MEDIUM,
                title="Unknown Dependency",
                description=f"Module '{imp.module}' is not identified as stdlib, local, or installed.",
                file=imp.source_file,
                line=imp.line
            ))

        elif imp.kind == DependencyKind.THIRD_PARTY:
            used_external.add(imp.module.lower().replace("-", "_"))

    # Drift Engine Execution
    declared = {d.lower().replace("-", "_") for d in project.declared_dependencies}
    
    # Undeclared: Used in code but missing from manifests
    undeclared = used_external - declared
    for dep in undeclared:
        # Find where it was imported
        record = next((imp for imp in project.used_dependencies if imp.module.lower().replace("-", "_") == dep), None)
        
        result.findings.append(Finding(
            severity=Severity.HIGH,
            title="Undeclared Dependency",
            description=f"Dependency '{dep}' is used but not declared in manifests.",
            file=record.source_file if record else None,
            line=record.line if record else None
        ))
        
    # Unused: Declared in manifests but not statically detected in code
    unused = declared - used_external
    for dep in unused:
        # Find which manifest declared it
        manifest_file = None
        for req_file in project.requirements_files:
            if dep in {d.lower().replace("-", "_") for d in parse_requirements(req_file)}:
                manifest_file = req_file
                break
        if not manifest_file:
            for toml_file in project.pyproject_files:
                if dep in {d.lower().replace("-", "_") for d in parse_pyproject(toml_file)}:
                    manifest_file = toml_file
                    break
                    
        result.findings.append(Finding(
            severity=Severity.INFO,
            title="Unused Dependency",
            description=f"Dependency '{dep}' is declared but not statically detected as used.",
            file=manifest_file,
            line=None
        ))

    return result


# ==========================================
# The Output Layer
# ==========================================

def format_json(result: AuditResult) -> str:
    """Formats the audit result as machine-readable JSON."""
    data = {
        "project_root": str(result.project.root),
        "files_scanned": len(result.project.python_files),
        "declared_dependencies": sorted(list(result.project.declared_dependencies)),
        "findings": [
            {
                "severity": f.severity.value,
                "title": f.title,
                "description": f.description,
                "file": str(f.file) if f.file else None,
                "line": f.line
            } for f in result.findings
        ]
    }
    return json.dumps(data, indent=2)

# ANSI escape codes
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"

def format_text(result: AuditResult) -> str:
    """Formats the audit result as human-readable text using raw ANSI colors."""
    out = []
    
    
    out.append(f"{BOLD}DepGuard Audit Report{RESET}")
    out.append(f"Project Root: {result.project.root}")
    out.append(f"Python Files Scanned: {len(result.project.python_files)}")
    out.append(f"Requirements Files: {len(result.project.requirements_files)}")
    out.append(f"Pyproject Files: {len(result.project.pyproject_files)}")
    out.append("")
    
    if not result.findings:
        out.append(f"{GREEN}{BOLD}✓ No issues found! Project dependencies are secure and properly declared.{RESET}")
        return "\n".join(out)
        
    out.append(f"{BOLD}Findings ({len(result.findings)}):{RESET}")
    out.append("-" * 60)
    
    # Sort findings by severity
    severity_order = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
        Severity.INFO: 4
    }

    sorted_findings = sorted(result.findings, key=lambda f: severity_order[f.severity])
    
    for finding in sorted_findings:
        color = RESET
        if finding.severity in (Severity.CRITICAL, Severity.HIGH):
            color = RED
        elif finding.severity == Severity.MEDIUM:
            color = YELLOW
        elif finding.severity == Severity.LOW:
            color = CYAN
        elif finding.severity == Severity.INFO:
            color = GREEN
            
        location = ""
        if finding.file:
            location = f"\n  Location: {finding.file}"
            if finding.line:
                location += f":{finding.line}"
                
        out.append(f"{color}[{finding.severity.value}]{RESET} {BOLD}{finding.title}{RESET}")
        out.append(f"  {finding.description}{location}")
        out.append("-" * 60)
        
    return "\n".join(out)


# ==========================================
# The CLI
# ==========================================

def main():
    """Main CLI entrypoint using argparse."""
    parser = argparse.ArgumentParser(
        description="DepGuard - A zero-dependency static auditor for Python projects.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")
    
    # 'scan' command
    scan_parser = subparsers.add_parser("scan", help="Scan a project and generate a report.")
    scan_parser.add_argument("path", type=str, help="Path to the project root directory")
    scan_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format (default: text)")
    
    # 'enforce' command
    enforce_parser = subparsers.add_parser("enforce", help="Scan a project and fail if THIRD_PARTY or UNKNOWN deps exist.")
    enforce_parser.add_argument("path", type=str, help="Path to the project root directory")
    
    args = parser.parse_args()
    target_path = Path(args.path)
    
    if not target_path.exists():
        print(f"Error: Target path '{args.path}' does not exist.", file=sys.stderr)
        sys.exit(1)
        
    project = scan_project(target_path)
    result = analyze_project(project)
    
    if args.command == "scan":
        if args.format == "json":
            print(format_json(result))
        else:
            print(format_text(result))
    elif args.command == "enforce":
        print(format_text(result))
        
        # Check for THIRD_PARTY or UNKNOWN dependencies
        violates = False
        for imp in result.project.used_dependencies:
            if imp.kind in (DependencyKind.THIRD_PARTY, DependencyKind.UNKNOWN):
                violates = True
                break
                
        if violates:
            print(f"\n{RED}{BOLD}Enforce failed: THIRD_PARTY or UNKNOWN dependencies detected.{RESET}")
            sys.exit(1)
        else:
            print(f"\n{GREEN}{BOLD}Enforce passed: No THIRD_PARTY or UNKNOWN dependencies detected.{RESET}")
            sys.exit(0)

if __name__ == "__main__":
    main()

