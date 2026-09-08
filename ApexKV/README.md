# ApexKV

A lightweight, in-memory key-value store written in C++17. Features a generic hash table with separate chaining and a simple append-only log (WAL) for persistent storage.

## Features

- **Generic Types:** Templated `HashTable<Key, Value>` supporting standard hashable types (`std::string`, `int`, etc.).
- **Collision Handling:** Separate chaining using `std::forward_list` for minimal per-node overhead.
- **Dynamic Resizing:** Automatically doubles bucket capacity and rehashes entries once load factor exceeds `0.75`.
- **Append-Only Persistence:** `PersistentKV` logs write/delete operations to disk and replays state on startup.
- **Snapshot Support:** Optional snapshot creation to compact state and reduce log size.
- **Minimal Footprint:** Header-only core data structure with zero third-party dependencies.

## Architecture

ApexKV is organized around two small layers: an in-memory hash table for fast access and a persistence wrapper that records changes on disk.

1. **In-Memory Engine**
    `HashTable<Key, Value>` is a generic container for standard and custom hashable types. It uses separate chaining with `std::forward_list`, keeping collision handling simple while avoiding the extra pointer overhead of doubly linked nodes.

2. **Dynamic Rehashing**
    The table tracks its load factor (`size / capacity`) and automatically doubles its bucket count when the load factor exceeds `0.75` (`16 -> 32 -> ...`). Existing entries are redistributed using their hash values so lookups remain efficient as the data set grows.

3. **Simple CRUD Semantics**
    `put()` inserts or updates a value, `get()` returns a value, `contains()` checks for a key, and `remove()` erases it. Updates do not increase the element count, and removals use `forward_list::erase_after()` with an iterator to the preceding node.

4. **Write-Ahead Persistence**
    `PersistentKV` composes `HashTable<std::string, std::string>` with an append-only log. Each successful write or deletion updates memory and appends a `PUT` or `DEL` record, allowing the store to reconstruct its state by replaying the log after a restart.

5. **Snapshots for Compaction**
    A snapshot stores the current key-value state in a compact form. On startup, ApexKV loads the snapshot first and then replays newer log records, reducing recovery time and preventing the append-only log from growing indefinitely.

The result is a deliberately small design with predictable behavior: reads stay in memory, writes are durable through the log, and recovery uses deterministic replay.

## Usage

### In-Memory Hash Table

```cpp
#include "hash_table.hpp"
#include <iostream>

int main() {
    HashTable<std::string, int> scores;

    scores.put("Alice", 95);
    scores.put("Bob", 88);

    if (scores.contains("Alice")) {
        std::cout << "Alice: " << scores.get("Alice") << "\n";
    }

    scores.remove("Bob");
    std::cout << "Remaining: " << scores.getSize() << "\n";
}
```

### Persistent Key-Value Store

```cpp
#include "persistent_kv.hpp"
#include <iostream>

int main() {
    // Opens or creates 'data.log' and 'data.snapshot', recovers existing records
    PersistentKV db("data.log", "data.snapshot");

    db.put("session_id", "xyz123");
    db.put("theme", "dark");

    std::cout << "Theme: " << db.get("theme") << "\n";

    // Deletions append a DEL record to the log
    db.remove("session_id");

    // Optionally create a snapshot to compact state
    db.save_snapshot();
}
```

## How It Works

### Hash Table & Rehashing
- Buckets are stored in a dynamically allocated array of `std::forward_list<std::pair<Key, Value>>`.
- Key lookups hash the key via `std::hash<Key>{}(key) % capacity`.
- When `size / capacity > 0.75`, `rehash()` allocates a new table with 2× capacity and redistributes all existing elements.

### Log-Structured Persistence
`PersistentKV` wraps `HashTable<std::string, std::string>` with an append-only transaction log:

```text
PUT user_1 Alice
PUT session_timeout 3600
DEL session_timeout
```

- **Writes (`put` / `remove`):** Updates the in-memory hash table and appends a line to disk immediately.
- **Startup Recovery:** Opens the log file (and snapshot if present), reads line-by-line from top to bottom, and replays each `PUT` / `DEL` operation to reconstruct the in-memory state.
- **Snapshots:** `save_snapshot()` writes the current key-value pairs to a snapshot file; on next startup, the snapshot is loaded first, then newer log entries are replayed.

## Project Structure

```text
ApexKV/
├── include/
│   ├── hash_table.hpp      # Templated HashTable implementation
│   └── persistent_kv.hpp   # Persistent KV store wrapper with disk logging
├── src/
│   └── hash_table.cpp      # Translation unit for build systems
├── tests/
│   └── test_apexkv.cpp     # Unit tests covering table & persistence
├── main.cpp                # Demo entry point
├── CMakeLists.txt          # CMake build configuration
├── .gitignore
└── README.md
```

## Building & Testing

### Direct Compilation (g++)

```bash
# Build & run demo
g++ -std=c++17 -I include main.cpp -o apexkv.exe
./apexkv.exe

# Build & run test suite
g++ -std=c++17 -I include tests/test_apexkv.cpp -o test_apexkv.exe
./test_apexkv.exe

# Build & run benchmark
g++ -std=c++17 -I include tests/benchmark_apexkv.cpp -o benchmark_apexkv.exe
./benchmark_apexkv.exe
```

### Using CMake

```bash
cmake -S . -B build
cmake --build build

# Run tests
./build/test_apexkv.exe
```

## Test Suite

The test suite in `tests/test_apexkv.cpp` exercises:

- **Type Variations:** Validates `HashTable<int, std::string>`, `HashTable<std::string, int>`, and string-to-string mappings.
- **CRUD Operations:** In-place updates, `contains()` lookups, and removing existing/missing keys.
- **Dynamic Growth:** Bulk insertion (50+ keys) to ensure zero data loss across rehash boundaries.
- **Persistence Lifecycle:** Verifies state persistence across distinct `PersistentKV` instances and confirms log replay accuracy after deletions.

## Roadmap

- [x] Generic `HashTable<Key, Value>` template with `std::forward_list` chaining
- [x] Dynamic load factor tracking and 2× rehashing
- [x] Key removal with `erase_after` iterator tracking
- [x] Append-only WAL persistence and crash recovery
- [x] Snapshot support to compact state and reduce log size
- [x] Basic throughput benchmarks against `std::unordered_map`
- [ ] : TTL/expiry for keys('ll do later)
- [ ] : Thread-safe version with fine-grained
locking('ll do later)


## verification o/p :
# 86c4ed797b6033606985c18ec78829c1d0b74f1e7b50a65688d32cc5edea20a8 *build1.exe
# e2b64dfdfec85fb9be287c6fba900662053ee46c5235036a40d90a5a1205655a *build2.exe

