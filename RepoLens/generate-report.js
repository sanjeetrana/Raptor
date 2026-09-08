/**
 * RepoLens - CLI Report Generation Script
 * Run with: `npm run report`
 */

const path = require('path');
const { analyzeProject } = require('./src/project');
const { writeHtmlReport } = require('./src/report');

console.log('=== Generating RepoLens Report ===');

const projectRoot = path.resolve(__dirname);
const outputFile = path.join(projectRoot, 'repolens-report.html');

try {
  console.log(`Analyzing project at: ${projectRoot}`);
  const report = analyzeProject(projectRoot);

  writeHtmlReport(report, outputFile);
  console.log(`Report generated: repolens-report.html`);
} catch (error) {
  console.error(`Failed to generate report: ${error.message}`);
  process.exitCode = 1;
}
