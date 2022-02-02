using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Linq.Expressions;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using Microsoft.Build.Execution;
using static Aclcache.Utils;
using static Aclcache.CacheStrategy;
using Microsoft.Build.Framework;
using Microsoft.Build.CPPTasks;
using Microsoft.Build.Utilities;
using Microsoft.Win32.SafeHandles;

namespace Aclcache
{
    public class CsvFileWriter : StreamWriter
    {

        public CsvFileWriter(string filename, params string[] row)
            : base(filename, false, Encoding.Unicode, 1024 * 1024)
        {
            if (row.Length > 0)
            {
                WriteRow(row.Append(Utils._version).Append(Utils._currentOemEncoding.CodePage.ToString()));
            }
        }
        public void WriteRow(IEnumerable<string> row)
        {
            WriteLine(string.Join("|", row)) ;
            WriteLine("^^");
        }
        public void WriteRow(params string[] row)
        {
            WriteRow((IEnumerable<string>)row);
        }

    }
    internal static class Utils
    {
        internal static string GetTemporaryFile(string extension, bool createFile = false, string directory = null)
        {
            if (extension[0] != '.')
            {
                extension = '.' + extension;
            }
            directory = directory ?? Path.GetTempPath();

            Directory.CreateDirectory(directory);

            string file = Path.Combine(directory, $"tmp{Guid.NewGuid():N}{extension}");

            if (createFile)
            {
                File.WriteAllText(file, string.Empty);
            }
            return file;
        }

        [System.Runtime.InteropServices.DllImport("kernel32.dll", EntryPoint = "GetOEMCP")] public static extern int GetOEMCP();

