/**
 * Zero-Dependency Test Suite for RepoLens Route Map Engine
 * Run with: `node test/test-routes.js`
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const {
  extractRoutes,
  analyzeRouteFile,
  analyzeProjectRoutes,
  parseHandler
} = require('../src/routes');

console.log('=== Running Static Route Map Tests ===');

// Test 1: extractRoutes on comprehensive in-memory source
const sampleRoutesCode = `
const express = require('express');
const app = express();
const router = express.Router();
const userRouter = express.Router();
const api = express.Router();

// 1. Standard GET route on app with direct function
app.get('/users', getUsers);

// 2. POST route with controller member expression
router.post('/users', userController.createUser);

// 3. PUT route with route parameters
userRouter.put('/users/:id', userController.updateUser);

// 4. PATCH route with multiple parameters
api.patch('/users/:userId/posts/:postId', updatePost);

// 5. DELETE route with middleware before final handler
app.delete('/users/:id', authMiddleware, checkRole, deleteUser);

// 6. Anonymous arrow function handler
router.get('/health', (req, res) => {
  res.send('ok');
});

// 7. Anonymous regular function handler
app.get('/status', function(req, res) {
  res.json({ status: 'ok' });
});

// 8. Commented-out routes MUST be ignored:
// app.get('/commented', fakeHandler);
/* router.post('/hidden', hiddenHandler); */

// 9. Dynamic route path MUST be ignored:
const dynamicPath = '/dynamic';
app.get(dynamicPath, dynamicHandler);

// 10. Duplicate route within the same file MUST be deduplicated:
app.get('/users', getUsers);
`;

const routes = extractRoutes(sampleRoutesCode, 'src/routes/userRoutes.js');
console.log('\n[Test 1] Extracted Routes Output:\n', JSON.stringify(routes, null, 2));

// Test 1.1: Verify total count (7 unique valid routes)
assert.strictEqual(routes.length, 7, 'Should detect exactly 7 valid routes');
console.log('✓ Test 1.1 Passed: Correct count of active routes extracted.');

// Test 1.2: Verify GET route on app
assert.deepStrictEqual(routes[0], {
  method: 'GET',
  path: '/users',
  handler: 'getUsers',
  file: 'src/routes/userRoutes.js'
});
console.log('✓ Test 1.2 Passed: Standard GET route detected.');

// Test 1.3: Verify POST route with controller-style member expression
assert.deepStrictEqual(routes[1], {
  method: 'POST',
  path: '/users',
  handler: 'userController.createUser',
  file: 'src/routes/userRoutes.js'
});
console.log('✓ Test 1.3 Passed: POST route with controller expression detected.');

// Test 1.4: Verify PUT route with route parameter
assert.deepStrictEqual(routes[2], {
  method: 'PUT',
  path: '/users/:id',
  handler: 'userController.updateUser',
  file: 'src/routes/userRoutes.js'
});
console.log('✓ Test 1.4 Passed: PUT route with :id parameter detected.');

// Test 1.5: Verify PATCH route with multi-params and custom router variable
assert.deepStrictEqual(routes[3], {
  method: 'PATCH',
  path: '/users/:userId/posts/:postId',
  handler: 'updatePost',
  file: 'src/routes/userRoutes.js'
});
console.log('✓ Test 1.5 Passed: PATCH route with multiple params detected.');

// Test 1.6: Verify DELETE route with middleware before final handler
assert.deepStrictEqual(routes[4], {
  method: 'DELETE',
  path: '/users/:id',
  handler: 'deleteUser',
  file: 'src/routes/userRoutes.js'
});
console.log('✓ Test 1.6 Passed: DELETE route with middleware sequence extracted terminal handler.');

// Test 1.7: Verify anonymous arrow function handler
assert.deepStrictEqual(routes[5], {
  method: 'GET',
  path: '/health',
  handler: 'anonymous',
  file: 'src/routes/userRoutes.js'
});
console.log('✓ Test 1.7 Passed: Anonymous arrow function handler detected.');

// Test 1.8: Verify anonymous function handler
assert.deepStrictEqual(routes[6], {
  method: 'GET',
  path: '/status',
  handler: 'anonymous',
  file: 'src/routes/userRoutes.js'
});
console.log('✓ Test 1.8 Passed: Anonymous regular function handler detected.');

// Test 2: parseHandler unit tests
assert.strictEqual(parseHandler('authMiddleware, userController.getUsers'), 'userController.getUsers');
assert.strictEqual(parseHandler('(req, res) => res.send()'), 'anonymous');
assert.strictEqual(parseHandler('async (req, res) => {}'), 'anonymous');
assert.strictEqual(parseHandler('function(req, res) {}'), 'anonymous');
assert.strictEqual(parseHandler(''), 'anonymous');
console.log('✓ Test 2 Passed: parseHandler utility behaves accurately.');

// Test 3: Integration test on physical disk files
const fixtureDir = path.join(__dirname, '__temp_routes_fixture__');

function setupFixture() {
  if (fs.existsSync(fixtureDir)) {
    fs.rmSync(fixtureDir, { recursive: true, force: true });
  }

  fs.mkdirSync(path.join(fixtureDir, 'src', 'routes'), { recursive: true });

  fs.writeFileSync(
    path.join(fixtureDir, 'src', 'routes', 'authRoutes.js'),
    `const router = require('express').Router();\nrouter.post('/login', authController.login);\nrouter.post('/logout', authController.logout);\n`
  );

  fs.writeFileSync(
    path.join(fixtureDir, 'src', 'routes', 'productRoutes.js'),
    `const app = require('express')();\napp.get('/products', getProducts);\napp.get('/products/:id', getProductById);\n`
  );
}

function cleanupFixture() {
  if (fs.existsSync(fixtureDir)) {
    fs.rmSync(fixtureDir, { recursive: true, force: true });
  }
}

try {
  setupFixture();

  const file1 = path.join(fixtureDir, 'src', 'routes', 'authRoutes.js');
  const file2 = path.join(fixtureDir, 'src', 'routes', 'productRoutes.js');

  const fileRoutes = analyzeRouteFile(file1, { projectRoot: fixtureDir });
  assert.strictEqual(fileRoutes.length, 2);
  assert.strictEqual(fileRoutes[0].path, '/login');
  assert.strictEqual(fileRoutes[0].file, 'src/routes/authRoutes.js');
  console.log('✓ Test 3.1 Passed: analyzeRouteFile works on single disk file.');

  const projectRoutes = analyzeProjectRoutes([file1, file2], { projectRoot: fixtureDir });
  console.log('\n[Test 3.2] Project-Wide Routes Aggregation:\n', JSON.stringify(projectRoutes, null, 2));

  assert.strictEqual(projectRoutes.length, 4);
  assert.strictEqual(projectRoutes[0].method, 'POST');
  assert.strictEqual(projectRoutes[2].method, 'GET');
  console.log('✓ Test 3.2 Passed: analyzeProjectRoutes aggregates across multiple files.');

  console.log('\nAll static route map tests passed successfully!');
} catch (err) {
  console.error('\n❌ Test failed:', err);
  process.exitCode = 1;
} finally {
  cleanupFixture();
}
