; Script generated by the Inno Setup Script Wizard.
; SEE THE DOCUMENTATION FOR DETAILS ON CREATING INNO SETUP SCRIPT FILES!

#ifndef VERSION
#define FileHandle
#define FileLine
#define VERSION = "unknown"
#if FileHandle = FileOpen(SourcePath + "\..\..\..\mercurial\__version__.py")
  #expr FileLine = FileRead(FileHandle)
  #expr FileLine = FileRead(FileHandle)
  #define VERSION = Copy(FileLine, Pos('"', FileLine)+1, Len(FileLine)-Pos('"', FileLine)-1)
#endif
#if FileHandle
  #expr FileClose(FileHandle)
#endif
#pragma message "Detected Version: " + VERSION
#endif

#ifndef ARCH
#define ARCH = "x86"
#endif

[Setup]
AppCopyright=Copyright 2005-2019 Matt Mackall and others
AppName=Mercurial
AppVersion={#VERSION}
#if ARCH == "x64"
AppVerName=Mercurial {#VERSION} (64-bit)
OutputBaseFilename=Mercurial-{#VERSION}-x64
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
#else
AppVerName=Mercurial {#VERSION}
OutputBaseFilename=Mercurial-{#VERSION}
#endif
InfoAfterFile=contrib/win32/postinstall.txt
LicenseFile=COPYING
ShowLanguageDialog=yes
AppPublisher=Matt Mackall and others
AppPublisherURL=https://mercurial-scm.org/
AppSupportURL=https://mercurial-scm.org/
AppUpdatesURL=https://mercurial-scm.org/
AppID={{4B95A5F1-EF59-4B08-BED8-C891C46121B3}
AppContact=mercurial@mercurial-scm.org
DefaultDirName={pf}\Mercurial
SourceDir=..\..\..
VersionInfoDescription=Mercurial distributed SCM (version {#VERSION})
VersionInfoCopyright=Copyright 2005-2019 Matt Mackall and others
VersionInfoCompany=Matt Mackall and others
InternalCompressLevel=max
SolidCompression=true
SetupIconFile=contrib\win32\mercurial.ico
AllowNoIcons=true
DefaultGroupName=Mercurial
PrivilegesRequired=none
ChangesEnvironment=true

[Files]
Source: contrib\mercurial.el; DestDir: {app}/Contrib
Source: contrib\vim\*.*; DestDir: {app}/Contrib/Vim
Source: contrib\zsh_completion; DestDir: {app}/Contrib
Source: contrib\bash_completion; DestDir: {app}/Contrib
Source: contrib\tcsh_completion; DestDir: {app}/Contrib
Source: contrib\tcsh_completion_build.sh; DestDir: {app}/Contrib
Source: contrib\hgk; DestDir: {app}/Contrib; DestName: hgk.tcl
Source: contrib\xml.rnc; DestDir: {app}/Contrib
Source: contrib\mercurial.el; DestDir: {app}/Contrib
Source: contrib\mq.el; DestDir: {app}/Contrib
Source: contrib\hgweb.fcgi; DestDir: {app}/Contrib
Source: contrib\hgweb.wsgi; DestDir: {app}/Contrib
Source: contrib\win32\ReadMe.html; DestDir: {app}; Flags: isreadme
Source: contrib\win32\postinstall.txt; DestDir: {app}; DestName: ReleaseNotes.txt
Source: dist\hg.exe; DestDir: {app}; AfterInstall: Touch('{app}\hg.exe.local')
#if ARCH == "x64"
Source: dist\lib\*.dll; Destdir: {app}\lib
Source: dist\lib\*.pyd; Destdir: {app}\lib
#else
Source: dist\w9xpopen.exe; DestDir: {app}
#endif
Source: dist\python*.dll; Destdir: {app}; Flags: skipifsourcedoesntexist
Source: dist\msvc*.dll; DestDir: {app}; Flags: skipifsourcedoesntexist
Source: dist\Microsoft.VC*.CRT.manifest; DestDir: {app}; Flags: skipifsourcedoesntexist
Source: dist\lib\library.zip; DestDir: {app}\lib
Source: doc\*.html; DestDir: {app}\Docs
Source: doc\style.css; DestDir: {app}\Docs
Source: mercurial\help\*.txt; DestDir: {app}\help
Source: mercurial\help\internals\*.txt; DestDir: {app}\help\internals
Source: mercurial\default.d\*.rc; DestDir: {app}\default.d
Source: mercurial\locale\*.*; DestDir: {app}\locale; Flags: recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: mercurial\templates\*.*; DestDir: {app}\Templates; Flags: recursesubdirs createallsubdirs
Source: CONTRIBUTORS; DestDir: {app}; DestName: Contributors.txt
Source: COPYING; DestDir: {app}; DestName: Copying.txt

[INI]
Filename: {app}\Mercurial.url; Section: InternetShortcut; Key: URL; String: https://mercurial-scm.org/
Filename: {app}\default.d\editor.rc; Section: ui; Key: editor; String: notepad

[UninstallDelete]
Type: files; Name: {app}\Mercurial.url
Type: filesandordirs; Name: {app}\default.d
Type: files; Name: "{app}\hg.exe.local"

[Icons]
Name: {group}\Uninstall Mercurial; Filename: {uninstallexe}
Name: {group}\Mercurial Command Reference; Filename: {app}\Docs\hg.1.html
Name: {group}\Mercurial Configuration Files; Filename: {app}\Docs\hgrc.5.html
Name: {group}\Mercurial Ignore Files; Filename: {app}\Docs\hgignore.5.html
Name: {group}\Mercurial Web Site; Filename: {app}\Mercurial.url

[Tasks]
Name: modifypath; Description: Add the installation path to the search path; Flags: unchecked

[Code]
procedure Touch(fn: String);
begin
  SaveStringToFile(ExpandConstant(fn), '', False);
end;

const
    ModPathName = 'modifypath';
    ModPathType = 'user';

function ModPathDir(): TArrayOfString;
begin
    setArrayLength(Result, 1)
    Result[0] := ExpandConstant('{app}');
end;
#include "modpath.iss"
