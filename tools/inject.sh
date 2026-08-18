#!/usr/bin/env bash
# Injeta um prompt na sessao tmux do agente (mesma via que o bot usa).
#
# POR QUE ESTE ARQUIVO TEM LOG E FILA:
# Uma versao anterior podia ser so `tmux has-session || exit 0`. Sem sessao,
# ela sairia em SILENCIO, com codigo 0, dizendo ao cron que tinha dado certo.
# Nada seria entregue e nada ficaria registrado — e varios automaticos
# dependem deste arquivo (briefing, lembretes, cobranca de projeto, aprendizado,
# relatorio, promessas, monitores). Todos com o mesmo risco: sumir sem deixar
# rastro.
#
# Agora: toda tentativa fica no log, e o que nao pode ser entregue vai pra fila
# em vez de evaporar. Quem estiver vivo depois entrega.
set -u
MSG="${1:-}"
LOG=/opt/{{AGENTE_NAME_LOWERCASE}}-bot/logs/inject.log
FILA=/opt/{{AGENTE_NAME_LOWERCASE}}/.rtk/inject-fila
mkdir -p "$(dirname "$LOG")" "$FILA" 2>/dev/null

carimbo() { date -u +%FT%TZ; }
resumo=$(printf '%s' "$MSG" | head -c 90 | tr '\n' ' ')

if [ -z "$MSG" ]; then
  echo "$(carimbo) RECUSADO mensagem vazia" >> "$LOG"
  exit 2
fi

if ! tmux has-session -t {{AGENTE_NAME_LOWERCASE}} 2>/dev/null; then
  # Nao perde: guarda pra proxima sessao. O nome do arquivo ordena por chegada.
  arq="$FILA/$(date -u +%Y%m%dT%H%M%S)-$$.txt"
  printf '%s' "$MSG" > "$arq"
  echo "$(carimbo) SEM SESSAO, enfileirado em $arq | $resumo" >> "$LOG"
  exit 0
fi

# has-session acima confirma sessao viva NO INSTANTE do check, mas a sessao
# pode morrer no meio (restart do agente cruzando com o inject). Sem checar
# o retorno do send-keys, essa corrida vazava erro cru do tmux pro log de
# quem chamou e a mensagem sumia sem cair na fila, contradizendo o motivo
# deste arquivo existir. Agora tambem enfileira nesse caso.
if ! tmux send-keys -t {{AGENTE_NAME_LOWERCASE}} -l "$MSG" 2>>"$LOG"; then
  arq="$FILA/$(date -u +%Y%m%dT%H%M%S)-$$.txt"
  printf '%s' "$MSG" > "$arq"
  echo "$(carimbo) SESSAO MORREU NO MEIO, enfileirado em $arq | $resumo" >> "$LOG"
  exit 0
fi
sleep 0.4
tmux send-keys -t {{AGENTE_NAME_LOWERCASE}} Enter 2>>"$LOG"
echo "$(carimbo) ENTREGUE | $resumo" >> "$LOG"