        public static string _pythonLocation_l;
        public static string _pythonLocation => _pythonLocation_l ?? (_pythonLocation_l = Utils.GetPythonLocation("pythonw.exe"));
        public static Lazy<string> _pythonLocation2 = new Lazy<string>(() => Utils.GetPythonLocation());
        public static string _version_l;
        public static string _version  => _version_l ?? (_version_l = string.Join(".", Environment.OSVersion.Version.Build, Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows NT\CurrentVersion")?.GetValue("UBR") ?? "0"));
        public static string _clcacheLocation_l;
        public static string _clcacheLocation => _clcacheLocation_l ?? (_clcacheLocation_l = Utils.GetClCacheLocation());
        public static Encoding _currentOemEncoding_l;
        public static Encoding _currentOemEncoding => _currentOemEncoding_l ?? (_currentOemEncoding_l = Encoding.GetEncoding(GetOEMCP()));
        public static string GetClCacheLocation()
        {
            if (Environment.GetEnvironmentVariable("ACLCACHE_LOCATION") is string loc &&
                System.IO.Directory.Exists(loc))
            {
                loc.TrimEnd('\\');
                return loc;
            }

            return AssemblyDirectory;
        }

        public static string GetPythonLocation(string name = "python.exe")
        {
            string a;
            if (Environment.GetEnvironmentVariable("ACLCACHE_PYTHON") is string loc &&
                File.Exists(a = Path.Combine(loc, name)))
            {
                return a;
            }

            var path = Environment.GetEnvironmentVariable("PATH")
                    ?.Split(';')
                    .Where(s => File.Exists(Path.Combine(s, "python.exe")))
                    .FirstOrDefault();
            if (path != null) path = Path.Combine(path, "python.exe");
            path = path ?? "python.exe";
            return path;
        }

        public static string AssemblyDirectory
        {
            get
            {
                return System.IO.Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
            }
        }
        internal static string GetTemporaryFile(string directory, string extension, bool createFile = true)
        {
            if (extension[0] != '.')
            {
                extension = '.' + extension;
            }

            directory = directory ?? Path.GetTempPath();

            Directory.CreateDirectory(directory);

            string file = Path.Combine(directory, $"tmp{Guid.NewGuid():N}{extension}");

            if (System.IO.File.Exists(file))
            {
                File.WriteAllText(file, string.Empty);
            }

            return file;
        }
        public static System.Diagnostics.ProcessStartInfo GetProcessStartInfo(string pathToTool, string commandLineCommands, bool redirect = false)
        {
            // Build up the command line that will be spawned.
            string commandLine = commandLineCommands;
            if (commandLine.Length > 32000)
            {
                throw new InvalidDataException("GetProcessStartInfo CommandTooLong");
            }

            var startInfo = new System.Diagnostics.ProcessStartInfo(pathToTool, commandLine);
            startInfo.CreateNoWindow = true;
            startInfo.UseShellExecute = false;
            if (redirect)
            {
                startInfo.RedirectStandardError = redirect;
                startInfo.RedirectStandardOutput = redirect;
                // ensure the redirected streams have the encoding we want
                startInfo.StandardErrorEncoding = _currentOemEncoding;
                startInfo.StandardOutputEncoding = _currentOemEncoding;
                startInfo.RedirectStandardInput = redirect;

            }
            startInfo.EnvironmentVariables.Remove("PYTHONDONTWRITEBYTECODE");
            startInfo.EnvironmentVariables.Remove("PYTHONUNBUFFERED");

            return startInfo;
        }
    }

    public class Timer : IDisposable
    {
        private Action<TimeSpan> _action;
        private DateTime _start = DateTime.Now;
        public Timer(Action<TimeSpan> a)
        {
            _action = a;
        }
        public void Dispose()
        {
            _action(DateTime.Now - _start);
        }
    }
    [Flags] public enum CacheStrategy : Int32
    {
        None = 0,
        UseCCache = 1,
        UseLinkerCache = 2,
        UseNoPdb = 4,
        UseNoPch = 8,
        UseZ7 = 16,
        AsyncCcache = 32,
        AsyncLinker = 64,
        UseRepro = 128,
        UsePatchAssembly = 256,
        UseSharedPchGen = 512,
    }
    [Flags] public enum BuildState : Int32
    {
        CompilerNotInvoked = 0,
        ClCachePreInvoked = 1,
        CompileFinished = 2,
        ClCachePostInvoked = 4,
        LinkerCachePreInvoked = 8,
        LinkerCachePostInvoked = 16,
    }
    public static class BuildWorkFlow
    {
        static char[] StringArraySplitter = new char[] { ';' };
        public static int PopulateTaskFromSourceItem(this object task, Type taskType, ITaskItem source, TrackedVCToolTaskInterfaceHelper schedulingTask)
        {
            int num = 0;
            foreach (PropertyInfo propertyInfo in taskType.GetProperties())
            {
                string name = propertyInfo.Name;
                if (!string.IsNullOrEmpty(name))
                {
                    if (string.Compare(schedulingTask.SourcesPropertyName, name, StringComparison.OrdinalIgnoreCase) == 0)
                    {
                        if (propertyInfo.PropertyType == typeof(ITaskItem))
                        {
                            propertyInfo.SetValue(schedulingTask.Instance, source);
                        }
                        else if (propertyInfo.PropertyType == typeof(ITaskItem[]))
                        {
                            propertyInfo.SetValue(schedulingTask.Instance, new ITaskItem[]
                            {
                                source
                            });
                        }
                        num++;
                    }
                    else
                    {
                        string metadata = source.GetMetadata(name);
                        if (!string.IsNullOrEmpty(metadata))
                        {
                            if (propertyInfo.PropertyType == typeof(bool))
                            {
                                propertyInfo.SetValue(schedulingTask.Instance, bool.Parse(metadata));
                            }
                            else if (propertyInfo.PropertyType == typeof(string))
                            {
                                propertyInfo.SetValue(schedulingTask.Instance, metadata);
                            }
                            else if (propertyInfo.PropertyType == typeof(string[]))
                            {
                                string[] value = (from p in metadata.Split(StringArraySplitter, StringSplitOptions.RemoveEmptyEntries)
                                                  select p.Trim()).ToArray<string>();
                                propertyInfo.SetValue(schedulingTask.Instance, value);
                            }
                            else if (propertyInfo.PropertyType == typeof(ITaskItem[]))
                            {
                                string[] array = (from p in metadata.Split(StringArraySplitter, StringSplitOptions.RemoveEmptyEntries)
                                                  select p.Trim()).ToArray<string>();
                                ITaskItem[] array2 = new ITaskItem[array.Length];
                                for (int j = 0; j < array.Length; j++)
                                {
                                    //array2[j] = new TaskItem(array[j]);
                                    array2[j] = new Microsoft.Build.Utilities.TaskItem(array[j]);
                                }
                                propertyInfo.SetValue(schedulingTask.Instance, array2);
                            }
                            else
                            {
                                if (!(propertyInfo.PropertyType == typeof(int)))
                                {
                                    throw new InvalidCastException(string.Concat(new string[]
                                    {
                                        "Unable to cast ",
                                        name,
                                        " of type ",
                                        propertyInfo.PropertyType.ToString(),
                                        " into bool, string, string[]."
                                    }));
                                }
                                propertyInfo.SetValue(schedulingTask.Instance, int.Parse(metadata));
                            }
                            num++;
                        }
                    }
                }
            }
            return num;
        }

        public class CompileArtifact
        {
            public CompileArtifact(string filename, string fullpath, string cmd, bool pch, string pchfile = null)
            {
                ItemSpec = filename;
                FullPath = fullpath;
                Cmd = cmd;
                GenPch = pch;
            }
            public string ItemSpec;
            public string Cmd;
            public bool GenPch;
            public string PchHeader;
            public string FullPath;
            public IEnumerable<string> Dependency { get; set; } = new string[0];
            public List<string> Output { get; set; } = new List<string>();

            public bool UsePch => (!GenPch) && (PchHeader != null);
        }

        public class LinkArtifact
        {
            public bool IsLink { get; set; } = false;
            public bool IsDll { get; set; } = false;

            public string _libGen { get; set; } = null;
            public IEnumerable<string> Input { get; set; } = new string[0];
            public IEnumerable<string> AdditionalInput { get; set; } = new string[0];
            public IEnumerable<string> Dependency { get; set; } = new string[0];
            public List<string> Output { get; set; } = new List<string>();
            public string Cmdline { get; set; }
            public string MainOut { get; set; }
        }

        public class ProjectInfo
        {
            public string FullPath;
            public string[] Targets;
            public int ReqId;
            public ProjectItemInstance[] ClCompile;
            public List<CompileArtifact> CompileArtifacts;

            public LinkArtifact LinkArtifact = new LinkArtifact();
            public string PathToCL;
            public string PathToLinker { get; private set; }

            public Dictionary<string, CompileArtifact> CompileArtifactMap;
            public HashSet<string> ArtifactsHits = new HashSet<string>();
            public TimeSpan CompileTime, LinkTime, LibTime;
            public DateTime? Start;
            public DateTime? BeforeReferences;
            public DateTime? AfterReferences;
            public DateTime? BeforeCompile;
            public DateTime? BeforeLink;
            public DateTime? AfterLink;
            public DateTime? BeforeLib;
            public DateTime? AfterLib;
            public BuildState State { get; set; } = BuildState.CompilerNotInvoked;
            public bool CompileSuccess { get; set; } = true;
            public bool LinkSuccess { get; set; } = true;

            public bool CompileArtifactCollected { get; set; } = false;
            private IBuildEngine CurrentEngine;
            public CacheStrategy Strategy { get; set; } = CacheStrategy.None;
            public string WindowsSDKVersion { get; set; } = null;
            public bool ExcludeCommonDir { get; set; } = true;
            public string VCVersion { get; set; } = null;
         
            public static string Id(string path, int id)
            {
                return $"{path}_{id}";
            }
            public string UniqId
            {
                get
                {
                    return Id(FullPath, ReqId);
                }
            }
            public string Desc
            {
                get
                {
                    return $"{FullPath}({string.Join(" ", Targets)})";
                }
            }
            public virtual void CachePreprocess(string ClPath)
            {
                PathToCL = ClPath.ToUpper();
                CompileArtifacts = new List<BuildWorkFlow.CompileArtifact>();
                CompileArtifactMap = new Dictionary<string, CompileArtifact>();
                foreach (var item in ClCompile)
                {
                    var taskitem = item.getProp<ITaskItem>("_taskItem");
                    if (taskitem.GetMetadata("ExcludedFromBuild") == "true") continue;
                    var cl = new Microsoft.Build.CPPTasks.CL();
                    var trackedVCToolTaskInterfaceHelper =
                        new TrackedVCToolTaskInterfaceHelper(cl, typeof(Microsoft.Build.CPPTasks.CL));
                    this.PopulateTaskFromSourceItem(typeof(Microsoft.Build.CPPTasks.CL), taskitem, trackedVCToolTaskInterfaceHelper);
                    var cmd = trackedVCToolTaskInterfaceHelper.GenerateCommandLineExceptSwitches(new string[] { "Sources" }, VCToolTask.CommandLineFormat.ForTracking);
                    var artifact = new CompileArtifact(taskitem.ItemSpec, taskitem.GetMetadata("FullPath").ToUpper(), cmd, cl.PrecompiledHeader == "Create");
                    if (!string.IsNullOrEmpty(cl.PrecompiledHeaderFile))
                    {
                        if (!string.IsNullOrEmpty(cl.PrecompiledHeaderOutputFile))
                        {
                            artifact.PchHeader =  (new TaskItem(cl.PrecompiledHeaderOutputFile)).GetMetadata("FullPath").ToUpper();
                        }
                        else
                            artifact.PchHeader = cl.PrecompiledHeaderFile;
                    }
                    if (!CompileArtifactMap.ContainsKey(artifact.ItemSpec))
                    {
                        CompileArtifacts.Add(artifact);
                        CompileArtifactMap.Add(artifact.ItemSpec, artifact);
                    }
                }
            }
            public int InvokeClCache(string switches, out string result, bool wait = true, string cmdline = null)
            {
                var proc = new System.Diagnostics.Process();
                cmdline = cmdline ?? $"-E \"{_clcacheLocation}\\aclcache.py\" {switches}";
                proc.StartInfo = Utils.GetProcessStartInfo(_pythonLocation, cmdline, false);

                int ExitCode = -1;
                result = string.Empty;

                LogMessage($"{_pythonLocation} {cmdline}");
                if (wait)
                {
                    string s = string.Empty;
                    proc.StartInfo.RedirectStandardOutput = true;
                    proc.StartInfo.RedirectStandardError = true;
                    proc.OutputDataReceived += (object sender, System.Diagnostics.DataReceivedEventArgs e) =>
                    {
                        if (e.Data != null)
                        {
                            s = e.Data;
                            LogMessage(s);
                        }
                    };
                    proc.ErrorDataReceived += (object sender, System.Diagnostics.DataReceivedEventArgs e) =>
                    {
                        if (!string.IsNullOrEmpty(e.Data))
                        {
                            LogError(e.Data);
                        }
                    };
                    proc.Start();
                    proc.BeginOutputReadLine();
                    proc.BeginErrorReadLine();
                    proc.WaitForExit();
                    result = s;
                    ExitCode = proc.ExitCode;
                }
                else
                {
                    proc.Start();
                }

                //// sign up for stderr callbacks
                //proc.BeginErrorReadLine();
                //// sign up for stdout callbacks
                //proc.BeginOutputReadLine();

                //// start the time-out timer
                //_toolTimer = new Timer(ReceiveTimeoutNotification, null, Timeout, System.Threading.Timeout.Infinite /* no periodic timeouts */);

                //// deal with the various notifications
                //HandleToolNotifications(proc);

                return ExitCode;
            }

            public virtual void PreInvokeClcache()
            {
                if (CompileArtifacts == null) return;
                State |= BuildState.ClCachePreInvoked;
                if (IsSharedPch())
                {
                    return;
                }
                var tmpfile = Utils.GetTemporaryFile(".1.txt");
                using (var writer = GetWriter(tmpfile, PathToCL))
                {
                    foreach (var item in CompileArtifacts)
                    {
                        writer.WriteRow(item.ItemSpec, item.FullPath, item.GenPch ? "2" : item.UsePch ? "1" : "0", item.PchHeader, item.Cmd);
                    }
                }
                if (System.IO.File.Exists(tmpfile))
                {
                    var exitcode = InvokeClCache($"-p \"{tmpfile}\" -b \"{PathToCL}\" -f \"{Desc}\"", out var ret);
                    if (exitcode == 0)
                    {
                        var lines = ret.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None);
                        ret = lines[lines.Length - 1];
                        var hits = ret.Split(new[] { "*" }, StringSplitOptions.RemoveEmptyEntries);
                        foreach (var item in hits)
                        {
                            ArtifactsHits.Add(item);
                        }
                    }
                }
            }

            private bool IsSharedPch()
            {
                return Strategy.HasFlag(CacheStrategy.UseSharedPchGen); //CompileArtifacts.Count == 1 && CompileArtifacts[0].GenPch
            }

            public virtual void PostInvokeClcache()
            {
                if (!State.HasFlag(BuildState.ClCachePreInvoked) || !State.HasFlag(BuildState.CompileFinished)
                    || State.HasFlag(BuildState.ClCachePostInvoked) || !CompileSuccess)
                    return;

                State |= BuildState.ClCachePostInvoked;

                var tmpfile = Utils.GetTemporaryFile(".2.txt");
                bool something = false;
                using (var writer = GetWriter(tmpfile, PathToCL))
                {
                    foreach (var item in CompileArtifacts)
                    {
                        if (item.Output.Count > 0)
                        {
                            something = true;
                            writer.WriteRow(item.ItemSpec, item.FullPath, item.GenPch ? "2" : item.UsePch ? "1" : "0", item.PchHeader, item.Cmd, string.Join("*", item.Dependency), string.Join("*", item.Output));
                        }
                    }
                }
                if (something)
                {
                    InvokeClCache($"-q \"{tmpfile}\" -b \"{PathToCL}\" -f \"{Desc}\"", out var ret, Strategy.HasFlag(AsyncCcache) || IsSharedPch() );
                }
                else
                {
                    System.IO.File.Delete(tmpfile);
                }
            }

            private string[] CalcAdditional(IEnumerable<string> AdditionalDependencies, IEnumerable<string> AdditionalDirectries)
            {
                AdditionalDependencies = AdditionalDependencies ?? Enumerable.Empty<string>();
                AdditionalDirectries = AdditionalDirectries ?? Enumerable.Empty<string>();
                if (Environment.GetEnvironmentVariable("LIB") is string lib)
                {
                    AdditionalDirectries = AdditionalDirectries.Concat(lib.Split(StringArraySplitter, StringSplitOptions.RemoveEmptyEntries));

                }
                HashSet<string> result = new HashSet<string>();
                foreach (var item in AdditionalDependencies)
                {
                    var x = item.Trim('"');
                    if (Path.IsPathRooted(x) && File.Exists(x))
                        result.Add(x.ToUpper());
                    var path = AdditionalDirectries.Where(s => File.Exists(Path.Combine(s, x))).FirstOrDefault();
                    if (path != null)
                        result.Add(Path.GetFullPath(Path.Combine(path, x)).ToUpper());
                }
                return result.ToArray();
            }

            internal bool PreInvokeLinkerCache(IEnumerable<ITaskItem> Sources, string output, IEnumerable<string> AdditionalDependencies, IEnumerable<string> AdditionalDirectries, TrackedVCToolTask tool)
            {
                System.Diagnostics.Debug.Assert(!State.HasFlag(BuildState.LinkerCachePreInvoked));

                this.State |= BuildState.LinkerCachePreInvoked;

                var additonal = CalcAdditional(AdditionalDependencies, AdditionalDirectries);
                additonal = FilterInput(additonal, tool, null).ToArray();
                var sources = Sources.Select(x => x.GetMetadata("FullPath").ToUpper()).ToArray();
                if (LinkArtifact.IsLink)
                    output = output ?? (LinkArtifact.IsDll ? Path.ChangeExtension(sources.First(x => x.ToUpper().EndsWith(".OBJ")), ".DLL") : Path.ChangeExtension(sources.First(x => x.ToUpper().EndsWith(".OBJ")), ".EXE"));
                else
                    output = output ?? Path.ChangeExtension(sources.First(x => x.ToUpper().EndsWith(".OBJ")), ".LIB");

                this.PathToLinker = tool.invoke<string>("ComputePathToTool").ToUpper();
                Array.Sort(sources);
                Array.Sort(additonal);
                this.LinkArtifact.Input = sources;
                this.LinkArtifact.AdditionalInput = additonal;
                this.LinkArtifact.Cmdline = tool.GenerateCommandLineExceptSwitches(new string[] { "Sources" }, VCToolTask.CommandLineFormat.ForTracking);
                this.LinkArtifact.MainOut = (new TaskItem(output)).GetMetadata("FullPath").ToUpper();
                var tmpfile = Utils.GetTemporaryFile(".3.txt");
                using (var writer = GetWriter(tmpfile, PathToLinker))
                {
                    writer.WriteRow(string.Join("*", LinkArtifact.Input.Concat(LinkArtifact.AdditionalInput)), LinkArtifact.Cmdline, LinkArtifact.MainOut);
                }
                if (System.IO.File.Exists(tmpfile))
                {
                    var exitcode = InvokeClCache($"-m \"{tmpfile}\" -b \"{PathToLinker}\" -f \"{Desc}\"", out var ret);
                    BuildWorkFlow.DebugHook(5);
                    if (exitcode == 0)
                    {
                        var lines = ret.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None);
                        ret = lines[lines.Length - 1];
                        var hits = ret.Split(new[] { "*" }, StringSplitOptions.RemoveEmptyEntries);
                        return hits.Length > 0 && hits[0] == LinkArtifact.MainOut;
                    }
                }

                return false;
            }

            internal void PatchAssembly(IEnumerable<ITaskItem> Sources, string output, CanonicalTrackedInputFiles SourceDependencies, Microsoft.Build.CPPTasks.Link tool)
            {
                DebugHook(7);
                if (!tool.SkippedExecution && this.Strategy.HasFlag(UseRepro) && this.Strategy.HasFlag(UsePatchAssembly))
                {
                    var sources = Sources.Select(x => x.GetMetadata("FullPath").ToUpper()).ToArray();
                    Array.Sort(sources);

                    var depends = FilterLinkTlogs(SourceDependencies.DependencyTable, sources);
                    if (!depends.Any(x => x.EndsWith("MSCOREE.LIB")))
                        return;

                    if (output == null)
                    {
                        output = (tool.LinkDLL ? Path.ChangeExtension(sources.First(x => x.ToUpper().EndsWith(".OBJ")), ".DLL") : Path.ChangeExtension(sources.First(x => x.ToUpper().EndsWith(".OBJ")), ".EXE"));
                    }
                    InvokeClCache(string.Empty, out var ret, true, $"-E \"{_clcacheLocation}\\patcher.py\" {output}");
                }
            }

            internal void PostInvokeLinkerCache(CanonicalTrackedInputFiles SourceDependencies, CanonicalTrackedOutputFiles SourceOutputs, TrackedVCToolTask tool)
            {
                if (!State.HasFlag(BuildState.LinkerCachePreInvoked)
                     || State.HasFlag(BuildState.LinkerCachePostInvoked) || !LinkSuccess)
                    return;
                State |= BuildState.LinkerCachePostInvoked;

                var depends = FilterInput(FilterLinkTlogs(SourceDependencies.DependencyTable), tool, null);
                var outputs = FilterLinkTlogs(SourceOutputs.DependencyTable).ToHashSet();
                System.Diagnostics.Debug.Assert(outputs.Contains(LinkArtifact.MainOut));
                var inputs = new HashSet<string>(LinkArtifact.Input.Concat(LinkArtifact.AdditionalInput));
                if (this.LinkArtifact.IsLink)
                {
                    if (LinkArtifact._libGen is string _libGen)
                    {
                        outputs.Add(_libGen);
                        var liboutput = Path.ChangeExtension(_libGen, ".LIB");
                        if (File.Exists(liboutput))
                            outputs.Add(liboutput);
                    }
                    else if (tool.SkippedExecution)
                    {
                        var link = (Link)tool;
                        var liboutput = link.ImportLibrary != null ? (new TaskItem(link.ImportLibrary)).GetMetadata("FullPath").ToUpper() :
                            LinkArtifact.MainOut;
                        liboutput = Path.ChangeExtension(liboutput, ".EXP");
                        if (!inputs.Contains(liboutput) && File.Exists(liboutput))
                        {
                            outputs.Add(liboutput);
                            liboutput = Path.ChangeExtension(liboutput, ".LIB");
                            if (File.Exists(liboutput)) outputs.Add(liboutput);
                        }
                    }
                }

                depends.ExceptWith(outputs);  // remove inputs that are also outputs
                depends.ExceptWith(inputs);

                var tmpfile = Utils.GetTemporaryFile(".4.txt");
                using (var writer = GetWriter(tmpfile, PathToLinker))
                {
                    writer.WriteRow(string.Join("*", LinkArtifact.Input.Concat(LinkArtifact.AdditionalInput)), this.LinkArtifact.Cmdline, this.LinkArtifact.MainOut, string.Join("*", depends), string.Join("*", outputs));
                }
                if (System.IO.File.Exists(tmpfile))
                {
                    BuildWorkFlow.DebugHook(6);
                    InvokeClCache($"-n \"{tmpfile}\" -b \"{PathToLinker}\" -f \"{Desc}\"", out var ret, Strategy.HasFlag(AsyncLinker));
                }
            }

            private CsvFileWriter GetWriter(string tmpfile, string tool)
            {
                var writer = new CsvFileWriter(tmpfile, FullPath, tool, WindowsSDKVersion, VCVersion);
                writer.WriteRow(string.Empty, IsSharedPch() ? "GenerateSharedPCH=1" : string.Empty ,
                    Environment.GetEnvironmentVariable("CL") is string cl ? $"CL={cl}" : string.Empty,
                    Environment.GetEnvironmentVariable("_CL_") is string _cl ? $"_CL_={_cl}" : string.Empty
                    );
                return writer;
            }

            public bool IsOldStyleClcache => Strategy.HasFlag(UseCCache) && Strategy.HasFlag(UseNoPch) && (Strategy.HasFlag(UseNoPdb) || Strategy.HasFlag(UseZ7));
            public bool IsNewStyleClcache => Strategy.HasFlag(UseCCache) && !Strategy.HasFlag(UseNoPch);

            public bool IsLinkerCache => Strategy.HasFlag(UseLinkerCache);

            public string[] CommonLibraryDir { get; set; } = new string[0];

            internal void SetCurrentEngine(IBuildEngine engine)
            {
                CurrentEngine = engine;
            }
            internal void LogMessage(string msg)
            {
                CurrentEngine.LogMessageEvent(new BuildMessageEventArgs(msg, null, null, MessageImportance.Normal));
            }
            internal void LogError(string msg)
            {
                CurrentEngine.LogErrorEvent(new BuildErrorEventArgs("ClCache", null, null, 1, 2, 3, 4, msg, null, null));
            }

            internal HashSet<string> FilterInput(IEnumerable<string> inputs, TrackedVCToolTask task, IEnumerable<string> commondir)
            {
                var tool = PathToCL ?? PathToLinker ?? task.invoke<string>("ComputePathToTool").ToUpper();
                var tooldir = Path.GetDirectoryName(tool).ToUpper();
                return inputs.Where(x => Path.GetDirectoryName(x) is string dir && !dir.StartsWith(tooldir) && !CommonDirTest(this.CommonLibraryDir, dir)).ToHashSet();
            }

            private bool CommonDirTest(IEnumerable<string> commondir, string dir)
            {
                if (ExcludeCommonDir)
                    return commondir.Any(x => dir.StartsWith(x));
                else
                    return false;
            }
            
            internal IEnumerable<string> FilterLinkTlogs<T>(Dictionary<string, Dictionary<string, T>> deptable, IEnumerable<string> inputs = null)
            {
                var inputmarker = string.Join("|", inputs ?? LinkArtifact.Input);
                foreach (var item in deptable)
                {
                    var marker = item.Key.Split('|');
                    Array.Sort(marker);
                    if (inputmarker == string.Join("|", marker))
                        return item.Value.Keys;
                }
                System.Diagnostics.Trace.Assert(false, "Linker tlog parsing error");
                return deptable.First().Value.Keys;
            }

        }
        private static Dictionary<string, ProjectInfo> _projects = new Dictionary<string, ProjectInfo>();

