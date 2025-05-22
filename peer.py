"""
    Peer - cliente que baixa arquivos de outros peers
"""

import socket                # para comunicação via rede (TCP)
import threading             # para fazer múltiplas tarefas ao mesmo tempo
import time                  # para controlar intervalos de tempo
import pathlib               # para manipular caminhos de arquivos de forma simples

from names import (          # traz constantes usadas no protocolo
    ENCODING, DELIM, HEARTBEAT, QUERY, QUERY_REPLY,
    GET, FILE_INFO, ERROR
)
from proto import send_json, recv_json
# send_json() e recv_json() encapsulam JSON sobre o socket

from tqdm import tqdm        # exibe barras de progresso
from checksum import sha256_arquivo  # função que calcula SHA-256 de um arquivo

import random                # para embaralhar listas (usado na seleção de holder)

BUF = 64 * 1024              # tamanho do bloco de dados (64 KB)

class Peer:
    def __init__(self, edge_host, edge_port,
                 folder='shared', my_port=6000, hb_interval=15):
        # guarda onde está o servidor de borda (edge)
        self.edge_addr   = (edge_host, edge_port)
        # cria (se não existir) a pasta onde guardaremos/baixaremos arquivos
        self.folder      = pathlib.Path(folder)
        self.folder.mkdir(exist_ok=True)
        # porta em que este peer vai servir downloads
        self.my_port     = my_port
        # intervalo em segundos entre heartbeats
        self.hb_interval = hb_interval
        # flag para manter o loop rodando até o usuário mandar sair
        self.running     = True

    # ---------------- ponto de entrada ---------------- #
    def start(self):
        # inicia, em threads separadas, o servidor de download e o loop de heartbeat
        threading.Thread(target=self._download_server, daemon=True).start()
        threading.Thread(target=self._keep_alive,     daemon=True).start()
        # mensagem inicial para o usuário
        print('[PEER] pronto; digite comandos (get <arquivo>, catalogo, quit)')
        self._cli_loop()  # entra no loop de interação com o usuário

    # ---------------- servidor de download ---------------- #
    def _download_server(self):
        # abre um socket TCP IPv4
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # associa a todas as interfaces na porta escolhida
        srv.bind(('0.0.0.0', self.my_port))
        srv.listen()  # começa a escutar conexões
        print(f'[PEER] servindo downloads em 0.0.0.0:{self.my_port}')
        # enquanto o peer estiver rodando, aceita conexões
        while self.running:
            conn, _cli = srv.accept()
            # cada nova conexão é tratada em uma thread própria
            threading.Thread(target=self._handle_get, args=(conn,), daemon=True).start()

    def _handle_get(self, conn):
        # recebe o pedido JSON do cliente
        req = recv_json(conn)
        # se não for um GET válido, fecha a conexão
        if not req or req.get('type') != GET:
            conn.close()
            return

        fname = req.get('filename')       # nome do arquivo pedido
        path  = self.folder / fname       # caminho completo no disco
        # se o arquivo não existir mais, avisa o cliente e fecha
        if not path.exists():
            send_json(conn, {"type": ERROR, "message": "FILE_NOT_FOUND"})
            conn.close()
            return

        size = path.stat().st_size       # tamanho total do arquivo
        # envia antes o tamanho para o cliente saber quanto vai receber
        send_json(conn, {"type": FILE_INFO, "size": size})

        # agora envia o conteúdo em blocos, mostrando barra de progresso
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

    # ---------------- heartbeat (keep-alive) ---------------- #
    def _keep_alive(self):
        # enquanto estiver ativo, envia o heartbeat e espera o intervalo
        while self.running:
            self._send_heartbeat()
            time.sleep(self.hb_interval)

    def _send_heartbeat(self):
        # lista todos os arquivos atuais na pasta
        files = [f.name for f in self.folder.iterdir() if f.is_file()]
        # calcula o SHA-256 de cada um
        checksums = {
            fname: sha256_arquivo(self.folder / fname)
            for fname in files
        }
        # monta a mensagem JSON
        msg = {
            "type":     HEARTBEAT,
            "files":    files,
            "checksums":checksums,
            "port":     self.my_port
        }
        # tenta conectar no edge e enviar
        try:
            with socket.create_connection(self.edge_addr, timeout=4) as sock:
                send_json(sock, msg)
        except OSError:
            print('[PEER] edge offline? heartbeat falhou')

    # ---------------- interface do usuário ---------------- #
    def _cli_loop(self):
        while True:
            try:
                cmd = input('p2p> ').strip().split()
            except (EOFError, KeyboardInterrupt):
                cmd = ['quit']
            if not cmd:
                continue
            # se for sair, para o loop
            if cmd[0] in ('quit', 'exit'):
                self.running = False
                break
            # se for baixar, chama download()
            elif cmd[0] == 'get' and len(cmd) == 2:
                self.download(cmd[1])
            # se for listar catálogo, chama catalogo()
            elif cmd[0] == 'catalogo' and len(cmd) == 1:
                self.catalogo()
            else:
                print('comando: get <arquivo> | catalogo | quit')

    # ---------------- download de arquivo ---------------- #
    def download(self, fname):
        # envia heartbeat imediato para atualizar o índice do edge
        self._send_heartbeat()

        # pergunta ao edge quem tem o arquivo
        try:
            with socket.create_connection(self.edge_addr, timeout=4) as sock:
                send_json(sock, {"type": QUERY, "filename": fname})
                reply = recv_json(sock)
        except OSError:
            print('[PEER] não conectou ao edge')
            return

        # valida resposta
        if not reply or reply.get("type") != QUERY_REPLY:
            print('[PEER] resposta inválida do edge')
            return

        holders = reply.get('holders', [])
        if not holders:
            print('[PEER] arquivo não encontrado na rede')
            return

        # embaralha a lista para balancear a carga
        random.shuffle(holders)

        # tenta baixar de cada holder até um funcionar
        for holder in holders:
            host, port_str = holder.split(':')
            port = int(port_str)

            # não tenta baixar de si mesmo
            if holder == f'{socket.gethostbyname(socket.gethostname())}:{self.my_port}':
                print(f'[PEER] {holder} é o proprio peer, não pode baixar de si mesmo')
                continue

            try:
                with socket.create_connection((host, port), timeout=4) as s:
                    # pede o arquivo
                    send_json(s, {"type": GET, "filename": fname})

                    # recebe info ou erro
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

                    # recebe dados e mostra barra de progresso
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

                    # checa se baixou tudo
                    if received == size:
                        print(f'[PEER] download ok ({size} bytes)')
                    else:
                        print('[PEER] download incompleto')
                    return

            except OSError as e:
                print(f'[PEER] erro conectando em {holder}:', e)
                continue

        # se nenhum holder funcionou
        print('[PEER] nenhum holder conseguiu fornecer o arquivo.')

    # ---------------- requisição de catálogo ---------------- #
    def catalogo(self):
        """requisita o catálogo do edge e imprime os arquivos disponíveis."""
        try:
            # conecta no edge
            with socket.create_connection(self.edge_addr, timeout=4) as sock:
                # pede o catálogo
                send_json(sock, {"type": "CATALOG"})
                # lê tudo até fechar a conexão
                buffer = b''
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk

            # decodifica com a codificação escolhida e mostra
            text = buffer.decode(ENCODING)
            print('[PEER] catálogo da rede:\n' + text)

        except OSError as e:
            print('[PEER] falha ao obter catálogo do edge:', e)

if __name__ == '__main__':
    import argparse, textwrap
    # configuração de linha de comando para facilitar execução
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""
        Exemplo de uso:
          python -m p2p.peer.peer --edge 127.0.0.1 5000 \\
                                 --folder ./shared/alice --port 6001"""))
    ap.add_argument('--edge', nargs=2, metavar=('HOST','PORT'), required=True)
    ap.add_argument('--folder', default='shared')
    ap.add_argument('--port',   type=int, default=6000)
    args = ap.parse_args()

    host, port = args.edge[0], int(args.edge[1])
    # instancia e inicia o peer
    Peer(host, port, folder=args.folder, my_port=args.port).start()
