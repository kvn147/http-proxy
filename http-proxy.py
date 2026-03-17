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


def split_http_header(buffer: bytes) -> tuple[bytes, bytes] | None:
    """Split a HTTP message into header bytes and remaining bytes.

    Accept either CRLFCRLF or LFLF for terminating.

    Args:
        buffer: The bytes to split.
    """
    crlf_index = buffer.find(b"\r\n\r\n")
    lf_index = buffer.find(b"\n\n")

    if crlf_index == -1 and lf_index == -1:
        return None

    if crlf_index != -1 and (lf_index == -1 or crlf_index <= lf_index):
        separator_len = 4
        split_index = crlf_index
    else:
        separator_len = 2
        split_index = lf_index

    return buffer[:split_index], buffer[split_index + separator_len :]


def force_close_headers(headers: dict[str, str]) -> None:
    """Force non-persistent HTTP connection headers.

    Args:
        headers: The HTTP headers to modify in-place.
    """
    headers["connection"] = "close"
    headers["proxy-connection"] = "close"
    headers.pop("keep-alive", None)


def deserialize_http_response(raw_response: str) -> tuple[str, dict[str, str]]:
    """Transform a raw response header to status line and headers.
    
    """
    lines = raw_response.splitlines()
    status_line, *header_lines = lines

    headers = {}
    for header_line in header_lines:
        key, separator, value = header_line.partition(":")
        if separator:
            headers[key.strip().lower()] = value.strip()

    return status_line, headers


def serialize_http_response(status_line: str, headers: dict[str, str]) -> str:
    """Transform response line + headers into raw header text.
    
    """
    headers_text = "\r\n".join([f"{key}: {value}" for (key, value) in headers.items()])
    return f"{status_line}\r\n{headers_text}\r\n\r\n"


def forward_response(server_socket: socket.socket, client_socket: socket.socket) -> None:
    """Forward response while rewriting connection headers to close.

    """
    buffer = b""

    while True:
        header_split = split_http_header(buffer)
        if header_split:
            raw_header, remaining = header_split
            status_line, headers = deserialize_http_response(raw_header.decode())
            force_close_headers(headers)

            modified_header = serialize_http_response(status_line, headers).encode()
            client_socket.sendall(modified_header)
            if remaining:
                client_socket.sendall(remaining)
            break

        data = server_socket.recv(BUFFER_SIZE)
        if not data:
            if buffer:
                client_socket.sendall(buffer)
            return
        buffer += data

    while data := server_socket.recv(BUFFER_SIZE):
        client_socket.sendall(data)


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

            # Keep reading until we have the full HTTP header.
            header_split = split_http_header(buffer)
            if not header_split:
                continue

            raw_request, buffer = header_split

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

            content_length = int(http_request.headers.get("content-length", 0))

            # Forward any body bytes that were already read along with the header.
            body = buffer[:content_length]
            if body:
                server_socket.sendall(body)

            bytes_sent = len(body)

            # Continue streaming the rest of the body, if any.
            while bytes_sent < content_length:
                chunk = client_socket.recv(BUFFER_SIZE)
                if not chunk:
                    break
                remaining = content_length - bytes_sent
                to_send = chunk[:remaining]
                server_socket.sendall(to_send)
                bytes_sent += len(to_send)

            # Now forward the response exactly once.
            forward_response(server_socket, client_socket)
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
    force_close_headers(headers)

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
