#!/usr/bin/env python
#
# This file is part of the clcache project.
#
# The contents of this file are subject to the BSD 3-Clause License, the
# full text of which is available in the accompanying LICENSE file at the
# root directory of this project.
#
import sys, os, re, hashlib, json, subprocess, threading, pickle, multiprocessing, gzip, errno, contextlib, concurrent.futures, codecs, functools,time
from collections import defaultdict, namedtuple
from ctypes import windll, wintypes, create_unicode_buffer, byref
from dataclasses import dataclass, asdict, InitVar
from shutil import copyfile, copyfileobj, rmtree, which
from tempfile import TemporaryFile
from typing import Any, List, Tuple, Iterator
from atomicwrites import atomic_write

VERSION = "5.0-dev"


def diff_time():
    creationtime = wintypes.ULARGE_INTEGER()
    exittime = wintypes.ULARGE_INTEGER()
    kerneltime = wintypes.ULARGE_INTEGER()
    usertime = wintypes.ULARGE_INTEGER()
    windll.kernel32.GetThreadTimes(
        windll.kernel32.GetCurrentThread(),
        byref(creationtime),
        byref(exittime),
        byref(kerneltime),
        byref(usertime))
    currtime = wintypes.ULARGE_INTEGER()
    windll.kernel32.GetSystemTimeAsFileTime(byref(currtime))
    alltime =  currtime.value - creationtime.value
    cputime = kerneltime.value + usertime.value
    cputime = alltime if cputime > alltime else cputime
    return alltime, cputime

def exception_hook(exc_type, exc_value, exc_traceback):
    import traceback
    s = traceback.format_exception(exc_type, exc_value, exc_traceback)
    printTraceStatement(''.join(s))
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

sys.excepthook = exception_hook

HashAlgorithm = hashlib.md5

OUTPUT_LOCK = threading.Lock()

g_project_name = None
# try to use os.scandir or scandir.scandir
# fall back to os.listdir if not found
# same for scandir.walk
try:
    import scandir # pylint: disable=wrong-import-position
    WALK = scandir.walk
    LIST = scandir.scandir
except ImportError:
    WALK = os.walk
    try:
        LIST = os.scandir # type: ignore # pylint: disable=no-name-in-module
    except AttributeError:
        LIST = os.listdir

# The codec that is used by clcache to store compiler STDOUR and STDERR in
# output.txt and stderr.txt.
# This codec is up to us and only used for clcache internal storage.
# For possible values see https://docs.python.org/2/library/codecs.html
CACHE_COMPILER_OUTPUT_STORAGE_CODEC = 'utf-8'

# The cl default codec
CL_DEFAULT_CODEC = 'mbcs'

# Manifest file will have at most this number of hash lists in it. Need to avoi
# manifests grow too large.
MAX_MANIFEST_HASHES = 100

# String, by which BASE_DIR will be replaced in paths, stored in manifests.
# ? is invalid character for file name, so it seems ok
# to use it as mark for relative path.
BASEDIR_REPLACEMENT = '?'

# Define some Win32 API constants here to avoid dependency on win32pipe
NMPWAIT_WAIT_FOREVER = wintypes.DWORD(0xFFFFFFFF)
ERROR_PIPE_BUSY = 231

# ManifestEntry: an entry in a manifest file
# `includeFiles`: list of paths to include files, which this source file uses
# `includesContentsHash`: hash of the contents of the includeFiles
# `objectHash`: hash of the object in cache
ManifestEntry = namedtuple('ManifestEntry', ['includeFiles', 'includesContentHash', 'objectHash'])

CompilerArtifacts = namedtuple('CompilerArtifacts', ['objectFilePath', 'stdout', 'stderr'])

def printBinary(stream, rawData):
    with OUTPUT_LOCK:
        stream.buffer.write(rawData)
        stream.flush()


def basenameWithoutExtension(path):
    basename = os.path.basename(path)
    return os.path.splitext(basename)[0]


def filesBeneath(baseDir):
    for path, _, filenames in WALK(baseDir):
        for filename in filenames:
            yield os.path.join(path, filename)


def childDirectories(path, absolute=True):
    supportsScandir = (LIST != os.listdir) # pylint: disable=comparison-with-callable
    for entry in LIST(path):
        if supportsScandir:
            if entry.is_dir():
                yield entry.path if absolute else entry.name
        else:
            absPath = os.path.join(path, entry)
            if os.path.isdir(absPath):
                yield absPath if absolute else entry


def normalizeBaseDir(baseDir):
    if baseDir:
        baseDir = os.path.normcase(baseDir)
        if baseDir.endswith(os.path.sep):
            baseDir = baseDir[0:-1]
        return baseDir
    else:
        # Converts empty string to None
        return None


def getCachedCompilerConsoleOutput(path):
    try:
        with open(path, 'rb') as f:
            return f.read().decode(CACHE_COMPILER_OUTPUT_STORAGE_CODEC)
    except IOError:
        return ''

def setCachedCompilerConsoleOutput(path, output):
    with open(path, 'wb') as f:
        f.write(output.encode(CACHE_COMPILER_OUTPUT_STORAGE_CODEC))

class IncludeNotFoundException(Exception):
    pass


class CacheLockException(Exception):
    pass


class CompilerFailedException(Exception):
    def __init__(self, exitCode, msgErr, msgOut=""):
        super(CompilerFailedException, self).__init__(msgErr)
        self.exitCode = exitCode
        self.msgOut = msgOut
        self.msgErr = msgErr

    def getReturnTuple(self):
        return self.exitCode, self.msgErr, self.msgOut, False


class LogicException(Exception):
    def __init__(self, message):
        super(LogicException, self).__init__(message)
        self.message = message

    def __str__(self):
        return repr(self.message)


class Manifest:
    def __init__(self, entries=None):
        if entries is None:
            entries = []
        self._entries = entries.copy()

    def entries(self):
        return self._entries

    def addEntry(self, entry):
        """Adds entry at the top of the entries"""
        self._entries.insert(0, entry)

    def touchEntry(self, objectHash):
        """Moves entry in entryIndex position to the top of entries()"""
        entryIndex = next((i for i, e in enumerate(self.entries()) if e.objectHash == objectHash), 0)
        self._entries.insert(0, self._entries.pop(entryIndex))


class ManifestSection:
    def __init__(self, manifestSectionDir):
        self.manifestSectionDir = manifestSectionDir
        self.lock = CacheLock.forPath(self.manifestSectionDir)

    def manifestPath(self, manifestHash):
        return os.path.join(self.manifestSectionDir, manifestHash + ".json")

    def manifestFiles(self):
        return filesBeneath(self.manifestSectionDir)

    def setManifest(self, manifestHash, manifest):
        manifestPath = self.manifestPath(manifestHash)
        printTraceStatement("Writing manifest with manifestHash = {} to {}".format(manifestHash, manifestPath))
        ensureDirectoryExists(self.manifestSectionDir)
        with atomic_write(manifestPath, overwrite=True) as outFile:
            # Converting namedtuple to JSON via OrderedDict preserves key names and keys order
            entries = [e._asdict() for e in manifest.entries()]
            jsonobject = { 'type': manifest.entries()[0].__class__.__name__ , 'entries': entries}
            json.dump(jsonobject, outFile, sort_keys=False, indent=2)

    def getManifest(self, manifestHash):
        fileName = self.manifestPath(manifestHash)
        if not os.path.exists(fileName):
            return None
        try:
            with open(fileName, 'r') as inFile:
                doc = json.load(inFile)
                return Manifest([globals()[doc['type']](**e) for e in doc['entries']])
        except IOError:
            return None
        except ValueError:
            printErrStr("clcache: manifest file %s was broken" % fileName)
            return None

    @staticmethod
    def gen_manifest(e):
        pass

@contextlib.contextmanager
def allSectionsLocked(repository):
    sections = list(repository.sections())
    for section in sections:
        section.lock.acquire()
    try:
        yield
    finally:
        for section in sections:
            section.lock.release()


class ManifestRepository:
    # Bump this counter whenever the current manifest file format changes.
    # E.g. changing the file format from {'oldkey': ...} to {'newkey': ...} requires
    # invalidation, such that a manifest that was stored using the old format is not
    # interpreted using the new format. Instead the old file will not be touched
    # again due to a new manifest hash and is cleaned away after some time.
    MANIFEST_FILE_FORMAT_VERSION = 9

    def __init__(self, manifestsRootDir):
        self._manifestsRootDir = manifestsRootDir

    def section(self, manifestHash):
        return ManifestSection(os.path.join(self._manifestsRootDir, manifestHash[:2]))

    def sections(self):
        return (ManifestSection(path) for path in childDirectories(self._manifestsRootDir))

    def clean(self, maxManifestsSize):
        manifestFileInfos = []
        for section in self.sections():
            for filePath in section.manifestFiles():
                try:
                    manifestFileInfos.append((os.stat(filePath), filePath))
                except OSError:
                    pass

        manifestFileInfos.sort(key=lambda t: t[0].st_atime, reverse=True)

        remainingObjectsSize = 0
        for stat, filepath in manifestFileInfos:
            if remainingObjectsSize + stat.st_size <= maxManifestsSize:
                remainingObjectsSize += stat.st_size
            else:
                os.remove(filepath)
        return remainingObjectsSize

    @staticmethod
    def getManifestHash(compilerBinary, commandLine, sourceFile):
        compilerHash = getCompilerHash(compilerBinary)

        # NOTE: We intentionally do not normalize command line to include
        # preprocessor options.  In direct mode we do not perform preprocessing
        # before cache lookup, so all parameters are important.  One of the few
        # exceptions to this rule is the /MP switch, which only defines how many
        # compiler processes are running simultaneusly.  Arguments that specify
        # the compiler where to find the source files are parsed to replace
        # ocurrences of CLCACHE_BASEDIR by a placeholder.
        arguments, inputFiles = CommandLineAnalyzer.parseArgumentsAndInputFiles(commandLine)
        collapseBasedirInCmdPath = lambda path: collapseBasedirToPlaceholder(os.path.normcase(os.path.abspath(path)))

        commandLine = []
        argumentsWithPaths = ("AI", "I", "FU")
        for k in sorted(arguments.keys()):
            if k in argumentsWithPaths:
                commandLine.extend(["/" + k + collapseBasedirInCmdPath(arg) for arg in arguments[k]])
            else:
                commandLine.extend(["/" + k + arg for arg in arguments[k]])

        commandLine.extend(collapseBasedirInCmdPath(arg) for arg in inputFiles)

        additionalData = "{}|{}|{}".format(
            compilerHash, commandLine, ManifestRepository.MANIFEST_FILE_FORMAT_VERSION)
        return getFileHash(sourceFile, additionalData)

    @staticmethod
    def getIncludesContentHashForFiles(includes):
        try:
            listOfHashes = getFileHashes(includes)
        except FileNotFoundError:
            raise IncludeNotFoundException

        return ManifestRepository.getIncludesContentHashForHashes(listOfHashes)

    @staticmethod
    def getIncludesContentHashForHashes(listOfHashes):
        return HashAlgorithm(','.join(listOfHashes).encode()).hexdigest()


