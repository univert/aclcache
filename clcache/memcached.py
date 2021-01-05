import sys, glob, re
from typing import List
from dataclasses import dataclass, asdict
from json import dumps,loads
import traceback
from pymemcache.client.base import Client
from pymemcache.serde import (python_memcache_serializer,
                              python_memcache_deserializer)
from .__main__ import getObjectFileHash, FILE_CHUNK_SIZE, printTraceStatement, ACLCACHE_MEMCCACHE_BIG_KEY
from .__main__ import HashAlgorithm




@dataclass
class big_file_descriptor:
    blocks: int = 0;
    size: int = 0;
    block_size: int = FILE_CHUNK_SIZE;
    hash_type : int = 0;
    hashes: List[str] = None;

    def __post_init__(self):
        if not self.hashes:
            self.hashes = []

    def add_chunk(self, chunk):
        self.blocks += 1
        self.size += len(chunk)
        hash = HashAlgorithm(chunk).hexdigest()
        self.hashes.append((hash, len(chunk)))
        return hash

    def pack(self):
        return dumps(asdict(self)).encode('utf-8')

    @staticmethod
    def unpack(buffer):
        return big_file_descriptor(**loads(buffer))

    def iter_hashes(self):
        return [x[0] for x in self.hashes]


def retry(func):
    count =3
    def mfunc(*args, **kargs):
        i = 0
        while True:
            try:
                r = func(*args, **kargs)
                return r
            except:
                i += 1
                if i > count:
                    printTraceStatement(traceback.format_exc())
                    break
    return mfunc
class memcached_client(Client):
    def __init__(self, server, compressor=None):
        super(memcached_client, self).__init__(server, ignore_exc=False,
                        serializer=python_memcache_serializer,
                        deserializer=python_memcache_deserializer,
                        timeout=60,
                        connect_timeout=15,
                        key_prefix='', encoding='utf-8')
        self.compressor = compressor

    @retry
    def fetch(self, key):
        result = self.get(key)
        return result

    def exist(self, key):
        if self.exist_multi(key):
            return True
        key += ACLCACHE_MEMCCACHE_BIG_KEY
        buffer = self.fetch(key)
        if buffer:
            desc = big_file_descriptor.unpack(buffer)
            return self.exist_multi(*desc.iter_hashes())
        return False

    @retry
    def exist_multi(self, *keys):
        r = self._store_cmd(b'append', dict.fromkeys(keys,b''), 0, False)
        return all(r.values())

    @retry
    def store(self, key, value):
        result = self._store_cmd(b'set', {key: value}, expire=0, noreply=False, flags=None)
        if not result.get(key, False):
            raise Exception('Store failed for key {}'.format(key))
        return True

    @retry
    def store_multi(self, keys, values, noreply=False):
        result = self._store_cmd(b'set', dict(zip(keys, values)), expire=0, noreply=noreply, flags=None)
        if not all((result[x] for x in keys)):
            raise Exception('store_multi failed')
        return True

    def store_file(self, key, file_name):
        data = open(file_name,'rb').read()
        if self.compressor:
            data = self.compressor[0].compress(data)
        if len(data) < FILE_CHUNK_SIZE:
            return self.store(key, data) and len(data)
        key += ACLCACHE_MEMCCACHE_BIG_KEY
        desc = big_file_descriptor()
        chunks = []
        keys = []
        for chunk in (data[i:i+FILE_CHUNK_SIZE] for i in range(0, len(data), FILE_CHUNK_SIZE)):
            h = desc.add_chunk(chunk)
            chunks.append(chunk)
            keys.append(h)
        desc = desc.pack()
        keys.append(key)
        chunks.append(desc)
        return self.store_multi(keys, chunks, noreply=False) and len(data)

    @retry
    def fetch_file(self, key):
        buffer = self.fetch(key)
        if buffer:
            if self.compressor:
                buffer = self.compressor[1].decompress(buffer)
            return buffer
        buffer = self.fetch(key + ACLCACHE_MEMCCACHE_BIG_KEY)
        if not buffer:
            return None
        desc = big_file_descriptor.unpack(buffer)
        result = self._fetch_cmd(b'get', desc.iter_hashes(), False)
        result = b''.join((result[x] for x in desc.iter_hashes())) if result else None
        if result and len(result) == desc.size:
            if self.compressor:
                result = self.compressor[1].decompress(result)
            return result
        return None

    def me(self, key):
        key = self.check_key(key)
        cmd = b'mg ' + key + b'\r\n'
        results = self._misc_cmd([cmd], b'me', noreply=False)
        return results

    def flush(self):
        self.flush_all()

def hash_checker(server, hash):
    client = memcached_client(server)

    r = client.exist(hash)
    if not r:
        print(f'{hash} not exit')
        return
    r = client.fetch_file(hash)
    if not getObjectFileHash(r) == hash:
        print(f'hash not verified')
        return
    print(f'hash is verified')
    return

def single_file_test(server, filename):
    hash = getObjectFileHash(filename)
    if isinstance(server, str):
        client = memcached_client(server)
    else:
        client = server
    r = client.exist(hash)
    client.store_file(hash, filename)
    assert client.exist(hash)
    r = client.fetch_file(hash)
    assert getObjectFileHash(r) == hash


def folder_test(server, folder):
    client = memcached_client(sys.argv[1])
    for filename in glob.iglob(folder, recursive=True):
        single_file_test(client, filename)

def populate(folder):
    client = memcached_client(sys.argv[1])

    #client.flush()
    for filename in glob.iglob(folder, recursive=True):
        hash = re.split(r'\\', filename)[-2]
        if client.exist(hash):
            print(f'!!!!!!!!!!{hash}')
        client.store_file(hash, filename)
        print(f'stored {filename}')

    for filename in glob.iglob(folder, recursive=True):
        hash = re.split(r'\\', filename)[-2]
        if not client.exist(hash):
            print(f'{hash}!!!!!!!!!!')
    for filename in glob.iglob(folder, recursive=True):
        hash = re.split(r'\\', filename)[-2]
        r = client.fetch_file(hash)
        if r and len(r) > 0 and not getObjectFileHash(r).startswith(hash):
            print(f'{filename}!!!!')
        else:
            pass
            #print(f'{filename}')
    client.disconnect_all()
    #client.store_multi(keys, files)


def test1(*args):
    client = memcached_client('10.41.90.115:8080')
    r = client.fetch('47a85552ac4d48aec4a0a02ab538bce7')
    print(r)
    #r = client.fetch_file('b70d4d9bd1fb316aca1ded8a6f31a7c5Z')

    '''91d7b08e677cb563f58b53c87d98a49cZ'''

def main():
    return test1(sys.argv[2])


if __name__ == '__main__':
    sys.exit(main())
