# 0031 — Isolação por instalação: o portal só mexe nos containers dele

* Status: aceito
* Data: 2026-11-21
* Decidida em: change `add-production-portal-install` (design D1, D2, D3)
* Complementa: [0030](0030-sistema-so-implantacao-no-portal-de-producao.md)

## Contexto

Sob o driver Docker, os containers de um sistema se chamam `appaiforge-sys-<slug>` (mais os sidecars) e o portal os acha pelo nome. Ao provisionar, ele removia à força o que tivesse esse nome; ao reconciliar, adotava o que encontrasse. Nada dizia a qual instalação o container pertencia. Um portal de produção no mesmo host de um de homologação assumiria, ou apagaria, o container de um sistema de mesmo slug.

## Decisão

1. **Identidade da instalação.** Cada portal grava no primeiro boot um identificador próprio em `portal_instance`, a linha que já fixa o modo de autenticação. Fica no banco, e não numa variável de ambiente, porque arquivos de configuração são copiados entre instalações e o banco não.
2. **Containers com dono.** Os containers que o driver Docker cria levam o rótulo `appaiforge.installation`. Antes de remover, adotar ou executar comandos num container pelo nome, o portal confere o dono:
   - Um container é deste portal se o rótulo é o desta instalação e o sistema é o mesmo.
   - Sem rótulo (anterior a esta decisão), vale o identificador do sistema.
   - Um container de outro dono nunca é removido nem reaproveitado. O sistema fica em erro com o motivo.
3. **Produção em host próprio.** O portal de produção recusa subir num host Docker com containers de outra instalação e lista quais são. A exceção `APPAIFORGE_ALLOW_SHARED_DOCKER_HOST` existe só para a stack de testes que roda os dois portais juntos.

## Alternativas consideradas

- **Prefixo de nome por instalação**, para dois portais conviverem no mesmo host: mexeria no nome de todo container, rede e rota, e os sistemas existentes teriam de ser recriados. Descartada: produção pede isolamento, não convivência.
- **Só a regra de dono, sem checagem no boot**: protege os containers, mas um sistema de produção só falharia quando um slug coincidisse, talvez semanas depois. A checagem no boot falha na instalação, quando ainda dá para trocar de host.
- **Rótulo também nos Pods do driver Kubernetes**: lá cada portal tem o seu namespace, que já isola os Pods.

## Consequências

- Um container gerenciado sem rótulo cujo sistema já não existe no banco conta como de outra instalação, e bloqueia a subida da produção até ser removido. A mensagem diz como conferir.
- Os containers existentes continuam reconhecidos sem recriação e ganham o rótulo na próxima recriação normal.
- No Kubernetes, o isolamento continua dependendo de um namespace por portal.
