import socket
import sys
import threading
from dataclasses import dataclass

# This constant is the number of bytes read from TCP stream in each iteration.
BUFFER_SIZE = 4096


@dataclass
class HttpRequest:
    """This type a HTTP request and contains its fields."""

    method: str
    uri: str
    protocol: str
    headers: dict[str, str]


def run_tcp_server():
    # maybe add base case to check the port from cli is valid
    port = int(sys.argv[1])

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("0.0.0.0", port))
    server_sock.listen()

    print(f"Listening to port: {port}")

    while True:
        client_sock, client_addr = server_sock.accept()

        thread = threading.Thread(
            target=handle_connection, args=(client_sock, client_addr)
        )
        thread.start()


def handle_connection(client_sock: socket.socket, client_addr: tuple[str, int]) -> None:
    """Create a new TCP connection with the client.

    Args:
        client_sock: The client socket connected to.
        client_addr: Address (IP, port) bound to the client socket.
    """
    buffer = ""

    while True:
        buffer += client_sock.recv(BUFFER_SIZE).decode()

        # Request line + headers part of a HTTP request will end with \r\n\r\n.
        parts = buffer.split("\r\n\r\n")

        # Continue reading from the TCP stream if request line + headers is
        # not fully formed.
        if len(parts) <= 1:
            continue

        http_request = parse_http_request(parts[0])


def parse_http_request(raw: str) -> HttpRequest:
    """Extracts the parts of a HTTP request from a raw string.

    Args:
        raw: The raw string that contains the HTTP request.
    """
    lines = raw.split("\r\n")
    request_line, header_lines = lines[0], lines[1:]

    method, uri, protocol = request_line.split()

    headers = {}
    for header_line in header_lines:
        key, value = header_line.split(":")
        headers[key] = value

    return HttpRequest(method, uri, protocol, headers)


if __name__ == "__main__":
    run_tcp_server()
