import socket

HOST = "127.0.0.1"
PORT = 6380

def main():
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect((HOST, PORT))

        print("Connected to NoDepDB")
        print("Type EXIT to quit")

        while True:
            command = input("> ")

            if command.upper() == "EXIT":
                break

            client.sendall((command + "\n").encode())

            response = client.recv(4096).decode()
            print(response)

        client.close()

    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    main()