class CacheLock:
    """ Implements a lock for the object cache which
    can be used in 'with' statements. """
    INFINITE = 0xFFFFFFFF
    WAIT_ABANDONED_CODE = 0x00000080
    WAIT_TIMEOUT_CODE = 0x00000102

    def __init__(self, mutexName, timeoutMs):
        self._mutexName = 'Local\\' + mutexName
        self._mutex = None
        self._timeoutMs = timeoutMs

    def createMutex(self):
        self._mutex = windll.kernel32.CreateMutexW(
            None,
            wintypes.BOOL(False),
            self._mutexName)
        assert self._mutex

    def __enter__(self):
        self.acquire()

    def __exit__(self, typ, value, traceback):
        self.release()

    def __del__(self):
        if self._mutex:
            windll.kernel32.CloseHandle(self._mutex)

    def acquire(self):
        if not self._mutex:
            self.createMutex()
        result = windll.kernel32.WaitForSingleObject(
            self._mutex, wintypes.INT(self._timeoutMs))
        if result not in [0, self.WAIT_ABANDONED_CODE]:
            if result == self.WAIT_TIMEOUT_CODE:
                errorString = \
                    'Failed to acquire lock {} after {}ms; ' \
                    'try setting CLCACHE_OBJECT_CACHE_TIMEOUT_MS environment variable to a larger value.'.format(
                        self._mutexName, self._timeoutMs)
            else:
                errorString = 'Error! WaitForSingleObject returns {result}, last error {error}'.format(
                    result=result,
                    error=windll.kernel32.GetLastError())
            raise CacheLockException(errorString)

    def release(self):
        windll.kernel32.ReleaseMutex(self._mutex)

    @staticmethod
    def forPath(path):
        timeoutMs = int(os.environ.get('CLCACHE_OBJECT_CACHE_TIMEOUT_MS', 10 * 1000))
        lockName = path.replace(':', '-').replace('\\', '-')
        return CacheLock(lockName, timeoutMs)


class CompilerArtifactsSection:
    OBJECT_FILE = 'object'
    STDOUT_FILE = 'output.txt'
    STDERR_FILE = 'stderr.txt'

    def __init__(self, compilerArtifactsSectionDir):
        self.compilerArtifactsSectionDir = compilerArtifactsSectionDir
        self.lock = CacheLock.forPath(self.compilerArtifactsSectionDir)

    def cacheEntryDir(self, key):
        return os.path.join(self.compilerArtifactsSectionDir, key)

    def cacheEntries(self):
        return childDirectories(self.compilerArtifactsSectionDir, absolute=False)

    def cachedObjectName(self, key):
        return os.path.join(self.cacheEntryDir(key), CompilerArtifactsSection.OBJECT_FILE)

    def hasEntry(self, key):
        return os.path.exists(self.cacheEntryDir(key))

    def setEntry(self, key, artifacts):
        cacheEntryDir = self.cacheEntryDir(key)
        # Write new files to a temporary directory
        tempEntryDir = cacheEntryDir + '.new'
        # Remove any possible left-over in tempEntryDir from previous executions
        rmtree(tempEntryDir, ignore_errors=True)
        ensureDirectoryExists(tempEntryDir)
        if artifacts.objectFilePath is not None:
            dstFilePath = os.path.join(tempEntryDir, CompilerArtifactsSection.OBJECT_FILE)
            copyOrLink(artifacts.objectFilePath, dstFilePath, True)
            size = os.path.getsize(dstFilePath)
        setCachedCompilerConsoleOutput(os.path.join(tempEntryDir, CompilerArtifactsSection.STDOUT_FILE),
                                       artifacts.stdout)
        if artifacts.stderr != '':
            setCachedCompilerConsoleOutput(os.path.join(tempEntryDir, CompilerArtifactsSection.STDERR_FILE),
                                           artifacts.stderr)
        # Replace the full cache entry atomically
        os.replace(tempEntryDir, cacheEntryDir)
        return size

    def getEntry(self, key):
        assert self.hasEntry(key)
        cacheEntryDir = self.cacheEntryDir(key)
        return CompilerArtifacts(
            os.path.join(cacheEntryDir, CompilerArtifactsSection.OBJECT_FILE),
            getCachedCompilerConsoleOutput(os.path.join(cacheEntryDir, CompilerArtifactsSection.STDOUT_FILE)),
            getCachedCompilerConsoleOutput(os.path.join(cacheEntryDir, CompilerArtifactsSection.STDERR_FILE))
            )

    def setEntry2(self, key, output):
        cacheEntryDir = self.cacheEntryDir(key)
        tempEntryDir = cacheEntryDir + '.{}'.format(os.getpid())
        dstFilePath = os.path.join(tempEntryDir, CompilerArtifactsSection.OBJECT_FILE)
        ensureDirectoryExists(tempEntryDir)
        copyOrLink(output, dstFilePath, True)
        size = os.path.getsize(dstFilePath)
        try:
            os.replace(tempEntryDir, cacheEntryDir)
            if os.path.exists(cacheEntryDir):
                printTraceStatement('Cache  created: "{}"'.format(cacheEntryDir))
        except:
            size = 0
            rmtree(tempEntryDir, ignore_errors=True)
        return size

    def getEntry2(self, key, targetpath):
        cacheEntryDir = self.cacheEntryDir(key)
        src = os.path.join(cacheEntryDir, CompilerArtifactsSection.OBJECT_FILE)
        copyOrLink(src, targetpath)
        return targetpath


class CompilerArtifactsRepository:
    def __init__(self, compilerArtifactsRootDir):
        self._compilerArtifactsRootDir = compilerArtifactsRootDir

    def section(self, key):
        return CompilerArtifactsSection(os.path.join(self._compilerArtifactsRootDir, key[:2]))

    def sections(self):
        return (CompilerArtifactsSection(path) for path in childDirectories(self._compilerArtifactsRootDir))

    def removeEntry(self, keyToBeRemoved):
        compilerArtifactsDir = self.section(keyToBeRemoved).cacheEntryDir(keyToBeRemoved)
        rmtree(compilerArtifactsDir, ignore_errors=True)

    def clean(self, maxCompilerArtifactsSize):
        objectInfos = []
        for section in self.sections():
            for cachekey in section.cacheEntries():
                try:
                    objectStat = os.stat(section.cachedObjectName(cachekey))
                    objectInfos.append((objectStat, cachekey))
                except OSError:
                    pass

        objectInfos.sort(key=lambda t: t[0].st_atime)

        # compute real current size to fix up the stored cacheSize
        currentSizeObjects = sum(x[0].st_size for x in objectInfos)

        removedItems = 0
        for stat, cachekey in objectInfos:
            self.removeEntry(cachekey)
            removedItems += 1
            currentSizeObjects -= stat.st_size
            if currentSizeObjects < maxCompilerArtifactsSize:
                break

        return len(objectInfos)-removedItems, currentSizeObjects

    @staticmethod
    def computeKeyDirect(manifestHash, includesContentHash):
        # We must take into account manifestHash to avoid
        # collisions when different source files use the same
        # set of includes.
        return getStringHash(manifestHash + includesContentHash)

    @staticmethod
    def computeKeyNodirect(compilerBinary, commandLine, environment):
        ppcmd = ["/EP"] + [arg for arg in commandLine if arg not in ("-c", "/c")]

        returnCode, preprocessedSourceCode, ppStderrBinary = \
            invokeRealCompiler(compilerBinary, ppcmd, captureOutput=True, outputAsString=False, environment=environment)

        if returnCode != 0:
            errMsg = ppStderrBinary.decode(CL_DEFAULT_CODEC) + "\nclcache: preprocessor failed"
            raise CompilerFailedException(returnCode, errMsg)

        compilerHash = getCompilerHash(compilerBinary)
        normalizedCmdLine = CompilerArtifactsRepository._normalizedCommandLine(commandLine)

        h = HashAlgorithm()
        h.update(compilerHash.encode("UTF-8"))
        h.update(' '.join(normalizedCmdLine).encode("UTF-8"))
        h.update(preprocessedSourceCode)
        return h.hexdigest()

    @staticmethod
    def _normalizedCommandLine(cmdline):
        # Remove all arguments from the command line which only influence the
        # preprocessor; the preprocessor's output is already included into the
        # hash sum so we don't have to care about these switches in the
        # command line as well.
        argsToStrip = ("AI", "C", "E", "P", "FI", "u", "X",
                       "FU", "D", "EP", "Fx", "U", "I")

        # Also remove the switch for specifying the output file name; we don't
        # want two invocations which are identical except for the output file
        # name to be treated differently.
        argsToStrip += ("Fo",)

        # Also strip the switch for specifying the number of parallel compiler
        # processes to use (when specifying multiple source files on the
        # command line).
        argsToStrip += ("MP",)

        return [arg for arg in cmdline
                if not (arg[0] in "/-" and arg[1:].startswith(argsToStrip))]

