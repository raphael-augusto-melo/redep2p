# p2p/peer/peer.py
import socket
import threading
import time
import pathlib
from names import ENCODING, DELIM, HEARTBEAT, QUERY, QUERY_REPLY, GET, FILE_INFO, ERROR
from proto import send_json, recv_json
from tqdm import tqdm
from checksum import sha256_arquivo
import random

BUF = 64 * 1024

class Peer:
    def __init__(self, edge_host, edge_port,
                 folder='shared', my_port=6000, hb_interval=30):
        self.edge_addr = (edge_host, edge_port)
        self.folder = pathlib.Path(folder)
        self.folder.mkdir(exist_ok=True)
        self.my_port = my_port
        self.hb_interval = hb_interval
        self.running = True

    # ---------------- API ---------------- #
    def start(self):
        # 1) servidor de download
        threading.Thread(target=self._download_server, daemon=True).start()
        # 2) loop keep-alive
        threading.Thread(target=self._keep_alive, daemon=True).start()
        print('[PEER] pronto; digite comandos (get <arquivo> ou quit)')
        self._cli_loop()

    # ---------------- servidor de download ---------------- #
    def _download_server(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(('0.0.0.0', self.my_port))
        srv.listen()
        print(f'[PEER] servindo downloads em 0.0.0.0:{self.my_port}')
        while self.running:
            conn, _cli = srv.accept()
            threading.Thread(target=self._handle_get, args=(conn,), daemon=True).start()

    def _handle_get(self, conn):
        req = recv_json(conn)
        if not req or req.get('type') != GET:
            conn.close()
            return

        fname = req.get('filename')
        path = self.folder / fname
        if not path.exists():
            # notifica o cliente que o arquivo não existe mais
            send_json(conn, {"type": ERROR, "message": "FILE_NOT_FOUND"})
            conn.close()
            return

        size = path.stat().st_size
        send_json(conn, {"type": FILE_INFO, "size": size})

        # envia o arquivo em blocos
        with open(path, 'rb') as f, tqdm(
            total=size,
            unit='B',
            unit_scale=True,
            desc=f"Enviando {fname}"
        ) as bar:
            while chunk := f.read(BUF):
                conn.sendall(chunk)
                bar.update(len(chunk))

        conn.close()
        print(f'[PEER] enviou {fname} ({size} bytes)')

    # ---------------- heartbeat ---------------- #
    def _keep_alive(self):
        while self.running:
            self._send_heartbeat()
            time.sleep(self.hb_interval)

    def _send_heartbeat(self):
        files = [f.name for f in self.folder.iterdir() if f.is_file()]
        checksums = { fname: sha256_arquivo(self.folder / fname)
                      for fname in files }
        
        msg = {
            "type": HEARTBEAT,
            "files": files,
            "checksums": checksums,
            "port": self.my_port
        }

        try:
            with socket.create_connection(self.edge_addr, timeout=4) as sock:
                send_json(sock, msg)
        except OSError:
            print('[PEER] edge offline? heartbeat falhou')

    # ---------------- linha de comando ---------------- #
    def _cli_loop(self):
        while True:
            try:
                cmd = input('p2p> ').strip().split()
            except (EOFError, KeyboardInterrupt):
                cmd = ['quit']
            if not cmd:
                continue
            if cmd[0] in ('quit', 'exit'):
                self.running = False
                break
            elif cmd[0] == 'get' and len(cmd) == 2:
                self.download(cmd[1])
            else:
                print('comando: get <arquivo> | quit')

    # ---------------- download de arquivo ---------------- #
    def download(self, fname):
        # 0) garanta que o Edge já “sabe” dos arquivos atuais
        self._send_heartbeat()

        # 1) pergunta ao edge quem tem o arquivo
        try:
            with socket.create_connection(self.edge_addr, timeout=4) as sock:
                send_json(sock, {"type": QUERY, "filename": fname})
                reply = recv_json(sock)
        except OSError:
            print('[PEER] não conectou ao edge')
            return

        if not reply or reply.get("type") != QUERY_REPLY:
            print('[PEER] resposta inválida do edge')
            return

        holders = reply.get('holders', [])
        if not holders:
            print('[PEER] arquivo não encontrado na rede')
            return

        # 2) tenta cada holder até conseguir baixar
        for holder in holders:
            holder = random.shuffle(holders)[0]  # aleatório
            host, port_str = holder.split(':')
            port = int(port_str)
            try:
                with socket.create_connection((host, port), timeout=4) as s:
                    # envia o pedido GET
                    send_json(s, {"type": GET, "filename": fname})

                    # recebe o FILE_INFO (JSON) ou erro
                    info = recv_json(s)
                    if not info:
                        print(f'[PEER] sem resposta de {holder}')
                        continue
                    if info.get("type") == ERROR:
                        print(f"[PEER] {holder} não tem mais o arquivo")
                        continue
                    if info.get("type") != FILE_INFO:
                        print(f'[PEER] resposta inesperada de {holder}')
                        continue

                    size = info['size']
                    dest = self.folder / fname
                    received = 0

                    # 3) recebe os dados com tqdm
                    with open(dest, 'wb') as f, tqdm(
                        total=size,
                        unit='B',
                        unit_scale=True,
                        desc=f"Baixando {fname}"
                    ) as bar:
                        while received < size:
                            chunk = s.recv(BUF)
                            if not chunk:
                                break
                            f.write(chunk)
                            received += len(chunk)
                            bar.update(len(chunk))

                    # 4) checa integridade (opcional)
                    if received == size:
                        print(f'[PEER] download ok ({size} bytes)')
                    else:
                        print('[PEER] download incompleto')
                    return

            except OSError as e:
                print(f'[PEER] erro conectando em {holder}:', e)
                continue

        print('[PEER] nenhum holder conseguiu fornecer o arquivo.')

if __name__ == '__main__':
    import argparse, textwrap
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""
        Exemplo de uso:
          python -m p2p.peer.peer --edge 127.0.0.1 5000 \\
                                 --folder ./shared/alice --port 6001"""))
    ap.add_argument('--edge', nargs=2, metavar=('HOST','PORT'), required=True)
    ap.add_argument('--folder', default='shared')
    ap.add_argument('--port', type=int, default=6000)
    args = ap.parse_args()
    host, port = args.edge[0], int(args.edge[1])
    Peer(host, port, folder=args.folder, my_port=args.port).start()
