import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


APP_NAME = "LogLens"
VERSION = "2.0"

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

LOG_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})"
    r"\s+(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)"
    r"\s+(?P<message>.*)$",
    re.IGNORECASE
)


def normalize_error(message):
    """
    Convert changing values into common patterns.

    Example:
    Database failed for user 101
    Database failed for user 102

    becomes one common error pattern.
    """

    message = message.lower()

    # Remove numbers
    message = re.sub(r"\b\d+\b", "<number>", message)

    # Remove IDs
    message = re.sub(
        r"\b[a-f0-9]{8,}\b",
        "<id>",
        message
    )

    return message.strip()


def parse_log_file(filename):
    """
    Read and analyze a log file.
    """

    path = Path(filename)

    if not path.exists():
        raise FileNotFoundError(
            f"Log file '{filename}' was not found."
        )

    if not path.is_file():
        raise ValueError(
            f"'{filename}' is not a valid file."
        )

    lines = path.read_text(
        encoding="utf-8",
        errors="replace"
    ).splitlines()

    level_count = Counter()
    error_patterns = Counter()
    hour_count = Counter()

    timestamps = []

    parsed_lines = 0
    ignored_lines = 0

    for line in lines:

        match = LOG_PATTERN.match(line.strip())

        if not match:
            ignored_lines += 1
            continue

        parsed_lines += 1

        timestamp_text = match.group("timestamp")
        level = match.group("level").upper()
        message = match.group("message").strip()

        level_count[level] += 1

        # Timestamp analysis
        try:
            timestamp = datetime.strptime(
                timestamp_text,
                "%Y-%m-%d %H:%M:%S"
            )

            timestamps.append(timestamp)
            hour_count[timestamp.hour] += 1

        except ValueError:
            pass

        # Error pattern detection
        if level in ("ERROR", "CRITICAL"):

            pattern = normalize_error(message)

            if pattern:
                error_patterns[pattern] += 1

    return {
        "filename": str(path),
        "total_lines": len(lines),
        "parsed_lines": parsed_lines,
        "ignored_lines": ignored_lines,
        "levels": level_count,
        "errors": error_patterns,
        "hours": hour_count,
        "timestamps": timestamps
    }


def calculate_health_score(data):

    errors = (
        data["levels"]["ERROR"]
        + data["levels"]["CRITICAL"]
    )

    warnings = data["levels"]["WARNING"]

    score = 100

    score -= errors * 7
    score -= data["levels"]["CRITICAL"] * 12
    score -= warnings * 2

    return max(0, min(100, score))


def get_status(score):

    if score >= 85:
        return "HEALTHY"

    if score >= 65:
        return "STABLE WITH WARNINGS"

    if score >= 40:
        return "NEEDS ATTENTION"

    return "CRITICAL"


def generate_insights(data, score):

    insights = []

    errors = (
        data["levels"]["ERROR"]
        + data["levels"]["CRITICAL"]
    )

    warnings = data["levels"]["WARNING"]

    if errors == 0:
        insights.append(
            "No application errors detected."
        )
    elif errors >= 5:
        insights.append(
            "High error activity detected. "
            "Immediate investigation is recommended."
        )
    else:
        insights.append(
            "Application errors were detected."
        )

    if data["levels"]["CRITICAL"] > 0:
        insights.append(
            "Critical events require immediate attention."
        )

    if warnings >= 5:
        insights.append(
            "Frequent warnings indicate possible instability."
        )

    if data["ignored_lines"] > 0:
        insights.append(
            f"{data['ignored_lines']} lines could not be parsed."
        )

    if data["hours"]:
        busiest_hour, count = data["hours"].most_common(1)[0]

        insights.append(
            f"Peak activity occurred around "
            f"{busiest_hour:02d}:00 with {count} entries."
        )

    if score >= 85:
        insights.append(
            "Overall log health looks good."
        )

    return insights


def build_report(data):

    score = calculate_health_score(data)

    status = get_status(score)

    insights = generate_insights(
        data,
        score
    )

    timestamps = data["timestamps"]

    first_timestamp = None
    last_timestamp = None

    if timestamps:
        first_timestamp = min(timestamps).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        last_timestamp = max(timestamps).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    top_errors = []

    for message, count in data["errors"].most_common(5):

        top_errors.append({
            "message": message,
            "count": count
        })

    busiest_hours = []

    for hour, count in data["hours"].most_common(5):

        busiest_hours.append({
            "hour": f"{hour:02d}:00",
            "count": count
        })

    return {
        "application": APP_NAME,
        "version": VERSION,
        "file": data["filename"],
        "summary": {
            "total_lines": data["total_lines"],
            "parsed_lines": data["parsed_lines"],
            "ignored_lines": data["ignored_lines"]
        },
        "log_levels": dict(data["levels"]),
        "health": {
            "score": score,
            "status": status
        },
        "top_errors": top_errors,
        "busiest_hours": busiest_hours,
        "time_range": {
            "first": first_timestamp,
            "last": last_timestamp
        },
        "insights": insights
    }


