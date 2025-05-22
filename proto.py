"""
Proto - Protocolo de comunicação entre cliente e servidor
"""

import json               # traz o módulo para trabalhar com JSON (converter entre dict e texto)
import socket             # traz o módulo para usar sockets de rede

from names import ENCODING, DELIM  
# ENCODING: codificação de texto (ex.: 'utf-8')
# DELIM: delimitador de mensagem (ex.: b'\n'), para indicar fim de cada JSON

def send_json(sock: socket.socket, obj: dict):
    """
    Envia um objeto Python (dict) como mensagem JSON pelo socket.
    """
    # 1) json.dumps(obj) → transforma dict em string JSON
    # 2) .encode(ENCODING) → converte string em bytes usando a codificação (utf-8)
    # 3) + DELIM → adiciona um byte de quebra de linha para marcar o fim da mensagem
    data = json.dumps(obj).encode(ENCODING) + DELIM
    # 4) sock.sendall(data) → envia todos os bytes pela conexão de rede
    sock.sendall(data)

def recv_json(sock: socket.socket) -> dict | None:
    """
    Lê bytes do socket até encontrar o delimitador (DELIM).
    Concatena esses bytes, decodifica para string e faz json.loads()
    para retornar um dict Python.
    Se a conexão fechar antes de ler qualquer byte (EOF), retorna None.
    """
    buf = bytearray()  # buffer mutável para armazenar os bytes recebidos
    while True:
        chunk = sock.recv(1)  # lê 1 byte da conexão
        if not chunk:
            # se recv() retornar b'', significa que a outra ponta fechou
            return None
        if chunk == DELIM:
            # se o byte lido for o delimitador (quebra de linha), paramos de ler
            break
        buf.extend(chunk)  
        # adiciona o byte lido ao buffer; continua até encontrar DELIM

    # quando sai do loop, buf tem todos os bytes antes do DELIM
    # 1) buf.decode(ENCODING) → converte bytes para string JSON
    # 2) json.loads(...) → transforma string JSON em dict Python
    return json.loads(buf.decode(ENCODING))
