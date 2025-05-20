# p2p/edge/edge.py
import socket, threading, time
from collections import defaultdict
from proto import send_json, recv_json

HEARTBEAT = "HEARTBEAT"
QUERY = "QUERY"
CATALOG_LOCK = threading.Lock()

class EdgeServer:
    def __init__(self, host='0.0.0.0', port=5000, timeout=90):
        self.addr = (host, port)
        self.timeout = timeout
        self.files_index = defaultdict(set)      # fname -> {peer_addr_str}
        self.peers_last_seen = {}                # peer_addr_str -> timestamp
        self.peer_checksums = {}

    def start(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(self.addr)
        srv.listen()
        print(f'[EDGE] ouvindo em {self.addr}')
        threading.Thread(target=self._janitor, daemon=True).start()

        while True:
            conn, cli = srv.accept()
            threading.Thread(
                target=self._handle_client,
                args=(conn, cli),
                daemon=True
            ).start()

    def _handle_client(self, conn, cli):
        while True:
            msg = recv_json(conn)
            if not msg:
                break

            msg_type = msg.get('type')
            if msg_type == HEARTBEAT:
                # passa também o endereço original do socket, para sabermos o IP
                self._handle_heartbeat(msg, cli)
            elif msg_type == QUERY:
                self._handle_query(msg, conn)

        conn.close()

    def _handle_heartbeat(self, msg, cli):
        """
        msg: dicionário com 'files' e 'port'
        cli: tupla (ip, porta TCP do heartbeat)
        """
        host = cli[0]
        download_port = msg.get('port')           # porto real do servidor de download
        peer_str = f'{host}:{download_port}'      # agora corretíssimo

        files = msg.get('files', [])
        checksums = msg.get('checksums', {})
        with CATALOG_LOCK:
            # primeiro, limpa entradas antigas para este peer em qualquer porto
            for fset in self.files_index.values():
                # se havia registros antigos com IP igual, mas porta errada, removemos
                fset = {p for p in fset if not p.startswith(f'{host}:')}
                fset.discard(peer_str)
                # armazena os checksums recebidos
                self.peer_checksums[peer_str] = checksums
            # adiciona arquivos atuais
            for fname in files:
                self.files_index[fname].add(peer_str)
            # atualiza timestamp com a chave correta
            self.peers_last_seen[peer_str] = time.time()

        print(f'[EDGE] heartbeat {peer_str} → {len(files)} arquivos')
        if checksums:
           print(f'[EDGE] hashes de {peer_str}:')
           for fname, h in checksums.items():
                print(f'    - {fname}: {h}')

    def _handle_query(self, msg, conn):
        fname = msg.get('filename')
        with CATALOG_LOCK:
            holders = list(self.files_index.get(fname, []))
        send_json(conn, {"type": "QUERY_REPLY", "holders": holders})

    def _janitor(self):
        """Remove peers que não mandaram heartbeat dentro do timeout."""
        while True:
            time.sleep(self.timeout // 3)
            cutoff = time.time() - self.timeout
            with CATALOG_LOCK:
                dead = [p for p, t in self.peers_last_seen.items() if t < cutoff]
                for peer in dead:
                    print(f'[EDGE] removendo {peer} (inativo)')
                    del self.peers_last_seen[peer]
                    for fset in self.files_index.values():
                        fset.discard(peer)
    
    def _cli_loop(self):
        while True:
            cmd = input('edge> ').strip().split()
            if cmd and cmd[0] == 'show_hashes':
                peer = cmd[1] if len(cmd)>1 else None
                if peer and peer in self.peer_checksums:
                    for f,h in self.peer_checksums[peer].items():
                        print(f'{peer} → {f}: {h}')
                else:
                    print('Uso: show_hashes ip:port')


if __name__ == '__main__':
    EdgeServer().start()