        static BuildWorkFlow()
        {

            DebugHook(1);
        }

        private static int? g_Aedebug_l;
        private static int g_aedebug => (int)( g_Aedebug_l ?? (g_Aedebug_l = ((Environment.GetEnvironmentVariable("ACLCACHE_DEBUG") is string _tmp && Int32.TryParse(_tmp, out var t_Aedebug_l)) ? t_Aedebug_l : 0)));
        [System.Diagnostics.Conditional("DEBUG")] public static void DebugHook(int level = 1)
        {
            if (g_aedebug == level)
            {
                while (true)
                {
                    if (System.Diagnostics.Debugger.IsAttached)
                    {
                        System.Diagnostics.Debugger.Break();
                        break;
                    }
                    else
                    {
                        System.Threading.Thread.Sleep(500);
                    }
                }
            }
        }
        public static T getProp<T>(this object obj, string prop)
        {
            var field = obj.GetType().GetField(prop, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
            if (field == null)
            {
                var p = obj.GetType().GetProperty(prop, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
                return (T)p?.GetValue(obj);
            }
            return (T)field.GetValue(obj);
        }
        public static object getProp(this object obj, string prop)
        {
            return obj.getProp<object>(prop);
        }

        public static Delegate ConvertDelegate(Delegate func, Type dtype, params Type[] argType)
        {
            var param = argType.Select(x => Expression.Parameter(x)).ToArray();
            var convertedParam = param.Select(x => Expression.Convert(x, typeof(object))).ToArray();

            Expression call =
                func.Target == null
                ? Expression.Call(func.Method, convertedParam)
                : Expression.Call(Expression.Constant(func.Target), func.Method, convertedParam);

            return Expression.Lambda(dtype, call, param).Compile();
        }

        public static void addEvent(this object obj, string prop, Delegate dele)
        {
            var evt = obj.GetType().GetEvent(prop, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            var types = evt.EventHandlerType.GetMethod("Invoke").GetParameters().Select(x => x.ParameterType).ToArray();
            evt.AddEventHandler(obj, ConvertDelegate(dele, evt.EventHandlerType, types));
        }

        public static T invokeT<T>(Type type, object obj, string prop, Type[] types, object[] pars)
        {
            if (type == null || type == typeof(object) || !type.IsClass || type.IsInterface)
            {
                throw new InvalidDataException("error in invoking method");
            }
            var method = type.GetMethod(prop, BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance, Type.DefaultBinder, types, null);
            if (method == null)
            {
                type = type.BaseType;
                return invokeT<T>(type, obj, prop, types, pars);
            }
            else
            {
                return (T)method.Invoke(obj, pars);
            }
        }
        public static T invoke<T>(this object obj, string prop, params object[] pars)
        {
            var type = obj.GetType();
            var types = pars.Select(x => x.GetType()).ToArray();
            return invokeT<T>(type, obj, prop, types, pars);
        }

        public static void invoke(this object obj, string prop, params object[] pars)
        {
            var types = pars.Select(x => x.GetType()).ToArray();
            var method = obj.GetType().GetMethod(prop, BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance, Type.DefaultBinder, types, null);
            method.Invoke(obj, pars);
        }
        public static string ProjectProperty(this Microsoft.Build.Framework.IBuildEngine engine, string prop)
        {
            var field = engine.getProp("_requestEntry").getProp("RequestConfiguration").getProp("BaseLookup").invoke<Microsoft.Build.Execution.ProjectPropertyInstance>("GetProperty", prop);
            return field?.EvaluatedValue;
        }

        public static string ProjectProperty(this object entry, string prop)
        {
            var field = entry.getProp("RequestConfiguration").getProp("BaseLookup").invoke<Microsoft.Build.Execution.ProjectPropertyInstance>("GetProperty", prop);
            return field?.EvaluatedValue;
        }

        public static ProjectInfo Begin(this Microsoft.Build.Framework.IBuildEngine engine)
        {
            var fullpath = engine.getProp("_requestEntry").getProp("RequestConfiguration").getProp<string>("ProjectFullPath");
            var reqId = engine.getProp("_requestEntry").getProp("Request").getProp<int>("GlobalRequestId");
            var hash = ProjectInfo.Id(fullpath, reqId);
            if (!_projects.TryGetValue(hash, out var project))
            {
                project = new ProjectInfo()
                {
                    FullPath = fullpath,
                    ReqId = reqId,
                    Start = DateTime.Now,
                    Targets = engine.getProp("_requestEntry").getProp("Request").getProp<IEnumerable<string>>("Targets").ToArray(),
                };
                if (project.Targets.Length == 0)
                {
                    project.Targets = engine.getProp("_requestEntry").getProp("RequestConfiguration").getProp<IEnumerable<string>>("ProjectDefaultTargets").ToArray();
                }
                engine.getProp("_requestEntry").addEvent("OnStateChanged", (Action<object, object>)((entry, b) =>
                {
                    if (3 == (int)Convert.ChangeType(b, typeof(int)))
                    {
                        if (_projects.TryGetValue(hash, out var _))
                        {
                            project.PostInvokeClcache();
                            LogTiming(entry, project);
                            LogBinaryFiles(entry, project);
                            lock (_projects)
                            {
                                _projects.Remove(hash);
                            }
                        }
                    }
                }));
                engine.PopulateProjectStrategy(project);
                lock (_projects)
                {
                    _projects.Add(hash, project);
                }
            }
            project.SetCurrentEngine(engine);
            return project;
        }

        public static void PopulateProjectStrategy(this Microsoft.Build.Framework.IBuildEngine engine, ProjectInfo project)
        {
            var _useccache = ProjectProperty(engine, "ACLCACHE_MODE");
            if (!string.IsNullOrEmpty(_useccache) && Int32.TryParse(_useccache, out var useccache))
            {
                if (useccache == 0)
                {
                    var file = ProjectProperty(engine, "ACLCACHE_LOG");
                    var msg = $"Skip processing[ACLCACHE_MODE=0] {project.Desc}\n";
                    if (Int32.TryParse(file, out var _))
                        engine.LogMessageEvent(new BuildMessageEventArgs(msg, null, null, MessageImportance.Normal));
                    else if (!string.IsNullOrEmpty(file))
                        AppendLog(file, msg);
                }
                if ((useccache & 1) == 1)
                    project.Strategy |= CacheStrategy.UseCCache;
                if ((useccache & 2) == 2)
                    project.Strategy |= CacheStrategy.UseLinkerCache;
                if (!string.IsNullOrEmpty(ProjectProperty(engine, "_USENOPCH")))
                    project.Strategy |= CacheStrategy.UseNoPch;
                if (!string.IsNullOrEmpty(ProjectProperty(engine, "_USENOPDB")))
                    project.Strategy |= CacheStrategy.UseNoPdb;
                if (!string.IsNullOrEmpty(ProjectProperty(engine, "ACLCACHE_USEZ7")))
                    project.Strategy |= CacheStrategy.UseZ7;
                if (!string.IsNullOrEmpty(ProjectProperty(engine, "GenerateSharedPCH")))
                    project.Strategy |= CacheStrategy.UseSharedPchGen;
                
                if (ProjectProperty(engine, "ACLCACHE_SYNC") is string _async && Int32.TryParse(_async, out var async_v))
                {
                    if ((async_v & 1) == 1)
                        project.Strategy |= CacheStrategy.AsyncCcache;
                    if ((async_v & 2) == 2)
                        project.Strategy |= CacheStrategy.AsyncLinker;
                }
                if (!string.IsNullOrEmpty(ProjectProperty(engine, "ACLCACHE_INCLUDECOMMONDIR")))
                    project.ExcludeCommonDir = false;
                if (project.ExcludeCommonDir)
                {
                    project.WindowsSDKVersion = string.Join("|", ProjectProperty(engine, "WindowsSDKVersion") ?? ProjectProperty(engine, "TargetPlatformVersion") ?? string.Empty, ProjectProperty(engine, "NETFXKitsDir") ?? string.Empty).ToUpper();
                    project.VCVersion = ProjectProperty(engine, "VCToolsVersion") ?? string.Empty;
                    IEnumerable<string> commonlib = (ProjectProperty(engine, "WindowsSdkDir") ?? string.Empty).ToUpper().Split(StringArraySplitter, StringSplitOptions.RemoveEmptyEntries);
                    commonlib = commonlib.Concat((ProjectProperty(engine, "NETFXKitsDir") ?? string.Empty).ToUpper().Split(StringArraySplitter, StringSplitOptions.RemoveEmptyEntries));;
                    commonlib = commonlib.Concat((ProjectProperty(engine, "VCINSTALLDIR") ?? string.Empty).ToUpper().Split(StringArraySplitter, StringSplitOptions.RemoveEmptyEntries));
                    var excludedirs = new HashSet<string>(commonlib);
                    excludedirs.Add(@"C:\WINDOWS");
                    project.CommonLibraryDir = excludedirs.ToArray();
                }
            }
            if (!string.IsNullOrEmpty(ProjectProperty(engine, "_USEBREPRO")))
                project.Strategy |= CacheStrategy.UseRepro;
            if (!string.IsNullOrEmpty(ProjectProperty(engine, "_USEPATCHASSEMBLY")))
                project.Strategy |= CacheStrategy.UsePatchAssembly;
        }
        public static ProjectInfo BeginCompile(this Microsoft.Build.Framework.IBuildEngine engine)
        {
            DebugHook(2);
            var project = Begin(engine);
            if (project.BeforeCompile == null)
            {
                project.BeforeCompile = DateTime.Now;
                if (project.IsNewStyleClcache)
                {
                    project.ClCompile = engine.getProp("_requestEntry").getProp("RequestConfiguration").getProp("BaseLookup").invoke<IEnumerable<ProjectItemInstance>>("GetItems", "ClCompile").ToArray();
                }
            }
            return project;
        }
        public static ProjectInfo BeginLink(this Microsoft.Build.Framework.IBuildEngine engine)
        {
            var project = Begin(engine);
            if (project.BeforeLink == null)
            {
                project.BeforeLink = DateTime.Now;
                project.LinkArtifact.IsLink = true;
            }
            return project;
        }
        public static void AfterLink(this Microsoft.Build.Framework.IBuildEngine engine, ProjectInfo project)
        {
            project.AfterLink = DateTime.Now;
        }

        public static ProjectInfo BeginLib(this Microsoft.Build.Framework.IBuildEngine engine)
        {
            var project = Begin(engine);
            if (project.BeforeLib == null)
            {
                project.BeforeLib = DateTime.Now;
                //var items = engine.getProp("_requestEntry").getProp("RequestConfiguration").getProp("BaseLookup").invoke("GetItems", "Link") as ICollection<Microsoft.Build.Execution.ProjectItemInstance>;
                //project.Link = items.ToArray();
            }
            return project;
        }

        public static void AfterLib(this Microsoft.Build.Framework.IBuildEngine engine, ProjectInfo project)
        {
            project.AfterLib = DateTime.Now;
        }

        [System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true, CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
        static extern SafeFileHandle CreateFile(string lpFileName, uint dwDesiredAccess, uint dwShareMode, IntPtr lpSecurityAttributes, uint dwCreationDisposition, uint dwFlagsAndAttributes, IntPtr hTemplateFile);
        [System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true)]
        static extern bool WriteFile(SafeFileHandle handle, byte[] bytes, int numBytesToWrite, out int numBytesWritten, IntPtr mustBeZero);

        // ILoggingService.LogBuildEvent ((Microsoft.Build.BackEnd.RequestBuilder)((Microsoft.Build.BackEnd.BuildRequestEntry)entry).Builder)._projectLoggingContext.LoggingService
        private static void LogTiming(this object engine, ProjectInfo project)
        {

            DateTime? starttime = project.Start ?? project.BeforeCompile ?? project.BeforeLib ?? project.BeforeLink;
            var compile = project.CompileTime.Ticks / 10000000.0;
            var link = project.LinkTime.Ticks / 10000000.0;
            var lib = project.LibTime.Ticks / 10000000.0;
            var other = starttime.HasValue ? (DateTime.Now.Ticks - starttime.Value.Ticks) / 10000000.0 - compile - link - lib : 0.0;
            string r = (project.State.HasFlag(BuildState.ClCachePreInvoked)) ?
            $"{project.Desc},{compile},{link},{lib},{other},{project.ArtifactsHits.Count},{project.CompileArtifacts.Count - project.ArtifactsHits.Count},{starttime},{DateTime.Now}\n"
                :
            $"{project.Desc},{compile},{link},{lib},{other},0,0,{starttime},{DateTime.Now} \n";
            System.Console.WriteLine(r);
            var file = ProjectProperty(engine, "ACLCACHE_STATLOG");
            if (Int32.TryParse(file, out var _)) return;
            if (!string.IsNullOrEmpty(file))
                AppendLog(file, r);
        }

        private static void LogBinaryFiles(this object engine, ProjectInfo project)
        {

            if (!string.IsNullOrEmpty(project.LinkArtifact.MainOut)) {
                string r = $"{project.LinkArtifact.MainOut}\n";
                var file = ProjectProperty(engine, "ACLCACHE_OUTPUT_BINARY_FILES");
                if (Int32.TryParse(file, out var _)) return;
                if (!string.IsNullOrEmpty(file))
                    AppendLog(file, r);
            }

        }

        static private void AppendLog(string file, string msg)
        {
            var handle = CreateFile(file, 0x00100000 | 4, 2 | 1, IntPtr.Zero, 4, 128, IntPtr.Zero);
            if (!handle.IsInvalid)
            {
                try
                {
                    var data = Encoding.UTF8.GetBytes(msg);
                    WriteFile(handle, data, data.Length, out var written, IntPtr.Zero);
                }
                finally
                {
                    handle.Close();

                }
            }
        }
    }
    public class CL : Microsoft.Build.CPPTasks.CL
    {
        protected BuildWorkFlow.ProjectInfo _project { get; set; }

        public override bool Execute()
        {
            _project = this.BuildEngine.BeginCompile();
            using var t = new Timer(t =>
            {
                _project.CompileTime += t;
            });
            if (_project.IsOldStyleClcache)
            {
                this.TrackFileAccess = false;
            }
            else if (_project.IsNewStyleClcache)
            {
                if (_project.CompileArtifacts == null)
                {
                    _project.CachePreprocess(this.invoke<string>("ComputePathToTool"));
                    _project.PreInvokeClcache();
                }
                var newsource = this.Sources.Where(x => !_project.ArtifactsHits.Contains(x.ItemSpec)).ToArray();
                this.Sources = newsource;
            }
            bool r = true;
            if (this.Sources.Length > 0)
            {
                if (this.BuildEngine.ProjectProperty("PlatformToolset") == "v143")
                    this.ComputeObjectFiles();
                r = base.Execute();
                if (r)
                {
                    PostProcess();
                    _project.State |= BuildState.CompileFinished;
                }
            }
            _project.CompileSuccess &= r;
            return r;
        }

        //protected override bool OutputDependencyFilter(string fullOutputPath)
        //{
        //    var ret = base.OutputDependencyFilter(fullOutputPath);
        //    return ret;
        //}
        protected override int PostExecuteTool(int exitCode)
        {
            var ret = base.PostExecuteTool(exitCode);
            return ret;
        }

        protected bool NotTLITLH(string fullOutputPath)
        {
            return !fullOutputPath.EndsWith(".TLH", StringComparison.OrdinalIgnoreCase) && !fullOutputPath.EndsWith(".TLI", StringComparison.OrdinalIgnoreCase);
        }
        private void PostProcess()
        {
            if (!_project.IsNewStyleClcache) return;
            var dep = SourceDependencies;

            //var test = this.ExcludedInputPaths.Select(x => x.ItemSpec.ToUpper()).ToHashSet();
            var test = new HashSet<string>();
            var commondir = ExcludedInputPaths.Select(x => x.ItemSpec.ToUpper());
            foreach (var item in this.Sources)
            {
                var artifact = _project.CompileArtifactMap[item.ItemSpec];
                var fullpath = item.GetMetadata("FullPath").ToUpper();
                System.Diagnostics.Debug.Assert(fullpath == artifact.FullPath);
                var obj_file = item.GetMetadata("ObjectFile");
                var objfile = Path.GetFullPath(obj_file).ToUpper();
                System.Diagnostics.Debug.Assert(!string.IsNullOrEmpty(objfile), $"ObjectFile of {item.ItemSpec} has no value");
                var headers = dep.DependencyTable[fullpath].Keys.Where(x => x != fullpath).ToHashSet();
                var outputs_all = SourceOutputs.OutputsForSource(item).Select(x => x.ItemSpec).Where(x => NotTLITLH(x)).ToHashSet();
                var output = SourceOutputs.OutputsForSource(item).FirstOrDefault(x => x.ItemSpec.StartsWith(objfile));
                System.Diagnostics.Debug.Assert(output != null, $"{item.ItemSpec} has no output");
                artifact.Output.Add(output.ItemSpec);
                headers.ExceptWith(outputs_all);  // remove inputs that are also outputs
                headers = processTLB(headers, artifact);
                headers = _project.FilterInput(headers, this, commondir);
                artifact.Dependency = headers;
            }
        }

        private HashSet<string> processTLB(HashSet<string> headers, BuildWorkFlow.CompileArtifact artifact)
        {
            Lazy<Dictionary<string, string>> basenames = new Lazy<Dictionary<string, string>>(delegate {
                Dictionary<string, string> _basenames = new Dictionary<string, string>();
                headers.Where(x => NotTLITLH(x) && Path.HasExtension(x) && !x.EndsWith(".H") && !x.EndsWith(".CPP")).ToList().ForEach(x => _basenames[Path.GetFileNameWithoutExtension(x)] = x);
                return _basenames;
                });
            HashSet<string> result = new HashSet<string>();
            foreach (var item in headers)
            {
                string source = null;
                if (NotTLITLH(item) || !basenames.Value.TryGetValue(Path.GetFileNameWithoutExtension(item), out source)) result.Add(item);
                else
                {
                   artifact.Output.Add($"{source}>{item}");
                   patchTLH(item);
                }
            }
            return result;
        }

        private void patchTLH(string file)
        {
            try
            {
                string[] lines = File.ReadAllLines(file);
                for (int i = 0; i < 6; i++)
                {
                    if (lines[i].StartsWith(@"//"))
                    {
                        lines[i] = string.Empty;
                    }
                }
                File.WriteAllLines(file, lines, Encoding.UTF8);
            }
            catch
            {
            }
        }
        protected override void RemoveTaskSpecificInputs(CanonicalTrackedInputFiles compactInputs)
        {
            base.RemoveTaskSpecificInputs(compactInputs);
        }
        protected override void RemoveTaskSpecificOutputs(CanonicalTrackedOutputFiles compactOutputs)
        {
            base.RemoveTaskSpecificOutputs(compactOutputs);
        }
        protected override int ExecuteTool(string pathToTool, string responseFileCommands, string commandLineCommands)
        {
            //if (_project.IsOldStyleClcache)
            //{
            //    pathToTool = _pythonLocation;
            //    commandLineCommands = " -m clcache " + commandLineCommands;
            //    LogToolCommand(pathToTool + commandLineCommands + " " + responseFileCommands);
            //}
#if DEBUG
            if (_project.IsNewStyleClcache)
            {
                foreach (var item in this.Sources)
                {
                    var filename = item.ItemSpec;
                    System.Diagnostics.Debug.Assert(_project.CompileArtifactMap.ContainsKey(filename));
                    System.Diagnostics.Debug.Assert(_project.CompileArtifactMap[filename].Cmd == this.GenerateCommandLineExceptSwitches(new string[] { this.SourcesPropertyName }, VCToolTask.CommandLineFormat.ForTracking));
                }
            }

#endif
            return base.ExecuteTool(pathToTool, responseFileCommands, commandLineCommands);
        }
        protected override System.Diagnostics.ProcessStartInfo GetProcessStartInfo(string pathToTool, string commandLineCommands, string responseFileSwitch)
        {
            var pinfo = base.GetProcessStartInfo(pathToTool, commandLineCommands, responseFileSwitch);
            if (_project.IsOldStyleClcache)
            {
                pinfo.FileName = _pythonLocation2.Value;
                pinfo.Arguments = $" \"{_clcacheLocation}\\aclcache.py\" " + pinfo.Arguments;
                LogToolCommand(_pythonLocation2.Value + pinfo.Arguments);
            }
            return pinfo;
        }
    }
    public class Link : Microsoft.Build.CPPTasks.Link
    {
        protected BuildWorkFlow.ProjectInfo _project { get; set; }

        public override bool Execute()
        {
            BuildWorkFlow.DebugHook(3);
            _project = this.BuildEngine.BeginLink();
            using var t = new Timer(t =>
            {
                _project.LinkTime += t;
            });
            _project.PostInvokeClcache();
            bool skip = false;
            if (_project.IsLinkerCache)
            {
                _project.LinkArtifact.IsDll = this.LinkDLL;
                skip = _project.PreInvokeLinkerCache(Sources, OutputFile, AdditionalDependencies, AdditionalLibraryDirectories, this);
            }
            bool r = true;
            if (!skip)
            {
                r = base.Execute();
                if (r)
                    _project.PatchAssembly(Sources, OutputFile, SourceDependencies, this);
            }
            _project.LinkSuccess &= r;
            if (!skip && r)
                PostProcess();
            this.BuildEngine.AfterLink(_project);
            return r;
        }

        protected override void RemoveTaskSpecificOutputs(CanonicalTrackedOutputFiles output)
        {
            if (_project.IsLinkerCache)
                _project.LinkArtifact._libGen = _project.FilterLinkTlogs(output.DependencyTable).FirstOrDefault(x => x.EndsWith(".EXP"));
            base.RemoveTaskSpecificOutputs(output);
        }
        private void PostProcess()
        {
            if (!_project.IsLinkerCache) return;
            _project.PostInvokeLinkerCache(SourceDependencies, SourceOutputs, this);
        }
    }
    public class LIB : Microsoft.Build.CPPTasks.LIB
    {
        protected BuildWorkFlow.ProjectInfo _project { get; set; }
        public override bool Execute()
        {
            BuildWorkFlow.DebugHook(4);
            _project = this.BuildEngine.BeginLib();
            using var t = new Timer(t =>
            {
                _project.LibTime += t;
            });
            _project.PostInvokeClcache();
            bool skip = false;
            if (_project.IsLinkerCache)
            {
                skip = _project.PreInvokeLinkerCache(Sources, OutputFile, AdditionalDependencies, AdditionalLibraryDirectories, this);
            }
            bool r = true;
            if (!skip)
              r = base.Execute();
            _project.LinkSuccess &= r;
            if (!skip && r)
                PostProcess();
            this.BuildEngine.AfterLib(_project);
            return r;
        }

        private void PostProcess()
        {
            if (!_project.IsLinkerCache) return;
            _project.PostInvokeLinkerCache(SourceDependencies, SourceOutputs, this);
        }
    }
}