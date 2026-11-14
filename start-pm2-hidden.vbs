Option Explicit
Dim shell, fso, root, command, result, logFile, stamp
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
command = "node.exe " & Chr(34) & fso.BuildPath(root, "pm2-local.cjs") & Chr(34) & " start"
On Error Resume Next
result = shell.Run(command, 0, True)
If Err.Number <> 0 Then result = -1
Err.Clear
If Not fso.FolderExists(fso.BuildPath(root, ".state")) Then fso.CreateFolder fso.BuildPath(root, ".state")
If Not fso.FolderExists(fso.BuildPath(root, ".state\pm2")) Then fso.CreateFolder fso.BuildPath(root, ".state\pm2")
Set logFile = fso.OpenTextFile(fso.BuildPath(root, ".state\pm2\startup.log"), 8, True)
If Err.Number = 0 Then
  stamp = Year(Now) & "-" & Right("0" & Month(Now), 2) & "-" & Right("0" & Day(Now), 2) & " " & Right("0" & Hour(Now), 2) & ":" & Right("0" & Minute(Now), 2) & ":" & Right("0" & Second(Now), 2)
  logFile.WriteLine stamp & " PM2 startup exit code: " & result
  logFile.Close
End If
On Error GoTo 0
