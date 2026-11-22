# Proposal

## Why

A reconciliação das unidades de execução (`provisioning.reconcile()`) existe desde o primeiro commit, mas o portal em execução nunca a chama: só os testes a chamam. As specs `container-lifecycle` e `container-driver-kubernetes` prometem reconciliar "ao iniciar e periodicamente", e o código depende disso: o driver Kubernetes deixa para "a reconciliação" recriar Pods sem o container `git` ou com spec divergente (imagem, Secrets de pull), e a documentação manda o operador contar com ela depois de trocar `BASE_IMAGE`, o broker de inferência ou o modo de roteamento. Hoje um container ou Pod que some fica sumido até alguém reprovisionar à mão o sistema.

## What Changes

- O portal passa a reconciliar **logo depois de subir** e depois **periodicamente**, num intervalo configurável (`APPAIFORGE_RECONCILE_INTERVAL`, padrão 300 s; `0` deixa só a passada da subida). A reconciliação roda em segundo plano: não atrasa a subida do portal.
- A reconciliação **não disputa** as operações do próprio portal com um sistema: não age num sistema que o portal está criando, recriando ou removendo naquele momento, e relê o estado do sistema antes de agir, para não recriar o container de um sistema arquivado ou excluído depois de a passada começar.
- **Falha num sistema não interrompe a passada**: um erro inesperado (API do Docker ou do cluster fora do ar, por exemplo) é registrado em log, o estado do sistema não muda e a próxima passada tenta de novo. Uma recriação que falha continua deixando o sistema em erro com o motivo.
- Um sistema que a reconciliação **recria com sucesso** volta a ativo, sem mensagem de erro (antes ficava com o estado que tinha, inclusive erro).
- Republicar a rota de cada sistema a cada passada deixa de reescrever o arquivo de rota do driver Docker quando o conteúdo não mudou (o Traefik não recarrega à toa).
- Efeitos que passam a acontecer de fato, nos dois drivers (já eram o comportamento de `reconcile()`, só que nunca rodavam): container ou Pod ausente é recriado; no Kubernetes, Pod sem o container `git` ou com spec divergente da configuração é recriado (interrompe uma execução do agente em andamento naquele sistema); num portal de produção, sistemas com agente são removidos e ficam em erro; a saúde das conexões de banco de cada sistema é checada a cada passada.
- `provisioning.republish_routes()`, chamada na subida pela change `gateway-api-traefik-subchart` (em andamento, ainda não integrada), fica redundante: a primeira passada da reconciliação republica a rota de todo sistema não arquivado, nos dois drivers. A remoção dessa chamada fica para a integração das duas changes (ver design, D7).

Fora desta change: vários processos do portal reconciliando ao mesmo tempo (o chart e o compose sobem uma réplica só), sistemas presos em "provisionando" por um reinício do portal no meio do provisionamento, e reconciliação de containers individuais dentro de um Pod (continua sendo do kubelet).

## Capabilities

### New Capabilities

(nenhuma)

### Modified Capabilities

- `container-lifecycle`: o requirement "Containers ativos e reconciliados" passa a definir quando a reconciliação roda (logo depois da subida e a cada intervalo configurável), que ela não atrasa a subida, não disputa operações do portal com o mesmo sistema, isola falhas por sistema e devolve a ativo um sistema recriado com sucesso.
- `container-driver-kubernetes`: o requirement "Reconciliação do estado dos Pods" ganha o cenário do Pod divergente da configuração (sem o container `git`, imagem ou Secrets de pull diferentes), recriado pela reconciliação.

## Impact

- **Código do portal**: `provisioning.py` (laço de reconciliação, trava por sistema usada por provisionamento, arquivamento, exclusão e troca da allow-list, isolamento de falhas, volta a ativo), `main.py` (inicia o laço na subida), `config.py` (`reconcile_interval`), `edge.py` (escrita de rota Docker só quando muda).
- **Configuração**: nova `APPAIFORGE_RECONCILE_INTERVAL`; no chart, via `portal.extraEnv`.
- **Testes**: unitários do laço, da trava e do isolamento de falhas; integração com Docker real (container removido por fora é recriado pelo laço). A integração Kubernetes existente já cobre `reconcile()` contra o cluster `kind-appaiforge-dev`.
- **Documentação**: `docs/configuracao.md`, `docs/driver-kubernetes.md`, ADR 0013 (nota de implementação) e docstrings de `reconcile()` e do driver Kubernetes.
