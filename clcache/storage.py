import contextlib

from pymemcache.client.base import Client
from pymemcache.serde import (python_memcache_serializer,
                              python_memcache_deserializer)

from .__main__ import CacheFileStrategy, Manifest, printTraceStatement, CompilerArtifacts, \
    CACHE_COMPILER_OUTPUT_STORAGE_CODEC
from .memcached import memcached_client

class CacheDummyLock:
    def __enter__(self):
        pass

    def __exit__(self, typ, value, traceback):
        pass


class CacheMemcacheStrategy:
    def __init__(self, server, cacheDirectory=None, manifestPrefix='manifests_', objectPrefix='objects_'):
        if not isinstance(cacheDirectory, str):
            self.fileStrategy = cacheDirectory
        else:
            self.fileStrategy = CacheFileStrategy(cacheDirectory=cacheDirectory)
        # XX Memcache Strategy should be independent

        self.lock = CacheDummyLock()
        self.localCacheKeys = {}
        self.localCache = {}
        self.localManifest = {}
        self.objectPrefix = objectPrefix
        self.manifestPrefix = manifestPrefix

        self.connect(server)

    def connect(self, server):
        server = CacheMemcacheStrategy.splitHosts(server)
        assert server, "{} is not a suitable server".format(server)
        if len(server) != 1:
            raise ValueError(f"{server} is not a suitable server")
        else:
            from pymemcache.client.hash import HashClient
            clientClass = HashClient
        self.client = memcached_client(server[0])

        # XX key_prefix ties fileStrategy cache to memcache entry
        # because tests currently the integration tests use this to start with clean cache
        # Prevents from having cache hits in when code base is in different locations
        # adding code to production just for testing purposes

    def server(self):
        return self.client.server

    @staticmethod
    def splitHost(host):
        port = 11211
        index = host.rfind(':')
        if index != -1:
            host, port = host[:index], int(host[index + 1:])
        if not host or port > 65535:
            raise ValueError
        return host.strip(), port

    @staticmethod
    def splitHosts(hosts):
        """
        :param hosts: A string in the format of HOST:PORT[,HOST:PORT]
        :return: a list [(HOST, int(PORT)), ..] of tuples that can be consumed by socket.connect()
        """
        return [CacheMemcacheStrategy.splitHost(h) for h in hosts.split(',')]

    def __str__(self):
        return "{}  @{}:{}".format(self.fileStrategy.__str__(), *self.server())

    @property
    def statistics(self):
        return self.fileStrategy.statistics

    @property
    def configuration(self):
        return self.fileStrategy.configuration

    @staticmethod
    def lockFor(_):
        return CacheDummyLock()

    @staticmethod
    def manifestLockFor(_):
        return CacheDummyLock()

    def _fetchEntry(self, key):
        data = self.client.get((self.objectPrefix + key).encode("UTF-8"))
        if data is not None:
            self.localCache[key] = data
            return True
        self.localCache[key] = None
        return None

    def hasEntry(self, key):
        if key in self.localCacheKeys:
            return self.localCacheKeys[key]
        if key in self.localCache and self.localCache[key] is not None:
            return True
        r = self.client.exist(key)
        self.localCacheKeys[key] = r
        return r

    def getEntry(self, key):
        if key not in self.localCache:
            self._fetchEntry(key)
        if self.localCache[key] is None:
            return None
        data = self.localCache[key]

        printTraceStatement("{} remote cache hit for {} dumping into local cache".format(self, key))

        assert len(data) == 3

        # XX this is writing the remote objectfile into the local cache
        # because the current cache lookup assumes that getEntry gives us an Entry in local cache
        # so it can copy it to the build destination later

        with self.fileStrategy.lockFor(key):
            objectFilePath = self.fileStrategy.deserializeCacheEntry(key, data[0])

        return CompilerArtifacts(objectFilePath,
                                 data[1].decode(CACHE_COMPILER_OUTPUT_STORAGE_CODEC),
                                 data[2].decode(CACHE_COMPILER_OUTPUT_STORAGE_CODEC)
                                )

    def setEntry(self, key, artifacts):
        assert artifacts.objectFilePath
        with open(artifacts.objectFilePath, 'rb') as objectFile:
            self._setIgnoreExc(self.objectPrefix + key,
                               [objectFile.read(),
                                artifacts.stdout.encode(CACHE_COMPILER_OUTPUT_STORAGE_CODEC),
                                artifacts.stderr.encode(CACHE_COMPILER_OUTPUT_STORAGE_CODEC)],
                              )

    def getEntry2(self, key, p):
        if key not in self.localCache:
            self.localCache[key] = self.client.fetch_file(key)
        if self.localCache[key] is None:
            printTraceStatement("Failed fetch file from memcache keyed {}".format(key))
            return None
        data = self.localCache[key]
        with open(p, 'wb') as f:
            f.write(data)
        return p

    def setEntry2(self, key, value):
        r = self.client.store_file(key, value)
        if r is not False:
            self.localCacheKeys[key] = True
        return r

    def setManifest(self, manifestHash, manifest):
        r = self.client.store(manifestHash, manifest.asdict(None).encode('utf-8') + b' ')
        if r:
            printTraceStatement("Writing manifest with manifestHash = {}".format(manifestHash))
        else:
            printTraceStatement("Failed writing manifest with manifestHash = {}".format(manifestHash))
        return r

    def _setIgnoreExc(self, key, value):
        self.client.set(key, value, noreply=False)

    def getManifest(self, manifestHash):
        doc = self.client.fetch(manifestHash)
        return Manifest.convert(doc.decode('utf-8')) if doc else None

    def clean(self, stats, maximumSize):
        self.fileStrategy.clean(stats,
                                maximumSize)

    def clear(self):
        self.client.flush()


