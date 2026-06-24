Option Explicit

Dim fso
Dim shell
Dim root
Dim pythonw
Dim python
Dim app
Dim command

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
python = root & "\.venv\Scripts\python.exe"
app = root & "\app.py"

If fso.FileExists(pythonw) Then
  command = """" & pythonw & """ """ & app & """"
ElseIf fso.FileExists(python) Then
  command = """" & python & """ """ & app & """"
Else
  MsgBox "Python was not found under .venv\Scripts. Please create the virtual environment first.", 48, "Boss Local Capture Tool"
  WScript.Quit 1
End If

shell.CurrentDirectory = root
shell.Run command, 0, False
