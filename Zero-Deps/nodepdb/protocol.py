class ProtocolError(Exception):
    """Raised when a client sends an invalid command."""
    pass


def parse_command(line):
    """
    Parse one line received from a NoDepDB client.

    Returns:
        tuple: (command, arguments)
    """

    line = line.strip()

    if not line:
        raise ProtocolError("empty_command")

    parts = line.split()
    command = parts[0].upper()
    args = parts[1:]

    if command == "PING":
        if args:
            raise ProtocolError("invalid_arguments")
        return command, args

    if command == "SET":
        if len(args) != 2:
            raise ProtocolError("invalid_arguments")
        return command, args

    if command == "GET":
        if len(args) != 1:
            raise ProtocolError("invalid_arguments")
        return command, args

    if command == "DEL":
        if len(args) != 1:
            raise ProtocolError("invalid_arguments")
        return command, args

    if command == "EXPIRE":
        if len(args) != 2:
            raise ProtocolError("invalid_arguments")

        try:
            seconds = int(args[1])
        except ValueError:
            raise ProtocolError("invalid_expiry")

        if seconds < 0:
            raise ProtocolError("invalid_expiry")

        return command, [args[0], seconds]

    if command == "KEYS":
        if args:
            raise ProtocolError("invalid_arguments")
        return command, args

    if command == "EXISTS":
        if len(args) != 1:
            raise ProtocolError("invalid_arguments")
        return command, args

    if command == "TTL":
        if len(args) != 1:
            raise ProtocolError("invalid_arguments")
        return command, args

    if command == "FLUSH":
        if args:
            raise ProtocolError("invalid_arguments")
        return command, args
    
    if command == "STATS":
        if args:
            raise ProtocolError("invalid_arguments")
        return command, args

    raise ProtocolError("unknown_command")