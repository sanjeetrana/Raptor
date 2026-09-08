# NoDepDB

**NoDepDB** is a zero-dependency key-value database built for the **Unstop Zero Dependency Hackathon**. It demonstrates how a functional client-server database system can be built using only a programming language's standard library—without external packages, frameworks, or database libraries.

## Introduction

Modern applications often rely on many external dependencies for networking, storage, serialization, testing, and command-line interfaces. While useful, these dependencies can add installation complexity, compatibility issues, security concerns, and maintenance overhead.

NoDepDB takes a different approach: it provides a lightweight database experience using only built-in language capabilities. The project includes a TCP server, storage engine, network protocol, CLI client, interactive REPL, batch execution, and integration tests.

## Problem Statement

Build a functional database system without using any third-party packages. The system must support client-server communication, persistent or in-memory data storage, command parsing, error handling, and a usable command-line interface while maintaining strict standard-library-only compliance.

## Why Zero Dependency?

A zero-dependency project is easier to understand, run, audit, and distribute.

Benefits include:

- No package installation or dependency conflicts
- Smaller deployment footprint
- Reduced supply-chain risk
- Easier portability across environments
- Better understanding of core networking and storage concepts
- Faster onboarding for contributors and hackathon evaluators

NoDepDB intentionally focuses on fundamentals: sockets, files, parsing, command execution, and data structures.

## Project Goals

- Build a functional TCP-based key-value database.
- Use only standard library modules.
- Provide a simple text-based request/response protocol.
- Support a command-line client and interactive REPL.
- Allow batch command execution.
- Handle network failures with connection retries.
- Provide integration tests for end-to-end validation.
- Keep the architecture simple, modular, and beginner-friendly.

## System Architecture

```text
+-----------------------+
|      CLI Client       |
|-----------------------|
| Interactive REPL      |
| Batch Command Mode    |
+-----------+-----------+
            |
            | TCP Socket Connection
            | Text-Based Protocol
            v
+-----------+-----------+
|      NoDepDB Server   |
|-----------------------|
| Network Layer         |
| Protocol Parser       |
| Command Handler       |
+-----------+-----------+
            |
            v
+-----------+-----------+
|    Storage Engine     |
|-----------------------|
| In-Memory Key Store   |
| Optional Persistence  |
+-----------------------+
```

## Components Overview

### Storage Engine

The storage engine manages database records and implements core key-value operations.

Responsibilities include:

- Storing keys and values
- Retrieving values
- Deleting records
- Checking whether keys exist
- Listing keys
- Optionally persisting data to disk

The initial implementation can use an in-memory dictionary or map. If persistence is enabled, the storage engine may serialize data to a local file using standard library file and serialization utilities.

### Network Layer

The network layer enables communication between clients and the NoDepDB server through TCP sockets.

Responsibilities include:

- Binding the server to a host and port
- Accepting incoming client connections
- Reading client requests
- Sending server responses
- Handling connection failures gracefully
- Supporting configurable host and port values

### Protocol Layer

The protocol layer defines how clients and servers exchange commands and responses. NoDepDB uses a simple text-based command format:

```text
COMMAND argument1 argument2
```

Example:

```text
SET username alice
```

Responses are also text-based:

```text
OK
```

```text
VALUE alice
```

```text
ERROR key not found
```

This approach keeps the protocol easy to inspect, test, and extend.

### CLI Client

The CLI client connects to a NoDepDB server and sends commands.

It supports:

- Single-command execution
- Interactive REPL mode
- Batch command execution from a file
- Configurable host and port
- Connection retry behavior
- Clear success and error output

## Supported Commands

| Command | Description | Example |
|---|---|---|
| `SET key value` | Stores a value under a key | `SET name Alice` |
| `GET key` | Retrieves the value for a key | `GET name` |
| `DELETE key` | Removes a key and its value | `DELETE name` |
| `EXISTS key` | Checks whether a key exists | `EXISTS name` |
| `KEYS` | Lists all stored keys | `KEYS` |
| `PING` | Checks server availability | `PING` |

## Example Usage

Start the server:

```bash
python server.py
```

Start the client:

```bash
python client.py
```

Send a single command:

```bash
python client.py SET language Python
```

Expected response:

```text
OK
```

Retrieve the stored value:

```bash
python client.py GET language
```

Expected response:

```text
VALUE Python
```

