# p2p/edge/edge.py
import socket, threading, time, os
from collections import defaultdict
from proto import send_json, recv_json

HEARTBEAT = "HEARTBEAT"
QUERY = "QUERY"
CATALOG = "CATALOG"
CATALOG_LOCK = threading.Lock()

class EdgeServer:
    def __init__(self, host='0.0.0.0', port=5000, timeout=60):
        self.addr = (host, port)
        self.timeout = timeout
        self.files_index = defaultdict(set)      # fname -> {peer_addr_str}
        self.peers_last_seen = {}                # peer_addr_str -> timestamp
        self.peer_checksums = {}

    def start(self):
        self._clear_catalog(path='catalog.txt')
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(self.addr)
        srv.listen()
        srv.settimeout(1.0)   # timeout de 1 segundo no accept()
        print(f'[EDGE] ouvindo em {self.addr}')
        threading.Thread(target=self._janitor, daemon=True).start()

        try:
            while True:
                try:
                    conn, cli = srv.accept()
                except socket.timeout:
                    continue     # volta pro topo do loop e permite capturar Ctrl+C
                threading.Thread(
                    target=self._handle_client,
                    args=(conn, cli),
                    daemon=True
                ).start()
        except (KeyboardInterrupt, SystemExit):
            print('\n[EDGE] desligando, limpando catálogo...')
            self._clear_catalog(path='catalog.txt')
        finally:
            srv.close()
        
    def _write_catalog(self, path='catalog.txt'):
        """
        Gera/atualiza um arquivo texto com todos os arquivos
        indexados, agrupados por extensão, sem duplicatas.
        """
        # agrupa por extensão
        groups = defaultdict(set)
        for fname in self.files_index:
            ext = os.path.splitext(fname)[1].lstrip('.').upper()  # 'txt', 'png' → 'TXT', 'PNG'
            if not ext:
                ext = 'SEM_EXTENSÃO'
            groups[ext].add(fname)

        # escreve em disco
        with open(path, 'w', encoding='utf-8') as f:
            for ext in sorted(groups):
                files = sorted(groups[ext])
                if not files:
                    continue
                f.write('---------------------------\n')
                f.write(f'{ext}\n\n')
                for name in files:
                    f.write(f'{name}\n')
                f.write('\n')

    def _clear_catalog(self, path='catalog.txt'):
        """Zera o índice em memória e apaga o arquivo no disco."""
        with CATALOG_LOCK:
            self.files_index.clear()
            # sobrescreve o catalog.txt para vazio
            open(path, 'w', encoding='utf-8').close()


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
            elif msg_type == CATALOG:
                # envia o catálogo em texto bruto
                with CATALOG_LOCK:
                    try:
                        with open('catalog.txt', 'r', encoding='utf-8') as f:
                            for line in f:
                                conn.send(line.encode('utf-8'))
                    except FileNotFoundError:
                        pass
                break  # fecha conexão após envio

        conn.close()

    def _handle_heartbeat(self, msg, cli):
        host = cli[0]
        download_port = msg.get('port')
        peer_str = f'{host}:{download_port}'
        files = set(msg.get('files', []))
        checksums = msg.get('checksums', {})

        with CATALOG_LOCK:
            # 1) Remove esse peer de todos os arquivos que ele tinha antes...
            for fname, holders in list(self.files_index.items()):
                if peer_str in holders and fname not in files:
                    holders.discard(peer_str)
                    if not holders:
                        del self.files_index[fname]

            # 2) Adiciona de volta só os arquivos anunciados agora
            for fname in files:
                self.files_index[fname].add(peer_str)

            # 3) Atualiza timestamps e checksums
            self.peers_last_seen[peer_str] = time.time()
            self.peer_checksums[peer_str] = checksums

        print(f'[EDGE] heartbeat {peer_str} → {len(files)} arquivos')

        # Se quiser atualizar o catálogo em disco sempre que mudar algo
        self._write_catalog(path='catalog.txt')

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
            changed = False
            with CATALOG_LOCK:
                dead = [p for p, t in self.peers_last_seen.items() if t < cutoff]
                for peer in dead:
                    print(f'[EDGE] removendo {peer} (inativo)')
                    # remove do last_seen
                    del self.peers_last_seen[peer]
                    # varre todos os arquivos indexados
                    for fname, holders in list(self.files_index.items()):
                        if peer in holders:
                            holders.discard(peer)
                            changed = True
                            # se não sobrou mais ninguém com este arquivo, remove a chave
                            if not holders:
                                del self.files_index[fname]
                # se algo mudou (removemos pelo menos um peer de algum arquivo),
                # atualiza o catalog.txt
                if changed:
                    self._write_catalog(path='catalog.txt')

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