class CacheFileWithMemcacheFallbackStrategy:
    def __init__(self, server, cacheDirectory=None, manifestPrefix='manifests_', objectPrefix='objects_'):
        self.localCache = CacheFileStrategy(cacheDirectory=cacheDirectory)
        self.remoteCache = CacheMemcacheStrategy(server, cacheDirectory=cacheDirectory,
                                                 manifestPrefix=manifestPrefix,
                                                 objectPrefix=objectPrefix)

    def __str__(self):
        return "CacheFileWithMemcacheFallbackStrategy local({}) and remote({})".format(self.localCache,
                                                                                       self.remoteCache)

    def hasEntry(self, key):
        return self.localCache.hasEntry(key) or self.remoteCache.hasEntry(key)

    def getEntry(self, key):
        if self.localCache.hasEntry(key):
            printTraceStatement("Getting object {} from local cache".format(key))
            return self.localCache.getEntry(key)
        remote = self.remoteCache.getEntry(key)
        if remote:
            printTraceStatement("Getting object {} from remote cache".format(key))
            return remote
        return None

    def setEntry(self, key, artifacts):
        self.localCache.setEntry(key, artifacts)
        self.remoteCache.setEntry(key, artifacts)

    def setManifest(self, manifestHash, manifest):
        with self.localCache.manifestLockFor(manifestHash):
            self.localCache.setManifest(manifestHash, manifest)
        self.remoteCache.setManifest(manifestHash, manifest)

    def getManifest(self, manifestHash):
        local = self.localCache.getManifest(manifestHash)
        if local:
            printTraceStatement("{} local manifest hit for {}".format(self, manifestHash))
            return local
        remote = self.remoteCache.getManifest(manifestHash)
        if remote:
            with self.localCache.manifestLockFor(manifestHash):
                self.localCache.setManifest(manifestHash, remote)
            printTraceStatement("{} remote manifest hit for {} writing into local cache".format(self, manifestHash))
            return remote
        return None

    @property
    def statistics(self):
        return self.localCache.statistics

    @property
    def configuration(self):
        return self.localCache.configuration

    @staticmethod
    def lockFor(_):
        return CacheDummyLock()

    @staticmethod
    def manifestLockFor(_):
        return CacheDummyLock()

    @property # type: ignore
    @contextlib.contextmanager
    def lock(self):
        with self.remoteCache.lock, self.localCache.lock:
            yield

    def clean(self, stats, maximumSize):
        self.localCache.clean(stats,
                              maximumSize)
