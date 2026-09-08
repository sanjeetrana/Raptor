const path = require('path');
const { analyzeProject } = require('./src/project');

console.log('=== RepoLens Unified Analysis Pipeline Demo ===\n');

// Target directory to inspect (this repository)
const targetDirectory = path.join(__dirname);
console.log(`Analyzing project at: ${targetDirectory}\n`);

try {
  const report = analyzeProject(targetDirectory);

  console.log('--- Project Overview ---');
  console.log(`Path: ${report.project.path}`);
  console.log(`Files Scanned: ${report.project.fileCount}`);

  console.log('\n--- Statistics ---');
  console.log(`Total Lines: ${report.statistics.totalLines} (Blank: ${report.statistics.totalBlankLines})`);
  console.log(`Functions: ${report.statistics.totalFunctions}, Classes: ${report.statistics.totalClasses}`);
  console.log(`TODOs: ${report.statistics.totalTodos}, FIXMEs: ${report.statistics.totalFixmes}`);
  if (report.statistics.largestFile) {
    console.log(`Largest File: ${report.statistics.largestFile.path} (${report.statistics.largestFile.lines} lines)`);
  }

  console.log('\n--- Architecture ---');
  console.log(`Entry Points: ${report.architecture.entryPoints.join(', ') || 'none'}`);
  console.log(`Leaf Modules: ${report.architecture.leafModules.join(', ') || 'none'}`);
  console.log(`Circular Dependencies: ${report.architecture.circularDependencies.length === 0 ? 'None detected' : JSON.stringify(report.architecture.circularDependencies)}`);

  console.log('\n--- "Where Should I Start?" Recommendations ---');
  report.recommendations.forEach((rec, idx) => {
    console.log(`\n  #${idx + 1} ${rec.path} (Score: ${rec.score})`);
    rec.reasons.forEach((reason) => console.log(`     • ${reason}`));
  });

  console.log('\n--- Route Map ---');
  if (report.routes.length === 0) {
    console.log('No HTTP route endpoints detected.');
  } else {
    report.routes.forEach((route) => {
      console.log(`  [${route.method}] ${route.path} -> ${route.handler} (${route.file})`);
    });
  }

  console.log('\nFull JSON Report Object:');
  console.log(JSON.stringify(report, null, 2));

} catch (error) {
  console.error(`Analysis failed: ${error.message}`);
}