Delete a key:

```bash
python client.py DELETE language
```

Expected response:

```text
OK
```

Check whether a key exists:

```bash
python client.py EXISTS language
```

Expected response:

```text
FALSE
```

## Interactive Mode

Interactive mode provides a REPL (Read-Eval-Print Loop) for entering multiple commands without reconnecting manually for every operation.

Start interactive mode:

```bash
python client.py --interactive
```

Example session:

```text
NoDepDB CLI connected to localhost:6379
Type HELP for available commands. Type EXIT to quit.

nodepdb> SET user alice
OK

nodepdb> GET user
VALUE alice

nodepdb> EXISTS user
TRUE

nodepdb> KEYS
user

nodepdb> EXIT
Disconnected.
```

## Batch Mode

Batch mode executes a series of database commands from a file.

Example command file, `commands.txt`:

```text
SET project NoDepDB
SET event Unstop Hackathon
GET project
KEYS
```

Run the batch file:

```bash
python client.py --file commands.txt
```

Example output:

```text
OK
OK
VALUE NoDepDB
event
project
```

## PING Command

`PING` verifies that the server is reachable and responding.

```bash
python client.py PING
```

Expected response:

```text
PONG
```

This command is useful for health checks, debugging, and connection validation.

## Testing Strategy

NoDepDB uses integration-focused testing to validate the complete system flow.

Tests should verify:

- Server startup and shutdown
- Client connection behavior
- Retry behavior during temporary connection failures
- `SET`, `GET`, `DELETE`, and `EXISTS` operations
- `KEYS` and `PING` responses
- Invalid command handling
- Batch command execution
- Protocol parsing
- Optional persistent-storage recovery after restart

Example integration flow:

```text
1. Start the NoDepDB server.
2. Connect a client.
3. Store a key using SET.
4. Retrieve it using GET.
5. Delete it using DELETE.
6. Verify removal using EXISTS.
7. Stop the server.
```

All tests are implemented with standard library testing tools only.

## Project Structure

```text
NoDepDB/
├── README.md
├── server.py
├── client.py
├── storage.py
├── protocol.py
├── config.py
├── tests/
│   ├── test_storage.py
│   ├── test_protocol.py
│   └── test_integration.py
├── data/
│   └── nodepdb.data
└── commands.txt
```

Suggested module responsibilities:

```text
server.py      Starts the TCP server and handles client sessions
client.py      Provides CLI, REPL, and batch execution modes
storage.py     Implements key-value storage and persistence
protocol.py    Parses commands and formats responses
config.py      Stores default host, port, and retry settings
tests/         Contains unit and integration tests
data/          Holds optional persistent database files
```

## Standard Library Compliance

NoDepDB is built with **only standard library modules**.

Typical built-in modules used may include:

```text
socket       TCP server and client communication
argparse     Command-line argument parsing
threading    Concurrent client handling
json         Optional data serialization
pathlib      File path management
os           Environment and filesystem utilities
time         Retry delays and timestamps
unittest     Testing framework
```

No external package manager, framework, ORM, networking library, or database library is required.

## Team Roles

Suggested team responsibilities:

| Role | Responsibilities |
|---|---|
| Storage Engineer | Key-value storage, deletion, key listing, persistence |
| Network Engineer | TCP server, socket communication, connection handling |
| Protocol Engineer | Command parsing, response formatting, validation |
| CLI Engineer | Command-line arguments, REPL, batch mode, retries |
| QA Engineer | Unit tests, integration tests, edge-case validation |
| Documentation Lead | README, architecture diagrams, usage examples |

In a small hackathon team, contributors may own multiple areas.

## Future Improvements

Potential future enhancements include:

- Durable write-ahead logging
- Improved persistence and recovery
- Namespaces or logical databases
- TTL and key expiration
- Authentication and access control
- Multi-threaded or asynchronous request handling
- Structured response formats
- Transaction support
- Backup and restore commands
- Benchmarking utilities
- Metrics and observability endpoints
- Client libraries for additional languages

## Conclusion

NoDepDB proves that a practical database system can be built from first principles using only the standard library. It combines networking, protocol design, storage management, command-line tooling, and testing into a focused learning project.

The project is intentionally simple, transparent, and dependency-free—making it ideal for demonstrating core systems-programming concepts in the Unstop Zero Dependency Hackathon.
