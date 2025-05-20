import hashlib, os

BUF_SIZE = 64 * 1024 # 64KB

def sha256_arquivo(path):
    """
    Calculate the SHA256 hash of a file.
    :param path: Path to the file.
    :param buf: Buffer size for reading the file.
    :return: SHA256 hash of the file.
    """
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(BUF_SIZE):
            h.update(chunk)
        return h.hexdigest()