class CacheFileStrategy:
    def __init__(self, cacheDirectory=None):
        self.dir = cacheDirectory
        if not self.dir:
            try:
                self.dir = os.environ["CLCACHE_DIR"]
            except KeyError:
                self.dir = os.path.join(os.path.expanduser("~"), "clcache")

        manifestsRootDir = os.path.join(self.dir, "manifests")
        ensureDirectoryExists(manifestsRootDir)
        self.manifestRepository = ManifestRepository(manifestsRootDir)

        compilerArtifactsRootDir = os.path.join(self.dir, "objects")
        ensureDirectoryExists(compilerArtifactsRootDir)
        self.compilerArtifactsRepository = CompilerArtifactsRepository(compilerArtifactsRootDir)

        self.configuration = Configuration(os.path.join(self.dir, "config.txt"))
        self.statistics = Statistics(os.path.join(self.dir, "stats.txt"))

    def __str__(self):
        return "Disk cache at {}".format(self.dir)

    @property # type: ignore
    @contextlib.contextmanager
    def lock(self):
        with allSectionsLocked(self.manifestRepository), \
             allSectionsLocked(self.compilerArtifactsRepository), \
             self.statistics.lock:
            yield

    def lockFor(self, key):
        assert isinstance(self.compilerArtifactsRepository.section(key).lock, CacheLock)
        return self.compilerArtifactsRepository.section(key).lock

    def manifestLockFor(self, key):
        return self.manifestRepository.section(key).lock

    def getEntry(self, key):
        return self.compilerArtifactsRepository.section(key).getEntry(key)

    def setEntry(self, key, value):
        return self.compilerArtifactsRepository.section(key).setEntry(key, value)

    def getEntry2(self, key, p):
        return self.compilerArtifactsRepository.section(key).getEntry2(key, p)

    def setEntry2(self, key, value):
        return self.compilerArtifactsRepository.section(key).setEntry2(key, value)

    def pathForObject(self, key):
        return self.compilerArtifactsRepository.section(key).cachedObjectName(key)

    def directoryForCache(self, key):
        return self.compilerArtifactsRepository.section(key).cacheEntryDir(key)

    def deserializeCacheEntry(self, key, objectData):
        path = self.pathForObject(key)
        ensureDirectoryExists(self.directoryForCache(key))
        with open(path, 'wb') as f:
            f.write(objectData)
        return path

    def hasEntry(self, cachekey):
        return self.compilerArtifactsRepository.section(cachekey).hasEntry(cachekey)

    def setManifest(self, manifestHash, manifest):
        self.manifestRepository.section(manifestHash).setManifest(manifestHash, manifest)

    def getManifest(self, manifestHash):
        return self.manifestRepository.section(manifestHash).getManifest(manifestHash)

    def clear(self, stats):
        rmtree(self.manifestRepository._manifestsRootDir, ignore_errors=True)
        rmtree(self.compilerArtifactsRepository._compilerArtifactsRootDir, ignore_errors=True)
        stats.setCacheSize(0)
        stats.setNumCacheEntries(0)

    def clean(self, stats, maximumSize):
        currentSize = stats.currentCacheSize()
        if currentSize < maximumSize:
            return

        # Free at least 10% to avoid cleaning up too often which
        # is a big performance hit with large caches.
        effectiveMaximumSizeOverall = maximumSize * 0.9

        # Split limit in manifests (10 %) and objects (90 %)
        effectiveMaximumSizeManifests = effectiveMaximumSizeOverall * 0.1
        effectiveMaximumSizeObjects = effectiveMaximumSizeOverall - effectiveMaximumSizeManifests

        # Clean manifests
        currentSizeManifests = self.manifestRepository.clean(effectiveMaximumSizeManifests)

        # Clean artifacts
        currentCompilerArtifactsCount, currentCompilerArtifactsSize = self.compilerArtifactsRepository.clean(
            effectiveMaximumSizeObjects)

        stats.setCacheSize(currentCompilerArtifactsSize + currentSizeManifests)
        stats.setNumCacheEntries(currentCompilerArtifactsCount)


class Cache:
    def __init__(self, cacheDirectory=None):
        memcachd = os.environ.get("CLCACHE_MEMCACHED")
        if memcachd:
            from .storage import CacheMemcacheStrategy
            printTraceStatement("Use memcache:{}".format(memcachd))
            self.strategy = CacheMemcacheStrategy(memcachd, cacheDirectory=cacheDirectory)
        else:
            self.strategy = CacheFileStrategy(cacheDirectory=cacheDirectory)

    def __str__(self):
        return str(self.strategy)

    @property
    def lock(self):
        return self.strategy.lock

    @contextlib.contextmanager
    def manifestLockFor(self, key):
        with self.strategy.manifestLockFor(key):
            yield

    @property
    def configuration(self):
        return self.strategy.configuration

    @property
    def statistics(self):
        return self.strategy.statistics

    def clean(self, stats, maximumSize):
        return self.strategy.clean(stats, maximumSize)

    def clear(self, stats):
        return self.strategy.clear(stats)

    @contextlib.contextmanager
    def lockFor(self, key):
        with self.strategy.lockFor(key):
            yield

    def getEntry(self, key):
        return self.strategy.getEntry(key)

    def setEntry(self, key, value):
        return self.strategy.setEntry(key, value)

    def getEntry2(self, key, p):
        return self.strategy.getEntry2(key, p)

    def setEntry2(self, key, value):
        return self.strategy.setEntry2(key, value)

    def hasEntry(self, cachekey):
        return self.strategy.hasEntry(cachekey)

    def setManifest(self, manifestHash, manifest):
        self.strategy.setManifest(manifestHash, manifest)

    def getManifest(self, manifestHash):
        return self.strategy.getManifest(manifestHash)


class PersistentJSONDict(defaultdict):
    def __init__(self, fileName):
        super().__init__(int)
        self._dirty = False
        self._fileName = fileName
        try:
            with open(self._fileName, 'r') as f:
                self.update(json.load(f))
        except IOError:
            pass
        except ValueError:
            printErrStr("clcache: persistent json file %s was broken" % fileName)

    def _save(self):
        try:
            with atomic_write(self._fileName, overwrite=True) as f:
                json.dump(self, f, sort_keys=False, indent=4)
            return True
        except:
            return False

    def save(self):
        if not self._dirty: return
        while not self._save():
            printTraceStatement("Failed to save Json Dict: {}".format(self._fileName))
            time.sleep(1.0)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._dirty = True


class Configuration:
    _defaultValues = {"MaximumCacheSize": 1073741824} # 1 GiB

    def __init__(self, configurationFile):
        self._configurationFile = configurationFile
        self._cfg = None

    def __enter__(self):
        self._cfg = PersistentJSONDict(self._configurationFile)
        for setting, defaultValue in self._defaultValues.items():
            if setting not in self._cfg:
                self._cfg[setting] = defaultValue
        return self

    def __exit__(self, typ, value, traceback):
        # Does not write to disc when unchanged
        self._cfg.save()

    def maximumCacheSize(self):
        return self._cfg["MaximumCacheSize"]

    def setMaximumCacheSize(self, size):
        self._cfg["MaximumCacheSize"] = size


class StatisticsMixin:
    NEW_KEYS = {
        "PreInvokeLauchCount",
        "PostInvokeLauchCount",
        "PreInvokeExitCount",
        "PostInvokeExitCount",
        "PreInvokeExecutionTime",
        "PreInvokeCpuTime",
        "PostInvokeExecutionTime",
        "PostInvokeCpuTime",
        "EntryHits",
        "HashHits",
        "AllMiss",
        "HashMiss",
        "EntryMiss",
        "CppRecompiledFromPchChange",
        "PchRecompiledFromCppChange",
        'DuplicateObjHashFound',
        'FailureAddObj',
        'FailureGetObj',
        'AddObjCount',
        'AddObjSize',
        'AddEntryCount',
        'IdenticalEntryCount',
        'DuplicateManifestEntryFound',
        'CleanUpCount',
        'DependencyMissingCount',
        'ProjectHits',
        'ProjectMiss',
    }
    NEW_PERSIST_KEYS = {
        'ManifestCount',
        'ManifestEntryCount',
    }
    _stats = defaultdict(int)

    @classmethod
    def init_methods(cls):
        for k in cls.NEW_KEYS | cls.NEW_PERSIST_KEYS:
            cls.define_method(k)

    @classmethod
    def define_method(cls, k):
        @property
        def getter(self):
            return self._stats[k]

        def setter(self, v):
            self._stats[k] = v

        def inc(self, v=1):
            self._stats[k] += v

        #getter.__name__ = k
        setter.__name__ = 'set{}'.format(k)
        inc.__name__ = 'inc{}'.format(k)
        setattr(cls, k, getter)
        setattr(cls, setter.__name__, setter)
        setattr(cls, inc.__name__, inc)


StatisticsMixin.init_methods()