def bar(value, maximum, width=25):

    if maximum == 0:
        return ""

    size = int(
        (value / maximum) * width
    )

    return "█" * size


def print_header():

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║          LOGLENS SMART ANALYZER              ║")
    print("║       Zero Dependency • Python CLI            ║")
    print("╚══════════════════════════════════════════════╝")
    print()


def print_report(report):

    print_header()

    print(f"📄 File       : {report['file']}")
    print(
        f"📊 Total Lines: "
        f"{report['summary']['total_lines']}"
    )

    print(
        f"🔎 Parsed     : "
        f"{report['summary']['parsed_lines']}"
    )

    print(
        f"⚠ Ignored     : "
        f"{report['summary']['ignored_lines']}"
    )

    print()
    print("━━━━━━━━━━━━━━ LOG HEALTH ━━━━━━━━━━━━━━")

    score = report["health"]["score"]
    status = report["health"]["status"]

    print(f"\n       {score}/100  —  {status}")

    print()
    print("━━━━━━━━━━━━━━ LOG LEVELS ━━━━━━━━━━━━━━")

    levels = report["log_levels"]

    maximum = max(
        levels.values()
    ) if levels else 0

    for level in LEVELS:

        count = levels.get(
            level,
            0
        )

        print(
            f"{level:<10} "
            f"{bar(count, maximum):<25} "
            f"{count}"
        )

    print()
    print("━━━━━━━━━━━━ TOP ERROR PATTERNS ━━━━━━━━━━━━")

    errors = report["top_errors"]

    if not errors:

        print("✓ No errors detected.")

    else:

        for index, item in enumerate(
            errors,
            start=1
        ):

            print(
                f"{index}. "
                f"[{item['count']}x] "
                f"{item['message']}"
            )

    print()
    print("━━━━━━━━━━━━━━ BUSIEST HOURS ━━━━━━━━━━━━━━")

    hours = report["busiest_hours"]

    if hours:

        for item in hours:

            print(
                f"{item['hour']}  →  "
                f"{item['count']} entries"
            )

    else:

        print("No timestamp information available.")

    print()
    print("━━━━━━━━━━━━━━ TIME RANGE ━━━━━━━━━━━━━━")

    print(
        f"First : "
        f"{report['time_range']['first'] or 'N/A'}"
    )

    print(
        f"Last  : "
        f"{report['time_range']['last'] or 'N/A'}"
    )

    print()
    print("━━━━━━━━━━━━━━ SMART INSIGHTS ━━━━━━━━━━━━━━")

    for insight in report["insights"]:

        print(f"• {insight}")

    print()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    print("✓ Analysis completed successfully.")
    print("✓ No third-party packages required.")

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()


def save_json(report, filename):

    path = Path(filename)

    path.write_text(
        json.dumps(
            report,
            indent=4
        ),
        encoding="utf-8"
    )

    print(
        f"\n✓ JSON report saved to: {filename}"
    )


def main():

    parser = argparse.ArgumentParser(
        prog="loglens",
        description=(
            "LogLens - Smart Log Analyzer "
            "(Zero Dependency)"
        )
    )

    parser.add_argument(
        "file",
        help="Path to the log file"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Display report as JSON"
    )

    parser.add_argument(
        "--save",
        metavar="FILE",
        help="Save report as JSON file"
    )

    args = parser.parse_args()

    try:

        data = parse_log_file(
            args.file
        )

        report = build_report(
            data
        )

        if args.save:

            save_json(
                report,
                args.save
            )

        if args.json:

            print(
                json.dumps(
                    report,
                    indent=4
                )
            )

        else:

            print_report(
                report
            )

    except FileNotFoundError as error:

        print(
            f"\n❌ {error}",
            file=sys.stderr
        )

        sys.exit(1)

    except ValueError as error:

        print(
            f"\n❌ {error}",
            file=sys.stderr
        )

        sys.exit(1)

    except OSError as error:

        print(
            f"\n❌ Unable to read file: {error}",
            file=sys.stderr
        )

        sys.exit(1)


if __name__ == "__main__":
    main()