import select
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
        print(f">>> {http_request.method} {http_request.uri}")

        if http_request.method == "CONNECT":
            handle_connect(client_sock, http_request.uri)
            return
        else:
            # call non-connect handler here
            return


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
        key, value = header_line.split(":", 1)
        headers[key] = value

    return HttpRequest(method, uri, protocol, headers)


def handle_connect(client_sock, target) -> None:
    """Handle a CONNECT request
    
    Args:
        client_sock: The client socket connected to.
        target: The target host and port to connect to.
    """
    host, port = target.split(":", 1)
    
    remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        remote.connect((host, int(port)))

        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        # establish tunnel
        tunnel(client_sock, remote)
    except OSError as error:
        client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
    finally:
        client_sock.close()
        remote.close()

def tunnel(client_sock, remote) -> None:
    """Establish a tunnel between the client and the remote server.
    
    Args:
        client_sock: The client socket connected to.
        remote: The remote socket connected to.
    """
    sockets = [client_sock, remote]
    while True:
        readable, _, _ = select.select(sockets, [], [])

        for sock in readable:
            data = sock.recv(BUFFER_SIZE)

            if not data:
                return
            if sock is client_sock:
                remote.sendall(data)
            else:
                client_sock.sendall(data)

if __name__ == "__main__":
    run_tcp_server()
