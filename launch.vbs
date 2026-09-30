Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
Set app = CreateObject("Shell.Application")

folder = fso.GetParentFolderName(WScript.ScriptFullName)
py = sh.ExpandEnvironmentStrings("%LocalAppData%\Programs\Python\Python312\pythonw.exe")
If Not fso.FileExists(py) Then py = "pythonw.exe"
scriptName = "gui.py"
If WScript.Arguments.Count > 0 Then scriptName = WScript.Arguments(0)
scriptPath = folder & "\" & scriptName

verb = "open"
If Not IsAdmin() Then verb = "runas"
app.ShellExecute py, """" & scriptPath & """", folder, verb, 1

Function IsAdmin()
  On Error Resume Next
  CreateObject("WScript.Shell").RegRead "HKEY_USERS\S-1-5-19\"
  IsAdmin = (Err.Number = 0)
  Err.Clear
End Function
