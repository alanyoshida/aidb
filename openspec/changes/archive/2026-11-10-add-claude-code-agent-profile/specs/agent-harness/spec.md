# Spec Delta

## MODIFIED Requirements

### Requirement: Continuidade de contexto do agente dentro da sessão
O portal SHALL manter o mesmo identificador de sessão do harness em uso ao longo de múltiplos pedidos dentro da mesma sessão de conversa, de forma que o agente retenha o contexto das mensagens anteriores, qualquer que seja o harness do perfil do sistema.

#### Scenario: Agente lembra pedido anterior na mesma sessão
- **WHEN** o editor envia um segundo pedido na mesma sessão de conversa
- **THEN** o agente processa o novo pedido com contexto das mensagens anteriores dessa sessão, sem que o editor precise repeti-las

#### Scenario: Sessões diferentes têm contextos isolados
- **WHEN** o editor alterna entre duas sessões de conversa do mesmo sistema
- **THEN** cada sessão mantém seu próprio contexto de agente, sem interferência entre elas
