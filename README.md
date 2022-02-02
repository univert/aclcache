aclcache - a compiler/linker cache
==================================

- [aclcache - a compiler/linker cache](#aclcache---a-compilerlinker-cache)
  - [Environment Variables](#environment-variables)
  - [Command Line Options](#command-line-options)
  - [Known limitations](#known-limitations)
  - [How clcache works](#how-clcache-works)
  - [Caveats](#caveats)
  - [License Terms](#license-terms)

aclcache is a compiling and linking accelarator. It is a utility tool
which attempts to avoid unnecessary recompilation by reusing previously
cached object/binary files if possible.

The tool is based on [clcache][] and extends
the functionality of clcache. Currently aclcache supports the following functionalities

- Precompiled header support for compiler cache:
- PDB files support
- Linker cache (caches linker.exe output)
- [import directive][] compilation support
- Mixed mode compilation support (planned)

[clcache]: https://github.com/frerich/clcache
[import directive]: https://docs.microsoft.com/en-us/cpp/preprocessor/hash-import-directive-cpp?view=vs-2019


Environment Variables
---------------------

### ACLCACHE_MODE

 Value | Meaning
-------|---------------------------------------
 1     | Enable compiler cache support
 2     | Enable linker cache support
 3     | Enable both compiler and linker cache

### ACLCACHE_DIR

If set, points to the directory within which all the cached object files
should be stored. This defaults to `%HOME%\clcache`

### ACLCACHE_LOG

 Value       | Meaning
-------------|----------------------------------------------------------------------------------------------
 Not set     | Disable logging
 1           | Enable logging to the standard ouput and windows debug buffer using [debugview][] to capture
 A file name | Enable logging to the file

[debugview]: https://docs.microsoft.com/en-us/sysinternals/downloads/debugview

### ACLCACHE_HARDLINK

If this variable is set, cached object files won't be copied to their
final location. Instead, hard links pointing to the cached object files
will be created. This is more efficient (faster, and uses less disk space)
but doesn't work if the cache directory is on a different drive than the
build directory. Please read [Caveats](#caveats) before using this variable.

### ACLCACHE_SERVER

If this variable is set, aclcache will use a server process to cache all
the header files' hash which will greatly improves performance during
header file content matching.

### ACLCACHE_SIZE

Set the maximum cache size in GB. If cache size is more than this size,
the caching will stop to work. You need to purge the cache if

### ACLCACHE_PROFILE

If this variable is set, clcache will generate profiling information about
how the runtime is spent in the clcache code. For each invocation, clcache
will generate a file with a name similiar to `clcache-<hashsum>.prof`. You
can aggregate these files and generate a report by running the
[showprofilereport.py](showprofilereport.py) script.

Command Line Options
--------------------

**--help(-h)**<br/>
    Print usage information

**--stat(-s)**<br/>
    Print some statistics about the cache (cache hits, cache misses, cache size etc.)

**--clear(-c)**<br/>
    Clean the cacheClear the cache: remove all cached objects, but keep the cache statistics (hits, misses, etc.).

**--reset(-z)**<br/>
    Reset the cache statistics, i.e. number of cache hits, cache misses etc..
    Doesn't actually clear the cache, so the number of cached objects and the
    cache size will remain unchanged.

**--max(-M) <size>**<br/>
    Sets the maximum size of the cache in GB.

**--start_svr**<br/>
    Restart the header hash server process.

Known limitations
-----------------

- [INCLUDE and LIBPATH][] environment variables are not supported. Currently only command line arguments to compiler/linker, and input files(header files, and lib files) are analyzed during caching. Compiling result difference resulting from [INCLUDE and LIBPATH][] modification is not supported.

[INCLUDE and LIBPATH]: https://msdn.microsoft.com/en-us/library/kezkeayy.aspx

How clcache works
-----------------

aclcache was designed to intercept calls to cl.exe and linker.exe by
msbuild extenstion. The extention calls the python script to do hit testing
and before and after calls to cl.exe and linker.exe.

Caveats
-------

- Currently aclcache does not support mix mode compiling (managed module).
- aclcache is not compatible with [/Zi][ziz7] copmiler switch, it uses [/Z7][ziz7] compiler switch if pdb files is needed. However, if you enable genreate pdb files, linker cache's hit rate may be impacted because [/Z7][ziz7] causes the object files generated not deterministic.
- ACLCACHE_HARDLINK is not very safe for development environment if your build your projects repeastedly or there is a custom step that modifies .obj/binary files.

[ziz7]: https://docs.microsoft.com/en-us/cpp/build/reference/z7-zi-zi-debug-information-format

License Terms
-------------

The source code of this project is - unless explicitly noted otherwise in the
respective files - subject to the
[BSD 3-Clause License](https://opensource.org/licenses/BSD-3-Clause).
