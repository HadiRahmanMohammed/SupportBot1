// Run engine.js in Node against the exported KB and print JSON results for comparison with Python.
const fs = require("fs");
global.window = { CDU_KB: JSON.parse(fs.readFileSync(process.argv[2], "utf8")), fetch: () => {} };
global.Response = class {};
eval(fs.readFileSync(process.argv[3], "utf8"));
const qs = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));
const out = qs.map(([q, prev]) => { const [, d] = [0, window.CDU_ENGINE.chat({ message: q, previous: prev || "" })[1]];
  return [d.type, d.faq ? d.faq.id : (d.options || []).map(o => o.id).join(",")]; });
console.log(JSON.stringify(out));
