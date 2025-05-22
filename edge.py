# p2p/edge/edge.py

import socket, threading, time, os
# traz classes e funções padrão de Python para trabalhar
# com rede (socket), threads (threading), tempo (time) e arquivos (os)

from collections import defaultdict
# defaultdict é como um dict normal, mas que já cria uma entrada vazia
# automaticamente quando você acessa uma chave nova

from proto import send_json, recv_json
# funções que enviam e recebem mensagens JSON pela rede

HEARTBEAT = "HEARTBEAT"
QUERY     = "QUERY"
CATALOG   = "CATALOG"
# constantes que definem tipos de mensagem que vamos usar

CATALOG_LOCK = threading.Lock()
# trava para garantir que só uma thread modifique o catálogo por vez

class EdgeServer:
    def __init__(self, host='0.0.0.0', port=5000, timeout=60):
        self.addr            = (host, port)
        # tupla (IP, porta) onde este servidor vai escutar conexões

        self.timeout         = timeout
        # tempo em segundos que esperamos antes de considerar um peer inativo

        self.files_index     = defaultdict(set)
        # armazena: nome_do_arquivo → conjunto de peers que têm esse arquivo

        self.peers_last_seen = {}
        # armazena: "ip:porta" do peer → timestamp (último heartbeat)

        self.peer_checksums  = {}
        # armazena: "ip:porta" do peer → dicionário de checksums {arquivo→hash}

    def start(self):
        self._clear_catalog(path='catalog.txt')
        # limpa o catálogo em disco e em memória no início

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # cria um “ouvido” de rede TCP usando IPv4

        srv.bind(self.addr)
        # associa esse “ouvido” ao IP e porta definidos

        srv.listen()
        # começa a escutar conexões que chegarem

        srv.settimeout(1.0)
        # faz o accept() não travar para sempre: ele “desperta” a cada 1s

        print(f'[EDGE] ouvindo em {self.addr}')
        # informa no console que o servidor está pronto

        threading.Thread(target=self._janitor, daemon=True).start()
        # inicia em paralelo a função que vai remover peers inativos

        try:
            while True:
                try:
                    conn, cli = srv.accept()
                    # espera uma nova conexão de peer; retorna socket e endereço
                except socket.timeout:
                    continue
                    # se deu timeout, volta ao topo do loop sem travar

                threading.Thread(
                    target=self._handle_client,
                    args=(conn, cli),
                    daemon=True
                ).start()
                # para cada conexão, inicia uma thread que vai tratar
        except (KeyboardInterrupt, SystemExit):
            print('\n[EDGE] desligando, limpando catálogo...')
            self._clear_catalog(path='catalog.txt')
            # ao apertar Ctrl+C, limpa novamente antes de sair
        finally:
            srv.close()
            # fecha o socket do servidor

    def _write_catalog(self, path='catalog.txt'):
        """
        Gera/atualiza um arquivo texto com todos os arquivos
        indexados, agrupados por extensão, sem duplicatas.
        """
        groups = defaultdict(set)
        # dicionário: extensão → conjunto de nomes de arquivo

        for fname in self.files_index:
            ext = os.path.splitext(fname)[1].lstrip('.').upper()
            # pega a parte depois do ponto no nome (ex.: ".jpg" → "JPG")
            if not ext:
                ext = 'SEM_EXTENSÃO'
                # se não tiver ponto, marca como “SEM_EXTENSÃO”
            groups[ext].add(fname)
            # adiciona o arquivo ao grupo da respectiva extensão

        with open(path, 'w', encoding='utf-8') as f:
            # abre (ou cria) o catalog.txt, apagando o que tinha antes
            for ext in sorted(groups):
                files = sorted(groups[ext])
                if not files:
                    continue
                    # só escreve se houver pelo menos um arquivo nessa extensão

                f.write('---------------------------\n')
                f.write(f'{ext}\n\n')
                for name in files:
                    f.write(f'{name}\n')
                f.write('\n')
                # formata o arquivo com seções por extensão

    def _clear_catalog(self, path='catalog.txt'):
        """Zera o índice em memória e apaga o arquivo no disco."""
        with CATALOG_LOCK:
            self.files_index.clear()
            # limpa todos os itens do dicionário em memória
            open(path, 'w', encoding='utf-8').close()
            # cria/esvazia o arquivo catalog.txt

    def _handle_client(self, conn, cli):
        """Recebe mensagens de um peer e processa os comandos."""
        while True:
            msg = recv_json(conn)
            # tenta ler uma mensagem JSON do peer
            if not msg:
                break
                # conexão fechou ou deu erro de leitura: sai

            msg_type = msg.get('type')
            # tipo de mensagem (HEARTBEAT, QUERY, CATALOG)

            if msg_type == HEARTBEAT:
                self._handle_heartbeat(msg, cli)
                # atualiza índice e checksums desse peer
            elif msg_type == QUERY:
                self._handle_query(msg, conn)
                # responde quem tem o arquivo pedido
            elif msg_type == CATALOG:
                with CATALOG_LOCK:
                    try:
                        with open('catalog.txt', 'r', encoding='utf-8') as f:
                            for line in f:
                                conn.send(line.encode('utf-8'))
                                # envia o catálogo linha a linha
                    except FileNotFoundError:
                        pass
                break
                # após enviar catálogo, fecha a conexão

        conn.close()
        # garante que o socket seja fechado ao final

    def _handle_heartbeat(self, msg, cli):
        host          = cli[0]
        download_port = msg.get('port')
        peer_str      = f'{host}:{download_port}'
        # monta string única para identificar o peer

        files     = set(msg.get('files', []))
        checksums = msg.get('checksums', {})
        # obtém lista de arquivos e seus hashes do heartbeat

        with CATALOG_LOCK:
            # 1) remove entradas antigas deste peer
            for fname, holders in list(self.files_index.items()):
                if peer_str in holders and fname not in files:
                    holders.discard(peer_str)
                    if not holders:
                        del self.files_index[fname]
            # 2) adiciona/atualiza arquivos anunciados agora
            for fname in files:
                self.files_index[fname].add(peer_str)
            # 3) atualiza a hora do último heartbeat
            self.peers_last_seen[peer_str] = time.time()
            # e salva o dicionário de checksums enviado
            self.peer_checksums[peer_str]  = checksums

        print(f'[EDGE] heartbeat {peer_str} → {len(files)} arquivos')
        # mostra quantos arquivos esse peer anunciou

        self._write_catalog(path='catalog.txt')
        # reescreve o catalog.txt com o índice atualizado

    def _handle_query(self, msg, conn):
        fname = msg.get('filename')
        # nome do arquivo que alguém pediu
        with CATALOG_LOCK:
            holders = list(self.files_index.get(fname, []))
            # lista de peers que têm esse arquivo
        send_json(conn, {"type": "QUERY_REPLY", "holders": holders})
        # manda de volta a lista para o peer solicitante

    def _janitor(self):
        """Remove peers que não mandaram heartbeat dentro do timeout."""
        while True:
            time.sleep(self.timeout // 3)
            # dorme 1/3 do tempo de timeout
            cutoff = time.time() - self.timeout
            changed = False
            with CATALOG_LOCK:
                dead = [p for p, t in self.peers_last_seen.items() if t < cutoff]
                # lista de peers que não deram heartbeat recentemente
                for peer in dead:
                    print(f'[EDGE] removendo {peer} (inativo)')
                    del self.peers_last_seen[peer]
                    for fname, holders in list(self.files_index.items()):
                        if peer in holders:
                            holders.discard(peer)
                            changed = True
                            if not holders:
                                del self.files_index[fname]
                if changed:
                    self._write_catalog(path='catalog.txt')
                    # se algo mudou, atualiza o arquivo em disco

    def _cli_loop(self):
        while True:
            cmd = input('edge> ').strip().split()
            # lê comando do usuário que administra o edge
            if cmd and cmd[0] == 'show_hashes':
                peer = cmd[1] if len(cmd)>1 else None
                if peer and peer in self.peer_checksums:
                    for f, h in self.peer_checksums[peer].items():
                        print(f'{peer} → {f}: {h}')
                else:
                    print('Uso: show_hashes ip:port')
                # permite ver lista de hashes de um peer específico

if __name__ == '__main__':
    EdgeServer().start()
    # se executado direto, inicia o servidor
