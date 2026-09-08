import test from 'node:test';
import assert from 'node:assert/strict';
import { execSync } from 'node:child_process';
import { join } from 'node:path';

const cliPath = join(process.cwd(), 'bin', 'zerovault.js');

test('CLI Subsystem', async (t) => {
  await t.test('should output help on empty run', () => {
    try {
      const output = execSync(`node ${cliPath}`).toString();
      assert.match(output, /Usage: zerovault <command>/);
    } catch (err) {
      assert.fail('CLI failed to run');
    }
  });

  await t.test('should generate password', () => {
    const output = execSync(`node ${cliPath} generate password`).toString();
    assert.match(output, /Password:/);
    assert.match(output, /Entropy:/);
  });
});