class Statistics(StatisticsMixin):
    CALLS_WITH_INVALID_ARGUMENT = "CallsWithInvalidArgument"
    CALLS_WITHOUT_SOURCE_FILE = "CallsWithoutSourceFile"
    CALLS_WITH_MULTIPLE_SOURCE_FILES = "CallsWithMultipleSourceFiles"
    CALLS_WITH_PCH = "CallsWithPch"
    CALLS_FOR_LINKING = "CallsForLinking"
    CALLS_FOR_EXTERNAL_DEBUG_INFO = "CallsForExternalDebugInfo"
    CALLS_FOR_PREPROCESSING = "CallsForPreprocessing"
    CACHE_HITS = "CacheHits"
    CACHE_MISSES = "CacheMisses"
    EVICTED_MISSES = "EvictedMisses"
    HEADER_CHANGED_MISSES = "HeaderChangedMisses"
    SOURCE_CHANGED_MISSES = "SourceChangedMisses"
    CACHE_ENTRIES = "CacheEntries"
    CACHE_SIZE = "CacheSize"

    RESETTABLE_KEYS = {
        CALLS_WITH_INVALID_ARGUMENT,
        CALLS_WITHOUT_SOURCE_FILE,
        CALLS_WITH_MULTIPLE_SOURCE_FILES,
        CALLS_WITH_PCH,
        CALLS_FOR_LINKING,
        CALLS_FOR_EXTERNAL_DEBUG_INFO,
        CALLS_FOR_PREPROCESSING,
        CACHE_HITS,
        CACHE_MISSES,
        EVICTED_MISSES,
        HEADER_CHANGED_MISSES,
        SOURCE_CHANGED_MISSES,
    }
    NON_RESETTABLE_KEYS = {
        CACHE_ENTRIES,
        CACHE_SIZE,
    }

    def __init__(self, statsFile):
        if statsFile is None:
            pass
        else:
            self._statsFile = statsFile
            self._stats = None
            self.lock = CacheLock.forPath(self._statsFile)

    def __enter__(self):
        if not self._stats:
            self._stats = PersistentJSONDict(self._statsFile)
        # for k in Statistics.RESETTABLE_KEYS | Statistics.NON_RESETTABLE_KEYS:
        #     if k not in self._stats:
        #         self._stats[k] = 0
        return self

    def __exit__(self, typ, value, traceback):
        # Does not write to disc when unchanged
        self._stats.save()
        self._stats = None

    def updateStats(self, other):
        for k in other._stats.keys():
            self._stats[k] += other._stats[k]

    def __eq__(self, other):
        return type(self) is type(other) and self.__dict__ == other.__dict__

    def numCallsWithInvalidArgument(self):
        return self._stats[Statistics.CALLS_WITH_INVALID_ARGUMENT]

    def registerCallWithInvalidArgument(self):
        self._stats[Statistics.CALLS_WITH_INVALID_ARGUMENT] += 1

    def numCallsWithoutSourceFile(self):
        return self._stats[Statistics.CALLS_WITHOUT_SOURCE_FILE]

    def registerCallWithoutSourceFile(self):
        self._stats[Statistics.CALLS_WITHOUT_SOURCE_FILE] += 1

    def numCallsWithMultipleSourceFiles(self):
        return self._stats[Statistics.CALLS_WITH_MULTIPLE_SOURCE_FILES]

    def registerCallWithMultipleSourceFiles(self):
        self._stats[Statistics.CALLS_WITH_MULTIPLE_SOURCE_FILES] += 1

    def numCallsWithPch(self):
        return self._stats[Statistics.CALLS_WITH_PCH]

    def registerCallWithPch(self):
        self._stats[Statistics.CALLS_WITH_PCH] += 1

    def numCallsForLinking(self):
        return self._stats[Statistics.CALLS_FOR_LINKING]

    def registerCallForLinking(self):
        self._stats[Statistics.CALLS_FOR_LINKING] += 1

    def numCallsForExternalDebugInfo(self):
        return self._stats[Statistics.CALLS_FOR_EXTERNAL_DEBUG_INFO]

    def registerCallForExternalDebugInfo(self):
        self._stats[Statistics.CALLS_FOR_EXTERNAL_DEBUG_INFO] += 1

    def numEvictedMisses(self):
        return self._stats[Statistics.EVICTED_MISSES]

    def registerEvictedMiss(self):
        self.registerCacheMiss()
        self._stats[Statistics.EVICTED_MISSES] += 1

    def numHeaderChangedMisses(self):
        return self._stats[Statistics.HEADER_CHANGED_MISSES]

    def registerHeaderChangedMiss(self):
        self.registerCacheMiss()
        self._stats[Statistics.HEADER_CHANGED_MISSES] += 1

    def numSourceChangedMisses(self):
        return self._stats[Statistics.SOURCE_CHANGED_MISSES]

    def registerSourceChangedMiss(self):
        self.registerCacheMiss()
        self._stats[Statistics.SOURCE_CHANGED_MISSES] += 1

    def numCacheEntries(self):
        return self._stats[Statistics.CACHE_ENTRIES]

    def setNumCacheEntries(self, number):
        self._stats[Statistics.CACHE_ENTRIES] = number

    def registerCacheEntry(self, size):
        self._stats[Statistics.CACHE_ENTRIES] += 1
        self._stats[Statistics.CACHE_SIZE] += size

    def unregisterCacheEntry(self, size):
        self._stats[Statistics.CACHE_ENTRIES] -= 1
        self._stats[Statistics.CACHE_SIZE] -= size

    def currentCacheSize(self):
        return self._stats[Statistics.CACHE_SIZE]

    def setCacheSize(self, size):
        self._stats[Statistics.CACHE_SIZE] = size

    def numCacheHits(self):
        return self._stats[Statistics.CACHE_HITS]

    def registerCacheHit(self):
        self._stats[Statistics.CACHE_HITS] += 1

    def numCacheMisses(self):
        return self._stats[Statistics.CACHE_MISSES]

    def registerCacheMiss(self):
        self._stats[Statistics.CACHE_MISSES] += 1

    def numCallsForPreprocessing(self):
        return self._stats[Statistics.CALLS_FOR_PREPROCESSING]

    def registerCallForPreprocessing(self):
        self._stats[Statistics.CALLS_FOR_PREPROCESSING] += 1

    def resetCounters(self):
        for k in (Statistics.RESETTABLE_KEYS | self.NEW_KEYS) & set( self._stats.keys()):
            self._stats[k] = 0


class AnalysisError(Exception):
    pass


class NoSourceFileError(AnalysisError):
    pass


class MultipleSourceFilesComplexError(AnalysisError):
    pass


class CalledForLinkError(AnalysisError):
    pass


class CalledWithPchError(AnalysisError):
    pass


class ExternalDebugInfoError(AnalysisError):
    pass


class CalledForPreprocessingError(AnalysisError):
    pass


class InvalidArgumentError(AnalysisError):
    pass


@functools.lru_cache(maxsize=1)
def getCompilerHash(compilerBinary):
    stat = os.stat(compilerBinary)
    data = '|'.join([
        str(stat.st_mtime),
        str(stat.st_size),
        compilerBinary,
        ])
    hasher = HashAlgorithm()
    hasher.update(data.encode("UTF-8"))
    return hasher.hexdigest()


def getFileHashes(filePaths):
    if 'CLCACHE_SERVER' in os.environ:
        pipeName = r'\\.\pipe\clcache_srv'
        while True:
            try:
                with open(pipeName, 'w+b') as f:
                    f.write('\n'.join(filePaths).encode('utf-8'))
                    f.write(b'\x00')
                    response = f.read()
                    if response.startswith(b'!'):
                        raise pickle.loads(response[1:-1])
                    return response[:-1].decode('utf-8').splitlines()
            except OSError as e:
                if e.errno == errno.EINVAL and windll.kernel32.GetLastError() == ERROR_PIPE_BUSY:
                    windll.kernel32.WaitNamedPipeW(pipeName, NMPWAIT_WAIT_FOREVER)
                else:
                    raise
    else:
        return [getFileHash(filePath) for filePath in filePaths]


def getFileHash(filePath, additionalData=None):
    hasher = HashAlgorithm()
    with open(filePath, 'rb') as inFile:
        hasher.update(inFile.read())
    if additionalData is not None:
        # Encoding of this additional data does not really matter
        # as long as we keep it fixed, otherwise hashes change.
        # The string should fit into ASCII, so UTF8 should not change anything
        hasher.update(additionalData.encode("UTF-8"))
    return hasher.hexdigest()


def getStringHash(dataString):
    hasher = HashAlgorithm()
    hasher.update(dataString.encode("UTF-8"))
    return hasher.hexdigest()


def expandBasedirPlaceholder(path):
    baseDir = normalizeBaseDir(os.environ.get('CLCACHE_BASEDIR'))
    if path.startswith(BASEDIR_REPLACEMENT):
        if not baseDir:
            raise LogicException('No CLCACHE_BASEDIR set, but found relative path ' + path)
        return path.replace(BASEDIR_REPLACEMENT, baseDir, 1)
    else:
        return path


def collapseBasedirToPlaceholder(path):
    baseDir = normalizeBaseDir(os.environ.get('CLCACHE_BASEDIR'))
    if baseDir is None:
        return path
    else:
        assert path == os.path.normcase(path)
        assert baseDir == os.path.normcase(baseDir)
        if path.startswith(baseDir):
            return path.replace(baseDir, BASEDIR_REPLACEMENT, 1)
        else:
            return path


def ensureDirectoryExists(path):
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise


def copyOrLink(srcFilePath, dstFilePath, writeCache=False):
    ensureDirectoryExists(os.path.dirname(os.path.abspath(dstFilePath)))

    if "CLCACHE_HARDLINK" in os.environ:
        ret = windll.kernel32.CreateHardLinkW(str(dstFilePath), str(srcFilePath), None)
        if ret != 0:
            # Touch the time stamp of the new link so that the build system
            # doesn't confused by a potentially old time on the file. The
            # hard link gets the same timestamp as the cached file.
            # Note that touching the time stamp of the link also touches
            # the time stamp on the cache (and hence on all over hard
            # links). This shouldn't be a problem though.
            os.utime(dstFilePath, None)
            return

    # If hardlinking fails for some reason (or it's not enabled), just
    # fall back to moving bytes around. Always to a temporary path first to
    # lower the chances of corrupting it.
    tempDst = dstFilePath + '.tmp'

    if "CLCACHE_COMPRESS" in os.environ:
        if "CLCACHE_COMPRESSLEVEL" in os.environ:
            compress = int(os.environ["CLCACHE_COMPRESSLEVEL"])
        else:
            compress = 6

        if writeCache is True:
            with open(srcFilePath, 'rb') as fileIn, gzip.open(tempDst, 'wb', compress) as fileOut:
                copyfileobj(fileIn, fileOut)
        else:
            with gzip.open(srcFilePath, 'rb', compress) as fileIn, open(tempDst, 'wb') as fileOut:
                copyfileobj(fileIn, fileOut)
    else:
        copyfile(srcFilePath, tempDst)
    os.replace(tempDst, dstFilePath)


def myExecutablePath():
    assert hasattr(sys, "frozen"), "is not frozen by py2exe"
    return sys.executable.upper()


def findCompilerBinary():
    if "CLCACHE_CL" in os.environ:
        path = os.environ["CLCACHE_CL"]
        if os.path.basename(path) == path:
            path = which(path)

        return path if os.path.exists(path) else None

    frozenByPy2Exe = hasattr(sys, "frozen")

    for p in os.environ["PATH"].split(os.pathsep):
        path = os.path.join(p, "cl.exe")
        if os.path.exists(path):
            if not frozenByPy2Exe:
                return path

            # Guard against recursively calling ourselves
            if path.upper() != myExecutablePath():
                return path
    return None

OutputDebugStringW = windll.kernel32.OutputDebugStringW
WriteFile = windll.kernel32.WriteFile
CreateFileW = windll.kernel32.CreateFileW

def shared_append(path: str, msg: str):
    msg = '{}\n'.format(msg).encode('utf-8')
    handle = shared_append.handle if hasattr(shared_append,'handle') else \
    CreateFileW(
        create_unicode_buffer(path),
        0x00100000 | 4,     #FILE_APPEND_DATA | SYNCHRONIZE
        2 | 1,  # FILE_SHARE_READ | FILE_SHARE_WRITE
        None,
        4,      # OPEN_ALWAYS
        128,    # FILE_ATTRIBUTE_NORMAL
        None)
    shared_append.handle = handle
    dw = wintypes.DWORD()
    r = WriteFile(handle, msg, len(msg), byref(dw), None)
    if not r:
        OutputDebugStringW("shared_append Failed")
    return r

g_log_mem = "CLCACHE_LOG" in os.environ
g_log_tofile = g_log_mem and not os.environ.get("CLCACHE_LOG").isdigit() and os.environ.get("CLCACHE_LOG")

g_isaty = False
try:
    g_isaty = sys.stdout.isatty()
except: pass

