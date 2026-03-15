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
    http_request = None

    while True:
        bytes_read = client_sock.recv(BUFFER_SIZE).decode()

        # Connection has been closed.
        if bytes_read == 0:
            return

        buffer += bytes_read

        # HTTP request is built and we need the body.
        if http_request:
            content_length = int(http_request.headers["Content-Length"])

            if len(buffer) < content_length:
                continue

            body, buffer = buffer[:content_length], buffer[content_length:]
            http_request = modify_http_request(http_request)
            forward_http_request(http_request, body)

            http_request = None

        else:
            # Request line + headers part of a HTTP request will end with \r\n\r\n.
            raw_request, separator, remaining = buffer.partition("\r\n\r\n")

            if not separator:
                continue

            buffer = remaining

            # TODO: Gracefully handle parsing failures, including requests
            # with no `Content-Length` headers.
            http_request = serialize_http_request(raw_request)


def forward_http_request(http_request: HttpRequest, body: str):
    """Forward a HTTP request to the server from the client.

    Args:
        http_request: The HTTP request.
        body: The body of the request.
    """
    pass


def modify_http_request(http_request: HttpRequest) -> HttpRequest:
    """Modify a HTTP request to the required format.

    Turn off `Keep-Alive` and lower the HTTP version.

    Args:
        http_request: The request to transform.
    """
    headers = http_request.headers

    if "Connection" in headers:
        headers["Connection"] = "close"

    if "Proxy-connection" in headers:
        headers["Proxy-connection"] = "close"

    http_request.protocol = "HTTP/1.0"

    return http_request


def serialize_http_request(raw_request: str) -> HttpRequest:
    """Transform a raw string to a `HttpRequest`.

    Args:
        raw_request: The raw string that contains the HTTP request.
    """
    lines = raw_request.splitlines()
    request_line, *header_lines = lines

    print(request_line)

    method, uri, protocol = request_line.split()

    headers = {}

    for header_line in header_lines:
        key, separator, value = header_line.partition(":")

        if separator:
            key = key.strip()
            value = value.strip()
            headers[key] = value

    return HttpRequest(method, uri, protocol, headers)


def deserialize_http_request(http_request: HttpRequest, body: str = "") -> str:
    """Transform a `HttpRequest` into string format.

    Args:
        http_request: The request object to transform.
        body: Optional body of the request.
    """

    return ""


if __name__ == "__main__":
    run_tcp_server()
