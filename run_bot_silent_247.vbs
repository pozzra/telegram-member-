' Telegram Adder Pro - Silent 24/7 Background Bot Runner
' Runs python bot.py completely hidden in the background with zero terminal windows.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Run python bot.py in hidden window mode (0 = hide, False = don't wait)
WshShell.CurrentDirectory = strDir
WshShell.Run "python bot.py", 0, False

