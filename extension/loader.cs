using System;
using Microsoft.Build.Framework;
using System.Collections.Generic;
using System.Text;
using System.IO;
using System.Reflection;

namespace Aclcache
{
    public class AclcacheLoaderTask : Microsoft.Build.Utilities.Task
    {
        public AclcacheLoaderTask() : base()
        {
        }
        private static int? g_Aedebug_l;
        private static int g_aedebug => (int)(g_Aedebug_l ?? (g_Aedebug_l = ((Environment.GetEnvironmentVariable("ACLCACHE_DEBUG") is string _tmp && Int32.TryParse(_tmp, out var t_Aedebug_l)) ? t_Aedebug_l : 0)));
        [System.Diagnostics.Conditional("DEBUG")]
        public static void DebugHook(int level = 1)
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
        public override bool Execute()
        {
            DebugHook(99);
            AppDomain.CurrentDomain.AssemblyResolve += CurrentDomain_AssemblyResolve;
           
            return true;
        }
        public static Assembly CurrentDomain_AssemblyResolve(object sender, ResolveEventArgs args)
        {
            if (string.IsNullOrEmpty(args?.Name)) return null;
            var fullname = new AssemblyName(args.Name);
            if (fullname.Name == "Microsoft.Build.CPPTasks.Common")
            {
                var assemlies = AppDomain.CurrentDomain.GetAssemblies();
                foreach (var asm in assemlies)
                {
                    if (fullname.Name == asm.GetName().Name)
                        return asm;
                }
            }
            return null;
        }
    }

}
