import test from 'node:test';
import assert from 'node:assert/strict';
import { Router } from '../src/server/router.js';

test('Router Subsystem', async (t) => {
  await t.test('should register and match exact GET route', async () => {
    const router = new Router();
    let handled = false;
    
    router.get('/api/test', (req, res) => {
      handled = true;
      res.json({ ok: true });
    });

    const mockReq = { method: 'GET', url: '/api/test' };
    const mockRes = {
      writeHead: () => {},
      end: (data) => {
        assert.equal(JSON.parse(data).ok, true);
      }
    };

    const matched = await router.handle(mockReq, mockRes);
    assert.equal(handled, true);
  });

  await t.test('should extract URL parameters', async () => {
    const router = new Router();
    let extractedId;

    router.get('/api/users/:id', (req, res) => {
      extractedId = req.params.id;
      res.json({ id: extractedId });
    });

    const mockReq = { method: 'GET', url: '/api/users/123' };
    const mockRes = { writeHead: () => {}, end: () => {} };

    await router.handle(mockReq, mockRes);
    assert.equal(extractedId, '123');
  });
});
