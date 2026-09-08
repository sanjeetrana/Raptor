

```markdown
# 📚 Standard Library Usage

LogLens uses only Python's built-in Standard Library.

No external packages are required.

## Modules Used

### argparse
Used to create the command-line interface and command options.

### re
Used for detecting log patterns and normalizing error messages.

### collections
`Counter` is used to count log levels, errors and activity.

### pathlib
Used for reading and writing files.

### datetime
Used for processing log timestamps.

### json
Used to generate machine-readable JSON reports.

### sys
Used for error handling and program exit codes.

## Dependency Policy

This project intentionally has:

- No third-party libraries
- No pip installation
- No runtime dependencies
- Empty requirements.txt

The project can run directly with Python 3.