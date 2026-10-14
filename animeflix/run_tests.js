const { execSync } = require('child_process');
const fs = require('fs');

try {
  const out = execSync('node tests/api.test.js', { cwd: __dirname, encoding: 'utf8' });
  fs.writeFileSync('test_output.txt', 'SUCCESS:\n' + out);
  console.log(out);
} catch (err) {
  fs.writeFileSync('test_output.txt', 'ERROR:\nSTDOUT:\n' + (err.stdout || '') + '\nSTDERR:\n' + (err.stderr || '') + '\nMESSAGE:\n' + err.message);
  console.log('Error logged to test_output.txt');
}