def printTraceStatement(msg: str) -> None:
    if g_log_tofile:
        shared_append(g_log_tofile, '[{}] {}'.format(os.getpid(),msg))
    elif g_log_mem:
        OutputDebugStringW(msg)
        if not g_isaty:
            print(msg)
        else:
            with OUTPUT_LOCK:
                print(msg)


class CommandLineTokenizer:
    def __init__(self, content):
        self.argv = []
        self._content = content
        self._pos = 0
        self._token = ''
        self._parser = self._initialState

        while self._pos < len(self._content):
            self._parser = self._parser(self._content[self._pos])
            self._pos += 1

        if self._token:
            self.argv.append(self._token)

    def _initialState(self, currentChar):
        if currentChar.isspace():
            return self._initialState

        if currentChar == '"':
            return self._quotedState

        if currentChar == '\\':
            self._parseBackslash()
            return self._unquotedState

        self._token += currentChar
        return self._unquotedState

    def _unquotedState(self, currentChar):
        if currentChar.isspace():
            self.argv.append(self._token)
            self._token = ''
            return self._initialState

        if currentChar == '"':
            return self._quotedState

        if currentChar == '\\':
            self._parseBackslash()
            return self._unquotedState

        self._token += currentChar
        return self._unquotedState

    def _quotedState(self, currentChar):
        if currentChar == '"':
            return self._unquotedState

        if currentChar == '\\':
            self._parseBackslash()
            return self._quotedState

        self._token += currentChar
        return self._quotedState

    def _parseBackslash(self):
        numBackslashes = 0
        while self._pos < len(self._content) and self._content[self._pos] == '\\':
            self._pos += 1
            numBackslashes += 1

        followedByDoubleQuote = self._pos < len(self._content) and self._content[self._pos] == '"'
        if followedByDoubleQuote:
            self._token += '\\' * (numBackslashes // 2)
            if numBackslashes % 2 == 0:
                self._pos -= 1
            else:
                self._token += '"'
        else:
            self._token += '\\' * numBackslashes
            self._pos -= 1

@functools.lru_cache(maxsize=1024)
def splitCommandsFile(content):
    return CommandLineTokenizer(content).argv


def expandCommandLine(cmdline):
    ret = []

    for arg in cmdline:
        if arg[0] == '@':
            includeFile = arg[1:]
            includeFileContents = read_file(includeFile)

            ret.extend(expandCommandLine(splitCommandsFile(includeFileContents.strip())))
        else:
            ret.append(arg)

    return ret


def read_file(includeFile):
    with open(includeFile, 'rb') as f:
        rawBytes = f.read()
    encoding = None
    bomToEncoding = {
        codecs.BOM_UTF32_BE: 'utf-32-be',
        codecs.BOM_UTF32_LE: 'utf-32-le',
        codecs.BOM_UTF16_BE: 'utf-16-be',
        codecs.BOM_UTF16_LE: 'utf-16-le',
    }
    for bom, enc in bomToEncoding.items():
        if rawBytes.startswith(bom):
            encoding = enc
            rawBytes = rawBytes[len(bom):]
            break
    if encoding:
        includeFileContents = rawBytes.decode(encoding)
    else:
        includeFileContents = rawBytes.decode("UTF-8")
    return includeFileContents


def extendCommandLineFromEnvironment(cmdLine, environment):
    remainingEnvironment = environment.copy()

    prependCmdLineString = remainingEnvironment.pop('CL', None)
    if prependCmdLineString is not None:
        cmdLine = splitCommandsFile(prependCmdLineString.strip()) + cmdLine

    appendCmdLineString = remainingEnvironment.pop('_CL_', None)
    if appendCmdLineString is not None:
        cmdLine = cmdLine + splitCommandsFile(appendCmdLineString.strip())

    return cmdLine, remainingEnvironment


class Argument:
    def __init__(self, name):
        self.name = name

    def __len__(self):
        return len(self.name)

    def __str__(self):
        return "/" + self.name

    def __eq__(self, other):
        return type(self) == type(other) and self.name == other.name

    def __hash__(self):
        key = (type(self), self.name)
        return hash(key)


# /NAMEparameter (no space, required parameter).
class ArgumentT1(Argument):
    pass


# /NAME[parameter] (no space, optional parameter)
class ArgumentT2(Argument):
    pass


# /NAME[ ]parameter (optional space)
class ArgumentT3(Argument):
    pass


# /NAME parameter (required space)
class ArgumentT4(Argument):
    pass


class CommandLineAnalyzer:

    @staticmethod
    def _getParameterizedArgumentType(cmdLineArgument):
        argumentsWithParameter = {
            # /NAMEparameter
            ArgumentT1('Ob'), ArgumentT1('Yl'), ArgumentT1('Zm'),
            # /NAME[parameter]
            ArgumentT2('doc'), ArgumentT2('FA'), ArgumentT2('FR'), ArgumentT2('Fr'),
            ArgumentT2('Gs'), ArgumentT2('MP'), ArgumentT2('Yc'), ArgumentT2('Yu'),
            ArgumentT2('Zp'), ArgumentT2('Fa'), ArgumentT2('Fd'), ArgumentT2('Fe'),
            ArgumentT2('Fi'), ArgumentT2('Fm'), ArgumentT2('Fo'), ArgumentT2('Fp'),
            ArgumentT2('Wv'),
            # /NAME[ ]parameter
            ArgumentT3('AI'), ArgumentT3('D'), ArgumentT3('Tc'), ArgumentT3('Tp'),
            ArgumentT3('FI'), ArgumentT3('U'), ArgumentT3('I'), ArgumentT3('F'),
            ArgumentT3('FU'), ArgumentT3('w1'), ArgumentT3('w2'), ArgumentT3('w3'),
            ArgumentT3('w4'), ArgumentT3('wd'), ArgumentT3('we'), ArgumentT3('wo'),
            ArgumentT3('V'),
            # /NAME parameter
        }
        # Sort by length to handle prefixes
        argumentsWithParameterSorted = sorted(argumentsWithParameter, key=len, reverse=True)
        for arg in argumentsWithParameterSorted:
            if cmdLineArgument.startswith(arg.name, 1):
                return arg
        return None

    @staticmethod
    def parseArgumentsAndInputFiles(cmdline):
        arguments = defaultdict(list)
        inputFiles = []
        i = 0
        while i < len(cmdline):
            cmdLineArgument = cmdline[i]

            # Plain arguments starting with / or -
            if cmdLineArgument.startswith('/') or cmdLineArgument.startswith('-'):
                arg = CommandLineAnalyzer._getParameterizedArgumentType(cmdLineArgument)
                if arg is not None:
                    if isinstance(arg, ArgumentT1):
                        value = cmdLineArgument[len(arg) + 1:]
                        if not value:
                            raise InvalidArgumentError("Parameter for {} must not be empty".format(arg))
                    elif isinstance(arg, ArgumentT2):
                        value = cmdLineArgument[len(arg) + 1:]
                    elif isinstance(arg, ArgumentT3):
                        value = cmdLineArgument[len(arg) + 1:]
                        if not value:
                            value = cmdline[i + 1]
                            i += 1
                    elif isinstance(arg, ArgumentT4):
                        value = cmdline[i + 1]
                        i += 1
                    else:
                        raise AssertionError("Unsupported argument type.")

                    arguments[arg.name].append(value)
                else:
                    argumentName = cmdLineArgument[1:] # name not followed by parameter in this case
                    arguments[argumentName].append('')

            # Response file
            elif cmdLineArgument[0] == '@':
                raise AssertionError("No response file arguments (starting with @) must be left here.")

            # Source file arguments
            else:
                inputFiles.append(cmdLineArgument)

            i += 1

        return dict(arguments), inputFiles

    @staticmethod
    def analyze(cmdline: List[str]) -> Tuple[List[Tuple[str, str]], List[str]]:
        options, inputFiles = CommandLineAnalyzer.parseArgumentsAndInputFiles(cmdline)
        # Use an override pattern to shadow input files that have
        # already been specified in the function above
        inputFiles = {inputFile: '' for inputFile in inputFiles}
        compl = False
        if 'Tp' in options:
            inputFiles.update({inputFile: '/Tp' for inputFile in options['Tp']})
            compl = True
        if 'Tc' in options:
            inputFiles.update({inputFile: '/Tc' for inputFile in options['Tc']})
            compl = True

        # Now collect the inputFiles into the return format
        inputFiles = list(inputFiles.items())
        if not inputFiles:
            raise NoSourceFileError()

        for opt in ['E', 'EP', 'P']:
            if opt in options:
                raise CalledForPreprocessingError()

        # Technically, it would be possible to support /Zi: we'd just need to
        # copy the generated .pdb files into/out of the cache.
        if 'Zi' in options:
            raise ExternalDebugInfoError()

        if ('Yc' in options or 'Yu' in options) and 'Y-' not in options:
            raise CalledWithPchError()

        if 'link' in options or 'c' not in options:
            raise CalledForLinkError()

        if len(inputFiles) > 1 and compl:
            raise MultipleSourceFilesComplexError()

        objectFiles = None
        prefix = ''
        if 'Fo' in options and options['Fo'][0]:
            # Handle user input
            tmp = os.path.normpath(options['Fo'][0])
            if os.path.isdir(tmp):
                prefix = tmp
            elif len(inputFiles) == 1:
                objectFiles = [tmp]
        if objectFiles is None:
            # Generate from .c/.cpp filenames
            objectFiles = [os.path.join(prefix, basenameWithoutExtension(f)) + '.obj' for f, _ in inputFiles]

        printTraceStatement("Compiler source files: {}".format(inputFiles))
        printTraceStatement("Compiler object file: {}".format(objectFiles))
        return inputFiles, objectFiles


def invokeRealCompiler(compilerBinary, cmdLine, captureOutput=False, outputAsString=True, environment=None):
    realCmdline = [compilerBinary] + cmdLine
    printTraceStatement("Invoking real compiler as {}".format(realCmdline))

    environment = environment or os.environ

    # Environment variable set by the Visual Studio IDE to make cl.exe write
    # Unicode output to named pipes instead of stdout. Unset it to make sure
    # we can catch stdout output.
    environment.pop("VS_UNICODE_OUTPUT", None)

    returnCode = None
    stdout = b''
    stderr = b''
    if captureOutput:
        # Don't use subprocess.communicate() here, it's slow due to internal
        # threading.
        with TemporaryFile() as stdoutFile, TemporaryFile() as stderrFile:
            compilerProcess = subprocess.Popen(realCmdline, stdout=stdoutFile, stderr=stderrFile, env=environment)
            returnCode = compilerProcess.wait()
            stdoutFile.seek(0)
            stdout = stdoutFile.read()
            stderrFile.seek(0)
            stderr = stderrFile.read()
    else:
        returnCode = subprocess.call(realCmdline, env=environment)

    printTraceStatement("Real compiler returned code {0:d}".format(returnCode))

    if outputAsString:
        stdoutString = stdout.decode(CL_DEFAULT_CODEC)
        stderrString = stderr.decode(CL_DEFAULT_CODEC)
        return returnCode, stdoutString, stderrString

    return returnCode, stdout, stderr

# Returns the amount of jobs which should be run in parallel when
# invoked in batch mode as determined by the /MP argument
def jobCount(cmdLine):
    mpSwitches = [arg for arg in cmdLine if re.match(r'^/MP(\d+)?$', arg)]
    if not mpSwitches:
        return 1

    # the last instance of /MP takes precedence
    mpSwitch = mpSwitches.pop()

    count = mpSwitch[3:]
    if count != "":
        return int(count)

    # /MP, but no count specified; use CPU count
    try:
        return multiprocessing.cpu_count()
    except NotImplementedError:
        # not expected to happen
        return 2

def printStatistics(cache):
    if '_USECCACHE' in os.environ and '_USENOPCH' not in os.environ:
        return printStatistics2(cache)
    template = """
clcache statistics:
  current cache dir            : {}
  cache size                   : {:.2f} GB
  maximum cache size           : {:.2f} GB
  cache entries                : {}
  cache hits                   : {}
  cache misses   
    total                      : {}
    evicted                    : {}
    header changed             : {}
    source changed             : {}
  passed to real compiler
    called w/ invalid argument : {}
    called for preprocessing   : {}
    called for linking         : {}
    called for external debug  : {}
    called w/o source          : {}
    called w/ multiple sources : {}
    called w/ PCH              : {}""".strip()

    with cache.statistics.lock, cache.statistics as stats, cache.configuration as cfg:
        print(template.format(
            str(cache),
            stats.currentCacheSize() / (1024 * 1024 * 1024),
            cfg.maximumCacheSize() / (1024 * 1024 * 1024),
            stats.numCacheEntries(),
            stats.numCacheHits(),
            stats.numCacheMisses(),
            stats.numEvictedMisses(),
            stats.numHeaderChangedMisses(),
            stats.numSourceChangedMisses(),
            stats.numCallsWithInvalidArgument(),
            stats.numCallsForPreprocessing(),
            stats.numCallsForLinking(),
            stats.numCallsForExternalDebugInfo(),
            stats.numCallsWithoutSourceFile(),
            stats.numCallsWithMultipleSourceFiles(),
            stats.numCallsWithPch(),
        ))

def printStatistics2(cache):
    template = """
    clcache statistics:
      current cache dir         : {}
      maximum cache size        : {:.2f} GB
      cache size                : {:.2f} GB
      cache entries             : {}
      #manifest count           : {stats.ManifestCount}
      #manifest entry           : {stats.ManifestEntryCount}
      
      file hit rate             : {fpercent:.2f}%
      file rebuild rate         : {frecompile:.2f}%
      #file hits                : {stats.EntryHits} (manifest hash hits: {stats.HashHits})
      #file misses              : {AllMiss}
        source/cmd changed      : {stats.HashMiss}
        header changed          : {stats.EntryMiss}
        pch changed             : {stats.CppRecompiledFromPchChange}
        obj missing             : {stats.FailureGetObj}
      #pch file rebuild         : {stats.PchRecompiledFromCppChange}

      #proj cache hits :        : {stats.ProjectHits}
      #proj cache misses :      : {stats.ProjectMiss}

      diagnostics
        #entry modified         : {stats.DuplicateManifestEntryFound}
        #identical entry found  : {stats.IdenticalEntryCount}
        #add entry              : {stats.AddEntryCount}
        #duplicate objs found   : {stats.DuplicateObjHashFound}
        #add objs               : {stats.AddObjCount}
        add objs size           : {AddObjSize:.2f} MB
        #failure add obj        : {stats.FailureAddObj}
        #header file missing    : {stats.DependencyMissingCount}
        #cache cleanup          : {stats.CleanUpCount}
      run statistics
        #preinvoke launch       : {stats.PreInvokeLauchCount}
        #preinvoke exit         : {stats.PreInvokeExitCount}
        preinvoke time          : {PreInvokeExecutionTime:.3f} Seconds
        preinvoke CPU time      : {PreInvokeCpuTime:.3f} Seconds
        preinvoke wait%         : {prewaitrate:.2f}%
        #postinvoke launch      : {stats.PostInvokeLauchCount}
        #postinvoke exit        : {stats.PostInvokeExitCount}
        postinvoke time         : {PostInvokeExecutionTime:.3f} Seconds
        postinvoke CPU time     : {PostInvokeCpuTime:.3f} Seconds
        postinvoke wait%        : {postwaitrate:.2f}%        
        
        """.strip()
    with  cache.statistics as stats, cache.configuration as cfg:
        PreInvokeExecutionTime = stats.PreInvokeExecutionTime / 10**7
        PostInvokeExecutionTime = stats.PostInvokeExecutionTime / 10**7
        PreInvokeCpuTime = stats.PreInvokeCpuTime / 10**7
        PostInvokeCpuTime = stats.PostInvokeCpuTime / 10**7
        postwaitrate = (1 - PostInvokeCpuTime /  PostInvokeExecutionTime) * 100 if PostInvokeExecutionTime else 0
        prewaitrate = (1 - PreInvokeCpuTime /  PreInvokeExecutionTime) * 100 if PreInvokeExecutionTime else 0
        AllMiss = stats.EntryMiss + stats.HashMiss + stats.CppRecompiledFromPchChange + stats.FailureGetObj
        allfiles = (stats.EntryHits + AllMiss)
        fpercent = 100* stats.EntryHits / allfiles if allfiles  else 0
        frecompile = 100* (AllMiss + stats.PchRecompiledFromCppChange) / allfiles if allfiles else 0
        AddObjSize = stats.AddObjSize / (1024 * 1024)
        print(template.format(
            str(cache),
            cfg.maximumCacheSize() / (1024 * 1024 * 1024),
            stats.currentCacheSize() / (1024 * 1024 * 1024),
            stats.numCacheEntries(),
            **locals()))


def resetStatistics(cache):
    with cache.statistics.lock, cache.statistics as stats:
        stats.resetCounters()


def cleanCache(cache):
    with cache.lock, cache.statistics.lock, cache.statistics as stats, cache.configuration as cfg:
        stats.incCleanUpCount()
        #cache.clean(stats, cfg.maximumCacheSize())


def clearCache(cache):
    with cache.lock, cache.statistics.lock, cache.statistics as stats:
        cache.clear(stats)
        stats.setManifestCount(0)
        stats.setManifestEntryCount(0)


# Returns pair:
#   1. set of include filepaths
#   2. new compiler output
# Output changes if strip is True in that case all lines with include
# directives are stripped from it
def parseIncludesSet(compilerOutput, sourceFile, strip):
    newOutput = []
    includesSet = set()

    # Example lines
    # Note: including file:         C:\Program Files (x86)\Microsoft Visual Studio 12.0\VC\INCLUDE\limits.h
    # Hinweis: Einlesen der Datei:   C:\Program Files (x86)\Microsoft Visual Studio 12.0\VC\INCLUDE\iterator
    #
    # So we match
    # - one word (translation of "note")
    # - colon
    # - space
    # - a phrase containing characters and spaces (translation of "including file")
    # - colon
    # - one or more spaces
    # - the file path, starting with a non-whitespace character
    reFilePath = re.compile(r'^(\w+): ([ \w]+):( +)(?P<file_path>\S.*)$')

    absSourceFile = os.path.normcase(os.path.abspath(sourceFile))
    for line in compilerOutput.splitlines(True):
        match = reFilePath.match(line.rstrip('\r\n'))
        if match is not None:
            filePath = match.group('file_path')
            filePath = os.path.normcase(os.path.abspath(filePath))
            if filePath != absSourceFile:
                includesSet.add(filePath)
        elif strip:
            newOutput.append(line)
    if strip:
        return includesSet, ''.join(newOutput)
    else:
        return includesSet, compilerOutput


def addObjectToCache(stats, cache, cachekey, artifacts):
    # This function asserts that the caller locked 'section' and 'stats'
    # already and also saves them
    printTraceStatement("Adding file {} to cache using key {}".format(artifacts.objectFilePath, cachekey))

    size = cache.setEntry(cachekey, artifacts)
    if size is None:
        size = os.path.getsize(artifacts.objectFilePath)
    stats.registerCacheEntry(size)

    with cache.configuration as cfg:
        return stats.currentCacheSize() >= cfg.maximumCacheSize()


def processCacheHit(cache, objectFile, cachekey):
    printTraceStatement("Reusing cached object for key {} for object file {}".format(cachekey, objectFile))

    with cache.lockFor(cachekey):
        with cache.statistics.lock, cache.statistics as stats:
            stats.registerCacheHit()

        if os.path.exists(objectFile):
            os.remove(objectFile)

        cachedArtifacts = cache.getEntry(cachekey)
        copyOrLink(cachedArtifacts.objectFilePath, objectFile)
        printTraceStatement("Finished. Exit code 0")
        return 0, cachedArtifacts.stdout, cachedArtifacts.stderr, False


def createManifestEntry(manifestHash, includePaths):
    sortedIncludePaths = sorted(set(includePaths))
    includeHashes = getFileHashes(sortedIncludePaths)

    safeIncludes = [collapseBasedirToPlaceholder(path) for path in sortedIncludePaths]
    includesContentHash = ManifestRepository.getIncludesContentHashForHashes(includeHashes)
    cachekey = CompilerArtifactsRepository.computeKeyDirect(manifestHash, includesContentHash)

    return ManifestEntry(safeIncludes, includesContentHash, cachekey)

windll.kernel32.GetCommandLineW.restype = wintypes.LPCWSTR

def _main():
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument('-s', '--stat', action='store_true', help='print cache statistics')
    parser.add_argument('-c', '--clean', dest='clean', action='store_true', help='Cache cleaned')
    parser.add_argument('-C', '--clear', dest='clear', action='store_true', help='Cache cleared')
    parser.add_argument('-z', '--reset', dest='reset', action='store_true', help='reset cache statistics')
    parser.add_argument('-M', '--max', dest='max_size', type=float, help='set maximum cache size (in GB)')
    parser.add_argument('-b', '--compiler', dest='compiler', type=str)
    parser.add_argument('-f', '--project', dest='project', type=str)
    parser.add_argument('-p', '--prepare', action='store_true')
    parser.add_argument('-q', '--collect', action='store_true')
    parser.add_argument('-d', '--debug', action='store_true')

    args, other_args = parser.parse_known_args()

    global g_project_name
    g_project_name = args.project or ''
    cache = Cache()
    args.stat and printStatistics(cache)
    args.clean and cleanCache(cache)
    args.clear and clearCache(cache)
    args.reset and resetStatistics(cache)
    args.debug and processDebug(cache)

    if args.max_size and args.max_size > 0:
        with cache.lock, cache.configuration as cfg:
            cfg.setMaximumCacheSize(int(args.max_size * 1024 * 1024 * 1024))

    len(other_args) or sys.exit(0)

    compiler = args.compiler or findCompilerBinary()
    if compiler:
        compiler = os.path.abspath(compiler).upper()
    if not compiler:
        printTraceStatement("Failed to locate cl.exe on PATH (and CLCACHE_CL is not set), aborting.")
        return 1

    if args.prepare:
        return processPreInvoke(cache, other_args, compiler)
    elif args.collect:
        return processPostInvoke(cache, other_args, compiler)

    printTraceStatement("Found real compiler binary at '{0!s}'".format(compiler))

    if "CLCACHE_DISABLE" in os.environ:
        return invokeRealCompiler(compiler, other_args)[0]
    try:
        return processCompileRequest(cache, compiler, other_args)
    except LogicException as e:
        print(e)
        return 1


def updateCacheStatistics(cache, method):
    with cache.statistics.lock, cache.statistics as stats:
        method(stats)

def printOutAndErr(out, err):
    printBinary(sys.stdout, out.encode(CL_DEFAULT_CODEC))
    printBinary(sys.stderr, err.encode(CL_DEFAULT_CODEC))


def printErrStr(message):
    printTraceStatement(message)
    with OUTPUT_LOCK:
        print(message, file=sys.stderr)


def parse_input(args):
    content = read_file(args[0])
    delete_tmp_file(args[0])
    content = [x.strip() for x in content.split('^^')]
    content = [x.split('|') for x in content if x.strip()]
    content = sorted(content, key=lambda x: x[2], reverse=True)
    return [CompilerItem(*x) for x in content]

#CompilerEntry = namedtuple('CompilerEntry', ['file', 'project', 'cmdline', 'output' , 'dependency', 'dependency_hash'])

@dataclass
class CompilerEntry:
    manifest_hash: str =None;
    parent_hash: str = None;
    file: str =None;project: str= None;compiler:str= None; cmdline: str =None;
    output: List =None;
    parent:  InitVar[object] = None;
    dependency_hash: str=None;dependency: List= None;
    def _asdict(self):
        return asdict(self)

    def __post_init__(self, parent):
        if not self.dependency_hash:
            self.dependency_hash = self.generate_dependency_hash(self.dependency)
        if parent:
            self.parent_hash = '|'.join( (parent.entry.manifest_hash, parent.entry.dependency_hash) )

    def match_local(self):
        return self.dependency_hash == self.generate_dependency_hash(self.dependency)

    @staticmethod
    def generate_dependency_hash(files):
        return ManifestRepository.getIncludesContentHashForFiles(files)


@functools.lru_cache(maxsize=16)
def cmd_normalize(cmdline):
    return re.subn('\s{2,}/', ' /', cmdline)[0]

pch_dp_map = dict()

@dataclass
class CompilerItem(Statistics):
    item_spec: str;full_path: str; pch_state: str
    pch_hdr: str
    cmdline: str
    dependency: List[str] = None
    output: List[str] = None
    entry : bool = None
    hash: str = None
    parent = None

    @classmethod
    def set_compiler(cls, compiler):
        cls.compiler_hash = getCompilerHash(compiler)
    def __post_init__(self):
        if self.pch_hdr:
            self.pch_hdr = self.pch_hdr.strip().strip('"').upper()
        dependency = self.dependency.split('*') if self.dependency else []
        if self.is_usePch():
            dependency = set((x for x in dependency if not x.endswith('.PCH')))
        else:
            dependency = set(dependency)

        if self.is_genPch():
            assert self.pch_hdr not in pch_dp_map
            pch_dp_map[self.pch_hdr] = self
        elif self.is_usePch():
            self.parent = pch_dp_map[self.pch_hdr]

        self.dependency = sorted(dependency)
        self.output = sorted(self.output.split('*') if self.output else [])
        self.cmdline = cmd_normalize(self.cmdline)

    def is_genPch(self):
        return self.pch_state == '2'
    def is_usePch(self):
        return self.pch_state == '1'

    def manifest_hash(self):
        if self.hash: return self.hash
        additionalData = [self.compiler_hash, self.cmdline,self.full_path, str(ManifestRepository.MANIFEST_FILE_FORMAT_VERSION)]
        if self.parent:
            additionalData += [self.parent.manifest_hash(), self.parent.entry.dependency_hash ]
        self.hash = getFileHash(self.full_path, '|'.join(additionalData))
        return self.hash

    def manifest_hit(self, cache):
        if self.entry is not None:
            return self.entry
        manifest_hash = self.manifest_hash()
        manifest = None
        with cache.manifestLockFor(manifest_hash):
            manifest = cache.getManifest(manifest_hash)
        if manifest:
            self.incHashHits()
            printTraceStatement("manifest hash Hit: {} {}".format(self.full_path, manifest_hash))
            self.entry = self.manifest_search(manifest)
            if self.entry:
                self.incEntryHits()
                printTraceStatement("manifest Entry Hit: {} {}".format(self.full_path, self.entry.dependency_hash))
            else:
                self.incEntryMiss()
                printTraceStatement("manifest Entry Miss: {}".format(self.full_path))
        else:
            self.incHashMiss()
            printTraceStatement("manifest hash Miss: {}".format(self.full_path))
            self.entry = False
        return self.entry

    def manifest_search(self, manifest):
        for entry in manifest.entries():
            try:
                if entry.match_local():
                    return entry
            except IncludeNotFoundException:
                self.incDependencyMissingCount()
        return False

    def retrieve_hit(self, cache):
        entry = self.manifest_hit(cache)
        if not entry: return
        for item in entry.output:
            r = self.get_object(cache, item[1], item[0])
            if not r: return False
        return True

    def manifest_entry(self) -> CompilerEntry:
        assert self.output
        hashes = getFileHashes(self.dependency)
         #safeIncludes = [collapseBasedirToPlaceholder(path) for path in sortedIncludePaths]
        output = [ list(y) for y in  zip(self.output, [getFileHash(x) for x in self.output]) ]
        self.entry = CompilerEntry(manifest_hash = self.manifest_hash(),
            file=self.full_path, cmdline=self.cmdline,
                              output=output, dependency=self.dependency,
                              dependency_hash=None, project=g_project_name, compiler=self.compiler_hash, parent=self.parent)
        return self.entry

    def ensure_output(self, cache):
        entry = self.manifest_entry()
        add_success = False
        for item in entry.output:
            size = self.add_object(cache, item[1], item[0])
            add_success |= (size > 0)
            if not add_success: break
        if not add_success: return
        manifest_hash = entry.manifest_hash
        with cache.manifestLockFor(manifest_hash):
            manifest = cache.getManifest(manifest_hash) or (Manifest(), self.incManifestCount())[0]
            found = next((x for x in manifest.entries() if x.dependency_hash == entry.dependency_hash), None)
            if not found:
                manifest.addEntry(entry)
                self.incManifestEntryCount()
                self.incAddEntryCount()
                cache.setManifest(manifest_hash, manifest)   #entry added
            elif found.output != entry.output:
                self.incDuplicateManifestEntryFound()
                found.output = entry.output
                cache.setManifest(manifest_hash, manifest)   #entry replaced
                printTraceStatement("Duplicate entry found for {}".format(entry.file))
            else:
                self.incIdenticalEntryCount()
                printTraceStatement("Identical entry found for {}".format(entry.file))
        return

    def add_object(self, cache : Cache, key, file):
        printTraceStatement("Adding file {} to cache using key {}".format(file, key))
        with cache.lockFor(key):
            if cache.hasEntry(key):
                printTraceStatement("Duplicate File {} with key {} already in cache".format(file, key))
                self.incDuplicateObjHashFound()
                return 1
            size = cache.setEntry2(key, file)
            if size and cache.hasEntry(key):
                self.registerCacheEntry(size)
                self.incAddObjCount()
                self.incAddObjSize(size)
            else:
                printTraceStatement("Failed to add file for {}".format(file))
                self.incFailureAddObj()
                return 0
        return size

    def get_object(self, cache : Cache, key, file):
        with cache.lockFor(key):
            if cache.hasEntry(key):
                printTraceStatement("Get file keyed {} to {}".format(key, file))
                if os.path.exists(file):
                    os.remove(file)
                return cache.getEntry2(key, file)
            else:
                printTraceStatement("Failed to get file keyed {} to {}".format(key, file))
                self.incFailureGetObj()

    def __hash__(self):
        return self.item_spec.__hash__()

    def __eq__(self, other):
        return self.item_spec == other.item_spec

def delete_tmp_file(path):
    if not 'MSBUILDPRESERVETOOLTEMPFILES' in os.environ:
        os.remove(path)

def processPreInvoke(cache, args, compiler):
    printTraceStatement("PreInvoke {}".format(windll.kernel32.GetCommandLineW()))
    with cache.statistics.lock, cache.statistics as stats:
        stats.incPreInvokeLauchCount()
    skip_pre = 'CLCACHE_FORCEMISS' in os.environ
    CompilerItem.set_compiler(compiler)
    content = parse_input(args)
    miss = set(content) if skip_pre else set()
    for item in content:
        if item in miss: continue
        if not item.manifest_hit(cache):
            miss.add(item)
            if item.is_genPch():
                prelen = len(miss)
                miss.update( (x for x in content if x.is_usePch() and x.pch_hdr == item.pch_hdr) )
                item.incCppRecompiledFromPchChange(len(miss) - prelen)
            elif item.is_usePch():
                prelen = len(miss)
                miss.update((x for x in content if x.is_genPch() and x.pch_hdr == item.pch_hdr))
                item.incPchRecompiledFromCppChange(len(miss) - prelen)
    hits = set(content) - miss
    for item in hits:
        success = item.retrieve_hit(cache)
        if not success:
            miss.add(item)
    hits -= miss
    print("*".join((x.item_spec for x in hits)), end='*')
    with cache.statistics.lock, cache.statistics as stats:
        if miss:
            stats.incProjectMiss()
        else:
            stats.incProjectHits()
        stats.updateStats(CompilerItem)
        stats.incPreInvokeExitCount()
        alltime, cputime = diff_time()
        stats.incPreInvokeExecutionTime(alltime)
        stats.incPreInvokeCpuTime(cputime)
    return 0


def processPostInvoke(cache, args, compiler):
    printTraceStatement("PostInvoke {}".format(windll.kernel32.GetCommandLineW()))
    cacheSize = 0
    cleanup = False
    with cache.statistics.lock, cache.statistics as stats:
        stats.incPostInvokeLauchCount()
        cacheSize = stats.currentCacheSize()
    with cache.configuration as cfg:
        cleanup = cacheSize >= cfg.maximumCacheSize()

    CompilerItem.set_compiler(compiler)
    content = parse_input(args)
    if cleanup:
        printTraceStatement('Cache size {} limit reached. Need cleaning.'.format(cacheSize))
        cleanCache(cache)
    else:
        for item in content:
            item.ensure_output(cache)

    with cache.statistics.lock, cache.statistics as stats:
        stats.updateStats(CompilerItem)
        stats.incPostInvokeExitCount()
        alltime, cputime = diff_time()
        stats.incPostInvokeExecutionTime(alltime)
        stats.incPostInvokeCpuTime(cputime)
    return 0


def processDebug(cache: Cache):
    import glob
    count = 0
    objs = set()
    for filename in glob.iglob(r'U:\bin\cache\manifests\**\*.json', recursive=True):
        b = json.load(open(filename))
        count += 1
    for filename in glob.iglob(r'U:\bin\cache\objects\**\object', recursive=True):
        hash = filename.split('\\')[-2]
        objs.add(hash)

    print(count)
    print(len(objs))


def processCompileRequest(cache, compiler, args):
    printTraceStatement("Parsing given commandline '{0!s}'".format(args))

    cmdLine, environment = extendCommandLineFromEnvironment(args, os.environ)
    cmdLine = expandCommandLine(cmdLine)
    printTraceStatement("Expanded commandline '{0!s}'".format(cmdLine))

    try:
        sourceFiles, objectFiles = CommandLineAnalyzer.analyze(cmdLine)
        return scheduleJobs(cache, compiler, cmdLine, environment, sourceFiles, objectFiles)
    except InvalidArgumentError:
        printTraceStatement("Cannot cache invocation as {}: invalid argument".format(cmdLine))
        updateCacheStatistics(cache, Statistics.registerCallWithInvalidArgument)
    except NoSourceFileError:
        printTraceStatement("Cannot cache invocation as {}: no source file found".format(cmdLine))
        updateCacheStatistics(cache, Statistics.registerCallWithoutSourceFile)
    except MultipleSourceFilesComplexError:
        printTraceStatement("Cannot cache invocation as {}: multiple source files found".format(cmdLine))
        updateCacheStatistics(cache, Statistics.registerCallWithMultipleSourceFiles)
    except CalledWithPchError:
        printTraceStatement("Cannot cache invocation as {}: precompiled headers in use".format(cmdLine))
        updateCacheStatistics(cache, Statistics.registerCallWithPch)
    except CalledForLinkError:
        printTraceStatement("Cannot cache invocation as {}: called for linking".format(cmdLine))
        updateCacheStatistics(cache, Statistics.registerCallForLinking)
    except ExternalDebugInfoError:
        printTraceStatement(
            "Cannot cache invocation as {}: external debug information (/Zi) is not supported".format(cmdLine)
        )
        updateCacheStatistics(cache, Statistics.registerCallForExternalDebugInfo)
    except CalledForPreprocessingError:
        printTraceStatement("Cannot cache invocation as {}: called for preprocessing".format(cmdLine))
        updateCacheStatistics(cache, Statistics.registerCallForPreprocessing)

    exitCode, out, err = invokeRealCompiler(compiler, args)
    printOutAndErr(out, err)
    return exitCode

def filterSourceFiles(cmdLine: List[str], sourceFiles: List[Tuple[str, str]]) -> Iterator[str]:
    setOfSources = set(sourceFile for sourceFile, _ in sourceFiles)
    skippedArgs = ('/Tc', '/Tp', '-Tp', '-Tc')
    yield from (
        arg for arg in cmdLine
        if not (arg in setOfSources or arg.startswith(skippedArgs))
    )

def scheduleJobs(cache: Any, compiler: str, cmdLine: List[str], environment: Any,
                 sourceFiles: List[Tuple[str, str]], objectFiles: List[str]) -> int:
    # Filter out all source files from the command line to form baseCmdLine
    baseCmdLine = [arg for arg in filterSourceFiles(cmdLine, sourceFiles) if not arg.startswith('/MP')]

    exitCode = 0
    cleanupRequired = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobCount(cmdLine)) as executor:
        jobs = []
        for (srcFile, srcLanguage), objFile in zip(sourceFiles, objectFiles):
            jobCmdLine = baseCmdLine + [srcLanguage + srcFile]
            jobs.append(executor.submit(
                processSingleSource,
                compiler, jobCmdLine, srcFile, objFile, environment))
        for future in concurrent.futures.as_completed(jobs):
            exitCode, out, err, doCleanup = future.result()
            printTraceStatement("Finished. Exit code {0:d}".format(exitCode))
            cleanupRequired |= doCleanup
            printOutAndErr(out, err)

            if exitCode != 0:
                break

    if cleanupRequired:
        cleanCache(cache)

    return exitCode

