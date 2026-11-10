#!/usr/bin/env node
// Stub da Anthropic Messages API pro teste de ponta a ponta do perfil
// claude-code (task 7.3, change add-claude-code-agent-profile) — mesmo
// racional do spike real (tasks.md 1.1-1.4): sem chave nem custo de API,
// shape real o suficiente pra exercitar o pipeline inteiro (container real,
// shim real, CLI real, harness real, fila/checkpoint reais) de ponta a
// ponta, só o modelo em si que é fabricado.
//
// Primeiro turno (sem tool_result no histórico): texto + tool_use (Bash,
// comando configurável via SPIKE_BASH_COMMAND — escreve algo real em
// /workspace, pra o checkpoint git ter o que commitar).
// Segundo turno: texto final, stop_reason end_turn.
//
// ACHADO (design.md, "Achado crítico da verificação real"): este teste fica
// pulado (@pytest.mark.skip em test_claude_code_e2e.py) porque
// base-image/httpproxy/proxy.py descarta o corpo e os headers de toda
// requisição HTTP absoluta (não-CONNECT) — sem o tool_result chegando de
// volta no corpo, este stub nunca vê hasToolResult()==true e o claude -p
// fica pedindo a mesma ferramenta pra sempre. Quando esse bug for corrigido
// (tarefa separada), remover o skip e este teste deve passar sem nenhuma
// outra mudança.
const http = require("http");
const crypto = require("crypto");

const port = parseInt(process.argv[2] || "18080", 10);
const bashCommand = process.env.SPIKE_BASH_COMMAND || "echo e2e-ok > e2e_marker.txt";

function hasToolResult(messages) {
  for (const msg of messages || []) {
    const content = msg.content;
    if (Array.isArray(content)) {
      for (const block of content) {
        if (block && block.type === "tool_result") return true;
      }
    }
  }
  return false;
}

const server = http.createServer((req, res) => {
  if (req.method !== "POST") {
    res.writeHead(404);
    res.end();
    return;
  }
  let raw = "";
  req.on("data", (c) => (raw += c));
  req.on("end", () => {
    let body = {};
    try {
      body = raw ? JSON.parse(raw) : {};
    } catch (e) {
      body = {};
    }
    const messages = body.messages || [];
    const msgId = "msg_" + crypto.randomBytes(12).toString("hex");
    const model = body.model || "claude-fake";
    const usage = { input_tokens: 100, output_tokens: 20 };

    let contentBlocks, stopReason;
    if (hasToolResult(messages)) {
      contentBlocks = [{ type: "text", text: "Pronto." }];
      stopReason = "end_turn";
    } else {
      contentBlocks = [
        { type: "text", text: "Vou registrar isso." },
        {
          type: "tool_use",
          id: "toolu_" + crypto.randomBytes(12).toString("hex"),
          name: "Bash",
          input: { command: bashCommand },
        },
      ];
      stopReason = "tool_use";
    }

    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
    const emit = (event, data) => {
      res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    };
    emit("message_start", {
      type: "message_start",
      message: {
        id: msgId, type: "message", role: "assistant", model,
        content: [], stop_reason: null, stop_sequence: null,
        usage: { input_tokens: usage.input_tokens, output_tokens: 0 },
      },
    });
    contentBlocks.forEach((block, idx) => {
      if (block.type === "text") {
        emit("content_block_start", { type: "content_block_start", index: idx, content_block: { type: "text", text: "" } });
        emit("content_block_delta", { type: "content_block_delta", index: idx, delta: { type: "text_delta", text: block.text } });
        emit("content_block_stop", { type: "content_block_stop", index: idx });
      } else if (block.type === "tool_use") {
        emit("content_block_start", { type: "content_block_start", index: idx, content_block: { type: "tool_use", id: block.id, name: block.name, input: {} } });
        emit("content_block_delta", { type: "content_block_delta", index: idx, delta: { type: "input_json_delta", partial_json: JSON.stringify(block.input) } });
        emit("content_block_stop", { type: "content_block_stop", index: idx });
      }
    });
    emit("message_delta", { type: "message_delta", delta: { stop_reason: stopReason, stop_sequence: null }, usage: { output_tokens: usage.output_tokens } });
    emit("message_stop", { type: "message_stop" });
    res.end();
  });
});

server.listen(port, "0.0.0.0", () => {
  process.stderr.write(`[fake-anthropic-e2e] listening on 0.0.0.0:${port}\n`);
});
