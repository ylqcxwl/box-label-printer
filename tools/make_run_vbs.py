# -*- coding: utf-8 -*-
"""生成 run.vbs（GBK 编码）：由 wscript 后台启动程序，无控制台窗口。"""

VBS = '''Set ws = CreateObject("WScript.Shell")
ws.CurrentDirectory = "E:\\文件夹\\WorkBuddy\\GitHub\\外箱标签打印程序"
ws.Environment("PROCESS")("QT_QPA_PLATFORM_PLUGIN_PATH") = "C:\\wbqt\\plugins\\platforms"
ws.Run """E:\\文件夹\\WorkBuddy\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\pythonw.exe"" app\\main.py", 1, False
'''

with open("run.vbs", "wb") as f:
    f.write(VBS.encode("gbk"))
print("run.vbs written (GBK)")