def processSingleSource(compiler, cmdLine, sourceFile, objectFile, environment):
    try:
        assert objectFile is not None
        cache = Cache()

        if 'CLCACHE_NODIRECT' in os.environ:
            return processNoDirect(cache, objectFile, compiler, cmdLine, environment)
        else:
            return processDirect(cache, objectFile, compiler, cmdLine, sourceFile)

    except IncludeNotFoundException:
        return invokeRealCompiler(compiler, cmdLine, environment=environment), False
    except CompilerFailedException as e:
        return e.getReturnTuple()

def processDirect(cache, objectFile, compiler, cmdLine, sourceFile):
    manifestHash = ManifestRepository.getManifestHash(compiler, cmdLine, sourceFile)
    manifestHit = None
    with cache.manifestLockFor(manifestHash):
        manifest = cache.getManifest(manifestHash)
        if manifest:
            printTraceStatement("manifest Hit: {}".format(manifestHash))
            for entryIndex, entry in enumerate(manifest.entries()):
                # NOTE: command line options already included in hash for manifest name
                try:
                    includesContentHash = ManifestRepository.getIncludesContentHashForFiles(
                        [expandBasedirPlaceholder(path) for path in entry.includeFiles])

                    if entry.includesContentHash == includesContentHash:
                        cachekey = entry.objectHash
                        assert cachekey is not None
                        if entryIndex > 0:
                            # Move manifest entry to the top of the entries in the manifest
                            manifest.touchEntry(cachekey)
                            cache.setManifest(manifestHash, manifest)

                        manifestHit = True
                        with cache.lockFor(cachekey):
                            if cache.hasEntry(cachekey):
                                return processCacheHit(cache, objectFile, cachekey)

                except IncludeNotFoundException:
                    pass

            unusableManifestMissReason = Statistics.registerHeaderChangedMiss
        else:
            unusableManifestMissReason = Statistics.registerSourceChangedMiss

    if manifestHit is None:
        stripIncludes = False
        if '/showIncludes' not in cmdLine:
            cmdLine = list(cmdLine)
            cmdLine.insert(0, '/showIncludes')
            if '/nologo' not in cmdLine:
                cmdLine.insert(0, '/nologo')
            stripIncludes = True
    compilerResult = invokeRealCompiler(compiler, cmdLine, captureOutput=True)
    if manifestHit is None:
        includePaths, compilerOutput = parseIncludesSet(compilerResult[1], sourceFile, stripIncludes)
        compilerResult = (compilerResult[0], compilerOutput, compilerResult[2])

    with cache.manifestLockFor(manifestHash):
        if manifestHit is not None:
            return ensureArtifactsExist(cache, cachekey, unusableManifestMissReason,
                                        objectFile, compilerResult)

        entry = createManifestEntry(manifestHash, includePaths)
        cachekey = entry.objectHash

        def addManifest():
            manifest = cache.getManifest(manifestHash) or Manifest()
            manifest.addEntry(entry)
            cache.setManifest(manifestHash, manifest)

        return ensureArtifactsExist(cache, cachekey, unusableManifestMissReason,
                                    objectFile, compilerResult, addManifest)


