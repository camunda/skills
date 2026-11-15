/**
 * Entry point. `node dist/index.js --stdio` for Claude Desktop / Claude Code / Codex,
 * or `node dist/index.js` for Streamable HTTP on $PORT (default 3001) at /mcp.
 */
import { StdioServerTransport } from "@modelcontextprotocol/server/stdio";
import { createMcpExpressApp } from "@modelcontextprotocol/express";
import { NodeStreamableHTTPServerTransport } from "@modelcontextprotocol/node";
import cors from "cors";
import type { Request, Response } from "express";
import { createServer } from "./src/server/server.js";

async function startHttp() {
  const port = parseInt(process.env.PORT ?? "3001", 10);
  const app = createMcpExpressApp({ host: process.env.HOST ?? "127.0.0.1" });
  app.use(cors());
  app.all("/mcp", async (req: Request, res: Response) => {
    const server = createServer();
    const transport = new NodeStreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    res.on("close", () => {
      transport.close().catch(() => {});
      server.close().catch(() => {});
    });
    try {
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
    } catch (error) {
      console.error("MCP error:", error);
      if (!res.headersSent) res.status(500).json({ jsonrpc: "2.0", error: { code: -32603, message: "Internal server error" }, id: null });
    }
  });
  app.listen(port, () => console.error(`bpmn-studio MCP listening on http://localhost:${port}/mcp`));
}

if (process.argv.includes("--stdio")) {
  await createServer().connect(new StdioServerTransport());
} else {
  await startHttp();
}
