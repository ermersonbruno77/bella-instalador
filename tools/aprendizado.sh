#!/usr/bin/env bash
# Aciona o agente para rodar a consolidação de aprendizado do time.
#
# Por que existe: agente não retém nada entre execuções: o único aprendizado
# possível é reescrever o .md dele. Se isso dependesse do agente lembrar de
# consolidar sozinho, teria o mesmo defeito que existe para corrigir.
#
# Roda diariamente. Se a fila estiver vazia, não incomoda ninguém.
set -euo pipefail

FILA=/opt/{{AGENTE_NAME_LOWERCASE}}/memory/aprendizado/fila.md

# Conta só as entradas (linhas "## AAAA-MM-DD"), não o cabeçalho de exemplo.
# Cuidado: `grep -c` sai com status 1 quando a contagem é zero, mesmo tendo
# impresso "0" certinho. Com `|| echo 0` DENTRO do $(...), as duas saídas se
# juntariam ("0\n0"), e o teste de integer quebraria em silêncio, deixando o
# script seguir e chamar o inject.sh com fila vazia. `|| N=0` FORA do $(...)
# evita a duplicação: só substitui se o grep falhar de verdade (arquivo
# sumiu), nunca por causa do próprio "zero matches".
N=$(grep -cE '^## [0-9]{4}-[0-9]{2}-[0-9]{2} · ' "$FILA" 2>/dev/null) || N=0

[ "$N" -eq 0 ] && exit 0

/opt/{{AGENTE_NAME_LOWERCASE}}/tools/inject.sh "[sistema] Consolidação de aprendizado: a fila em memory/aprendizado/fila.md tem $N lição(ões) ainda não gravadas. Acione a aria-arquivista para ler a fila, escrever cada lição no arquivo do agente que pode quebrá-la, revalidar o YAML de todos os agentes e mover as entradas para consolidadas.md. Depois me diga em uma linha o que foi aprendido hoje, sem inventar item que não estava na fila."
