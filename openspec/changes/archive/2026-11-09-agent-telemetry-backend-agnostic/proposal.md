# Proposal

## Why

A instrumentação de telemetria (`agent-telemetry`) usa o SDK OTel de forma vendor-neutral no código, mas tem dois pontos hard-coded a um backend específico (Grafana Tempo/Loki): o endpoint de exportação aponta direto pra ele, e o Debug log do chat consulta a API REST proprietária do Tempo pra reconstruir a árvore de spans. O objetivo do projeto é que o cliente que for implantar o sistema possa escolher seu próprio backend de observabilidade (Grafana, Elastic, ou outro) sem o portal/broker precisarem saber qual foi escolhido — hoje isso não é possível sem mudar código ou perder o Debug log.

## What Changes

- Exportação de traços/logs passa a ir sempre para um **OTel Collector** com endpoint fixo na aplicação; a escolha do backend final (Tempo/Loki/Grafana, Elasticsearch/Kibana/APM, ou outro) passa a ser configuração do Collector (arquivo de config dele), nunca código ou endpoint na aplicação.
- O profile `observability` existente no `deploy/docker-compose.yml` (Tempo/Loki/Grafana) passa a incluir o Collector na frente. Um novo profile de exemplo, `observability-elastic` (Elasticsearch, Kibana, APM Server/Elastic Agent), é adicionado ao lado dele, alimentado pelo mesmo Collector — provando concretamente a troca de backend.
- O Debug log do chat deixa de consultar a API REST do Tempo. Um `SpanProcessor` próprio, adicionado ao mesmo `TracerProvider` que já exporta pro Collector, persiste cada span finalizado numa tabela nova compartilhada entre portal e broker (mesma Postgres que ambos já usam). O Debug log passa a ler dessa tabela, nunca de um backend de observabilidade externo. **BREAKING** (interno): `telemetry_query.py` deixa de falar com a API do Tempo; a função que o Debug log chama muda de implementação.
- A nova tabela de spans ganha limpeza automática por TTL (ex.: 30/90 dias) — política de retenção nova para o projeto, já que `AgentRun`/`RunEventRecord` não têm nenhuma hoje.
- `GateDecision` e `ManagementAudit` continuam não afetados (mesmo non-goal da change anterior).

## Capabilities

### New Capabilities
(nenhuma)

### Modified Capabilities
- `agent-telemetry`: a exportação de traços/logs deixa de assumir um backend específico (passa a ser sempre via um Collector com config própria de destino); o Debug log deixa de depender de uma API de consulta de backend externo e passa a ler de uma tabela própria em Postgres; é adicionado um requisito de retenção/limpeza para essa tabela.

## Impact

- **Código**: `portal/appaiforge/telemetry.py` (adiciona `SpanProcessor` de persistência em Postgres, mantém o `BatchSpanProcessor` de exportação), `portal/appaiforge/services/telemetry_query.py` (reescrito para consultar Postgres em vez da API do Tempo), `portal/appaiforge/models.py` (nova tabela de spans), nova migração, novo job/rotina de limpeza por TTL, `portal/appaiforge/ui/chat.py` (ponto de leitura do Debug log, mesma assinatura).
- **Infra**: `deploy/docker-compose.yml` (Collector no profile `observability` existente, novo profile `observability-elastic`), novos arquivos de config em `deploy/observability/` (config do Collector com exporters pra cada backend de exemplo, config do Elasticsearch/Kibana/APM Server ou Elastic Agent).
- **Testes**: novos testes unitários para o `SpanProcessor`/persistência em Postgres, a limpeza por TTL, e o Debug log lendo de Postgres (substituindo os testes que hoje mockam a API do Tempo em `test_telemetry_query.py`).
