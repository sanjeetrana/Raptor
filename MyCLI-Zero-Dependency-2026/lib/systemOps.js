'use strict';
// Zero-dependency replacement for the `system:*` / `apps:*` / `installer:*`
// ipcMain handlers. Windows system data is obtained the same way the
// original app got it: by composing built-in PowerShell/CIM cmdlets via
// node:child_process and parsing the JSON they emit. That is calling the
// operating system's own tools, not a third-party library.

const path = require('node:path');
const { spawn } = require('node:child_process');
const store = require('./store');
const { isWindows } = require('./fsOps');
const { runChild } = require('./terminalOps');

function psJson(script) {
  if (!isWindows) return Promise.reject(new Error('This operation is available on Windows only.'));
  return new Promise((resolve, reject) => {
    const child = spawn('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', `$ErrorActionPreference='Stop'; ${script} | ConvertTo-Json -Depth 5 -Compress`], { windowsHide: true });
    let out = '';
    let err = '';
    child.stdout.on('data', (d) => { out += d; });
    child.stderr.on('data', (d) => { err += d; });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code !== 0) return reject(new Error(err.trim() || `PowerShell exited with code ${code}.`));
      try { resolve(out.trim() ? JSON.parse(out) : null); } catch { reject(new Error('Windows returned invalid data.')); }
    });
  });
}

const info = () => psJson('Get-ComputerInfo | Select-Object WindowsProductName,WindowsVersion,OsBuildNumber,OsArchitecture,CsName,CsUserName,CsProcessors,CsTotalPhysicalMemory,BiosManufacturer,BiosVersion');
const processesList = () => psJson('Get-Process | Select-Object ProcessName,Id,CPU,WorkingSet,Path,StartTime | Sort-Object ProcessName');
const services = () => psJson('Get-Service | Select-Object Name,DisplayName,Status,StartType | Sort-Object DisplayName');
const startup = () => psJson('Get-CimInstance Win32_StartupCommand | Select-Object Name,Command,Location,User');
const storage = () => psJson('Get-Volume | Where-Object DriveLetter | Select-Object DriveLetter,FileSystemLabel,FileSystem,Size,SizeRemaining,HealthStatus');
const network = () => psJson('Get-NetIPConfiguration | Select-Object InterfaceAlias,IPv4Address,IPv6Address,DNSServer,NetProfile');
const health = () => psJson("$os=Get-CimInstance Win32_OperatingSystem; $cpu=(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average; [pscustomobject]@{Cpu=[math]::Round($cpu,1); MemoryTotal=$os.TotalVisibleMemorySize*1KB; MemoryFree=$os.FreePhysicalMemory*1KB; Uptime=((Get-Date)-$os.LastBootUpTime).TotalSeconds; Computer=$env:COMPUTERNAME}");
const installedApps = () => psJson("$paths=@('HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*','HKLM:\\Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*','HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*'); Get-ItemProperty $paths -ErrorAction SilentlyContinue | Where-Object DisplayName | Select-Object DisplayName,DisplayVersion,Publisher,InstallDate,InstallLocation,UninstallString | Sort-Object DisplayName");

async function killProcess(pid) {
  if (!Number.isInteger(Number(pid))) throw new Error('Invalid process ID.');
  const result = await psJson(`Stop-Process -Id ${Number(pid)} -Force -PassThru | Select-Object Id,ProcessName`);
  store.addActivity('Process terminated', String(pid), 'Success');
  return result;
}

async function serviceAction(name, action) {
  const { assertName } = require('./fsOps');
  assertName(name);
  if (!['Start-Service', 'Stop-Service', 'Restart-Service'].includes(action)) throw new Error('Unsupported service action.');
  const result = await psJson(`${action} -Name '${name.replaceAll("'", "''")}' -PassThru | Select-Object Name,Status`);
  store.addActivity('Service changed', `${action} ${name}`, 'Success');
  return result;
}

// Launching the same first-party Windows utilities the original app
// launched. On non-Windows platforms these tools do not exist, so the
// call fails with a clear error instead of a silent no-op.
const TOOL_MAP = {
  taskmgr: 'taskmgr.exe', devmgmt: 'devmgmt.msc', diskmgmt: 'diskmgmt.msc', eventvwr: 'eventvwr.msc',
  services: 'services.msc', regedit: 'regedit.exe', control: 'control.exe', settings: 'ms-settings:',
  cmd: 'cmd.exe', powershell: 'powershell.exe', compmgmt: 'compmgmt.msc', msinfo: 'msinfo32.exe',
};

async function launchTool(tool) {
  const target = TOOL_MAP[tool];
  if (!target) throw new Error('Unknown Windows tool.');
  if (!isWindows) throw new Error('Windows tools are only available on Windows.');
  await new Promise((resolve, reject) => {
    const child = target.endsWith(':')
      ? spawn('cmd.exe', ['/d', '/s', '/c', 'start', '""', target], { windowsHide: true })
      : spawn('cmd.exe', ['/d', '/s', '/c', 'start', '""', target], { windowsHide: true });
    child.on('error', reject);
    child.on('spawn', resolve);
  });
  store.addActivity('System tool launched', target, 'Success');
  return true;
}

async function runDiagnosticScript(script, label = 'Diagnostic') {
  if (typeof script !== 'string' || script.length > 2000) throw new Error('Invalid diagnostic script.');
  const result = await psJson(script);
  store.addActivity(label, label, 'Success');
  return result;
}

function winget(args, broadcast) {
  const safe = Array.isArray(args) ? args.map((x) => String(x).replace(/[&|<>`$;\n\r]/g, '')).filter(Boolean) : [];
  return new Promise((resolve) => {
    const id = runChild({
      command: `winget ${safe.join(' ')}`,
      cwd: process.cwd(),
      kind: 'cmd',
      onData: (d) => broadcast('operation:data', d),
      onExit: (r) => resolve({ id, ...r }),
    });
  });
}

function runInstaller(installer, args = [], broadcast) {
  const { safePath } = require('./fsOps');
  const target = safePath(installer);
  const ext = path.extname(target).toLowerCase();
  if (!['.exe', '.msi'].includes(ext)) throw new Error('Only .exe and .msi installers are supported.');
  const safeArgs = Array.isArray(args) ? args.map((x) => String(x).replace(/[\0\r\n]/g, '')) : [];
  const command = ext === '.msi' ? `msiexec.exe /i "${target}" ${safeArgs.join(' ')}` : `"${target}" ${safeArgs.join(' ')}`;
  return new Promise((resolve) => {
    const id = runChild({
      command,
      cwd: path.dirname(target),
      kind: 'cmd',
      onData: (d) => broadcast('operation:data', d),
      onExit: (r) => {
        store.addActivity('Application installed', target, r.code === 0 ? 'Success' : 'Failed', `Exit code ${r.code}`);
        resolve({ id, ...r });
      },
    });
  });
}

module.exports = {
  info, processesList, services, startup, storage, network, health, installedApps,
  killProcess, serviceAction, launchTool, runDiagnosticScript, winget, runInstaller,
};
