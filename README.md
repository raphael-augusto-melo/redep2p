# Rede P2P Híbrida (Edge + Peer)

Este repositório contém um cliente/servidor P2P híbrido em Python.
O **EdgeServer** mantém catálogo de quem tem cada arquivo; os **Peers** anunciam seus arquivos e solicitam downloads.

---

## Pré-requisitos

* Python 3.8 ou superior
* Git (opcional, para clonar este repositório)
* Rede local ou VPN (por ex. Radmin VPN) para testes distribuídos

---

## 1. Clonar e configurar

```bash
# 1) Clone o repositório (ou baixe o ZIP)
git clone https://github.com/raphael-augusto-melo/redep2p.git
cd redep2p

# 2) Crie e ative um virtualenv
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# 3) Instale dependências
pip install tqdm
```

---

## 2. Estrutura de arquivos

```
redep2p/
├─ checksum.py      ← SHA-256 de arquivos
├─ proto.py         ← send_json, recv_json
├─ edge.py          ← servidor de catálogo
├─ peer.py          ← cliente/servidor de arquivos
└─ README.md        ← este arquivo
```

---

## 3. Usando o EdgeServer

1. Abra um terminal na pasta raiz (`redep2p/`)

2. Ative o `venv` (veja acima)

3. Rode o servidor de borda:

   ```bash
   python -m edge
   ```

4. Você verá:

   ```
   [EDGE] ouvindo em ('0.0.0.0', 5000)
   ```

5. (Opcional) No console do Edge, digite `show_hashes ip:porta` para ver checksums de um peer.

---

## 4. Usando um Peer

Para cada máquina (ou terminal) que atuará como peer:

1. Crie uma pasta de compartilhamento:

   ```bash
   mkdir -p shared/<pasta>      # exemplo: peer “Alice”
   echo "Olá, mundo!" > shared/<pasta>/ola.txt # Linux
   ```

2. Rode o peer apontando para o Edge:

   ```bash
   python -m peer \
     --edge <IP_DO_EDGE> 5000 \
     --folder shared/<pasta> \
     --port <600X>
   ```

3. Você verá:

   ```
   [PEER] servindo downloads em 0.0.0.0:600X
   [PEER] pronto; digite comandos (get <arquivo>, catalogo, quit)
   ```

4. Comandos disponíveis:

   * `get <arquivo>`
     Baixa `<arquivo>` de outro peer. Exemplo:

     ```
     p2p> get ola.txt
     ```
   * `catalogo`
     Pede ao Edge o `catalog.txt` e imprime lista de todos os arquivos disponíveis:

     ```
     p2p> catalogo
     ```
   * `quit` ou `exit`
     Encerra o peer.

---

## 5. Fluxo de uso típico

1. **Inicie** o EdgeServer.
2. **Inicie** Peer A  — ele anuncia seus arquivos.
3. **Inicie** Peer B  — ele anuncia os seus.
4. No Peer B, execute `catalogo` para ver o que há na rede.
5. No Peer B, execute `get nome_do_arquivo` para baixar do Peer A.
6. Veja a barra de progresso e mensagem de “download ok”.

---

## 6. Ajustes avançados

* **Portas**: mude `--port` no peer e `--port` no edge (argumento de linha de comando em `edge.py`, se configurado).
* **Intervalo de heartbeat**: ajuste `hb_interval` no construtor do `Peer`.
* **Logs**: use `tee` para salvar logs, ex.

  ```bash
  python -m peer ... | tee logs/peer_a.txt
  ```

---

## 7. Limpeza e encerramento

* Para parar o EdgeServer, use `Ctrl+C`. Ele limpa o catálogo antes de fechar.
* Para parar cada Peer, digite `quit` no prompt do peer.

---

### Pronto!

Seguindo este guia você terá uma rede P2P híbrida funcional, com catálogo centralizado e troca de arquivos via sockets IPv4.