def processNoDirect(cache, objectFile, compiler, cmdLine, environment):
    cachekey = CompilerArtifactsRepository.computeKeyNodirect(compiler, cmdLine, environment)
    with cache.lockFor(cachekey):
        if cache.hasEntry(cachekey):
            return processCacheHit(cache, objectFile, cachekey)

    compilerResult = invokeRealCompiler(compiler, cmdLine, captureOutput=True, environment=environment)

    return ensureArtifactsExist(cache, cachekey, Statistics.registerCacheMiss,
                                objectFile, compilerResult)


def ensureArtifactsExist(cache, cachekey, reason, objectFile, compilerResult, extraCallable=None):
    cleanupRequired = False
    returnCode, compilerOutput, compilerStderr = compilerResult
    correctCompiliation = (returnCode == 0 and os.path.exists(objectFile))
    with cache.lockFor(cachekey):
        if not cache.hasEntry(cachekey):
            with cache.statistics.lock, cache.statistics as stats:
                reason(stats)
                if correctCompiliation:
                    artifacts = CompilerArtifacts(objectFile, compilerOutput, compilerStderr)
                    cleanupRequired = addObjectToCache(stats, cache, cachekey, artifacts)
            if extraCallable and correctCompiliation:
                extraCallable()
    return returnCode, compilerOutput, compilerStderr, cleanupRequired


def main():
    if 'CLCACHE_PROFILE' in os.environ:
        import cProfile
        INVOCATION_HASH = getStringHash(','.join(sys.argv))
        cProfile.runctx('_main()', globals(), locals(), filename='clcache-{}.prof'.format(INVOCATION_HASH))
    else:
        return _main()
if __name__ == '__main__':
    sys.exit(main())
