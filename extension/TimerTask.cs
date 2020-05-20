using System;
using Microsoft.Build.Framework;
using System.Windows.Forms;
using System.Collections.Generic;
using System.Text;
using System.IO;

namespace AcadExtension
{
    public class TimerTask : Microsoft.Build.Utilities.Task
    {
        private static readonly System.Text.Encoding s_defaultEncoding = new System.Text.UTF8Encoding(false, true);
        public class Duration
        {
            public DateTime? Start;
            public DateTime? BeforeReferences;
            public DateTime? AfterReferences;
            public DateTime? BeforeCompile;
            public DateTime? BeforeLink;
            public DateTime? AfterLink;
        }

        public static Dictionary<string, Duration> _duration_dic = new Dictionary<string, Duration> ();
        //public static Duration _duration;
        public TimerTask() : base()
        {
        }
        public override bool Execute()
        {
            Duration _duration;
            if (!_duration_dic.TryGetValue(this.Project, out _duration))
            {
                _duration = new Duration();
                _duration_dic.Add(this.Project, _duration);
            }
            switch (Reason)
            {
                case "Start":
                    //MessageBox.Show("", "", MessageBoxButtons.YesNo);
                    BuildWorkFlow.Begin(this.BuildEngine);
                    if (!_duration.Start.HasValue)
                        _duration.Start = DateTime.Now;
                    break;
                case "BeforeResolveReferences":
                    if (!_duration.BeforeReferences.HasValue)
                        _duration.BeforeReferences = DateTime.Now;
                    break;
                case "AfterResolveReferences":
                    if (!_duration.AfterReferences.HasValue)
                        _duration.AfterReferences = DateTime.Now;
                    break;
                case "BeforeCompile":
                    if (!_duration.BeforeCompile.HasValue)
                        _duration.BeforeCompile = DateTime.Now;
                    break;
                case "BeforeLink":
                    if (!_duration.BeforeLink.HasValue)
                        _duration.BeforeLink = DateTime.Now;
                    break;
                case "AfterLink":
                    if (!_duration.AfterLink.HasValue)
                        _duration.AfterLink = DateTime.Now;
                    break;
            }
            if (_duration.AfterLink.HasValue && _duration.BeforeLink.HasValue && _duration.BeforeCompile.HasValue && _duration.Start.HasValue)
            {
                var other = ((_duration.BeforeCompile.Value.Ticks - _duration.AfterReferences.Value.Ticks) + (_duration.BeforeReferences.Value.Ticks - _duration.Start.Value.Ticks)) /10000000.0 ;
                var compile = (_duration.BeforeLink.Value.Ticks - _duration.BeforeCompile.Value.Ticks) / 10000000.0;
                var link = (_duration.AfterLink.Value.Ticks - _duration.BeforeLink.Value.Ticks)/10000000.0;
                string r = $"{this.Project},{compile},{link},{other}\n";
                Log.LogMessage(MessageImportance.High, r);
                
                if (this.File != null)
                {
                    if (Int32.TryParse(this.File, out var _)) return true;
                    int retry = 0;
                        while (true) {
                        try
                        {
                            System.IO.File.AppendAllText(this.File, r, s_defaultEncoding);
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
            return true;
        }
        public string Project
        {
            get;
            set;
        }
        public string Reason
        {
            get;
            set;
        }
        public string File
        {
            get;
            set;
        }
    }

    public class GetMetadataTask : Microsoft.Build.Utilities.Task
    {
        [Required]
        public ITaskItem[] MyItemGroup { get; set; }

        [Output]
        public string MetadataString { get; private set; }

        public override bool Execute()
        {
            StringBuilder command = new StringBuilder();
            foreach (ITaskItem item in MyItemGroup)
            {
                command.AppendFormat("ItemName={0}\r\n", item);
                foreach (string parameter in item.MetadataNames)
                {
                    command.AppendFormat("  {0}={1}\r\n", parameter, item.GetMetadata(parameter));
                }
                command.AppendFormat("\r\n");
            }
            MetadataString = command.ToString();
            return true;
        }
    }

    public class RegexFileUpdate : Microsoft.Build.Utilities.Task
    {
        [Required]
        [Output]
        public ITaskItem[] Files { get; set; }

        [Required]
        public string Regex { get; set; }

        [Required]
        public string ReplacementText { get; set; }

        [Required]
        public string OutDir { get; set; }

        public override bool Execute()
        {
            try
            {
                var rx = new System.Text.RegularExpressions.Regex(this.Regex);
                var result = new List<ITaskItem>();
                for (int i = 0; i < Files.Length; ++i)
                {
                    var path = Files[i].GetMetadata("FullPath");
                    if (!File.Exists(path)) continue;

                    var newpath = Path.Combine(OutDir, Path.GetFileNameWithoutExtension(path) + ".temp.cs");
                    var txt = File.ReadAllText(path);
                    var newtxt = rx.Replace(txt, this.ReplacementText);
                    if (newtxt != txt)
                    {
                        if (File.Exists(newpath) && File.GetLastWriteTime(newpath) > File.GetLastWriteTime(path))
                        { }
                        else
                        {
                            Log.LogMessage(MessageImportance.High, $"Replaced AssemblyVersion in ${newpath}");
                            File.WriteAllText(newpath, newtxt);
                        }
                        Files[i] = new Microsoft.Build.Utilities.TaskItem(Files[i]) { ItemSpec = newpath };
                        Files[i].SetMetadata("_Temp", "true");
                    }
                }
                return true;
            }
            catch (Exception ex)
            {
                Log.LogErrorFromException(ex);
                return true;
            }
        }
    }
}
