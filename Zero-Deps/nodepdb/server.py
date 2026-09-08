import socket

from nodepdb.protocol import parse_command, ProtocolError


HOST = "127.0.0.1"
PORT = 6380


def execute_command(storage, command, args):
    """Execute a parsed command against the storage engine."""

    if command == "PING":
        return "PONG"

    if command == "SET":
        storage.set(args[0], args[1])
        return "OK"

    if command == "GET":
        value = storage.get(args[0])

        if value is None:
            return "NOT_FOUND"

        return f"VALUE {value}"

    if command == "DEL":
        deleted = storage.delete(args[0])
        return "OK" if deleted else "NOT_FOUND"

    if command == "EXPIRE":
        success = storage.expire(args[0], args[1])
        return "OK" if success else "NOT_FOUND"

    if command == "EXISTS":
        exists = storage.exists(args[0])
        return "EXISTS" if exists else "NOT_FOUND"

    if command == "TTL":
        ttl = storage.ttl(args[0])

        if ttl is None:
            return "NOT_FOUND"

        return f"TTL {ttl}"

    if command == "KEYS":
        keys = storage.keys()

        if not keys:
            return "KEYS"

        return "KEYS " + " ".join(keys)

    if command == "FLUSH":
        storage.flush()
        return "OK"

    if command == "STATS":
        return "ERROR not_implemented"

    return "ERROR unknown_command"


def handle_client(conn, storage):
    """Handle one connected TCP client."""

    with conn:
        buffer = b""

        while True:
            data = conn.recv(4096)

            if not data:
                break

            buffer += data

            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)

                line = line.decode("utf-8").strip()

                if not line:
                    continue

                try:
                    command, args = parse_command(line)
                    response = execute_command(storage, command, args)
                    

                except ProtocolError as error:
                    response = f"ERROR {error}"

                except Exception:
                    response = "ERROR internal_error"

                conn.sendall((response + "\n").encode("utf-8"))


def start_server(storage):
    """Start the NoDepDB TCP server."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        server.bind((HOST, PORT))
        server.listen()

        print(f"NoDepDB server listening on {HOST}:{PORT}")

        while True:
            conn, address = server.accept()

            print(f"Client connected: {address}")

            handle_client(conn, storage)


if __name__ == "__main__":
    from storage_engine import StorageEngine

    storage = StorageEngine()
    start_server(storage)
            


    