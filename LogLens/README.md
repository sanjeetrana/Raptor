# 🔍 LogLens – Smart Log Analyzer

LogLens is a zero-dependency Python CLI tool that analyzes
application log files and generates a useful health report.

## 🚨 Problem

Large log files contain thousands of entries.
Developers need to manually search for errors and warnings,
which takes time.

## 💡 Solution

LogLens automatically analyzes logs and provides:

- Log level statistics
- Repeated error detection
- System health score
- Busiest log hours
- Smart diagnostic insights
- JSON report export

## ⚙️ Technologies

- Python 3
- Python Standard Library
- CLI

## 🚫 Zero Dependency

LogLens does not require any third-party Python packages.

No `pip install` is required.

## ▶️ Run

```bash
python loglens.py sample.log