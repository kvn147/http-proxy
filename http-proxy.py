import socket
import threading
import sys

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
            target = handle_connection, 
            args = (client_sock, client_addr)
        )
        thread.start()

def handle_connection (client_sock, client_addr):
    try:
        data = client_sock.recv(4096)
        print(f"Connection from {client_addr}")
        
    finally:
        client_sock.close()
    
if __name__ == "__main__":
    run_tcp_server()
