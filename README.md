aclcache - a compiler/linker cache
==================================

- [aclcache - a compiler/linker cache](#aclcache---a-compilerlinker-cache)
  - [What's aclcache](#whats-aclcache)
  - [FAQs](#faqs)
  - [Environment Variables](#environment-variables)
  - [Command Line Options](#command-line-options)
  - [Known limitations](#known-limitations)
  - [How clcache works](#how-clcache-works)
  - [Caveats](#caveats)
  - [License Terms](#license-terms)

What's aclcache
---------------

aclcache is a compiling and linking accelarator to Visual C++
 (just like ccache is for gcc & clang). It is a utility tool
which attempts to avoid unnecessary recompilation by reusing previously
cached object/binary files if possible.

The tool borrows basic ideas from [clcache][] and enhance
the functionality of clcache. Aclcache supports compilation scenarios
 previsouly not possible with other compiler cache implementations.
Currently aclache support the following functionalities:

- Precompiled header support for compiler cache:
- PDB files support
- Linker cache (caches linker.exe output)
- [import directive][] compilation support
- Mixed mode compilation support (planned)

[clcache]: https://github.com/frerich/clcache
[import directive]: https://docs.microsoft.com/en-us/cpp/preprocessor/hash-import-directive-cpp?view=vs-2019

### Runtime requirements

- MSVC 14.2+
- .NET Framework 4.7.2+
- MSBuild 16.0+
- python 3.7+

```

FAQs
----

### **How to verify aclcache is enabled?**

If aclache is enabled after you set environment variables and 
call `%ASSEMBLYREF%\aclcache\initialize.bat`, you will be able to execute
the `aclcache -s` command and see the aclcache configuration and statistics.
Note that `aclcache` is a doskey command and it expand to appropiate command paths 
depend on your environement settings.

### **Is aclcache working for all MSVC projects?**

Not all projects are currently supported. Notably, Makefile based projects and mananged C++ projects are currently
not supported(It does not mean they cannot be build. It just means it will fallback to build these projects as-is without aclcache). Also, if the project uses a custom build step to do linking then it is not supported.

### **How to purge aclcache cache?**

aclcache cache is located at `ACLCACHE_DIR`. 
you can execute the following command to purge the cache.

```batch
aclcache --clear
```

### **How to boost performance of aclcache?**


```batch

If `ACLCACHE_HARDLINK` is set, cached object files won't be copied to their
final location. Instead, hard links pointing to the cached object files
will be created. If `ACLCACHE_SERVER` is set, aclcache will use a server process to cache all the header files' hash which will greatly improves performance during
header file content matching.


### **How to disable aclcache?**

You can remove the `ACLCACHE_MODE` environment variable to disable aclache

```batch
set ACLCACHE_MODE=
```

### **How do I know which version of aclcache I'm using?**

If you run `fabric aget` you will find out the exact version of aclcache downloaded by looking at the symbolic link inside `ACPAPCKAGEDIR`

### **How do I check cache stats (hitrate etc)**

After you enable aclcache. You can run `aclcache -s` command to print out the stats of aclcache.

Environment Variables
---------------------

### ACLCACHE_MODE

 Value | Meaning                               
-------|---------------------------------------
 1     | Enable compiler cache support         
 2     | Enable [linker cache][How clcache works] support           
 3     | Enable both compiler and [linker cache][How clcache works]

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

If aclache is enabled, you will be able to execute
the `aclcache` command with the following command line switches

**--help(-h)**<br/>
    Print usage information

**--stat(-s)**<br/>
    Print some statistics about the cache (cache hits, cache misses, cache size etc.)

**--clear(-c)**<br/>
    Clean the cache: remove all cached objects, but keep the cache statistics (hits, misses, etc.).

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

Aclcache borrows design ideas from both of ccache and clcache. It is important
that you have basic understanding of [how ccache works] and [how clcache works].

Alcache is both a compiler cache and a linker cache.
Aclcache does not work by replacing the compiler like ccache and clcache.

Aclcache consists of three components: 

- aclache.dll: <br/>
  A MSBuild extention that intercepts invokation parameter to compiler and linker and calls aclcache.py to determine hit result.
- aclcache.py: <br/> 
  A python module that caches the compiler/linker artifacts and return to caller the hit result.
- aclachesrv.py: <br/>
  A background python process that caches the hash of files to boost performance of aclcache such that a particular file does not need to be hashed more than once.
 
Aclcache is instead designed to intercept calls to cl.exe and linker.exe by a
msbuild extenstion. The extention calls the python script to do hit testing
and before and after calls to cl.exe and linker.exe.

Aclcache does not call the preprocessor. It works more like the [depend mode of ccache].
Aclcache uses the tlog files produced by the MSBduild [file tracker] to generate the dependent headers of a particular cpp file. Likewise, it also use tlog files to find out
the dependent lib files of a particular executble.

[how ccache works]: https://ccache.dev/manual/latest.html#_how_ccache_works
[how clcache works]: https://github.com/frerich/clcache#how-clcache-works
[depend mode of ccache]: https://ccache.dev/manual/latest.html#_the_depend_mode
[file tracker]: https://docs.microsoft.com/en-us/visualstudio/msbuild/file-tracking

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
