const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const out = fs.openSync(path.join(__dirname, "server.log"), "a");
const child = spawn("python", ["run.py"], {
  cwd: __dirname,
  detached: true,
  stdio: ["ignore", out, out],
  windowsHide: true,
});

child.unref();
