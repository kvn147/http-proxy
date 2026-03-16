import select
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
    if len(sys.argv) != 2:
        print("Usage: python proxy.py <port>")
        sys.exit(1)

    port = int(sys.argv[1])

    if not 0 <= port <= 65535:
        print("Port must be between 0 and 65535")
        sys.exit(1)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("localhost", port))
    server_socket.listen()

    try:
        while True:
            client_sock, client_addr = server_socket.accept()

            thread = threading.Thread(
                target=handle_connection, args=(client_sock, client_addr)
            )
            thread.start()
    finally:
        server_socket.close()


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
    buffer = b""
    http_request = None
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        while bytes_read := client_socket.recv(BUFFER_SIZE):
            buffer += bytes_read

            # HTTP request is built and we need the body.
            if http_request:
                content_length = int(http_request.headers.get("content-length", 0))

                # Right now we're buffering the entire body before sending it.
                if len(buffer) < content_length:
                    continue

                # Forward body to server.
                body = buffer[:content_length]
                server_socket.sendall(body)

                # Listen for response from server and forward to client.
                while data := server_socket.recv(BUFFER_SIZE):
                    client_socket.sendall(data)

                # Spec says: You keep forwarding data in this way, in each direction, until you detect that the source has closed the connection.
                # Does this mean one TCP connection per request-responese???
                break

            else:
                # Request line + headers part of a HTTP request will end with \r\n\r\n.
                raw_request, separator, remaining = buffer.partition(b"\r\n\r\n")

                if not separator:
                    continue

                buffer = remaining

                # TODO: Gracefully handle parsing failures, including requests
                # with no `Content-Length` headers.
                http_request = deserialize_http_request(raw_request.decode())

                if http_request.method == "CONNECT":
                    handle_connect(client_socket, http_request.uri)
                    return
                
                # Modify request to send to server.
                address = get_address(http_request)
                modified_request = modify_http_request(http_request)
                raw_modified_request = seserialize_http_request(
                    modified_request
                ).encode()

                # Forward request to server without buffering the body.
                server_socket.connect(address)
                server_socket.sendall(raw_modified_request)

                while True:
                    data = server_socket.recv(BUFFER_SIZE)
                    if not data:
                        break
                    client_socket.sendall(data)

                break

    except Exception as e:
        print(f"Error: {e}")

    finally:
        client_socket.close()
        server_socket.close()


def modify_http_request(http_request: HttpRequest) -> HttpRequest:
    """Modify a HTTP request to the required format.

    Turn off `Keep-Alive` and lower the HTTP version.

    Args:
        http_request: The request to transform.
    """
    headers = http_request.headers

    if "connection" in headers:
        headers["connection"] = "close"

    if "proxy-connection" in headers:
        headers["proxy-connection"] = "close"

    http_request.protocol = "HTTP/1.0"

    url = urlsplit(http_request.uri)
    path = url.path or "/"

    if url.query:
        path += "?" + url.query

    http_request.uri = path

    return http_request


def deserialize_http_request(raw_request: str) -> HttpRequest:
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
            headers[key.strip().lower()] = value

    return HttpRequest(method, uri, protocol, headers)


def seserialize_http_request(http_request: HttpRequest) -> str:
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

    return f"{request_line}{headers}\r\n\r\n"


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

    host_header = http_request.headers["host"]

    host, separator, raw_port = host_header.partition(":")
    port = int(raw_port) if separator else 80

    return host, port

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
