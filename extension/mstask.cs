using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace AcadExtension
{
    public class CL : Microsoft.Build.CPPTasks.CL
    {
        public override bool Execute()
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

                    else { }
                }
            }

            return base.Execute();
        }
    }
    public class Link : Microsoft.Build.CPPTasks.Link
    {
        public override bool Execute()
        {
            return base.Execute();
        }
    }
    public class LIB : Microsoft.Build.CPPTasks.LIB
    {
        public override bool Execute()
        {
            return base.Execute();
        }
    }
}
