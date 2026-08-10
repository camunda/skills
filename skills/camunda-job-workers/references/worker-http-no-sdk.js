// Zero-dependency Camunda 8 job worker — Node.js built-ins only.
//
// Copy this file and adapt it; it is a template, not a helper to run as-is.
// At minimum set BASE_URL, AUTH, and JOB_TYPE, and replace the business logic
// marked below. Runs on any Camunda 8.8+ cluster exposing the Zeebe REST API:
//   node worker-http-no-sdk.js
//
// Requires no `package.json` and no `node_modules`. See worker-http-no-sdk.md
// for the API shapes, auth notes, and the limitations vs. the TypeScript SDK.

const http = require('http');
const https = require('https');

const BASE_URL = 'http://localhost:8080';
const AUTH = 'Basic ' + Buffer.from('demo:demo').toString('base64');
const JOB_TYPE = 'your-job-type';          // must match zeebe:taskDefinition type in BPMN

async function request(method, path, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(BASE_URL + path);
    const client = url.protocol === 'https:' ? https : http;
    const opts = {
      hostname: url.hostname,
      port: url.port || (url.protocol === 'https:' ? 443 : 80),
      path: url.pathname + url.search,   // preserve any query string
      method,
      headers: {
        'Authorization': AUTH,
        'Content-Type': 'application/json',
      },
    };
    const req = client.request(opts, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch { resolve(data); }
      });
    });
    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

async function poll() {
  const activation = await request('POST', '/v2/jobs/activation', {
    type: JOB_TYPE,
    maxJobsToActivate: 5,
    timeout: 30000,                        // ms — engine's lease; handler must complete within this window
    worker: 'my-worker',
  });

  const jobs = activation.jobs ?? [];
  for (const job of jobs) {
    try {
      // --- your business logic here ---
      const result = { processedAt: new Date().toISOString() };

      await request('POST', `/v2/jobs/${job.jobKey}/completion`, {
        variables: result,
      });
    } catch (err) {
      // Fail the job — engine will redeliver after retries
      await request('POST', `/v2/jobs/${job.jobKey}/failure`, {
        errorMessage: String(err?.message ?? err),   // non-Error throws stringify cleanly
        retries: Math.max(0, (job.retries ?? 1) - 1), // never go negative (0 → incident)
        retryBackOff: 5000,
      });
    }
  }
}

// Self-scheduling loop: await each poll before the next, so polls never
// overlap, and catch errors so a thrown rejection doesn't crash the process.
async function loop() {
  for (;;) {
    try {
      await poll();
    } catch (err) {
      console.error('poll failed:', err);
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

console.log(`Worker polling for ${JOB_TYPE}...`);
loop();
