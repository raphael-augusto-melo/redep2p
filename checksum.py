"""
Checksum - Calcula o hash SHA-256 de um arquivo.
"""

import hashlib
# traz o módulo para calcular funções de hash (SHA-256, MD5, etc.)

BUF_SIZE = 64 * 1024  # 64KB
# define o tamanho do bloco de leitura do arquivo em bytes
# (ler em pedaços grandes é mais eficiente do que ler byte a byte)

def sha256_arquivo(path: str, buf: int = BUF_SIZE) -> str:
    """
    Calcula o hash SHA-256 de um arquivo.
    
    :param path: Caminho (string) até o arquivo no disco.
    :param buf:  Tamanho do buffer (quantos bytes ler por vez).
    :return:     O hash SHA-256 completo como string hexadecimal.
    """
    h = hashlib.sha256()
    # cria um objeto de hash SHA-256 vazio
    
    with open(path, 'rb') as f:
        # abre o arquivo em modo binário ("rb")
        # o 'with' garante que o arquivo será fechado automaticamente

        while chunk := f.read(buf):
            # lê até `buf` bytes do arquivo por vez
            # a leitura retorna bytes, ou b'' quando chega ao fim
            h.update(chunk)
            # atualiza o estado do hash com o bloco lido

        # quando o loop terminar, todo o arquivo já foi processado
        return h.hexdigest()
        # retorna o resultado final do hash como string em hexadecimal
        # (por exemplo, '3a7bd3e2360a...ff')
