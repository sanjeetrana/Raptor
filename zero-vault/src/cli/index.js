import { parseArgs } from 'node:util';
import { startServer } from '../server/server.js';
import * as security from '../security/index.js';

const args = process.argv.slice(2);

if (args.length === 0 || args[0] === 'help') {
  console.log(`
ZeroVault CLI
Usage: zerovault <command> [options]

Commands:
  serve [--port <number>]    Start local HTTP server (default port: 3000)
  generate <type> [options]  Generate password, passphrase, or key
  totp <secret>              Generate TOTP token
  scan <text>                Scan text for secrets
  audit <password>           Audit a password
  file <command> <path>      File protection (inspect, secure, hash, shred)
  `);
  process.exit(0);
}

const command = args[0];

if (command === 'serve') {
  const { values } = parseArgs({
    args,
    options: {
      port: {
        type: 'string',
        short: 'p',
        default: '3000'
      }
    },
    allowPositionals: true
  });
  const port = parseInt(values.port, 10);
  startServer(port);
} else if (command === 'generate') {
  const type = args[1] || 'password';
  if (type === 'password') {
    const { password, entropyBits } = security.generatePassword();
    console.log(`Password: ${password}`);
    console.log(`Entropy: ${entropyBits} bits`);
  } else if (type === 'passphrase') {
    const { passphrase, entropyBits } = security.generatePassphrase();
    console.log(`Passphrase: ${passphrase}`);
    console.log(`Entropy: ${entropyBits} bits`);
  } else if (type === 'key') {
    console.log(`Hex Key: ${security.generateHexKey()}`);
    console.log(`Base64 Key: ${security.generateBase64Key()}`);
  } else {
    console.error('Unknown generate type. Use password, passphrase, or key');
    process.exit(1);
  }
} else if (command === 'totp') {
  const secret = args[1];
  if (!secret) {
    console.error('Missing secret');
    process.exit(1);
  }
  const token = security.generateTOTP(secret);
  console.log(`Token: ${token}`);
} else if (command === 'scan') {
  const text = args.slice(1).join(' ');
  if (!text) {
    console.error('Missing text to scan');
    process.exit(1);
  }
  const findings = security.scanSecrets(text);
  if (findings.length === 0) {
    console.log('No secrets found.');
  } else {
    console.log(JSON.stringify(findings, null, 2));
    console.log(`\nRedacted text: ${security.redactText(text)}`);
  }
} else if (command === 'audit') {
  const password = args[1];
  if (!password) {
    console.error('Missing password');
    process.exit(1);
  }
  const audit = security.auditPassword(password);
  console.log(JSON.stringify(audit, null, 2));
} else if (command === 'file') {
  const fileCommand = args[1];
  const filePath = args[2];
  if (!fileCommand || !filePath) {
    console.error('Usage: zerovault file <inspect|secure|hash|shred> <path>');
    process.exit(1);
  }
  
  try {
    if (fileCommand === 'inspect') {
      const res = security.checkFilePermissions(filePath);
      console.log(JSON.stringify(res, null, 2));
    } else if (fileCommand === 'secure') {
      const newMode = security.secureFilePermissions(filePath);
      console.log(`Secured file permissions to ${newMode}`);
    } else if (fileCommand === 'hash') {
      const hash = security.hashFile(filePath);
      console.log(`SHA256 Hash: ${hash}`);
    } else if (fileCommand === 'shred') {
      security.shredFile(filePath);
      console.log(`Successfully shredded ${filePath}`);
    } else {
      console.error('Unknown file command');
      process.exit(1);
    }
  } catch (err) {
    console.error(`Error: ${err.message}`);
    process.exit(1);
  }
} else {
  console.error(`Unknown command: ${command}`);
  process.exit(1);
}
