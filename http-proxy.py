import socket
import sys
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit

# This constant is the number of bytes read from TCP stream in each iteration.
BUFFER_SIZE = 4096


@dataclass
class HttpRequest:
    """This type represents a HTTP request and contains its fields."""

    method: str
    uri: str
    protocol: str
    headers: dict[str, str]


def run_tcp_server():
    # maybe add base case to check the port from cli is valid
    port = int(sys.argv[1])

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("localhost", port))
    server_sock.listen()

    print(f"Listening to port: {port}")

    while True:
        client_sock, client_addr = server_sock.accept()

        thread = threading.Thread(
            target=handle_connection, args=(client_sock, client_addr)
        )
        thread.start()


def handle_connection(
    client_socket: socket.socket, client_addr: tuple[str, int]
) -> None:
    """Create a new TCP connection with the client.

    Invariant: One TCP connection per request-response.
        This means that all listen to request from client -> forward request
        to server -> listen to response from server -> forward response to
        client will all belong in this thread.

    Args:
        client_socket: The client socket connected to.
        client_addr: Address (IP, port) bound to the client socket.
    """
    buffer = ""
    http_request = None
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    while bytes_read := client_socket.recv(BUFFER_SIZE):
        buffer += bytes_read.decode()

        # HTTP request is built and we need the body.
        if http_request:
            content_length = int(http_request.headers["Content-Length"])

            # Right now we're buffering the entire body before sending it.
            if len(buffer) < content_length:
                continue

            # Forward body to server.
            body = buffer[:content_length].encode()
            server_socket.sendall(body)

            # Listen for response from server and forward to client.
            while data := server_socket.recv(BUFFER_SIZE):
                client_socket.sendall(data)

            # Spec says: You keep forwarding data in this way, in each direction, until you detect that the source has closed the connection.
            # Does this mean one TCP connection per request-responese???
            break

        else:
            # Request line + headers part of a HTTP request will end with \r\n\r\n.
            raw_request, separator, remaining = buffer.partition("\r\n\r\n")

            if not separator:
                continue

            buffer = remaining

            # TODO: Gracefully handle parsing failures, including requests
            # with no `Content-Length` headers.
            http_request = serialize_http_request(raw_request)

            # Modify request to send to server.
            address = get_address(http_request)
            modified_request = modify_http_request(http_request)
            raw_modified_request = deserialize_http_request(modified_request).encode()

            # Forward request to server without buffering the body.
            server_socket.connect(address)
            server_socket.sendall(raw_modified_request)

    client_socket.close()
    server_socket.close()


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

    print(f">>> {request_line}")

    method, uri, protocol = request_line.split()

    headers = {}

    for header_line in header_lines:
        key, separator, value = header_line.partition(":")

        if separator:
            key = key.strip()
            value = value.strip()
            headers[key] = value

    return HttpRequest(method, uri, protocol, headers)


def deserialize_http_request(http_request: HttpRequest) -> str:
    """Transform a `HttpRequest` into string format.

    Args:
        http_request: The request object to transform.
    """
    request_line = (
        f"{http_request.method} {http_request.uri} {http_request.protocol}\r\n"
    )
    headers = "\r\n".join(
        [f"{key}: {value}" for (key, value) in http_request.headers.items()]
    )

    return f"{request_line}{headers}\r\n"


def get_address(http_request: HttpRequest) -> tuple[str, int]:
    """Get the destination address (host, port) of a HTTP request.

    Args:
        http_request: A serialized HTTP request.
    """
    url_parts = urlsplit(http_request.uri)

    if url_parts.hostname:
        host = url_parts.hostname
        port = url_parts.port or (443 if url_parts.scheme == "https" else 80)
        return host, port

    host_header = http_request.headers["Host"]

    host, separator, raw_port = host_header.partition(":")
    port = int(raw_port) if separator else 80

    return host, port


if __name__ == "__main__":
    run_tcp_server()
