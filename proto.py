import json
import socket
from names import ENCODING, DELIM

def send_json(sock: socket.socket, obj:dict):
    """
    Envia um objeto JSON para o socket.
    """
    data = json.dumps(obj).encode(ENCODING) + DELIM
    sock.sendall(data)

def recv_json(sock: socket.socket) -> dict | None:
    """Lê até \\n; devolve objeto ou None se conexão fechada."""
    buf = bytearray()
    while True:
        chunk = sock.recv(1)
        if not chunk:                # EOF
            return None
        if chunk == DELIM:
            break
        buf.extend(chunk)
    return json.loads(buf.decode(ENCODING))