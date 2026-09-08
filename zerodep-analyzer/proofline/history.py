import sqlite3
import datetime
from pathlib import Path
from proofline.rules_engine import RulesReport, Severity
from proofline.evidence_graph import EvidenceGraph

def _get_db_path(repo_root: str) -> Path:
    dot_proofline = Path(repo_root) / ".proofline"
    dot_proofline.mkdir(exist_ok=True)
    return dot_proofline / "history.db"

def init_db(repo_root: str, memory_db: str = None):
    db_path = memory_db if memory_db else str(_get_db_path(repo_root))
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            commit_hash TEXT,
            author TEXT,
            message TEXT,
            overall_severity TEXT,
            rules_fired_count INTEGER,
            total_symbols_changed INTEGER
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS rule_hits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            history_id INTEGER,
            rule_name TEXT,
            severity TEXT,
            FOREIGN KEY(history_id) REFERENCES history(id)
        )
    ''')
    conn.commit()
    conn.close()

def save_analysis(repo_root: str, commit_info: dict, rules_report: RulesReport, eg: EvidenceGraph, memory_db: str = None):
    db_path = memory_db if memory_db else str(_get_db_path(repo_root))
    init_db(repo_root, memory_db)
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    commit_hash = commit_info.get("hash", "unknown")
    author = commit_info.get("author", "unknown")
    message = commit_info.get("message", "")
    overall_severity = rules_report.overall_severity.name
    rules_fired_count = len(rules_report.fired_rules)
    
    total_symbols_changed = len(eg.nodes())
    
    c.execute('''
        INSERT INTO history (timestamp, commit_hash, author, message, overall_severity, rules_fired_count, total_symbols_changed)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (timestamp, commit_hash, author, message, overall_severity, rules_fired_count, total_symbols_changed))
    
    history_id = c.lastrowid
    
    for rule in rules_report.fired_rules:
        c.execute('''
            INSERT INTO rule_hits (history_id, rule_name, severity)
            VALUES (?, ?, ?)
        ''', (history_id, rule.rule_name, getattr(rule.severity, 'name', str(rule.severity))))
        
    conn.commit()
    conn.close()

def get_history(repo_root: str, limit: int = 50, memory_db: str = None) -> list[dict]:
    db_path = memory_db if memory_db else str(_get_db_path(repo_root))
    if db_path != ":memory:" and not Path(db_path).exists():
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    try:
        c.execute("""
            SELECT id, timestamp, commit_hash, author, message, overall_severity, rules_fired_count, total_symbols_changed
            FROM history
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        rows = c.fetchall()
        result = [dict(row) for row in rows]
    except sqlite3.OperationalError:
        result = []
    finally:
        conn.close()

    # Reverse to return chronological order for plotting
    return list(reversed(result))
