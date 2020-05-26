using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Linq.Expressions;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using Microsoft.Build.Execution;
using static AcadExtension.Utils;
using static AcadExtension.CacheStrategy;
using Microsoft.Build.Framework;
using Microsoft.Build.CPPTasks;
using Microsoft.Build.Utilities;

namespace AcadExtension
{
    public class CsvFileWriter : StreamWriter
    {

        public CsvFileWriter(string filename)
            : base(filename, false, Encoding.Unicode, 1024 * 64)
        {
        }
        public void WriteRow(IEnumerable<string> row)
        {
            StringBuilder builder = new StringBuilder();
            bool firstColumn = true;
            foreach (string value in row)
            {
                if (!firstColumn)
                    builder.Append('|');
                if (value == null)
                    builder.Append(string.Empty);
                else
                    builder.Append(value);
                firstColumn = false;
            }
            WriteLine(builder.ToString());
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
        static Utils()
        {
        }

        public static string _pythonLocation = Utils.GetPythonLocation();
        public static string _clcacheLocation = Utils.GetClCacheLocation();
        public static Encoding _currentOemEncoding = Encoding.GetEncoding(GetOEMCP());
        public static string GetClCacheLocation()
        {
            if (Environment.GetEnvironmentVariable("CLCACHE_LOCATION") is string loc && 
                System.IO.Directory.Exists(loc))
            {
                loc.TrimEnd('\\');
                return loc;
            }

            return AssemblyDirectory;
        }

        public static string GetPythonLocation()
        {
            if (Environment.GetEnvironmentVariable("CLCACHE_PYTHON") is string loc &&
                System.IO.File.Exists(loc))
            {
                return loc;
            }

            var path = Environment.GetEnvironmentVariable("PATH")
                    ?.Split(';')
                    .Where(s => File.Exists(Path.Combine(s, "python.exe")))
                    .FirstOrDefault();
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
        public static System.Diagnostics.ProcessStartInfo GetProcessStartInfo (string pathToTool, string commandLineCommands, bool redirect = false)
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
        UseZ7 = 16
    }
    [Flags] public enum BuildState : Int32
    {
        CompilerNotInvoked = 0,
        ClCachePreInvoked = 1,
        CompileFinished =2 ,
        ClCachePostInvoked =4,
    }
    public static class BuildWorkFlow
    {
        static char[] StringArraySplitter = new char[]{ ';' };
        public static int PopulateTaskFromSourceItem(this object task ,Type taskType, ITaskItem source, TrackedVCToolTaskInterfaceHelper schedulingTask)
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


        private static readonly System.Text.Encoding s_defaultEncoding = new System.Text.UTF8Encoding(false, true);

        public class CompileArtifact
        {
            private static char[] s_QuoteChar = new char[] {'"'};
            public CompileArtifact(string filename, string fullpath , string cmd, bool pch, string pchfile = null) {
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
        public class ProjectInfo
        {
            public string FullPath;
            public string[] Targets;
            public int ReqId;
            public ProjectItemInstance[] ClCompile;
            public List<CompileArtifact> CompileArtifacts;
            public string PathToCL;
            public Dictionary<string, CompileArtifact> CompileArtifactMap;
            public HashSet<string> ArtifactsHits = new HashSet<string>();
            public ProjectItemInstance[] Link;
            public ProjectItemInstance[] Lib;
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
            public bool CompileArtifactCollected { get; set; } = false;
            private IBuildEngine CurrentEngine;
            public CacheStrategy Strategy { get; set; } = CacheStrategy.None;
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
                    var cl = new Microsoft.Build.CPPTasks.CL();
                    var trackedVCToolTaskInterfaceHelper =
                        new TrackedVCToolTaskInterfaceHelper(cl, typeof(Microsoft.Build.CPPTasks.CL));
                    this.PopulateTaskFromSourceItem(typeof(Microsoft.Build.CPPTasks.CL), taskitem, trackedVCToolTaskInterfaceHelper);
                    var cmd = trackedVCToolTaskInterfaceHelper.GenerateCommandLineExceptSwitches(new string[] { "Sources" }, VCToolTask.CommandLineFormat.ForTracking);
                    var artifact = new CompileArtifact(taskitem.ItemSpec, taskitem.GetMetadata("FullPath").ToUpper(), cmd, cl.PrecompiledHeader == "Create");
                    if (!string.IsNullOrEmpty(cl.PrecompiledHeaderFile))
                    {
                        artifact.PchHeader = cl.PrecompiledHeaderFile;
                    }
                    CompileArtifacts.Add(artifact);
                    CompileArtifactMap.Add(artifact.ItemSpec, artifact);
                }
            }
            public int InvokeClCache(string switches, out string result , bool wait = true)
            {
                var proc = new System.Diagnostics.Process();

                var cmdline = $" {_clcacheLocation}\\clcache.py {switches}";
                proc.StartInfo = Utils.GetProcessStartInfo(_pythonLocation, cmdline, false);

                int ExitCode = -1;
                result = string.Empty;

                LogMessage($"{_pythonLocation}{cmdline}");
                if (wait)
                {
                    string s = string.Empty;
                    proc.StartInfo.RedirectStandardOutput = true;
                    proc.StartInfo.RedirectStandardError = true;
                    proc.OutputDataReceived += (object sender, System.Diagnostics.DataReceivedEventArgs e) => {
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
                var tmpfile = Utils.GetTemporaryFile(".1.txt");
                using (var writer = new CsvFileWriter(tmpfile))
                {
                    foreach (var item in CompileArtifacts)
                    {
                        writer.WriteRow(item.ItemSpec ,item.FullPath, item.GenPch ? "2" : item.UsePch ? "1" : "0", item.PchHeader, item.Cmd);
                        writer.WriteLine("^^");
                    }
                }
                if (System.IO.File.Exists(tmpfile))
                {
                    var exitcode = InvokeClCache($"-p {tmpfile} -b {PathToCL}", out var ret);
                    if (exitcode == 0)
                    {
                        var lines = ret.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None);
                        System.Diagnostics.Debug.Assert(lines.Length > 0, "Clcache does not return anything");
                        ret = lines[lines.Length - 1];
                        var hits = ret.Split(new[] {"*"}, StringSplitOptions.RemoveEmptyEntries);
                        foreach (var item in hits)
                        {
                            ArtifactsHits.Add(item);
                        }
                    }
                }
            }

            public virtual void PostInvokeClcache()
            {
                if ( !State.HasFlag(BuildState.ClCachePreInvoked) || !State.HasFlag(BuildState.CompileFinished) || State.HasFlag(BuildState.ClCachePostInvoked)) 
                    return;

                State |= BuildState.ClCachePostInvoked;

                var tmpfile = Utils.GetTemporaryFile(".2.txt");
                bool something = false;
                using (var writer = new CsvFileWriter(tmpfile))
                {
                    foreach (var item in CompileArtifacts)
                    {
                        if (item.Output.Count > 0)
                        {
                            something = true;
                            writer.WriteRow(item.ItemSpec, item.FullPath, item.GenPch ? "2" : item.UsePch ? "1" : "0", item.PchHeader, item.Cmd, string.Join("*", item.Dependency), string.Join("*", item.Output));
                            writer.WriteLine("^^");
                        }
                    }
                }
                if (something)
                {
                    InvokeClCache($"-q {tmpfile} -b {PathToCL}", out var ret, false);
                }
                else
                {
                    System.IO.File.Delete(tmpfile);
                }
            }
            public bool IsOldStyleClcache => Strategy.HasFlag(UseCCache) && Strategy.HasFlag(UseNoPch) && (Strategy.HasFlag(UseNoPdb) || Strategy.HasFlag(UseZ7));
            public bool IsNewStyleClcache => Strategy.HasFlag(UseCCache) && !Strategy.HasFlag(UseNoPch) && !Strategy.HasFlag(CacheStrategy.UseNoPdb);

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
        }
        private static Dictionary<string, ProjectInfo> _projects = new Dictionary<string, ProjectInfo>();

        static BuildWorkFlow()
        {
            DebugHook();
        }
        public static void DebugHook()
        {
            if (null != Environment.GetEnvironmentVariable("_aedebug"))
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

        public static void addEvent(this object obj, string prop ,Delegate dele)
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
               engine.getProp("_requestEntry").addEvent("OnStateChanged", (Action<object,object>)( (entry, b) => {
                   if (3 == (int)Convert.ChangeType(b, typeof(int)))
                   {
                       if (_projects.TryGetValue(hash, out var _))
                       {
                           project.PostInvokeClcache();
                           LogTiming(entry, project);
                           _projects.Remove(hash);
                       }
                   }
               }));
               _projects.Add(hash, project);
           }
           project.SetCurrentEngine(engine);
           return project;
        }
        public static ProjectInfo BeginCompile(this Microsoft.Build.Framework.IBuildEngine engine)
        {
            var project = Begin(engine);
            if (project.BeforeCompile == null)
            {
                project.BeforeCompile = DateTime.Now;
                if (!string.IsNullOrEmpty(ProjectProperty(engine, "_USECCACHE")))
                {
                    project.Strategy |= CacheStrategy.UseCCache;
                    if (!string.IsNullOrEmpty(ProjectProperty(engine, "_USENOPCH")))
                        project.Strategy |= CacheStrategy.UseNoPch;
                    if (!string.IsNullOrEmpty(ProjectProperty(engine, "_USENOPDB")))
                        project.Strategy |= CacheStrategy.UseNoPdb;
                    if (!string.IsNullOrEmpty(ProjectProperty(engine, "_USEZ7")))
                        project.Strategy |= CacheStrategy.UseZ7;
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
                project.Link = engine.getProp("_requestEntry").getProp("RequestConfiguration").getProp("BaseLookup").invoke<IEnumerable<ProjectItemInstance>>("GetItems", "Link").ToArray();
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

        // ILoggingService.LogBuildEvent ((Microsoft.Build.BackEnd.RequestBuilder)((Microsoft.Build.BackEnd.BuildRequestEntry)entry).Builder)._projectLoggingContext.LoggingService
        private static void LogTiming(this object engine, ProjectInfo project)
        {

            DateTime? starttime = project.Start ?? project.BeforeCompile ?? project.BeforeLib ?? project.BeforeLink;
            var compile = project.CompileTime.Ticks / 10000000.0 ;
            var link = project.LinkTime.Ticks / 10000000.0 ;
            var lib = project.LibTime.Ticks / 10000000.0 ;
            var other = starttime.HasValue ? (DateTime.Now.Ticks - starttime.Value.Ticks ) / 10000000.0 - compile - link - lib : 0.0;
            string r = (project.State.HasFlag(BuildState.ClCachePreInvoked))?
            $"{project.Desc},{compile},{link},{lib},{other},{project.ArtifactsHits.Count},{project.CompileArtifacts.Count - project.ArtifactsHits.Count}\n"
                :
            $"{project.Desc},{compile},{link},{lib},{other},0,0 \n";
            System.Console.WriteLine(r);
            var file = ProjectProperty(engine, "_statlog");
            if (Int32.TryParse(file, out var _)) return;

            if (file != null)
            {
                int retry = 0;
                while (true)
                {
                    try
                    {
                        System.IO.File.AppendAllText(file, r, s_defaultEncoding);
                        break;
                    }
                    catch (Exception)
                    {
                        retry++;
                        if (retry < 5)
                        {
                            System.Threading.Thread.Sleep(100);
                            continue;
                        }
                        else
                        {
                            throw;
                        }
                    }
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
            using var t = new Timer(t => {
                _project.CompileTime += t ;
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
                r = base.Execute();
            if (r)
            {
                PostProcess();
                _project.State |= BuildState.CompileFinished;
            }
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

        private void PostProcess()
        {
            if (!_project.IsNewStyleClcache) return;
            var dep = SourceDependencies;

            //var test = this.ExcludedInputPaths.Select(x => x.ItemSpec.ToUpper()).ToHashSet();
            var test = new HashSet<string>();
            foreach (var item in this.Sources)
            {
                var artifact = _project.CompileArtifactMap[item.ItemSpec];
                var fullpath = item.GetMetadata("FullPath").ToUpper();
#if DEBUG
                System.Diagnostics.Debug.Assert(fullpath == artifact.FullPath);
#endif
                var objfile = Path.GetFullPath(item.GetMetadata("ObjectFile")).ToUpper();
                System.Diagnostics.Debug.Assert(!string.IsNullOrEmpty(objfile), $"ObjectFile of {item.ItemSpec} has no value");
                var headers = dep.DependencyTable[fullpath].Keys.Where(x => !test.Contains(Path.GetDirectoryName(x)) && x != fullpath).ToHashSet();
                var outputs_all = SourceOutputs.OutputsForSource(item).Select(x => x.ItemSpec).ToHashSet();
                var output = SourceOutputs.OutputsForSource(item).FirstOrDefault(x => x.ItemSpec.StartsWith(objfile));
                System.Diagnostics.Debug.Assert(output !=null,  $"{item.ItemSpec} has no output");
                artifact.Output.Add(output.ItemSpec);
                headers.ExceptWith(outputs_all);  // remove inputs that are also outputs
                artifact.Dependency = headers;
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
        protected override int ExecuteTool ( string pathToTool, string responseFileCommands, string commandLineCommands)
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
        protected override System.Diagnostics.ProcessStartInfo GetProcessStartInfo(string pathToTool,string commandLineCommands, string responseFileSwitch )
        {
            var pinfo = base.GetProcessStartInfo(pathToTool, commandLineCommands, responseFileSwitch);
            if (_project.IsOldStyleClcache)
            {
                pinfo.FileName = _pythonLocation;
                pinfo.Arguments = $" {_clcacheLocation}\\clcache.py " + pinfo.Arguments;
                LogToolCommand(_pythonLocation + pinfo.Arguments);
            }
            return pinfo;
        }
    }
    public class Link : Microsoft.Build.CPPTasks.Link
    {
        public override bool Execute()  
        {
            var proj = this.BuildEngine.BeginLink();
            using var t = new Timer(t => {
                proj.LinkTime += t;
            });
            proj.PostInvokeClcache();
            var r = base.Execute();
            this.BuildEngine.AfterLink(proj);
            return r;
        }
    }
    public class LIB : Microsoft.Build.CPPTasks.LIB
    {
        public override bool Execute()
        {
            var proj = this.BuildEngine.BeginLib();
            using var t = new Timer(t => {
                proj.LibTime += t;
            });
            proj.PostInvokeClcache();
            var r = base.Execute();
            this.BuildEngine.AfterLib(proj);
            return r;
        }
    }
}
